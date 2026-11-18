"""Showcase bids: a few bids at different stages, so a new demo's All Bids list isn't empty.

They were built with the app from the sample solicitations (src/bootstrap/build_showcase_bids.py)
and are kept in _shared_data/showcase_bids.json. ensure_showcase_bids() inserts them only into a
database with no bids yet; from then on they're ordinary bids, and nothing reloads them. On the
way in, every timestamp and due date moves forward by the time since the export, so the newest
bid looks recent and each due date keeps its distance, and the document paths point at the
sample files the seed job writes to this demo's volume.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb

from . import lakebase
from .config import Settings

logger = logging.getLogger("bids")

FIXTURE = Path(__file__).parent / "_shared_data" / "showcase_bids.json"
TABLES = ("bids", "bid_line_items", "bid_requirements")  # parents first
_LOCK = 470131703  # pg advisory lock key, next to reference_seed's
_JSON_COLUMNS = {"documents", "candidates", "owning_teams"}
_TIMESTAMP_COLUMNS = ("created_at", "updated_at", "last_updated_at")


def showcase_rows(settings: Settings, now: datetime | None = None) -> dict[str, list[dict[str, Any]]]:
    """The fixture's rows for each table, shifted to `now` and pointed at this demo's volume."""
    fixture = json.loads(FIXTURE.read_text())
    shift = (now or datetime.now(timezone.utc)) - datetime.fromisoformat(fixture["exported_at"])
    rows: dict[str, list[dict[str, Any]]] = {table: [] for table in TABLES}
    for bid in fixture["bids"]:
        for table in TABLES:
            rows[table] += [_shifted(row, shift) for row in bid[table]]
    for bid in rows["bids"]:
        bid["uploaded_document_path"] = f"{settings.volume_root}/{bid['uploaded_document_path']}"
        bid["documents"] = [{**doc, "path": f"{settings.volume_root}/{doc['path']}"} for doc in bid["documents"]]
    return rows


def _shifted(row: dict[str, Any], shift: timedelta) -> dict[str, Any]:
    row = dict(row)
    for column in _TIMESTAMP_COLUMNS:
        if row.get(column):
            row[column] = datetime.fromisoformat(row[column]) + shift
    if row.get("due_date"):
        row["due_date"] = (date.fromisoformat(row["due_date"]) + timedelta(days=shift.days)).isoformat()
    return row


def ensure_showcase_bids(settings: Settings) -> None:
    try:
        if _load(settings):
            logger.info("Loaded the showcase bids into a database with no bids.")
    except Exception:
        logger.exception("Loading the showcase bids failed; All Bids starts empty.")


def _load(settings: Settings) -> bool:
    rows = showcase_rows(settings)
    with lakebase._connect() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", [_LOCK])
            cur.execute("SELECT EXISTS (SELECT 1 FROM bids) AS has_bids")
            if cur.fetchone()["has_bids"]:
                return False
            for table in TABLES:
                for row in rows[table]:
                    columns = list(row)
                    cur.execute(
                        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                            sql.Identifier(table),
                            sql.SQL(", ").join(map(sql.Identifier, columns)),
                            sql.SQL(", ").join(sql.Placeholder() * len(columns)),
                        ),
                        [Jsonb(row[c]) if c in _JSON_COLUMNS else row[c] for c in columns],
                    )
    return True
