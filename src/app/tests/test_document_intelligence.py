"""Databricks document-intelligence pipeline: the structured parse layer, the
ai_extract-primary / FMAPI-recovery / heuristic cascade, ai_classify routing,
best-effort page attribution, and JSON decoding (see docs/architecture.md). The invariants here are:
every extracted row carries provenance (incl. fallback/heuristic rows), the
flaky AI endpoint degrades gracefully, and page numbers are attributed only when
unambiguous.
"""

from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import patch

from server import databricks_api
from server.config import get_settings

SETTINGS = get_settings()
SETTINGS_AI = SETTINGS if SETTINGS.use_ai_extract else replace(SETTINGS, use_ai_extract=True)
SETTINGS_FMAPI = replace(SETTINGS, use_ai_extract=False)


# --------------------------------------------------------------------------- #
# _loads_variant — tolerate JSON strings and double-encoded historical values
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


def test_run_parse_calls_rest_with_volume_path_and_version():
    response = {"document": {"elements": [{"content": "hello"}]}}
    with patch("server.databricks_api._call_ai_function", return_value=response) as call:
        assert databricks_api._run_parse(SETTINGS, "/Volumes/c/s/v/doc.pdf") == response
    call.assert_called_once_with(
        "ai-parse-document",
        {"content": "/Volumes/c/s/v/doc.pdf", "options": {"version": "2.0"}},
    )


# --------------------------------------------------------------------------- #
# Line-item extraction cascade: ai_extract -> FMAPI -> heuristic
# --------------------------------------------------------------------------- #

def _spans(*pairs):
    return {"text": "\n\n".join(t for _, t in pairs), "page_spans": list(pairs)}


def test_line_items_ai_extract_primary_path():
    parsed = _spans((1, "Nitrile exam gloves, large, box of 100"))
    response = {"response": {"line_items": [
        {"line_number": 1, "raw_description": "Nitrile exam gloves, large, box of 100", "qty": 5, "uom": "BX"},
    ]}, "error_message": None}
    with patch("server.databricks_api._call_ai_function", return_value=response):
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
    response = {"response": {"line_items": [
        {
            "line_number": {"value": 1},
            "raw_description": {"value": "Nitrile exam gloves, large, box of 100", "citations": [{"page": 1}]},
            "qty": {"value": 5},
            "uom": {"value": "BX"},
            "given_code": {"value": None},
        },
    ]}, "error_message": None}
    with patch("server.databricks_api._call_ai_function", return_value=response):
        items = databricks_api.extract_line_items(SETTINGS_AI, parsed)
    assert len(items) == 1
    assert items[0]["raw_description"] == "Nitrile exam gloves, large, box of 100"
    assert items[0]["qty"] == 5
    assert items[0]["uom"] == "BX"
    assert items[0]["given_code"] is None


def test_requirements_ai_extract_unwraps_wrapped_field_values():
    """Same wrapped-field shape for requirements."""
    parsed = _spans((1, "Contractor shall indemnify and hold harmless the agency."))
    response = {"response": {"requirements": [
        {
            "term_label": {"value": "Indemnification"},
            "raw_text": {"value": "Contractor shall indemnify and hold harmless the agency."},
        },
    ]}, "error_message": None}
    with patch("server.databricks_api._call_ai_function", return_value=response):
        reqs = databricks_api.extract_requirements(SETTINGS_AI, parsed)
    assert len(reqs) == 1
    assert reqs[0]["term_label"] == "Indemnification"
    assert reqs[0]["raw_text"].startswith("Contractor shall indemnify")
    # Extraction no longer emits category — routing to a term is a separate pass.
    assert "category" not in reqs[0]


def test_line_items_recover_to_fmapi_when_ai_extract_empty():
    parsed = _spans((1, "Surgical masks, level 3"))
    empty_extract = {"response": {"line_items": []}, "error_message": None}
    fmapi_result = {"items": [
        {"line_number": 1, "raw_description": "Surgical masks, level 3", "qty": 1, "uom": "EA", "given_code": ""},
    ]}

    with patch("server.databricks_api._call_ai_function", return_value=empty_extract), \
            patch("server.databricks_api._fmapi_structured_output", return_value=fmapi_result):
        items = databricks_api.extract_line_items(SETTINGS_AI, parsed)
    assert len(items) == 1
    assert items[0]["extraction_method"] == "fmapi"


def test_line_items_fall_back_to_heuristic_when_both_ai_paths_fail():
    parsed = _spans((1, "Tongue depressors wooden sterile box"))

    with patch("server.databricks_api._call_ai_function", side_effect=RuntimeError("endpoint down")), \
            patch("server.databricks_api._fmapi_structured_output", side_effect=RuntimeError("endpoint down")):
        items = databricks_api.extract_line_items(SETTINGS_AI, parsed)
    assert items, "heuristic split should keep at least one row alive"
    assert all(it["extraction_method"] == "heuristic" for it in items)
    # Even heuristic rows must carry provenance keys (page best-effort / None ok).
    assert all("source_page" in it and "confidence" in it for it in items)


