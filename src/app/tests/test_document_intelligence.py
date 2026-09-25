"""Databricks document-intelligence pipeline: the structured parse layer, the
ai_extract-primary / ai_query-recovery / heuristic cascade, ai_classify routing,
best-effort page attribution, and VARIANT decoding. These are the pieces the
`docs/archive/databricks_document_intelligence_spec.md` upgrade adds; the invariants here are:
every extracted row carries provenance (incl. fallback/heuristic rows), the
flaky AI endpoint degrades gracefully, and page numbers are attributed only when
unambiguous.
"""

from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from server import databricks_api
from server.config import get_settings

SETTINGS = get_settings()
SETTINGS_AI = SETTINGS if SETTINGS.use_ai_extract else replace(SETTINGS, use_ai_extract=True)
SETTINGS_LEGACY = replace(SETTINGS, use_ai_extract=False)


# --------------------------------------------------------------------------- #
# _loads_variant — VARIANT columns arrive as (sometimes double-encoded) strings
# --------------------------------------------------------------------------- #

def test_loads_variant_handles_dict_string_and_double_encoded():
    payload = {"response": {"line_items": [{"raw_description": "x"}]}}
    assert databricks_api._loads_variant(payload) == payload
    assert databricks_api._loads_variant(json.dumps(payload)) == payload
    assert databricks_api._loads_variant(json.dumps(json.dumps(payload))) == payload


def test_loads_variant_returns_empty_on_garbage():
    assert databricks_api._loads_variant("not json at all {") == {}
    assert databricks_api._loads_variant(None) is None


# --------------------------------------------------------------------------- #
# Page-attribution index + best-effort matcher
# --------------------------------------------------------------------------- #

def _parsed_variant(elements):
    return json.dumps({"document": {"pages": [{"id": 0}, {"id": 1}], "elements": elements}})


def test_index_parsed_document_reads_elements_and_normalizes_pages():
    parsed = _parsed_variant([
        {"content": "Firm pricing clause here", "bbox": [{"page_id": 0}]},
        {"content": "Indemnification clause here", "bbox": [{"page_id": 1}]},
        {"content": "   ", "bbox": [{"page_id": 1}]},  # blank skipped
    ])
    text, spans = databricks_api._index_parsed_document(parsed)
    assert "Firm pricing clause here" in text and "Indemnification clause here" in text
    # page_id is 0-based in the schema -> normalized to 1-based here.
    assert spans == [(1, "Firm pricing clause here"), (2, "Indemnification clause here")]


def test_index_parsed_document_falls_back_when_no_elements():
    # No structured elements -> legacy flat-text path, empty spans.
    parsed = json.dumps({"document": {"content": "some flat text"}})
    text, spans = databricks_api._index_parsed_document(parsed)
    assert text == "some flat text"
    assert spans == []


def test_match_page_single_containment_wins():
    spans = [(1, "The firm pricing clause applies for one year."), (2, "Unrelated content.")]
    assert databricks_api._match_page("firm pricing clause applies", spans) == 1


def test_match_page_null_when_short_needle():
    spans = [(1, "net 30 terms and more text here")]
    assert databricks_api._match_page("net 30", spans) is None  # under min length


def test_match_page_null_when_ambiguous_across_pages():
    spans = [(1, "the same repeated clause text"), (2, "the same repeated clause text")]
    assert databricks_api._match_page("the same repeated clause text", spans) is None


def test_match_page_token_overlap_tiebreak():
    # No exact containment, but strong token overlap with page 2.
    spans = [(1, "completely different words about apples"),
             (2, "warranty of products free from defects period")]
    assert databricks_api._match_page("warranty of products free from defects", spans) == 2


# --------------------------------------------------------------------------- #
# parse_document — Excel path + flaky-parser degradation
# --------------------------------------------------------------------------- #

