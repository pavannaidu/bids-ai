"""Requirement routing uses REST ai-classify against the matrix term taxonomy.
Each clause is classified with the merged matrix terms (+ a __none__ escape).
A confident, in-taxonomy match sets matched_term to the canonical term (so the
Material banner keeps firing) and inherits that term's teams/risk; the escape
label or a below-threshold score leaves the clause unmatched for a human.

These tests stub the AI Functions REST boundary.
"""

from __future__ import annotations

from unittest.mock import patch

from server import databricks_api, reference
from server._shared_data.responsibility_matrix import (
    TEAM_BUSINESS,
    TEAM_HR,
    TEAM_LEGAL,
    TEAM_RISK,
    compute_review_verdict,
)
from server.config import get_settings

SETTINGS = get_settings()


def _classify_one(term_label: str, raw_text: str, *, label: str, conf: float) -> dict:
    """Classify one requirement with a stubbed REST response."""
    req = {"requirement_id": "req-1", "term_label": term_label, "raw_text": raw_text}
    response = {"response": [{"value": label, "confidence_score": conf}]}
    with patch("server.databricks_api._call_ai_function", return_value=response):
        return databricks_api.classify_requirements(SETTINGS, [req])[0]


def test_confident_match_adopts_canonical_term_teams_and_risk():
    result = _classify_one(
        "Indemnity", "The Contractor shall indemnify and hold harmless the Agency.",
        label="Indemnification", conf=0.94,
    )
    assert result["matched_term"] == "Indemnification"
    assert result["term_label"] == "Indemnification"
    assert result["owning_teams"] == [TEAM_LEGAL]
    assert result["risk_level"] == "high"
    assert result["source"] == "ai_classified"
    assert result["confidence"] == 0.94


def test_warranty_of_products_inherits_joint_ownership():
    """A term jointly owned in the BRD must classify to BOTH teams."""
    result = _classify_one(
        "Warranty", "The Contractor warrants all products are free from defects.",
        label="Warranty of Products", conf=0.8,
    )
    assert result["owning_teams"] == [TEAM_BUSINESS, TEAM_LEGAL]
    assert result["matched_term"] == "Warranty of Products"


def test_escape_label_leaves_clause_unmatched():
    result = _classify_one(
        "Green Procurement", "Vendor shall report recycled content percentage of packaging.",
        label="__none__", conf=0.99,
    )
    assert result["matched_term"] is None
    assert result["owning_teams"] == []
    assert result["source"] == "ai_suggested"


def test_below_confidence_floor_leaves_clause_unmatched():
    """Even a valid term label is treated as unmatched below the floor."""
    result = _classify_one(
        "Payment", "Invoices paid within a reasonable time.",
        label="Payment Terms", conf=0.30,  # < 0.45 floor
    )
    assert result["matched_term"] is None
    assert result["source"] == "ai_suggested"
    assert result["confidence"] == 0.30


def test_unknown_label_not_in_taxonomy_leaves_unmatched():
    result = _classify_one(
        "Mystery", "Some clause the model labeled with a nonexistent term.",
        label="Not A Real Term", conf=0.9,
    )
    assert result["matched_term"] is None
    assert result["source"] == "ai_suggested"


def test_classified_trigger_term_fires_material_banner():
    """End-to-end: classifying a clause to a trigger term must set matched_term
    so compute_review_verdict flags the bid Material — this is the whole point of
    classifying INTO the taxonomy rather than just to a team."""
    result = _classify_one(
        "Best Price", "Prices shall be no less favorable than those to any other customer.",
        label="Most Favored Nation", conf=0.88,
    )
    verdict = compute_review_verdict([result])
    assert verdict["material"] is True
    assert "Most Favored Nation" in verdict["trigger_terms"]


def test_concurrent_classification_preserves_input_order():
    reqs = [
        {"requirement_id": "r0", "term_label": "A", "raw_text": "indemnify and hold harmless"},
        {"requirement_id": "r1", "term_label": "B", "raw_text": "net 30 payment terms"},
        {"requirement_id": "r2", "term_label": "C", "raw_text": "maintain liability insurance"},
    ]
    labels = {
        "indemnify and hold harmless": "Indemnification",
        "net 30 payment terms": "Payment Terms",
        "maintain liability insurance": "Insurance Requirements",
    }

    def classify(_function_name, body):
        return {"response": [{"value": labels[body["content"]], "confidence_score": 0.9}]}

    with patch("server.databricks_api._call_ai_function", side_effect=classify):
        results = databricks_api.classify_requirements(SETTINGS, reqs)
    assert results[0]["matched_term"] == "Indemnification"
    assert results[1]["matched_term"] == "Payment Terms"
    assert results[2]["matched_term"] == "Insurance Requirements"
    assert results[2]["owning_teams"] == [TEAM_RISK]


