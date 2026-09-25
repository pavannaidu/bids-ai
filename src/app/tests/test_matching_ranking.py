"""Regression tests for the P0 matching/ranking guardrails: hard compatibility
checks (product family, clinical/ASTM level) must prevent a semantically
weaker-but-wrong-family candidate from outranking a correct one regardless of
purchase/bid history, and the history boost itself must be bounded so it can
only break near-ties, never flip a large semantic gap. Soft mismatches
(UOM/size/gauge) stay visible but flagged and penalized, not excluded.
"""

from __future__ import annotations

from unittest.mock import patch

from server import databricks_api
from server.config import get_settings

SETTINGS = get_settings()


def _mocked(vector_hits, catalog_rows, historical=None, purchased=None):
    return (
        patch("server.databricks_api._vector_search_candidates", return_value=vector_hits),
        patch("server.databricks_api.reference.get_item_catalog_rows", return_value=catalog_rows),
        patch("server.databricks_api.reference.get_historical_bids_for_items", return_value=historical or {}),
        patch("server.databricks_api.reference.get_purchase_history_for_items", return_value=purchased or {}),
    )


def _run(line_item, vector_hits, catalog_rows, historical=None, purchased=None):
    patches = _mocked(vector_hits, catalog_rows, historical, purchased)
    with patches[0], patches[1], patches[2], patches[3]:
        return databricks_api.build_weighted_candidates(SETTINGS, line_item, customer_id="CUST-1001")


def test_isolation_gown_never_outranked_by_gloves_with_history():
    line_item = {"raw_description": "Disp isolation gowns, fluid resistant, XL", "uom": "CS", "qty": 45}
    hits = [
        {
            "item_code": "SKU-GLOVE-1", "_score": 0.62,
            "description_long": "Kimberly-Clark Kimtech nitrile exam gloves, powder-free, textured fingertips, 100/BX, M",
            "manufacturer_name": "Kimberly-Clark", "category": "Exam Gloves", "list_price": 8.0,
        },
        {
            "item_code": "SKU-GOWN-1", "_score": 0.58,
            "description_long": "Medline AAMI L2 fluid-resistant isolation gown, elastic cuff, 10/CS, XL",
            "manufacturer_name": "Medline", "category": "Personal Protection", "list_price": 60.0,
        },
    ]
    catalog_rows = {
        "SKU-GLOVE-1": {"category": "Exam Gloves", "subcategory": "Nitrile", "uom": "BX", "item_size": "M",
                       "description_long": hits[0]["description_long"]},
        "SKU-GOWN-1": {"category": "Personal Protection", "subcategory": "Isolation Gowns", "uom": "CS", "item_size": "XL",
                      "description_long": hits[1]["description_long"]},
    }
    # The customer has bought the (wrong-family) gloves before — under the old
    # additive +0.15 boost this alone was enough to outrank the gown.
    purchased = {"SKU-GLOVE-1": [{"last_purchase_date": "2026-01-01", "last_price_paid": 7.5}]}

    top = _run(line_item, hits, catalog_rows, purchased=purchased)
    assert top[0]["item_code"] == "SKU-GOWN-1"
    glove = next(c for c in top if c["item_code"] == "SKU-GLOVE-1")
    assert glove["compatible"] is False
    assert glove["review_flag"]


def test_iv_admin_set_never_outranked_by_blood_tubes_with_history():
    line_item = {"raw_description": "IV admin sets w/ needle-free connector", "uom": "CS", "qty": 40}
    hits = [
        {
            "item_code": "SKU-TUBE-1", "_score": 0.60,
            "description_long": "BD Vacutainer blood collection tube, EDTA additive, 100/BX, 2mL",
            "manufacturer_name": "BD", "category": "Lab Supplies", "list_price": 20.0,
        },
        {
            "item_code": "SKU-IVSET-1", "_score": 0.55,
            "description_long": "ICU Medical Clearlink IV administration set, needle-free connector, 50/CS",
            "manufacturer_name": "ICU Medical", "category": "IV Supplies", "list_price": 100.0,
        },
    ]
    catalog_rows = {
        "SKU-TUBE-1": {"category": "Lab Supplies", "subcategory": "Blood Collection Tubes", "uom": "BX", "item_size": "2mL",
                      "description_long": hits[0]["description_long"]},
        "SKU-IVSET-1": {"category": "IV Supplies", "subcategory": "IV Administration Sets", "uom": "CS", "item_size": None,
                       "description_long": hits[1]["description_long"]},
    }
    # Won 2 of 3 prior bids on the (wrong-family) tube — old scheme boosted
    # this above the admin set.
    historical = {"SKU-TUBE-1": [{"outcome": "won"}, {"outcome": "won"}, {"outcome": "lost"}]}

    top = _run(line_item, hits, catalog_rows, historical=historical)
    assert top[0]["item_code"] == "SKU-IVSET-1"
    tube = next(c for c in top if c["item_code"] == "SKU-TUBE-1")
    assert tube["compatible"] is False
    assert tube["review_flag"]


