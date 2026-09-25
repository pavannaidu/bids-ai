"""Reference-data access, dispatching to Lakebase (when configured) or an
in-process fallback built from the shared synthetic dataset (local dev)."""

from __future__ import annotations

import uuid
from typing import Any

from . import lakebase

_fallback_catalog: list[dict[str, Any]] | None = None
_fallback_customers: list[dict[str, Any]] | None = None
_fallback_historical: list[dict[str, Any]] | None = None
_fallback_purchase: list[dict[str, Any]] | None = None

# Accounts created from the app when Lakebase isn't configured (local dev /
# tests). The Lakebase path persists to the bids.app_customers table instead;
# either way get_customers() merges these on top of the seeded/synced list.
_app_customers: list[dict[str, Any]] = []

# Defaults for the "name only" quick-add form: a well-formed account row that
# matching/pricing can consume (they only soft-boost on customer_id, so the
# division/type/region just need to be present and valid).
_NEW_ACCOUNT_DEFAULTS = {
    "division_id": "DIV-CORE",
    "customer_type": "Unspecified",
    "region": "Unspecified",
}

# Editable responsibility-matrix overrides for the non-Lakebase path (local dev
# / tests), keyed by term_label. The Lakebase path persists to the
# bids.matrix_term_overrides table instead; either way matrix_payload() merges
# these on top of the seeded BRD matrix.
_matrix_overrides: dict[str, dict[str, Any]] = {}
_VALID_RISKS = frozenset({"high", "medium", "low"})


def _ensure_fallback() -> None:
    global _fallback_catalog, _fallback_customers, _fallback_historical, _fallback_purchase
    if _fallback_catalog is not None:
        return
    from ._shared_data.demo_data import (
        CUSTOMERS,
        build_customer_purchase_history_rows,
        build_historical_bid_rows,
        build_item_catalog_rows,
    )

    _fallback_catalog = build_item_catalog_rows()
    _fallback_customers = list(CUSTOMERS)
    _fallback_historical = build_historical_bid_rows(_fallback_catalog)
    _fallback_purchase = build_customer_purchase_history_rows(_fallback_catalog)


def get_customers() -> list[dict[str, Any]]:
    """The seeded accounts plus any created from the app, merged. App-created
    accounts are appended after the seeded list."""
    if lakebase.lakebase_configured():
        return lakebase.get_customers() + lakebase.get_app_customers()
    _ensure_fallback()
    return (_fallback_customers or []) + _app_customers


def get_customer(customer_id: str) -> dict[str, Any] | None:
    return next((c for c in get_customers() if c.get("customer_id") == customer_id), None)


def create_customer(name: str) -> dict[str, Any]:
    """Create a new account from a name (the "quick add" flow). Generates a
    collision-safe customer_id and fills in default division/type/region so the
    row is well-formed for matching/pricing. Persists to Lakebase when
    configured, else an in-process list (local dev / tests)."""
    # CUST-<hex8> can't collide with the seeded CUST-10xx ids.
    customer = {
        "customer_id": f"CUST-{uuid.uuid4().hex[:8]}",
        "customer_name": name,
        **_NEW_ACCOUNT_DEFAULTS,
    }
    if lakebase.lakebase_configured():
        lakebase.create_app_customer(**customer)
    else:
        _app_customers.append(customer)
    return customer


# --------------------------------------------------------------------------- #
# Responsibility matrix (editable overlay on the seeded BRD matrix)
#
# The seeded matrix (RESPONSIBILITY_MATRIX in _shared_data) is authoritative for
# upload-time auto-detection + the material/immaterial banner, which read it
# directly and are NOT affected here. matrix_payload() below is what the Matrix
# PAGE and the Extract-step routing dropdowns read — this is where user edits
# merge in. Overrides are keyed by term_label: is_custom=False replaces a seeded
# term's team/risk/category in place; is_custom=True appends a new term.
# --------------------------------------------------------------------------- #


def get_matrix_overrides() -> list[dict[str, Any]]:
    if lakebase.lakebase_configured():
        return lakebase.get_matrix_overrides()
    return list(_matrix_overrides.values())


