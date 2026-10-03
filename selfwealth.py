from __future__ import annotations

import csv
import json
import math
import re
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests


CASH_FIELDS = ["date", "market", "comment", "credit", "debit", "balance", "kind"]
PORTFOLIO_FIELDS = ["market", "ticker", "name", "price", "units", "market_value", "weight"]
MOVEMENT_FIELDS = [
    "trade_date", "settlement_date", "market", "action", "reference", "ticker",
    "name", "units", "average_price", "consideration", "brokerage", "total",
]

EXTERNAL_IN_RE = re.compile(r"^(direct transfer|payment from\b)", re.IGNORECASE)
EXTERNAL_OUT_RE = re.compile(r"^(withdraw|payment to\b|direct debit to\b)", re.IGNORECASE)
FX_RE = re.compile(
    r"(?:transfer|convert)\s+[\d,.]+\s+(aud|usd)\s+to\s+(aud|usd)",
    re.IGNORECASE,
)
BUY_RE = re.compile(r"\bbuy\b", re.IGNORECASE)
SELL_RE = re.compile(r"\bsell\b", re.IGNORECASE)
BROKERAGE_RE = re.compile(r"\bbrokerage\b", re.IGNORECASE)
DIVIDEND_RE = re.compile(
    r"\b(dividend|distribution|dist\.?|cashdiv|cash\s+div)\b",
    re.IGNORECASE,
)
TAX_REFUND_RE = re.compile(r"\btax\s+refund\b", re.IGNORECASE)
INTEREST_RE = re.compile(r"\binterest\b", re.IGNORECASE)
FEE_RE = re.compile(
    r"\b(fee|charge|withholding\s+tax|with\s+holding\s+tax|tax\s+withheld|cash\s+div\s+fee)\b",
    re.IGNORECASE,
)


def _float(value) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return 0.0