def test_astm_level_3_mask_never_outranked_by_level_1_with_history():
    line_item = {"raw_description": "ASTM level 3 fluid-resistant surgical mask, ear loop", "uom": "BX", "qty": 50}
    hits = [
        {
            "item_code": "SKU-MASK-L1", "_score": 0.66,
            "description_long": "Halyard Fluidshield ASTM level 1 procedure face mask, ear loop, 50/BX",
            "manufacturer_name": "Halyard", "category": "Face Masks", "list_price": 6.0,
        },
        {
            "item_code": "SKU-MASK-L3", "_score": 0.60,
            "description_long": "Halyard Fluidshield ASTM level 3 fluid-resistant surgical mask, ear loop, 50/BX",
            "manufacturer_name": "Halyard", "category": "Face Masks", "list_price": 9.0,
        },
    ]
    catalog_rows = {
        "SKU-MASK-L1": {"category": "Face Masks", "subcategory": "Level 1", "uom": "BX", "item_size": None,
                       "description_long": hits[0]["description_long"]},
        "SKU-MASK-L3": {"category": "Face Masks", "subcategory": "Level 3", "uom": "BX", "item_size": None,
                       "description_long": hits[1]["description_long"]},
    }
    purchased = {"SKU-MASK-L1": [{"last_purchase_date": "2026-01-01", "last_price_paid": 5.5}]}

    top = _run(line_item, hits, catalog_rows, purchased=purchased)
    assert top[0]["item_code"] == "SKU-MASK-L3"
    level1 = next(c for c in top if c["item_code"] == "SKU-MASK-L1")
    assert level1["compatible"] is False
    assert "level" in level1["review_flag"].lower()


def test_bounded_boost_cannot_flip_a_large_semantic_gap():
    line_item = {"raw_description": "premium wound care dressing kit", "uom": "BX", "qty": 10}
    hits = [
        {"item_code": "SKU-STRONG", "_score": 0.85, "description_long": "Strong semantic match dressing kit",
         "manufacturer_name": None, "category": "Wound Care", "list_price": 40.0},
        {"item_code": "SKU-WEAK", "_score": 0.56, "description_long": "Weak semantic match dressing kit",
         "manufacturer_name": None, "category": "Wound Care", "list_price": 40.0},
    ]
    catalog_rows = {
        "SKU-STRONG": {"category": "Wound Care", "subcategory": "Dressing Kits", "uom": "BX", "item_size": None,
                      "description_long": hits[0]["description_long"]},
        "SKU-WEAK": {"category": "Wound Care", "subcategory": "Dressing Kits", "uom": "BX", "item_size": None,
                    "description_long": hits[1]["description_long"]},
    }
    # Maximal history boost on the weak candidate: purchased + 3 won bids.
    purchased = {"SKU-WEAK": [{"last_purchase_date": "2026-01-01", "last_price_paid": 39.0}]}
    historical = {"SKU-WEAK": [{"outcome": "won"}, {"outcome": "won"}, {"outcome": "won"}]}

    top = _run(line_item, hits, catalog_rows, historical=historical, purchased=purchased)
    assert top[0]["item_code"] == "SKU-STRONG"


