"""The split upload workflow: staging+parse creates an "uploaded" bid (no rows
yet, parse stashed on the manifest); separate extract endpoints pull line items
and requirements on demand, merging multi-file results with per-file line-number
offset + provenance, and are idempotent (clear-then-add) on re-run."""

from __future__ import annotations

import pytest

from server import main
from server.state import InMemoryBidStore


@pytest.fixture
def multifile_env(monkeypatch):
    """Swap in an in-memory store + stubbed parse/extract/volume so the merge
    logic is exercised deterministically (no warehouse / AI parser)."""
    store = InMemoryBidStore()
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main.volumes, "write_volume_file", lambda path, content: None)
    monkeypatch.setattr(main.volumes, "delete_volume_file", lambda path: None)
    monkeypatch.setattr(
        main.reference, "get_customer",
        lambda cid: {"customer_id": cid, "customer_name": "Test Customer"},
    )

    # Each file yields 2 line items numbered 1..2 (so we can see the offset) and
    # one requirement keyed off the filename. parse_document returns the
    # structured dict; extractors read parsed["text"].
    def fake_parse(_settings, _path, content):
        text = content.decode()
        return {"text": text, "page_spans": [(1, text)], "source_kind": "ai_parse_document", "parse_error": None}

    def fake_lines(_settings, parsed):
        text = parsed["text"] if isinstance(parsed, dict) else parsed
        return [
            {"line_id": f"l-{text}-1", "line_number": 1, "raw_description": f"{text} item A", "qty": 1, "uom": "EA",
             "source_page": 1, "extraction_method": "ai_extract", "confidence": None},
            {"line_id": f"l-{text}-2", "line_number": 2, "raw_description": f"{text} item B", "qty": 1, "uom": "EA",
             "source_page": 1, "extraction_method": "ai_extract", "confidence": None},
        ]

    def fake_reqs(_settings, parsed):
        text = parsed["text"] if isinstance(parsed, dict) else parsed
        return [{
            "requirement_id": f"r-{text}", "term_label": "Indemnification", "raw_text": f"clause from {text}",
            "owning_teams": ["Corporate Legal"], "risk_level": "high",
            "risk_rationale": "", "matched_term": "Indemnification", "source": "ai_classified",
            "source_page": 1, "extraction_method": "ai_extract", "confidence": 0.9,
        }]

    monkeypatch.setattr(main.databricks_api, "parse_document", fake_parse)
    monkeypatch.setattr(main.databricks_api, "extract_line_items", fake_lines)
    monkeypatch.setattr(main.databricks_api, "extract_and_classify_requirements", fake_reqs)
    return store


def _stage(files, bid_id="bid-multi"):
    return main._stage_and_parse(
        bid_id=bid_id, files=files, customer_id="CUST-1", due_date="2026-09-01", bid_name="Multi",
    )


def test_stage_and_parse_creates_uploaded_bid_with_no_rows(multifile_env):
    result = _stage([("fileA", b"fileA"), ("fileB", b"fileB")])
    # Two docs staged, distinct doc_ids, primary = first file, status "uploaded".
    assert [d["file_name"] for d in result["documents"]] == ["fileA", "fileB"]
    assert len({d["doc_id"] for d in result["documents"]}) == 2
    assert result["status"] == "uploaded"
    # No extraction yet.
    assert result["line_items"] == []
    assert result["requirements"] == []
    # The heavy parse cache is stripped from the API response...
    assert all("parsed_text" not in d and "page_spans" not in d for d in result["documents"])
    # ...but IS stashed in the store for the extract endpoints to reuse.
    stored = multifile_env.get_bid("bid-multi")
    assert all(d["parsed_text"] for d in stored["documents"])


def test_extract_line_items_merges_with_offset_and_provenance(multifile_env):
    _stage([("fileA", b"fileA"), ("fileB", b"fileB")])
    result = main.extract_line_items_endpoint("bid-multi")
    # 4 line items, contiguous + unique 1..4 (fileB's 1,2 offset to 3,4).
    assert [li["line_number"] for li in result["line_items"]] == [1, 2, 3, 4]
    assert result["status"] == "matching"
    doc_by_name = {d["file_name"]: d["doc_id"] for d in result["documents"]}
    lines_by_num = {li["line_number"]: li for li in result["line_items"]}
    assert lines_by_num[1]["source_filename"] == "fileA"
    assert lines_by_num[1]["source_doc_id"] == doc_by_name["fileA"]
    assert lines_by_num[3]["source_filename"] == "fileB"
    assert lines_by_num[3]["source_doc_id"] == doc_by_name["fileB"]