def test_parse_document_excel_has_no_page_spans():
    # A tiny xlsx built in-memory so we exercise the openpyxl branch.
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Item", "Qty"])
    ws.append(["Gloves", 10])
    buf = BytesIO()
    wb.save(buf)

    parsed = databricks_api.parse_document(SETTINGS, "/Volumes/x/y/z/sheet.xlsx", buf.getvalue())
    assert parsed["source_kind"] == "excel"
    assert parsed["page_spans"] == []
    assert "Gloves" in parsed["text"]


def test_parse_document_returns_empty_when_parser_never_yields():
    with patch("server.databricks_api._run_parse", return_value=None):
        parsed = databricks_api.parse_document(SETTINGS, "/Volumes/x/y/z/doc.pdf", b"...")
    assert parsed["text"] == ""
    assert parsed["page_spans"] == []
    assert parsed["parse_error"]


# --------------------------------------------------------------------------- #
# Line-item extraction cascade: ai_extract -> ai_query -> heuristic
# --------------------------------------------------------------------------- #

def _spans(*pairs):
    return {"text": "\n\n".join(t for _, t in pairs), "page_spans": list(pairs)}


def test_line_items_ai_extract_primary_path():
    parsed = _spans((1, "Nitrile exam gloves, large, box of 100"))
    variant = json.dumps({"response": {"line_items": [
        {"line_number": 1, "raw_description": "Nitrile exam gloves, large, box of 100", "qty": 5, "uom": "BX"},
    ]}, "error_message": None})
    with patch("server.databricks_api.execute_sql", return_value=[{"extracted": variant}]):
        items = databricks_api.extract_line_items(SETTINGS_AI, parsed)
    assert len(items) == 1
    assert items[0]["extraction_method"] == "ai_extract"
    assert items[0]["qty"] == 5
    assert items[0]["source_page"] == 1


def test_line_items_ai_extract_unwraps_wrapped_field_values():
    """ai_extract v2.1 can return each field as a {value,...} object (with
    citations/confidence) rather than a bare scalar. Extraction must unwrap
    those, not choke on a dict where a string was expected (regression: a live
    parse returned wrapped fields and crashed on .strip())."""
    parsed = _spans((1, "Nitrile exam gloves, large, box of 100"))
    variant = json.dumps({"response": {"line_items": [
        {
            "line_number": {"value": 1},
            "raw_description": {"value": "Nitrile exam gloves, large, box of 100", "citations": [{"page": 1}]},
            "qty": {"value": 5},
            "uom": {"value": "BX"},
            "given_code": {"value": None},
        },
    ]}, "error_message": None})
    with patch("server.databricks_api.execute_sql", return_value=[{"extracted": variant}]):
        items = databricks_api.extract_line_items(SETTINGS_AI, parsed)
    assert len(items) == 1
    assert items[0]["raw_description"] == "Nitrile exam gloves, large, box of 100"
    assert items[0]["qty"] == 5
    assert items[0]["uom"] == "BX"
    assert items[0]["given_code"] is None


def test_requirements_ai_extract_unwraps_wrapped_field_values():
    """Same wrapped-field shape for requirements."""
    parsed = _spans((1, "Contractor shall indemnify and hold harmless the agency."))
    variant = json.dumps({"response": {"requirements": [
        {
            "term_label": {"value": "Indemnification"},
            "raw_text": {"value": "Contractor shall indemnify and hold harmless the agency."},
        },
    ]}, "error_message": None})
    with patch("server.databricks_api.execute_sql", return_value=[{"extracted": variant}]):
        reqs = databricks_api.extract_requirements(SETTINGS_AI, parsed)
    assert len(reqs) == 1
    assert reqs[0]["term_label"] == "Indemnification"
    assert reqs[0]["raw_text"].startswith("Contractor shall indemnify")
    # Extraction no longer emits category — routing to a term is a separate pass.
    assert "category" not in reqs[0]


