from pathlib import Path

from selfwealth import (
    classify_cash_comment,
    merge_movement_exports,
    movement_unit_delta,
    parse_cash_csv,
    parse_movements_csv,
    parse_portfolio_csv,
    yahoo_symbol,
)


def test_cash_comment_classification():
    assert classify_cash_comment("PAYMENT FROM Mr Angus Symons", 1000, 0) == "external_contribution"
    assert classify_cash_comment("Direct Transfer", 2000, 0) == "external_contribution"
    assert classify_cash_comment("Transfer 2,013.31 AUD to USD. Estimate 1 AUD = 0.737898 USD", 0, 2013.31) == "internal_fx"
    assert classify_cash_comment("Order 19: Brokerage BUY LIT", 0, 9.5) == "brokerage"
    assert classify_cash_comment("Order 19: Buy 17 LIT @ $84.90", 0, 1443.3) == "trade_buy"
    assert classify_cash_comment("Dividend GOOG", 12.5, 0) == "dividend"
    assert classify_cash_comment("7 MSFT CASHDIV @ USD 0.91", 6.37, 0) == "dividend"
    assert classify_cash_comment("7 MSFT CASHDIV @ USD 0.91 (WITH HOLDING TAX)", 0, 0.96) == "fee"
    assert classify_cash_comment("7 MSFT CASHDIV @ USD 0.91 (Cash Div Fee)", 0, 0.08) == "fee"
    assert classify_cash_comment("CASH DIV @ USD 0.21 LESS TAX 15% 40 Alphabet - C GOOG", 8.4, 0) == "dividend"
    assert classify_cash_comment("17 LIT TAX REFUND @ USD 0.000332417", 0.01, 0) == "dividend"
    assert classify_cash_comment("Convert 271.82 USD TO AUD. 1 USD = 1.414709 AUD", 384.55, 0) == "internal_fx"
    assert classify_cash_comment("Transfer 68.41 USD to AUD. Estimate 1 USD = 1.458200 AUD", 0, 68.41) == "internal_fx"
    assert classify_cash_comment("na", 0, 274.62) == "external_withdrawal"
    assert classify_cash_comment("NEED FUNDS", 0, 384.55) == "external_withdrawal"


def test_parse_cash_csv(tmp_path: Path):
    path = tmp_path / "cash.csv"
    path.write_text(
        "TransactionDate,Comment,Credit,Debit,Balance * Please note, this is not a bank statement.\n"
        ",Opening Balance,,,2013.310000\n"
        "2021-09-07 11:33:21,\"Transfer 2,013.31 AUD to USD. Estimate 1 AUD = 0.737898 USD\",,2013.31,0.000000\n"
        "2021-09-15 00:00:00,Direct Transfer,2000.00,,2000.000000\n",
        encoding="utf-8",
    )
    parsed = parse_cash_csv(path, "AU")
    assert parsed["opening_balance"] == 2013.31
    assert parsed["start_date"].isoformat() == "2021-09-07"
    assert parsed["rows"][0]["kind"] == "internal_fx"
    assert parsed["rows"][1]["kind"] == "external_contribution"


def test_parse_portfolio_csv_without_header(tmp_path: Path):
    path = tmp_path / "portfolio.csv"
    path.write_text(
        "A200,BETASHARES AUSTRALIA 200 ETF,144.900000,73.000000,10577.700000,14.54\n"
        "CASH,Cash,,,17.970000,0.02\n",
        encoding="utf-8",
    )
    parsed = parse_portfolio_csv(path, "AU")
    assert parsed["positions"][0]["ticker"] == "A200"
    assert parsed["positions"][0]["units"] == 73
    assert parsed["positions"][1]["ticker"] == "CASH"
    assert parsed["positions"][1]["market_value"] == 17.97


def test_movements_signed_units(tmp_path: Path):
    path = tmp_path / "movements.csv"
    path.write_text(
        "Trade Date,Settlement Date,Action,Reference,Code,Name,Units,Average Price,Consideration,Brokerage,Total\n"
        "2022-01-20 00:00:00,2022-01-24 00:00:00,Buy,T1,MQG,MACQUARIE GROUP LTD,10,196.92,1969.20,9.50,1978.70\n"
        "2023-01-20 00:00:00,2023-01-24 00:00:00,Sell,T2,MQG,MACQUARIE GROUP LTD,2,200.00,400.00,9.50,390.50\n",
        encoding="utf-8",
    )
    rows = parse_movements_csv(path, "AU")
    assert movement_unit_delta(rows[0]) == 10
    assert movement_unit_delta(rows[1]) == -2


def test_merge_overlapping_movement_exports_deduplicates(tmp_path: Path):
    header = (
        "Trade Date,Settlement Date,Action,Reference,Code,Name,Units,"
        "Average Price,Consideration,Brokerage,Total\n"
    )
    old = tmp_path / "old.csv"
    fresh = tmp_path / "fresh.csv"
    old.write_text(
        header
        + "2020-03-27 00:00:00,2020-03-31 00:00:00,Buy,T0,A200,A200,59,100,5900,9.5,5909.5\n"
        + "2021-09-22 00:00:00,2021-09-24 00:00:00,Buy,T1,VGS,VGS,20,100.89,2017.8,9.5,2027.3\n",
        encoding="utf-8",
    )
    fresh.write_text(
        header
        + "2021-09-22 00:00:00,2021-09-24 00:00:00,Buy,T1,VGS,VGS,20,100.89,2017.8,9.5,2027.3\n"
        + "2026-07-16 00:00:00,2026-07-16 00:00:00,In,DRP1,VGS,VGS,1,0,0,0,0\n",
        encoding="utf-8",
    )
    rows = merge_movement_exports([old, fresh], "AU")
    assert len(rows) == 3
    assert rows[0]["ticker"] == "A200"
    assert rows[-1]["action"] == "In"


def test_z1p_uses_zip_price_history():
    assert yahoo_symbol("AU", "Z1P") == "ZIP.AX"
    assert yahoo_symbol("AU", "ZIP") == "ZIP.AX"