def test_extract_requirements_merges_and_does_not_set_matching(multifile_env):
    staged = _stage([("fileA", b"fileA"), ("fileB", b"fileB")])
    assert staged["status"] == "uploaded"
    result = main.extract_requirements_endpoint("bid-multi")
    assert len(result["requirements"]) == 2
    assert [r["seq"] for r in result["requirements"]] == [1, 2]
    # Requirements extraction is additive — it must NOT advance status to matching.
    assert result["status"] == "uploaded"
    doc_ids = {d["doc_id"] for d in result["documents"]}
    for req in result["requirements"]:
        assert req["source_doc_id"] in doc_ids
        assert req["matched_term"] == "Indemnification"


def test_extract_endpoints_are_idempotent(multifile_env):
    """Re-running an extract endpoint clears then re-adds — no duplicate rows."""
    _stage([("fileA", b"fileA"), ("fileB", b"fileB")])
    main.extract_line_items_endpoint("bid-multi")
    r2 = main.extract_line_items_endpoint("bid-multi")
    assert [li["line_number"] for li in r2["line_items"]] == [1, 2, 3, 4]  # still 4, not 8

    main.extract_requirements_endpoint("bid-multi")
    r4 = main.extract_requirements_endpoint("bid-multi")
    assert len(r4["requirements"]) == 2  # still 2, not 4
    assert [r["seq"] for r in r4["requirements"]] == [1, 2]


def test_extractions_are_independent(multifile_env):
    """Requirements can be extracted without line items and vice-versa (the two
    endpoints write disjoint tables, so parallel firing is safe)."""
    _stage([("fileA", b"fileA")], bid_id="bid-indep")
    req_only = main.extract_requirements_endpoint("bid-indep")
    assert len(req_only["requirements"]) == 1
    assert req_only["line_items"] == []
    # Verdict is valid from requirements alone (Indemnification is a trigger term).
    assert req_only["review_verdict"]["material"] is True

    line_only = main.extract_line_items_endpoint("bid-indep")
    assert len(line_only["line_items"]) == 2
    assert len(line_only["requirements"]) == 1  # requirements untouched


def test_requirement_extraction_failure_is_non_fatal(multifile_env, monkeypatch):
    def boom(_settings, _parsed):
        raise RuntimeError("model serving down")

    monkeypatch.setattr(main.databricks_api, "extract_and_classify_requirements", boom)
    _stage([("fileA", b"fileA"), ("fileB", b"fileB")], bid_id="bid-noreq")
    result = main.extract_requirements_endpoint("bid-noreq")
    assert result["requirements"] == []  # per-file failure swallowed, endpoint still returns


def test_delete_document_guards_and_removes(multifile_env):
    from fastapi import HTTPException

    _stage([("fileA", b"fileA"), ("fileB", b"fileB")], bid_id="bid-del")
    docs = multifile_env.get_bid("bid-del")["documents"]
    doc_a = next(d["doc_id"] for d in docs if d["file_name"] == "fileA")

    # Removes one, keeps the other.
    result = main.delete_source_document("bid-del", doc_a)
    assert [d["file_name"] for d in result["documents"]] == ["fileB"]

    # Can't remove the last remaining document.
    doc_b = result["documents"][0]["doc_id"]
    with pytest.raises(HTTPException) as exc:
        main.delete_source_document("bid-del", doc_b)
    assert exc.value.status_code == 422


def test_delete_document_allowed_after_extraction(multifile_env):
    """Docs are now removable at any step (so a user can prune + re-extract). The
    only remaining delete guard is "keep at least one document"."""
    _stage([("fileA", b"fileA"), ("fileB", b"fileB")], bid_id="bid-locked")
    main.extract_line_items_endpoint("bid-locked")  # -> status "matching"
    docs = multifile_env.get_bid("bid-locked")["documents"]
    result = main.delete_source_document("bid-locked", docs[0]["doc_id"])
    assert len(result["documents"]) == 1  # removed one despite status "matching"


