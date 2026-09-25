"""Lakebase (managed Postgres) data-access layer.

Two kinds of data:
 - Transactional (`bids` schema, owned by this app): bids + their line items,
   candidate matches, review decisions, generated-proposal paths.
 - Reference (`*bids_ref` schema, UC -> Lakebase synced, read-only): the item
   catalog, historical bids, customer purchase history, customers, divisions.

When Lakebase is not configured (no PG* env vars), the app falls back to the
in-memory store in state.py so local dev works without a database.

Auth: the app's service principal is granted a Postgres role (named after its
client id) via the App's database resource. We mint a short-lived OAuth token
at runtime through the SDK and use it as the Postgres password (token TTL ~1h).
"""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .state import coerce_requirement_status

_APP_SCHEMA = "bids"


def lakebase_configured() -> bool:
    """True when the App injected Lakebase connection env vars."""
    return bool(os.environ.get("PGHOST") and os.environ.get("PGUSER"))


def _instance_name() -> str:
    from .config import get_settings

    return get_settings().lakebase_instance


class _TokenCache:
    """Caches the OAuth credential used as the Postgres password."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: datetime = datetime.min.replace(tzinfo=timezone.utc)

    def get(self) -> str:
        with self._lock:
            now = datetime.now(timezone.utc)
            if self._token and now < self._expires_at - timedelta(minutes=5):
                return self._token
            self._token, self._expires_at = self._mint()
            return self._token

    @staticmethod
    def _mint() -> tuple[str, datetime]:
        from databricks.sdk import WorkspaceClient

        instance = _instance_name()
        if not instance:
            raise RuntimeError("BIDS_LAKEBASE_INSTANCE is not set; cannot mint a Lakebase credential.")
        cred = WorkspaceClient().database.generate_database_credential(
            request_id=str(uuid.uuid4()),
            instance_names=[instance],
        )
        expires = _parse_expiry(cred.expiration_time)
        return cred.token, expires


def _parse_expiry(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc) + timedelta(minutes=50)


_token_cache = _TokenCache()


def _floatify(row: dict[str, Any]) -> dict[str, Any]:
    """psycopg returns Postgres NUMERIC columns as Decimal, which the JSON
    encoder renders as a string ("7.61") instead of a number — convert so API
    responses carry real numbers."""
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in row.items()}


def _connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ["PGHOST"],
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "bids_ai"),
        user=os.environ["PGUSER"],
        password=_token_cache.get(),
        sslmode=os.environ.get("PGSSLMODE", "require"),
        application_name=os.environ.get("PGAPPNAME", "bids-app"),
        options=f"-c search_path={_APP_SCHEMA},public",
        autocommit=True,
        row_factory=dict_row,
    )


# --------------------------------------------------------------------------- #
# Transactional schema
# --------------------------------------------------------------------------- #

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS bids (
    bid_id              TEXT PRIMARY KEY,
    file_name           TEXT NOT NULL,
    bid_name            TEXT DEFAULT '',
    customer_id         TEXT NOT NULL,
    customer_name       TEXT NOT NULL,
    solicitation_ref    TEXT DEFAULT '',
    due_date            TEXT DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'parsing',
    proposal_pdf_path   TEXT,
    proposal_excel_path TEXT,
    uploaded_document_path TEXT,
    documents           JSONB NOT NULL DEFAULT '[]',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bid_line_items (
    line_id               TEXT PRIMARY KEY,
    bid_id                TEXT NOT NULL REFERENCES bids(bid_id) ON DELETE CASCADE,
    line_number            INTEGER NOT NULL,
    raw_description        TEXT NOT NULL,
    qty                    INTEGER NOT NULL DEFAULT 1,
    uom                    TEXT DEFAULT '',
    given_code             TEXT,
    candidates             JSONB NOT NULL DEFAULT '[]',
    selected_item_code  TEXT,
    proposed_price         NUMERIC,
    pricing_basis          TEXT DEFAULT '',
    review_action          TEXT NOT NULL DEFAULT 'pending',
    reviewer_email         TEXT,
    resolution             TEXT NOT NULL DEFAULT 'pending',
    no_product_reason      TEXT DEFAULT '',
    source_doc_id          TEXT,
    source_filename        TEXT,
    source_page            INTEGER,
    extraction_method      TEXT DEFAULT 'ai_extract',
    confidence             DOUBLE PRECISION,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bid_requirements (
    requirement_id         TEXT PRIMARY KEY,
    bid_id                 TEXT NOT NULL REFERENCES bids(bid_id) ON DELETE CASCADE,
    seq                    INTEGER NOT NULL DEFAULT 0,
    term_label             TEXT NOT NULL,
    raw_text               TEXT NOT NULL,
    category               TEXT DEFAULT '',
    owning_teams           JSONB NOT NULL DEFAULT '[]',
    risk_level             TEXT NOT NULL DEFAULT 'medium',
    risk_rationale         TEXT DEFAULT '',
    matched_term           TEXT,
    source                 TEXT NOT NULL DEFAULT 'matrix',
    review_status          TEXT NOT NULL DEFAULT 'pending',
    note                   TEXT DEFAULT '',
    assigned_to            TEXT,
    last_updated_by        TEXT,
    last_updated_at        TIMESTAMPTZ,
    source_doc_id          TEXT,
    source_filename        TEXT,
    source_page            INTEGER,
    extraction_method      TEXT DEFAULT 'ai_extract',
    confidence             DOUBLE PRECISION,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Accounts created from the app ("Bidding on behalf of" -> New account). The
-- seeded customer list lives in the read-only synced `*bids_ref.customers`
-- table, which the app can't write to; app-created accounts go here and are
-- merged on top of the synced list by reference.get_customers().
CREATE TABLE IF NOT EXISTS app_customers (
    customer_id    TEXT PRIMARY KEY,
    customer_name  TEXT NOT NULL,
    division_id    TEXT DEFAULT 'DIV-CORE',
    customer_type  TEXT DEFAULT 'Unspecified',
    region         TEXT DEFAULT 'Unspecified',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Editable overlay on the seeded BRD responsibility matrix (the hardcoded
-- RESPONSIBILITY_MATRIX in _shared_data). Keyed by term_label: a row with
-- is_custom=false OVERRIDES a seeded term's team/risk/category; is_custom=true
-- is a brand-new user-added term. reference.matrix_payload() merges these on
-- top of the seeded matrix. This drives the Matrix page + Extract-step routing
-- dropdowns only; upload-time auto-detection still uses the built-in BRD set.
CREATE TABLE IF NOT EXISTS matrix_term_overrides (
    term_label    TEXT PRIMARY KEY,
    owning_teams  JSONB NOT NULL DEFAULT '[]',
    default_risk  TEXT NOT NULL DEFAULT 'medium',
    category      TEXT NOT NULL DEFAULT '',
    description   TEXT NOT NULL DEFAULT '',
    is_trigger    BOOLEAN NOT NULL DEFAULT false,
    is_custom     BOOLEAN NOT NULL DEFAULT false,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def init_schema() -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_APP_SCHEMA}")
        cur.execute(_SCHEMA_SQL)
        # CREATE TABLE IF NOT EXISTS above is a no-op against an already-deployed
        # table, so new columns need an explicit migration here.
        cur.execute("ALTER TABLE bids ADD COLUMN IF NOT EXISTS due_date TEXT DEFAULT ''")
        cur.execute("ALTER TABLE bids ADD COLUMN IF NOT EXISTS uploaded_document_path TEXT")
        cur.execute("ALTER TABLE bids ADD COLUMN IF NOT EXISTS bid_name TEXT DEFAULT ''")
        # A bid can now carry multiple source documents (the upload step accepts
        # several files, all parsed into the one bid). `documents` is the list of
        # {doc_id, file_name, path, file_format}; scalar file_name/uploaded_document_path
        # stay as the "primary" (first) doc for the history list + back-compat.
        # Backfill wraps each legacy single-doc row into a 1-element array (idempotent).
        cur.execute("ALTER TABLE bids ADD COLUMN IF NOT EXISTS documents JSONB NOT NULL DEFAULT '[]'")
        cur.execute(
            "UPDATE bids SET documents = jsonb_build_array(jsonb_build_object("
            "'doc_id', 'doc-legacy', 'file_name', file_name, 'path', uploaded_document_path, "
            "'file_format', lower(split_part(file_name, '.', -1)))) "
            "WHERE documents = '[]'::jsonb AND uploaded_document_path IS NOT NULL"
        )
        # bid_requirements originally shipped with a single owning_team TEXT
        # NOT NULL column; it's now owning_teams JSONB (a term can be jointly
        # owned). Add the new column, and if the legacy scalar column is still
        # present, backfill from it and then DROP it — leaving it in place keeps
        # its NOT NULL constraint, which the new INSERT (which never populates
        # owning_team) would violate on every write.
        cur.execute("ALTER TABLE bid_requirements ADD COLUMN IF NOT EXISTS owning_teams JSONB NOT NULL DEFAULT '[]'")
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'bid_requirements' AND column_name = 'owning_team'"
        )
        if cur.fetchone():
            cur.execute(
                "UPDATE bid_requirements SET owning_teams = to_jsonb(ARRAY[owning_team]) "
                "WHERE owning_teams = '[]'::jsonb AND owning_team IS NOT NULL"
            )
            cur.execute("ALTER TABLE bid_requirements DROP COLUMN owning_team")
        # Editable-table + review-workflow columns.
        cur.execute("ALTER TABLE bid_requirements ADD COLUMN IF NOT EXISTS note TEXT DEFAULT ''")
        cur.execute("ALTER TABLE bid_requirements ADD COLUMN IF NOT EXISTS last_updated_by TEXT")
        cur.execute("ALTER TABLE bid_requirements ADD COLUMN IF NOT EXISTS last_updated_at TIMESTAMPTZ")
        # Legacy statuses (acknowledged/routed) -> current enum, done in-place so
        # old rows read back as valid workflow states.
        cur.execute("UPDATE bid_requirements SET review_status = 'approved' WHERE review_status = 'acknowledged'")
        cur.execute("UPDATE bid_requirements SET review_status = 'in_review' WHERE review_status = 'routed'")
        # Source-traceability (provenance) columns on both extracted-entity tables:
        # which uploaded file/page each row came from and how it was extracted.
        # Additive + nullable — old rows read back with NULL provenance. confidence
        # is DOUBLE PRECISION (not NUMERIC) so it deserializes as a float, not a
        # Decimal-turned-string.
        for _tbl in ("bid_line_items", "bid_requirements"):
            cur.execute(f"ALTER TABLE {_tbl} ADD COLUMN IF NOT EXISTS source_doc_id TEXT")
            cur.execute(f"ALTER TABLE {_tbl} ADD COLUMN IF NOT EXISTS source_filename TEXT")
            cur.execute(f"ALTER TABLE {_tbl} ADD COLUMN IF NOT EXISTS source_page INTEGER")
            cur.execute(f"ALTER TABLE {_tbl} ADD COLUMN IF NOT EXISTS extraction_method TEXT DEFAULT 'ai_extract'")
            cur.execute(f"ALTER TABLE {_tbl} ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION")
        # Matrix terms now carry an editable natural-language `description` (the
        # ai_classify label definition) instead of the old `category`. Additive;
        # the legacy `category` column is left in place, unused (no destructive drop).
        cur.execute(
            f"ALTER TABLE {_APP_SCHEMA}.matrix_term_overrides ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT ''"
        )
        # A term can be flagged a "material trigger" (drives the Extract-step
        # Material/Immaterial banner) editable per-term from the Matrix page.
        cur.execute(
            f"ALTER TABLE {_APP_SCHEMA}.matrix_term_overrides ADD COLUMN IF NOT EXISTS is_trigger BOOLEAN NOT NULL DEFAULT false"
        )
        # Guardrail-first matching: per-line resolution state (pending /
        # catalog_match / no_match). The no_product_reason column is legacy (the
        # earlier NO-BID flow) — kept, unused, no destructive drop.
        cur.execute("ALTER TABLE bid_line_items ADD COLUMN IF NOT EXISTS resolution TEXT NOT NULL DEFAULT 'pending'")
        cur.execute("ALTER TABLE bid_line_items ADD COLUMN IF NOT EXISTS no_product_reason TEXT DEFAULT ''")


class LakebaseBidStore:
    """Transactional store backed by Lakebase Postgres."""

    def create_bid(
        self, *, bid_id: str, file_name: str, customer_id: str, customer_name: str,
        solicitation_ref: str, due_date: str, uploaded_document_path: str, bid_name: str = "",
        documents: list[dict[str, Any]] | None = None,
    ) -> None:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO bids (bid_id, file_name, bid_name, customer_id, customer_name, solicitation_ref, "
                "due_date, uploaded_document_path, documents) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (bid_id, file_name, bid_name, customer_id, customer_name, solicitation_ref, due_date,
                 uploaded_document_path, Jsonb(list(documents or []))),
            )

    def list_bids(self, limit: int = 50) -> list[dict[str, Any]]:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT b.bid_id, b.file_name, b.bid_name, b.customer_name, b.status, b.due_date, b.created_at, "
                "COUNT(l.line_id) AS line_item_count "
                "FROM bids b LEFT JOIN bid_line_items l ON l.bid_id = b.bid_id "
                "GROUP BY b.bid_id ORDER BY b.created_at DESC LIMIT %s",
                (limit,),
            )
            return [_floatify(row) for row in cur.fetchall()]

    # Provenance columns shared by both line-item INSERTs. A manually-added line
    # (add_line_item) defaults extraction_method to "manual"; extracted rows carry
    # their own from the pipeline.
    _LINE_INSERT_SQL = (
        "INSERT INTO bid_line_items (line_id, bid_id, line_number, raw_description, qty, uom, given_code, "
        "source_doc_id, source_filename, source_page, extraction_method, confidence) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )

    def add_line_items(self, bid_id: str, lines: list[dict[str, Any]]) -> None:
        with _connect() as conn, conn.cursor() as cur:
            for line in lines:
                cur.execute(
                    self._LINE_INSERT_SQL,
                    (
                        line["line_id"], bid_id, line["line_number"], line["raw_description"],
                        line.get("qty", 1), line.get("uom", ""), line.get("given_code"),
                        line.get("source_doc_id"), line.get("source_filename"), line.get("source_page"),
                        line.get("extraction_method", "ai_extract"), line.get("confidence"),
                    ),
                )

    def add_line_item(self, bid_id: str, line: dict[str, Any]) -> None:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                self._LINE_INSERT_SQL,
                (
                    line["line_id"], bid_id, line["line_number"], line.get("raw_description", ""),
                    line.get("qty", 1), line.get("uom", ""), line.get("given_code"),
                    line.get("source_doc_id"), line.get("source_filename"), line.get("source_page"),
                    line.get("extraction_method", "manual"), line.get("confidence"),
                ),
            )

    def delete_line_item(self, bid_id: str, line_id: str) -> None:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM bid_line_items WHERE bid_id = %s AND line_id = %s", (bid_id, line_id))

    def clear_line_items(self, bid_id: str) -> None:
        """Remove all line items for a bid, so re-extraction is idempotent (the
        extract-line-items endpoint clears before re-adding)."""
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM bid_line_items WHERE bid_id = %s", (bid_id,))

    def clear_requirements(self, bid_id: str) -> None:
        """Remove all requirements for a bid, so re-extraction is idempotent."""
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM bid_requirements WHERE bid_id = %s", (bid_id,))

    def set_bid_documents(self, bid_id: str, documents: list[dict[str, Any]]) -> None:
        """Replace the documents manifest (e.g. after deleting a staged doc)."""
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE bids SET documents = %s, updated_at = now() WHERE bid_id = %s",
                (Jsonb(list(documents)), bid_id),
            )

    # Editable bid-metadata columns for update_bid_metadata (all plain scalars).
    _BID_META_FIELDS = (
        "bid_name", "due_date", "customer_id", "customer_name",
        "file_name", "uploaded_document_path",
    )

    def update_bid_metadata(
        self, bid_id: str, *, bid_name: str | None = None, due_date: str | None = None,
        customer_id: str | None = None, customer_name: str | None = None,
        file_name: str | None = None, uploaded_document_path: str | None = None,
    ) -> None:
        """Partial update of a bid's editable metadata (Upload step). Only the
        provided (non-None) fields are changed; a call with nothing set is a no-op."""
        provided = {
            "bid_name": bid_name, "due_date": due_date,
            "customer_id": customer_id, "customer_name": customer_name,
            "file_name": file_name, "uploaded_document_path": uploaded_document_path,
        }
        sets: list[str] = []
        params: list[Any] = []
        for key in self._BID_META_FIELDS:
            if provided[key] is not None:
                sets.append(f"{key} = %s")
                params.append(provided[key])
        if not sets:
            return
        sets.append("updated_at = now()")
        params.append(bid_id)
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE bids SET {', '.join(sets)} WHERE bid_id = %s", params)

    def add_requirements(self, bid_id: str, requirements: list[dict[str, Any]]) -> None:
        with _connect() as conn, conn.cursor() as cur:
            for i, req in enumerate(requirements, start=1):
                cur.execute(
                    "INSERT INTO bid_requirements (requirement_id, bid_id, seq, term_label, raw_text, category, "
                    "owning_teams, risk_level, risk_rationale, matched_term, source, "
                    "source_doc_id, source_filename, source_page, extraction_method, confidence) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        req["requirement_id"], bid_id, i, req["term_label"], req["raw_text"],
                        req.get("category", ""), Jsonb(list(req.get("owning_teams") or [])),
                        req.get("risk_level", "medium"), req.get("risk_rationale", ""),
                        req.get("matched_term"), req.get("source", "matrix"),
                        req.get("source_doc_id"), req.get("source_filename"), req.get("source_page"),
                        req.get("extraction_method", "ai_extract"), req.get("confidence"),
                    ),
                )

    def add_requirement(self, bid_id: str, requirement: dict[str, Any], *, updated_by: str | None) -> None:
        """A single manually-added requirement, appended after the existing ones."""
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM bid_requirements WHERE bid_id = %s", (bid_id,))
            next_seq = cur.fetchone()["next_seq"]
            cur.execute(
                "INSERT INTO bid_requirements (requirement_id, bid_id, seq, term_label, raw_text, category, "
                "owning_teams, risk_level, risk_rationale, matched_term, source, last_updated_by, "
                "source_doc_id, source_filename, source_page, extraction_method, confidence, last_updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())",
                (
                    requirement["requirement_id"], bid_id, next_seq, requirement["term_label"],
                    requirement.get("raw_text", ""), requirement.get("category", ""),
                    Jsonb(list(requirement.get("owning_teams") or [])), requirement.get("risk_level", "medium"),
                    requirement.get("risk_rationale", ""), requirement.get("matched_term"),
                    requirement.get("source", "manual"), updated_by,
                    requirement.get("source_doc_id"), requirement.get("source_filename"),
                    requirement.get("source_page"), requirement.get("extraction_method", "manual"),
                    requirement.get("confidence"),
                ),
            )

    # Editable requirement fields and their JSON/scalar handling for update_requirement.
    _REQ_TEXT_FIELDS = ("term_label", "raw_text", "category", "risk_level", "review_status", "note")

    def update_requirement(
        self, bid_id: str, requirement_id: str, *, fields: dict[str, Any], updated_by: str | None,
    ) -> None:
        """Partial update of any editable requirement field, always stamping the
        reviewer + timestamp. Only provided (non-None) fields are changed."""
        sets: list[str] = []
        params: list[Any] = []
        for key in self._REQ_TEXT_FIELDS:
            if fields.get(key) is not None:
                sets.append(f"{key} = %s")
                params.append(fields[key])
        if fields.get("owning_teams") is not None:
            sets.append("owning_teams = %s")
            params.append(Jsonb(list(fields["owning_teams"])))
        sets.append("last_updated_by = %s")
        params.append(updated_by)
        sets.append("last_updated_at = now()")
        sets.append("updated_at = now()")
        params.extend([bid_id, requirement_id])
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"UPDATE bid_requirements SET {', '.join(sets)} WHERE bid_id = %s AND requirement_id = %s",
                params,
            )

    def delete_requirement(self, bid_id: str, requirement_id: str) -> None:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM bid_requirements WHERE bid_id = %s AND requirement_id = %s", (bid_id, requirement_id))

    def set_line_candidates(self, bid_id: str, line_id: str, candidates: list[dict[str, Any]]) -> None:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE bid_line_items SET candidates = %s, updated_at = now() WHERE bid_id = %s AND line_id = %s",
                (Jsonb(candidates), bid_id, line_id),
            )

    def update_line_item(
        self, bid_id: str, line_id: str, *, raw_description: str, qty: int, uom: str, given_code: str | None,
    ) -> None:
        """A corrected description invalidates whatever was matched against
        the old (possibly wrong) text — reset downstream match/review state
        in the same statement so the next /match call re-processes this line."""
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE bid_line_items SET raw_description = %s, qty = %s, uom = %s, given_code = %s, "
                "candidates = '[]'::jsonb, selected_item_code = NULL, proposed_price = NULL, "
                "pricing_basis = '', review_action = 'pending', reviewer_email = NULL, updated_at = now() "
                "WHERE bid_id = %s AND line_id = %s",
                (raw_description, qty, uom, given_code, bid_id, line_id),
            )

    def clear_line_match(self, bid_id: str, line_id: str) -> None:
        """Reset a line's match/review state so the next /match re-processes it —
        same reset update_line_item does, minus touching the line's own fields.
        Used by a 'Re-match all' re-run to discard prior candidates/selections."""
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE bid_line_items SET candidates = '[]'::jsonb, selected_item_code = NULL, "
                "proposed_price = NULL, pricing_basis = '', review_action = 'pending', "
                "reviewer_email = NULL, resolution = 'pending', updated_at = now() "
                "WHERE bid_id = %s AND line_id = %s",
                (bid_id, line_id),
            )

    def update_bid_status(self, bid_id: str, status: str) -> None:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("UPDATE bids SET status = %s, updated_at = now() WHERE bid_id = %s", (status, bid_id))

    def review_line(
        self, bid_id: str, line_id: str, *, selected_item_code: str, proposed_price: float,
        pricing_basis: str, review_action: str, reviewer_email: str | None,
    ) -> None:
        # Selecting/pricing a catalog product resolves the line as catalog_match.
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE bid_line_items SET selected_item_code = %s, proposed_price = %s, "
                "pricing_basis = %s, review_action = %s, reviewer_email = %s, "
                "resolution = 'catalog_match', updated_at = now() "
                "WHERE bid_id = %s AND line_id = %s",
                (selected_item_code, proposed_price, pricing_basis, review_action, reviewer_email, bid_id, line_id),
            )

    def resolve_no_match(
        self, bid_id: str, line_id: str, *, reviewer_email: str | None,
    ) -> None:
        """Record that the catalog has no fit for this line — clears code/price,
        sets resolution=no_match. The line renders BLANK (unpriced) in the
        proposal. review_action='overridden' marks it a deliberate human decision
        (so it's not 'pending' and doesn't block submission). No reason needed."""
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE bid_line_items SET selected_item_code = NULL, proposed_price = NULL, "
                "pricing_basis = '', review_action = 'overridden', reviewer_email = %s, "
                "resolution = 'no_match', updated_at = now() "
                "WHERE bid_id = %s AND line_id = %s",
                (reviewer_email, bid_id, line_id),
            )

    def finalize_bid(self, bid_id: str, *, pdf_path: str, excel_path: str) -> None:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE bids SET status = 'submitted', proposal_pdf_path = %s, proposal_excel_path = %s, "
                "updated_at = now() WHERE bid_id = %s",
                (pdf_path, excel_path, bid_id),
            )

    def get_bid(self, bid_id: str) -> dict[str, Any] | None:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM bids WHERE bid_id = %s", (bid_id,))
            bid_row = cur.fetchone()
            if not bid_row:
                return None
            # Legacy/edge rows may have an empty documents array but a stored single
            # doc path — synthesize a 1-element array so the frontend viewer always
            # has something to show (belt-and-braces alongside the init_schema backfill).
            if not bid_row.get("documents") and bid_row.get("uploaded_document_path"):
                file_name = bid_row["file_name"]
                bid_row["documents"] = [{
                    "doc_id": "doc-legacy",
                    "file_name": file_name,
                    "path": bid_row["uploaded_document_path"],
                    "file_format": (file_name.rsplit(".", 1)[-1] if "." in file_name else "").lower(),
                }]
            cur.execute("SELECT * FROM bid_line_items WHERE bid_id = %s ORDER BY line_number", (bid_id,))
            lines = []
            for line in cur.fetchall():
                line = _floatify(line)
                # Backfill resolution for rows predating the guardrail migration:
                # a selected catalog code -> catalog_match, else pending.
                if not line.get("resolution"):
                    line["resolution"] = "catalog_match" if line.get("selected_item_code") else "pending"
                lines.append(line)
            bid_row["line_items"] = lines
            cur.execute("SELECT * FROM bid_requirements WHERE bid_id = %s ORDER BY seq", (bid_id,))
            requirements = []
            for req in cur.fetchall():
                req = _floatify(req)
                req["review_status"] = coerce_requirement_status(req.get("review_status"))
                # Normalize TIMESTAMPTZ columns to ISO strings for the JSON response.
                for ts_key in ("last_updated_at", "updated_at"):
                    if isinstance(req.get(ts_key), datetime):
                        req[ts_key] = req[ts_key].isoformat()
                requirements.append(req)
            bid_row["requirements"] = requirements
            return bid_row


# --------------------------------------------------------------------------- #
# Reference data (read-only, UC -> Lakebase synced tables in the `*bids_ref` schema)
# --------------------------------------------------------------------------- #

_ref_schema_cache: str | None = None
_ref_lock = threading.Lock()
_REF_TTL = timedelta(minutes=5)
_ref_data_cache: dict[str, tuple[datetime, Any]] = {}


def _ref_schema() -> str:
    global _ref_schema_cache
    with _ref_lock:
        if _ref_schema_cache:
            return _ref_schema_cache
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT table_schema FROM information_schema.tables "
                "WHERE table_name = 'item_catalog' AND table_schema LIKE '%%bids_ref' "
                "ORDER BY length(table_schema) DESC LIMIT 1"
            )
            row = cur.fetchone()
        if not row:
            raise RuntimeError("No synced reference schema (*bids_ref with an item_catalog table) found.")
        _ref_schema_cache = row["table_schema"]
        return _ref_schema_cache


def _ref_query(sql_template: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    sql = sql_template.format(ref=f'"{_ref_schema()}"')
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params or [])
        return [_floatify(row) for row in cur.fetchall()]


def _cached(key: str, loader) -> Any:
    now = datetime.now(timezone.utc)
    hit = _ref_data_cache.get(key)
    if hit and now - hit[0] < _REF_TTL:
        return hit[1]
    value = loader()
    _ref_data_cache[key] = (now, value)
    return value


def get_customers() -> list[dict[str, Any]]:
    return _cached("customers", lambda: _ref_query("SELECT * FROM {ref}.customers ORDER BY customer_name"))


def get_customer(customer_id: str) -> dict[str, Any] | None:
    return next((c for c in get_customers() if c.get("customer_id") == customer_id), None)


# App-created accounts live in the transactional `bids` schema (writable), NOT
# the synced `*bids_ref` schema — so these use _connect() directly, not
# _ref_query()/_cached() (which target the read-only reference schema and would
# cache away new rows).
def create_app_customer(
    *, customer_id: str, customer_name: str, division_id: str, customer_type: str, region: str,
) -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {_APP_SCHEMA}.app_customers "
            "(customer_id, customer_name, division_id, customer_type, region) "
            "VALUES (%s, %s, %s, %s, %s)",
            [customer_id, customer_name, division_id, customer_type, region],
        )


def get_app_customers() -> list[dict[str, Any]]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT customer_id, customer_name, division_id, customer_type, region "
            f"FROM {_APP_SCHEMA}.app_customers ORDER BY customer_name"
        )
        return [_floatify(row) for row in cur.fetchall()]


# Editable responsibility-matrix overlay — same transactional-schema pattern as
# app_customers (writable `bids` schema, plain _connect(), no _ref_query/_cached).
def get_matrix_overrides() -> list[dict[str, Any]]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT term_label, owning_teams, default_risk, description, is_trigger, is_custom "
            f"FROM {_APP_SCHEMA}.matrix_term_overrides"
        )
        return [_floatify(row) for row in cur.fetchall()]


def upsert_matrix_override(
    *, term_label: str, owning_teams: list[str], default_risk: str, description: str,
    is_trigger: bool, is_custom: bool,
) -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {_APP_SCHEMA}.matrix_term_overrides "
            "(term_label, owning_teams, default_risk, description, is_trigger, is_custom, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, now()) "
            "ON CONFLICT (term_label) DO UPDATE SET "
            "owning_teams = EXCLUDED.owning_teams, default_risk = EXCLUDED.default_risk, "
            "description = EXCLUDED.description, is_trigger = EXCLUDED.is_trigger, "
            "is_custom = EXCLUDED.is_custom, updated_at = now()",
            [term_label, Jsonb(list(owning_teams)), default_risk, description, is_trigger, is_custom],
        )


def delete_matrix_override(term_label: str) -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {_APP_SCHEMA}.matrix_term_overrides WHERE term_label = %s",
            [term_label],
        )


def get_item_catalog_row(item_code: str) -> dict[str, Any] | None:
    rows = _ref_query("SELECT * FROM {ref}.item_catalog WHERE item_code = %s", [item_code])
    return rows[0] if rows else None


def get_item_catalog_rows(item_codes: list[str]) -> dict[str, dict[str, Any]]:
    if not item_codes:
        return {}
    placeholders = ",".join(["%s"] * len(item_codes))
    rows = _ref_query(f"SELECT * FROM {{ref}}.item_catalog WHERE item_code IN ({placeholders})", item_codes)
    return {r["item_code"]: r for r in rows}


def get_catalog_manufacturers() -> list[str]:
    """Distinct active-catalog manufacturer names, sorted — reference option list
    for the Match-step manufacturer filter. Cached like the other reference reads."""
    def _load() -> list[str]:
        rows = _ref_query(
            "SELECT DISTINCT manufacturer_name FROM {ref}.item_catalog "
            "WHERE is_active = true AND manufacturer_name IS NOT NULL "
            "ORDER BY manufacturer_name"
        )
        return [r["manufacturer_name"] for r in rows if (r.get("manufacturer_name") or "").strip()]

    return _cached("manufacturers", _load)


def get_historical_bids_for_items(item_codes: list[str], customer_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """historical_bids rows for a set of items, optionally scoped to one customer.
    Keyed by item_code for easy per-candidate lookup."""
    if not item_codes:
        return {}
    placeholders = ",".join(["%s"] * len(item_codes))
    params: list[Any] = list(item_codes)
    customer_clause = ""
    if customer_id:
        customer_clause = "AND customer_id = %s"
        params.append(customer_id)
    rows = _ref_query(
        f"SELECT * FROM {{ref}}.historical_bids WHERE item_code IN ({placeholders}) {customer_clause} "
        "ORDER BY submitted_date DESC",
        params,
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(row["item_code"], []).append(row)
    return out


def get_purchase_history_for_items(item_codes: list[str], customer_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    if not item_codes:
        return {}
    placeholders = ",".join(["%s"] * len(item_codes))
    params: list[Any] = list(item_codes)
    customer_clause = ""
    if customer_id:
        customer_clause = "AND customer_id = %s"
        params.append(customer_id)
    rows = _ref_query(
        f"SELECT * FROM {{ref}}.customer_purchase_history WHERE item_code IN ({placeholders}) {customer_clause} "
        "ORDER BY last_purchase_date DESC",
        params,
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(row["item_code"], []).append(row)
    return out
