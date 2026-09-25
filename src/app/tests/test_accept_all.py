"""Regression tests for the "Accept eligible matches" bulk-review action: it
should only touch lines that are still pending, matched to a catalog item, AND
whose selected candidate is auto_select_eligible (the guardrail predicate) —
never a line a human already accepted/overrode, never an unmatched line, and
never a GUARDED line (below threshold / UOM mismatch / incompatible) that a
reviewer must decide on deliberately."""

from __future__ import annotations

from server.state import InMemoryBidStore
from server.validation import lines_defaulting_to_no_match, lines_eligible_for_bulk_accept


def _line(line_id: str, line_number: int, *, eligible: bool = True, **overrides: object) -> dict[str, object]:
    """A pending, matched line. By default its selected candidate is
    auto_select_eligible; pass eligible=False to simulate a guarded selection."""
    selected = overrides.get("selected_item_code", "SKU-100001")
    base: dict[str, object] = {
        "line_id": line_id,
        "line_number": line_number,
        "selected_item_code": selected,
        "proposed_price": 12.5,
        "review_action": "pending",
        "candidates": (
            [{"item_code": selected, "auto_select_eligible": eligible}] if selected else []
        ),
    }
    base.update(overrides)
    return base


def test_pending_line_with_a_match_is_eligible():
    bid = {"line_items": [_line("line-1", 1)]}
    eligible = lines_eligible_for_bulk_accept(bid)
    assert [l["line_id"] for l in eligible] == ["line-1"]


def test_already_accepted_line_is_left_alone():
    bid = {"line_items": [_line("line-1", 1, review_action="accepted")]}
    assert lines_eligible_for_bulk_accept(bid) == []


def test_already_overridden_line_is_left_alone():
    bid = {"line_items": [_line("line-1", 1, review_action="overridden")]}
    assert lines_eligible_for_bulk_accept(bid) == []


def test_unmatched_pending_line_is_left_alone():
    """No candidate selected at all — still needs a manual catalog search."""
    bid = {"line_items": [_line("line-1", 1, selected_item_code=None)]}
    assert lines_eligible_for_bulk_accept(bid) == []


def test_empty_string_selection_is_not_eligible():
    bid = {"line_items": [_line("line-1", 1, selected_item_code="")]}
    assert lines_eligible_for_bulk_accept(bid) == []


def test_guarded_selection_is_not_eligible():
    """A pending line whose selected candidate is NOT auto_select_eligible (below
    threshold / UOM mismatch / incompatible) must never be bulk-accepted."""
    bid = {"line_items": [_line("line-1", 1, eligible=False)]}
    assert lines_eligible_for_bulk_accept(bid) == []


def test_mixed_bid_only_returns_pending_eligible_matched_lines():
    bid = {
        "line_items": [
            _line("line-1", 1, review_action="accepted"),
            _line("line-2", 2),  # pending, matched, eligible -> eligible
            _line("line-3", 3, selected_item_code=None),  # pending, unmatched -> not eligible
            _line("line-4", 4, review_action="overridden"),
            _line("line-5", 5, eligible=False),  # pending, matched, but GUARDED -> not eligible
        ]
    }
    eligible = lines_eligible_for_bulk_accept(bid)
    assert [l["line_id"] for l in eligible] == ["line-2"]


def test_against_real_in_memory_store_after_matching():
    """Mirrors what match_bid actually does in main.py: pre-populate a pending
    selection with a computed price — exactly the state Accept all picks up —
    then simulates the endpoint's own accept loop via the public store API."""
    store = InMemoryBidStore()
    store.create_bid(
        bid_id="bid-1", file_name="test.pdf", customer_id="CUST-1001",
        customer_name="Test Customer", solicitation_ref="", due_date="2026-08-01",
        uploaded_document_path="/Volumes/cat/schema/vol/uploads/bid-1/test.pdf",
    )
    store.add_line_items("bid-1", [
        {"line_id": "line-1", "line_number": 1, "raw_description": "gloves", "qty": 1, "uom": "BX"},
    ])

    # Freshly added, unmatched -> nothing eligible yet.
    assert lines_eligible_for_bulk_accept(store.get_bid("bid-1")) == []

    # match_bid sets the candidate list, then pre-populates a pending selection +
    # price for the top candidate (only when it's auto_select_eligible).
    store.set_line_candidates("bid-1", "line-1", [
        {"item_code": "SKU-100001", "auto_select_eligible": True, "semantic_score": 0.82},
    ])
    store.review_line(
        "bid-1", "line-1", selected_item_code="SKU-100001", proposed_price=9.99,
        pricing_basis="last price paid by this customer (2026-01-01)",
        review_action="pending", reviewer_email=None,
    )
    eligible = lines_eligible_for_bulk_accept(store.get_bid("bid-1"))
    assert [l["line_id"] for l in eligible] == ["line-1"]

    # What the accept-all endpoint does with that eligible line: reuse its
    # existing selection/price as-is, just flip the review decision.
    for line in eligible:
        store.review_line(
            "bid-1", line["line_id"],
            selected_item_code=line["selected_item_code"],
            proposed_price=line["proposed_price"],
            pricing_basis="reviewer-selected",
            review_action="accepted",
            reviewer_email="rep@example.com",
        )

    bid = store.get_bid("bid-1")
    accepted_line = bid["line_items"][0]
    assert accepted_line["review_action"] == "accepted"
    assert accepted_line["proposed_price"] == 9.99  # unchanged by the bulk accept
    assert lines_eligible_for_bulk_accept(bid) == []  # not eligible for a repeat run