def test_line_items_recover_to_ai_query_when_ai_extract_empty():
    parsed = _spans((1, "Surgical masks, level 3"))
    empty_extract = json.dumps({"response": {"line_items": []}, "error_message": None})
    query_result = json.dumps({"items": [
        {"line_number": 1, "raw_description": "Surgical masks, level 3", "qty": 1, "uom": "EA"},
    ]})

    calls = {"n": 0}

    def fake_sql(_settings, query, params=None):
        calls["n"] += 1
        if "ai_extract" in query:
            return [{"extracted": empty_extract}]
        if "ai_query" in query:
            return [{"extracted": query_result}]
        return []

    with patch("server.databricks_api.execute_sql", side_effect=fake_sql):
        items = databricks_api.extract_line_items(SETTINGS_AI, parsed)
    assert len(items) == 1
    assert items[0]["extraction_method"] == "ai_query"


def test_line_items_fall_back_to_heuristic_when_both_ai_paths_fail():
    parsed = _spans((1, "Tongue depressors wooden sterile box"))

    def boom(_settings, _query, _params=None):
        raise RuntimeError("endpoint down")

    with patch("server.databricks_api.execute_sql", side_effect=boom):
        items = databricks_api.extract_line_items(SETTINGS_AI, parsed)
    assert items, "heuristic split should keep at least one row alive"
    assert all(it["extraction_method"] == "heuristic" for it in items)
    # Even heuristic rows must carry provenance keys (page best-effort / None ok).
    assert all("source_page" in it and "confidence" in it for it in items)


def test_line_items_flag_off_uses_ai_query_directly():
    parsed = _spans((1, "Cotton rolls #2 non-sterile"))
    query_result = json.dumps({"items": [
        {"line_number": 1, "raw_description": "Cotton rolls #2 non-sterile", "qty": 1, "uom": "BG"},
    ]})

    def fake_sql(_settings, query, _params=None):
        assert "ai_extract" not in query, "flag off must not call ai_extract"
        return [{"extracted": query_result}]

    with patch("server.databricks_api.execute_sql", side_effect=fake_sql):
        items = databricks_api.extract_line_items(SETTINGS_LEGACY, parsed)
    assert len(items) == 1
    assert items[0]["extraction_method"] == "ai_query"


# --------------------------------------------------------------------------- #
# Requirement extraction recovery asymmetry: empty is NOT a trigger
# --------------------------------------------------------------------------- #

def test_requirements_empty_result_does_not_trigger_recovery():
    parsed = _spans((1, "A short prose document with no clauses."))
    empty_extract = json.dumps({"response": {"requirements": []}, "error_message": None})

    seen = {"ai_query": False}

    def fake_sql(_settings, query, _params=None):
        if "ai_query" in query:
            seen["ai_query"] = True
        return [{"extracted": empty_extract}]

    with patch("server.databricks_api.execute_sql", side_effect=fake_sql):
        result = databricks_api.extract_requirements(SETTINGS_AI, parsed)
    assert result == []
    assert seen["ai_query"] is False, "well-formed empty result must NOT fall back to ai_query"


def test_requirements_error_message_triggers_recovery():
    parsed = _spans((1, "Indemnification: contractor shall hold harmless the agency."))
    errored = json.dumps({"response": None, "error_message": "model overloaded"})
    query_result = json.dumps({"requirements": [
        {"term_label": "Indemnification", "raw_text": "contractor shall hold harmless the agency", "category": "legal"},
    ]})

    def fake_sql(_settings, query, _params=None):
        if "ai_extract" in query:
            return [{"extracted": errored}]
        return [{"extracted": query_result}]

    with patch("server.databricks_api.execute_sql", side_effect=fake_sql):
        result = databricks_api.extract_requirements(SETTINGS_AI, parsed)
    assert len(result) == 1
    assert result[0]["extraction_method"] == "ai_query"
    assert result[0]["source_page"] == 1
