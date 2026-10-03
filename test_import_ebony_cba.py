from pathlib import Path
from import_ebony_cba import parse_cba_row, row_id, classify_row_type, extract_value_date, extract_merchant

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


def test_extract_value_date_card_purchase():
    assert extract_value_date("COLES 0524 DONCASTER E VI AUS Card xx1537 Value Date: 14/06/2026") == "2026-06-14"

def test_extract_value_date_missing_returns_none():
    assert extract_value_date("Direct Debit 025632 A.E.U. VICTORIAN 10037868-12673127") is None

def test_extract_merchant_strips_card_suffix_and_state_code():
    assert extract_merchant("COLES 0524 DONCASTER E VI AUS Card xx1537 Value Date: 14/06/2026") == "Coles 0524 Doncaster E"
    assert extract_merchant("WOOLWORTHS 3301 DONCASTER VI AUS Card xx1537 Value Date: 18/07/2026") == "Woolworths 3301 Doncaster"

def test_extract_merchant_paypal_prefix():
    assert extract_merchant("PAYPAL *APPLE.COM/BILL 4029357733 AU AUS Card xx1537 Value Date: 23/07/2026") == "Paypal - Apple.com/bill"
    assert extract_merchant("PAYPAL *DISNEYPLUS 4029357733 AU AUS Card xx1537 Value Date: 13/07/2026") == "Paypal - Disneyplus"

def test_extract_merchant_keeps_full_multiword_business_name():
    # No location-guessing: the whole business name is preserved, unlike a
    # trailing-word heuristic which would incorrectly cut "Company" or "The Pines".
    assert extract_merchant("COLONIAL FRUIT COMPANY DONCASTER EAS AUS Card xx1537 Value Date: 18/07/2026") == "Colonial Fruit Company Doncaster Eas"
    assert extract_merchant("Boost Juice The Pines Doncaster Eas VI AUS Card xx1537 Value Date: 15/02/2026") == "Boost Juice The Pines Doncaster Eas"

def test_extract_merchant_mixed_case_input_unchanged():
    assert extract_merchant("Bakers Delight St Helena AU AUS Card xx1537 Value Date: 10/05/2026") == "Bakers Delight St Helena Au"

def test_extract_merchant_mixed_case_brand_name_preserved():
    assert extract_merchant("WWW.THEFISHANDBURGERCO DONCASTER EAS VI AUS Card xx1537 Value Date: 21/02/2026") == "Www.thefishandburgerco Doncaster Eas"