def parse_dt(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def classify_cash_comment(comment: str, credit: float, debit: float) -> str:
    text = (comment or "").strip()
    lowered = text.lower()
    if FX_RE.search(text):
        return "internal_fx"
    if BROKERAGE_RE.search(text):
        return "brokerage"
    if BUY_RE.search(text):
        return "trade_buy"
    if SELL_RE.search(text):
        return "trade_sell"
    # SelfWealth emits withholding-tax and cash-dividend-fee rows using the
    # same CASHDIV prefix as the gross dividend credit. Debit rows with those
    # fee/tax markers must be classified before generic dividend detection.
    if debit > 0 and FEE_RE.search(text):
        return "fee"
    if DIVIDEND_RE.search(text):
        return "dividend"
    if credit > 0 and TAX_REFUND_RE.search(text):
        # SelfWealth uses TAX REFUND for tiny reversals/adjustments to prior
        # investment-income tax withholding. Treat it as investment income,
        # never as an external contribution.
        return "dividend"
    if INTEREST_RE.search(text):
        return "interest"
    if FEE_RE.search(text):
        return "fee"
    if credit > 0 and EXTERNAL_IN_RE.search(text):
        return "external_contribution"
    if debit > 0 and (
        EXTERNAL_OUT_RE.search(text)
        or lowered in {"na", "need funds"}
    ):
        return "external_withdrawal"
    return "cash_other"


def parse_cash_csv(path: Path, market: str) -> Dict[str, object]:
    rows: List[Dict[str, object]] = []
    opening_balance = 0.0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            dt = parse_dt(raw.get("TransactionDate", ""))
            comment = (raw.get("Comment") or "").strip()
            credit = _float(raw.get("Credit"))
            debit = _float(raw.get("Debit"))
            balance_key = next((key for key in raw if key and key.startswith("Balance")), "Balance")
            balance = _float(raw.get(balance_key))
            if not dt:
                if comment.lower().startswith("opening balance"):
                    opening_balance = balance
                continue
            rows.append({
                "date": dt,
                "market": market,
                "comment": comment,
                "credit": credit,
                "debit": debit,
                "balance": balance,
                "kind": classify_cash_comment(comment, credit, debit),
            })
    rows.sort(key=lambda row: row["date"])
    return {
        "market": market,
        "path": str(path),
        "opening_balance": opening_balance,
        "start_date": rows[0]["date"].date() if rows else None,
        "end_date": rows[-1]["date"].date() if rows else None,
        "rows": rows,
    }


def parse_portfolio_csv(path: Path, market: str) -> Dict[str, object]:
    positions: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row or len(row) < 6:
                continue
            ticker = row[0].strip()
            if not ticker:
                continue
            positions.append({
                "market": market,
                "ticker": ticker,
                "name": row[1].strip(),
                "price": _float(row[2]),
                "units": _float(row[3]),
                "market_value": _float(row[4]),
                "weight": _float(row[5]),
            })
    return {"market": market, "path": str(path), "positions": positions}


def parse_movements_csv(path: Path, market: str) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            trade_dt = parse_dt(raw.get("Trade Date", ""))
            if not trade_dt:
                continue
            action = (raw.get("Action") or "").strip()
            units = _float(raw.get("Units"))
            rows.append({
                "trade_date": trade_dt,
                "settlement_date": parse_dt(raw.get("Settlement Date", "")),
                "market": market,
                "action": action,
                "reference": (raw.get("Reference") or "").strip(),
                "ticker": (raw.get("Code") or "").strip(),
                "name": (raw.get("Name") or "").strip(),
                "units": units,
                "average_price": _float(raw.get("Average Price")),
                "consideration": _float(raw.get("Consideration")),
                "brokerage": _float(raw.get("Brokerage")),
                "total": _float(raw.get("Total")),
            })
    rows.sort(key=lambda row: row["trade_date"])
    return rows


def movement_identity(row: Dict[str, object]) -> Tuple[object, ...]:
    """Stable identity for the same movement appearing in overlapping exports."""
    settlement = row.get("settlement_date")
    return (
        row.get("trade_date"),
        settlement,
        str(row.get("market") or ""),
        str(row.get("action") or "").strip().lower(),
        str(row.get("reference") or "").strip(),
        str(row.get("ticker") or "").strip().upper(),
        round(float(row.get("units") or 0.0), 8),
        round(float(row.get("average_price") or 0.0), 8),
        round(float(row.get("consideration") or 0.0), 8),
        round(float(row.get("brokerage") or 0.0), 8),
        round(float(row.get("total") or 0.0), 8),
    )


def merge_movement_exports(paths: Iterable[Path], market: str) -> List[Dict[str, object]]:
    """Merge overlapping SelfWealth Movements exports without double-counting."""
    by_identity: Dict[Tuple[object, ...], Dict[str, object]] = {}
    for path in paths:
        for row in parse_movements_csv(path, market):
            by_identity.setdefault(movement_identity(row), row)
    rows = list(by_identity.values())
    rows.sort(key=lambda row: (
        row["trade_date"],
        str(row.get("ticker") or ""),
        str(row.get("action") or ""),
        str(row.get("reference") or ""),
    ))
    return rows


def movement_unit_delta(row: Dict[str, object]) -> float:
    action = str(row.get("action") or "").strip().lower()
    units = float(row.get("units") or 0.0)
    if action in {"buy", "in"}:
        return units
    if action in {"sell", "out"}:
        return -units
    return 0.0


def positions_at(movements: Iterable[Dict[str, object]], on_date: date) -> Dict[Tuple[str, str], float]:
    positions: Dict[Tuple[str, str], float] = {}
    for row in movements:
        trade_dt: datetime = row["trade_date"]
        if trade_dt.date() > on_date:
            break
        key = (str(row["market"]), str(row["ticker"]))
        positions[key] = positions.get(key, 0.0) + movement_unit_delta(row)
    return {key: units for key, units in positions.items() if abs(units) > 1e-9}


def cash_balance_at(cash_data: Dict[str, object], on_date: date) -> float:
    balance = float(cash_data.get("opening_balance") or 0.0)
    for row in cash_data.get("rows", []):
        if row["date"].date() > on_date:
            break
        balance = float(row["balance"])
    return balance


def snapshot_date_from_name(path: Path) -> Optional[date]:
    match = re.search(r"(20\d{2})-(\d{2})-(\d{2})", path.name)
    if not match:
        return None
    return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def reconcile_units(
    movements: Iterable[Dict[str, object]],
    portfolios: Iterable[Dict[str, object]],
    snapshot_date: date,
) -> List[Dict[str, object]]:
    reconstructed = positions_at(movements, snapshot_date)
    actual: Dict[Tuple[str, str], float] = {}
    for portfolio in portfolios:
        for position in portfolio.get("positions", []):
            ticker = str(position["ticker"])
            if ticker.upper() in {"CASH", "US CASH"}:
                continue
            actual[(str(position["market"]), ticker)] = float(position["units"])

    keys = sorted(set(reconstructed) | set(actual))
    result = []
    for market, ticker in keys:
        expected = reconstructed.get((market, ticker), 0.0)
        observed = actual.get((market, ticker), 0.0)
        diff = observed - expected
        if abs(diff) > 1e-6:
            result.append({
                "market": market,
                "ticker": ticker,
                "reconstructed_units": round(expected, 6),
                "snapshot_units": round(observed, 6),
                "difference": round(diff, 6),
            })
    return result


class YahooPrices:
    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        if cache_path.exists():
            try:
                self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                self.cache = {}
        else:
            self.cache = {}

    def save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, indent=2, sort_keys=True), encoding="utf-8")

    def ensure(self, symbol: str, start: date, end: date) -> None:
        key = symbol
        existing = self.cache.get(key, {})
        if existing:
            dates = sorted(existing)
            if dates and dates[0] <= start.isoformat() and dates[-1] >= (end - timedelta(days=5)).isoformat():
                return

        period1 = int(datetime.combine(start - timedelta(days=10), datetime.min.time()).timestamp())
        period2 = int(datetime.combine(end + timedelta(days=2), datetime.min.time()).timestamp())
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        response = requests.get(
            url,
            params={"period1": period1, "period2": period2, "interval": "1d", "events": "div,splits"},
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        payload = response.json()
        result = (payload.get("chart") or {}).get("result") or []
        if not result:
            raise RuntimeError(f"No Yahoo price data for {symbol}")
        block = result[0]
        timestamps = block.get("timestamp") or []
        closes = (((block.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
        prices = dict(existing)
        for ts, value in zip(timestamps, closes):
            if value is None:
                continue
            d = datetime.fromtimestamp(ts).date().isoformat()
            prices[d] = float(value)
        self.cache[key] = prices

    def value(self, symbol: str, on_date: date) -> Optional[float]:
        series = self.cache.get(symbol, {})
        if not series:
            return None
        dates = sorted(series)
        idx = bisect_right(dates, on_date.isoformat()) - 1
        if idx < 0:
            return None
        return float(series[dates[idx]])


def yahoo_symbol(market: str, ticker: str) -> str:
    if market.upper() == "AU":
        # SelfWealth records the historical Z1P -> ZIP rename as an Out/In pair.
        # Yahoo carries the continuous price history under the current ZIP symbol.
        aliases = {"Z1P": "ZIP.AX"}
        return aliases.get(ticker.upper(), f"{ticker}.AX")
    return ticker


def aud_per_usd(prices: YahooPrices, on_date: date) -> Optional[float]:
    usd_per_aud = prices.value("AUDUSD=X", on_date)
    if not usd_per_aud:
        return None
    return 1.0 / usd_per_aud


def market_value_aud(
    *,
    on_date: date,
    movements: List[Dict[str, object]],
    au_cash: Dict[str, object],
    us_cash: Dict[str, object],
    prices: YahooPrices,
) -> Optional[Dict[str, float]]:
    positions = positions_at(movements, on_date)
    au_value = cash_balance_at(au_cash, on_date)
    us_value_usd = cash_balance_at(us_cash, on_date)

    for (market, ticker), units in positions.items():
        price = prices.value(yahoo_symbol(market, ticker), on_date)
        if price is None:
            return None
        if market == "AU":
            au_value += units * price
        else:
            us_value_usd += units * price

    usd_to_aud = aud_per_usd(prices, on_date)
    if usd_to_aud is None:
        return None
    us_value_aud = us_value_usd * usd_to_aud
    return {
        "au": au_value,
        "us": us_value_aud,
        "combined": au_value + us_value_aud,
    }


def external_cash_flows_aud(
    au_cash: Dict[str, object],
    us_cash: Dict[str, object],
    prices: YahooPrices,
    start: date,
    end: date,
) -> List[Dict[str, object]]:
    flows: List[Dict[str, object]] = []
    for cash in (au_cash, us_cash):
        market = str(cash["market"])
        for row in cash.get("rows", []):
            d = row["date"].date()
            if d < start or d > end:
                continue
            kind = row["kind"]
            amount = 0.0
            if kind == "external_contribution":
                amount = float(row["credit"])
            elif kind == "external_withdrawal":
                amount = -float(row["debit"])
            else:
                continue
            if market == "US":
                fx = aud_per_usd(prices, d)
                if fx is None:
                    continue
                amount *= fx
            flows.append({"date": d, "amount": amount, "market": market, "comment": row["comment"]})
    flows.sort(key=lambda row: row["date"])
    return flows


def modified_dietz(
    begin_value: float,
    end_value: float,
    flows: List[Dict[str, object]],
    start: date,
    end: date,
) -> Optional[float]:
    days = max((end - start).days, 1)
    total_flow = sum(float(flow["amount"]) for flow in flows)
    weighted = 0.0
    for flow in flows:
        elapsed = max((flow["date"] - start).days, 0)
        weight = max(days - elapsed, 0) / days
        weighted += float(flow["amount"]) * weight
    denominator = begin_value + weighted
    if abs(denominator) < 1e-9:
        return None
    return (end_value - begin_value - total_flow) / denominator


def month_range(start: date, end: date) -> List[Tuple[date, date, str]]:
    cursor = start.replace(day=1)
    result = []
    while cursor <= end:
        if cursor.month == 12:
            next_month = date(cursor.year + 1, 1, 1)
        else:
            next_month = date(cursor.year, cursor.month + 1, 1)
        period_start = max(start, cursor)
        period_end = min(end, next_month - timedelta(days=1))
        if period_start <= period_end:
            result.append((period_start, period_end, f"{cursor.year}{cursor.month:02d}"))
        cursor = next_month
    return result


def dividend_totals_aud(
    cash_data: Iterable[Dict[str, object]],
    prices: YahooPrices,
) -> Dict[str, float]:
    totals: Dict[str, float] = {}
    for cash in cash_data:
        market = str(cash["market"])
        for row in cash.get("rows", []):
            if row.get("kind") != "dividend":
                continue
            amount = float(row.get("credit") or 0.0) - float(row.get("debit") or 0.0)
            if market == "US":
                fx = aud_per_usd(prices, row["date"].date())
                if fx is None:
                    continue
                amount *= fx
            year = str(row["date"].year)
            totals[year] = totals.get(year, 0.0) + amount
    return {year: round(value, 2) for year, value in totals.items()}


def current_snapshot_summary(
    au_portfolio: Dict[str, object],
    us_portfolio: Dict[str, object],
    prices: YahooPrices,
    snapshot_date: date,
) -> Dict[str, object]:
    au_total = sum(float(row["market_value"]) for row in au_portfolio["positions"])
    us_total_usd = sum(float(row["market_value"]) for row in us_portfolio["positions"])
    fx = aud_per_usd(prices, snapshot_date)
    if fx is None:
        raise RuntimeError("Missing AUDUSD FX for current SelfWealth snapshot")
    us_total_aud = us_total_usd * fx

    holdings = []
    for portfolio in (au_portfolio, us_portfolio):
        market = str(portfolio["market"])
        for row in portfolio["positions"]:
            ticker = str(row["ticker"])
            native_value = float(row["market_value"])
            value_aud = native_value if market == "AU" else native_value * fx
            holdings.append({
                "market": market,
                "ticker": ticker,
                "name": row["name"],
                "units": row["units"],
                "price_native": row["price"],
                "value_native": round(native_value, 2),
                "value_aud": round(value_aud, 2),
                "weight": row["weight"],
            })
    return {
        "snapshot_date": snapshot_date.isoformat(),
        "fx_usd_to_aud": round(fx, 6),
        "au_value_aud": round(au_total, 2),
        "us_value_aud": round(us_total_aud, 2),
        "current_value_aud": round(au_total + us_total_aud, 2),
        "holdings": holdings,
    }
