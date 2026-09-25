"""Editable responsibility-matrix overlay (Compliance Matrix page).

Lakebase isn't configured under tests, so reference.* takes the in-process
fallback path (_matrix_overrides dict). Editing a term via the overlay changes
the MERGED matrix_payload() — and, since classification is now ai_classify into
that merged taxonomy, matrix edits ALSO drive upload-time routing (see
test_requirement_routing.test_matrix_override_changes_classification). The
material/immaterial banner (compute_review_verdict) keys on matched_term in the
seeded REVIEW_TRIGGER_TERMS, so it still fires for a classified trigger term
regardless of who the term is re-owned to.
"""

from __future__ import annotations

import pytest

from server import reference
from server._shared_data.responsibility_matrix import (
    TEAM_HR,
    TEAM_LEGAL,
    TEAM_RISK,
    compute_review_verdict,
)
from server.config import get_settings

SETTINGS = get_settings()


@pytest.fixture(autouse=True)
def _clean_overrides():
    saved = dict(reference._matrix_overrides)
    reference._matrix_overrides.clear()
    yield
    reference._matrix_overrides.clear()
    reference._matrix_overrides.update(saved)


def _term(payload: dict, label: str) -> dict:
    return next(t for t in payload["terms"] if t["term_label"] == label)


def test_seeded_terms_have_origin_seeded_by_default():
    payload = reference.matrix_payload()
    indemnification = _term(payload, "Indemnification")
    assert indemnification["origin"] == "seeded"
    assert indemnification["owning_teams"] == [TEAM_LEGAL]


def test_override_updates_teams_risk_and_description_in_merged_payload():
    reference.upsert_matrix_term(
        term_label="Indemnification", owning_teams=[TEAM_HR], default_risk="low",
        description="Custom description for indemnification.",
    )
    edited = _term(reference.matrix_payload(), "Indemnification")
    assert edited["owning_teams"] == [TEAM_HR]
    assert edited["default_risk"] == "low"
    assert edited["description"] == "Custom description for indemnification."
    assert edited["origin"] == "seeded_override"
    # The curated risk_rationale survives an override (it's not an override column).
    assert edited["risk_rationale"]


def test_seeded_override_keeps_risk_rationale_from_seed():
    reference.upsert_matrix_term(
        term_label="Most Favored Nation", owning_teams=[TEAM_HR], default_risk="low", description="",
    )
    edited = _term(reference.matrix_payload(), "Most Favored Nation")
    # Empty override description falls back to the seeded description.
    assert edited["description"]
    assert edited["risk_rationale"]


def test_banner_trigger_logic_keys_on_matched_term_not_ownership():
    """Re-owning a trigger term doesn't change the banner: it keys on matched_term
    membership in the seeded REVIEW_TRIGGER_TERMS, not on who owns the term."""
    reference.upsert_matrix_term(
        term_label="Anti-Trust Violations", owning_teams=[TEAM_HR], default_risk="low", description="",
    )
    verdict = compute_review_verdict([
        {"matched_term": "Anti-Trust Violations", "term_label": "Anti-Trust Violations",
         "owning_teams": [TEAM_HR]},
    ])
    assert verdict["material"] is True
    assert "Anti-Trust Violations" in verdict["trigger_terms"]


def test_add_custom_term_appears_with_origin_custom():
    before = len(reference.matrix_payload()["terms"])
    reference.upsert_matrix_term(
        term_label="Data Privacy Addendum", owning_teams=[TEAM_LEGAL, TEAM_RISK],
        default_risk="high", description="A data-privacy / BAA addendum the vendor must sign.",
    )
    payload = reference.matrix_payload()
    assert len(payload["terms"]) == before + 1
    custom = _term(payload, "Data Privacy Addendum")
    assert custom["origin"] == "custom"
    assert custom["owning_teams"] == [TEAM_LEGAL, TEAM_RISK]
    assert custom["description"] == "A data-privacy / BAA addendum the vendor must sign."


