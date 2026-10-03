from decimal import Decimal

from shared_expenses import (
    allocation_from_legacy_row,
    allocation_from_up_transaction,
    allocation_balance_components,
    make_group_allocation,
    parse_joint_tag,
    personal_spend_for_transaction,
    shared_summary,
)


def test_joint_tag_defaults_to_half():
    parsed = parse_joint_tag("food,joint")
    assert parsed["angus_ratio"] == Decimal("0.5")
    assert parsed["ebony_ratio"] == Decimal("0.5")


def test_joint_ratio_tags():
    assert parse_joint_tag("joint-a60")["angus_ratio"] == Decimal("0.6")
    assert parse_joint_tag("joint-e60")["angus_ratio"] == Decimal("0.4")


def test_group_tag_requires_review():
    parsed = parse_joint_tag("group")
    assert parsed["allocation_type"] == "group_booking"
    assert parsed["status"] == "review"


def test_up_joint_allocation_counts_only_angus_share():
    row = {
        "id": "txn-1",
        "amount": "-100.00",
        "tags": "joint-a60",
        "description": "Dinner",
        "category": "restaurants-and-cafes",
        "settled_at": "2026-10-01T10:00:00+10:00",
    }
    allocation = allocation_from_up_transaction(row)
    assert allocation["angus_share"] == "60.00"
    assert allocation["ebony_share"] == "40.00"
    assert personal_spend_for_transaction(row, {"txn-1": allocation}) == Decimal("60.00")


def test_legacy_row_preserves_personal_plus_half_joint():
    row = {
        "date": "2025-09-30",
        "description": "Grand Hotel",
        "who_paid": "Angus",
        "angus_amount": "48.50",
        "ebony_amount": "36.50",
        "joint_amount": "20.00",
        "category": "Restaurants",
    }
    allocation = allocation_from_legacy_row(row, 1)
    assert allocation["gross_amount"] == "105.00"
    assert allocation["angus_share"] == "58.50"
    assert allocation["ebony_share"] == "46.50"


def test_group_booking_rounds_and_reconciles():
    allocation = make_group_allocation(
        source="up",
        source_transaction_id="hoyts-1",
        date="2026-09-01",
        description="Hoyts",
        payer="Angus",
        gross_amount="435.60",
        people_count=17,
        angus_units=1,
        ebony_units=1,
        category="events-and-gigs",
    )
    assert allocation["unit_price"] == "25.62"
    assert allocation["angus_share"] == "25.62"
    assert allocation["ebony_share"] == "25.62"
    assert Decimal(allocation["angus_share"]) + Decimal(allocation["ebony_share"]) + Decimal(allocation["other_share"]) == Decimal("435.60")


def test_balance_when_angus_paid():
    allocation = make_group_allocation(
        source="up",
        source_transaction_id="hoyts-1",
        date="2026-09-01",
        description="Hoyts",
        payer="Angus",
        gross_amount="435.60",
        people_count=17,
        angus_units=1,
        ebony_units=1,
    )
    components = allocation_balance_components(allocation)
    assert components["ebony_owes_angus"] == Decimal("25.62")
    assert components["other_owes_angus"] == Decimal("384.36")


def test_settlement_reduces_receivable_not_personal_spend():
    allocation = make_group_allocation(
        source="up",
        source_transaction_id="hoyts-1",
        date="2026-09-01",
        description="Hoyts",
        payer="Angus",
        gross_amount="100.00",
        people_count=4,
        angus_units=1,
        ebony_units=1,
    )
    settlement = {
        "settlement_id": "s1",
        "amount": "25.00",
        "matched_allocation_id": allocation["allocation_id"],
    }
    summary = shared_summary([allocation], [settlement])
    assert summary["personal_spend"] == 25.0
    assert summary["ebony_owes_angus"] == 0.0
    assert summary["other_owes_angus"] == 50.0
