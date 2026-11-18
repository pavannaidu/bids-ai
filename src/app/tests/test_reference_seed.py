"""Reference data seeded directly in Lakebase at startup: deterministic rows, idempotent reseeding
(skipped when unchanged, embeddings kept), and the Lakebase Search index build."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from unittest.mock import patch

from server import reference_seed
from server._shared_data.demo_data import build_reference_tables


def test_reference_tables_are_deterministic_and_complete():
    first = build_reference_tables()
    build_reference_tables()  # consuming the shared RNG in between must not change the next call
    assert build_reference_tables() == first
    assert {name: len(rows) for name, rows in first.items()} == {
        "item_catalog": 119, "historical_bids": 1200, "customer_purchase_history": 900,
        "customers": 20, "divisions": 7,
    }
    for name, columns in reference_seed._COLUMNS.items():
        assert set(columns) <= set(first[name][0]), name


class _Cursor:
    def __init__(self, answers):
        self.calls: list[tuple[str, object]] = []
        self.many: list[tuple[str, list]] = []
        self._answers = answers
        self._row = None
        self._rows: list = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        for needle, answer in self._answers:
            if needle in sql:
                answer = answer() if callable(answer) else answer
                self._rows = answer if isinstance(answer, list) else [answer]
                self._row = self._rows[0] if self._rows else None
                return
        self._rows, self._row = [], None

    def executemany(self, sql, values):
        self.many.append((sql, list(values)))

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _connect_with(cursor):
    class _Conn:
        def cursor(self):
            return cursor

        def transaction(self):
            return nullcontext()

    @contextmanager
    def connect():
        yield _Conn()

    return connect


def test_seed_is_a_no_op_when_the_data_is_unchanged():
    current = reference_seed._data_hash(build_reference_tables())
    cursor = _Cursor([("SELECT data_hash", {"data_hash": current})])
    with patch("server.reference_seed.lakebase._connect", _connect_with(cursor)):
        assert reference_seed._seed() is False
    executed = " ".join(sql for sql, _ in cursor.calls)
    assert "CREATE TABLE IF NOT EXISTS bids_ref.seed_state" in executed
    assert "DROP TABLE" not in executed and "CREATE TABLE IF NOT EXISTS bids_ref.item_catalog" not in executed
    assert not cursor.many


def test_reseed_reloads_every_table_and_keeps_embeddings_of_unchanged_items():
    item = build_reference_tables()["item_catalog"][0]
    kept = [0.25] * 1024
    cursor = _Cursor([
        ("SELECT data_hash", {"data_hash": "stale"}),
        ("to_regclass", {"exists": True}),
        ("SELECT item_code, description_long, embedding", [
            {"item_code": item["item_code"], "description_long": item["description_long"], "embedding": kept},
            {"item_code": "SKU-GONE", "description_long": "old text", "embedding": [0.5] * 1024},
        ]),
    ])
    with patch("server.reference_seed.lakebase._connect", _connect_with(cursor)):
        assert reference_seed._seed() is True
    executed = [sql for sql, _ in cursor.calls]
    drops = [i for i, sql in enumerate(executed) if sql.startswith("DROP TABLE IF EXISTS bids_ref.")]
    create = next(i for i, sql in enumerate(executed) if "CREATE TABLE IF NOT EXISTS bids_ref.item_catalog" in sql)
    assert len(drops) == 5 and max(drops) < create  # derived tables are rebuilt with the current DDL
    inserts = {sql.split()[2]: values for sql, values in cursor.many}
    assert len(inserts["bids_ref.item_catalog"]) == 119 and len(inserts["bids_ref.historical_bids"]) == 1200
    embeddings = [row[-1] for row in inserts["bids_ref.item_catalog"]]
    assert embeddings[0] == kept and embeddings[1:].count(None) == 118
    assert any("INSERT INTO bids_ref.seed_state" in sql for sql, _ in cursor.calls)


def test_native_indexes_are_skipped_without_lakebase_search():
    cursor = _Cursor([("pg_available_extensions", {"n": 0})])
    with patch("server.reference_seed.lakebase._connect", _connect_with(cursor)):
        assert reference_seed._ensure_native_indexes() is False
    assert not any("CREATE EXTENSION" in sql for sql, _ in cursor.calls)


def test_native_indexes_are_built_once_the_catalog_is_embedded():
    built = {"valid": []}

    def valid_indexes():
        rows = [{"relname": name, "amname": amname} for name, (amname, _) in reference_seed._NATIVE_INDEXES.items()]
        result, built["valid"] = built["valid"], rows
        return result

    cursor = _Cursor([
        ("pg_available_extensions", {"n": 2}),
        ("pg_try_advisory_lock", {"locked": True}),
        ("FILTER (WHERE embedding IS NULL)", {"total": 119, "missing": 0}),
        ("FROM pg_index", valid_indexes),
    ])
    with patch("server.reference_seed.lakebase._connect", _connect_with(cursor)):
        assert reference_seed._ensure_native_indexes() is True
    executed = [sql for sql, _ in cursor.calls]
    assert "CREATE EXTENSION IF NOT EXISTS lakebase_text" in executed
    assert "CREATE EXTENSION IF NOT EXISTS lakebase_vector CASCADE" in executed
    assert any("USING lakebase_bm25 (terms) WITH (prefilter = true)" in sql for sql in executed)
    assert any("USING lakebase_ann ((embedding::vector(1024)) vector_cosine_ops)" in sql for sql in executed)
    assert executed.index("SET search_path = public") < executed.index("CREATE EXTENSION IF NOT EXISTS lakebase_text")
    assert executed[-1].startswith("SELECT pg_advisory_unlock")


def test_native_indexes_wait_until_every_item_is_embedded():
    cursor = _Cursor([
        ("pg_available_extensions", {"n": 2}),
        ("pg_try_advisory_lock", {"locked": True}),
        ("FILTER (WHERE embedding IS NULL)", {"total": 119, "missing": 3}),
    ])
    with patch("server.reference_seed.lakebase._connect", _connect_with(cursor)):
        assert reference_seed._ensure_native_indexes() is False
    assert not any("CREATE INDEX" in sql for sql, _ in cursor.calls)


def test_listed_but_not_enabled_lakebase_search_is_not_an_error():
    import psycopg

    class _NotPreloaded(_Cursor):
        def execute(self, sql, params=None):
            if sql.startswith("CREATE EXTENSION"):
                self.calls.append((sql, params))
                raise psycopg.errors.InternalError_("[lakebase_text] lakebase_text must be loaded via shared_preload_libraries.")
            super().execute(sql, params)

    cursor = _NotPreloaded([("pg_available_extensions", {"n": 2}), ("pg_try_advisory_lock", {"locked": True})])
    with patch("server.reference_seed.lakebase._connect", _connect_with(cursor)):
        assert reference_seed._ensure_native_indexes() is False
    assert not any("CREATE INDEX" in sql for sql, _ in cursor.calls)
    assert cursor.calls[-1][0].startswith("SELECT pg_advisory_unlock")


def test_a_changed_table_definition_changes_the_seed_hash():
    tables = build_reference_tables()
    before = reference_seed._data_hash(tables)
    with patch("server.reference_seed._TABLES_DDL", reference_seed._TABLES_DDL + "-- changed\n"):
        assert reference_seed._data_hash(tables) != before