def test_delete_reverts_seeded_override_to_brd_default():
    reference.upsert_matrix_term(
        term_label="Indemnification", owning_teams=[TEAM_HR], default_risk="low", description="x",
    )
    assert _term(reference.matrix_payload(), "Indemnification")["origin"] == "seeded_override"
    reference.delete_matrix_term("Indemnification")
    reverted = _term(reference.matrix_payload(), "Indemnification")
    assert reverted["origin"] == "seeded"
    assert reverted["owning_teams"] == [TEAM_LEGAL]  # back to the seeded default


# --- Editable "material trigger" flag ---------------------------------------

def test_seeded_matrix_seeds_trigger_flag_from_review_trigger_terms():
    """The merged payload exposes is_trigger, seeded True for the curated set."""
    from server._shared_data.responsibility_matrix import REVIEW_TRIGGER_TERMS

    payload = reference.matrix_payload()
    assert _term(payload, "Anti-Trust Violations")["is_trigger"] is True  # a seeded trigger
    assert _term(payload, "Payment Terms")["is_trigger"] is False  # not a trigger
    assert reference.trigger_terms() == set(REVIEW_TRIGGER_TERMS)


def test_checking_trigger_on_non_default_term_adds_it():
    """Flagging Payment Terms as a trigger via the matrix makes trigger_terms()
    include it (and it survives in the merged payload)."""
    reference.upsert_matrix_term(
        term_label="Payment Terms", owning_teams=[TEAM_LEGAL], default_risk="medium",
        description="", is_trigger=True,
    )
    assert _term(reference.matrix_payload(), "Payment Terms")["is_trigger"] is True
    assert "Payment Terms" in reference.trigger_terms()


def test_unchecking_trigger_on_default_term_removes_it():
    """Unchecking a seeded trigger (Anti-Trust) drops it from trigger_terms()."""
    reference.upsert_matrix_term(
        term_label="Anti-Trust Violations", owning_teams=[TEAM_LEGAL], default_risk="high",
        description="", is_trigger=False,
    )
    assert _term(reference.matrix_payload(), "Anti-Trust Violations")["is_trigger"] is False
    assert "Anti-Trust Violations" not in reference.trigger_terms()


def test_custom_term_can_be_a_trigger():
    reference.upsert_matrix_term(
        term_label="Data Privacy Addendum", owning_teams=[TEAM_LEGAL], default_risk="high",
        description="A data-privacy / BAA addendum.", is_trigger=True,
    )
    assert _term(reference.matrix_payload(), "Data Privacy Addendum")["is_trigger"] is True
    assert "Data Privacy Addendum" in reference.trigger_terms()


def test_delete_removes_custom_term_entirely():
    reference.upsert_matrix_term(
        term_label="Data Privacy Addendum", owning_teams=[TEAM_LEGAL], default_risk="high", description="x",
    )
    reference.delete_matrix_term("Data Privacy Addendum")
    labels = [t["term_label"] for t in reference.matrix_payload()["terms"]]
    assert "Data Privacy Addendum" not in labels


def test_upsert_rejects_unknown_team_and_bad_risk():
    with pytest.raises(ValueError):
        reference.upsert_matrix_term(
            term_label="X", owning_teams=["Marketing"], default_risk="medium", description="",
        )
    with pytest.raises(ValueError):
        reference.upsert_matrix_term(
            term_label="X", owning_teams=[TEAM_LEGAL], default_risk="critical", description="",
        )
    with pytest.raises(ValueError):
        reference.upsert_matrix_term(
            term_label="   ", owning_teams=[TEAM_LEGAL], default_risk="low", description="",
        )


def test_merged_payload_labels_stay_unique():
    reference.upsert_matrix_term(
        term_label="Indemnification", owning_teams=[TEAM_HR], default_risk="low", description="x",
    )
    labels = [t["term_label"] for t in reference.matrix_payload()["terms"]]
    assert len(labels) == len(set(labels)), "overriding a seeded term must not duplicate its row"
