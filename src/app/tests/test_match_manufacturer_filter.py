"""Manufacturer pre-filter on item matching (Match step).

Databricks Vector Search accepts a `filters=` dict applied BEFORE the ANN
search, so passing a manufacturer restricts the semantic ranking to that brand's
catalog items rather than filtering the top-k after the fact. These tests pin:
  1. `_vector_search_candidates(..., manufacturer=...)` passes the right
     `filters={"manufacturer_name": ...}` to the index (and None when unset).
  2. `build_weighted_candidates(..., manufacturer=...)` threads it through.
  3. `reference.get_manufacturers()` returns sorted, de-duped, active names.

The Vector Search SDK isn't installed under tests, so #1 stubs the SDK's
`VectorSearchClient` and asserts on the recorded `similarity_search` kwargs.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import patch

from server import databricks_api, reference
from server.config import get_settings

SETTINGS = get_settings()


class _FakeIndex:
    def __init__(self, recorder: dict) -> None:
        self._recorder = recorder

    def similarity_search(self, **kwargs):
        self._recorder.update(kwargs)
        # Minimal well-formed Vector Search response shape.
        return {
            "manifest": {"columns": [
                {"name": "item_code"}, {"name": "description_long"},
                {"name": "manufacturer_name"}, {"name": "category"}, {"name": "list_price"},
            ]},
            "result": {"data_array": [["SKU-100001", "3M mask", "3M", "Face Masks", 6.0, 0.71]]},
        }


class _FakeClient:
    def __init__(self, recorder: dict) -> None:
        self._recorder = recorder

    def get_index(self, _endpoint, _index):
        return _FakeIndex(self._recorder)


def _run_vector_search(manufacturers):
    recorder: dict = {}
    fake_module = types.ModuleType("databricks.vector_search.client")
    fake_module.VectorSearchClient = lambda **_kw: _FakeClient(recorder)
    with patch.dict(sys.modules, {"databricks.vector_search.client": fake_module}), \
            patch.dict("os.environ", {
                "DATABRICKS_HOST": "https://example.databricks.com",
                "DATABRICKS_CLIENT_ID": "cid",
                "DATABRICKS_CLIENT_SECRET": "secret",
            }):
        hits = databricks_api._vector_search_candidates(
            SETTINGS, "surgical mask", num_results=8, manufacturers=manufacturers,
        )
    return recorder, hits


def test_single_manufacturer_becomes_a_bare_string_filter():
    recorder, hits = _run_vector_search(["3M"])
    assert recorder["filters"] == {"manufacturer_name": "3M"}
    assert recorder["num_results"] == 8
    assert recorder["query_type"] == "HYBRID"
    assert "manufacturer_item_code" in recorder["columns"]
    assert "competitor_item_code" in recorder["columns"]
    assert "uom" in recorder["columns"]
    assert "pack_size" in recorder["columns"]
    assert "item_size" in recorder["columns"]
    assert hits and hits[0]["item_code"] == "SKU-100001"
    assert hits[0]["_score"] == 0.71


def test_multiple_manufacturers_become_a_list_filter_match_any():
    recorder, _ = _run_vector_search(["3M", "Medline"])
    # Vector Search treats a list value as match-ANY.
    assert recorder["filters"] == {"manufacturer_name": ["3M", "Medline"]}


def test_no_manufacturer_sends_null_filter():
    recorder, _ = _run_vector_search([])
    assert recorder["filters"] is None
    recorder2, _ = _run_vector_search(None)
    assert recorder2["filters"] is None


def test_blank_manufacturer_names_are_ignored():
    recorder, _ = _run_vector_search(["", "  ", "Medline"])
    assert recorder["filters"] == {"manufacturer_name": "Medline"}


def test_build_weighted_candidates_threads_manufacturers_into_vector_search():
    line_item = {"raw_description": "nitrile exam gloves, medium", "uom": "BX", "qty": 100}
    with patch("server.databricks_api._vector_search_candidates", return_value=[]) as vs, \
            patch("server.databricks_api.reference.get_item_catalog_rows", return_value={}), \
            patch("server.databricks_api.reference.get_historical_bids_for_items", return_value={}), \
            patch("server.databricks_api.reference.get_purchase_history_for_items", return_value={}), \
            patch("server.databricks_api._general_knowledge_fallback", return_value=None):
        databricks_api.build_weighted_candidates(
            SETTINGS, line_item, customer_id="CUST-1001", manufacturers=["Medline", "BD"],
        )
    # The manufacturers must reach the Vector Search call as a keyword arg.
    _, kwargs = vs.call_args
    assert kwargs["manufacturers"] == ["Medline", "BD"]


def test_get_manufacturers_returns_sorted_distinct_active_names():
    names = reference.get_manufacturers()
    assert names == sorted(names), "manufacturers must be sorted"
    assert len(names) == len(set(names)), "manufacturers must be de-duplicated"
    # Seeded synthetic catalog includes these well-known brands.
    assert "3M" in names
    assert "Medline" in names
    assert all(n and n.strip() for n in names), "no blank manufacturer names"
