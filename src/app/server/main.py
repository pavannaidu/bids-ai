from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import databricks_api, documents, lakebase, reference, volumes
from .config import (
    MATCH_SENSITIVITY_THRESHOLDS,
    Settings,
    get_extraction_default,
    get_match_sensitivity,
    get_match_threshold,
    get_settings,
    set_extraction_default,
    set_match_sensitivity,
)
from .models import (
    AddRequirementRequest,
    CreateCustomerRequest,
    ManualMatchRequest,
    MatrixTermDeleteRequest,
    MatrixTermUpsertRequest,
    ReviewLineRequest,
    UpdateLineItemRequest,
    UpdateRequirementRequest,
)
from .state import InMemoryBidStore
from .validation import (
    lines_defaulting_to_no_match,
    lines_eligible_for_bulk_accept,
    validate_bid_ready_for_submission,
)

logger = logging.getLogger("bids")
settings = get_settings()
static_root = Path(__file__).resolve().parents[1] / "static"

_lakebase_active = lakebase.lakebase_configured()
store = lakebase.LakebaseBidStore() if _lakebase_active else InMemoryBidStore()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if _lakebase_active:
        try:
            lakebase.init_schema()
            logger.info("Lakebase store active: transactional schema ready; reference data from *bids_ref.")
        except Exception:
            logger.exception("Lakebase initialization failed.")
    else:
        logger.info("Lakebase not configured; using in-memory store and in-process reference data.")
    yield


app = FastAPI(title="Bids AI Demo", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=static_root), name="static")


def _seller_email(http_request: Request) -> str | None:
    """Databricks Apps forward the signed-in user on these headers."""
    for header in ("X-Forwarded-Email", "X-Forwarded-User", "x-forwarded-email"):
        value = http_request.headers.get(header)
        if value:
            return value
    return None


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    # no-cache so the browser always revalidates index.html and picks up a new
    # deploy's content-hashed JS/CSS bundle. Without this the browser can serve a
    # stale index.html that points at an old bundle, so deploys silently don't
    # reach users until a manual hard-reload. The hashed assets under /static stay
    # long-cacheable (their names change per build), so only the HTML revalidates.
    return FileResponse(static_root / "index.html", headers={"Cache-Control": "no-cache"})


# Static reference deck ("Bids AI — Document Intelligence in Databricks"). Lives in
# ../pages (NOT ../static, which vite build wipes via emptyOutDir on every FE build)
# so it survives deploys. Served self-contained; no-cache so edits show up immediately.
_pages_root = Path(__file__).resolve().parents[1] / "pages"