def test_reconstruct_parsed_reparses_when_stash_missing(multifile_env):
    """Back-compat: a bid whose manifest predates the parse-stash re-parses from
    the Volume path rather than failing."""
    # Simulate an old bid: documents without parsed_text.
    doc = {"doc_id": "doc-legacy", "file_name": "old", "path": "/Volumes/x/old",
           "file_format": "pdf"}
    # Stub read_volume_file so _reconstruct_parsed's re-parse path has content.
    import server.main as m
    m.volumes.read_volume_file = lambda path: b"legacy text"
    parsed = main._reconstruct_parsed(doc)
    assert parsed["text"] == "legacy text"  # came back through fake_parse


# --------------------------------------------------------------------------- #
# Editable bid metadata + add-document on the Upload step
# --------------------------------------------------------------------------- #


class _FakeUpload:
    """Minimal stand-in for fastapi.UploadFile (filename + async read)."""

    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self._content = content

    async def read(self) -> bytes:
        return self._content


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_update_bid_sets_name_and_due_date(multifile_env):
    _stage([("fileA", b"fileA")], bid_id="bid-edit")
    result = main.update_bid("bid-edit", main.BidUpdateRequest(bid_name="Renamed", due_date="2027-01-15"))
    assert result["bid_name"] == "Renamed"
    assert result["due_date"] == "2027-01-15"
    # Persisted, not just echoed.
    assert multifile_env.get_bid("bid-edit")["bid_name"] == "Renamed"


def test_update_bid_customer_updates_denormalized_name(multifile_env, monkeypatch):
    _stage([("fileA", b"fileA")], bid_id="bid-cust")
    # Now point the picker at a differently-named account and switch to it.
    monkeypatch.setattr(
        main.reference, "get_customer",
        lambda cid: {"customer_id": cid, "customer_name": "Bureau of Prisons"},
    )
    result = main.update_bid("bid-cust", main.BidUpdateRequest(customer_id="CUST-99"))
    assert result["customer_id"] == "CUST-99"
    assert result["customer_name"] == "Bureau of Prisons"


def test_update_bid_rejects_unknown_customer(multifile_env, monkeypatch):
    from fastapi import HTTPException

    _stage([("fileA", b"fileA")], bid_id="bid-badcust")  # staged with the fixture's valid customer
    monkeypatch.setattr(main.reference, "get_customer", lambda cid: None)  # now nothing resolves
    with pytest.raises(HTTPException) as exc:
        main.update_bid("bid-badcust", main.BidUpdateRequest(customer_id="CUST-nope"))
    assert exc.value.status_code == 400


def test_update_bid_customer_blocked_after_extraction(multifile_env):
    from fastapi import HTTPException

    _stage([("fileA", b"fileA")], bid_id="bid-lockcust")
    main.extract_line_items_endpoint("bid-lockcust")  # -> status "matching"
    with pytest.raises(HTTPException) as exc:
        main.update_bid("bid-lockcust", main.BidUpdateRequest(customer_id="CUST-1"))
    assert exc.value.status_code == 409


def test_add_documents_appends_and_parses(multifile_env):
    _stage([("fileA", b"fileA")], bid_id="bid-add")
    result = _run(main.add_source_documents("bid-add", [_FakeUpload("fileB", b"fileB")]))
    assert [d["file_name"] for d in result["documents"]] == ["fileA", "fileB"]
    # The new doc carries a parse stash the extract endpoints can reuse.
    stored = multifile_env.get_bid("bid-add")
    assert all(d["parsed_text"] for d in stored["documents"])
    # Primary reference stays at documents[0].
    assert result["file_name"] == "fileA"


def test_add_documents_allowed_after_extraction(multifile_env):
    """Docs can now be added after extraction so a user can fold in a new file and
    re-extract; the new doc is staged + parsed like any other."""
    _stage([("fileA", b"fileA")], bid_id="bid-addlock")
    main.extract_line_items_endpoint("bid-addlock")  # -> status "matching"
    result = _run(main.add_source_documents("bid-addlock", [_FakeUpload("fileB", b"fileB")]))
    assert [d["file_name"] for d in result["documents"]] == ["fileA", "fileB"]
    assert all(d["parsed_text"] for d in multifile_env.get_bid("bid-addlock")["documents"])


