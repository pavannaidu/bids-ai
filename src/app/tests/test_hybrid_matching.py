"""Confidence-preserving reranking of catalog search candidates (retrieval itself is
tested in test_catalog_search.py)."""

from __future__ import annotations

from unittest.mock import patch

from server import databricks_api
from server.config import get_settings


SETTINGS = get_settings()


def _rank(line_item: dict, hits: list[dict], rows: dict[str, dict]):
    with patch("server.catalog_search.search_catalog", return_value=hits) as search, patch(
        "server.databricks_api.reference.get_item_catalog_rows", return_value=rows,
    ), patch(
        "server.databricks_api.reference.get_historical_bids_for_items", return_value={},
    ), patch(
        "server.databricks_api.reference.get_purchase_history_for_items", return_value={},
    ), patch("server.databricks_api._general_knowledge_fallback", return_value=None):
        ranked = databricks_api.build_weighted_candidates(
            SETTINGS, line_item, customer_id="CUST-1001",
        )
    return search, ranked


def test_given_code_is_added_to_query_and_unique_exact_match_ranks_first():
    line = {
        "raw_description": "peripheral IV catheter winged 20G",
        "given_code": "bd 4521",
        "uom": "BX",
        "qty": 10,
    }
    hits = [
        {"item_code": "SKU-OTHER", "_retrieval_score": 0.98, "_semantic_score": 0.91,
         "description_long": "BD Insyte peripheral IV catheter winged 20G", "manufacturer_name": "BD",
         "category": "IV Supplies", "list_price": 35.0},
        {"item_code": "SKU-EXACT", "manufacturer_item_code": "BD-4521",
         "_retrieval_score": 0.62, "_semantic_score": 0.40,
         "description_long": "BD Insyte peripheral IV catheter winged 20G", "manufacturer_name": "BD",
         "category": "IV Supplies", "list_price": 40.0},
    ]
    rows = {
        code: {**hit, "uom": "BX", "item_size": "20G", "subcategory": "IV Catheters"}
        for code, hit in ((hit["item_code"], hit) for hit in hits)
    }

    search, ranked = _rank(line, hits, rows)

    assert search.call_args.args[1].endswith("bd 4521")
    assert ranked[0]["item_code"] == "SKU-EXACT"
    assert ranked[0]["exact_code_match"] is True
    assert ranked[0]["auto_select_eligible"] is True


def test_hybrid_rrf_score_never_satisfies_semantic_confidence_guard():
    line = {"raw_description": "nitrile exam gloves medium", "given_code": None, "uom": "BX", "qty": 10}
    hits = [{
        "item_code": "SKU-1", "_retrieval_score": 0.99, "_semantic_score": None,
        "description_long": "Kimtech nitrile exam gloves medium 100/BX",
        "manufacturer_name": "Kimberly-Clark", "category": "Exam Gloves", "list_price": 8.0,
    }]
    rows = {"SKU-1": {**hits[0], "uom": "BX", "item_size": "M", "subcategory": "Nitrile"}}

    _search, ranked = _rank(line, hits, rows)

    assert ranked[0]["retrieval_score"] == 0.99
    assert ranked[0]["semantic_score"] is None
    assert ranked[0]["auto_select_eligible"] is False
    assert ranked[0]["guard_reason"] == "confidence_unavailable"


def test_exact_code_match_with_compatibility_warning_requires_review():
    line = {
        "raw_description": "nitrile exam gloves medium",
        "given_code": "KC-100",
        "uom": "BX",
        "qty": 10,
    }
    hits = [{
        "item_code": "SKU-1", "manufacturer_item_code": "KC-100",
        "_retrieval_score": 0.99, "_semantic_score": 0.95,
        "description_long": "Kimtech nitrile exam gloves medium 10 BX/CS",
        "manufacturer_name": "Kimberly-Clark", "category": "Exam Gloves", "list_price": 80.0,
    }]
    rows = {"SKU-1": {**hits[0], "uom": "CS", "item_size": "M", "subcategory": "Nitrile"}}

    _search, ranked = _rank(line, hits, rows)

    assert ranked[0]["exact_code_match"] is True
    assert ranked[0]["auto_select_eligible"] is False
    assert ranked[0]["guard_reason"] == "uom_mismatch"