@app.get("/bids-ai", include_in_schema=False)
def bids_ai_deck() -> FileResponse:
    return FileResponse(_pages_root / "bids-ai.html", headers={"Cache-Control": "no-cache"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _display_name_from_email(email: str) -> str:
    local_part = email.split("@", 1)[0]
    return " ".join(part.capitalize() for part in local_part.replace("_", ".").split(".")) or "Guest"


@app.get("/api/me")
def current_user(http_request: Request) -> dict[str, object]:
    email = _seller_email(http_request)
    display_email = email or "demo.seller@example.com"
    return {
        "email": display_email,
        "name": _display_name_from_email(display_email),
        "authenticated": bool(email),
    }


def _settings_response() -> dict[str, object]:
    """App-level settings surfaced to the frontend: the default extraction method
    and the match sensitivity (+ its effective numeric threshold, for read-only
    helper text). All derived from process-local overrides (or env baseline)."""
    return {
        "extraction_method": "ai_extract" if get_extraction_default() else "ai_query",
        "match_sensitivity": get_match_sensitivity(),
        "match_threshold": get_match_threshold(),
    }


class SettingsRequest(BaseModel):
    """Partial settings PATCH — only the provided fields change. `match_sensitivity`
    gates AUTOMATED match selection/bulk-accept only (not manual catalog search)."""

    extraction_method: Literal["ai_extract", "ai_query"] | None = None
    match_sensitivity: Literal["conservative", "balanced", "permissive"] | None = None


@app.get("/api/settings")
def get_app_settings() -> dict[str, object]:
    return _settings_response()


@app.patch("/api/settings")
def update_app_settings(request: SettingsRequest) -> dict[str, object]:
    """Set process-local app settings (Settings pane). In-memory by design —
    resets to the env baseline on redeploy."""
    if request.extraction_method is not None:
        set_extraction_default(request.extraction_method == "ai_extract")
    if request.match_sensitivity is not None:
        set_match_sensitivity(request.match_sensitivity)
    return _settings_response()


@app.get("/api/customers")
def list_customers() -> dict[str, object]:
    return {"customers": reference.get_customers()}


@app.post("/api/customers")
def create_customer(request: CreateCustomerRequest) -> dict[str, object]:
    """Create an account from the Upload step's "New account" quick-add so a
    presenter can bid on behalf of a customer that isn't in the seeded list."""
    name = request.customer_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Account name is required")
    return {"customer": reference.create_customer(name)}


@app.get("/api/sample-documents")
def list_sample_documents() -> dict[str, object]:
    """The pre-seeded sample bid solicitations a presenter can load with one
    click, so the live demo doesn't depend on having a real file handy."""
    from ._shared_data.sample_documents import SAMPLE_DOCUMENTS, document_manifest

    return {"documents": [document_manifest(d) for d in SAMPLE_DOCUMENTS]}


# Heavy parse artifacts stashed on each documents[] entry so the extract
# endpoints can reuse the parse without re-running ai_parse_document. They must
# never ship to the client (hundreds of KB of parsed text) — stripped on read.
_DOC_INTERNAL_KEYS = ("parsed_text", "page_spans", "source_kind", "parse_error")


def _bid_to_response(bid_id: str) -> dict[str, object]:
    bid = store.get_bid(bid_id)
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")
    # Strip the internal parse cache from the documents manifest before it leaves
    # the server — the frontend's SourceDocument type never sees these keys. Build
    # NEW dicts rather than pop() in place: the in-memory store hands back the same
    # document objects it holds, so mutating them would wipe the stash the extract
    # endpoints rely on.
    if bid.get("documents"):
        bid["documents"] = [
            {k: v for k, v in doc.items() if k not in _DOC_INTERNAL_KEYS}
            for doc in bid["documents"]
        ]
    # Derive the material/immaterial triage verdict on read from the current
    # requirements — no persistence, so it always reflects the latest clause set
    # (lazy import mirrors the matrix_payload() usage in responsibility_matrix()).
    from ._shared_data.responsibility_matrix import compute_review_verdict
    # Pass the MERGED matrix's editable trigger set so the banner reflects Matrix-
    # page edits (a term's "material trigger" checkbox), not just the seeded set.
    bid["review_verdict"] = compute_review_verdict(bid.get("requirements", []), reference.trigger_terms())
    return bid


def _file_format(file_name: str) -> str:
    return (file_name.rsplit(".", 1)[-1] if "." in file_name else "").lower()


# Filenames are controlled by us on write, so extension-based MIME is adequate.
_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
}


def _media_type_for(file_name: str) -> str:
    return _MEDIA_TYPES.get(_file_format(file_name), "application/octet-stream")


def _stage_documents(bid_id: str, files: list[tuple[str, bytes]]) -> list[dict[str, object]]:
    """Stage each file to the Volume and PARSE it (fast, ~15s/file), returning the
    enriched documents[] manifest entries with the parse result stashed
    (parsed_text/page_spans/source_kind/parse_error) so the separate
    extract-requirements / extract-line-items endpoints can reuse it without
    re-parsing. Used at initial upload and when adding a doc to an existing bid."""
    documents: list[dict[str, object]] = []
    for file_name, content in files:
        doc_id = f"doc-{uuid.uuid4().hex[:8]}"
        upload_path = f"{settings.uploads_path}/{bid_id}/{doc_id}/{file_name}"
        try:
            volumes.write_volume_file(upload_path, content)
        except Exception as exc:
            logger.exception("Could not write upload to Volume path %s", upload_path)
            raise HTTPException(status_code=502, detail=f"Could not stage document in the Volume: {exc}") from exc
        # parse_document never raises; on a failed parse it returns empty text +
        # a parse_error, which the extract endpoints surface later.
        parsed = databricks_api.parse_document(settings, upload_path, content)
        documents.append({
            "doc_id": doc_id, "file_name": file_name, "path": upload_path,
            "file_format": _file_format(file_name),
            "parsed_text": parsed["text"], "page_spans": parsed["page_spans"],
            "source_kind": parsed["source_kind"], "parse_error": parsed["parse_error"],
        })
    return documents


def _stage_and_parse(
    *, bid_id: str, files: list[tuple[str, bytes]], customer_id: str, due_date: str, bid_name: str = "",
) -> dict[str, object]:
    """Phase 1 of upload: stage + parse every file, then create the bid at status
    "uploaded" with no line items or requirements yet. Splitting extraction out
    into separate endpoints keeps each request well under the 300s gateway."""
    customer = reference.get_customer(customer_id)
    if not customer:
        raise HTTPException(status_code=400, detail=f"Unknown customer {customer_id}")
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    documents = _stage_documents(bid_id, files)

    primary = documents[0]
    store.create_bid(
        bid_id=bid_id, file_name=primary["file_name"], customer_id=customer_id,
        customer_name=customer["customer_name"], solicitation_ref="", due_date=due_date,
        uploaded_document_path=primary["path"], bid_name=bid_name, documents=documents,
    )
    store.update_bid_status(bid_id, "uploaded")
    return _bid_to_response(bid_id)


def _reconstruct_parsed(doc: dict[str, object]) -> dict[str, object]:
    """Return the parse for a document — from the stash on the manifest if
    present, else re-parse from the Volume (back-compat for bids created before
    parse results were stashed)."""
    if doc.get("parsed_text") is not None:
        return {
            "text": doc["parsed_text"], "page_spans": doc.get("page_spans") or [],
            "source_kind": doc.get("source_kind", "raw_json"), "parse_error": doc.get("parse_error"),
        }
    content = volumes.read_volume_file(doc["path"])
    return databricks_api.parse_document(settings, doc["path"], content)


ExtractionMethod = Literal["ai_extract", "ai_query"]


def _extraction_settings(method: ExtractionMethod | None) -> Settings:
    """Resolve the Settings to use for an extraction request. `method=None` uses
    the current global default (env baseline or the Settings-pane override);
    "ai_extract"/"ai_query" force that path for this one call. The only knob that
    changes is `use_ai_extract`, which both extraction paths already honor."""
    use_ai = get_extraction_default() if method is None else (method == "ai_extract")
    return replace(settings, use_ai_extract=use_ai)


def _extract_lines_for_bid(
    bid: dict[str, object], settings_override: Settings | None = None,
) -> list[dict[str, object]]:
    """Line items across all of a bid's documents, merged with per-file line-number
    offset + doc-level provenance (lifted from the old monolithic upload)."""
    effective = settings_override or settings
    all_lines: list[dict[str, object]] = []
    line_offset = 0
    for doc in bid["documents"]:
        parsed = _reconstruct_parsed(doc)
        for item in databricks_api.extract_line_items(effective, parsed):
            item["line_number"] = item["line_number"] + line_offset
            item["source_doc_id"] = doc["doc_id"]
            item["source_filename"] = doc["file_name"]
            all_lines.append(item)
        line_offset = max((line["line_number"] for line in all_lines), default=0)
    return all_lines


def _extract_requirements_for_bid(
    bid: dict[str, object], settings_override: Settings | None = None,
) -> list[dict[str, object]]:
    """Requirements across all of a bid's documents. Per-file failure is
    non-fatal (requirements are additive)."""
    effective = settings_override or settings
    all_requirements: list[dict[str, object]] = []
    for doc in bid["documents"]:
        try:
            parsed = _reconstruct_parsed(doc)
            requirements = databricks_api.extract_and_classify_requirements(effective, parsed)
        except Exception:
            logger.exception("Requirement extraction failed for bid %s file %s (non-fatal)",
                             bid["bid_id"], doc.get("file_name"))
            continue
        for req in requirements:
            req["source_doc_id"] = doc["doc_id"]
            req["source_filename"] = doc["file_name"]
        all_requirements.extend(requirements)
    return all_requirements


@app.post("/api/bids/upload")
async def upload_bid(
    customer_id: str, due_date: str, files: list[UploadFile] = File(...), bid_name: str = "",
) -> dict[str, object]:
    bid_id = f"bid-{uuid.uuid4().hex[:10]}"
    staged = [(f.filename or "upload", await f.read()) for f in files]
    return _stage_and_parse(
        bid_id=bid_id, files=staged,
        customer_id=customer_id, due_date=due_date, bid_name=bid_name,
    )


class UploadSampleRequest(BaseModel):
    sample_file_name: str
    customer_id: str
    due_date: str
    bid_name: str = ""


@app.post("/api/bids/upload-sample")
def upload_sample_bid(request: UploadSampleRequest) -> dict[str, object]:
    bid_id = f"bid-{uuid.uuid4().hex[:10]}"
    sample_path = f"{settings.sample_documents_path}/{request.sample_file_name}"
    try:
        content = volumes.read_volume_file(sample_path)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Sample document not found: {request.sample_file_name}") from exc
    return _stage_and_parse(
        bid_id=bid_id, files=[(request.sample_file_name, content)],
        customer_id=request.customer_id, due_date=request.due_date, bid_name=request.bid_name,
    )


class BidUpdateRequest(BaseModel):
    bid_name: str | None = None
    due_date: str | None = None
    customer_id: str | None = None


@app.patch("/api/bids/{bid_id}")
def update_bid(bid_id: str, request: BidUpdateRequest) -> dict[str, object]:
    """Edit a bid's metadata from the Upload step. Name and due date are cosmetic
    and editable any time; changing the customer is only allowed before extraction
    runs (status "uploaded") — afterwards it would invalidate matching/pricing."""
    bid = store.get_bid(bid_id)
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")

    customer_name: str | None = None
    if request.customer_id is not None:
        if bid.get("status") != "uploaded":
            raise HTTPException(status_code=409, detail="The customer can only be changed before extraction runs.")
        customer = reference.get_customer(request.customer_id)
        if not customer:
            raise HTTPException(status_code=400, detail=f"Unknown customer {request.customer_id}")
        customer_name = customer["customer_name"]

    store.update_bid_metadata(
        bid_id, bid_name=request.bid_name, due_date=request.due_date,
        customer_id=request.customer_id, customer_name=customer_name,
    )
    return _bid_to_response(bid_id)


@app.post("/api/bids/{bid_id}/documents")
async def add_source_documents(bid_id: str, files: list[UploadFile] = File(...)) -> dict[str, object]:
    """Add one or more documents to a bid at ANY step. The new file is staged +
    parsed immediately (parse stashed on the manifest); already-extracted rows are
    NOT auto-refreshed — the user re-runs Re-extract to fold the new doc in. Keeps
    the primary file_name/uploaded_document_path pointing at documents[0]."""
    bid = store.get_bid(bid_id)
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")
    staged = [(f.filename or "upload", await f.read()) for f in files]
    if not staged:
        raise HTTPException(status_code=400, detail="No files uploaded")
    new_docs = _stage_documents(bid_id, staged)
    docs = list(bid.get("documents", [])) + new_docs
    store.set_bid_documents(bid_id, docs)
    primary = docs[0]
    store.update_bid_metadata(
        bid_id, file_name=primary["file_name"], uploaded_document_path=primary["path"],
    )
    return _bid_to_response(bid_id)


class ExtractRequest(BaseModel):
    """Optional body for the extract endpoints. `method` picks the extraction
    path for this one call: "ai_extract" / "ai_query", or null/omitted to use the
    current global default (env baseline or Settings-pane override). Lets the UI
    re-extract a flaky bid with a different method without touching the default."""

    method: Literal["ai_extract", "ai_query"] | None = None


@app.post("/api/bids/{bid_id}/extract-requirements")
def extract_requirements_endpoint(
    bid_id: str, request: ExtractRequest = ExtractRequest(),
) -> dict[str, object]:
    """Phase 2a: pull + classify the non-product requirements. Independent of
    line-item extraction (writes only bid_requirements), so it can run
    concurrently with it. Clear-then-add makes a re-run idempotent (also backs the
    UI's "Re-extract"). Never touches status. ~85s."""
    bid = store.get_bid(bid_id)
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")
    requirements = _extract_requirements_for_bid(bid, _extraction_settings(request.method))
    store.clear_requirements(bid_id)
    if requirements:
        store.add_requirements(bid_id, requirements)
    return _bid_to_response(bid_id)


@app.post("/api/bids/{bid_id}/extract-line-items")
def extract_line_items_endpoint(
    bid_id: str, request: ExtractRequest = ExtractRequest(),
) -> dict[str, object]:
    """Phase 2b: extract the product line items (the slow ~150s pass). Writes only
    bid_line_items (+ status), so it's safe to run concurrently with requirement
    extraction. Clear-then-add makes a re-run idempotent. Advances status to
    "matching" on success; leaves it "uploaded" on failure."""
    bid = store.get_bid(bid_id)
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")
    try:
        lines = _extract_lines_for_bid(bid, _extraction_settings(request.method))
    except Exception:
        logger.exception("Line-item extraction failed for bid %s", bid_id)
        store.update_bid_status(bid_id, "uploaded")
        raise HTTPException(status_code=502, detail="Line-item extraction failed. Check warehouse/model serving configuration.")
    store.clear_line_items(bid_id)
    store.add_line_items(bid_id, lines)
    store.update_bid_status(bid_id, "matching")
    return _bid_to_response(bid_id)


@app.delete("/api/bids/{bid_id}/documents/{doc_id}")
def delete_source_document(bid_id: str, doc_id: str) -> dict[str, object]:
    """Remove a document from a bid at ANY step. A bid must keep at least one
    document. Already-extracted rows from the removed doc are left in place (they
    carry source_doc_id) — refreshed on the next Re-extract, not auto-pruned."""
    bid = store.get_bid(bid_id)
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")
    docs = bid.get("documents", [])
    if len(docs) <= 1:
        raise HTTPException(status_code=422, detail="A bid must keep at least one document.")
    doc = next((d for d in docs if d.get("doc_id") == doc_id), None)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        volumes.delete_volume_file(doc["path"])
    except Exception:
        logger.exception("Volume delete failed for %s (removing from manifest anyway)", doc.get("path"))
    remaining = [d for d in docs if d.get("doc_id") != doc_id]
    store.set_bid_documents(bid_id, remaining)
    # Keep the primary file reference pointing at a doc that still exists.
    primary = remaining[0]
    store.update_bid_metadata(
        bid_id, file_name=primary["file_name"], uploaded_document_path=primary["path"],
    )
    return _bid_to_response(bid_id)


class MatchRequest(BaseModel):
    """Optional match-time filters. `manufacturers` restricts Vector Search to
    those brands' catalog items before ranking (match-ANY across the list) —
    used when a solicitation mandates preferred/awarded manufacturers. Omit or
    empty for unconstrained matching.

    `mode` controls a re-run's scope:
      - "unmatched" (default): match lines not yet resolved by a human. A line
        the reviewer has accepted, overridden, or marked no-catalog-match is left
        untouched; pending / auto-selected lines ARE re-matched, so changing the
        manufacturer filter and re-running actually takes effect.
      - "all": force-clear every line's match state and re-match from scratch,
        discarding manual picks. Callers should confirm this with the user."""

    manufacturers: list[str] = Field(default_factory=list)
    mode: Literal["unmatched", "all"] = "unmatched"


# A line is a deliberate human decision (never clobbered by an "unmatched"
# re-run) when the reviewer accepted/overrode it, or marked it no-catalog-match.
def _is_human_resolved(line: dict[str, object]) -> bool:
    return line.get("review_action") in ("accepted", "overridden") or line.get("resolution") == "no_match"


@app.post("/api/bids/{bid_id}/match")
def match_bid(bid_id: str, request: MatchRequest = MatchRequest()) -> dict[str, object]:
    bid = _bid_to_response(bid_id)
    manufacturers = [m.strip() for m in request.manufacturers if m and m.strip()]
    # "all" wipes every line's match state up front so the skip below never fires
    # — a full re-match from scratch. "unmatched" preserves human decisions.
    if request.mode == "all":
        for line in bid["line_items"]:
            store.clear_line_match(bid_id, line["line_id"])
        bid = _bid_to_response(bid_id)
    for line in bid["line_items"]:
        # Skip lines a human has deliberately resolved (accepted / overridden /
        # no-catalog-match). Pending or auto-selected lines fall through and get
        # fresh candidates — so a manufacturer-filter change re-runs cleanly.
        if _is_human_resolved(line):
            continue
        try:
            candidates = databricks_api.build_weighted_candidates(
                settings, line, bid["customer_id"], manufacturers=manufacturers,
            )
        except Exception as exc:
            logger.exception("Vector Search candidate matching failed for bid %s", bid_id)
            raise HTTPException(
                status_code=502,
                detail="Vector Search unavailable. Check vector search endpoint/index configuration.",
            ) from exc
        store.set_line_candidates(bid_id, line["line_id"], candidates)

        # Guardrail: pre-select + price the top candidate ONLY when it's
        # auto_select_eligible (meets the sensitivity threshold on its unboosted
        # semantic score, hard-compatible, no UOM warning, a real catalog hit).
        # Otherwise leave the line unselected/pending — the reviewer must
        # deliberately pick a product or mark it no-catalog-product. This is the
        # core of the guardrail-first change: no silent low-confidence selection.
        top_candidate = candidates[0] if candidates else None
        if top_candidate and top_candidate["item_code"] and top_candidate.get("auto_select_eligible"):
            priced = databricks_api.propose_price(top_candidate["item_code"], bid["customer_id"])
            store.review_line(
                bid_id, line["line_id"],
                selected_item_code=top_candidate["item_code"],
                proposed_price=priced["proposed_price"] or top_candidate.get("list_price") or 0.0,
                pricing_basis=priced["pricing_basis"],
                review_action="pending",
                reviewer_email=None,
            )
    store.update_bid_status(bid_id, "pending_review")
    return _bid_to_response(bid_id)


class AddLineItemRequest(BaseModel):
    raw_description: str = ""
    qty: int = 1
    uom: str = ""
    given_code: str | None = None


@app.post("/api/bids/{bid_id}/lines")
def add_line_item(bid_id: str, request: AddLineItemRequest) -> dict[str, object]:
    """Manual line item, added for something the parser missed."""
    bid = _bid_to_response(bid_id)
    next_number = max((l["line_number"] for l in bid["line_items"]), default=0) + 1
    new_line = {
        "line_id": f"line-{uuid.uuid4().hex[:8]}",
        "line_number": next_number,
        "raw_description": request.raw_description,
        "qty": request.qty,
        "uom": request.uom,
        "given_code": request.given_code,
    }
    store.add_line_item(bid_id, new_line)
    return _bid_to_response(bid_id)


@app.delete("/api/bids/{bid_id}/lines/{line_id}")
def delete_line_item(bid_id: str, line_id: str) -> dict[str, object]:
    bid = _bid_to_response(bid_id)
    if not any(l["line_id"] == line_id for l in bid["line_items"]):
        raise HTTPException(status_code=404, detail="Line item not found")
    store.delete_line_item(bid_id, line_id)
    return _bid_to_response(bid_id)


@app.patch("/api/bids/{bid_id}/lines/{line_id}")
def update_line_item(bid_id: str, line_id: str, request: UpdateLineItemRequest) -> dict[str, object]:
    """Presenter correction to a line's extracted text, made before matching
    runs. Resets that line's candidates/selection/price server-side (see
    store.update_line_item) so a stale match can never survive a correction."""
    store.update_line_item(
        bid_id, line_id,
        raw_description=request.raw_description,
        qty=request.qty,
        uom=request.uom,
        given_code=request.given_code,
    )
    return _bid_to_response(bid_id)


@app.post("/api/bids/{bid_id}/lines/{line_id}/review")
def review_line(bid_id: str, line_id: str, request: ReviewLineRequest, http_request: Request) -> dict[str, object]:
    store.review_line(
        bid_id, line_id,
        selected_item_code=request.selected_item_code,
        proposed_price=request.proposed_price,
        pricing_basis="reviewer-selected",
        review_action=request.review_action,
        reviewer_email=_seller_email(http_request),
    )
    return _bid_to_response(bid_id)


@app.post("/api/bids/{bid_id}/lines/accept-all")
def accept_all_lines(bid_id: str, http_request: Request) -> dict[str, object]:
    """"Reviewed everything, accept everything" fast path that fully clears the
    list in one click: bulk-accepts every pending line with an auto-select-eligible
    matched candidate (using its current selection/price as-is), AND defaults every
    remaining pending line — guarded, unmatched, low-confidence — to no_match (blank
    in the proposal). Never overwrites an explicit accept/override a reviewer already
    made; the reviewer can still pick a product for any no-matched line afterward.
    Both lists are computed from the same pre-accept snapshot so they don't overlap."""
    bid = _bid_to_response(bid_id)
    reviewer_email = _seller_email(http_request)
    eligible = lines_eligible_for_bulk_accept(bid)
    defaulting = lines_defaulting_to_no_match(bid)
    for line in eligible:
        store.review_line(
            bid_id, line["line_id"],
            selected_item_code=line["selected_item_code"],
            proposed_price=line.get("proposed_price") or 0.0,
            pricing_basis="reviewer-selected",
            review_action="accepted",
            reviewer_email=reviewer_email,
        )
    for line in defaulting:
        store.resolve_no_match(bid_id, line["line_id"], reviewer_email=reviewer_email)
    return _bid_to_response(bid_id)


@app.post("/api/bids/{bid_id}/lines/{line_id}/price")
def reprice_line(bid_id: str, line_id: str, item_code: str | None = None) -> dict[str, object]:
    """Convenience endpoint: given a candidate (or, if omitted, the currently
    top-ranked/already-selected one), compute a proposed price + basis
    without requiring the client to duplicate the pricing rule."""
    bid = _bid_to_response(bid_id)
    line = next((l for l in bid["line_items"] if l["line_id"] == line_id), None)
    if not line:
        raise HTTPException(status_code=404, detail="Line item not found")
    code = item_code or line.get("selected_item_code") or (
        line["candidates"][0]["item_code"] if line["candidates"] else ""
    )
    priced = databricks_api.propose_price(code, bid["customer_id"])
    return {"item_code": code, **priced}


@app.get("/api/bids/{bid_id}/lines/{line_id}/search")
def search_catalog_for_line(
    bid_id: str, line_id: str, q: str,
    manufacturers: list[str] = Query(default_factory=list),
) -> dict[str, object]:
    """Free-text catalog search for manual matching — bypasses
    build_weighted_candidates' specificity gate and history boosting
    entirely, since a manual pick is inherently user-confirmed. Optional
    `manufacturers` (repeatable query param) filters Vector Search to those
    brands before searching (match-ANY)."""
    if not q or not q.strip():
        return {"candidates": []}
    names = [m.strip() for m in manufacturers if m and m.strip()]
    try:
        hits = databricks_api._vector_search_candidates(
            settings, q.strip(), num_results=8, manufacturers=names,
        )
    except Exception as exc:
        logger.exception("Manual catalog search failed for bid %s line %s", bid_id, line_id)
        raise HTTPException(status_code=502, detail="Vector Search unavailable.") from exc
    candidates = [
        {
            "item_code": hit["item_code"],
            "description_long": hit["description_long"],
            "manufacturer_name": hit.get("manufacturer_name"),
            "category": hit.get("category"),
            "list_price": hit.get("list_price"),
            "score": round(float(hit.get("_score") or 0.0), 3),
            "retrieval_score": round(float(hit.get("_retrieval_score", hit.get("_score")) or 0.0), 3),
            "semantic_score": hit.get("_semantic_score"),
            "source": "manual_search",
            "rationale": "Manually searched.",
            "history_snippet": "",
        }
        for hit in hits
    ]
    return {"candidates": candidates}


@app.post("/api/bids/{bid_id}/lines/{line_id}/manual-match")
def manual_match_line(bid_id: str, line_id: str, request: ManualMatchRequest, http_request: Request) -> dict[str, object]:
    """Attach a presenter's manually-searched catalog pick to a line — persists
    it as a candidate (source=manual_search) and selects/prices it in one step."""
    bid = _bid_to_response(bid_id)
    line = next((l for l in bid["line_items"] if l["line_id"] == line_id), None)
    if not line:
        raise HTTPException(status_code=404, detail="Line item not found")

    catalog_row = reference.get_item_catalog_rows([request.item_code]).get(request.item_code)
    if not catalog_row:
        raise HTTPException(status_code=404, detail=f"Unknown catalog item {request.item_code}")

    manual_candidate = {
        "item_code": request.item_code,
        "description_long": catalog_row.get("description_long", ""),
        "manufacturer_name": catalog_row.get("manufacturer_name"),
        "category": catalog_row.get("category"),
        "list_price": catalog_row.get("list_price"),
        "score": 1.0,
        "source": "manual_search",
        "rationale": "Manually selected by reviewer.",
        "history_snippet": "",
    }
    existing = [c for c in line["candidates"] if c["item_code"] != request.item_code]
    store.set_line_candidates(bid_id, line_id, existing + [manual_candidate])

    priced = databricks_api.propose_price(request.item_code, bid["customer_id"])
    store.review_line(
        bid_id, line_id,
        selected_item_code=request.item_code,
        proposed_price=priced["proposed_price"] or catalog_row.get("list_price") or 0.0,
        pricing_basis=priced["pricing_basis"],
        review_action="overridden",
        reviewer_email=_seller_email(http_request),
    )
    return _bid_to_response(bid_id)


@app.post("/api/bids/{bid_id}/lines/{line_id}/no-match")
def resolve_no_match(bid_id: str, line_id: str, http_request: Request) -> dict[str, object]:
    """Mark a line as having no catalog match. Clears any code/price and sets
    resolution=no_match. The line becomes a resolved decision — it no longer
    blocks submission, and renders BLANK (unpriced) in the generated proposal.
    No reason required (simplified from the earlier NO-BID flow)."""
    bid = _bid_to_response(bid_id)
    if not any(l["line_id"] == line_id for l in bid["line_items"]):
        raise HTTPException(status_code=404, detail="Line item not found")
    store.resolve_no_match(bid_id, line_id, reviewer_email=_seller_email(http_request))
    return _bid_to_response(bid_id)


@app.get("/api/catalog/manufacturers")
def catalog_manufacturers() -> dict[str, object]:
    """Distinct manufacturer names in the item catalog — populates the Match-step
    manufacturer filter dropdowns (auto-match + manual catalog search)."""
    return {"manufacturers": reference.get_manufacturers()}


@app.get("/api/responsibility-matrix")
def responsibility_matrix() -> dict[str, object]:
    """The BRD Glossary matrix (terms -> owning teams + default risk) plus the
    team and status option lists — the single source of truth the requirements
    table's Team->Term cascade and dropdowns read from. Now the SEEDED matrix
    with any user edits from the Compliance Matrix page merged in."""
    return reference.matrix_payload()


@app.put("/api/responsibility-matrix/terms")
def upsert_matrix_term(request: MatrixTermUpsertRequest) -> dict[str, object]:
    """Add or edit a matrix term (Compliance Matrix page). Returns the full
    merged payload so the client can replace its matrix state in one shot."""
    try:
        return reference.upsert_matrix_term(
            term_label=request.term_label,
            owning_teams=request.owning_teams,
            default_risk=request.default_risk,
            description=request.description,
            is_trigger=request.is_trigger,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/responsibility-matrix/terms")
def delete_matrix_term(request: MatrixTermDeleteRequest) -> dict[str, object]:
    """Remove a matrix overlay row (seeded term reverts to its BRD default; a
    custom term disappears). Returns the merged payload."""
    return reference.delete_matrix_term(request.term_label)


@app.patch("/api/bids/{bid_id}/requirements/{requirement_id}")
def update_requirement(
    bid_id: str, requirement_id: str, request: UpdateRequirementRequest, http_request: Request,
) -> dict[str, object]:
    """Partial edit to one requirement: reclassify risk/team(s), change status,
    correct the term/clause, or leave a note. Only provided fields change; the
    signed-in reviewer + timestamp are stamped on every edit."""
    bid = _bid_to_response(bid_id)
    if not any(r["requirement_id"] == requirement_id for r in bid.get("requirements", [])):
        raise HTTPException(status_code=404, detail="Requirement not found")
    store.update_requirement(
        bid_id, requirement_id,
        fields=request.model_dump(exclude_unset=True),
        updated_by=_seller_email(http_request),
    )
    return _bid_to_response(bid_id)


@app.post("/api/bids/{bid_id}/requirements")
def add_requirement(bid_id: str, request: AddRequirementRequest, http_request: Request) -> dict[str, object]:
    """Add a requirement the AI missed. term_label is a matrix term; owning_teams
    and risk are sent from the client (pre-filled from that term, overridable)."""
    _bid_to_response(bid_id)  # 404s if the bid doesn't exist
    requirement = {
        "requirement_id": f"req-{uuid.uuid4().hex[:8]}",
        "term_label": request.term_label,
        "raw_text": request.raw_text,
        "category": request.category,
        "owning_teams": request.owning_teams,
        "risk_level": request.risk_level,
        "source": "manual",
    }
    store.add_requirement(bid_id, requirement, updated_by=_seller_email(http_request))
    return _bid_to_response(bid_id)


@app.delete("/api/bids/{bid_id}/requirements/{requirement_id}")
def delete_requirement(bid_id: str, requirement_id: str) -> dict[str, object]:
    bid = _bid_to_response(bid_id)
    if not any(r["requirement_id"] == requirement_id for r in bid.get("requirements", [])):
        raise HTTPException(status_code=404, detail="Requirement not found")
    store.delete_requirement(bid_id, requirement_id)
    return _bid_to_response(bid_id)


@app.post("/api/bids/{bid_id}/submit")
def submit_bid(bid_id: str) -> dict[str, object]:
    bid = _bid_to_response(bid_id)
    blocking = validate_bid_ready_for_submission(bid)
    if blocking:
        raise HTTPException(status_code=422, detail={
            "error": "incomplete_lines",
            "message": f"{len(blocking)} of {len(bid['line_items'])} line item(s) are not ready to submit.",
            "blocking_lines": blocking,
        })
    pdf_bytes = documents.render_proposal_pdf(bid)
    excel_bytes = documents.render_customer_submission_excel(bid)

    pdf_path = f"{settings.generated_proposals_path}/{bid_id}/proposal.pdf"
    excel_path = f"{settings.generated_proposals_path}/{bid_id}/customer_submission.xlsx"
    try:
        volumes.write_volume_file(pdf_path, pdf_bytes)
        volumes.write_volume_file(excel_path, excel_bytes)
    except Exception:
        logger.exception("Could not persist generated proposal documents to Volume for bid %s", bid_id)

    store.finalize_bid(bid_id, pdf_path=pdf_path, excel_path=excel_path)
    return {
        "bid": _bid_to_response(bid_id),
        "proposal_pdf_url": f"/api/bids/{bid_id}/documents/pdf",
        "proposal_excel_url": f"/api/bids/{bid_id}/documents/excel",
    }


@app.get("/api/bids/{bid_id}/documents/{doc_type}")
def download_bid_document(bid_id: str, doc_type: str, inline: bool = False) -> Response:
    bid = _bid_to_response(bid_id)
    if doc_type == "pdf":
        content = documents.render_proposal_pdf(bid)
        # `inline` lets the frontend embed this in an <iframe> for an in-browser
        # preview before download. Browsers only render a PDF response inline
        # this way — an attachment-disposition response just triggers a save
        # dialog / blank frame instead of previewing.
        disposition = "inline" if inline else "attachment"
        return StreamingResponse(iter([content]), media_type="application/pdf", headers={
            "Content-Disposition": f'{disposition}; filename="{bid_id}_proposal.pdf"'
        })
    if doc_type == "excel":
        content = documents.render_customer_submission_excel(bid)
        return StreamingResponse(
            iter([content]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{bid_id}_submission.xlsx"'},
        )
    if doc_type == "original":
        path = bid.get("uploaded_document_path")
        if not path:
            raise HTTPException(status_code=404, detail="Original document not available for this bid")
        try:
            content = volumes.read_volume_file(path)
        except Exception as exc:
            logger.exception("Could not read original document for bid %s at %s", bid_id, path)
            raise HTTPException(status_code=502, detail="Could not read the original document from the Volume") from exc
        return StreamingResponse(iter([content]), media_type="application/octet-stream", headers={
            "Content-Disposition": f'attachment; filename="{bid["file_name"]}"'
        })
    raise HTTPException(status_code=404, detail=f"Unknown document type {doc_type}")


@app.get("/api/bids/{bid_id}/documents/original/{doc_id}")
def download_source_document(bid_id: str, doc_id: str, inline: bool = False) -> Response:
    """Stream one of a bid's original source documents from the Volume. Two path
    segments (`original/{doc_id}`), so this never collides with the single-segment
    `{doc_type}` route above. PDFs are served inline (for the frontend viewer's
    <iframe>); everything else downloads as an attachment."""
    bid = _bid_to_response(bid_id)
    doc = next((d for d in bid.get("documents", []) if d.get("doc_id") == doc_id), None)
    if not doc:
        raise HTTPException(status_code=404, detail="Source document not found for this bid")
    try:
        content = volumes.read_volume_file(doc["path"])
    except Exception as exc:
        logger.exception("Could not read source document %s for bid %s at %s", doc_id, bid_id, doc["path"])
        raise HTTPException(status_code=502, detail="Could not read the document from the Volume") from exc
    media_type = _media_type_for(doc["file_name"])
    disposition = "inline" if (inline and media_type == "application/pdf") else "attachment"
    return StreamingResponse(iter([content]), media_type=media_type, headers={
        "Content-Disposition": f'{disposition}; filename="{doc["file_name"]}"'
    })


@app.get("/api/bids")
def list_bids() -> dict[str, object]:
    return {"bids": store.list_bids()}


@app.get("/api/bids/{bid_id}")
def get_bid(bid_id: str) -> dict[str, object]:
    return _bid_to_response(bid_id)
