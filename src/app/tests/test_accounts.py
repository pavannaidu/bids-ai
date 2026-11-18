"""Creating an account from the app ("Bidding on behalf of" -> New account).

Lakebase isn't configured under tests, so reference.create_customer takes the
in-process fallback path: it appends to a module-level list that get_customers()
merges on top of the seeded CUSTOMERS. Verifies the new account is immediately
resolvable by the same get_customer() gate the upload endpoint uses."""

from __future__ import annotations

import pytest

from server import reference


@pytest.fixture(autouse=True)
def _clean_app_customers():
    """The fallback store is a module global; reset it around each test so
    accounts don't leak between tests."""
    saved = list(reference._app_customers)
    reference._app_customers.clear()
    yield
    reference._app_customers.clear()
    reference._app_customers.extend(saved)


def test_create_customer_returns_well_formed_account_with_generated_id():
    created = reference.create_customer("Acme Health System")
    assert created["customer_name"] == "Acme Health System"
    # Generated id is a CUST- id but not one of the seeded CUST-10xx ids.
    assert created["customer_id"].startswith("CUST-")
    assert created["customer_id"] not in {"CUST-1001", "CUST-1006"}
    # Defaults fill the fields matching/pricing read, so the row is complete.
    assert created["division_id"] == "DIV-CORE"
    assert created["customer_type"] == "Unspecified"
    assert created["region"] == "Unspecified"


def test_created_account_is_resolvable_by_get_customer():
    created = reference.create_customer("Beta Regional Clinic")
    # This is exactly the lookup the upload endpoint uses to validate customer_id.
    found = reference.get_customer(created["customer_id"])
    assert found is not None
    assert found["customer_name"] == "Beta Regional Clinic"


def test_created_account_appears_after_seeded_accounts_in_the_list():
    before = reference.get_customers()
    assert any(c["customer_id"] == "CUST-1001" for c in before)  # seeded still present
    created = reference.create_customer("Gamma Dental Group")
    after = reference.get_customers()
    assert len(after) == len(before) + 1
    # Seeded accounts are all still present; the new one is appended at the end.
    assert after[-1]["customer_id"] == created["customer_id"]
    assert any(c["customer_id"] == "CUST-1001" for c in after)


def test_generated_ids_are_unique_across_creations():
    a = reference.create_customer("One")
    b = reference.create_customer("Two")
    assert a["customer_id"] != b["customer_id"]
