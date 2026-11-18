from __future__ import annotations

from unittest.mock import patch

from server import lakebase


def test_catalog_lookup_reads_explicit_columns_from_bids_ref():
    rows = [{"item_code": "SKU-100001", "list_price": 8.17}]
    with patch("server.lakebase._ref_query", return_value=rows) as query:
        result = lakebase.get_item_catalog_rows(["SKU-100001"])

    sql, params = query.call_args.args
    # Search columns (terms, the 1024-d embedding) never leave the database on this path.
    assert sql.startswith("SELECT item_code, manufacturer_name,") and "embedding" not in sql
    assert "FROM {ref}.item_catalog WHERE item_code = ANY(%s)" in sql
    assert params == [["SKU-100001"]]
    assert result["SKU-100001"]["list_price"] == 8.17


def test_history_lookup_groups_rows_by_item_code():
    rows = [
        {"item_code": "SKU-100001", "submitted_price": 7.90},
        {"item_code": "SKU-100001", "submitted_price": 8.00},
    ]
    with patch("server.lakebase._ref_query", return_value=rows) as query:
        result = lakebase.get_historical_bids_for_items(["SKU-100001"], "CUST-1001")

    sql, params = query.call_args.args
    assert "WHERE item_code IN (%s) AND customer_id = %s" in sql
    assert params == ["SKU-100001", "CUST-1001"]
    assert len(result["SKU-100001"]) == 2


def test_reference_queries_target_the_fixed_bids_ref_schema():
    class _Cursor:
        def execute(self, sql, params):
            self.sql = sql

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    cursor = _Cursor()

    class _Conn:
        def cursor(self):
            return cursor

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    with patch("server.lakebase._connect", return_value=_Conn()):
        lakebase._ref_query("SELECT * FROM {ref}.customers")
    assert cursor.sql == "SELECT * FROM bids_ref.customers"
