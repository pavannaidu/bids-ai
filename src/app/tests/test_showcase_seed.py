"""Showcase bids loaded into a new demo: the shipped fixture is consistent with the schema, the
samples and the reference data; loading shifts its dates and paths; and it only ever loads into a
database with no bids."""

from __future__ import annotations

import json
import re
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from psycopg.types.json import Jsonb

from server import lakebase, showcase_seed
from server._shared_data.demo_data import build_reference_tables
from server._shared_data.sample_documents import SAMPLE_DOCUMENTS
from server.config import get_settings

EXPORTED_AT = datetime(2026, 11, 18, 5, 0, tzinfo=timezone.utc)


def _tiny_fixture(tmp_path):
    path = tmp_path / "showcase_bids.json"
    path.write_text(json.dumps({
        "exported_at": EXPORTED_AT.isoformat(),
        "bids": [{
            "bids": [{
                "bid_id": "bid-1", "status": "pending_review", "due_date": "2026-11-30",
                "created_at": "2026-11-14T02:00:00+00:00", "updated_at": "2026-11-14T03:00:00+00:00",
                "uploaded_document_path": "sample_bid_documents/A.pdf",
                "documents": [{"doc_id": "doc-1", "file_name": "A.pdf", "path": "sample_bid_documents/A.pdf"}],
            }],
            "bid_line_items": [{"line_id": "line-1", "bid_id": "bid-1", "candidates": [{"item_code": "X"}],
                                "updated_at": "2026-11-14T03:00:00+00:00"}],
            "bid_requirements": [{"requirement_id": "req-1", "bid_id": "bid-1", "owning_teams": ["Legal"],
                                  "last_updated_at": None, "updated_at": "2026-11-14T02:30:00+00:00"}],
        }],
    }))
    return path


def test_loading_moves_dates_forward_and_points_documents_at_this_volume(tmp_path):
    settings = get_settings()
    now = EXPORTED_AT + timedelta(days=30, hours=5)
    with patch.object(showcase_seed, "FIXTURE", _tiny_fixture(tmp_path)):
        rows = showcase_seed.showcase_rows(settings, now=now)
    bid = rows["bids"][0]
    assert bid["created_at"] == datetime(2026, 12, 14, 7, 0, tzinfo=timezone.utc)
    assert bid["due_date"] == "2026-12-30"  # same distance from the bid's creation
    assert rows["bid_line_items"][0]["updated_at"] == datetime(2026, 12, 14, 8, 0, tzinfo=timezone.utc)
    assert rows["bid_requirements"][0]["last_updated_at"] is None
    assert bid["uploaded_document_path"] == f"{settings.volume_root}/sample_bid_documents/A.pdf"
    assert bid["documents"][0]["path"] == f"{settings.volume_root}/sample_bid_documents/A.pdf"


class _Cursor:
    def __init__(self, has_bids):
        self.has_bids = has_bids
        self.inserts: list[tuple[str, list]] = []
        self._row = None

    def execute(self, query, params=None):
        text = query if isinstance(query, str) else query.as_string(None)
        self._row = {"has_bids": self.has_bids} if "has_bids" in text else None
        if text.startswith("INSERT"):
            self.inserts.append((text, params))

    def fetchone(self):
        return self._row

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


def test_showcase_loads_into_a_database_without_bids(tmp_path):
    cursor = _Cursor(has_bids=False)
    with patch.object(showcase_seed, "FIXTURE", _tiny_fixture(tmp_path)), \
            patch("server.showcase_seed.lakebase._connect", _connect_with(cursor)):
        assert showcase_seed._load(get_settings()) is True
    tables = [re.match(r'INSERT INTO "(\w+)"', text).group(1) for text, _ in cursor.inserts]
    assert tables == ["bids", "bid_line_items", "bid_requirements"]  # parents first
    documents = dict(zip(re.findall(r'"(\w+)"', cursor.inserts[0][0])[1:], cursor.inserts[0][1]))["documents"]
    assert isinstance(documents, Jsonb)


def test_showcase_never_loads_over_existing_bids(tmp_path):
    cursor = _Cursor(has_bids=True)
    with patch.object(showcase_seed, "FIXTURE", _tiny_fixture(tmp_path)), \
            patch("server.showcase_seed.lakebase._connect", _connect_with(cursor)):
        assert showcase_seed._load(get_settings()) is False
    assert not cursor.inserts


def test_shipped_showcase_matches_the_schema_samples_and_reference_data():
    rows = showcase_seed.showcase_rows(get_settings())
    bids = rows["bids"]
    assert len(bids) >= 3
    assert len({b["status"] for b in bids}) == len(bids)  # one bid per stage
    table_columns = {
        table: set(re.findall(r"^\s+(\w+)\s+[A-Z]", body, re.M))
        for table, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", lakebase._SCHEMA_SQL, re.S)
    }
    for table in showcase_seed.TABLES:
        for row in rows[table]:
            assert set(row) <= table_columns[table], (table, set(row) - table_columns[table])
    bid_ids = {b["bid_id"] for b in bids}
    assert {r["bid_id"] for r in rows["bid_line_items"] + rows["bid_requirements"]} <= bid_ids
    samples = {d.file_name for d in SAMPLE_DOCUMENTS}
    customers = {c["customer_id"] for c in build_reference_tables()["customers"]}
    volume = get_settings().volume_root
    for bid in bids:
        assert bid["customer_id"] in customers
        for doc in bid["documents"]:
            assert doc["file_name"] in samples and doc["path"] == f"{volume}/sample_bid_documents/{doc['file_name']}"
    emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", showcase_seed.FIXTURE.read_text()))
    assert emails <= {"reviewer@example.com"}
