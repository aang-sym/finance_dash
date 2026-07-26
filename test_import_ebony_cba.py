from pathlib import Path
from import_ebony_cba import parse_cba_row, row_id, classify_row_type

def test_parse_cba_row_card_purchase():
    row = ["25/07/2026", "-9.99", "PAYPAL *APPLE.COM/BILL 4029357733 AU AUS Card xx1537 Value Date: 23/07/2026", "+1889.31"]
    result = parse_cba_row(row)
    assert result["date"] == "2026-07-25"
    assert result["amount"] == -9.99
    assert result["description"] == "PAYPAL *APPLE.COM/BILL 4029357733 AU AUS Card xx1537 Value Date: 23/07/2026"
    assert result["row_type"] == "card_purchase"

def test_parse_cba_row_transfer():
    row = ["22/07/2026", "-2000.00", "Transfer to xx2784 CommBank app", "+2095.44"]
    result = parse_cba_row(row)
    assert result["row_type"] == "transfer"

def test_parse_cba_row_direct_debit():
    row = ["23/07/2026", "-71.59", "Direct Debit 025632 A.E.U. VICTORIAN 10037868-12673127", "+1951.85"]
    result = parse_cba_row(row)
    assert result["row_type"] == "direct_debit"

def test_parse_cba_row_malformed_returns_none():
    assert parse_cba_row(["not-a-date", "-9.99", "desc", "+100"]) is None
    assert parse_cba_row(["25/07/2026", "not-a-number", "desc", "+100"]) is None
    assert parse_cba_row(["25/07/2026", "-9.99"]) is None

def test_row_id_stable():
    id1 = row_id("2026-07-25", -9.99, "PAYPAL TEST")
    id2 = row_id("2026-07-25", -9.99, "PAYPAL TEST")
    assert id1 == id2
    assert len(id1) == 40  # sha1 hex digest length

def test_row_id_differs_on_different_input():
    id1 = row_id("2026-07-25", -9.99, "PAYPAL TEST")
    id2 = row_id("2026-07-25", -10.99, "PAYPAL TEST")
    assert id1 != id2

def test_classify_row_type_other():
    assert classify_row_type("KMART 1373 DONC") == "other"