def test_bounded_boost_can_break_a_near_tie():
    line_item = {"raw_description": "premium wound care dressing kit", "uom": "BX", "qty": 10}
    hits = [
        {"item_code": "SKU-A", "_score": 0.58, "description_long": "Dressing kit option A",
         "manufacturer_name": None, "category": "Wound Care", "list_price": 40.0},
        {"item_code": "SKU-B", "_score": 0.56, "description_long": "Dressing kit option B",
         "manufacturer_name": None, "category": "Wound Care", "list_price": 40.0},
    ]
    catalog_rows = {
        "SKU-A": {"category": "Wound Care", "subcategory": "Dressing Kits", "uom": "BX", "item_size": None,
                 "description_long": hits[0]["description_long"]},
        "SKU-B": {"category": "Wound Care", "subcategory": "Dressing Kits", "uom": "BX", "item_size": None,
                 "description_long": hits[1]["description_long"]},
    }
    purchased = {"SKU-B": [{"last_purchase_date": "2026-01-01", "last_price_paid": 39.0}]}
    historical = {"SKU-B": [{"outcome": "won"}, {"outcome": "won"}, {"outcome": "won"}]}

    top = _run(line_item, hits, catalog_rows, historical=historical, purchased=purchased)
    assert top[0]["item_code"] == "SKU-B"


def test_uom_mismatch_stays_visible_but_flagged_and_penalized():
    line_item = {"raw_description": "nitrile exam gloves, size L", "uom": "BX", "qty": 100}
    hits = [
        {
            "item_code": "SKU-GLOVE-CASE", "_score": 0.70,
            "description_long": "Kimberly-Clark Kimtech nitrile exam gloves, powder-free, textured fingertips, 10 BX/CS, L",
            "manufacturer_name": "Kimberly-Clark", "category": "Exam Gloves", "list_price": 80.0,
        },
        {
            "item_code": "SKU-GLOVE-BOX", "_score": 0.70,
            "description_long": "Kimberly-Clark Kimtech nitrile exam gloves, powder-free, textured fingertips, 100/BX, L",
            "manufacturer_name": "Kimberly-Clark", "category": "Exam Gloves", "list_price": 8.0,
        },
    ]
    catalog_rows = {
        "SKU-GLOVE-CASE": {"category": "Exam Gloves", "subcategory": "Nitrile", "uom": "CS", "item_size": "L",
                          "description_long": hits[0]["description_long"]},
        "SKU-GLOVE-BOX": {"category": "Exam Gloves", "subcategory": "Nitrile", "uom": "BX", "item_size": "L",
                         "description_long": hits[1]["description_long"]},
    }

    top = _run(line_item, hits, catalog_rows)
    codes = {c["item_code"] for c in top}
    assert codes == {"SKU-GLOVE-CASE", "SKU-GLOVE-BOX"}

    case = next(c for c in top if c["item_code"] == "SKU-GLOVE-CASE")
    box = next(c for c in top if c["item_code"] == "SKU-GLOVE-BOX")
    assert case["compatible"] is True  # not excluded — same product family, just a pack-size mismatch
    assert case["review_flag"] and "UOM" in case["review_flag"]
    assert box["review_flag"] is None
    assert box["score"] > case["score"]
    assert top[0]["item_code"] == "SKU-GLOVE-BOX"


def test_size_synonyms_do_not_false_flag_as_mismatched():
    """Live-testing bug: 'medium' (free-text) and 'M' (catalog item_size) are
    the same size, but a naive string comparison flagged them as a mismatch."""
    line_item = {"raw_description": "nitrile exam gloves, powder free, medium", "uom": "BX", "qty": 100}
    hits = [
        {
            "item_code": "SKU-GLOVE-M", "_score": 0.75,
            "description_long": "Kimberly-Clark Kimtech nitrile exam gloves, powder-free, textured fingertips, 100/BX, M",
            "manufacturer_name": "Kimberly-Clark", "category": "Exam Gloves", "list_price": 8.0,
        },
    ]
    catalog_rows = {
        "SKU-GLOVE-M": {"category": "Exam Gloves", "subcategory": "Nitrile", "uom": "BX", "item_size": "M",
                       "description_long": hits[0]["description_long"]},
    }

    top = _run(line_item, hits, catalog_rows)
    assert top[0]["review_flag"] is None
    assert top[0]["score"] == top[0]["semantic_score"]  # no soft penalty applied
