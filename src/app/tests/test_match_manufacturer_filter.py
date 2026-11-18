"""Manufacturer pre-filter on item matching (Match step).

Catalog search applies the manufacturer filter inside both rankings (keyword and vector), so it
restricts the candidates to those brands before ranking rather than filtering the top-k after
the fact; that SQL is pinned in test_catalog_search.py. These tests pin:
  1. `build_weighted_candidates(..., manufacturers=...)` threads it through to catalog search.
  2. `reference.get_manufacturers()` returns sorted, de-duped, active names.
"""

from __future__ import annotations

from unittest.mock import patch

from server import databricks_api, reference
from server.config import get_settings

SETTINGS = get_settings()


def test_build_weighted_candidates_threads_manufacturers_into_catalog_search():
    line_item = {"raw_description": "nitrile exam gloves, medium", "uom": "BX", "qty": 100}
    with patch("server.catalog_search.search_catalog", return_value=[]) as search, \
            patch("server.databricks_api.reference.get_item_catalog_rows", return_value={}), \
            patch("server.databricks_api.reference.get_historical_bids_for_items", return_value={}), \
            patch("server.databricks_api.reference.get_purchase_history_for_items", return_value={}), \
            patch("server.databricks_api._general_knowledge_fallback", return_value=None):
        databricks_api.build_weighted_candidates(
            SETTINGS, line_item, customer_id="CUST-1001", manufacturers=["Medline", "BD"],
        )
    _, kwargs = search.call_args
    assert kwargs["manufacturers"] == ["Medline", "BD"]


def test_get_manufacturers_returns_sorted_distinct_active_names():
    names = reference.get_manufacturers()
    assert names == sorted(names), "manufacturers must be sorted"
    assert len(names) == len(set(names)), "manufacturers must be de-duplicated"
    # Seeded synthetic catalog includes these well-known brands.
    assert "3M" in names
    assert "Medline" in names
    assert all(n and n.strip() for n in names), "no blank manufacturer names"
