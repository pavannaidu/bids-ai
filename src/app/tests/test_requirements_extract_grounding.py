"""Workstream A: the requirements ai_extract is grounded in the SAME editable
matrix taxonomy that classification uses. _requirements_extract_instructions()
emits the matrix glossary (term_label + description), reflects matrix edits, and
is actually passed to ai_extract via the `instructions` option. Both extract
schemas carry non-empty field descriptions.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from server import databricks_api, reference
from server.config import get_settings

SETTINGS = get_settings()


def test_instructions_contain_seeded_terms_and_descriptions():
    text = databricks_api._requirements_extract_instructions()
    # Core steering survived.
    assert "IGNORE the product line items" in text
    assert "non-exhaustive" in text
    # Representative seeded matrix terms + (a fragment of) their descriptions.
    assert "Indemnification" in text
    assert "Most Favored Nation" in text
    assert "indemnify" in text.lower()  # from the Indemnification description


def test_instructions_reflect_a_custom_matrix_term():
    """A custom term added via the matrix overlay must appear in the extraction
    instructions — proving matrix edits reach extraction, not just classification."""
    saved = dict(reference._matrix_overrides)
    reference._matrix_overrides.clear()
    try:
        reference.upsert_matrix_term(
            term_label="Sustainability Attestation",
            owning_teams=["Corporate Legal"], default_risk="low",
            description="A clause requiring the vendor to attest to sustainability / ESG practices.",
        )
        text = databricks_api._requirements_extract_instructions()
        assert "Sustainability Attestation" in text
        assert "ESG" in text
    finally:
        reference._matrix_overrides.clear()
        reference._matrix_overrides.update(saved)


def test_requirements_ai_extract_sends_instructions_option():
    """_requirements_ai_extract must pass the matrix-grounded instructions to
    ai_extract (v2.1) — the whole point of workstream A."""
    captured: dict = {}

    def fake_ai_function(function_name, body):
        captured["function_name"] = function_name
        captured["body"] = body
        # Well-formed empty ai_extract envelope (no hard fail).
        return {"response": {"requirements": []}}

    with patch("server.databricks_api._call_ai_function", side_effect=fake_ai_function):
        items, hard_fail = databricks_api._requirements_ai_extract(SETTINGS, "Some solicitation text.")

    assert hard_fail is False
    assert captured["function_name"] == "ai-extract"
    options = captured["body"]["options"]
    assert "IGNORE the product line items" in options["instructions"]
    assert "Indemnification" in options["instructions"]
    assert options["version"] == "2.1"


def test_both_extract_schemas_have_field_descriptions():
    for schema_json in (
        databricks_api._REQUIREMENTS_EXTRACT_SCHEMA,
        databricks_api._LINE_ITEMS_EXTRACT_SCHEMA,
    ):
        schema = json.loads(schema_json)
        # The single top-level array -> items.properties
        (array_def,) = schema.values()
        props = array_def["items"]["properties"]
        assert props, "schema has no fields"
        for name, spec in props.items():
            assert spec.get("description", "").strip(), f"field {name} is missing a description"
