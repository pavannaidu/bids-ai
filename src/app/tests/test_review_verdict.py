"""Tests for the material/immaterial bid-review triage verdict.

compute_review_verdict is a pure function of a bid's extracted requirements: a
bid is MATERIAL (route to Corporate Legal / Business-Terms review) if any
requirement is a curated BRD trigger clause, else IMMATERIAL. A requirement
triggers via EITHER its matched_term (matrix rows) OR its term_label (manual /
relabeled rows). Verdict is a triage-routing signal, distinct from risk_level.
"""

from __future__ import annotations

from server._shared_data.responsibility_matrix import (
    RESPONSIBILITY_MATRIX,
    REVIEW_TRIGGER_TERMS,
    TEAM_BUSINESS,
    TEAM_LEGAL,
    compute_review_verdict,
)


def _req(term_label: str, *, matched_term: str | None = None, owning_teams: list[str] | None = None,
         source: str = "matrix") -> dict:
    """Minimal requirement row as the store would serialize it."""
    return {
        "term_label": term_label,
        "matched_term": matched_term if matched_term is not None else term_label,
        "owning_teams": owning_teams if owning_teams is not None else [],
        "source": source,
    }


def test_trigger_clause_makes_bid_material():
    verdict = compute_review_verdict([
        _req("Indemnification", owning_teams=[TEAM_LEGAL]),
    ])
    assert verdict["material"] is True
    assert "Indemnification" in verdict["trigger_terms"]
    assert TEAM_LEGAL in verdict["review_teams"]
    assert "Material" in verdict["summary"]


def test_no_requirements_is_immaterial():
    verdict = compute_review_verdict([])
    assert verdict["material"] is False
    assert verdict["trigger_terms"] == []
    assert verdict["review_teams"] == []
    assert "Immaterial" in verdict["summary"]


def test_non_trigger_clauses_only_is_immaterial():
    """Payment Terms + Insurance Requirements are real matrix terms but NOT
    triage triggers — a bid with only these is immaterial."""
    verdict = compute_review_verdict([
        _req("Payment Terms", owning_teams=[TEAM_BUSINESS]),
        _req("Insurance Requirements", owning_teams=["Risk Management"]),
    ])
    assert verdict["material"] is False
    assert verdict["trigger_terms"] == []


def test_multiple_triggers_dedupe_and_canonical_team_order():
    """Two triggers owned by different teams: trigger_terms lists both, and
    review_teams is in canonical TEAMS order (Business before Corporate Legal)."""
    verdict = compute_review_verdict([
        _req("Litigation", owning_teams=[TEAM_LEGAL]),
        _req("Most Favored Nation", owning_teams=[TEAM_BUSINESS]),
    ])
    assert verdict["material"] is True
    assert len(verdict["trigger_terms"]) == 2
    assert set(verdict["trigger_terms"]) == {"Litigation", "Most Favored Nation"}
    assert verdict["review_teams"] == [TEAM_BUSINESS, TEAM_LEGAL]


def test_manual_row_triggers_via_term_label():
    """A manually-added requirement has matched_term=None but a matrix-seeded
    term_label; it must still trigger on the label."""
    verdict = compute_review_verdict([
        _req("Rebate Commitments", matched_term=None, owning_teams=[TEAM_BUSINESS], source="manual"),
    ])
    assert verdict["material"] is True
    assert "Rebate Commitments" in verdict["trigger_terms"]


def test_ai_suggested_noncanonical_label_does_not_trigger():
    """An ai_suggested clause with a free-text, non-matrix label is NOT a trigger
    (documents the known edge case — reviewer relabels to a matrix term to flip it)."""
    verdict = compute_review_verdict([
        _req("Green Procurement", matched_term=None, owning_teams=["Compliance"], source="ai_suggested"),
    ])
    assert verdict["material"] is False


def test_trigger_terms_are_all_real_matrix_labels():
    """Integrity guard: every trigger term must be an exact matrix term_label so a
    rename/typo in the matrix can't silently disable a trigger."""
    matrix_labels = {t.term_label for t in RESPONSIBILITY_MATRIX}
    assert REVIEW_TRIGGER_TERMS <= matrix_labels, (
        f"trigger terms not in matrix: {REVIEW_TRIGGER_TERMS - matrix_labels}"
    )


def test_explicit_trigger_set_overrides_default():
    """When a caller passes an editable trigger set (from the merged matrix), it —
    not the seeded frozenset — decides material. A default trigger (Indemnification)
    dropped from the set no longer fires; a normally-non-trigger term (Payment
    Terms) added to it does."""
    reqs = [
        _req("Indemnification", owning_teams=[TEAM_LEGAL]),
        _req("Payment Terms", owning_teams=[TEAM_BUSINESS]),
    ]
    # Custom set: Payment Terms is a trigger, Indemnification is not.
    verdict = compute_review_verdict(reqs, {"Payment Terms"})
    assert verdict["material"] is True
    assert verdict["trigger_terms"] == ["Payment Terms"]
    assert "Indemnification" not in verdict["trigger_terms"]


def test_empty_trigger_set_makes_everything_immaterial():
    """An empty trigger set (all boxes unchecked) => no bid is material."""
    verdict = compute_review_verdict([_req("Indemnification", owning_teams=[TEAM_LEGAL])], set())
    assert verdict["material"] is False
    assert verdict["trigger_terms"] == []