def test_delete_document_keeps_primary_reference_valid(multifile_env):
    """Deleting the primary (documents[0]) re-points file_name at a surviving doc."""
    staged = _stage([("fileA", b"fileA"), ("fileB", b"fileB")], bid_id="bid-delprim")
    assert staged["file_name"] == "fileA"
    doc_a = next(d["doc_id"] for d in staged["documents"] if d["file_name"] == "fileA")
    result = main.delete_source_document("bid-delprim", doc_a)
    assert [d["file_name"] for d in result["documents"]] == ["fileB"]
    assert result["file_name"] == "fileB"


# --------------------------------------------------------------------------- #
# Per-request extraction method + the runtime default it falls back to.
# --------------------------------------------------------------------------- #

def _capture_req_settings(monkeypatch):
    """Swap the requirement extractor for one that records the use_ai_extract flag
    of the Settings it was handed, so we can assert method threading."""
    seen: dict[str, bool] = {}

    def fake(settings, _parsed):
        seen["use_ai_extract"] = settings.use_ai_extract
        return []

    monkeypatch.setattr(main.databricks_api, "extract_and_classify_requirements", fake)
    return seen


def test_extract_requirements_method_forces_ai_query(multifile_env, monkeypatch):
    seen = _capture_req_settings(monkeypatch)
    _stage([("fileA", b"fileA")], bid_id="bid-method")
    main.extract_requirements_endpoint("bid-method", main.ExtractRequest(method="ai_query"))
    assert seen["use_ai_extract"] is False


def test_extract_requirements_method_forces_ai_extract(multifile_env, monkeypatch):
    seen = _capture_req_settings(monkeypatch)
    _stage([("fileA", b"fileA")], bid_id="bid-method2")
    main.extract_requirements_endpoint("bid-method2", main.ExtractRequest(method="ai_extract"))
    assert seen["use_ai_extract"] is True


def test_extract_requirements_no_method_uses_runtime_default(multifile_env, monkeypatch):
    """method=None (default body) resolves to the process-local extraction default,
    which the Settings pane sets — not the frozen deploy-time Settings."""
    from server import config

    seen = _capture_req_settings(monkeypatch)
    monkeypatch.setattr(config, "_runtime_use_ai_extract", False)
    _stage([("fileA", b"fileA")], bid_id="bid-default")
    main.extract_requirements_endpoint("bid-default")  # no ExtractRequest -> default
    assert seen["use_ai_extract"] is False


def test_line_items_method_forces_ai_query(multifile_env, monkeypatch):
    seen: dict[str, bool] = {}

    def fake_lines(settings, _parsed):
        seen["use_ai_extract"] = settings.use_ai_extract
        return []

    monkeypatch.setattr(main.databricks_api, "extract_line_items", fake_lines)
    _stage([("fileA", b"fileA")], bid_id="bid-lmethod")
    main.extract_line_items_endpoint("bid-lmethod", main.ExtractRequest(method="ai_query"))
    assert seen["use_ai_extract"] is False


def test_settings_endpoints_roundtrip(monkeypatch):
    """GET reflects the runtime override; PATCH sets it. Reset the module global
    afterwards so the process-local default doesn't leak across tests."""
    from server import config

    monkeypatch.setattr(config, "_runtime_use_ai_extract", None)
    # Env baseline (use_ai_extract default True) surfaces as ai_extract.
    assert main.get_app_settings()["extraction_method"] == "ai_extract"
    out = main.update_app_settings(main.SettingsRequest(extraction_method="ai_query"))
    assert out["extraction_method"] == "ai_query"
    assert main.get_app_settings()["extraction_method"] == "ai_query"
    assert config.get_extraction_default() is False


def test_match_sensitivity_settings_roundtrip(monkeypatch):
    """Match sensitivity is a partial PATCH field: setting it changes the
    effective threshold and doesn't disturb the extraction method."""
    from server import config

    monkeypatch.setattr(config, "_runtime_match_sensitivity", None)
    # Default is balanced -> 0.70.
    resp = main.get_app_settings()
    assert resp["match_sensitivity"] == "balanced"
    assert resp["match_threshold"] == 0.70
    # PATCH only the sensitivity; extraction method must be untouched.
    out = main.update_app_settings(main.SettingsRequest(match_sensitivity="conservative"))
    assert out["match_sensitivity"] == "conservative"
    assert out["match_threshold"] == 0.80
    assert config.get_match_threshold() == 0.80
    monkeypatch.setattr(config, "_runtime_match_sensitivity", None)
