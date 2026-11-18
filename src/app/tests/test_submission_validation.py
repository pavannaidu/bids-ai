"""Regression tests for the P0 submission gate: a bid must not be submittable
unless every line has a real catalog selection, a valid non-negative price,
and an explicit (non-"pending") reviewer decision."""

from __future__ import annotations

from server.state import InMemoryBidStore
from server.validation import validate_bid_ready_for_submission as _validate_bid_ready_for_submission


def _line(line_id: str, line_number: int, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "line_id": line_id,
        "line_number": line_number,
        "selected_item_code": "SKU-100001",
        "proposed_price": 12.5,
        "review_action": "accepted",
    }
    base.update(overrides)
    return base


def test_zero_of_fifteen_reviewed_blocks_every_line():
    bid = {"line_items": [_line(f"line-{i}", i, review_action="pending") for i in range(1, 16)]}
    blocking = _validate_bid_ready_for_submission(bid)
    assert len(blocking) == 15
    assert all("Not yet reviewed" in b["reasons"] for b in blocking)


def test_mixed_bid_only_blocks_pending_lines():
    bid = {
        "line_items": [
            _line("line-1", 1, review_action="accepted"),
            _line("line-2", 2, review_action="pending"),
            _line("line-3", 3, review_action="overridden"),
        ]
    }
    blocking = _validate_bid_ready_for_submission(bid)
    assert [b["line_number"] for b in blocking] == [2]


def test_missing_catalog_selection_blocks_even_if_reviewed():
    bid = {"line_items": [_line("line-1", 1, selected_item_code=None, review_action="accepted")]}
    blocking = _validate_bid_ready_for_submission(bid)
    assert len(blocking) == 1
    assert "No catalog item selected" in blocking[0]["reasons"]


def test_empty_string_catalog_selection_blocks():
    bid = {"line_items": [_line("line-1", 1, selected_item_code="", review_action="accepted")]}
    blocking = _validate_bid_ready_for_submission(bid)
    assert "No catalog item selected" in blocking[0]["reasons"]


def test_negative_price_blocks():
    bid = {"line_items": [_line("line-1", 1, proposed_price=-1.0, review_action="accepted")]}
    blocking = _validate_bid_ready_for_submission(bid)
    assert "No valid non-negative price" in blocking[0]["reasons"]


def test_missing_price_blocks():
    bid = {"line_items": [_line("line-1", 1, proposed_price=None, review_action="accepted")]}
    blocking = _validate_bid_ready_for_submission(bid)
    assert "No valid non-negative price" in blocking[0]["reasons"]


def test_zero_price_is_valid():
    bid = {"line_items": [_line("line-1", 1, proposed_price=0.0, review_action="accepted")]}
    assert _validate_bid_ready_for_submission(bid) == []


def test_fully_complete_bid_has_no_blocking_lines():
    bid = {"line_items": [_line(f"line-{i}", i) for i in range(1, 4)]}
    assert _validate_bid_ready_for_submission(bid) == []


def test_line_can_have_multiple_reasons_at_once():
    bid = {
        "line_items": [
            _line("line-1", 1, selected_item_code=None, proposed_price=None, review_action="pending"),
        ]
    }
    blocking = _validate_bid_ready_for_submission(bid)
    assert len(blocking) == 1
    assert set(blocking[0]["reasons"]) == {
        "No catalog item selected",
        "No valid non-negative price",
        "Not yet reviewed",
    }


def test_no_match_resolution_allows_submission_without_a_reason():
    """A no_match line is RESOLVED (no code/price/reason needed) and must NOT
    block submission — it just renders blank in the proposal."""
    bid = {"line_items": [_line(
        "line-1", 1, selected_item_code=None, proposed_price=None,
        review_action="overridden", resolution="no_match",
    )]}
    assert _validate_bid_ready_for_submission(bid) == []


def test_no_match_via_real_store_resolve():
    """The store's resolve_no_match output must satisfy the submission gate."""
    store = InMemoryBidStore()
    store.create_bid(
        bid_id="bid-1", file_name="test.pdf", customer_id="CUST-1001",
        customer_name="Test Customer", solicitation_ref="", due_date="2026-08-01",
        uploaded_document_path="/Volumes/cat/schema/vol/uploads/bid-1/test.pdf",
    )
    store.add_line_items("bid-1", [
        {"line_id": "line-1", "line_number": 1, "raw_description": "obscure item", "qty": 1, "uom": "EA"},
    ])
    store.resolve_no_match("bid-1", "line-1", reviewer_email="rep@example.com")
    bid = store.get_bid("bid-1")
    assert bid["line_items"][0]["resolution"] == "no_match"
    assert _validate_bid_ready_for_submission(bid) == []


def test_against_real_in_memory_store_shape():
    """Exercises the actual InMemoryBidStore output (not just hand-built dicts),
    to guard against the validator assuming a field shape the store doesn't
    actually produce."""
    store = InMemoryBidStore()
    store.create_bid(
        bid_id="bid-1", file_name="test.pdf", customer_id="CUST-1001",
        customer_name="Test Customer", solicitation_ref="", due_date="2026-08-01",
        uploaded_document_path="/Volumes/cat/schema/vol/uploads/bid-1/test.pdf",
    )
    store.add_line_items("bid-1", [
        {"line_id": "line-1", "line_number": 1, "raw_description": "gloves", "qty": 1, "uom": "BX"},
    ])

    # Freshly matched, never reviewed — must block.
    bid = store.get_bid("bid-1")
    blocking = _validate_bid_ready_for_submission(bid)
    assert len(blocking) == 1
    assert "Not yet reviewed" in blocking[0]["reasons"]
    assert "No catalog item selected" in blocking[0]["reasons"]
    assert "No valid non-negative price" in blocking[0]["reasons"]

    # After a real review action, the line clears.
    store.review_line(
        "bid-1", "line-1", selected_item_code="SKU-100001", proposed_price=9.99,
        pricing_basis="list_price", review_action="accepted", reviewer_email="rep@example.com",
    )
    bid = store.get_bid("bid-1")
    assert _validate_bid_ready_for_submission(bid) == []
