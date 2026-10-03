from pathlib import Path

from selfwealth import (
    classify_cash_comment,
    movement_unit_delta,
    parse_cash_csv,
    parse_movements_csv,
    parse_portfolio_csv,
)


def test_cash_comment_classification():
    assert classify_cash_comment("PAYMENT FROM Mr Angus Symons", 1000, 0) == "external_contribution"
    assert classify_cash_comment("Direct Transfer", 2000, 0) == "external_contribution"
    assert classify_cash_comment("Transfer 2,013.31 AUD to USD. Estimate 1 AUD = 0.737898 USD", 0, 2013.31) == "internal_fx"
    assert classify_cash_comment("Order 19: Brokerage BUY LIT", 0, 9.5) == "brokerage"
    assert classify_cash_comment("Order 19: Buy 17 LIT @ $84.90", 0, 1443.3) == "trade_buy"
    assert classify_cash_comment("Dividend GOOG", 12.5, 0) == "dividend"


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