def test_line_items_flag_off_uses_fmapi_directly():
    parsed = _spans((1, "Cotton rolls #2 non-sterile"))
    fmapi_result = {"items": [
        {"line_number": 1, "raw_description": "Cotton rolls #2 non-sterile", "qty": 1, "uom": "BG", "given_code": ""},
    ]}

    with patch("server.databricks_api._call_ai_function") as ai_function, \
            patch("server.databricks_api._fmapi_structured_output", return_value=fmapi_result):
        items = databricks_api.extract_line_items(SETTINGS_FMAPI, parsed)
    ai_function.assert_not_called()
    assert len(items) == 1
    assert items[0]["extraction_method"] == "fmapi"


# --------------------------------------------------------------------------- #
# Requirement extraction recovery asymmetry: empty is NOT a trigger
# --------------------------------------------------------------------------- #

def test_requirements_empty_result_does_not_trigger_recovery():
    parsed = _spans((1, "A short prose document with no clauses."))
    empty_extract = {"response": {"requirements": []}, "error_message": None}

    with patch("server.databricks_api._call_ai_function", return_value=empty_extract), \
            patch("server.databricks_api._fmapi_structured_output") as fmapi:
        result = databricks_api.extract_requirements(SETTINGS_AI, parsed)
    assert result == []
    fmapi.assert_not_called()


def test_requirements_error_message_triggers_recovery():
    parsed = _spans((1, "Indemnification: contractor shall hold harmless the agency."))
    errored = {"response": None, "error_message": "model overloaded"}
    fmapi_result = {"requirements": [
        {"term_label": "Indemnification", "raw_text": "contractor shall hold harmless the agency", "category": "legal"},
    ]}

    with patch("server.databricks_api._call_ai_function", return_value=errored), \
            patch("server.databricks_api._fmapi_structured_output", return_value=fmapi_result):
        result = databricks_api.extract_requirements(SETTINGS_AI, parsed)
    assert len(result) == 1
    assert result[0]["extraction_method"] == "fmapi"
    assert result[0]["source_page"] == 1


def test_fmapi_structured_output_sends_strict_non_streaming_request():
    response = {"choices": [{"message": {"content": '{"items": []}'}}]}
    databricks_api._fmapi_temperature_ok.clear()
    databricks_api._fmapi_response_format_ok.clear()
    with patch("server.databricks_api._post_json", return_value=response) as post:
        result = databricks_api._fmapi_structured_output(
            SETTINGS,
            "extract",
            databricks_api._LINE_ITEMS_FMAPI_RESPONSE_FORMAT,
        )
    assert result == {"items": []}
    path, body = post.call_args.args
    assert path.endswith("/databricks-claude-sonnet-5-5/invocations")
    assert body["stream"] is False
    assert body["temperature"] == 0.0
    assert body["response_format"]["json_schema"]["strict"] is True


def test_fmapi_falls_back_to_schema_in_prompt_for_models_without_structured_output():
    """Newer Claude models (Sonnet 5.5) reject response_format and temperature: retry with the
    JSON Schema in the prompt and no temperature, parse a fenced JSON reply, and remember both
    for the endpoint so later calls go straight to the accepted request."""
    databricks_api._fmapi_temperature_ok.clear()
    databricks_api._fmapi_response_format_ok.clear()
    bodies = []
    reply = {"choices": [{"message": {"content": '```json\n{"items": [{"raw_description": "Gloves"}]}\n```'}}]}

    def endpoint(path, body):
        bodies.append(json.loads(json.dumps(body)))
        if "response_format" in body:
            raise RuntimeError("INVALID_PARAMETER_VALUE: Structured output is not supported for this model")
        if "temperature" in body:
            raise RuntimeError("BAD_REQUEST: Model does not support the temperature parameter.")
        return reply

    fmt = databricks_api._LINE_ITEMS_FMAPI_RESPONSE_FORMAT
    with patch("server.databricks_api._post_json", side_effect=endpoint):
        result = databricks_api._fmapi_structured_output(SETTINGS, "extract", fmt)
        assert result == {"items": [{"raw_description": "Gloves"}]}
        assert len(bodies) == 3
        final = bodies[-1]
        assert "response_format" not in final and "temperature" not in final
        assert json.dumps(fmt["json_schema"]["schema"]) in final["messages"][0]["content"]

        bodies.clear()
        databricks_api._fmapi_structured_output(SETTINGS, "extract again", fmt)
        assert len(bodies) == 1  # no failed attempts once the endpoint's limits are known
