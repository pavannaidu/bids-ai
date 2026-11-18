"""Reference data in Lakebase, created and seeded by the app itself at startup.

The item catalog, historical bids, customer purchase history, customers and divisions live in
the `bids_ref` schema of the demo's own Lakebase database. Setup creates the schema; the app
creates and owns the tables in it (startup runs as its service principal), and the rows come
straight from the synthetic generators in _shared_data/demo_data.py; nothing is synced from the
lakehouse. ensure_reference_data():
  1. creates the tables (IF NOT EXISTS);
  2. reseeds them in one transaction only when the generated data changed (its hash is kept in
     seed_state), so restarts and redeploys are no-ops;
  3. embeds catalog descriptions that have no embedding yet (databricks-gte-large-en, 1024-d);
  4. when Lakebase Search is enabled on the project, installs lakebase_text and lakebase_vector
     and builds the native BM25 and vector indexes, after the data is in (BM25 needs rows).
Nothing here blocks startup: on failure the app still serves, and catalog search degrades
(plain Postgres ranking instead of the native indexes, or keywords only without embeddings).
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import psycopg

from . import lakebase
from .config import Settings

logger = logging.getLogger("bids")

REF = lakebase.REF_SCHEMA
_SEED_LOCK = 470131701  # pg advisory lock keys: one instance seeds / builds indexes at a time
_INDEX_LOCK = 470131702

_COLUMNS: dict[str, tuple[str, ...]] = {
    "item_catalog": (
        "item_code", "manufacturer_name", "manufacturer_item_code", "competitor_item_code",
        "description_short", "description_long", "category", "subcategory", "uom", "pack_size",
        "item_size", "list_price", "is_active",
    ),
    "historical_bids": (
        "historical_bid_id", "customer_id", "division_id", "item_code", "qty", "submitted_price",
        "outcome", "competitor_price_observed", "submitted_date",
    ),
    "customer_purchase_history": (
        "purchase_history_id", "customer_id", "division_id", "item_code", "last_price_paid",
        "last_purchase_date", "cumulative_qty",
    ),
    "customers": ("customer_id", "customer_name", "division_id", "customer_type", "region"),
    "divisions": ("division_id", "division_name", "vertical", "capacity_constrained"),
}

_STATE_DDL = f"""
CREATE SCHEMA IF NOT EXISTS {REF};
CREATE TABLE IF NOT EXISTS {REF}.seed_state (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    data_hash TEXT NOT NULL,
    seeded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# The reference tables hold derived data only, so a changed definition is applied by dropping and
# recreating them (the hash covers this DDL as well as the rows).
_TABLES_DDL = f"""
CREATE TABLE IF NOT EXISTS {REF}.item_catalog (
    item_code TEXT PRIMARY KEY,
    manufacturer_name TEXT,
    manufacturer_item_code TEXT,
    competitor_item_code TEXT,
    description_short TEXT,
    description_long TEXT,
    category TEXT,
    subcategory TEXT,
    uom TEXT,
    pack_size TEXT,
    item_size TEXT,
    list_price DOUBLE PRECISION,
    is_active BOOLEAN,
    -- Keyword search covers what a bid line can name: brand, descriptions and product codes.
    -- 'simple' keeps every token, including size letters (S, M, L) that 'english' drops as stopwords.
    terms TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple',
        coalesce(manufacturer_name, '') || ' ' || coalesce(description_short, '') || ' ' ||
        coalesce(description_long, '') || ' ' || item_code || ' ' ||
        coalesce(manufacturer_item_code, '') || ' ' || coalesce(competitor_item_code, ''))) STORED,
    embedding REAL[] CHECK (embedding IS NULL OR cardinality(embedding) = 1024)
);
CREATE INDEX IF NOT EXISTS item_catalog_terms ON {REF}.item_catalog USING gin (terms);
CREATE TABLE IF NOT EXISTS {REF}.historical_bids (
    historical_bid_id TEXT PRIMARY KEY,
    customer_id TEXT,
    division_id TEXT,
    item_code TEXT,
    qty BIGINT,
    submitted_price DOUBLE PRECISION,
    outcome TEXT,
    competitor_price_observed DOUBLE PRECISION,
    submitted_date TEXT
);
CREATE INDEX IF NOT EXISTS historical_bids_item ON {REF}.historical_bids (item_code);
CREATE TABLE IF NOT EXISTS {REF}.customer_purchase_history (
    purchase_history_id TEXT PRIMARY KEY,
    customer_id TEXT,
    division_id TEXT,
    item_code TEXT,
    last_price_paid DOUBLE PRECISION,
    last_purchase_date TEXT,
    cumulative_qty BIGINT
);
CREATE INDEX IF NOT EXISTS purchase_history_item ON {REF}.customer_purchase_history (item_code);
CREATE TABLE IF NOT EXISTS {REF}.customers (
    customer_id TEXT PRIMARY KEY,
    customer_name TEXT,
    division_id TEXT,
    customer_type TEXT,
    region TEXT
);
CREATE TABLE IF NOT EXISTS {REF}.divisions (
    division_id TEXT PRIMARY KEY,
    division_name TEXT,
    vertical TEXT,
    capacity_constrained BOOLEAN
);
"""

# Lakebase Search indexes, as in the reference implementation: BM25 over the keyword terms
# (prefilter lets WHERE clauses run inside the index scan) and ANN over the cosine distance.
_NATIVE_INDEXES = {
    "item_catalog_bm25": (
        "lakebase_bm25",
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS item_catalog_bm25 ON {REF}.item_catalog "
        "USING lakebase_bm25 (terms) WITH (prefilter = true)",
    ),
    "item_catalog_cosine": (
        "lakebase_ann",
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS item_catalog_cosine ON {REF}.item_catalog "
        "USING lakebase_ann ((embedding::vector(1024)) vector_cosine_ops)",
    ),
}

_native_ready = False


def native_search_ready() -> bool:
    """True once this process has confirmed both Lakebase Search indexes are valid."""
    return _native_ready


def ensure_reference_data(settings: Settings) -> None:
    global _native_ready
    try:
        if _seed():
            logger.info("Reference data seeded into %s.", REF)
    except Exception:
        logger.exception("Reference data setup failed; catalog lookups will be empty.")
        return
    try:
        _embed_missing(settings)
    except Exception:
        logger.exception("Embedding the item catalog failed; catalog search uses keywords only until a restart.")
    try:
        _native_ready = _ensure_native_indexes()
    except Exception:
        logger.exception("Building Lakebase Search indexes failed; using plain Postgres ranking.")
        _native_ready = False
    logger.info("Catalog search: %s.", "Lakebase Search native indexes" if _native_ready else "plain Postgres ranking")


def _data_hash(tables: dict[str, list[dict[str, Any]]]) -> str:
    payload = {name: [[row.get(c) for c in _COLUMNS[name]] for row in rows] for name, rows in tables.items()}
    payload["_ddl"] = _TABLES_DDL
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _seed() -> bool:
    """Create the tables and (re)load their rows when the generated data changed."""
    from ._shared_data.demo_data import build_reference_tables

    tables = build_reference_tables()
    data_hash = _data_hash(tables)
    with lakebase._connect() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", [_SEED_LOCK])
            cur.execute(_STATE_DDL)
            cur.execute(f"SELECT data_hash FROM {REF}.seed_state WHERE id = 1")
            row = cur.fetchone()
            if row and row["data_hash"] == data_hash:
                return False
            # Keep embeddings whose text didn't change, so a reseed doesn't re-embed everything.
            kept = {}
            cur.execute(f"SELECT to_regclass('{REF}.item_catalog') IS NOT NULL AS exists")
            if cur.fetchone()["exists"]:
                cur.execute(f"SELECT item_code, description_long, embedding FROM {REF}.item_catalog WHERE embedding IS NOT NULL")
                kept = {(r["item_code"], r["description_long"]): r["embedding"] for r in cur.fetchall()}
            for name in _COLUMNS:
                cur.execute(f"DROP TABLE IF EXISTS {REF}.{name} CASCADE")
            cur.execute(_TABLES_DDL)
            for name, rows in tables.items():
                columns = _COLUMNS[name] + (("embedding",) if name == "item_catalog" else ())
                values = [
                    [row.get(c) for c in _COLUMNS[name]]
                    + ([kept.get((row["item_code"], row.get("description_long")))] if name == "item_catalog" else [])
                    for row in rows
                ]
                cur.executemany(
                    f"INSERT INTO {REF}.{name} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})",
                    values,
                )
            cur.execute(
                f"INSERT INTO {REF}.seed_state (id, data_hash) VALUES (1, %s) "
                "ON CONFLICT (id) DO UPDATE SET data_hash = EXCLUDED.data_hash, seeded_at = now()",
                [data_hash],
            )
    return True


def _embed_missing(settings: Settings) -> None:
    from .catalog_search import embed_texts

    with lakebase._connect() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT item_code, description_long FROM {REF}.item_catalog WHERE embedding IS NULL ORDER BY item_code")
        rows = cur.fetchall()
        if not rows:
            return
        vectors = embed_texts(settings.embedding_endpoint, [r["description_long"] or "" for r in rows])
        cur.executemany(
            f"UPDATE {REF}.item_catalog SET embedding = %s WHERE item_code = %s",
            [(vector, row["item_code"]) for vector, row in zip(vectors, rows)],
        )
    logger.info("Embedded %d catalog descriptions.", len(rows))


def _valid_native_indexes(cur) -> set[str]:
    cur.execute(
        "SELECT c.relname, am.amname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
        "JOIN pg_am am ON am.oid = c.relam "
        "WHERE i.indrelid = %s::regclass AND i.indisvalid AND i.indisready",
        [f"{REF}.item_catalog"],
    )
    return {r["relname"] for r in cur.fetchall() if _NATIVE_INDEXES.get(r["relname"], ("",))[0] == r["amname"]}


def _ensure_native_indexes() -> bool:
    with lakebase._connect() as conn, conn.cursor() as cur:  # autocommit: CONCURRENTLY can't run in a transaction
        cur.execute(
            "SELECT count(*) AS n FROM pg_available_extensions WHERE name IN ('lakebase_text', 'lakebase_vector')"
        )
        if cur.fetchone()["n"] < 2:
            logger.info("Lakebase Search isn't enabled on this Lakebase project.")
            return False
        cur.execute("SELECT pg_try_advisory_lock(%s) AS locked", [_INDEX_LOCK])
        if not cur.fetchone()["locked"]:  # another instance is building them
            return len(_valid_native_indexes(cur)) == len(_NATIVE_INDEXES)
        try:
            cur.execute("SET statement_timeout = '15min'")
            # Install into public (the app's search_path starts with its own `bids` schema).
            cur.execute("SET search_path = public")
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS lakebase_text")
                cur.execute("CREATE EXTENSION IF NOT EXISTS lakebase_vector CASCADE")
            except psycopg.Error as exc:
                # The extensions are listed even when Lakebase Search is off; creating them is the
                # real test ("must be loaded via shared_preload_libraries" until it's enabled).
                logger.info("Lakebase Search isn't enabled on this Lakebase project (%s).", str(exc).strip())
                return False
            cur.execute(f"SELECT count(*) AS total, count(*) FILTER (WHERE embedding IS NULL) AS missing FROM {REF}.item_catalog")
            counts = cur.fetchone()
            if not counts["total"] or counts["missing"]:
                logger.info("Catalog not fully embedded yet; Lakebase Search indexes wait for the next start.")
                return False
            valid = _valid_native_indexes(cur)
            for name, (_, ddl) in _NATIVE_INDEXES.items():
                if name not in valid:
                    # IF NOT EXISTS only checks the name: drop an interrupted or foreign build first.
                    cur.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {REF}.{name}")
                    cur.execute(ddl)
            cur.execute(f"ALTER TABLE {REF}.item_catalog SET (autovacuum_vacuum_insert_scale_factor = 0)")
            cur.execute(f"VACUUM ANALYZE {REF}.item_catalog")
            return len(_valid_native_indexes(cur)) == len(_NATIVE_INDEXES)
        finally:
            cur.execute("SELECT pg_advisory_unlock(%s)", [_INDEX_LOCK])
