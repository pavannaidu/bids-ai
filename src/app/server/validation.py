"""Pure business-rule validation, kept free of any FastAPI/framework import so
it can be unit-tested without constructing the full app (and its multipart-
upload route) — see src/app/tests/test_submission_validation.py."""

from __future__ import annotations

from typing import Any


def validate_bid_ready_for_submission(bid: dict[str, Any]) -> list[dict[str, Any]]:
    """Authoritative submission gate (the UI's SubmitBar check is convenience
    only). Each line must be RESOLVED one of two ways:
      - catalog_match: a real catalog selection + a valid non-negative price;
      - no_match: a reviewer decided the catalog has no fit (no code/price; the
        line renders blank in the proposal).
    A pending line (no reviewer decision) always blocks."""
    blocking: list[dict[str, Any]] = []
    for line in bid["line_items"]:
        reasons: list[str] = []
        resolution = line.get("resolution") or (
            "catalog_match" if line.get("selected_item_code") else "pending"
        )
        if resolution == "no_match":
            # A resolved no-match line needs nothing further — never blocks.
            pass
        else:
            # Treat anything not explicitly resolved as needing a catalog match.
            if not line.get("selected_item_code"):
                reasons.append("No catalog item selected")
            if line.get("proposed_price") is None or line["proposed_price"] < 0:
                reasons.append("No valid non-negative price")
            if line.get("review_action", "pending") == "pending":
                reasons.append("Not yet reviewed")
        if reasons:
            blocking.append({"line_id": line["line_id"], "line_number": line["line_number"], "reasons": reasons})
    return blocking


def lines_eligible_for_bulk_accept(bid: dict[str, Any]) -> list[dict[str, Any]]:
    """Lines an "Accept eligible matches" action may touch: still pending, matched
    to a catalog item, AND that selected candidate is auto_select_eligible (meets
    the sensitivity threshold, hard-compatible, no UOM/soft warning). Guarded
    lines (below threshold, incompatible, UOM mismatch, low-specificity) are NEVER
    bulk-accepted — a reviewer must select or mark them no-product deliberately.
    This is the authoritative server-side rule; UI filtering is convenience only."""
    eligible = []
    for line in bid["line_items"]:
        if line.get("review_action", "pending") != "pending":
            continue
        selected = line.get("selected_item_code")
        if not selected:
            continue
        candidate = next(
            (c for c in line.get("candidates", []) if c.get("item_code") == selected), None
        )
        if candidate and candidate.get("auto_select_eligible"):
            eligible.append(line)
    return eligible


def lines_defaulting_to_no_match(bid: dict[str, Any]) -> list[dict[str, Any]]:
    """The pending lines "Accept all" DOESN'T catalog-accept — i.e. the guarded /
    unmatched leftovers `lines_eligible_for_bulk_accept` leaves behind. Accept-all
    defaults these to no_match so one click resolves the whole list; a reviewer can
    still pick a product for any of them afterward. A line counts here when it's
    still pending, isn't already resolved no_match, and isn't catalog-eligible."""
    eligible_ids = {line["line_id"] for line in lines_eligible_for_bulk_accept(bid)}
    defaulting = []
    for line in bid["line_items"]:
        if line.get("review_action", "pending") != "pending":
            continue
        if line.get("resolution") == "no_match":
            continue
        if line["line_id"] in eligible_ids:
            continue
        defaulting.append(line)
    return defaulting
