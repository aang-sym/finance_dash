import csv
from pathlib import Path

import pytest

from server import get_angus_joint_candidates, DATA_DIR


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("server.DATA_DIR", tmp_path)
    spending_fields = [
        "id", "created_at", "settled_at", "description", "message", "amount",
        "status", "category", "parent_category", "tags", "transfer_account_id",
        "transaction_type", "raw_text",
    ]
    rows = [
        {"id": "tx1", "created_at": "2026-07-01T10:00:00+10:00", "settled_at": "", "description": "Woolworths", "message": "", "amount": "-25.00", "status": "SETTLED", "category": "groceries", "parent_category": "home", "tags": "joint", "transfer_account_id": "", "transaction_type": "Purchase", "raw_text": ""},
        {"id": "tx2", "created_at": "2026-07-02T10:00:00+10:00", "settled_at": "", "description": "Rent", "message": "", "amount": "-100.00", "status": "SETTLED", "category": "rent", "parent_category": "home", "tags": "rent-jul-2026", "transfer_account_id": "", "transaction_type": "Purchase", "raw_text": ""},
        {"id": "tx3", "created_at": "2026-07-03T10:00:00+10:00", "settled_at": "", "description": "Dinner", "message": "", "amount": "-50.00", "status": "SETTLED", "category": "restaurants", "parent_category": "good-life", "tags": "joint,jarrod", "transfer_account_id": "", "transaction_type": "Purchase", "raw_text": ""},
    ]
    with (tmp_path / "transactions_spending.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=spending_fields)
        writer.writeheader()
        writer.writerows(rows)
    with (tmp_path / "transactions_2up.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=spending_fields)
        writer.writeheader()
    return tmp_path


def test_get_angus_joint_candidates_filters_by_tag(tmp_data_dir):
    candidates = get_angus_joint_candidates()
    ids = {c["id"] for c in candidates}
    assert ids == {"tx1", "tx3"}


def test_get_angus_joint_candidates_extracts_fields(tmp_data_dir):
    candidates = get_angus_joint_candidates()
    tx1 = next(c for c in candidates if c["id"] == "tx1")
    assert tx1["date"] == "2026-07-01"
    assert tx1["description"] == "Woolworths"
    assert tx1["amount"] == "-25.00"
