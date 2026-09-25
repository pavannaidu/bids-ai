"""Regression tests for the bid History feature: the uploaded document's Volume
path round-trips through create_bid/get_bid, and list_bids returns lightweight,
newest-first summaries (no line_items) with correct per-bid line counts."""

from __future__ import annotations

from server.state import InMemoryBidStore


def _create(store: InMemoryBidStore, bid_id: str, **overrides: object) -> None:
    base: dict[str, object] = {
        "bid_id": bid_id,
        "file_name": "solicitation.pdf",
        "customer_id": "CUST-1001",
        "customer_name": "Test Customer",
        "solicitation_ref": "",
        "due_date": "2026-08-01",
        "uploaded_document_path": f"/Volumes/cat/schema/vol/uploads/{bid_id}/solicitation.pdf",
    }
    base.update(overrides)
    store.create_bid(**base)


def test_uploaded_document_path_round_trips_through_get_bid():
    store = InMemoryBidStore()
    _create(store, "bid-1", uploaded_document_path="/Volumes/cat/schema/vol/uploads/bid-1/foo.pdf")
    bid = store.get_bid("bid-1")
    assert bid["uploaded_document_path"] == "/Volumes/cat/schema/vol/uploads/bid-1/foo.pdf"


def test_documents_manifest_round_trips_through_get_bid():
    store = InMemoryBidStore()
    docs = [
        {"doc_id": "doc-a", "file_name": "rfp.pdf", "path": "/Volumes/v/uploads/bid-1/doc-a/rfp.pdf", "file_format": "pdf"},
        {"doc_id": "doc-b", "file_name": "pricing.xlsx", "path": "/Volumes/v/uploads/bid-1/doc-b/pricing.xlsx", "file_format": "xlsx"},
    ]
    _create(store, "bid-1", documents=docs)
    bid = store.get_bid("bid-1")
    assert [d["doc_id"] for d in bid["documents"]] == ["doc-a", "doc-b"]
    assert bid["documents"][1]["file_format"] == "xlsx"


def test_get_bid_synthesizes_documents_for_legacy_single_doc_bid():
    """A bid created via the old single-doc signature (no documents kwarg) still
    yields a 1-element documents array, so the frontend viewer always has input."""
    store = InMemoryBidStore()
    _create(store, "bid-1", uploaded_document_path="/Volumes/v/uploads/bid-1/foo.pdf")
    docs = store.get_bid("bid-1")["documents"]
    assert len(docs) == 1
    assert docs[0]["path"] == "/Volumes/v/uploads/bid-1/foo.pdf"
    assert docs[0]["file_name"] == "solicitation.pdf"
    assert docs[0]["file_format"] == "pdf"


def test_list_bids_on_empty_store_returns_empty_list():
    store = InMemoryBidStore()
    assert store.list_bids() == []


def test_list_bids_returns_summaries_newest_first_with_line_counts():
    store = InMemoryBidStore()
    _create(store, "bid-1")
    store.add_line_items("bid-1", [
        {"line_id": "l1", "line_number": 1, "raw_description": "gloves", "qty": 1, "uom": "BX"},
        {"line_id": "l2", "line_number": 2, "raw_description": "gowns", "qty": 1, "uom": "CS"},
    ])
    _create(store, "bid-2")
    store.add_line_items("bid-2", [
        {"line_id": "l3", "line_number": 1, "raw_description": "masks", "qty": 1, "uom": "BX"},
    ])

    summaries = store.list_bids()
    assert [s["bid_id"] for s in summaries] == ["bid-2", "bid-1"]
    assert all("line_items" not in s for s in summaries)
    by_id = {s["bid_id"]: s for s in summaries}
    assert by_id["bid-1"]["line_item_count"] == 2
    assert by_id["bid-2"]["line_item_count"] == 1


def test_bid_name_round_trips_through_get_bid():
    store = InMemoryBidStore()
    _create(store, "bid-1", bid_name="VA Medical Center — Q3 renewal")
    bid = store.get_bid("bid-1")
    assert bid["bid_name"] == "VA Medical Center — Q3 renewal"


def test_bid_name_defaults_to_empty_string_when_not_provided():
    store = InMemoryBidStore()
    _create(store, "bid-1")
    bid = store.get_bid("bid-1")
    assert bid["bid_name"] == ""


def test_list_bids_includes_bid_name_in_summary():
    store = InMemoryBidStore()
    _create(store, "bid-1", bid_name="Q3 renewal")
    summaries = store.list_bids()
    assert summaries[0]["bid_name"] == "Q3 renewal"


