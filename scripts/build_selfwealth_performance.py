#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List

from selfwealth import (
    YahooPrices,
    current_snapshot_summary,
    dividend_totals_aud,
    external_cash_flows_aud,
    market_value_aud,
    modified_dietz,
    month_range,
    parse_cash_csv,
    parse_movements_csv,
    parse_portfolio_csv,
    reconcile_units,
    snapshot_date_from_name,
)


BASE_DIR = Path(__file__).resolve().parents[1]
IMPORT_DIR = BASE_DIR / "imports" / "selfwealth"
DATA_DIR = BASE_DIR / "data"


def newest(pattern: str) -> Path:
    matches = sorted(IMPORT_DIR.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No SelfWealth file matches {pattern}")
    return max(matches, key=lambda path: path.stat().st_mtime)


def historical_movements(market: str) -> Path:
    matches = sorted(IMPORT_DIR.glob(f"{market} - Movements-*.csv"))
    if not matches:
        raise FileNotFoundError(f"No {market} SelfWealth Movements CSV found")
    return max(matches, key=lambda path: path.stat().st_mtime)


def _serialise_row(row: Dict[str, object]) -> Dict[str, object]:
    out = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat(sep=" ")
        elif isinstance(value, date):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


def write_csv(path: Path, rows: Iterable[Dict[str, object]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(_serialise_row(row))


def build() -> Dict[str, object]:
    au_cash_path = newest("selfwealth_au_cash_*.csv")
    us_cash_path = newest("selfwealth_us_cash_*.csv")
    au_portfolio_path = newest("selfwealth_au_portfolio_*.csv")
    us_portfolio_path = newest("selfwealth_us_portfolio_*.csv")
    au_movements_path = historical_movements("AU")
    us_movements_path = historical_movements("US")

    au_cash = parse_cash_csv(au_cash_path, "AU")
    us_cash = parse_cash_csv(us_cash_path, "US")
    au_portfolio = parse_portfolio_csv(au_portfolio_path, "AU")
    us_portfolio = parse_portfolio_csv(us_portfolio_path, "US")
    movements = (
        parse_movements_csv(au_movements_path, "AU")
        + parse_movements_csv(us_movements_path, "US")
    )
    movements.sort(key=lambda row: row["trade_date"])

    au_snapshot_date = snapshot_date_from_name(au_portfolio_path)
    us_snapshot_date = snapshot_date_from_name(us_portfolio_path)
    if not au_snapshot_date or not us_snapshot_date:
        raise RuntimeError("Could not infer current portfolio statement dates from filenames")
    snapshot_date = min(au_snapshot_date, us_snapshot_date)

    reconciliation = reconcile_units(
        movements,
        [au_portfolio, us_portfolio],
        snapshot_date,
    )

    cash_starts = [
        value for value in (au_cash.get("start_date"), us_cash.get("start_date")) if value
    ]
    if not cash_starts:
        raise RuntimeError("SelfWealth cash files contain no dated transactions")
    performance_start = max(cash_starts)

    last_movement_date = max(row["trade_date"].date() for row in movements)
    performance_end = snapshot_date
    performance_complete_to_snapshot = not reconciliation
    if reconciliation:
        performance_end = min(snapshot_date, last_movement_date)

    if performance_end <= performance_start:
        raise RuntimeError("No usable SelfWealth performance period after cash-history start")

    prices = YahooPrices(DATA_DIR / "selfwealth_prices.json")

    symbols = {"AUDUSD=X"}
    for row in movements:
        if row["trade_date"].date() <= performance_end:
            ticker = str(row["ticker"])
            market = str(row["market"])
            symbols.add(f"{ticker}.AX" if market == "AU" else ticker)
    for portfolio in (au_portfolio, us_portfolio):
        for position in portfolio["positions"]:
            ticker = str(position["ticker"])
            if ticker.upper() in {"CASH", "US CASH"}:
                continue
            market = str(position["market"])
            symbols.add(f"{ticker}.AX" if market == "AU" else ticker)

    price_errors = []
    for symbol in sorted(symbols):
        try:
            prices.ensure(symbol, performance_start, snapshot_date)
        except Exception as exc:
            price_errors.append({"symbol": symbol, "error": str(exc)})
    prices.save()

    monthly_twr: Dict[str, float] = {}
    monthly_values: Dict[str, Dict[str, float]] = {}
    skipped_months = []

    for period_start, period_end, label in month_range(performance_start, performance_end):
        begin = market_value_aud(
            on_date=period_start,
            movements=movements,
            au_cash=au_cash,
            us_cash=us_cash,
            prices=prices,
        )
        end = market_value_aud(
            on_date=period_end,
            movements=movements,
            au_cash=au_cash,
            us_cash=us_cash,
            prices=prices,
        )
        if not begin or not end:
            skipped_months.append(label)
            continue
        flows = external_cash_flows_aud(
            au_cash,
            us_cash,
            prices,
            period_start,
            period_end,
        )
        result = modified_dietz(
            begin["combined"],
            end["combined"],
            flows,
            period_start,
            period_end,
        )
        if result is None:
            skipped_months.append(label)
            continue
        monthly_twr[label] = round(result * 100, 6)
        monthly_values[label] = {
            "begin_value_aud": round(begin["combined"], 2),
            "end_value_aud": round(end["combined"], 2),
            "au_end_value_aud": round(end["au"], 2),
            "us_end_value_aud": round(end["us"], 2),
            "external_flow_aud": round(sum(float(flow["amount"]) for flow in flows), 2),
        }

    current = current_snapshot_summary(
        au_portfolio,
        us_portfolio,
        prices,
        snapshot_date,
    )

    returns = [monthly_twr[key] / 100 for key in sorted(monthly_twr)]
    chained = 1.0
    for value in returns:
        chained *= 1.0 + value
    since_return_pct = (chained - 1.0) * 100 if returns else None

    months = len(returns)
    annualised_pct = None
    if months and chained > 0:
        annualised_pct = (chained ** (12 / months) - 1.0) * 100

    ytd_prefix = str(snapshot_date.year)
    ytd = 1.0
    ytd_count = 0
    for month_key, pct in monthly_twr.items():
        if month_key.startswith(ytd_prefix):
            ytd *= 1.0 + pct / 100
            ytd_count += 1
    ytd_pct = (ytd - 1.0) * 100 if ytd_count else None

    dividends = dividend_totals_aud([au_cash, us_cash], prices)
    flows = external_cash_flows_aud(
        au_cash,
        us_cash,
        prices,
        performance_start,
        performance_end,
    )

    cash_kind_counts: Dict[str, int] = {}
    unknown_cash_examples = []
    for cash in (au_cash, us_cash):
        for row in cash["rows"]:
            kind = str(row["kind"])
            cash_kind_counts[kind] = cash_kind_counts.get(kind, 0) + 1
            if kind == "cash_other" and len(unknown_cash_examples) < 25:
                unknown_cash_examples.append({
                    "market": row["market"],
                    "date": row["date"].isoformat(sep=" "),
                    "comment": row["comment"],
                    "credit": row["credit"],
                    "debit": row["debit"],
                })

    payload = {
        "available": bool(monthly_twr),
        "platform": "SelfWealth",
        "performance_method": "monthly_modified_dietz",
        "performance_start": performance_start.isoformat(),
        "performance_end": performance_end.isoformat(),
        "snapshot_date": snapshot_date.isoformat(),
        "performance_complete_to_snapshot": performance_complete_to_snapshot,
        "monthly_twr": monthly_twr,
        "monthly_values": monthly_values,
        "since_return_pct": round(since_return_pct, 4) if since_return_pct is not None else None,
        "annualised_return_pct": round(annualised_pct, 4) if annualised_pct is not None else None,
        "ytd_return_pct": round(ytd_pct, 4) if ytd_pct is not None else None,
        "dividends_by_year_aud": dividends,
        "current": current,
        "external_flows": [
            {
                "date": flow["date"].isoformat(),
                "amount_aud": round(float(flow["amount"]), 2),
                "market": flow["market"],
                "comment": flow["comment"],
            }
            for flow in flows
        ],
        "data_quality": {
            "unit_reconciliation": reconciliation,
            "price_errors": price_errors,
            "skipped_months": skipped_months,
            "cash_kind_counts": cash_kind_counts,
            "unknown_cash_examples": unknown_cash_examples,
            "last_movement_date": last_movement_date.isoformat(),
            "note": (
                "Current snapshot units differ from reconstructed Movements history, "
                "so return history is capped at the last available security movement. "
                "Refresh Movements to extend performance to the snapshot date."
                if reconciliation
                else "Movements reconcile to the current portfolio snapshots."
            ),
        },
        "source_files": {
            "au_cash": au_cash_path.name,
            "us_cash": us_cash_path.name,
            "au_portfolio": au_portfolio_path.name,
            "us_portfolio": us_portfolio_path.name,
            "au_movements": au_movements_path.name,
            "us_movements": us_movements_path.name,
        },
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "selfwealth_performance.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )

    write_csv(
        DATA_DIR / "selfwealth_cashflows.csv",
        [
            {
                "date": flow["date"],
                "amount_aud": round(float(flow["amount"]), 2),
                "market": flow["market"],
                "comment": flow["comment"],
            }
            for flow in flows
        ],
        ["date", "amount_aud", "market", "comment"],
    )
    write_csv(
        DATA_DIR / "selfwealth_movements.csv",
        movements,
        [
            "trade_date", "settlement_date", "market", "action", "reference",
            "ticker", "name", "units", "average_price", "consideration",
            "brokerage", "total",
        ],
    )
    write_csv(
        DATA_DIR / "selfwealth_holdings.csv",
        current["holdings"],
        [
            "market", "ticker", "name", "units", "price_native",
            "value_native", "value_aud", "weight",
        ],
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build SelfWealth performance cache")
    parser.parse_args()
    payload = build()
    print(json.dumps({
        "available": payload["available"],
        "performance_start": payload["performance_start"],
        "performance_end": payload["performance_end"],
        "snapshot_date": payload["snapshot_date"],
        "current_value_aud": payload["current"]["current_value_aud"],
        "months": len(payload["monthly_twr"]),
        "unit_reconciliation": payload["data_quality"]["unit_reconciliation"],
        "price_errors": payload["data_quality"]["price_errors"],
        "skipped_months": payload["data_quality"]["skipped_months"],
    }, indent=2))


if __name__ == "__main__":
    main()
