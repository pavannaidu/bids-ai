"""Hybrid candidate retrieval and confidence-preserving reranking tests."""

from __future__ import annotations

import sys
import types
from dataclasses import replace
from unittest.mock import patch

from server import databricks_api
from server.config import get_settings


SETTINGS = get_settings()


def _response(columns: list[str], rows: list[list[object]]) -> dict:
    return {
        "manifest": {"columns": [{"name": name} for name in columns]},
        "result": {"data_array": rows},
    }


class _HybridIndex:
    def __init__(self, calls: list[dict], ann_fails: bool = False) -> None:
        self.calls = calls
        self.ann_fails = ann_fails

    def similarity_search(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["query_type"] == "ANN":
            if self.ann_fails:
                raise RuntimeError("confidence unavailable")
            return _response(
                ["item_code", "description_long"],
                [
                    ["SKU-1", "BD Insyte IV catheter 20G, 50/BX", 0.84],
                    ["SKU-2", "BD Insyte IV catheter 22G, 50/BX", 0.72],
                ],
            )
        return _response(
            [
                "item_code", "manufacturer_item_code", "competitor_item_code",
                "description_short", "description_long", "manufacturer_name",
                "category", "subcategory", "uom", "pack_size", "item_size", "list_price",
            ],
            [
                ["SKU-1", "BD-4521", None, "IV cath 20G", "BD Insyte IV catheter 20G, 50/BX",
                 "BD", "IV Supplies", "IV Catheters", "BX", "50/BX", "20G", 40.0, 0.91],
                ["SKU-2", None, None, "IV cath 22G", "BD Insyte IV catheter 22G, 50/BX",
                 "BD", "IV Supplies", "IV Catheters", "BX", "50/BX", "22G", 38.0, 0.76],
            ],
        )


def _run_real_search(*, ann_fails: bool = False):
    calls: list[dict] = []
    index = _HybridIndex(calls, ann_fails=ann_fails)
    fake_module = types.ModuleType("databricks.vector_search.client")
    fake_module.VectorSearchClient = lambda **_kwargs: types.SimpleNamespace(
        get_index=lambda _endpoint, _index: index,
    )
    with patch.dict(sys.modules, {"databricks.vector_search.client": fake_module}), patch.dict(
        "os.environ",
        {
            "DATABRICKS_HOST": "https://example.databricks.com",
            "DATABRICKS_CLIENT_ID": "cid",
            "DATABRICKS_CLIENT_SECRET": "secret",
        },
    ):
        hits = databricks_api._vector_search_candidates(
            replace(SETTINGS, search_mode="hybrid"),
            "BD Insyte IV catheter BD-4521",
            manufacturers=["BD"],
            include_semantic_scores=True,
        )
    return calls, hits


def test_hybrid_retrieval_uses_25_candidates_then_filtered_ann_confidence():
    calls, hits = _run_real_search()

    assert len(calls) == 2
    assert calls[0]["query_type"] == "HYBRID"
    assert calls[0]["num_results"] == 25
    assert calls[0]["filters"] == {"manufacturer_name": "BD"}
    assert calls[1]["query_type"] == "ANN"
    assert calls[1]["num_results"] == 2
    assert calls[1]["filters"] == {
        "manufacturer_name": "BD",
        "item_code": ["SKU-1", "SKU-2"],
    }
    assert hits[0]["_retrieval_score"] == 0.91
    assert hits[0]["_semantic_score"] == 0.84


def test_ann_confidence_failure_keeps_hybrid_candidates_visible():
    _calls, hits = _run_real_search(ann_fails=True)
    assert [hit["item_code"] for hit in hits] == ["SKU-1", "SKU-2"]
    assert all(hit["_semantic_score"] is None for hit in hits)


def test_ann_search_mode_is_a_single_query_rollback_path():
    calls: list[dict] = []
    index = _HybridIndex(calls)
    fake_module = types.ModuleType("databricks.vector_search.client")
    fake_module.VectorSearchClient = lambda **_kwargs: types.SimpleNamespace(
        get_index=lambda _endpoint, _index: index,
    )
    with patch.dict(sys.modules, {"databricks.vector_search.client": fake_module}), patch.dict(
        "os.environ",
        {
            "DATABRICKS_HOST": "https://example.databricks.com",
            "DATABRICKS_CLIENT_ID": "cid",
            "DATABRICKS_CLIENT_SECRET": "secret",
        },
    ):
        hits = databricks_api._vector_search_candidates(
            replace(SETTINGS, search_mode="ann"), "IV catheter", include_semantic_scores=True,
        )

    assert len(calls) == 1
    assert calls[0]["query_type"] == "ANN"
    assert hits[0]["_retrieval_score"] == hits[0]["_semantic_score"]


def _rank(line_item: dict, hits: list[dict], rows: dict[str, dict]):
    with patch("server.databricks_api._vector_search_candidates", return_value=hits) as search, patch(
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
    assert search.call_args.kwargs["include_semantic_scores"] is True
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