def _requirement(requirement_id: str, **overrides: object) -> dict:
    base: dict[str, object] = {
        "requirement_id": requirement_id,
        "term_label": "Indemnification",
        "raw_text": "The Contractor shall indemnify and hold harmless the Agency.",
        "category": "legal",
        "owning_teams": ["Corporate Legal"],
        "risk_level": "high",
        "risk_rationale": "Uncapped indemnity exposure.",
        "matched_term": "Indemnification",
        "source": "matrix",
    }
    base.update(overrides)
    return base


def test_requirements_round_trip_through_get_bid():
    store = InMemoryBidStore()
    _create(store, "bid-1")
    store.add_requirements("bid-1", [
        _requirement("req-1"),
        _requirement("req-2", term_label="E-Verify", owning_teams=["HR"], risk_level="medium",
                     matched_term="E-Verify", category="hr"),
    ])
    bid = store.get_bid("bid-1")
    assert [r["requirement_id"] for r in bid["requirements"]] == ["req-1", "req-2"]
    assert bid["requirements"][0]["owning_teams"] == ["Corporate Legal"]
    assert bid["requirements"][0]["review_status"] == "pending"
    assert bid["requirements"][1]["owning_teams"] == ["HR"]


def test_requirements_preserve_joint_ownership_round_trip():
    store = InMemoryBidStore()
    _create(store, "bid-1")
    store.add_requirements("bid-1", [
        _requirement("req-1", term_label="Warranty of Products",
                     owning_teams=["Business", "Corporate Legal"]),
    ])
    req = store.get_bid("bid-1")["requirements"][0]
    assert req["owning_teams"] == ["Business", "Corporate Legal"]


def test_update_requirement_partial_edit_stamps_updater():
    store = InMemoryBidStore()
    _create(store, "bid-1")
    store.add_requirements("bid-1", [_requirement("req-1")])
    store.update_requirement(
        "bid-1", "req-1",
        fields={"review_status": "approved", "risk_level": "low", "note": "capped at fees"},
        updated_by="legal@example.com",
    )
    req = store.get_bid("bid-1")["requirements"][0]
    assert req["review_status"] == "approved"
    assert req["risk_level"] == "low"
    assert req["note"] == "capped at fees"
    assert req["last_updated_by"] == "legal@example.com"
    assert req["last_updated_at"] is not None
    # Untouched fields keep their values (None fields are ignored).
    assert req["term_label"] == "Indemnification"
    assert req["owning_teams"] == ["Corporate Legal"]


def test_update_requirement_can_reassign_teams():
    store = InMemoryBidStore()
    _create(store, "bid-1")
    store.add_requirements("bid-1", [_requirement("req-1")])
    store.update_requirement(
        "bid-1", "req-1", fields={"owning_teams": ["Risk Management", "Business"]}, updated_by="biz@example.com",
    )
    assert store.get_bid("bid-1")["requirements"][0]["owning_teams"] == ["Risk Management", "Business"]


def test_add_requirement_appends_manual_row():
    store = InMemoryBidStore()
    _create(store, "bid-1")
    store.add_requirements("bid-1", [_requirement("req-1")])
    store.add_requirement(
        "bid-1",
        {"requirement_id": "req-2", "term_label": "Tax Exemption / Withholding",
         "raw_text": "Agency is tax exempt.", "owning_teams": ["Tax"], "risk_level": "low", "source": "manual"},
        updated_by="tax@example.com",
    )
    reqs = store.get_bid("bid-1")["requirements"]
    assert [r["requirement_id"] for r in reqs] == ["req-1", "req-2"]
    added = reqs[1]
    assert added["source"] == "manual"
    assert added["owning_teams"] == ["Tax"]
    assert added["seq"] == 2
    assert added["last_updated_by"] == "tax@example.com"


def test_delete_requirement_removes_row():
    store = InMemoryBidStore()
    _create(store, "bid-1")
    store.add_requirements("bid-1", [_requirement("req-1"), _requirement("req-2")])
    store.delete_requirement("bid-1", "req-1")
    reqs = store.get_bid("bid-1")["requirements"]
    assert [r["requirement_id"] for r in reqs] == ["req-2"]


def test_legacy_status_coerced_on_read():
    store = InMemoryBidStore()
    _create(store, "bid-1")
    store.add_requirements("bid-1", [_requirement("req-1")])
    # Simulate a row written under the old vocabulary.
    store._requirements["bid-1"]["req-1"]["review_status"] = "acknowledged"
    assert store.get_bid("bid-1")["requirements"][0]["review_status"] == "approved"


def test_bid_without_requirements_returns_empty_list():
    store = InMemoryBidStore()
    _create(store, "bid-1")
    assert store.get_bid("bid-1")["requirements"] == []
