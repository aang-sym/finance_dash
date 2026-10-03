from __future__ import annotations

import csv
import hashlib
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


ALLOCATION_FIELDS = [
    "allocation_id",
    "source",
    "source_transaction_id",
    "event_key",
    "date",
    "description",
    "payer",
    "gross_amount",
    "allocation_type",
    "angus_share",
    "ebony_share",
    "other_share",
    "people_count",
    "unit_price",
    "angus_units",
    "ebony_units",
    "other_units",
    "category",
    "status",
    "notes",
]

SETTLEMENT_FIELDS = [
    "settlement_id",
    "date",
    "source",
    "source_transaction_id",
    "event_key",
    "from_person",
    "to_person",
    "amount",
    "matched_allocation_id",
    "notes",
]

JOINT_TAG_RE = re.compile(r"^joint(?:-([ae])(\d{1,3}))?$", re.IGNORECASE)

CATEGORY_MAP = {
    "restaurants": "restaurants-and-cafes",
    "restaurant": "restaurants-and-cafes",
    "events": "events-and-gigs",
    "event": "events-and-gigs",
    "groceries": "groceries",
    "misc": "uncategorised",
    "shopping": "shopping",
    "travel": "holidays-and-travel",
    "takeaway": "takeaway",
}


def _money(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value).replace("$", "").replace(",", "").strip() or "0")


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _money_str(value: Decimal) -> str:
    return f"{_q(value):.2f}"


