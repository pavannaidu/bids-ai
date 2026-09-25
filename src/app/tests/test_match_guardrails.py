"""Workstream B: guardrail-first matching. A candidate is auto_select_eligible
only when its UNBOOSTED semantic score meets the active sensitivity threshold AND
it's hard-compatible, warning-free, and a real catalog hit. The match endpoint
pre-selects only eligible candidates; guarded lines stay pending. No-catalog
document rows render as NO BID.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from server import config, databricks_api, documents
from server.config import get_settings

SETTINGS = get_settings()


@pytest.fixture(autouse=True)
def _reset_sensitivity():
    """Sensitivity is process-local; reset it around each test."""
    config.set_match_sensitivity("balanced")
    yield
    config._runtime_match_sensitivity = None


def _run(line_item, vector_hits, catalog_rows, historical=None, purchased=None):
    with patch("server.databricks_api._vector_search_candidates", return_value=vector_hits), \
            patch("server.databricks_api.reference.get_item_catalog_rows", return_value=catalog_rows), \
            patch("server.databricks_api.reference.get_historical_bids_for_items", return_value=historical or {}), \
            patch("server.databricks_api.reference.get_purchase_history_for_items", return_value=purchased or {}), \
            patch("server.databricks_api._general_knowledge_fallback", return_value=None):
        return databricks_api.build_weighted_candidates(SETTINGS, line_item, customer_id="CUST-1001")


def _gloves(score: float):
    line = {"raw_description": "nitrile exam gloves, medium", "uom": "BX", "qty": 100}
    hits = [{
        "item_code": "SKU-1", "_score": score,
        "description_long": "Kimberly-Clark Kimtech nitrile exam gloves, powder-free, 100/BX, M",
        "manufacturer_name": "Kimberly-Clark", "category": "Exam Gloves", "list_price": 8.0,
    }]
    rows = {"SKU-1": {"category": "Exam Gloves", "subcategory": "Nitrile", "uom": "BX", "item_size": "M",
                     "description_long": hits[0]["description_long"]}}
    return line, hits, rows


def test_below_balanced_threshold_is_not_eligible():
    line, hits, rows = _gloves(0.69)  # balanced = 0.70
    top = _run(line, hits, rows)
    assert top[0]["auto_select_eligible"] is False
    assert top[0]["guard_reason"] == "below_confidence_threshold"


def test_at_balanced_threshold_is_eligible():
    line, hits, rows = _gloves(0.70)
    top = _run(line, hits, rows)
    assert top[0]["auto_select_eligible"] is True
    assert top[0]["guard_reason"] is None


def test_conservative_raises_the_bar():
    """0.72 is eligible under Balanced but guarded under Conservative (0.80)."""
    line, hits, rows = _gloves(0.72)
    assert _run(line, hits, rows)[0]["auto_select_eligible"] is True
    config.set_match_sensitivity("conservative")
    guarded = _run(line, hits, rows)[0]
    assert guarded["auto_select_eligible"] is False
    assert guarded["guard_reason"] == "below_confidence_threshold"


def test_uom_mismatch_never_eligible_even_at_high_score():
    """A soft (UOM) warning blocks auto-select regardless of a strong score, at
    every sensitivity."""
    line = {"raw_description": "nitrile exam gloves, medium", "uom": "BX", "qty": 100}
    hits = [{
        "item_code": "SKU-CS", "_score": 0.95,
        "description_long": "Kimberly-Clark Kimtech nitrile exam gloves, 10 BX/CS, M",
        "manufacturer_name": "Kimberly-Clark", "category": "Exam Gloves", "list_price": 80.0,
    }]
    rows = {"SKU-CS": {"category": "Exam Gloves", "subcategory": "Nitrile", "uom": "CS", "item_size": "M",
                      "description_long": hits[0]["description_long"]}}
    for mode in ("permissive", "balanced", "conservative"):
        config.set_match_sensitivity(mode)
        top = _run(line, hits, rows)[0]
        assert top["auto_select_eligible"] is False, mode
        assert top["guard_reason"] == "uom_mismatch", mode


def test_hard_incompatibility_never_eligible():
    """A wrong-family (isolation gown query vs gloves) hard-incompatible candidate
    is never eligible."""
    line = {"raw_description": "disposable isolation gowns, XL", "uom": "CS", "qty": 40}
    hits = [{
        "item_code": "SKU-GLOVE", "_score": 0.9,
        "description_long": "Kimberly-Clark nitrile exam gloves, 100/BX, M",
        "manufacturer_name": "Kimberly-Clark", "category": "Exam Gloves", "list_price": 8.0,
    }]
    rows = {"SKU-GLOVE": {"category": "Exam Gloves", "subcategory": "Nitrile", "uom": "CS", "item_size": "M",
                         "description_long": hits[0]["description_long"]}}
    top = _run(line, hits, rows)[0]
    assert top["auto_select_eligible"] is False
    assert top["guard_reason"] == "hard_incompatibility"


def test_low_specificity_is_not_eligible():
    line = {"raw_description": "table", "uom": "", "qty": 1}
    hits = [{"item_code": "SKU-T", "_score": 0.9, "description_long": "some table",
             "manufacturer_name": None, "category": "Furniture", "list_price": 5.0}]
    rows = {"SKU-T": {"category": "Furniture", "uom": "", "item_size": None, "description_long": "some table"}}
    top = _run(line, hits, rows)
    # A low-specificity line has no eligible candidate (it may only carry a
    # general-knowledge fallback, which is patched off here).
    assert all(not c.get("auto_select_eligible") for c in top)


# A no_match line + a normal catalog line, to prove the no_match row appears
# (requested description present) but with blank Item/Product/Price cells.
_NO_MATCH_BID = {
    "customer_name": "Test Customer", "bid_id": "bid-1", "solicitation_ref": "REF-1",
    "line_items": [
        {"line_id": "l1", "line_number": 1, "raw_description": "obscure widget", "qty": 2, "uom": "EA",
         "resolution": "no_match", "selected_item_code": None, "proposed_price": None, "candidates": []},
        {"line_id": "l2", "line_number": 2, "raw_description": "nitrile gloves", "qty": 5, "uom": "BX",
         "resolution": "catalog_match", "selected_item_code": "SKU-100001", "proposed_price": 8.0,
         "candidates": [{"item_code": "SKU-100001", "description_long": "KC nitrile gloves",
                         "manufacturer_name": "Kimberly-Clark"}]},
    ],
}


def test_no_match_line_renders_in_pdf():
    pytest.importorskip("reportlab")  # runtime-only dep; skip when absent in tests
    pdf = documents.render_proposal_pdf(_NO_MATCH_BID)
    assert pdf[:4] == b"%PDF"


def test_no_match_line_renders_blank_in_excel():
    pytest.importorskip("openpyxl")
    xlsx = documents.render_customer_submission_excel(_NO_MATCH_BID)
    from io import BytesIO
    from openpyxl import load_workbook
    wb = load_workbook(BytesIO(xlsx))
    sheet = wb.active
    rows = list(sheet.iter_rows(values_only=True))
    # Columns (1-based): Sort, Customer Description, Item #, Catalog Description,
    # Manufacturer, UOM, Customer Quantity, Bid Price, Extended Bid Price, Comments.
    # Find the no_match row by its Customer Description (col index 1).
    no_match_row = next(r for r in rows if r and r[1] == "obscure widget")
    assert not no_match_row[2], "Item # should be blank for a no-match line"
    assert no_match_row[7] is None, "Bid Price should be blank for a no-match line"
    assert no_match_row[8] is None, "Extended Bid Price should be blank for a no-match line"
    assert no_match_row[9] == "No catalog match", "Comments should flag no catalog match"
    # Never renders NO BID anymore.
    cells = [c.value for row in sheet.iter_rows() for c in row if isinstance(c.value, str)]
    assert not any("NO BID" in v for v in cells)


def test_external_quote_header_and_totals():
    """The XLSX uses catalog column names, a Date line, a
    Total Bid Price in the header, and a matching Total row at the bottom."""
    pytest.importorskip("openpyxl")
    bid = dict(_NO_MATCH_BID, due_date="2026-08-01")
    xlsx = documents.render_customer_submission_excel(bid)
    from io import BytesIO
    from openpyxl import load_workbook
    wb = load_workbook(BytesIO(xlsx))
    sheet = wb.active
    all_cells = [c.value for row in sheet.iter_rows() for c in row if c.value is not None]

    # Catalog column names (renamed from the old Line/Item Code/Product set).
    header = next(r for r in sheet.iter_rows(values_only=True) if r and r[0] == "Sort")
    assert list(header)[:10] == [
        "Sort", "Customer Description", "Item #", "Catalog Description",
        "Manufacturer Description", "UOM", "Customer Quantity",
        "Bid Price", "Extended Bid Price", "Comments",
    ]
    # Date line and Total Bid Price label both appear.
    assert any(isinstance(v, str) and v.startswith("Date: 2026-08-01") for v in all_cells)
    assert any(v == "Total Bid Price:" for v in all_cells)
    # Only the catalog line (5 × $8.00) contributes; the no_match line is excluded.
    assert 40.0 in all_cells