def matrix_payload() -> dict[str, Any]:
    """The seeded BRD matrix with user overrides applied. Same shape as
    responsibility_matrix.matrix_payload() ({terms, teams, statuses}) plus a
    per-term `origin` (seeded | seeded_override | custom) so the UI can offer
    Reset vs Remove."""
    from ._shared_data.responsibility_matrix import matrix_payload as seeded_payload

    base = seeded_payload()
    overrides = {o["term_label"]: o for o in get_matrix_overrides()}

    terms: list[dict[str, Any]] = []
    for term in base["terms"]:
        ov = overrides.get(term["term_label"])
        if ov and not ov.get("is_custom"):
            terms.append({
                "term_label": term["term_label"],
                "owning_teams": list(ov.get("owning_teams") or []),
                "default_risk": ov.get("default_risk") or term["default_risk"],
                # An edited description overrides the seeded one; the curated
                # risk_rationale isn't an override column, so it survives from
                # the seeded term.
                "description": ov.get("description") or term["description"],
                "risk_rationale": term.get("risk_rationale", ""),
                # Whether this term makes a bid material (Extract-step banner).
                # The override row's flag wins over the seeded default.
                "is_trigger": bool(ov.get("is_trigger")),
                "origin": "seeded_override",
            })
        else:
            terms.append({**term, "origin": "seeded"})

    # Append custom (user-added) terms not present in the seeded set.
    for ov in overrides.values():
        if ov.get("is_custom"):
            terms.append({
                "term_label": ov["term_label"],
                "owning_teams": list(ov.get("owning_teams") or []),
                "default_risk": ov.get("default_risk") or "medium",
                "description": ov.get("description") or "",
                "risk_rationale": "",
                "is_trigger": bool(ov.get("is_trigger")),
                "origin": "custom",
            })

    return {"terms": terms, "teams": base["teams"], "statuses": base["statuses"]}


def trigger_terms() -> set[str]:
    """The set of term_labels flagged as material triggers in the MERGED matrix
    (seeded defaults + user overrides). Passed into compute_review_verdict so the
    Extract-step Material/Immaterial banner reflects the editable trigger config."""
    return {t["term_label"] for t in matrix_payload()["terms"] if t.get("is_trigger")}


def upsert_matrix_term(
    *, term_label: str, owning_teams: list[str], default_risk: str, description: str,
    is_trigger: bool = False,
) -> dict[str, Any]:
    """Add or edit a matrix term. Validates inputs, decides override-vs-custom
    from the seeded label set, persists, and returns the full merged payload.
    The `description` feeds ai_classify at upload time — editing it (or adding a
    custom term) changes how future uploads classify (see classify_requirements).
    `is_trigger` controls whether the term makes a bid material (Extract banner)."""
    from ._shared_data.responsibility_matrix import TEAMS, TERM_LABELS

    label = (term_label or "").strip()
    if not label:
        raise ValueError("Term label is required")
    if default_risk not in _VALID_RISKS:
        raise ValueError(f"Invalid risk level {default_risk!r}")
    unknown = [t for t in owning_teams if t not in TEAMS]
    if unknown:
        raise ValueError(f"Unknown owning team(s): {', '.join(unknown)}")

    is_custom = label not in TERM_LABELS
    row = {
        "term_label": label,
        "owning_teams": list(owning_teams),
        "default_risk": default_risk,
        "description": (description or "").strip(),
        "is_trigger": bool(is_trigger),
        "is_custom": is_custom,
    }
    if lakebase.lakebase_configured():
        lakebase.upsert_matrix_override(**row)
    else:
        _matrix_overrides[label] = row
    return matrix_payload()


def delete_matrix_term(term_label: str) -> dict[str, Any]:
    """Remove an overlay row: a seeded term reverts to its BRD default; a custom
    term disappears. Returns the merged payload."""
    label = (term_label or "").strip()
    if lakebase.lakebase_configured():
        lakebase.delete_matrix_override(label)
    else:
        _matrix_overrides.pop(label, None)
    return matrix_payload()


def get_item_catalog_rows(item_codes: list[str]) -> dict[str, dict[str, Any]]:
    if lakebase.lakebase_configured():
        return lakebase.get_item_catalog_rows(item_codes)
    _ensure_fallback()
    lookup = {row["item_code"]: row for row in (_fallback_catalog or [])}
    return {code: lookup[code] for code in item_codes if code in lookup}


def get_manufacturers() -> list[str]:
    """Distinct, sorted manufacturer names in the active catalog — the option
    list for the Match-step manufacturer filter (Vector Search pre-filter)."""
    if lakebase.lakebase_configured():
        return lakebase.get_catalog_manufacturers()
    _ensure_fallback()
    names = {
        (row.get("manufacturer_name") or "").strip()
        for row in (_fallback_catalog or [])
        if row.get("is_active", True)
    }
    return sorted(n for n in names if n)


def get_historical_bids_for_items(item_codes: list[str], customer_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    if lakebase.lakebase_configured():
        return lakebase.get_historical_bids_for_items(item_codes, customer_id)
    _ensure_fallback()
    out: dict[str, list[dict[str, Any]]] = {}
    for row in _fallback_historical or []:
        if row["item_code"] not in item_codes:
            continue
        if customer_id and row["customer_id"] != customer_id:
            continue
        out.setdefault(row["item_code"], []).append(row)
    return out


def get_purchase_history_for_items(item_codes: list[str], customer_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    if lakebase.lakebase_configured():
        return lakebase.get_purchase_history_for_items(item_codes, customer_id)
    _ensure_fallback()
    out: dict[str, list[dict[str, Any]]] = {}
    for row in _fallback_purchase or []:
        if row["item_code"] not in item_codes:
            continue
        if customer_id and row["customer_id"] != customer_id:
            continue
        out.setdefault(row["item_code"], []).append(row)
    return out
