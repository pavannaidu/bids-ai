"""In-memory fallback transactional store, used when Lakebase isn't configured
(local dev / tests). Same method surface as lakebase.LakebaseBidStore."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

# Earlier rows used a narrower status vocabulary; map those to the nearest value
# in the current review-workflow enum when reading them back.
_LEGACY_STATUS_MAP = {"acknowledged": "approved", "routed": "in_review"}


def coerce_requirement_status(status: str | None) -> str:
    """Normalize a stored review_status to the current enum (see models.py)."""
    if not status:
        return "pending"
    return _LEGACY_STATUS_MAP.get(status, status)


class InMemoryBidStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bids: dict[str, dict[str, Any]] = {}
        self._lines: dict[str, dict[str, dict[str, Any]]] = {}  # bid_id -> line_id -> line
        self._requirements: dict[str, dict[str, dict[str, Any]]] = {}  # bid_id -> requirement_id -> requirement

    def create_bid(
        self, *, bid_id: str, file_name: str, customer_id: str, customer_name: str,
        solicitation_ref: str, due_date: str, uploaded_document_path: str, bid_name: str = "",
        documents: list[dict[str, Any]] | None = None,
    ) -> None:
        with self._lock:
            self._bids[bid_id] = {
                "bid_id": bid_id,
                "file_name": file_name,
                "bid_name": bid_name,
                "customer_id": customer_id,
                "customer_name": customer_name,
                "solicitation_ref": solicitation_ref,
                "due_date": due_date,
                "status": "parsing",
                "proposal_pdf_path": None,
                "proposal_excel_path": None,
                "uploaded_document_path": uploaded_document_path,
                "documents": list(documents or []),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._lines[bid_id] = {}
            self._requirements[bid_id] = {}

    def list_bids(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            summaries = [
                {
                    "bid_id": b["bid_id"],
                    "file_name": b["file_name"],
                    "bid_name": b["bid_name"],
                    "customer_name": b["customer_name"],
                    "status": b["status"],
                    "due_date": b["due_date"],
                    "created_at": b["created_at"],
                    "line_item_count": len(self._lines.get(b["bid_id"], {})),
                }
                for b in self._bids.values()
            ]
            # created_at is always an isoformat() UTC string from the same call
            # site above, so lexicographic sort is chronologically correct here.
            summaries.sort(key=lambda s: s["created_at"], reverse=True)
            return summaries[:limit]

    @staticmethod
    def _new_line_row(bid_id: str, line: dict[str, Any], *, default_method: str) -> dict[str, Any]:
        return {
            "line_id": line["line_id"],
            "bid_id": bid_id,
            "line_number": line["line_number"],
            "raw_description": line.get("raw_description", ""),
            "qty": line.get("qty", 1),
            "uom": line.get("uom", ""),
            "given_code": line.get("given_code"),
            "candidates": [],
            "selected_item_code": None,
            "proposed_price": None,
            "pricing_basis": "",
            "review_action": "pending",
            "reviewer_email": None,
            "resolution": "pending",
            # Source-traceability: which uploaded file/page this came from and how.
            "source_doc_id": line.get("source_doc_id"),
            "source_filename": line.get("source_filename"),
            "source_page": line.get("source_page"),
            "extraction_method": line.get("extraction_method", default_method),
            "confidence": line.get("confidence"),
        }

    def add_line_items(self, bid_id: str, lines: list[dict[str, Any]]) -> None:
        with self._lock:
            for line in lines:
                self._lines[bid_id][line["line_id"]] = self._new_line_row(
                    bid_id, line, default_method="ai_extract",
                )

    def add_line_item(self, bid_id: str, line: dict[str, Any]) -> None:
        with self._lock:
            self._lines[bid_id][line["line_id"]] = self._new_line_row(
                bid_id, line, default_method="manual",
            )

    def delete_line_item(self, bid_id: str, line_id: str) -> None:
        with self._lock:
            self._lines[bid_id].pop(line_id, None)

    def _new_requirement_row(self, bid_id: str, req: dict[str, Any], seq: int) -> dict[str, Any]:
        return {
            "requirement_id": req["requirement_id"],
            "bid_id": bid_id,
            "seq": seq,
            "term_label": req["term_label"],
            "raw_text": req.get("raw_text", ""),
            "category": req.get("category", ""),
            "owning_teams": list(req.get("owning_teams") or []),
            "risk_level": req.get("risk_level", "medium"),
            "risk_rationale": req.get("risk_rationale", ""),
            "matched_term": req.get("matched_term"),
            "source": req.get("source", "matrix"),
            "review_status": "pending",
            "note": "",
            "assigned_to": None,
            "last_updated_by": None,
            "last_updated_at": None,
            # Source-traceability: which uploaded file/page this clause came from
            # and how it was extracted (distinct from `source`, which is routing).
            "source_doc_id": req.get("source_doc_id"),
            "source_filename": req.get("source_filename"),
            "source_page": req.get("source_page"),
            "extraction_method": req.get("extraction_method", "ai_extract"),
            "confidence": req.get("confidence"),
        }

    def add_requirements(self, bid_id: str, requirements: list[dict[str, Any]]) -> None:
        with self._lock:
            bucket = self._requirements.setdefault(bid_id, {})
            # Continue seq past whatever's already there (defensive — the extract
            # flow clears first, but this keeps a stray double-add collision-free).
            base = max((r["seq"] for r in bucket.values()), default=0)
            for i, req in enumerate(requirements, start=1):
                bucket[req["requirement_id"]] = self._new_requirement_row(bid_id, req, base + i)

    def clear_line_items(self, bid_id: str) -> None:
        with self._lock:
            self._lines[bid_id] = {}

    def clear_requirements(self, bid_id: str) -> None:
        with self._lock:
            self._requirements[bid_id] = {}

    def set_bid_documents(self, bid_id: str, documents: list[dict[str, Any]]) -> None:
        with self._lock:
            self._bids[bid_id]["documents"] = list(documents)

    def update_bid_metadata(
        self, bid_id: str, *, bid_name: str | None = None, due_date: str | None = None,
        customer_id: str | None = None, customer_name: str | None = None,
        file_name: str | None = None, uploaded_document_path: str | None = None,
    ) -> None:
        """Partial update of a bid's editable metadata (Upload step). Only the
        provided (non-None) fields are changed."""
        with self._lock:
            bid = self._bids.get(bid_id)
            if not bid:
                return
            for key, value in (
                ("bid_name", bid_name), ("due_date", due_date),
                ("customer_id", customer_id), ("customer_name", customer_name),
                ("file_name", file_name), ("uploaded_document_path", uploaded_document_path),
            ):
                if value is not None:
                    bid[key] = value

    def add_requirement(self, bid_id: str, requirement: dict[str, Any], *, updated_by: str | None) -> None:
        """A single manually-added requirement, appended after the existing ones."""
        with self._lock:
            bucket = self._requirements.setdefault(bid_id, {})
            next_seq = max((r["seq"] for r in bucket.values()), default=0) + 1
            row = self._new_requirement_row(bid_id, requirement, next_seq)
            row["source"] = requirement.get("source", "manual")
            row["extraction_method"] = requirement.get("extraction_method", "manual")
            row["last_updated_by"] = updated_by
            row["last_updated_at"] = datetime.now(timezone.utc).isoformat()
            bucket[requirement["requirement_id"]] = row

    def update_requirement(
        self, bid_id: str, requirement_id: str, *, fields: dict[str, Any], updated_by: str | None,
    ) -> None:
        """Partial update of any editable requirement field, always stamping the
        reviewer + timestamp. Unknown/None fields are ignored."""
        with self._lock:
            req = self._requirements.get(bid_id, {}).get(requirement_id)
            if not req:
                return
            for key in ("term_label", "raw_text", "category", "risk_level", "review_status", "note"):
                if fields.get(key) is not None:
                    req[key] = fields[key]
            if fields.get("owning_teams") is not None:
                req["owning_teams"] = list(fields["owning_teams"])
            req["last_updated_by"] = updated_by
            req["last_updated_at"] = datetime.now(timezone.utc).isoformat()

    def delete_requirement(self, bid_id: str, requirement_id: str) -> None:
        with self._lock:
            self._requirements.get(bid_id, {}).pop(requirement_id, None)

    def set_line_candidates(self, bid_id: str, line_id: str, candidates: list[dict[str, Any]]) -> None:
        with self._lock:
            self._lines[bid_id][line_id]["candidates"] = candidates

    def update_line_item(
        self, bid_id: str, line_id: str, *, raw_description: str, qty: int, uom: str, given_code: str | None,
    ) -> None:
        with self._lock:
            line = self._lines[bid_id][line_id]
            line["raw_description"] = raw_description
            line["qty"] = qty
            line["uom"] = uom
            line["given_code"] = given_code
            # A corrected description invalidates whatever was matched against
            # the old (possibly wrong) text — reset downstream match/review
            # state so the next /match call re-processes this line.
            line["candidates"] = []
            line["selected_item_code"] = None
            line["proposed_price"] = None
            line["pricing_basis"] = ""
            line["review_action"] = "pending"
            line["reviewer_email"] = None
            line["resolution"] = "pending"

    def clear_line_match(self, bid_id: str, line_id: str) -> None:
        """Mirror of LakebaseBidStore.clear_line_match — reset a line's
        match/review state so the next /match re-processes it (used by a
        'Re-match all' re-run)."""
        with self._lock:
            line = self._lines[bid_id][line_id]
            line["candidates"] = []
            line["selected_item_code"] = None
            line["proposed_price"] = None
            line["pricing_basis"] = ""
            line["review_action"] = "pending"
            line["reviewer_email"] = None
            line["resolution"] = "pending"

    def update_bid_status(self, bid_id: str, status: str) -> None:
        with self._lock:
            self._bids[bid_id]["status"] = status

    def review_line(
        self, bid_id: str, line_id: str, *, selected_item_code: str, proposed_price: float,
        pricing_basis: str, review_action: str, reviewer_email: str | None,
    ) -> None:
        with self._lock:
            line = self._lines[bid_id][line_id]
            line["selected_item_code"] = selected_item_code
            line["proposed_price"] = proposed_price
            line["pricing_basis"] = pricing_basis
            line["review_action"] = review_action
            line["reviewer_email"] = reviewer_email
            line["resolution"] = "catalog_match"

    def resolve_no_match(
        self, bid_id: str, line_id: str, *, reviewer_email: str | None,
    ) -> None:
        """Mirror of LakebaseBidStore.resolve_no_match for the in-memory store."""
        with self._lock:
            line = self._lines[bid_id][line_id]
            line["selected_item_code"] = None
            line["proposed_price"] = None
            line["pricing_basis"] = ""
            line["review_action"] = "overridden"
            line["reviewer_email"] = reviewer_email
            line["resolution"] = "no_match"

    def finalize_bid(self, bid_id: str, *, pdf_path: str, excel_path: str) -> None:
        with self._lock:
            self._bids[bid_id]["status"] = "submitted"
            self._bids[bid_id]["proposal_pdf_path"] = pdf_path
            self._bids[bid_id]["proposal_excel_path"] = excel_path

    def get_bid(self, bid_id: str) -> dict[str, Any] | None:
        with self._lock:
            if bid_id not in self._bids:
                return None
            bid = dict(self._bids[bid_id])
            # Synthesize a 1-element documents array for bids created via the old
            # single-doc signature (mirrors LakebaseBidStore.get_bid).
            if not bid.get("documents") and bid.get("uploaded_document_path"):
                file_name = bid["file_name"]
                bid["documents"] = [{
                    "doc_id": "doc-legacy",
                    "file_name": file_name,
                    "path": bid["uploaded_document_path"],
                    "file_format": (file_name.rsplit(".", 1)[-1] if "." in file_name else "").lower(),
                }]
            bid["line_items"] = sorted(self._lines[bid_id].values(), key=lambda line: line["line_number"])
            requirements = sorted(
                self._requirements.get(bid_id, {}).values(), key=lambda req: req.get("seq", 0),
            )
            for req in requirements:
                req["review_status"] = coerce_requirement_status(req.get("review_status"))
            bid["requirements"] = requirements
            return bid