# --------------------------------------------------------------------------- #
# lines_defaulting_to_no_match — the leftovers Accept-all defaults to no_match.
# --------------------------------------------------------------------------- #


def test_defaulting_returns_pending_non_eligible_lines():
    """Every pending line Accept-all does NOT catalog-accept — guarded selections
    and unmatched lines — is defaulted to no_match."""
    bid = {
        "line_items": [
            _line("line-1", 1),  # eligible catalog match -> NOT defaulting
            _line("line-2", 2, eligible=False),  # guarded selection -> defaulting
            _line("line-3", 3, selected_item_code=None),  # unmatched -> defaulting
        ]
    }
    assert [l["line_id"] for l in lines_defaulting_to_no_match(bid)] == ["line-2", "line-3"]


def test_defaulting_excludes_already_resolved_and_reviewed():
    bid = {
        "line_items": [
            _line("line-1", 1, review_action="accepted"),  # already reviewed
            _line("line-2", 2, review_action="overridden"),  # already reviewed
            _line("line-3", 3, selected_item_code=None, resolution="no_match"),  # already no_match
        ]
    }
    assert lines_defaulting_to_no_match(bid) == []


def test_eligible_and_defaulting_never_overlap():
    """The two lists partition the pending, unresolved lines — no line is both
    catalog-accepted and defaulted-to-no-match."""
    bid = {
        "line_items": [
            _line("line-1", 1),  # eligible
            _line("line-2", 2, eligible=False),  # defaulting
            _line("line-3", 3, selected_item_code=None),  # defaulting
        ]
    }
    eligible_ids = {l["line_id"] for l in lines_eligible_for_bulk_accept(bid)}
    defaulting_ids = {l["line_id"] for l in lines_defaulting_to_no_match(bid)}
    assert eligible_ids.isdisjoint(defaulting_ids)


def test_accept_all_clears_the_whole_list_via_real_store():
    """The full endpoint behavior: eligible lines become accepted catalog matches,
    every remaining pending line becomes a resolved no_match. Afterward nothing is
    eligible and nothing defaults — the list is fully cleared."""
    store = InMemoryBidStore()
    store.create_bid(
        bid_id="bid-1", file_name="test.pdf", customer_id="CUST-1001",
        customer_name="Test Customer", solicitation_ref="", due_date="2026-08-01",
        uploaded_document_path="/Volumes/cat/schema/vol/uploads/bid-1/test.pdf",
    )
    store.add_line_items("bid-1", [
        {"line_id": "line-1", "line_number": 1, "raw_description": "gloves", "qty": 1, "uom": "BX"},
        {"line_id": "line-2", "line_number": 2, "raw_description": "burn jel", "qty": 1, "uom": "BTL"},
    ])
    # line-1: eligible catalog match. line-2: guarded (candidate not eligible).
    store.set_line_candidates("bid-1", "line-1", [
        {"item_code": "SKU-100001", "auto_select_eligible": True, "semantic_score": 0.82},
    ])
    store.review_line(
        "bid-1", "line-1", selected_item_code="SKU-100001", proposed_price=9.99,
        pricing_basis="list_price", review_action="pending", reviewer_email=None,
    )
    store.set_line_candidates("bid-1", "line-2", [
        {"item_code": "SKU-100095", "auto_select_eligible": False, "semantic_score": 0.44},
    ])

    bid = store.get_bid("bid-1")
    eligible = lines_eligible_for_bulk_accept(bid)
    defaulting = lines_defaulting_to_no_match(bid)
    assert [l["line_id"] for l in eligible] == ["line-1"]
    assert [l["line_id"] for l in defaulting] == ["line-2"]

    # Mirror accept_all_lines: accept eligible, no-match the rest.
    for line in eligible:
        store.review_line(
            "bid-1", line["line_id"], selected_item_code=line["selected_item_code"],
            proposed_price=line["proposed_price"], pricing_basis="reviewer-selected",
            review_action="accepted", reviewer_email="rep@example.com",
        )
    for line in defaulting:
        store.resolve_no_match("bid-1", line["line_id"], reviewer_email="rep@example.com")

    bid = store.get_bid("bid-1")
    by_id = {l["line_id"]: l for l in bid["line_items"]}
    assert by_id["line-1"]["review_action"] == "accepted"
    assert by_id["line-2"]["resolution"] == "no_match"
    assert by_id["line-2"]["selected_item_code"] is None
    assert by_id["line-2"]["proposed_price"] is None
    # Fully cleared: a repeat Accept-all would touch nothing.
    assert lines_eligible_for_bulk_accept(bid) == []
    assert lines_defaulting_to_no_match(bid) == []