def test_one_rest_failure_does_not_sink_other_clauses():
    reqs = [
        {"requirement_id": "r0", "term_label": "X", "raw_text": "indemnify and hold harmless"},
        {"requirement_id": "r1", "term_label": "Y", "raw_text": "temporary endpoint failure"},
    ]

    def classify(_function_name, body):
        if body["content"].startswith("temporary"):
            raise RuntimeError("endpoint down")
        return {"response": [{"value": "Indemnification", "confidence_score": 0.9}]}

    with patch("server.databricks_api._call_ai_function", side_effect=classify):
        results = databricks_api.classify_requirements(SETTINGS, reqs)
    assert results[0]["matched_term"] == "Indemnification"
    assert results[1]["matched_term"] is None


def test_total_classify_failure_leaves_all_unmatched():
    req = {"requirement_id": "r0", "term_label": "X", "raw_text": "some clause"}
    with patch("server.databricks_api._call_ai_function", side_effect=RuntimeError("endpoint down")):
        result = databricks_api.classify_requirements(SETTINGS, [req])[0]
    assert result["matched_term"] is None
    assert result["source"] == "ai_suggested"


def test_matrix_override_changes_classification():
    """Editing a seeded term's owning teams via the overlay MUST change how a
    clause classifying to that term is routed — the boundary reversal: the merged
    matrix now drives upload-time classification."""
    saved = dict(reference._matrix_overrides)
    reference._matrix_overrides.clear()
    try:
        reference.upsert_matrix_term(
            term_label="Indemnification", owning_teams=[TEAM_HR], default_risk="low",
            description="The vendor must indemnify or hold the buyer harmless.",
        )
        result = _classify_one(
            "Indemnity", "The Contractor shall indemnify the Agency.",
            label="Indemnification", conf=0.9,
        )
        assert result["owning_teams"] == [TEAM_HR]   # was [Corporate Legal] in the seed
        assert result["risk_level"] == "low"
    finally:
        reference._matrix_overrides.clear()
        reference._matrix_overrides.update(saved)


def test_build_classify_labels_falls_back_to_label_for_empty_description():
    """A custom term with no description must still get a non-empty ai_classify
    label definition (its own label)."""
    saved = dict(reference._matrix_overrides)
    reference._matrix_overrides.clear()
    try:
        reference.upsert_matrix_term(
            term_label="Widget Clause", owning_teams=[TEAM_BUSINESS], default_risk="medium",
            description="",
        )
        labels, index = databricks_api._build_classify_labels()
        assert labels["Widget Clause"] == "Widget Clause"
        assert "Widget Clause" in index
        assert databricks_api._ESCAPE_LABEL in labels
    finally:
        reference._matrix_overrides.clear()
        reference._matrix_overrides.update(saved)


def test_extract_requirements_returns_empty_on_blank_document():
    assert databricks_api.extract_requirements(SETTINGS, "") == []
    assert databricks_api.extract_requirements(SETTINGS, "   ") == []


def test_extract_and_classify_returns_empty_when_extraction_fails():
    """extract_and_classify_requirements must never raise into the upload path;
    an extraction failure yields no requirements."""
    with patch("server.databricks_api._call_ai_function", side_effect=RuntimeError("endpoint down")), \
            patch("server.databricks_api._fmapi_structured_output", side_effect=RuntimeError("endpoint down")):
        assert databricks_api.extract_and_classify_requirements(SETTINGS, "some document text") == []


def test_matrix_payload_lists_terms_teams_and_statuses():
    from server._shared_data.responsibility_matrix import matrix_payload

    payload = matrix_payload()
    labels = [t["term_label"] for t in payload["terms"]]
    assert len(labels) == len(set(labels)), "matrix term labels must be unique (frontend keys on them)"
    assert len(payload["teams"]) == 8
    assert "approved" in payload["statuses"] and "needs_changes" in payload["statuses"]
    # Every term now carries a non-empty description (the ai_classify definition).
    assert all(t["description"].strip() for t in payload["terms"]), "every term needs a description"
    warranty = next(t for t in payload["terms"] if t["term_label"] == "Warranty of Products")
    assert set(warranty["owning_teams"]) == {"Business", "Corporate Legal"}
    assert warranty["default_risk"] in {"high", "medium", "low"}