def stable_id(*parts: str) -> str:
    payload = "|".join(str(part or "") for part in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def normalise_category(value: str) -> str:
    raw = (value or "").strip()
    key = raw.lower()
    if not key:
        return "uncategorised"
    if key in CATEGORY_MAP:
        return CATEGORY_MAP[key]
    return re.sub(r"[^a-z0-9]+", "-", key).strip("-") or "uncategorised"


def parse_tags(value: str) -> List[str]:
    return [tag.strip().lower() for tag in (value or "").split(",") if tag.strip()]


def parse_joint_tag(value: str) -> Optional[Dict[str, object]]:
    """
    Interpret lightweight Up tags:
      joint      -> Angus 50 / Ebony 50
      joint-a60  -> Angus 60 / Ebony 40
      joint-e60  -> Ebony 60 / Angus 40
      group      -> group booking requiring review
    """
    tags = parse_tags(value)
    if "group" in tags or "group-booking" in tags:
        return {"allocation_type": "group_booking", "status": "review"}

    for tag in tags:
        match = JOINT_TAG_RE.match(tag)
        if not match:
            continue
        side, pct_raw = match.groups()
        if not pct_raw:
            angus_pct = Decimal("50")
        else:
            pct = Decimal(pct_raw)
            if pct < 0 or pct > 100:
                return None
            angus_pct = pct if side and side.lower() == "a" else Decimal("100") - pct
        return {
            "allocation_type": "joint",
            "status": "confirmed",
            "angus_ratio": angus_pct / Decimal("100"),
            "ebony_ratio": (Decimal("100") - angus_pct) / Decimal("100"),
        }
    return None


def allocation_from_up_transaction(row: Dict[str, str]) -> Optional[Dict[str, str]]:
    parsed = parse_joint_tag(row.get("tags", ""))
    if not parsed:
        return None

    amount = _money(row.get("amount"))
    if amount >= 0:
        return None

    gross = abs(amount)
    transaction_id = (row.get("id") or "").strip()
    if not transaction_id:
        return None

    allocation_type = str(parsed["allocation_type"])
    if allocation_type == "group_booking":
        angus_share = gross
        ebony_share = Decimal("0")
        other_share = Decimal("0")
    else:
        angus_share = _q(gross * parsed["angus_ratio"])
        ebony_share = _q(gross - angus_share)
        other_share = Decimal("0")

    dt = row.get("settled_at") or row.get("created_at") or ""
    return {
        "allocation_id": stable_id("up", transaction_id),
        "source": "up",
        "source_transaction_id": transaction_id,
        "event_key": "",
        "date": dt[:10],
        "description": (row.get("description") or "").strip(),
        "payer": "Angus",
        "gross_amount": _money_str(gross),
        "allocation_type": allocation_type,
        "angus_share": _money_str(angus_share),
        "ebony_share": _money_str(ebony_share),
        "other_share": _money_str(other_share),
        "people_count": "",
        "unit_price": "",
        "angus_units": "",
        "ebony_units": "",
        "other_units": "",
        "category": normalise_category(row.get("category") or ""),
        "status": str(parsed["status"]),
        "notes": "Created from Up tag",
    }


def allocation_from_legacy_row(row: Dict[str, str], row_number: int = 0) -> Dict[str, str]:
    angus_amount = _money(row.get("angus_amount"))
    ebony_amount = _money(row.get("ebony_amount"))
    joint_amount = _money(row.get("joint_amount"))
    gross = angus_amount + ebony_amount + joint_amount
    angus_share = _q(angus_amount + joint_amount / Decimal("2"))
    ebony_share = _q(ebony_amount + joint_amount / Decimal("2"))

    source_key = stable_id(
        "legacy",
        row.get("date", ""),
        row.get("description", ""),
        row.get("who_paid", ""),
        _money_str(angus_amount),
        _money_str(ebony_amount),
        _money_str(joint_amount),
        row.get("category", ""),
    )

    return {
        "allocation_id": source_key,
        "source": "legacy_joint_ledger",
        "source_transaction_id": source_key,
        "event_key": "",
        "date": (row.get("date") or "").strip(),
        "description": (row.get("description") or "").strip(),
        "payer": (row.get("who_paid") or "").strip() or "Angus",
        "gross_amount": _money_str(gross),
        "allocation_type": "legacy_joint",
        "angus_share": _money_str(angus_share),
        "ebony_share": _money_str(ebony_share),
        "other_share": "0.00",
        "people_count": "",
        "unit_price": "",
        "angus_units": "",
        "ebony_units": "",
        "other_units": "",
        "category": normalise_category(row.get("category") or ""),
        "status": "confirmed",
        "notes": "Migrated from joint_ledger.csv",
    }


def make_group_allocation(
    *,
    source: str,
    source_transaction_id: str,
    date: str,
    description: str,
    payer: str,
    gross_amount,
    people_count: int,
    angus_units: int,
    ebony_units: int,
    event_key: str = "",
    category: str = "",
    notes: str = "",
) -> Dict[str, str]:
    if people_count <= 0:
        raise ValueError("people_count must be positive")
    if angus_units < 0 or ebony_units < 0:
        raise ValueError("unit counts cannot be negative")
    if angus_units + ebony_units > people_count:
        raise ValueError("Angus + Ebony units cannot exceed people_count")

    gross = _q(_money(gross_amount))
    unit_price = gross / Decimal(people_count)
    other_units = people_count - angus_units - ebony_units
    angus_share = _q(unit_price * Decimal(angus_units))
    ebony_share = _q(unit_price * Decimal(ebony_units))
    other_share = _q(gross - angus_share - ebony_share)

    allocation_id = stable_id(source, source_transaction_id, event_key, date, description)
    return {
        "allocation_id": allocation_id,
        "source": source,
        "source_transaction_id": source_transaction_id,
        "event_key": event_key,
        "date": date,
        "description": description,
        "payer": payer,
        "gross_amount": _money_str(gross),
        "allocation_type": "group_booking",
        "angus_share": _money_str(angus_share),
        "ebony_share": _money_str(ebony_share),
        "other_share": _money_str(other_share),
        "people_count": str(people_count),
        "unit_price": _money_str(unit_price),
        "angus_units": str(angus_units),
        "ebony_units": str(ebony_units),
        "other_units": str(other_units),
        "category": normalise_category(category),
        "status": "confirmed",
        "notes": notes,
    }


def read_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, fieldnames: List[str], rows: Iterable[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def load_allocations(data_dir: Path) -> List[Dict[str, str]]:
    return read_rows(data_dir / "shared_allocations.csv")


def save_allocations(data_dir: Path, rows: Iterable[Dict[str, str]]) -> None:
    write_rows(data_dir / "shared_allocations.csv", ALLOCATION_FIELDS, rows)


def load_settlements(data_dir: Path) -> List[Dict[str, str]]:
    return read_rows(data_dir / "shared_settlements.csv")


def save_settlements(data_dir: Path, rows: Iterable[Dict[str, str]]) -> None:
    write_rows(data_dir / "shared_settlements.csv", SETTLEMENT_FIELDS, rows)


def sync_up_allocations(
    transaction_rows: Iterable[Dict[str, str]],
    existing_allocations: Iterable[Dict[str, str]],
) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    rows = [dict(row) for row in existing_allocations]
    by_source_id = {
        (row.get("source") or "", row.get("source_transaction_id") or ""): row
        for row in rows
        if row.get("source_transaction_id")
    }

    added = 0
    review = 0
    for txn in transaction_rows:
        allocation = allocation_from_up_transaction(txn)
        if not allocation:
            continue
        key = ("up", allocation["source_transaction_id"])
        if key in by_source_id:
            continue
        rows.append(allocation)
        by_source_id[key] = allocation
        added += 1
        if allocation["status"] == "review":
            review += 1

    rows.sort(key=lambda row: (row.get("date", ""), row.get("description", "")), reverse=True)
    return rows, {"added": added, "review": review, "total": len(rows)}


def allocation_index(allocations: Iterable[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    return {
        row.get("source_transaction_id", ""): row
        for row in allocations
        if row.get("source_transaction_id") and row.get("status") == "confirmed"
    }


def settlement_transaction_ids(settlements: Iterable[Dict[str, str]]) -> set[str]:
    return {
        row.get("source_transaction_id", "")
        for row in settlements
        if row.get("source_transaction_id")
    }


def personal_spend_for_transaction(
    row: Dict[str, str],
    allocations_by_transaction: Dict[str, Dict[str, str]],
) -> Optional[Decimal]:
    transaction_id = row.get("id") or ""
    allocation = allocations_by_transaction.get(transaction_id)
    if allocation:
        return _q(_money(allocation.get("angus_share")))

    inferred = allocation_from_up_transaction(row)
    if inferred and inferred.get("status") == "confirmed":
        return _q(_money(inferred.get("angus_share")))
    return None


def allocation_balance_components(allocation: Dict[str, str]) -> Dict[str, Decimal]:
    payer = (allocation.get("payer") or "").strip().lower()
    angus = _q(_money(allocation.get("angus_share")))
    ebony = _q(_money(allocation.get("ebony_share")))
    other = _q(_money(allocation.get("other_share")))

    result = {
        "ebony_owes_angus": Decimal("0"),
        "angus_owes_ebony": Decimal("0"),
        "other_owes_angus": Decimal("0"),
    }
    if payer == "angus":
        result["ebony_owes_angus"] = ebony
        result["other_owes_angus"] = other
    elif payer == "ebony":
        result["angus_owes_ebony"] = angus
    return result


def shared_summary(
    allocations: Iterable[Dict[str, str]],
    settlements: Iterable[Dict[str, str]],
) -> Dict[str, object]:
    confirmed = [row for row in allocations if row.get("status") == "confirmed"]
    review = [row for row in allocations if row.get("status") != "confirmed"]

    ebony_owes = Decimal("0")
    angus_owes = Decimal("0")
    other_owes = Decimal("0")
    personal_spend = Decimal("0")
    recoverable = Decimal("0")

    by_id = {row.get("allocation_id", ""): row for row in confirmed if row.get("allocation_id")}
    repaid_by_allocation: Dict[str, Decimal] = {}

    for settlement in settlements:
        allocation_id = settlement.get("matched_allocation_id") or ""
        if allocation_id:
            repaid_by_allocation[allocation_id] = repaid_by_allocation.get(allocation_id, Decimal("0")) + _money(settlement.get("amount"))

    for allocation in confirmed:
        personal_spend += _money(allocation.get("angus_share"))
        components = allocation_balance_components(allocation)
        ebony_owes += components["ebony_owes_angus"]
        angus_owes += components["angus_owes_ebony"]
        other_owes += components["other_owes_angus"]
        recoverable += components["ebony_owes_angus"] + components["other_owes_angus"]

        repaid = repaid_by_allocation.get(allocation.get("allocation_id", ""), Decimal("0"))
        if repaid > 0:
            remaining = repaid
            if components["ebony_owes_angus"] > 0:
                applied = min(components["ebony_owes_angus"], remaining)
                ebony_owes -= applied
                remaining -= applied
            if remaining > 0 and components["other_owes_angus"] > 0:
                applied = min(components["other_owes_angus"], remaining)
                other_owes -= applied
                remaining -= applied

    net_ebony = ebony_owes - angus_owes
    return {
        "confirmed_count": len(confirmed),
        "review_count": len(review),
        "personal_spend": float(_q(personal_spend)),
        "recoverable_created": float(_q(recoverable)),
        "ebony_owes_angus": float(_q(max(net_ebony, Decimal("0")))),
        "angus_owes_ebony": float(_q(max(-net_ebony, Decimal("0")))),
        "other_owes_angus": float(_q(max(other_owes, Decimal("0")))),
        "review": review,
    }


def outstanding_for_allocation(
    allocation: Dict[str, str],
    settlements: Iterable[Dict[str, str]],
) -> Decimal:
    components = allocation_balance_components(allocation)
    outstanding = components["ebony_owes_angus"] + components["other_owes_angus"]
    allocation_id = allocation.get("allocation_id") or ""
    repaid = sum(
        _money(row.get("amount"))
        for row in settlements
        if row.get("matched_allocation_id") == allocation_id
    )
    return _q(max(outstanding - repaid, Decimal("0")))


def suggest_settlement_matches(
    transaction_rows: Iterable[Dict[str, str]],
    allocations: Iterable[Dict[str, str]],
    settlements: Iterable[Dict[str, str]],
    *,
    max_days: int = 90,
) -> List[Dict[str, object]]:
    """Suggest positive Up credits that look like repayments of shared expenses.

    Suggestions are deliberately non-destructive. Exact event-key matches score
    highest; amount/date/person hints are used only to rank possible matches.
    """
    allocation_rows = [
        row for row in allocations
        if row.get("status") == "confirmed"
        and (row.get("payer") or "").strip().lower() == "angus"
    ]
    settlement_rows = list(settlements)
    used_transaction_ids = settlement_transaction_ids(settlement_rows)
    suggestions: List[Dict[str, object]] = []

    for txn in transaction_rows:
        txn_id = (txn.get("id") or "").strip()
        if not txn_id or txn_id in used_transaction_ids:
            continue
        amount = _money(txn.get("amount"))
        if amount <= 0:
            continue

        dt_raw = txn.get("settled_at") or txn.get("created_at") or ""
        try:
            txn_dt = datetime.fromisoformat(dt_raw.replace("Z", "+00:00"))
            txn_date = txn_dt.date()
        except Exception:
            txn_date = None

        text = " ".join([
            txn.get("description") or "",
            txn.get("message") or "",
            txn.get("raw_text") or "",
            txn.get("tags") or "",
        ]).lower()

        candidates = []
        for allocation in allocation_rows:
            outstanding = outstanding_for_allocation(allocation, settlement_rows)
            if outstanding <= 0:
                continue

            alloc_date = None
            try:
                alloc_date = datetime.fromisoformat((allocation.get("date") or "")[:10]).date()
            except Exception:
                pass
            if txn_date and alloc_date:
                delta_days = (txn_date - alloc_date).days
                if delta_days < 0 or delta_days > max_days:
                    continue
            else:
                delta_days = None

            score = 0
            reasons = []
            event_key = (allocation.get("event_key") or "").strip().lower()
            if event_key and event_key in text:
                score += 100
                reasons.append("event key")
            if "ebony" in text and _money(allocation.get("ebony_share")) > 0:
                score += 30
                reasons.append("Ebony credit")
            difference = abs(amount - outstanding)
            if difference <= Decimal("0.05"):
                score += 60
                reasons.append("exact outstanding amount")
            elif amount < outstanding and amount >= Decimal("1"):
                score += 20
                reasons.append("possible partial repayment")
            elif amount > outstanding and difference <= Decimal("5"):
                score += 10
                reasons.append("near outstanding amount")

            description = (allocation.get("description") or "").lower()
            description_words = [
                word for word in re.findall(r"[a-z0-9]+", description)
                if len(word) >= 4
            ]
            if description_words and any(word in text for word in description_words):
                score += 15
                reasons.append("description hint")

            if delta_days is not None:
                if delta_days <= 7:
                    score += 15
                    reasons.append("within 7 days")
                elif delta_days <= 30:
                    score += 8
                    reasons.append("within 30 days")

            if score >= 35:
                candidates.append({
                    "allocation_id": allocation.get("allocation_id", ""),
                    "description": allocation.get("description", ""),
                    "event_key": allocation.get("event_key", ""),
                    "outstanding": float(outstanding),
                    "score": score,
                    "reasons": reasons,
                })

        candidates.sort(key=lambda item: (-item["score"], abs(float(amount) - item["outstanding"])))
        if candidates:
            suggestions.append({
                "source_transaction_id": txn_id,
                "date": txn_date.isoformat() if txn_date else "",
                "description": txn.get("description") or txn.get("raw_text") or "",
                "amount": float(_q(amount)),
                "best": candidates[0],
                "alternatives": candidates[1:4],
            })

    suggestions.sort(key=lambda item: (-item["best"]["score"], item["date"]))
    return suggestions
