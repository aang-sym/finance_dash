import csv
import json
import re
from datetime import date, datetime, timedelta
from datetime import datetime as dt_class
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dateutil import parser
from flask import Flask, jsonify, redirect, request, send_file
from openpyxl import load_workbook

from sync import CONFIG_PATH, DATA_DIR, discover_account_ids, load_config, sync_transactions
from shared_expenses import (
    allocation_from_legacy_row,
    allocation_from_up_transaction,
    allocation_index,
    load_allocations,
    load_settlements,
    make_group_allocation,
    personal_spend_for_transaction,
    save_allocations,
    save_settlements,
    settlement_transaction_ids,
    shared_summary,
    suggest_settlement_matches,
    stable_id as shared_stable_id,
    sync_up_allocations,
)



BASE_DIR = Path(__file__).resolve().parent
BILL_CYCLES_PATH = DATA_DIR / "bill_cycles.csv"
BILL_TYPES_PATH = DATA_DIR / "bill_types.csv"
NETWORTH_CSV = DATA_DIR / "networth.csv"
HOLDINGS_CSV = DATA_DIR / "holdings.csv"
EXCEL_PATH = DATA_DIR / "Net worth calculator.xlsx"
NETWORTH_FIELDS = ["date", "cash_aud", "investments_aud", "super_aud", "total_aud"]
HOLDINGS_FIELDS = [
    "ticker", "platform", "currency", "units",
    "cost_base_aud", "current_price_aud", "current_value_aud",
    "unrealised_gain_aud", "acquisition_date",
]
HOUSEMATE_NAMES = ["angus", "sean", "alex", "jarrod", "ryan"]
BILL_SLUGS = {"rent", "elec", "water", "internet", "gas"}
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
PERIOD_TAG_RE = re.compile(r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)-(\d{4})$")
LABEL_DEFAULTS = {
    "rent": "Rent",
    "elec": "Electricity",
    "water": "Water",
    "internet": "Internet",
    "gas": "Gas",
}

app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def write_csv(path: Path, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_float(value: Optional[str]) -> Optional[float]:
    if value in (None, ""):
        return None
    return float(value)


def parse_bool(value: Optional[str]) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def cycle_tag_for(slug: str, due_date: str) -> Tuple[str, str, str]:
    due = parse_date(due_date)
    month = MONTHS[due.month - 1]
    year = str(due.year)
    return f"{slug}-{month}-{year}", month, year


def parse_cycle_tag(tag: str) -> Optional[Tuple[str, str, str]]:
    parts = [part.strip().lower() for part in (tag or "").split("-")]
    if len(parts) != 3:
        return None
    slug, month, year = parts
    if slug not in BILL_SLUGS or month not in MONTHS or not year.isdigit():
        return None
    return slug, month, year


def parse_period_tag(tag: str) -> Optional[Tuple[str, str]]:
    match = PERIOD_TAG_RE.match((tag or "").strip().lower())
    if not match:
        return None
    return match.group(1), match.group(2)


def expand_bill_cycle_tags(tags: set[str]) -> set[str]:
    expanded = set()
    slug_tags = {tag for tag in tags if tag in BILL_SLUGS}
    period_tags = [parse_period_tag(tag) for tag in tags]
    valid_periods = [period for period in period_tags if period]

    for tag in tags:
        parsed = parse_cycle_tag(tag)
        if parsed:
            slug, month, year = parsed
            expanded.add(f"{slug}-{month}-{year}")

    for slug in slug_tags:
        for month, year in valid_periods:
            expanded.add(f"{slug}-{month}-{year}")

    return expanded


def format_share(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value, 2)


def read_housemates() -> List[Dict[str, str]]:
    return read_csv(DATA_DIR / "housemates.csv")


def read_bill_types() -> Dict[str, Dict[str, str]]:
    rows = read_csv(BILL_TYPES_PATH)
    return {row["slug"]: row for row in rows if row.get("slug")}


def read_bills() -> List[Dict[str, str]]:
    return read_csv(DATA_DIR / "bills.csv")


def read_manual_overrides() -> List[Dict[str, str]]:
    return read_csv(DATA_DIR / "manual_overrides.csv")


def write_bill_cycles(rows: List[Dict[str, str]]) -> None:
    write_csv(
        BILL_CYCLES_PATH,
        [
            "cycle_id",
            "slug",
            "label",
            "provider",
            "month",
            "year",
            "total_due",
            "collected_amount",
            "forwarded_amount",
            "paid_housemates",
            "paid_count",
            "status",
            "latest_activity",
        ],
        rows,
    )


def get_status() -> Dict:
    if not CONFIG_PATH.exists():
        config = {
            "token": "",
            "account_ids": {"spending": "", "savings": "", "grow": "", "two_up": "", "essentials": ""},
            "last_sync_spending": None,
            "last_sync_2up": None,
            "last_sync_essentials": None,
        }
    else:
        with CONFIG_PATH.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
    return {
        "last_sync_spending": config.get("last_sync_spending"),
        "last_sync_2up": config.get("last_sync_2up"),
        "last_sync_essentials": config.get("last_sync_essentials"),
        "account_ids": config.get("account_ids", {}),
        "up_accounts": config.get("up_accounts", []),
        "token_present": bool(config.get("token")),
    }


DEFAULT_ONE_OFF_CATEGORIES = {"holidays-and-travel"}
DEFAULT_ESSENTIAL_CATEGORIES = {
    "groceries",
    "rent-and-mortgage",
    "utilities",
    "internet",
    "fuel",
    "public-transport",
    "mobile-phone",
    "health-and-medical",
    "car-insurance-and-maintenance",
}
INVESTMENT_DESCRIPTIONS = {"ibkr", "selfwealth", "stake", "commsec", "pearler"}
INSURANCE_DESCRIPTIONS = {"john symons", "insurance"}
TAX_DESCRIPTIONS = {"tax office payments", "australian taxation office", "ato"}


def owned_up_account_ids(status: Optional[Dict] = None) -> set[str]:
    """All current Up accounts plus named/legacy IDs used by historical data."""
    status = status or get_status()
    ids = {
        str(account.get("id") or "")
        for account in status.get("up_accounts", [])
        if account.get("id")
    }
    ids.update(
        str(value)
        for value in status.get("account_ids", {}).values()
        if value
    )
    return {account_id for account_id in ids if account_id}


def bill_account_ids(status: Optional[Dict] = None) -> set[str]:
    """Accounts used for household bills, including retired 2Up history."""
    status = status or get_status()
    ids = set()
    for account in status.get("up_accounts", []):
        name = (account.get("display_name") or "").lower()
        if "essentials" in name or "bills" in name:
            if account.get("id"):
                ids.add(str(account["id"]))
    account_ids = status.get("account_ids", {})
    for key in ("essentials", "two_up"):
        if account_ids.get(key):
            ids.add(str(account_ids[key]))
    return ids


def read_all_up_transactions() -> List[Dict[str, str]]:
    """Return transactions across every synced Up account with source metadata."""
    all_path = DATA_DIR / "transactions_all.csv"
    if all_path.exists():
        return read_csv(all_path)

    status = get_status()
    account_ids = status.get("account_ids", {})
    account_names = {
        str(account.get("id") or ""): str(account.get("display_name") or "")
        for account in status.get("up_accounts", [])
        if account.get("id")
    }
    sources = [
        (DATA_DIR / "transactions_spending.csv", account_ids.get("spending", ""), "Spending"),
        (DATA_DIR / "transactions_savings.csv", account_ids.get("savings", ""), "Savings"),
        (DATA_DIR / "transactions_essentials.csv", account_ids.get("essentials", ""), "Essentials"),
        (DATA_DIR / "transactions_2up.csv", account_ids.get("two_up", ""), "Legacy 2Up"),
    ]
    deduped: Dict[str, Dict[str, str]] = {}
    for path, account_id, fallback_name in sources:
        if not path.exists():
            continue
        for row in read_csv(path):
            enriched = dict(row)
            enriched["account_id"] = enriched.get("account_id") or account_id
            enriched["account_name"] = (
                enriched.get("account_name")
                or account_names.get(account_id, fallback_name)
            )
            row_id = enriched.get("id") or ""
            key = f"{enriched.get('account_id', '')}:{row_id}"
            if row_id:
                deduped[key] = enriched
    return list(deduped.values())


def spending_treatment(row: Dict[str, str], config: Optional[Dict] = None) -> str:
    """Classify external spend as essential, lifestyle, one-off or excluded."""
    if config is None:
        try:
            config = load_config()
        except Exception:
            config = {}
    treatment_cfg = config.get("spending_treatments", {})
    category = (row.get("category") or "").strip().lower() or "uncategorised"
    description = (row.get("description") or "").strip().lower()

    merchant_overrides = {
        str(key).strip().lower(): str(value).strip().lower()
        for key, value in treatment_cfg.get("merchant_overrides", {}).items()
    }
    category_overrides = {
        str(key).strip().lower(): str(value).strip().lower()
        for key, value in treatment_cfg.get("category_overrides", {}).items()
    }
    if description in merchant_overrides:
        return merchant_overrides[description]
    if category in category_overrides:
        return category_overrides[category]

    one_off_categories = {
        str(value).strip().lower()
        for value in treatment_cfg.get("one_off_categories", DEFAULT_ONE_OFF_CATEGORIES)
    }
    essential_categories = {
        str(value).strip().lower()
        for value in treatment_cfg.get("essential_categories", DEFAULT_ESSENTIAL_CATEGORIES)
    }
    if category in one_off_categories:
        return "one_off"
    if category in essential_categories:
        return "essential"
    if any(keyword in description for keyword in INSURANCE_DESCRIPTIONS | TAX_DESCRIPTIONS):
        return "essential"
    return "lifestyle"


def is_investment_outflow(row: Dict[str, str]) -> bool:
    description = (row.get("description") or "").strip().lower()
    return any(keyword in description for keyword in INVESTMENT_DESCRIPTIONS)


def is_reimbursement_credit(row: Dict[str, str]) -> bool:
    description = (row.get("description") or "").strip().lower()
    raw_text = (row.get("raw_text") or "").strip().lower()
    haystack = f"{description} {raw_text}"
    return any(keyword in haystack for keyword in ("beem", "refund", "reimbursement", "cashback"))


def period_financials(start: datetime, end: datetime) -> Dict:
    """Personal-spend and cashflow classification across all synced Up accounts."""
    status = get_status()
    internal_ids = owned_up_account_ids(status)
    config = load_config()

    allocations = load_allocations(DATA_DIR)
    settlements = load_settlements(DATA_DIR)
    allocations_by_txn = allocation_index(allocations)
    all_allocations_by_txn = {
        row.get("source_transaction_id", ""): row
        for row in allocations
        if row.get("source_transaction_id")
    }
    settlement_ids = settlement_transaction_ids(settlements)

    result = {
        "income": 0.0,
        "reimbursements": 0.0,
        "shared_settlements": 0.0,
        "total_spend": 0.0,
        "gross_cash_spend": 0.0,
        "ordinary_spend": 0.0,
        "essential_spend": 0.0,
        "lifestyle_spend": 0.0,
        "one_off_spend": 0.0,
        "investment_transfers": 0.0,
        "internal_transfers": 0.0,
        "internal_transfer_count": 0,
        "transaction_count": 0,
        "shared_gross_outflows": 0.0,
        "shared_personal_spend": 0.0,
        "shared_recoverable_created": 0.0,
        "shared_unallocated_gross": 0.0,
        "shared_paid_by_others": 0.0,
        "categories": {},
        "merchants": {},
    }

    seen_allocation_ids: set[str] = set()

    def add_personal_spend(
        spent: float,
        category: str,
        merchant: str,
        treatment: str,
    ) -> None:
        if spent <= 0:
            return
        result["transaction_count"] += 1
        result["total_spend"] += spent
        if treatment == "one_off":
            result["one_off_spend"] += spent
        else:
            result["ordinary_spend"] += spent
            if treatment == "essential":
                result["essential_spend"] += spent
            else:
                result["lifestyle_spend"] += spent

        category_entry = result["categories"].setdefault(
            category,
            {"total": 0.0, "treatment": treatment},
        )
        category_entry["total"] += spent
        if category_entry["treatment"] != treatment:
            category_entry["treatment"] = "mixed"

        merchant_entry = result["merchants"].setdefault(
            merchant,
            {"total": 0.0, "count": 0, "category": category, "treatment": treatment},
        )
        merchant_entry["total"] += spent
        merchant_entry["count"] += 1

    for row in read_all_up_transactions():
        dt_str = row.get("settled_at") or row.get("created_at") or ""
        if not dt_str:
            continue
        try:
            dt = parse_datetime_or_date(dt_str)
        except Exception:
            continue
        if not (start <= dt < end):
            continue

        amount = parse_float(row.get("amount")) or 0.0
        transfer_account_id = (row.get("transfer_account_id") or "").strip()
        if transfer_account_id and transfer_account_id in internal_ids:
            if amount < 0:
                result["internal_transfers"] += abs(amount)
                result["internal_transfer_count"] += 1
            continue

        if amount > 0:
            if row.get("id") in settlement_ids:
                result["shared_settlements"] += amount
            elif is_reimbursement_credit(row):
                result["reimbursements"] += amount
            else:
                result["income"] += amount
            continue
        if amount >= 0:
            continue

        if is_investment_outflow(row):
            result["investment_transfers"] += abs(amount)
            continue

        treatment = spending_treatment(row, config=config)
        if treatment == "exclude":
            continue

        gross = abs(amount)
        result["gross_cash_spend"] += gross
        spent = gross
        category = (row.get("category") or "").strip() or "uncategorised"
        merchant = (row.get("description") or "").strip() or "Unknown"

        transaction_id = row.get("id") or ""
        allocation = all_allocations_by_txn.get(transaction_id)
        inferred = allocation_from_up_transaction(row)
        if (
            (allocation and allocation.get("status") != "confirmed")
            or (allocation is None and inferred and inferred.get("status") != "confirmed")
        ):
            result["shared_gross_outflows"] += gross
            result["shared_unallocated_gross"] += gross
            continue

        personal_override = personal_spend_for_transaction(row, allocations_by_txn)
        if personal_override is not None:
            spent = float(personal_override)
            result["shared_gross_outflows"] += gross
            result["shared_personal_spend"] += spent
            result["shared_recoverable_created"] += max(gross - spent, 0.0)
            if allocation:
                seen_allocation_ids.add(allocation.get("allocation_id") or "")
                category = (allocation.get("category") or category).strip() or category
                merchant = (allocation.get("description") or merchant).strip() or merchant
                treatment = spending_treatment(
                    {"category": category, "description": merchant},
                    config=config,
                )

        add_personal_spend(spent, category, merchant, treatment)

    # Include Angus's responsibility for shared expenses paid by Ebony/others.
    # These affect personal burn but not Angus's bank cash outflow.
    for allocation in allocations:
        if allocation.get("status") != "confirmed":
            continue
        allocation_id = allocation.get("allocation_id") or ""
        if allocation_id in seen_allocation_ids:
            continue
        payer = (allocation.get("payer") or "").strip().lower()
        if payer == "angus":
            continue
        date_raw = (allocation.get("date") or "").strip()
        if not date_raw:
            continue
        try:
            alloc_dt = parser.parse(date_raw).replace(tzinfo=None)
        except Exception:
            continue
        if not (start <= alloc_dt < end):
            continue

        angus_share = parse_float(allocation.get("angus_share")) or 0.0
        if angus_share <= 0:
            continue
        category = (allocation.get("category") or "").strip() or "uncategorised"
        merchant = (allocation.get("description") or "").strip() or "Shared expense"
        treatment = spending_treatment(
            {"category": category, "description": merchant},
            config=config,
        )
        if treatment == "exclude":
            continue

        result["shared_personal_spend"] += angus_share
        result["shared_paid_by_others"] += angus_share
        add_personal_spend(angus_share, category, merchant, treatment)

    for key in (
        "income", "reimbursements", "shared_settlements", "total_spend",
        "gross_cash_spend", "ordinary_spend", "essential_spend",
        "lifestyle_spend", "one_off_spend", "investment_transfers",
        "internal_transfers", "shared_gross_outflows",
        "shared_personal_spend", "shared_recoverable_created",
        "shared_unallocated_gross", "shared_paid_by_others",
    ):
        result[key] = round(float(result[key]), 2)

    # Reimbursements only net ordinary spend where the original purchase has
    # not already been reduced through a shared allocation. Shared settlements
    # are deliberately excluded here to avoid double-netting.
    result["net_external_spend"] = round(
        max(result["total_spend"] - result["reimbursements"], 0.0), 2
    )
    result["net_ordinary_spend"] = round(
        max(result["ordinary_spend"] - result["reimbursements"], 0.0), 2
    )
    return result


def get_budgets() -> Dict[str, float]:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    return {k: float(v) for k, v in config.get("budgets", {}).items()}


def save_budgets(budgets: Dict[str, float]) -> None:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("config.json not found")
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["budgets"] = budgets
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
        handle.write("\n")


def is_incoming_beem(row: Dict[str, str]) -> bool:
    amount = parse_float(row.get("amount")) or 0.0
    description = (row.get("description") or "").lower()
    transfer_account_id = (row.get("transfer_account_id") or "").strip()
    return amount > 0 and ("beem" in description or not transfer_account_id)


def tag_set(tags: str) -> set[str]:
    return {tag.strip().lower() for tag in (tags or "").split(",") if tag.strip()}


def build_override_lookup() -> Dict[Tuple[str, str, str, str], Dict[str, str]]:
    lookup: Dict[Tuple[str, str, str, str], Dict[str, str]] = {}
    for row in read_manual_overrides():
        key = (
            (row.get("housemate") or "").lower(),
            (row.get("slug") or "").lower(),
            (row.get("month") or "").lower(),
            str(row.get("year") or ""),
        )
        lookup[key] = row
    return lookup


def share_for_housemate(bill: Dict[str, str], housemate: Dict[str, str], total_amount: Optional[float]) -> Optional[float]:
    split_type = (bill.get("split_type") or "").lower()
    if split_type == "fixed":
        return format_share(parse_float(housemate.get("rent_share")))
    if split_type == "equal" and total_amount is not None:
        return format_share(total_amount / len(HOUSEMATE_NAMES))
    return None


def total_due_for_bill(bill: Dict[str, str], housemates: List[Dict[str, str]]) -> Optional[float]:
    split_type = (bill.get("split_type") or "").lower()
    if split_type == "fixed":
        return round(sum(parse_float(housemate.get("rent_share")) or 0.0 for housemate in housemates), 2)
    return parse_float(bill.get("total_amount"))


def find_bill_template(slug: str) -> Optional[Dict[str, str]]:
    bills = [bill for bill in read_bills() if (bill.get("slug") or "").lower() == slug.lower()]
    if not bills:
        return None
    bills.sort(key=lambda bill: bill.get("due_date", ""))
    return bills[0]


def cycle_bill_model(slug: str, month: str, year: str) -> Dict[str, Optional[str]]:
    cycle_due_date = f"{year}-{MONTHS.index(month) + 1:02d}-01"
    matching = [
        bill for bill in read_bills()
        if (bill.get("slug") or "").lower() == slug.lower()
        and cycle_tag_for(bill["slug"], bill["due_date"])[0] == f"{slug}-{month}-{year}"
    ]
    template = matching[0] if matching else find_bill_template(slug)
    if template:
        model = dict(template)
        model["slug"] = slug
        model["label"] = template.get("label") or LABEL_DEFAULTS.get(slug, slug.title())
        if not matching:
            model["due_date"] = cycle_due_date
        return model

    return {
        "slug": slug,
        "label": LABEL_DEFAULTS.get(slug, slug.title()),
        "due_date": cycle_due_date,
        "recurrence": "",
        "split_type": "fixed" if slug == "rent" else "equal",
        "notes": "",
        "total_amount": "",
        "status": "pending",
    }


def infer_cycle_from_date(slug: str, created_at: str) -> Tuple[str, str, str]:
    dt = parse_datetime_or_date(created_at)
    month = MONTHS[dt.month - 1]
    year = str(dt.year)
    return f"{slug}-{month}-{year}", month, year


def match_bill_type_for_bill_account_payment(row: Dict[str, str], bill_types: Dict[str, Dict[str, str]]) -> Optional[str]:
    description = (row.get("description") or "").strip().lower()
    message = (row.get("message") or "").strip().lower()
    raw_text = (row.get("raw_text") or "").strip().lower()
    haystack = " ".join(part for part in [description, message, raw_text] if part)

    for slug, bill_type in bill_types.items():
        provider = (bill_type.get("provider") or "").strip().lower()
        label = (bill_type.get("label") or "").strip().lower()
        if provider and provider in haystack:
            return slug
        if label and label in haystack:
            return slug
    return None


def compute_bill_statuses() -> List[Dict]:
    bills = read_bills()
    housemates = read_housemates()
    transactions = read_csv(DATA_DIR / "transactions_spending.csv")
    overrides = build_override_lookup()
    today = date.today()

    beem_transactions = [row for row in transactions if is_incoming_beem(row)]
    bill_payloads: List[Dict] = []

    for bill in bills:
        due_date = bill["due_date"]
        due = parse_date(due_date)
        total_amount = total_due_for_bill(bill, housemates)
        cycle_tag, month, year = cycle_tag_for(bill["slug"], due_date)
        housemate_rows = []
        total_collected = 0.0

        for housemate in housemates:
            name = (housemate.get("name") or "").lower()
            share = share_for_housemate(bill, housemate, total_amount)
            paid = False
            source = None

            for txn in beem_transactions:
                tags = tag_set(txn.get("tags", ""))
                expanded_cycle_tags = expand_bill_cycle_tags(tags)
                if name in tags and cycle_tag in expanded_cycle_tags:
                    paid = True
                    source = "tag"
                    break

            if not paid:
                override = overrides.get((name, bill["slug"].lower(), month, year))
                if override is not None:
                    paid = parse_bool(override.get("paid"))
                    source = "manual" if paid else None

            if paid and share is not None:
                total_collected += share

            housemate_rows.append(
                {
                    "name": name,
                    "share": share,
                    "paid": paid,
                    "source": source,
                }
            )

        outstanding = None if total_amount is None else round(max(total_amount - total_collected, 0.0), 2)
        derived_status = bill.get("status", "pending")
        paid_count = sum(1 for entry in housemate_rows if entry["paid"])
        if paid_count == len(housemate_rows) and housemate_rows:
            derived_status = "paid"
        elif paid_count > 0:
            derived_status = "partial"
        else:
            derived_status = "pending"

        if due <= today + timedelta(days=60) or derived_status != "paid":
            bill_payloads.append(
                {
                    "id": int(bill["id"]),
                    "slug": bill["slug"],
                    "label": bill["label"],
                    "total_amount": total_amount,
                    "due_date": due_date,
                    "recurrence": bill["recurrence"],
                    "split_type": bill["split_type"],
                    "notes": bill.get("notes", ""),
                    "status": derived_status,
                    "cycle_tag": cycle_tag,
                    "housemates": housemate_rows,
                    "total_collected": round(total_collected, 2),
                    "outstanding": outstanding,
                }
            )

    bill_payloads.sort(key=lambda entry: entry["due_date"])
    return bill_payloads


def compute_bill_history() -> List[Dict]:
    spending_rows = read_csv(DATA_DIR / "transactions_spending.csv")
    status = get_status()
    bill_accounts = bill_account_ids(status)
    bill_account_rows = [
        row for row in read_all_up_transactions()
        if (row.get("account_id") or "") in bill_accounts
    ]
    housemates = read_housemates()
    bill_types = read_bill_types()
    history: Dict[str, Dict] = {}

    def ensure_entry(cycle_tag: str, slug: str, month: str, year: str, latest_activity: str, description: str = "") -> Dict:
        entry = history.setdefault(
            cycle_tag,
            {
                "cycle_id": cycle_tag,
                "cycle_tag": cycle_tag,
                "slug": slug,
                "label": bill_types.get(slug, {}).get("label") or LABEL_DEFAULTS.get(slug, slug.title()),
                "month": month,
                "year": int(year),
                "housemates_paid": set(),
                "forwarded_total": 0.0,
                "matched_transactions": 0,
                "latest_activity": latest_activity,
                "descriptions": set(),
                "seeded_from_bill_payment": False,
                "bill_payment_amount": None,
                "paid_date": None,
            },
        )
        if latest_activity and latest_activity > entry["latest_activity"]:
            entry["latest_activity"] = latest_activity
        if description:
            entry["descriptions"].add(description)
        return entry

    for row in bill_account_rows:
        amount = parse_float(row.get("amount")) or 0.0
        if amount >= 0:
            continue
        tags = tag_set(row.get("tags", ""))
        created_at = row.get("settled_at") or row.get("created_at") or ""
        description = row.get("description", "") or ""

        cycle_tags = sorted(expand_bill_cycle_tags(tags))
        if cycle_tags:
            inferred_cycles = cycle_tags
        else:
            matched_slug = match_bill_type_for_bill_account_payment(row, bill_types)
            if not matched_slug or not created_at:
                continue
            inferred_cycle, month, year = infer_cycle_from_date(matched_slug, created_at)
            cycle_tags = [inferred_cycle]
            inferred_cycles = cycle_tags

        for cycle_tag in inferred_cycles:
            parsed = parse_cycle_tag(cycle_tag)
            if not parsed:
                continue
            slug, month, year = parsed
            entry = ensure_entry(cycle_tag, slug, month, year, created_at, description)
            entry["matched_transactions"] += 1
            entry["seeded_from_bill_payment"] = True
            entry["bill_payment_amount"] = round(abs(amount), 2)
            if not entry["paid_date"] or created_at < entry["paid_date"]:
                entry["paid_date"] = created_at

    for row in spending_rows:
        tags = tag_set(row.get("tags", ""))
        cycle_tags = sorted(expand_bill_cycle_tags(tags))
        if not cycle_tags:
            continue

        amount = parse_float(row.get("amount")) or 0.0
        transfer_account_id = row.get("transfer_account_id", "")
        created_at = row.get("settled_at") or row.get("created_at") or ""
        description = row.get("description", "") or ""

        for cycle_tag in cycle_tags:
            slug, month, year = parse_cycle_tag(cycle_tag)  # type: ignore[misc]
            entry = ensure_entry(cycle_tag, slug, month, year, created_at, description)
            entry["matched_transactions"] += 1

            if is_incoming_beem(row):
                paid_names = tags.intersection(HOUSEMATE_NAMES)
                entry["housemates_paid"].update(paid_names)

            if transfer_account_id and transfer_account_id in bill_account_ids and amount < 0:
                entry["forwarded_total"] += abs(amount)

    overrides = build_override_lookup()
    payload = []
    cycle_csv_rows: List[Dict[str, str]] = []
    for entry in history.values():
        bill_model = cycle_bill_model(entry["slug"], entry["month"], str(entry["year"]))
        total_due = total_due_for_bill(bill_model, housemates)
        if entry.get("seeded_from_bill_payment") and entry.get("bill_payment_amount") is not None:
            # Always trust the actual payment amount over the current config
            total_due = float(entry["bill_payment_amount"])

        # Merge manual overrides into housemates_paid
        for housemate in housemates:
            name = (housemate.get("name") or "").lower()
            if name not in entry["housemates_paid"]:
                override = overrides.get((name, entry["slug"].lower(), entry["month"], str(entry["year"])))
                if override and parse_bool(override.get("paid")):
                    entry["housemates_paid"].add(name)

        collected_amount = 0.0
        for housemate in housemates:
            name = (housemate.get("name") or "").lower()
            if name in entry["housemates_paid"]:
                share = share_for_housemate(bill_model, housemate, total_due)
                if share is not None:
                    collected_amount += share

        if entry.get("seeded_from_bill_payment"):
            # Outbound bills-account payment to provider confirms bill was paid, no tagging needed
            status_value = "paid"
        elif entry["housemates_paid"] and len(entry["housemates_paid"]) == len(housemates):
            status_value = "paid"
        elif entry["housemates_paid"]:
            status_value = "partial"
        else:
            status_value = "pending"
        provider = bill_types.get(entry["slug"], {}).get("provider", "")

        payload.append(
            {
                "cycle_id": entry["cycle_id"],
                "cycle_tag": entry["cycle_tag"],
                "slug": entry["slug"],
                "label": bill_model.get("label") or entry["label"],
                "provider": provider,
                "month": entry["month"],
                "year": entry["year"],
                "housemates_paid": sorted(entry["housemates_paid"]),
                "housemates_paid_count": len(entry["housemates_paid"]),
                "incoming_total": round(collected_amount, 2),
                "forwarded_total": round(entry["forwarded_total"], 2),
                "matched_transactions": entry["matched_transactions"],
                "latest_activity": entry["latest_activity"],
                "paid_date": entry.get("paid_date"),
                "descriptions": sorted(entry["descriptions"]),
                "total_due": total_due,
                "status": status_value,
            }
        )
        cycle_csv_rows.append(
            {
                "cycle_id": entry["cycle_id"],
                "slug": entry["slug"],
                "label": bill_model.get("label") or entry["label"],
                "provider": provider,
                "month": entry["month"],
                "year": str(entry["year"]),
                "total_due": "" if total_due is None else f"{total_due:.2f}",
                "collected_amount": f"{collected_amount:.2f}",
                "forwarded_amount": f"{entry['forwarded_total']:.2f}",
                "paid_housemates": ",".join(sorted(entry["housemates_paid"])),
                "paid_count": str(len(entry["housemates_paid"])),
                "status": status_value,
                "latest_activity": entry["latest_activity"],
            }
        )

    payload.sort(
        key=lambda item: (
            item["year"],
            MONTHS.index(item["month"]),
            item["slug"],
        ),
        reverse=True,
    )
    cycle_csv_rows.sort(
        key=lambda item: (
            item["year"],
            MONTHS.index(item["month"]),
            item["slug"],
        ),
        reverse=True,
    )
    write_bill_cycles(cycle_csv_rows)
    return payload


def append_bill(payload: Dict) -> Dict:
    bills_path = DATA_DIR / "bills.csv"
    bills = read_bills()
    next_id = max((int(row["id"]) for row in bills), default=0) + 1
    row = {
        "id": str(next_id),
        "slug": payload["slug"],
        "label": payload["label"],
        "total_amount": "" if payload.get("total_amount") in (None, "") else f"{float(payload['total_amount']):.2f}",
        "due_date": payload["due_date"],
        "recurrence": payload["recurrence"],
        "split_type": payload["split_type"],
        "notes": payload.get("notes", ""),
        "status": "pending",
    }
    bills.append(row)
    write_csv(
        bills_path,
        ["id", "slug", "label", "total_amount", "due_date", "recurrence", "split_type", "notes", "status"],
        bills,
    )
    row["id"] = next_id
    row["total_amount"] = parse_float(row["total_amount"])
    return row


def upsert_override(bill_id: int, payload: Dict) -> Dict:
    bills = {int(row["id"]): row for row in read_bills()}
    if bill_id not in bills:
        raise KeyError(f"Bill {bill_id} not found")

    bill = bills[bill_id]
    cycle_tag, month, year = cycle_tag_for(bill["slug"], bill["due_date"])
    _ = cycle_tag
    housemate = (payload.get("housemate") or "").lower().strip()
    if housemate not in HOUSEMATE_NAMES:
        raise ValueError("Unknown housemate")

    paid = bool(payload.get("paid"))
    note = payload.get("note", "")
    overrides = read_manual_overrides()
    fieldnames = ["housemate", "slug", "month", "year", "paid", "note"]

    updated = False
    for row in overrides:
        if (
            row.get("housemate", "").lower() == housemate
            and row.get("slug", "").lower() == bill["slug"].lower()
            and row.get("month", "").lower() == month
            and str(row.get("year", "")) == year
        ):
            row["paid"] = "true" if paid else "false"
            row["note"] = note
            updated = True
            break

    if not updated:
        overrides.append(
            {
                "housemate": housemate,
                "slug": bill["slug"],
                "month": month,
                "year": year,
                "paid": "true" if paid else "false",
                "note": note,
            }
        )

    write_csv(DATA_DIR / "manual_overrides.csv", fieldnames, overrides)
    return {
        "housemate": housemate,
        "slug": bill["slug"],
        "month": month,
        "year": year,
        "paid": paid,
        "note": note,
    }


def parse_datetime_or_date(value: str) -> datetime:
    parsed = parser.isoparse(value)
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone().replace(tzinfo=None)


def filter_spending_rows(rows: List[Dict[str, str]], since: Optional[str], until: Optional[str], category: Optional[str]) -> List[Dict]:
    status = get_status()
    internal_ids = owned_up_account_ids(status)

    since_dt = parser.isoparse(since) if since else None
    until_dt = parser.isoparse(until) if until else None
    if until_dt and until_dt.hour == 0 and until_dt.minute == 0 and until_dt.second == 0:
        until_dt = until_dt + timedelta(days=1)

    filtered = []
    for row in rows:
        amount = parse_float(row.get("amount")) or 0.0
        transfer_account_id = row.get("transfer_account_id", "")

        # Skip all internal transfers (to/from savings, grow, 2up)
        if transfer_account_id in internal_ids:
            continue

        created_at = row.get("settled_at") or row.get("created_at")
        if not created_at:
            continue
        created_dt = parse_datetime_or_date(created_at)

        if since_dt and created_dt < since_dt.replace(tzinfo=None):
            continue
        if until_dt and created_dt >= until_dt.replace(tzinfo=None):
            continue
        if category and (row.get("category") or "").lower() != category.lower():
            continue

        filtered.append(
            {
                **row,
                "amount": round(amount, 2),
            }
        )

    filtered.sort(key=lambda item: item.get("settled_at") or item.get("created_at") or "", reverse=True)
    return filtered


def group_spending_by_period(rows: List[Dict], group_by: str) -> List[Dict]:
    buckets: Dict[str, float] = {}
    counts: Dict[str, int] = {}

    for row in rows:
        amount = float(row.get("amount", 0))
        if amount >= 0:
            continue
        dt_str = row.get("settled_at") or row.get("created_at") or ""
        if not dt_str:
            continue
        dt = parse_datetime_or_date(dt_str)
        if group_by == "week":
            period = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
        else:
            period = f"{dt.year}-{dt.month:02d}"
        buckets[period] = buckets.get(period, 0.0) + abs(amount)
        counts[period] = counts.get(period, 0) + 1

    return [
        {"period": period, "total_spend": round(buckets[period], 2), "transaction_count": counts[period]}
        for period in sorted(buckets.keys())
    ]


RECURRING_TRANSACTION_TYPES = {"Direct Debit", "Scheduled Transfer"}


def detect_recurring(rows: List[Dict[str, str]], exclusions: Optional[set] = None) -> List[Dict]:
    from statistics import median, stdev

    exclusions = exclusions or set()
    today = datetime.now().date()

    # Group transactions by description, tagging whether they are typed as recurring
    merchant_txns: Dict[str, List[Dict]] = {}
    for row in rows:
        amount = parse_float(row.get("amount")) or 0.0
        if amount >= 0:
            continue
        desc = (row.get("description") or "").strip()
        if not desc or desc in exclusions:
            continue
        transfer_id = row.get("transfer_account_id", "")
        if transfer_id:
            continue
        dt_str = row.get("settled_at") or row.get("created_at") or ""
        if not dt_str:
            continue
        txn_type = (row.get("transaction_type") or "").strip()
        merchant_txns.setdefault(desc, []).append({
            "amount": abs(amount),
            "date": parse_datetime_or_date(dt_str),
            "typed_recurring": txn_type in RECURRING_TRANSACTION_TYPES,
        })

    recurring = []
    for desc, txns in merchant_txns.items():
        if len(txns) < 2:
            continue
        txns_sorted = sorted(txns, key=lambda t: t["date"])
        amounts = [t["amount"] for t in txns_sorted]
        dates = [t["date"] for t in txns_sorted]
        intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        med_interval = median(intervals)
        med_amount = median(amounts)
        if med_amount <= 0:
            continue

        # Primary signal: any transaction has a Direct Debit / Scheduled Transfer type
        typed = any(t["typed_recurring"] for t in txns)

        if typed:
            # Accept if interval looks roughly monthly (14–45 days) or annual (330–400)
            if not (14 <= med_interval <= 45 or 330 <= med_interval <= 400):
                continue
        else:
            # Fallback: strict statistical test (original behaviour)
            if not (20 <= med_interval <= 40):
                continue
            cv = (stdev(amounts) / med_amount) if len(amounts) > 1 else 0.0
            if cv > 0.15:
                continue

        monthly_cost = round(med_amount * (30.0 / med_interval), 2)
        last_date = dates[-1].date() if hasattr(dates[-1], "date") else dates[-1]
        next_date = last_date + timedelta(days=int(med_interval))

        # Skip entries where next expected date is more than one full interval in the past
        # (pattern likely stopped)
        if next_date < today - timedelta(days=int(med_interval)):
            continue

        recurring.append({
            "description": desc,
            "monthly_cost": monthly_cost,
            "median_amount": round(med_amount, 2),
            "interval_days": round(med_interval, 1),
            "occurrences": len(txns),
            "last_date": last_date.strftime("%Y-%m-%d"),
            "next_expected": next_date.strftime("%Y-%m-%d"),
        })

    return sorted(recurring, key=lambda r: r["monthly_cost"], reverse=True)


FRIVOLITY_WEIGHTS: Dict[str, float] = {
    "takeaway": 0.90,
    "restaurants-and-cafes": 0.75,
    "booze": 0.85,
    "pubs-and-bars": 0.85,
    "events-and-gigs": 0.80,
    "holidays-and-travel": 0.70,
    "hobbies": 0.70,
    "games-and-software": 0.80,
    "tv-and-music": 0.70,
    "lottery-and-gambling": 0.95,
    "clothing-and-accessories": 0.50,
    "hair-and-beauty": 0.50,
    "fitness-and-wellbeing": 0.30,
    "gifts-and-charity": 0.60,
    "technology": 0.60,
    "groceries": 0.10,
    "health-and-medical": 0.05,
    "rent-and-mortgage": 0.00,
    "utilities": 0.00,
    "internet": 0.05,
    "fuel": 0.10,
    "public-transport": 0.05,
    "mobile-phone": 0.05,
}


def linear_slope(values: List[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values))
    den = sum((x - x_mean) ** 2 for x in xs)
    return round(num / den, 2) if den else 0.0


def import_networth_from_excel(super_aud: float) -> int:
    if not EXCEL_PATH.exists():
        raise FileNotFoundError(f"Excel file not found: {EXCEL_PATH}")

    wb = load_workbook(EXCEL_PATH, read_only=True, data_only=True)
    ws = wb["Historical"]

    existing = {row["date"]: row for row in read_csv(NETWORTH_CSV)}

    imported = 0
    for row in ws.iter_rows():
        vals = [cell.value for cell in row]
        if not vals or not isinstance(vals[0], dt_class):
            continue
        date_str = vals[0].strftime("%Y-%m-%d")
        everyday = float(vals[1] or 0)
        savings = float(vals[2] or 0)
        selfwealth = float(vals[3] or 0)
        ibkr = float(vals[4] or 0)
        cash = round(everyday + savings, 2)
        investments = round(selfwealth + ibkr, 2)
        total = round(cash + investments, 2)
        existing[date_str] = {
            "date": date_str,
            "cash_aud": str(cash),
            "investments_aud": str(investments),
            "super_aud": "0",
            "total_aud": str(total),
        }
        imported += 1

    wb.close()

    if existing:
        latest_date = max(existing.keys())
        row = existing[latest_date]
        row["super_aud"] = str(round(super_aud, 2))
        row["total_aud"] = str(round(
            float(row["cash_aud"]) + float(row["investments_aud"]) + super_aud, 2
        ))

    sorted_rows = sorted(existing.values(), key=lambda r: r["date"])
    write_csv(NETWORTH_CSV, NETWORTH_FIELDS, sorted_rows)
    return imported


@app.get("/")
def root():
    return redirect("/dashboard")


@app.get("/dashboard")
def dashboard_page():
    return send_file(BASE_DIR / "dashboard.html")


@app.get("/bills")
def bills_page():
    return send_file(BASE_DIR / "bills.html")


@app.get("/spending")
def spending_page():
    return send_file(BASE_DIR / "spending.html")


@app.get("/insights")
def insights_page():
    return send_file(BASE_DIR / "insights.html")


@app.get("/runway")
def runway_page():
    return send_file(BASE_DIR / "runway.html")


@app.get("/api/status")
def api_status():
    return jsonify(get_status())


@app.get("/sync")
def sync_route():
    full_refresh = request.args.get("full", "").lower() in {"1", "true", "yes"}
    try:
        counts = sync_transactions(full_refresh=full_refresh)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "counts": counts})


@app.get("/api/bills")
def api_bills():
    return jsonify(compute_bill_statuses())


@app.get("/api/bills/history")
def api_bills_history():
    return jsonify(compute_bill_history())


@app.get("/api/bills/cycle/<cycle_tag>")
def api_bill_cycle_detail(cycle_tag: str):
    history = compute_bill_history()
    cycle = next((h for h in history if h["cycle_tag"] == cycle_tag), None)
    if not cycle:
        return jsonify({"error": "Cycle not found"}), 404

    parsed = parse_cycle_tag(cycle_tag)
    if not parsed:
        return jsonify({"error": "Invalid cycle tag"}), 400
    slug, month, year = parsed

    bill_model = cycle_bill_model(slug, month, str(year))
    housemates = read_housemates()
    overrides = build_override_lookup()

    spending_rows = read_csv(DATA_DIR / "transactions_spending.csv")
    beem_rows = [r for r in spending_rows if is_incoming_beem(r)]

    total_due = cycle.get("total_due")

    housemate_detail = []
    for hm in housemates:
        name = (hm.get("name") or "").lower()
        share = share_for_housemate(bill_model, hm, total_due)
        paid = False
        source = None
        paid_date = None

        for txn in beem_rows:
            tags = tag_set(txn.get("tags", ""))
            expanded = expand_bill_cycle_tags(tags)
            if name in tags and cycle_tag in expanded:
                paid = True
                source = "tag"
                paid_date = txn.get("settled_at") or txn.get("created_at")
                break

        if not paid:
            override = overrides.get((name, slug.lower(), month, str(year)))
            if override is not None:
                paid = parse_bool(override.get("paid"))
                source = "manual" if paid else None
                paid_date = override.get("paid_date") or None

        housemate_detail.append({
            "name": name,
            "share": share,
            "paid": paid,
            "source": source,
            "paid_date": paid_date,
        })

    timeline = []
    if cycle.get("paid_date"):
        timeline.append({
            "date": cycle["paid_date"],
            "event": f"Bill paid to {cycle.get('provider') or slug}",
            "type": "payment_out",
        })
    for hm in housemate_detail:
        if hm["paid"] and hm["paid_date"]:
            share_str = f"${hm['share']:.2f}" if hm["share"] else "share"
            timeline.append({
                "date": hm["paid_date"],
                "event": f"{hm['name'].title()} paid {share_str}",
                "type": "housemate_paid",
            })
    timeline.sort(key=lambda e: e["date"] or "")

    config = load_config()
    notes = config.get(f"bill_notes_{cycle_tag}", "")

    return jsonify({
        "cycle_tag": cycle_tag,
        "slug": slug,
        "month": month,
        "year": int(year),
        "label": cycle["label"],
        "provider": cycle.get("provider", ""),
        "status": cycle["status"],
        "paid_date": cycle.get("paid_date"),
        "total_due": total_due,
        "incoming_total": cycle.get("incoming_total", 0),
        "housemates": housemate_detail,
        "timeline": timeline,
        "notes": notes,
    })


@app.post("/api/bills/cycle/<cycle_tag>/override")
def api_bill_cycle_override(cycle_tag: str):
    parsed = parse_cycle_tag(cycle_tag)
    if not parsed:
        return jsonify({"ok": False, "error": "Invalid cycle tag"}), 400
    slug, month, year = parsed

    payload = request.get_json(force=True) or {}
    housemate = (payload.get("housemate") or "").lower().strip()
    if housemate not in HOUSEMATE_NAMES:
        return jsonify({"ok": False, "error": "Unknown housemate"}), 400

    paid = bool(payload.get("paid"))
    note = payload.get("note", "")
    paid_date = payload.get("paid_date", "")

    overrides = read_manual_overrides()
    fieldnames = ["housemate", "slug", "month", "year", "paid", "note", "paid_date"]

    updated = False
    for row in overrides:
        if (
            row.get("housemate", "").lower() == housemate
            and row.get("slug", "").lower() == slug.lower()
            and row.get("month", "").lower() == month
            and str(row.get("year", "")) == str(year)
        ):
            row["paid"] = "true" if paid else "false"
            row["note"] = note
            row["paid_date"] = paid_date
            updated = True
            break

    if not updated:
        overrides.append({
            "housemate": housemate,
            "slug": slug,
            "month": month,
            "year": str(year),
            "paid": "true" if paid else "false",
            "note": note,
            "paid_date": paid_date,
        })

    write_csv(DATA_DIR / "manual_overrides.csv", fieldnames, overrides)
    return jsonify({"ok": True, "housemate": housemate, "paid": paid})


@app.post("/api/bills/cycle/<cycle_tag>/notes")
def api_bill_cycle_notes(cycle_tag: str):
    parsed = parse_cycle_tag(cycle_tag)
    if not parsed:
        return jsonify({"ok": False, "error": "Invalid cycle tag"}), 400

    payload = request.get_json(force=True) or {}
    notes = (payload.get("notes") or "").strip()

    config = load_config()
    config[f"bill_notes_{cycle_tag}"] = notes
    CONFIG_PATH.write_text(json.dumps(config, indent=2))
    return jsonify({"ok": True, "notes": notes})


@app.post("/api/bills")
def api_add_bill():
    payload = request.get_json(force=True) or {}
    required = ["slug", "label", "due_date", "recurrence", "split_type"]
    missing = [field for field in required if not payload.get(field)]
    if missing:
        return jsonify({"ok": False, "error": f"Missing fields: {', '.join(missing)}"}), 400
    if payload["slug"] not in BILL_SLUGS:
        return jsonify({"ok": False, "error": "Invalid bill slug"}), 400
    row = append_bill(payload)
    return jsonify(row), 201


@app.post("/api/bills/<int:bill_id>/override")
def api_override_bill(bill_id: int):
    payload = request.get_json(force=True) or {}
    try:
        row = upsert_override(bill_id, payload)
    except KeyError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "override": row})


@app.get("/api/spending")
def api_spending():
    since = request.args.get("since")
    until = request.args.get("until")
    category = request.args.get("category")
    rows = read_csv(DATA_DIR / "transactions_spending.csv")
    return jsonify(filter_spending_rows(rows, since, until, category))


def _cashflow_monthly():
    months_back = 12
    today = datetime.now()
    month_ranges = []
    d = today.replace(day=1)
    for _ in range(months_back):
        d = (d - timedelta(days=1)).replace(day=1)
        next_d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_ranges.append((d, next_d, f"{d.year}-{d.month:02d}"))
    month_ranges.reverse()

    result = []
    for start, end, label in month_ranges:
        stats = period_financials(start, end)
        invested = stats["investment_transfers"]
        save_rate = round(invested / stats["income"] * 100, 1) if stats["income"] > 0 else 0.0
        result.append({
            "month": label,
            "income": stats["income"],
            "saved": invested,
            "invested": invested,
            "discretionary": stats["ordinary_spend"],
            "ordinary_spend": stats["ordinary_spend"],
            "one_off_spend": stats["one_off_spend"],
            "essential_spend": stats["essential_spend"],
            "lifestyle_spend": stats["lifestyle_spend"],
            "total_spend": stats["total_spend"],
            "reimbursements": stats["reimbursements"],
            "savings_rate": save_rate,
        })
    return jsonify(result)


@app.get("/api/spending/cashflow")
def api_spending_cashflow():
    if request.args.get("monthly", "").lower() in {"1", "true", "yes"}:
        return _cashflow_monthly()

    since = request.args.get("since")
    until = request.args.get("until")
    start = parser.isoparse(since).replace(tzinfo=None) if since else datetime(2020, 1, 1)
    end = parser.isoparse(until).replace(tzinfo=None) if until else datetime.now() + timedelta(days=1)
    if until and end.hour == 0 and end.minute == 0 and end.second == 0:
        end += timedelta(days=1)

    stats = period_financials(start, end)
    status = get_status()
    account_ids = status.get("account_ids", {})
    transfer_totals = {
        "savings_transfers": 0.0,
        "grow_transfers": 0.0,
        "two_up_transfers": 0.0,
        "essentials_transfers": 0.0,
        "other_internal_transfers": 0.0,
    }
    named_destinations = {
        account_ids.get("savings", ""): "savings_transfers",
        account_ids.get("grow", ""): "grow_transfers",
        account_ids.get("two_up", ""): "two_up_transfers",
        account_ids.get("essentials", ""): "essentials_transfers",
    }
    all_internal = owned_up_account_ids(status)
    for row in read_csv(DATA_DIR / "transactions_spending.csv"):
        dt_str = row.get("settled_at") or row.get("created_at") or ""
        if not dt_str:
            continue
        try:
            dt = parse_datetime_or_date(dt_str)
        except Exception:
            continue
        if not (start <= dt < end):
            continue
        amount = parse_float(row.get("amount")) or 0.0
        if amount >= 0:
            continue
        transfer_id = row.get("transfer_account_id", "")
        if transfer_id not in all_internal:
            continue
        key = named_destinations.get(transfer_id, "other_internal_transfers")
        transfer_totals[key] += abs(amount)

    net = (
        stats["income"]
        + stats["reimbursements"]
        + stats["shared_settlements"]
        - stats["gross_cash_spend"]
        - stats["investment_transfers"]
    )
    payload = {
        **{key: round(value, 2) for key, value in transfer_totals.items()},
        "income": stats["income"],
        "reimbursements": stats["reimbursements"],
        "shared_settlements": stats["shared_settlements"],
        "investment_transfers": stats["investment_transfers"],
        "insurance_payments": 0.0,
        "tax_payments": 0.0,
        "discretionary": stats["ordinary_spend"],
        "ordinary_spend": stats["ordinary_spend"],
        "one_off_spend": stats["one_off_spend"],
        "essential_spend": stats["essential_spend"],
        "lifestyle_spend": stats["lifestyle_spend"],
        "total_spend": stats["total_spend"],
        "gross_cash_spend": stats["gross_cash_spend"],
        "shared_gross_outflows": stats["shared_gross_outflows"],
        "shared_personal_spend": stats["shared_personal_spend"],
        "shared_recoverable_created": stats["shared_recoverable_created"],
        "shared_unallocated_gross": stats["shared_unallocated_gross"],
        "shared_paid_by_others": stats["shared_paid_by_others"],
        "internal_transfers_excluded": stats["internal_transfers"],
        "net": round(net, 2),
    }
    return jsonify(payload)


def _default_income_stop_date() -> str:
    try:
        config = load_config()
    except Exception:
        config = {}
    configured = (config.get("income_stop_date") or "").strip()
    if configured:
        return configured
    today = date.today()
    first_this_month = today.replace(day=1)
    previous_month_end = first_this_month - timedelta(days=1)
    return previous_month_end.replace(day=1).isoformat()


def _networth_snapshot_summary(since_date: date) -> Dict:
    rows = []
    for row in read_csv(NETWORTH_CSV):
        try:
            row_date = date.fromisoformat(row.get("date") or "")
        except Exception:
            continue
        rows.append((row_date, row))
    rows.sort(key=lambda item: item[0])
    if not rows:
        return {}

    latest_date, latest = rows[-1]
    eligible = [item for item in rows if item[0] <= since_date]
    start_date, start = eligible[-1] if eligible else rows[0]

    def num(row: Dict[str, str], key: str) -> float:
        return float(row.get(key) or 0.0)

    latest_values = {
        "date": latest_date.isoformat(),
        "cash": num(latest, "cash_aud"),
        "investments": num(latest, "investments_aud"),
        "super": num(latest, "super_aud"),
        "total": num(latest, "total_aud"),
    }
    start_values = {
        "date": start_date.isoformat(),
        "cash": num(start, "cash_aud"),
        "investments": num(start, "investments_aud"),
        "super": num(start, "super_aud"),
        "total": num(start, "total_aud"),
    }
    changes = {
        key: round(latest_values[key] - start_values[key], 2)
        for key in ("cash", "investments", "super", "total")
    }
    return {"start": start_values, "latest": latest_values, "change": changes}


@app.get("/api/runway")
def api_runway():
    since_raw = (request.args.get("since") or _default_income_stop_date()).strip()
    try:
        since_date = date.fromisoformat(since_raw)
    except ValueError:
        return jsonify({"error": "invalid since date, use YYYY-MM-DD"}), 400

    today = date.today()
    if since_date > today:
        return jsonify({"error": "since date cannot be in the future"}), 400

    start = datetime.combine(since_date, datetime.min.time())
    end = datetime.combine(today + timedelta(days=1), datetime.min.time())
    days = max((today - since_date).days + 1, 1)
    monthly_factor = 30.4375 / days

    stats = period_financials(start, end)
    shared_state = shared_summary(load_allocations(DATA_DIR), load_settlements(DATA_DIR))
    baseline_days = 90
    baseline_start = start - timedelta(days=baseline_days)
    baseline_stats = period_financials(baseline_start, start)
    baseline_factor = 30.4375 / baseline_days

    ordinary_monthly = round(stats["net_ordinary_spend"] * monthly_factor, 2)
    essential_net = max(stats["essential_spend"] - stats["reimbursements"], 0.0)
    essential_monthly = round(essential_net * monthly_factor, 2)
    lifestyle_monthly = round(stats["lifestyle_spend"] * monthly_factor, 2)
    one_off_monthly_equivalent = round(stats["one_off_spend"] * monthly_factor, 2)

    nw = _networth_snapshot_summary(since_date)
    current_cash = float(nw.get("latest", {}).get("cash") or 0.0)
    runway_months = round(current_cash / ordinary_monthly, 1) if ordinary_monthly > 0 else None
    lean_runway_months = round(current_cash / essential_monthly, 1) if essential_monthly > 0 else None

    current_categories = stats["categories"]
    baseline_categories = baseline_stats["categories"]
    lifestyle_slugs = {
        slug
        for slug, values in {**baseline_categories, **current_categories}.items()
        if (
            current_categories.get(slug, {}).get("treatment")
            or baseline_categories.get(slug, {}).get("treatment")
        ) == "lifestyle"
    }
    lifestyle_drift = []
    for slug in lifestyle_slugs:
        current_rate = current_categories.get(slug, {}).get("total", 0.0) * monthly_factor
        baseline_rate = baseline_categories.get(slug, {}).get("total", 0.0) * baseline_factor
        delta = current_rate - baseline_rate
        pct = round(delta / baseline_rate * 100, 1) if baseline_rate > 0 else None
        lifestyle_drift.append({
            "slug": slug,
            "current_monthly": round(current_rate, 2),
            "baseline_monthly": round(baseline_rate, 2),
            "delta_monthly": round(delta, 2),
            "delta_pct": pct,
        })
    lifestyle_drift.sort(key=lambda item: abs(item["delta_monthly"]), reverse=True)

    one_offs = sorted(
        [
            {"slug": slug, "total": round(values["total"], 2)}
            for slug, values in current_categories.items()
            if values.get("treatment") == "one_off"
        ],
        key=lambda item: item["total"],
        reverse=True,
    )

    one_off_merchants = sorted(
        [
            {
                "description": name,
                "total": round(values["total"], 2),
                "count": values["count"],
                "category": values.get("category", ""),
            }
            for name, values in stats["merchants"].items()
            if values.get("treatment") == "one_off"
        ],
        key=lambda item: item["total"],
        reverse=True,
    )[:12]

    lifestyle_merchants = sorted(
        [
            {
                "description": name,
                "total": round(values["total"], 2),
                "count": values["count"],
                "category": values.get("category", ""),
            }
            for name, values in stats["merchants"].items()
            if values.get("treatment") == "lifestyle"
        ],
        key=lambda item: item["total"],
        reverse=True,
    )[:12]

    investment_movement_estimate = None
    if nw:
        investment_movement_estimate = round(
            nw["change"]["investments"] - stats["investment_transfers"], 2
        )

    status = get_status()
    visible_accounts = [
        account.get("display_name") or account.get("id")
        for account in status.get("up_accounts", [])
    ]

    return jsonify({
        "since": since_date.isoformat(),
        "through": today.isoformat(),
        "days": days,
        "networth": nw,
        "cashflow": {
            "income": stats["income"],
            "reimbursements": stats["reimbursements"],
            "shared_settlements": stats["shared_settlements"],
            "total_spend": stats["total_spend"],
            "gross_cash_spend": stats["gross_cash_spend"],
            "shared_gross_outflows": stats["shared_gross_outflows"],
            "shared_personal_spend": stats["shared_personal_spend"],
            "shared_recoverable_created": stats["shared_recoverable_created"],
            "shared_paid_by_others": stats["shared_paid_by_others"],
            "ordinary_spend": stats["ordinary_spend"],
            "net_ordinary_spend": stats["net_ordinary_spend"],
            "essential_spend": stats["essential_spend"],
            "lifestyle_spend": stats["lifestyle_spend"],
            "one_off_spend": stats["one_off_spend"],
            "investment_transfers": stats["investment_transfers"],
            "internal_transfers_excluded": stats["internal_transfers"],
            "internal_transfer_count": stats["internal_transfer_count"],
        },
        "monthly": {
            "ordinary_burn": ordinary_monthly,
            "essential_burn": essential_monthly,
            "lifestyle_spend": lifestyle_monthly,
            "one_off_equivalent": one_off_monthly_equivalent,
            "baseline_lifestyle": round(baseline_stats["lifestyle_spend"] * baseline_factor, 2),
            "baseline_ordinary": round(baseline_stats["net_ordinary_spend"] * baseline_factor, 2),
        },
        "runway": {
            "cash": round(current_cash, 2),
            "months": runway_months,
            "lean_months": lean_runway_months,
        },
        "shared": {
            "ebony_owes_angus": shared_state["ebony_owes_angus"],
            "angus_owes_ebony": shared_state["angus_owes_ebony"],
            "other_owes_angus": shared_state["other_owes_angus"],
            "outstanding_receivables": round(
                shared_state["ebony_owes_angus"] + shared_state["other_owes_angus"], 2
            ),
            "review_count": shared_state["review_count"],
        },
        "lifestyle_drift": lifestyle_drift,
        "one_offs": one_offs,
        "one_off_merchants": one_off_merchants,
        "lifestyle_merchants": lifestyle_merchants,
        "investment_movement_estimate": investment_movement_estimate,
        "data_quality": {
            "owned_accounts_detected": len(visible_accounts),
            "owned_account_names": visible_accounts,
            "unified_transactions_present": (DATA_DIR / "transactions_all.csv").exists(),
            "baseline_days": baseline_days,
            "networth_start_snapshot": nw.get("start", {}).get("date") if nw else None,
            "networth_latest_snapshot": nw.get("latest", {}).get("date") if nw else None,
        },
    })


@app.post("/api/runway/settings")
def api_runway_settings():
    payload = request.get_json(force=True) or {}
    income_stop_date = (payload.get("income_stop_date") or "").strip()
    try:
        parsed = date.fromisoformat(income_stop_date)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid date, use YYYY-MM-DD"}), 400
    if parsed > date.today():
        return jsonify({"ok": False, "error": "date cannot be in the future"}), 400

    config = load_config()
    config["income_stop_date"] = parsed.isoformat()
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
        handle.write("\n")
    return jsonify({"ok": True, "income_stop_date": parsed.isoformat()})


@app.get("/api/shared/summary")
def api_shared_summary():
    allocations = load_allocations(DATA_DIR)
    settlements = load_settlements(DATA_DIR)
    summary = shared_summary(allocations, settlements)
    summary["allocations"] = allocations[:200]
    summary["settlements"] = settlements[:200]
    return jsonify(summary)


@app.post("/api/shared/sync")
def api_shared_sync():
    transactions = read_all_up_transactions()
    allocations = load_allocations(DATA_DIR)
    merged, stats = sync_up_allocations(transactions, allocations)
    save_allocations(DATA_DIR, merged)
    return jsonify({"ok": True, **stats})


@app.post("/api/shared/allocation")
def api_shared_allocation():
    payload = request.get_json(force=True) or {}
    allocation_id = (payload.get("allocation_id") or "").strip()
    source_transaction_id = (payload.get("source_transaction_id") or "").strip()

    allocations = load_allocations(DATA_DIR)
    existing = None
    if allocation_id:
        existing = next(
            (row for row in allocations if row.get("allocation_id") == allocation_id),
            None,
        )
    if existing is None and source_transaction_id:
        existing = next(
            (row for row in allocations if row.get("source_transaction_id") == source_transaction_id),
            None,
        )

    transaction = None
    if source_transaction_id:
        transaction = next(
            (row for row in read_all_up_transactions() if row.get("id") == source_transaction_id),
            None,
        )

    if existing is None and transaction is None:
        return jsonify({
            "ok": False,
            "error": "allocation_id or a valid source_transaction_id is required",
        }), 400

    source = (existing or {}).get("source") or "up"
    source_transaction_id = (
        source_transaction_id
        or (existing or {}).get("source_transaction_id")
        or ""
    )
    payer = (payload.get("payer") or (existing or {}).get("payer") or "Angus").strip()
    gross = (
        parse_float((existing or {}).get("gross_amount"))
        if existing is not None
        else abs(parse_float((transaction or {}).get("amount")) or 0.0)
    ) or 0.0
    if gross <= 0:
        return jsonify({"ok": False, "error": "allocation requires a positive gross amount"}), 400

    allocation_type = (payload.get("allocation_type") or (existing or {}).get("allocation_type") or "joint").strip().lower()
    description = (
        payload.get("description")
        or (existing or {}).get("description")
        or (transaction or {}).get("description")
        or ""
    ).strip()
    category = (
        payload.get("category")
        or (existing or {}).get("category")
        or (transaction or {}).get("category")
        or "uncategorised"
    ).strip()
    event_key = (payload.get("event_key") or (existing or {}).get("event_key") or "").strip()
    date_value = (
        payload.get("date")
        or (existing or {}).get("date")
        or (transaction or {}).get("settled_at")
        or (transaction or {}).get("created_at")
        or ""
    )[:10]
    notes = (payload.get("notes") or (existing or {}).get("notes") or "").strip()

    if allocation_type == "group_booking":
        try:
            allocation = make_group_allocation(
                source=source,
                source_transaction_id=source_transaction_id,
                date=date_value,
                description=description,
                payer=payer,
                gross_amount=gross,
                people_count=int(payload.get("people_count") or (existing or {}).get("people_count")),
                angus_units=int(payload.get("angus_units", (existing or {}).get("angus_units") or 0)),
                ebony_units=int(payload.get("ebony_units", (existing or {}).get("ebony_units") or 0)),
                event_key=event_key,
                category=category,
                notes=notes,
            )
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        if existing and existing.get("allocation_id"):
            allocation["allocation_id"] = existing["allocation_id"]
    elif allocation_type == "personal":
        allocation = {
            "allocation_id": (existing or {}).get("allocation_id") or shared_stable_id(source, source_transaction_id),
            "source": source,
            "source_transaction_id": source_transaction_id,
            "event_key": event_key,
            "date": date_value,
            "description": description,
            "payer": payer,
            "gross_amount": f"{gross:.2f}",
            "allocation_type": "personal",
            "angus_share": f"{gross:.2f}",
            "ebony_share": "0.00",
            "other_share": "0.00",
            "people_count": "",
            "unit_price": "",
            "angus_units": "",
            "ebony_units": "",
            "other_units": "",
            "category": category,
            "status": "confirmed",
            "notes": notes,
        }
    else:
        try:
            angus_ratio = float(payload.get("angus_ratio", 0.5))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "angus_ratio must be numeric"}), 400
        if not 0 <= angus_ratio <= 1:
            return jsonify({"ok": False, "error": "angus_ratio must be between 0 and 1"}), 400
        angus_share = round(gross * angus_ratio, 2)
        ebony_share = round(gross - angus_share, 2)
        allocation = {
            "allocation_id": (existing or {}).get("allocation_id") or shared_stable_id(source, source_transaction_id),
            "source": source,
            "source_transaction_id": source_transaction_id,
            "event_key": event_key,
            "date": date_value,
            "description": description,
            "payer": payer,
            "gross_amount": f"{gross:.2f}",
            "allocation_type": "joint",
            "angus_share": f"{angus_share:.2f}",
            "ebony_share": f"{ebony_share:.2f}",
            "other_share": "0.00",
            "people_count": "",
            "unit_price": "",
            "angus_units": "",
            "ebony_units": "",
            "other_units": "",
            "category": category,
            "status": "confirmed",
            "notes": notes,
        }

    replaced = False
    for index, row in enumerate(allocations):
        if (
            row.get("allocation_id") == allocation["allocation_id"]
            or (
                source_transaction_id
                and row.get("source") == source
                and row.get("source_transaction_id") == source_transaction_id
            )
        ):
            allocations[index] = allocation
            replaced = True
            break
    if not replaced:
        allocations.append(allocation)
    allocations.sort(key=lambda row: (row.get("date", ""), row.get("description", "")), reverse=True)
    save_allocations(DATA_DIR, allocations)
    return jsonify({"ok": True, "allocation": allocation})


@app.get("/api/shared/settlement-suggestions")
def api_shared_settlement_suggestions():
    suggestions = suggest_settlement_matches(
        read_all_up_transactions(),
        load_allocations(DATA_DIR),
        load_settlements(DATA_DIR),
    )
    return jsonify({"ok": True, "suggestions": suggestions})


@app.post("/api/shared/settlement")
def api_shared_settlement():
    payload = request.get_json(force=True) or {}
    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "amount required"}), 400
    if amount <= 0:
        return jsonify({"ok": False, "error": "amount must be positive"}), 400

    settlement = {
        "settlement_id": shared_stable_id(
            "settlement",
            str(payload.get("source_transaction_id") or ""),
            str(payload.get("matched_allocation_id") or ""),
            str(payload.get("date") or ""),
            f"{amount:.2f}",
        ),
        "date": (payload.get("date") or date.today().isoformat()),
        "source": (payload.get("source") or "manual"),
        "source_transaction_id": (payload.get("source_transaction_id") or ""),
        "event_key": (payload.get("event_key") or ""),
        "from_person": (payload.get("from_person") or "Ebony"),
        "to_person": (payload.get("to_person") or "Angus"),
        "amount": f"{amount:.2f}",
        "matched_allocation_id": (payload.get("matched_allocation_id") or ""),
        "notes": (payload.get("notes") or ""),
    }

    settlements = load_settlements(DATA_DIR)
    if not any(row.get("settlement_id") == settlement["settlement_id"] for row in settlements):
        settlements.append(settlement)
        settlements.sort(key=lambda row: row.get("date", ""), reverse=True)
        save_settlements(DATA_DIR, settlements)
    return jsonify({"ok": True, "settlement": settlement})


@app.get("/api/budgets")
def api_get_budgets():
    return jsonify(get_budgets())


@app.post("/api/budgets")
def api_save_budgets():
    payload = request.get_json(force=True) or {}
    budgets = {}
    for k, v in payload.items():
        try:
            val = float(v)
            if val >= 0:
                budgets[str(k)] = val
        except (TypeError, ValueError):
            pass
    save_budgets(budgets)
    return jsonify({"ok": True, "budgets": budgets})


def get_recurring_exclusions() -> set:
    if not CONFIG_PATH.exists():
        return set()
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    return set(config.get("recurring_exclusions", []))


def save_recurring_exclusions(exclusions: set) -> None:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["recurring_exclusions"] = sorted(exclusions)
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
        handle.write("\n")


@app.get("/api/spending/recurring")
def api_spending_recurring():
    rows = read_csv(DATA_DIR / "transactions_spending.csv")
    exclusions = get_recurring_exclusions()
    return jsonify(detect_recurring(rows, exclusions))


@app.post("/api/spending/recurring/exclude")
def api_recurring_exclude():
    payload = request.get_json(force=True) or {}
    description = (payload.get("description") or "").strip()
    if not description:
        return jsonify({"ok": False, "error": "description required"}), 400
    exclusions = get_recurring_exclusions()
    exclusions.add(description)
    save_recurring_exclusions(exclusions)
    return jsonify({"ok": True, "excluded": description})


@app.get("/api/spending/category-history")
def api_spending_category_history():
    months_back = int(request.args.get("months", 6))
    rows = read_all_up_transactions()

    status = get_status()
    internal_ids = owned_up_account_ids(status)

    today = datetime.now()
    cutoff = today.replace(day=1)
    for _ in range(months_back):
        cutoff = (cutoff - timedelta(days=1)).replace(day=1)

    months: List[str] = []
    d = cutoff
    current_month = today.replace(day=1)
    while d < current_month:
        months.append(f"{d.year}-{d.month:02d}")
        next_month = d.month + 1 if d.month < 12 else 1
        next_year = d.year + (1 if d.month == 12 else 0)
        d = d.replace(year=next_year, month=next_month)

    spend: Dict[str, Dict[str, float]] = {}
    for row in rows:
        amount = parse_float(row.get("amount")) or 0.0
        if amount >= 0:
            continue
        transfer_id = row.get("transfer_account_id", "")
        if transfer_id in internal_ids:
            continue
        dt_str = row.get("settled_at") or row.get("created_at") or ""
        if not dt_str:
            continue
        dt = parse_datetime_or_date(dt_str)
        month_key = f"{dt.year}-{dt.month:02d}"
        if month_key not in months:
            continue
        cat = (row.get("category") or "").strip() or "uncategorised"
        spend.setdefault(month_key, {})
        spend[month_key][cat] = spend[month_key].get(cat, 0.0) + abs(amount)

    cat_totals: Dict[str, float] = {}
    for month_data in spend.values():
        for cat, total in month_data.items():
            cat_totals[cat] = cat_totals.get(cat, 0.0) + total
    top_cats = sorted(cat_totals, key=lambda c: cat_totals[c], reverse=True)[:12]

    result = []
    for cat in top_cats:
        monthly_values = [
            {"month": month, "total": round(spend.get(month, {}).get(cat, 0.0), 2)}
            for month in months
        ]
        result.append({
            "category": cat,
            "total": round(cat_totals[cat], 2),
            "monthly": monthly_values,
        })

    return jsonify({"months": months, "categories": result})


def _get_month_range(month_str: str) -> tuple:
    """Return (start_dt, end_dt) for a YYYY-MM string."""
    year, month = int(month_str[:4]), int(month_str[5:7])
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start, end


def _compute_month_cashflow(month_str: str) -> Dict:
    """Return clean monthly cashflow across every synced Up account."""
    start, end = _get_month_range(month_str)
    stats = period_financials(start, end)
    invested = stats["investment_transfers"]
    savings_rate = round(invested / stats["income"] * 100, 1) if stats["income"] > 0 else 0.0
    return {
        "income": stats["income"],
        "saved": invested,
        "discretionary": stats["ordinary_spend"],
        "ordinary_spend": stats["ordinary_spend"],
        "one_off_spend": stats["one_off_spend"],
        "essential_spend": stats["essential_spend"],
        "lifestyle_spend": stats["lifestyle_spend"],
        "total_spend": stats["total_spend"],
        "net_external_spend": stats["net_external_spend"],
        "reimbursements": stats["reimbursements"],
        "investment_transfers": invested,
        "internal_transfers": stats["internal_transfers"],
        "savings_rate": savings_rate,
    }


@app.get("/api/insights/monthly")
def api_insights_monthly():
    today = datetime.now()
    first_of_this_month = today.replace(day=1)
    default_month_dt = (first_of_this_month - timedelta(days=1)).replace(day=1)
    default_month = f"{default_month_dt.year}-{default_month_dt.month:02d}"
    month_str = request.args.get("month", default_month)

    try:
        year, month = int(month_str[:4]), int(month_str[5:7])
        if not (2020 <= year <= 2099 and 1 <= month <= 12):
            raise ValueError
    except (ValueError, IndexError):
        return jsonify({"error": "invalid month format, use YYYY-MM"}), 400

    prev_dt = datetime(year, month, 1) - timedelta(days=1)
    prev_month = f"{prev_dt.year}-{prev_dt.month:02d}"
    start, end = _get_month_range(month_str)
    prev_start, prev_end = _get_month_range(prev_month)

    current_stats = period_financials(start, end)
    prev_stats = period_financials(prev_start, prev_end)
    cf = _compute_month_cashflow(month_str)
    cf_prev = _compute_month_cashflow(prev_month)

    month_set = set()
    for row in read_all_up_transactions():
        dt_str = row.get("settled_at") or row.get("created_at") or ""
        if not dt_str:
            continue
        try:
            dt = parse_datetime_or_date(dt_str)
        except Exception:
            continue
        mk = f"{dt.year}-{dt.month:02d}"
        if mk <= default_month:
            month_set.add(mk)
    available_months = sorted(month_set, reverse=True)

    cat_spend = current_stats["categories"]
    cat_spend_prev = prev_stats["categories"]
    total_spend_den = current_stats["total_spend"] or 1.0
    top_categories = sorted(
        [
            {
                "slug": cat,
                "total": round(values["total"], 2),
                "prev_total": round(cat_spend_prev.get(cat, {}).get("total", 0.0), 2),
                "pct_of_disc": round(values["total"] / total_spend_den * 100, 1),
                "pct_of_spend": round(values["total"] / total_spend_den * 100, 1),
                "treatment": values.get("treatment", "lifestyle"),
            }
            for cat, values in cat_spend.items()
        ],
        key=lambda item: item["total"],
        reverse=True,
    )[:15]

    sorted_merchants = sorted(
        current_stats["merchants"].items(),
        key=lambda item: item[1]["total"],
        reverse=True,
    )[:15]
    cumulative = 0.0
    top_merchants = []
    for desc, values in sorted_merchants:
        cumulative += values["total"]
        top_merchants.append({
            "description": desc,
            "total": round(values["total"], 2),
            "count": values["count"],
            "cumulative": round(cumulative, 2),
            "category": values.get("category", ""),
            "treatment": values.get("treatment", "lifestyle"),
        })

    ordinary_categories = {
        cat: values
        for cat, values in cat_spend.items()
        if values.get("treatment") != "one_off"
    }
    ordinary_den = current_stats["ordinary_spend"] or 1.0
    weighted_total = sum(
        values["total"] * FRIVOLITY_WEIGHTS.get(cat, 0.5)
        for cat, values in ordinary_categories.items()
    )
    frivolity_score = round(weighted_total / ordinary_den * 100, 1)
    drivers = sorted(
        [
            {
                "slug": cat,
                "total": round(values["total"], 2),
                "weight": FRIVOLITY_WEIGHTS.get(cat, 0.5),
                "contribution": round(values["total"] * FRIVOLITY_WEIGHTS.get(cat, 0.5), 2),
            }
            for cat, values in ordinary_categories.items()
            if values["total"] * FRIVOLITY_WEIGHTS.get(cat, 0.5) > 0
        ],
        key=lambda item: item["contribution"],
        reverse=True,
    )[:8]

    hist_months = []
    d = default_month_dt
    for _ in range(6):
        hist_months.append(f"{d.year}-{d.month:02d}")
        d = (d - timedelta(days=1)).replace(day=1)
    hist_months.reverse()

    monthly_stats = {}
    frivolity_history = []
    for hm in hist_months:
        hs, he = _get_month_range(hm)
        stats = period_financials(hs, he)
        monthly_stats[hm] = stats
        hm_weighted = sum(
            values["total"] * FRIVOLITY_WEIGHTS.get(cat, 0.5)
            for cat, values in stats["categories"].items()
            if values.get("treatment") != "one_off"
        )
        hm_den = stats["ordinary_spend"]
        hm_score = round(hm_weighted / hm_den * 100, 1) if hm_den > 0 else 0.0
        frivolity_history.append({"month": hm, "score": hm_score})

    all_categories = set()
    for stats in monthly_stats.values():
        all_categories.update(stats["categories"].keys())
    cat_monthly = {
        cat: [
            monthly_stats[hm]["categories"].get(cat, {}).get("total", 0.0)
            for hm in hist_months
        ]
        for cat in all_categories
    }
    top_trend_cats = sorted(cat_monthly, key=lambda cat: sum(cat_monthly[cat]), reverse=True)[:8]
    trends = []
    for cat in top_trend_cats:
        vals = cat_monthly[cat]
        recent_3 = [value for value in vals[-3:] if value > 0]
        avg_3mo = round(sum(recent_3) / len(recent_3), 2) if recent_3 else 0.0
        this_month_val = cat_spend.get(cat, {}).get("total", 0.0)
        treatment = cat_spend.get(cat, {}).get("treatment", "lifestyle")
        trends.append({
            "slug": cat,
            "slope_per_month": linear_slope(vals),
            "avg_3mo": avg_3mo,
            "this_month": round(this_month_val, 2),
            "treatment": treatment,
        })

    return jsonify({
        "month": month_str,
        "prev_month": prev_month,
        "available_months": available_months,
        "income": cf["income"],
        "saved": cf["saved"],
        "discretionary": cf["ordinary_spend"],
        "ordinary_spend": cf["ordinary_spend"],
        "one_off_spend": cf["one_off_spend"],
        "essential_spend": cf["essential_spend"],
        "lifestyle_spend": cf["lifestyle_spend"],
        "total_spend": cf["total_spend"],
        "net_external_spend": cf["net_external_spend"],
        "internal_transfers_excluded": cf["internal_transfers"],
        "reimbursements": cf["reimbursements"],
        "savings_rate": cf["savings_rate"],
        "prev_savings_rate": cf_prev["savings_rate"],
        "prev_discretionary": cf_prev["ordinary_spend"],
        "prev_ordinary_spend": cf_prev["ordinary_spend"],
        "prev_one_off_spend": cf_prev["one_off_spend"],
        "top_categories": top_categories,
        "top_merchants": top_merchants,
        "frivolity": {
            "score": frivolity_score,
            "weighted_total": round(weighted_total, 2),
            "drivers": drivers,
            "history": frivolity_history,
            "basis": "ordinary_spend_only",
        },
        "trends": trends,
    })


def get_subscription_tags() -> Dict[str, str]:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    return config.get("subscription_tags", {})


def save_subscription_tag(description: str, tag: Optional[str]) -> None:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    tags = config.get("subscription_tags", {})
    if tag is None:
        tags.pop(description, None)
    else:
        tags[description] = tag
    config["subscription_tags"] = tags
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
        handle.write("\n")


@app.get("/api/insights/subscription-tags")
def api_get_subscription_tags():
    return jsonify(get_subscription_tags())


@app.post("/api/insights/subscription-tag")
def api_subscription_tag():
    payload = request.get_json(force=True) or {}
    description = (payload.get("description") or "").strip()
    tag = payload.get("tag")
    if not description:
        return jsonify({"ok": False, "error": "description required"}), 400
    if tag is not None and tag not in {"KEEP", "REVIEW", "CUT"}:
        return jsonify({"ok": False, "error": "tag must be KEEP, REVIEW, CUT, or null"}), 400
    save_subscription_tag(description, tag)
    return jsonify({"ok": True, "description": description, "tag": tag})


@app.get("/api/insights/category")
def api_insights_category():
    slug = (request.args.get("slug") or "").strip()
    if not slug:
        return jsonify({"error": "slug required"}), 400
    month_str = request.args.get("month", "")
    if not month_str:
        today = datetime.now()
        first_of_this_month = today.replace(day=1)
        default_dt = (first_of_this_month - timedelta(days=1)).replace(day=1)
        month_str = f"{default_dt.year}-{default_dt.month:02d}"
    try:
        year, month = int(month_str[:4]), int(month_str[5:7])
        if not (2020 <= year <= 2099 and 1 <= month <= 12):
            raise ValueError
    except (ValueError, IndexError):
        return jsonify({"error": "invalid month"}), 400

    status = get_status()
    internal_ids = owned_up_account_ids(status)

    # Build 6-month history window ending at month_str
    hist_months: List[str] = []
    d = datetime(year, month, 1)
    for _ in range(6):
        hist_months.append(f"{d.year}-{d.month:02d}")
        d = (d - timedelta(days=1)).replace(day=1)
    hist_months.reverse()

    all_rows = read_all_up_transactions()

    # Selected month range
    sel_start, sel_end = _get_month_range(month_str)

    history: Dict[str, float] = {m: 0.0 for m in hist_months}
    merchant_totals: Dict[str, float] = {}
    merchant_counts: Dict[str, int] = {}
    transactions: List[Dict] = []

    for row in all_rows:
        amount = parse_float(row.get("amount")) or 0.0
        if amount >= 0:
            continue
        if row.get("transfer_account_id", "") in internal_ids:
            continue
        if is_investment_outflow(row):
            continue
        dt_str = row.get("settled_at") or row.get("created_at") or ""
        if not dt_str:
            continue
        try:
            dt = parse_datetime_or_date(dt_str)
        except Exception:
            continue
        cat = (row.get("category") or "").strip() or "uncategorised"
        if cat != slug:
            continue
        mk = f"{dt.year}-{dt.month:02d}"
        if mk in history:
            history[mk] = history[mk] + abs(amount)
        if sel_start <= dt < sel_end:
            desc = (row.get("description") or "").strip()
            merchant_totals[desc] = merchant_totals.get(desc, 0.0) + abs(amount)
            merchant_counts[desc] = merchant_counts.get(desc, 0) + 1
            transactions.append({
                "date": dt.strftime("%Y-%m-%d"),
                "description": desc,
                "category": cat,
                "amount": round(abs(amount), 2),
            })

    transactions.sort(key=lambda x: x["date"], reverse=True)
    top_merchants = sorted(
        [
            {"description": d, "total": round(t, 2), "count": merchant_counts[d]}
            for d, t in merchant_totals.items()
        ],
        key=lambda x: x["total"],
        reverse=True,
    )[:10]

    return jsonify({
        "slug": slug,
        "month": month_str,
        "history": [{"month": m, "total": round(history[m], 2)} for m in hist_months],
        "top_merchants": top_merchants,
        "transactions": transactions,
    })


@app.get("/api/insights/merchant")
def api_insights_merchant():
    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    month_str = request.args.get("month", "")
    if not month_str:
        today = datetime.now()
        first_of_this_month = today.replace(day=1)
        default_dt = (first_of_this_month - timedelta(days=1)).replace(day=1)
        month_str = f"{default_dt.year}-{default_dt.month:02d}"
    try:
        year, month = int(month_str[:4]), int(month_str[5:7])
        if not (2020 <= year <= 2099 and 1 <= month <= 12):
            raise ValueError
    except (ValueError, IndexError):
        return jsonify({"error": "invalid month"}), 400

    status = get_status()
    internal_ids = owned_up_account_ids(status)

    hist_months: List[str] = []
    d = datetime(year, month, 1)
    for _ in range(6):
        hist_months.append(f"{d.year}-{d.month:02d}")
        d = (d - timedelta(days=1)).replace(day=1)
    hist_months.reverse()

    all_rows = read_all_up_transactions()
    sel_start, sel_end = _get_month_range(month_str)

    history: Dict[str, float] = {m: 0.0 for m in hist_months}
    transactions: List[Dict] = []

    for row in all_rows:
        amount = parse_float(row.get("amount")) or 0.0
        if amount >= 0:
            continue
        if row.get("transfer_account_id", "") in internal_ids:
            continue
        if is_investment_outflow(row):
            continue
        dt_str = row.get("settled_at") or row.get("created_at") or ""
        if not dt_str:
            continue
        try:
            dt = parse_datetime_or_date(dt_str)
        except Exception:
            continue
        desc = (row.get("description") or "").strip()
        if desc != name:
            continue
        mk = f"{dt.year}-{dt.month:02d}"
        if mk in history:
            history[mk] = history[mk] + abs(amount)
        if sel_start <= dt < sel_end:
            cat = (row.get("category") or "").strip() or "uncategorised"
            transactions.append({
                "date": dt.strftime("%Y-%m-%d"),
                "description": desc,
                "category": cat,
                "amount": round(abs(amount), 2),
            })

    transactions.sort(key=lambda x: x["date"], reverse=True)

    return jsonify({
        "name": name,
        "month": month_str,
        "history": [{"month": m, "total": round(history[m], 2)} for m in hist_months],
        "transactions": transactions,
    })


@app.get("/api/spending/summary")
def api_spending_summary():
    since = request.args.get("since")
    until = request.args.get("until")
    category = request.args.get("category")
    group_by = request.args.get("group_by", "month")
    exclude_refunds = request.args.get("exclude_refunds", "").lower() in {"1", "true", "yes"}
    min_amount = request.args.get("min_amount")

    rows = read_csv(DATA_DIR / "transactions_spending.csv")
    filtered = filter_spending_rows(rows, since, until, category)

    if exclude_refunds:
        filtered = [row for row in filtered if float(row.get("amount", 0)) < 0]

    if min_amount:
        try:
            threshold = abs(float(min_amount))
            filtered = [row for row in filtered if abs(float(row.get("amount", 0))) >= threshold]
        except ValueError:
            pass

    if group_by not in {"week", "month"}:
        group_by = "month"

    grouped = group_spending_by_period(filtered, group_by)

    merchant_totals: Dict[str, float] = {}
    merchant_counts: Dict[str, int] = {}
    for row in filtered:
        amount = float(row.get("amount", 0))
        if amount >= 0:
            continue
        desc = (row.get("description") or "").strip()
        if not desc:
            continue
        merchant_totals[desc] = merchant_totals.get(desc, 0.0) + abs(amount)
        merchant_counts[desc] = merchant_counts.get(desc, 0) + 1

    merchants = sorted(
        [
            {"description": desc, "total_spend": round(merchant_totals[desc], 2), "transaction_count": merchant_counts[desc]}
            for desc in merchant_totals
        ],
        key=lambda merchant: merchant["total_spend"],
        reverse=True,
    )[:20]

    total_spend = round(sum(abs(float(row.get("amount", 0))) for row in filtered if float(row.get("amount", 0)) < 0), 2)
    total_in = round(sum(float(row.get("amount", 0)) for row in filtered if float(row.get("amount", 0)) > 0), 2)

    return jsonify(
        {
            "group_by": group_by,
            "periods": grouped,
            "merchants": merchants,
            "total_spend": total_spend,
            "total_in": total_in,
            "transaction_count": len(filtered),
        }
    )


@app.get("/budget")
def budget_page():
    return send_file(BASE_DIR / "budget.html")


@app.get("/networth")
def networth_page():
    return send_file(BASE_DIR / "networth.html")


@app.get("/portfolio")
def portfolio_page():
    return send_file(BASE_DIR / "portfolio.html")


@app.get("/cgt")
def cgt_page():
    return send_file(BASE_DIR / "cgt.html")


@app.get("/house")
def house_page():
    return send_file(BASE_DIR / "house.html")


BILLS_UPLOAD_DIR = BASE_DIR / "imports" / "bills"
BILLS_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.post("/api/bills/upload")
def api_bills_upload():
    from flask import send_from_directory
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "Empty filename"}), 400
    safe_name = re.sub(r"[^\w.\- ]", "_", f.filename)
    dest = BILLS_UPLOAD_DIR / safe_name
    f.save(str(dest))
    return jsonify({"ok": True, "filename": safe_name, "path": str(dest)}), 201


@app.get("/api/bills/uploads")
def api_bills_uploads():
    files = []
    for p in sorted(BILLS_UPLOAD_DIR.iterdir()):
        if p.is_file():
            files.append({"filename": p.name, "size": p.stat().st_size, "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat()})
    return jsonify(files)


RECURRING_CSV = DATA_DIR / "recurring_investments.csv"
IBKR_INCEPTION = BASE_DIR / "imports" / "ibkr" / "Angus_J_Symons_Inception_May_15_2026.csv"
IBKR_FLEX = BASE_DIR / "imports" / "ibkr" / "U9504716_U9504716_20250516_20260515_AF_NA_47d9d492ad59520899300f36f9855bde.csv"


def parse_ibkr_performance():
    """Parse monthly TWR, dividends, and MTM from IBKR inception report + flex query."""
    import re as _re
    monthly_twr = {}
    dividends_by_year = {}
    mtm_by_ticker = {}

    if IBKR_INCEPTION.exists():
        with IBKR_INCEPTION.open(encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            if line.startswith("Historical Performance Benchmark Comparison,Data,"):
                parts = line.strip().split(",")
                month = parts[2]
                if _re.match(r"^\d{6}$", month):
                    val = parts[-1].strip()
                    if val and val != "-":
                        try:
                            monthly_twr[month] = float(val)
                        except ValueError:
                            pass
            elif line.startswith("Dividends,Data"):
                parts = line.strip().split(",")
                try:
                    year = parts[2][:4]
                    amount = float(parts[7])
                    dividends_by_year[year] = dividends_by_year.get(year, 0.0) + amount
                except (ValueError, IndexError):
                    pass

    if IBKR_FLEX.exists():
        with IBKR_FLEX.open(encoding="utf-8") as f:
            content = f.read()
        lines = content.splitlines()
        in_mtm = False
        for line in lines:
            if "TransactionMtmPnl" in line and "Symbol" in line:
                in_mtm = True
                continue
            if in_mtm and not line.startswith('"'):
                in_mtm = False
            if in_mtm and line.startswith('"'):
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 4 and parts[0] not in ("", "AUD", "USD"):
                    try:
                        mtm_by_ticker[parts[0]] = {
                            "transaction_mtm": float(parts[1]),
                            "prior_open_mtm": float(parts[2]),
                            "commissions": float(parts[3]),
                            "total": float(parts[4]),
                        }
                    except (ValueError, IndexError):
                        pass

    month_keys = sorted(monthly_twr)
    chained = 1.0
    for month_key in month_keys:
        chained *= 1.0 + monthly_twr[month_key] / 100.0
    since_return_pct = (chained - 1.0) * 100.0 if month_keys else None
    annualised_return_pct = None
    if month_keys and chained > 0:
        annualised_return_pct = (chained ** (12.0 / len(month_keys)) - 1.0) * 100.0

    current_year = str(date.today().year)
    ytd_factor = 1.0
    ytd_count = 0
    for month_key in month_keys:
        if month_key.startswith(current_year):
            ytd_factor *= 1.0 + monthly_twr[month_key] / 100.0
            ytd_count += 1

    current_value_aud = 0.0
    for row in read_csv(HOLDINGS_CSV):
        if (row.get("platform") or "").strip().upper() != "IBKR":
            continue
        current_value_aud += parse_float(row.get("current_value_aud")) or 0.0

    return {
        "available": bool(monthly_twr),
        "platform": "IBKR",
        "monthly_twr": monthly_twr,
        "dividends_by_year": {k: round(v, 2) for k, v in dividends_by_year.items()},
        "dividend_currency": "USD",
        "mtm_by_ticker": mtm_by_ticker,
        "since_return_pct": round(since_return_pct, 4) if since_return_pct is not None else None,
        "annualised_return_pct": round(annualised_return_pct, 4) if annualised_return_pct is not None else None,
        "ytd_return_pct": round((ytd_factor - 1.0) * 100.0, 4) if ytd_count else None,
        "current_value_aud": round(current_value_aud, 2),
        "performance_start": month_keys[0] if month_keys else None,
        "performance_end": month_keys[-1] if month_keys else None,
    }


def parse_selfwealth_performance() -> Dict:
    path = DATA_DIR / "selfwealth_performance.json"
    if not path.exists():
        return {
            "available": False,
            "platform": "SelfWealth",
            "error": "SelfWealth performance cache not built",
            "build_command": "python scripts/build_selfwealth_performance.py",
        }
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        return {
            "available": False,
            "platform": "SelfWealth",
            "error": f"Unable to read SelfWealth performance cache: {exc}",
        }


@app.get("/api/performance")
def api_performance():
    ibkr = parse_ibkr_performance()
    selfwealth = parse_selfwealth_performance()
    selfwealth_current = (
        float((selfwealth.get("current") or {}).get("current_value_aud") or 0.0)
        if selfwealth.get("available")
        else 0.0
    )
    combined_current = float(ibkr.get("current_value_aud") or 0.0) + selfwealth_current
    combined = {
        "available": False,
        "platform": "All",
        "current_value_aud": round(combined_current, 2),
        "error": (
            "Combined current value is available, but combined TWR is intentionally "
            "withheld until IBKR monthly portfolio valuations/cash flows are available."
        ),
    }
    return jsonify({
        "default_platform": "ibkr",
        "platforms": {
            "ibkr": ibkr,
            "selfwealth": selfwealth,
            "all": combined,
        },
    })


@app.get("/api/recurring")
def api_recurring():
    return jsonify(read_csv(RECURRING_CSV))


@app.get("/performance")
def performance_page():
    return send_file(BASE_DIR / "performance.html")


@app.get("/tax")
def tax_page():
    return send_file(BASE_DIR / "tax.html")


HEALTH_DIR = BASE_DIR / "health"
CARE_DIR = BASE_DIR / "care"


@app.get("/health")
def health_root():
    return redirect("/health/dashboard")


@app.get("/health/<tab>")
def health_page(tab: str):
    page = HEALTH_DIR / f"{tab}.html"
    if not page.exists():
        return "Not found", 404
    return send_file(page)


@app.get("/care")
def care_root():
    return redirect("/care/anti-age")


@app.get("/care/<tab>")
def care_page(tab: str):
    page = CARE_DIR / f"{tab}.html"
    if not page.exists():
        return "Not found", 404
    return send_file(page)


# ── Health data API ──────────────────────────────────────────────────────────

from health_pipeline.metrics import (
    hrv_daily, resting_hr_daily, sleep_daily, spo2_daily, resp_rate_daily,
    steps_daily, vo2_trend, nutrition_daily, workout_sessions,
    import_status, get_config, set_config, hrv_baseline, resting_hr_baseline,
)
from health_pipeline.parse_macrofactor import (
    import_nutrition as _import_nutrition,
    import_workouts as _import_workouts,
    NUTRITION_PATH, WORKOUTS_PATH,
)
from health_pipeline.parse_health_json import parse_and_import, latest_health_json

HEALTH_UPLOAD_DIR = BASE_DIR / "imports" / "health"
HEALTH_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ICLOUD_HEALTH_EXPORT_DIR = (
    Path.home()
    / "Library"
    / "Mobile Documents"
    / "iCloud~com~ifunography~HealthExport"
    / "Documents"
)
HEVY_ICLOUD_PATH = ICLOUD_HEALTH_EXPORT_DIR / "hevy_workout_data.csv"


@app.get("/api/health/status")
def api_health_status():
    return jsonify({
        "imports": import_status(),
        "config": get_config(),
    })


@app.get("/api/health/hrv")
def api_health_hrv():
    days = int(request.args.get("days", 30))
    return jsonify({
        "data": hrv_daily(days),
        "baseline": hrv_baseline(days),
    })


@app.get("/api/health/resting-hr")
def api_health_resting_hr():
    days = int(request.args.get("days", 30))
    return jsonify({
        "data": resting_hr_daily(days),
        "baseline": resting_hr_baseline(days),
    })


@app.get("/api/health/sleep")
def api_health_sleep():
    days = int(request.args.get("days", 30))
    return jsonify(sleep_daily(days))


@app.get("/api/health/spo2")
def api_health_spo2():
    days = int(request.args.get("days", 30))
    return jsonify(spo2_daily(days))


@app.get("/api/health/respiratory-rate")
def api_health_resp():
    days = int(request.args.get("days", 30))
    return jsonify(resp_rate_daily(days))


@app.get("/api/health/steps")
def api_health_steps():
    days = int(request.args.get("days", 30))
    return jsonify(steps_daily(days))


@app.get("/api/health/vo2")
def api_health_vo2():
    days = int(request.args.get("days", 90))
    return jsonify(vo2_trend(days))


@app.get("/api/health/nutrition")
def api_health_nutrition():
    days = int(request.args.get("days", 30))
    return jsonify(nutrition_daily(days))


@app.get("/api/health/nutrition/protein-target")
def api_protein_target():
    """Return dynamic protein target based on latest body weight (2× BW in grams)."""
    from health_pipeline.db import get_conn
    conn = get_conn()
    row = conn.execute(
        "SELECT date, body_weight_kg FROM body_measurements WHERE body_weight_kg IS NOT NULL ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if row and row["body_weight_kg"]:
        bw = row["body_weight_kg"]
        target = round(bw * 2)
        return jsonify({"target_g": target, "body_weight_kg": bw, "date": row["date"], "formula": "2× BW"})
    return jsonify({"target_g": 160, "body_weight_kg": None, "date": None, "formula": "default"})


@app.get("/api/health/workouts")
def api_health_workouts():
    days = int(request.args.get("days", 30))
    return jsonify(workout_sessions(days))


@app.get("/api/health/scores")
def api_health_scores():
    from health_pipeline.scores import compute_scores
    return jsonify(compute_scores())


@app.get("/api/health/scores/history")
def api_health_scores_history():
    from health_pipeline.scores import scores_history
    days = int(request.args.get("days", 30))
    return jsonify(scores_history(days))


@app.get("/api/health/strain/workouts")
def api_health_strain_workouts():
    from health_pipeline.scores import strain_workouts_detail
    days = int(request.args.get("days", 30))
    return jsonify(strain_workouts_detail(days))


@app.get("/api/health/nutrition/detail")
def api_health_nutrition_detail():
    days = int(request.args.get("days", 30))
    return jsonify(nutrition_daily(days))


@app.get("/api/health/nutrition/food-log")
def api_health_food_log():
    """Return raw food log entries grouped by date, most recent first."""
    days = int(request.args.get("days", 7))
    from health_pipeline.db import get_conn
    conn = get_conn()
    rows = conn.execute(
        """SELECT date, time, food_name, calories, protein_g, carbs_g, fat_g, fiber_g, sodium_mg
           FROM nutrition_log
           WHERE date >= date('now', ? || ' days') AND food_name != ''
           ORDER BY date DESC, time ASC""",
        (f"-{days}",)
    ).fetchall()
    conn.close()
    # Group by date
    from collections import defaultdict
    by_date = defaultdict(list)
    for r in rows:
        by_date[r[0]].append({
            "time": r[1], "food_name": r[2],
            "calories": r[3], "protein_g": r[4],
            "carbs_g": r[5], "fat_g": r[6],
            "fiber_g": r[7], "sodium_mg": r[8],
        })
    return jsonify([{"date": d, "entries": entries} for d, entries in sorted(by_date.items(), reverse=True)])


@app.get("/api/health/nutrition/top-foods")
def api_health_top_foods():
    """Return top foods by protein density, frequency, and calorie contribution."""
    days = int(request.args.get("days", 90))
    from health_pipeline.db import get_conn
    conn = get_conn()
    rows = conn.execute(
        """SELECT food_name,
                  COUNT(*) as times_logged,
                  AVG(calories) as avg_cal,
                  AVG(protein_g) as avg_prot,
                  AVG(carbs_g) as avg_carbs,
                  AVG(fat_g) as avg_fat,
                  SUM(protein_g) as total_prot,
                  SUM(calories) as total_cal
           FROM nutrition_log
           WHERE date >= date('now', ? || ' days')
             AND food_name != ''
             AND (calories > 0 OR protein_g > 0)
           GROUP BY food_name
           HAVING COUNT(*) >= 2
           ORDER BY avg_prot DESC
           LIMIT 50""",
        (f"-{days}",)
    ).fetchall()
    conn.close()
    foods = []
    for r in rows:
        avg_prot = r[3] or 0
        avg_cal = r[2] or 1
        prot_density = round(avg_prot / avg_cal * 100, 1) if avg_cal > 0 else 0
        foods.append({
            "food_name": r[0],
            "times_logged": r[1],
            "avg_calories": round(r[2] or 0, 0),
            "avg_protein_g": round(avg_prot, 1),
            "avg_carbs_g": round(r[4] or 0, 1),
            "avg_fat_g": round(r[5] or 0, 1),
            "total_protein_g": round(r[6] or 0, 1),
            "protein_per_100kcal": prot_density,
        })
    return jsonify(foods)


@app.get("/api/health/strength/exercises")
def api_health_strength_exercises():
    from health_pipeline.scores import strength_exercises
    return jsonify(strength_exercises())


@app.get("/api/health/strength/progression")
def api_health_strength_progression():
    from health_pipeline.scores import strength_progression
    exercise = request.args.get("exercise", "")
    days = int(request.args.get("days", 90))
    return jsonify(strength_progression(exercise, days))


@app.get("/api/health/strength/weekly-sets")
def api_health_strength_weekly_sets():
    from health_pipeline.scores import strength_weekly_sets
    days = int(request.args.get("days", 7))
    return jsonify(strength_weekly_sets(days))


@app.get("/api/health/strength/muscle-detail")
def api_strength_muscle_detail():
    from health_pipeline.scores import strength_muscle_detail
    muscle = request.args.get("muscle", "")
    days = int(request.args.get("days", 84))
    return jsonify(strength_muscle_detail(muscle, days))


@app.get("/api/health/strength/set-analysis")
def api_strength_set_analysis():
    from health_pipeline.scores import strength_set_analysis
    exercise = request.args.get("exercise", "")
    days = int(request.args.get("days", 90))
    return jsonify(strength_set_analysis(exercise, days))


@app.get("/api/health/strength/forecast")
def api_strength_forecast():
    from health_pipeline.scores import strength_overload_forecast
    exercise = request.args.get("exercise", "")
    days = int(request.args.get("days", 180))
    return jsonify(strength_overload_forecast(exercise, days))


@app.get("/api/health/strength/recommended-program")
def api_strength_recommended_program():
    """Return the recommended 2-upper-2-lower program and MEV gap analysis."""
    from health_pipeline.scores import strength_weekly_sets, HYPERTROPHY
    # Get 18-week avg for comparison
    current = strength_weekly_sets(days=126)  # ~18 weeks
    current_avg = current.get("muscle_avg_per_week", {})

    program = {
        "upper_a": {
            "name": "Upper A — Push/Pull",
            "location": "Revo or Garage",
            "focus": "Posture + balanced push/pull",
            "duration_min": 65,
            "exercises": [
                {"order": 1, "exercise": "Neutral Grip Machine Rear Delt Fly", "sets": 4, "reps": "12–15", "rir": "0–1", "note": "Train first — fresh. Posture fix priority #1"},
                {"order": 2, "exercise": "Cable Face Pull", "sets": 3, "reps": "12–15", "rir": "0–1", "note": "External rotation. Non-negotiable for rounded shoulder fix"},
                {"order": 3, "exercise": "45° Incline Barbell Press", "sets": 3, "reps": "8–10", "rir": "1", "note": "One chest press only. Upper chest, minimal pec minor"},
                {"order": 4, "exercise": "Wide Grip Cable Row", "sets": 4, "reps": "10–12", "rir": "0–1", "note": "Bump to 4 sets — your strongest row"},
                {"order": 5, "exercise": "Seated Dumbbell Lateral Raise", "sets": 3, "reps": "12–15", "rir": "0", "note": "Failure first set, two back-offs"},
                {"order": 6, "exercise": "Standing Dumbbell Biceps Curl", "sets": 3, "reps": "10–12", "rir": "0", "note": "3 hard sets — drop the faded 4th"},
                {"order": 7, "exercise": "Single Arm Neutral Grip Cable Triceps Pushdown", "sets": 3, "reps": "12–14", "rir": "0", "note": "Keep as-is"},
            ]
        },
        "upper_c": {
            "name": "Upper C — OHP/Pull",
            "location": "Revo",
            "focus": "Vertical pull + overhead strength",
            "duration_min": 75,
            "exercises": [
                {"order": 1, "exercise": "Barbell Overhead Press", "sets": 3, "reps": "6–8", "rir": "0–1", "note": "Reverse pyramid. Push final set to RIR 0"},
                {"order": 2, "exercise": "Seated Machine Lateral Raise", "sets": 3, "reps": "12–15", "rir": "0", "note": "NEW — zero side delts in this session currently"},
                {"order": 3, "exercise": "Chest-Supported Wide Grip T-Bar Row", "sets": 4, "reps": "8–12", "rir": "0–1", "note": "Bump to 4 sets. Best stretch-position back exercise you do"},
                {"order": 4, "exercise": "Neutral Close Grip Cable Lat Pulldown", "sets": 3, "reps": "8–10", "rir": "0–1", "note": "Keep"},
                {"order": 5, "exercise": "EZ Bar Preacher Curl", "sets": 3, "reps": "8–10", "rir": "0–1", "note": "Keep. Best peak-contraction biceps exercise"},
                {"order": 6, "exercise": "Cable Straight Bar Overhead Triceps Extension", "sets": 3, "reps": "9–12", "rir": "0–1", "note": "Keep. Long head stretch essential"},
                {"order": 7, "exercise": "Kneeling Cable Crunch", "sets": 3, "reps": "12–15", "rir": "0–1", "note": "Replace decline sit-up — sit-up is hip flexor, not abs"},
            ]
        },
        "lower_d1": {
            "name": "Lower D1 — Glute/Ham",
            "location": "Revo",
            "focus": "Hip extension dominant",
            "duration_min": 70,
            "exercises": [
                {"order": 1, "exercise": "Smith Machine Hip Thrust", "sets": 3, "reps": "10–13", "rir": "0", "note": "Push every set to RIR 0. You're strong here"},
                {"order": 2, "exercise": "Lying Hamstring Curl", "sets": 3, "reps": "10–13", "rir": "0–1", "note": "Keep"},
                {"order": 3, "exercise": "Barbell Romanian Deadlift", "sets": 3, "reps": "8–10", "rir": "0–1", "note": "NEW to this session — hip-extension hamstring stimulus missing from Revo D"},
                {"order": 4, "exercise": "Dumbbell Bulgarian Split Squat", "sets": 3, "reps": "10–12", "rir": "0–1", "note": "Replace step-up. More quad-dominant, you're already proficient"},
                {"order": 5, "exercise": "Seated Machine Hip Abduction", "sets": 3, "reps": "12–15", "rir": "0", "note": "3 working sets — not 6 drop sets"},
            ]
        },
        "lower_d2": {
            "name": "Lower D2 — Quad/Posterior",
            "location": "Garage",
            "focus": "Knee extension + full posterior chain",
            "duration_min": 85,
            "exercises": [
                {"order": 1, "exercise": "Barbell Box Squat", "sets": 3, "reps": "10–12", "rir": "0–1", "note": "Tighten RPT drops to 5–8%. All sets RIR 0–1 — current avg RIR 1.4 is too conservative"},
                {"order": 2, "exercise": "Dumbbell Bulgarian Split Squat", "sets": 3, "reps": "10–12", "rir": "0–1", "note": "Quad isolation substitute — no leg press in garage, knee-safe alternative"},
                {"order": 3, "exercise": "Barbell Romanian Deadlift", "sets": 3, "reps": "8–10", "rir": "0–1", "note": "Keep"},
                {"order": 4, "exercise": "Standing Cable Leg Curl", "sets": 3, "reps": "12–15", "rir": "0–1", "note": "Keep"},
                {"order": 5, "exercise": "Barbell Hip Thrust", "sets": 3, "reps": "10–12", "rir": "0–1", "note": "Add — don't skip hip thrust when in garage"},
            ]
        }
    }

    # MEV gap analysis
    mev_analysis = []
    muscles_in_program = {
        "chest": 3, "side delts": 6, "back": 11, "rear delts": 7,
        "biceps": 6, "triceps": 6, "quads": 9, "hamstrings": 9,
        "glutes": 9, "front delts": 3, "abs": 3, "traps": 3,
    }
    for muscle, program_sets in muscles_in_program.items():
        h = HYPERTROPHY.get(muscle, {"min": 6, "target": 10, "max": 20})
        current_wk = current_avg.get(muscle, 0)
        mev_analysis.append({
            "muscle": muscle,
            "current_avg_per_week": current_wk,
            "program_sets_per_week": program_sets,
            "mev": h.get("min", 6),
            "target": h.get("target", 10),
            "current_status": "above_target" if current_wk >= h.get("target", 10) else
                              "above_mev" if current_wk >= h.get("min", 6) else "below_mev",
            "program_status": "above_target" if program_sets >= h.get("target", 10) else
                              "above_mev" if program_sets >= h.get("min", 6) else "intentional_low",
        })

    rpt_notes = {
        "verdict": "Good method, wrong execution",
        "recommendation": "Keep reverse pyramid",
        "details": [
            "RPT front-loads heaviest work when fresh — correct principle",
            "Your drop magnitudes are too large: box squat 82.5→75→65kg is a 21% drop, sets 2–3 land at RIR 1–2",
            "Target: 5–8% weight drop per set, all sets should hit RIR 0–1",
            "RIR 0–1 applies to EVERY working set, not just the first",
            "If set 3 has RIR 2+, you dropped too much weight — increase it next session",
        ]
    }

    return jsonify({
        "program": program,
        "mev_analysis": mev_analysis,
        "rpt_notes": rpt_notes,
        "duration_note": "Durations based on your actual session data (Revo C avg 107min, Garage A avg 97min, Garage D avg 85min, Revo D avg 71min). Timer-forgotten sessions excluded.",
    })


@app.get("/api/health/measurements")
def api_health_measurements_get():
    from health_pipeline.scores import body_measurements_get
    days = int(request.args.get("days", 90))
    return jsonify(body_measurements_get(days))


@app.post("/api/health/measurements")
def api_health_measurements_post():
    from health_pipeline.scores import body_measurements_add
    payload = request.get_json(force=True) or {}
    body_measurements_add(payload)
    return jsonify({"ok": True})


@app.get("/api/health/body-composition")
def api_health_body_composition():
    from health_pipeline.scores import body_composition_forecast
    days = int(request.args.get("days", 90))
    return jsonify(body_composition_forecast(days))


@app.get("/api/health/symptoms")
def api_health_symptoms_get():
    """Return symptom log entries."""
    from health_pipeline.db import get_conn
    days = int(request.args.get("days", 90))
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM symptom_log WHERE date >= ? ORDER BY date DESC, time DESC",
        (cutoff,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.post("/api/health/symptoms")
def api_health_symptoms_post():
    """Log a new symptom entry."""
    from health_pipeline.db import get_conn
    payload = request.get_json(force=True) or {}
    # Validate
    bristol = payload.get("bristol_type")
    if bristol is not None and not (1 <= int(bristol) <= 7):
        return jsonify({"ok": False, "error": "bristol_type must be 1–7"}), 400
    conn = get_conn()
    conn.execute("""
        INSERT INTO symptom_log
          (date, time, bristol_type, urgency, quantity, effort, gut_comfort,
           bloating, pain_level, duration_mins, weight_g, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        payload.get("date", date.today().isoformat()),
        payload.get("time"),
        payload.get("bristol_type"),
        payload.get("urgency"),
        payload.get("quantity"),
        payload.get("effort"),
        payload.get("gut_comfort"),
        payload.get("bloating"),
        payload.get("pain_level"),
        payload.get("duration_mins"),
        payload.get("weight_g"),
        payload.get("notes", ""),
    ))
    conn.commit()
    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return jsonify({"ok": True, "id": new_id})


@app.delete("/api/health/symptoms/<int:entry_id>")
def api_health_symptoms_delete(entry_id):
    """Delete a symptom log entry."""
    from health_pipeline.db import get_conn
    conn = get_conn()
    conn.execute("DELETE FROM symptom_log WHERE id=?", (entry_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.get("/api/health/cardio/weekly")
def api_health_cardio_weekly():
    from health_pipeline.scores import cardio_weekly_summary
    weeks = int(request.args.get("weeks", 12))
    return jsonify(cardio_weekly_summary(weeks))


@app.get("/api/health/cardio/rhr-trend")
def api_health_cardio_rhr_trend():
    from health_pipeline.scores import cardio_rhr_trend
    days = int(request.args.get("days", 90))
    return jsonify(cardio_rhr_trend(days))


@app.get("/api/health/cardio/zone-history")
def api_health_cardio_zone_history():
    from health_pipeline.scores import cardio_zone_minutes_history
    days = int(request.args.get("days", 84))
    return jsonify(cardio_zone_minutes_history(days))


@app.get("/api/health/cardio/ecg")
def api_health_cardio_ecg():
    from health_pipeline.scores import cardio_ecg_results
    return jsonify(cardio_ecg_results())


@app.get("/api/health/cardio/blood-panel")
def api_health_cardio_blood_panel():
    from health_pipeline.scores import cardio_blood_panel
    tests = request.args.getlist("test")
    return jsonify(cardio_blood_panel(tests if tests else None))


@app.post("/api/health/config")
def api_health_config():
    payload = request.get_json(force=True) or {}
    allowed = {"hr_max", "sleep_goal_hrs", "sleep_source_preference"}
    for k, v in payload.items():
        if k in allowed:
            set_config(k, str(v))
    return jsonify({"ok": True, "config": get_config()})


@app.post("/api/health/import/apple-health")
def api_health_import_apple():
    if "file" in request.files:
        f = request.files["file"]
        safe_name = re.sub(r"[^\w.\- ]", "_", f.filename or "health.json")
        dest = HEALTH_UPLOAD_DIR / safe_name
        f.save(str(dest))
        path = dest
    else:
        path = latest_health_json()
        if not path:
            return jsonify({"ok": False, "error": "No Health Auto Export file found in iCloud Drive"}), 404

    try:
        counts = parse_and_import(path)
        # Also import AutoSync .hae data (weight + routes) every time
        try:
            from health_pipeline.parse_hae import import_autosync_all
            hae_counts = import_autosync_all()
            counts.update(hae_counts)
        except Exception:
            pass
        return jsonify({"ok": True, "counts": counts, "file": path.name})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/health/import/autosync")
def api_health_import_autosync():
    """Standalone endpoint to import AutoSync .hae files without a full JSON export."""
    try:
        from health_pipeline.parse_hae import import_autosync_all
        counts = import_autosync_all()
        return jsonify({"ok": True, "counts": counts})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/health/import/apple-xml")
def api_health_import_apple_xml():
    """Import Apple Health native XML export (.zip or upload)."""
    from health_pipeline.parse_apple_xml import parse_apple_xml_zip

    if "file" in request.files:
        f = request.files["file"]
        safe_name = re.sub(r"[^\w.\- ]", "_", f.filename or "export.zip")
        dest = HEALTH_UPLOAD_DIR / safe_name
        f.save(str(dest))
        zip_path = dest
    else:
        # Look for a zip in HEALTH_UPLOAD_DIR
        zips = sorted(HEALTH_UPLOAD_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not zips:
            return jsonify({"ok": False, "error": "No zip file found — upload the Apple Health export zip"}), 404
        zip_path = zips[0]

    try:
        counts = parse_apple_xml_zip(zip_path)
        # Log the import
        conn_log = __import__("health_pipeline.db", fromlist=["get_conn"]).get_conn()
        total = sum(v for v in counts.values() if isinstance(v, int))
        conn_log.execute(
            "INSERT INTO import_log(source, imported_at, record_count, filename) "
            "VALUES ('apple_xml', datetime('now'), ?, ?)",
            (total, zip_path.name)
        )
        conn_log.commit()
        conn_log.close()
        return jsonify({"ok": True, "counts": counts, "file": zip_path.name})
    except Exception as exc:
        import traceback
        return jsonify({"ok": False, "error": str(exc), "trace": traceback.format_exc()}), 500


@app.post("/api/health/import/hevy")
def api_health_import_hevy():
    """Import Hevy workout CSV (uploaded or auto-detected from iCloud Health Export folder)."""
    from health_pipeline.parse_hevy import parse_hevy_csv

    if "file" in request.files:
        f = request.files["file"]
        safe_name = re.sub(r"[^\w.\- ]", "_", f.filename or "hevy_workout_data.csv")
        dest = HEALTH_UPLOAD_DIR / safe_name
        f.save(str(dest))
        csv_path = dest
    elif HEVY_ICLOUD_PATH.exists():
        csv_path = HEVY_ICLOUD_PATH
    else:
        csvs = sorted(HEALTH_UPLOAD_DIR.glob("hevy*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not csvs:
            return jsonify({"ok": False, "error": "No Hevy CSV found — upload hevy_workout_data.csv or place it in the Health Export iCloud folder"}), 404
        csv_path = csvs[0]

    try:
        counts = parse_hevy_csv(csv_path)
        # Log the import
        import sqlite3 as _sqlite3
        conn_log = __import__("health_pipeline.db", fromlist=["get_conn"]).get_conn()
        # Get date range of inserted Hevy data
        date_range = conn_log.execute(
            "SELECT MIN(date), MAX(date) FROM workout_sets WHERE source='hevy'"
        ).fetchone()
        conn_log.execute(
            "INSERT INTO import_log(source, imported_at, record_count, date_from, date_to, filename) "
            "VALUES ('hevy', datetime('now'), ?, ?, ?, ?)",
            (counts.get("inserted", 0), date_range[0], date_range[1], str(csv_path.name))
        )
        conn_log.commit()
        conn_log.close()
        return jsonify({"ok": True, "counts": counts, "file": str(csv_path.name)})
    except Exception as exc:
        import traceback
        return jsonify({"ok": False, "error": str(exc), "trace": traceback.format_exc()}), 500


@app.post("/api/health/import/macrofactor")
def api_health_import_mf():
    results = {}
    errors = {}

    nutr_file = request.files.get("nutrition")
    work_file = request.files.get("workouts")
    nutrition_only = request.form.get("nutrition_only") == "1"
    workouts_only = request.form.get("workouts_only") == "1"

    from health_pipeline.parse_macrofactor import latest_nutrition_path, latest_workouts_path

    # Determine which sources to import.
    # nutrition_only / workouts_only flags restrict to one source (used by dedicated sync buttons).
    want_nutr = not workouts_only
    want_work = not nutrition_only

    # Determine paths: prefer uploaded file, then iCloud drop folder (latest CSV), then skip
    nutr_path = None
    work_path = None

    if want_nutr:
        if nutr_file:
            nutr_path = HEALTH_UPLOAD_DIR / "nutrition.csv"
            nutr_file.save(str(nutr_path))
        else:
            nutr_path = latest_nutrition_path()

    if want_work:
        if work_file:
            work_path = HEALTH_UPLOAD_DIR / "workouts.csv"
            work_file.save(str(work_path))
        else:
            work_path = latest_workouts_path()

    # Only import what we have — never error on a missing file the user didn't request
    if nutr_path:
        try:
            results["nutrition"] = _import_nutrition(nutr_path)
        except Exception as exc:
            errors["nutrition"] = str(exc)

    if work_path:
        try:
            results["workouts"] = _import_workouts(work_path)
        except Exception as exc:
            errors["workouts"] = str(exc)

    if not nutr_path and not work_path:
        errors["files"] = "No files provided and no iCloud exports found"

    ok = not errors
    return jsonify({"ok": ok, "imported": results, "errors": errors}), (200 if ok else 207)


@app.get("/api/networth")
def api_networth():
    return jsonify(read_csv(NETWORTH_CSV))


@app.get("/api/holdings")
def api_holdings():
    return jsonify(read_csv(HOLDINGS_CSV))


@app.post("/api/networth/import")
def api_networth_import():
    payload = request.get_json(force=True) or {}
    try:
        super_aud = float(payload.get("super_aud", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "super_aud must be a number"}), 400
    try:
        count = import_networth_from_excel(super_aud)
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "imported": count})


def _get_gspread_client():
    try:
        import gspread  # noqa: PLC0415
        from google.oauth2.service_account import Credentials  # noqa: PLC0415
    except ImportError:
        raise RuntimeError("Install gspread and google-auth: pip install gspread google-auth")
    config = load_config()
    gs = config.get("google_sheets", {})
    creds_path = BASE_DIR / gs.get("credentials_path", "credentials.json")
    if not creds_path.exists():
        raise FileNotFoundError(f"Google credentials file not found: {creds_path}")
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(str(creds_path), scopes=scopes)
    return gspread.authorize(creds), gs


def import_networth_from_sheets() -> int:
    gc, gs = _get_gspread_client()
    sheet_id = gs.get("networth_sheet_id", "")
    if not sheet_id:
        raise ValueError("google_sheets.networth_sheet_id not set in config.json")

    tab = gs.get("networth_sheet_tab", "")
    spreadsheet = gc.open_by_key(sheet_id)
    ws = spreadsheet.worksheet(tab) if tab else spreadsheet.get_worksheet(0)
    records = ws.get_all_records()

    col_date = gs.get("networth_col_date", "Timestamp")
    col_everyday = gs.get("networth_col_everyday", "Everyday")
    col_savings = gs.get("networth_col_savings", "Savings")
    col_selfwealth = gs.get("networth_col_selfwealth", "SelfWealth")
    col_ibkr = gs.get("networth_col_ibkr", "IBKR")
    col_super = gs.get("networth_col_super", "")

    existing = {row["date"]: row for row in read_csv(NETWORTH_CSV)}
    imported = 0
    for record in records:
        raw_date = str(record.get(col_date, "")).strip()
        if not raw_date:
            continue
        try:
            date_str = parser.parse(raw_date, dayfirst=True).strftime("%Y-%m-%d")
        except Exception:
            continue
        everyday = float(record.get(col_everyday) or 0)
        savings = float(record.get(col_savings) or 0)
        selfwealth = float(record.get(col_selfwealth) or 0)
        ibkr = float(record.get(col_ibkr) or 0)
        super_aud = float(record.get(col_super) or 0) if col_super else 0.0
        cash = round(everyday + savings, 2)
        investments = round(selfwealth + ibkr, 2)
        existing[date_str] = {
            "date": date_str,
            "cash_aud": str(cash),
            "investments_aud": str(investments),
            "super_aud": str(round(super_aud, 2)),
            "total_aud": str(round(cash + investments + super_aud, 2)),
        }
        imported += 1

    write_csv(NETWORTH_CSV, NETWORTH_FIELDS, sorted(existing.values(), key=lambda r: r["date"]))
    return imported


def import_bills_from_sheets() -> int:
    gc, gs = _get_gspread_client()
    sheet_id = gs.get("bills_sheet_id", "")
    if not sheet_id:
        raise ValueError("google_sheets.bills_sheet_id not set in config.json")

    ws = gc.open_by_key(sheet_id).get_worksheet(0)
    records = ws.get_all_records()

    col_slug = gs.get("bills_col_slug", "Bill Type")
    col_amount = gs.get("bills_col_amount", "Amount")
    col_due_date = gs.get("bills_col_due_date", "Due Date")
    col_notes = gs.get("bills_col_notes", "Notes")

    bills = read_bills()
    added = 0
    for record in records:
        slug = str(record.get(col_slug, "")).strip().lower()
        if slug not in BILL_SLUGS:
            continue
        raw_due = str(record.get(col_due_date, "")).strip()
        try:
            due_date_str = parser.parse(raw_due).strftime("%Y-%m-%d")
        except Exception:
            continue
        if any(b.get("slug", "").lower() == slug and b.get("due_date") == due_date_str for b in bills):
            continue
        amount_raw = str(record.get(col_amount, "")).replace("$", "").replace(",", "").strip()
        amount = None
        try:
            if amount_raw:
                amount = float(amount_raw)
        except ValueError:
            pass
        notes = str(record.get(col_notes, "")).strip()
        append_bill({
            "slug": slug,
            "label": LABEL_DEFAULTS.get(slug, slug.title()),
            "total_amount": amount,
            "due_date": due_date_str,
            "recurrence": "monthly",
            "split_type": "fixed" if slug == "rent" else "equal",
            "notes": notes,
        })
        bills = read_bills()
        added += 1
    return added


@app.post("/api/networth/import-sheets")
def api_networth_import_sheets():
    try:
        count = import_networth_from_sheets()
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "imported": count})


@app.post("/api/bills/sync-sheets")
def api_bills_sync_sheets():
    try:
        added = import_bills_from_sheets()
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "added": added})


def import_gut_from_sheets() -> int:
    gc, gs = _get_gspread_client()
    sheet_id = gs.get("gut_sheet_id", "")
    if not sheet_id:
        raise ValueError("google_sheets.gut_sheet_id not set in config.json")

    tab = gs.get("gut_sheet_tab", "Form responses 1")
    spreadsheet = gc.open_by_key(sheet_id)
    ws = spreadsheet.worksheet(tab) if tab else spreadsheet.get_worksheet(0)
    records = ws.get_all_records()

    db = get_db()
    imported = 0
    for record in records:
        raw_date = str(record.get("Timestamp", "")).strip()
        if not raw_date:
            continue
        try:
            dt = parser.parse(raw_date, dayfirst=True)
            date_str = dt.strftime("%Y-%m-%d")
            time_str = dt.strftime("%H:%M") if dt.hour or dt.minute else None
        except Exception:
            continue

        def _int(key):
            v = record.get(key, "")
            try:
                return int(str(v).strip()) if str(v).strip() else None
            except (ValueError, TypeError):
                return None

        def _float(key):
            v = record.get(key, "")
            try:
                return float(str(v).strip()) if str(v).strip() else None
            except (ValueError, TypeError):
                return None

        bristol_type = _int("Bristol Stool Type")
        urgency = _int("Urgency")
        quantity = _int("Quantity")
        effort = _int("Effort")
        gut_comfort = _int("Comfort")
        bloating = _int("Bloating")
        pain_level = _int("Pain/cramping")
        duration_mins = _int("Duration (mins)")
        weight_g = _float("Weight")
        notes = str(record.get("Notes", "")).strip() or None

        existing = db.execute(
            "SELECT id FROM symptom_log WHERE date=? AND time IS ?",
            (date_str, time_str)
        ).fetchone()

        if existing:
            db.execute("""
                UPDATE symptom_log SET bristol_type=?, urgency=?, quantity=?,
                effort=?, gut_comfort=?, bloating=?, pain_level=?, duration_mins=?,
                weight_g=?, notes=?
                WHERE id=?
            """, (bristol_type, urgency, quantity, effort, gut_comfort, bloating,
                  pain_level, duration_mins, weight_g, notes, existing["id"]))
        else:
            db.execute("""
                INSERT INTO symptom_log
                (date, time, bristol_type, urgency, quantity, effort, gut_comfort,
                 bloating, pain_level, duration_mins, weight_g, notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (date_str, time_str, bristol_type, urgency, quantity, effort,
                  gut_comfort, bloating, pain_level, duration_mins, weight_g, notes))
            imported += 1

    db.commit()
    return imported


JOINT_STAGING_HEADER = [
    "ID", "Date", "Merchant", "Amount", "Value Date",
    "Description", "Row Type", "Joint?", "Source",
]
JOINT_STAGING_JOINT_COL = JOINT_STAGING_HEADER.index("Joint?") + 1
JOINT_LEDGER_CSV = DATA_DIR / "joint_ledger.csv"
JOINT_LEDGER_FIELDS = [
    "date", "description", "who_paid",
    "angus_amount", "ebony_amount", "joint_amount", "category",
]


def ensure_joint_staging_tab(gc, gs: dict):
    sheet_id = gs.get("joint_sheet_id", "")
    if not sheet_id:
        raise ValueError("google_sheets.joint_sheet_id not set in config.json")
    tab_name = gs.get("joint_staging_tab", "Ebony_Transactions")
    spreadsheet = gc.open_by_key(sheet_id)
    try:
        ws = spreadsheet.worksheet(tab_name)
    except Exception:
        ws = spreadsheet.add_worksheet(
            title=tab_name,
            rows=1,
            cols=len(JOINT_STAGING_HEADER),
        )
        ws.append_row(JOINT_STAGING_HEADER)
    return ws


def _joint_col_letter(col_index_1based: int) -> str:
    letters = ""
    n = col_index_1based
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _format_new_joint_staging_rows(ws, first_row: int, last_row: int) -> None:
    if last_row < first_row:
        return
    import gspread  # noqa: PLC0415

    joint_col_letter = _joint_col_letter(JOINT_STAGING_JOINT_COL)
    ws.add_validation(
        f"{joint_col_letter}{first_row}:{joint_col_letter}{last_row}",
        gspread.utils.ValidationConditionType.boolean,
        [],
    )

    date_col_letter = _joint_col_letter(JOINT_STAGING_HEADER.index("Date") + 1)
    value_date_col_letter = _joint_col_letter(JOINT_STAGING_HEADER.index("Value Date") + 1)
    grid_range = {
        "sheetId": ws.id,
        "startRowIndex": first_row - 1,
        "endRowIndex": last_row,
        "startColumnIndex": 0,
        "endColumnIndex": len(JOINT_STAGING_HEADER),
    }
    weekend_formula = (
        f'=OR(WEEKDAY(IF(${value_date_col_letter}{first_row}<>"",'
        f'${value_date_col_letter}{first_row},${date_col_letter}{first_row}))=6,'
        f'WEEKDAY(IF(${value_date_col_letter}{first_row}<>"",'
        f'${value_date_col_letter}{first_row},${date_col_letter}{first_row}))=7,'
        f'WEEKDAY(IF(${value_date_col_letter}{first_row}<>"",'
        f'${value_date_col_letter}{first_row},${date_col_letter}{first_row}))=1)'
    )
    ws.spreadsheet.batch_update({
        "requests": [{
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [grid_range],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [{"userEnteredValue": weekend_formula}],
                        },
                        "format": {
                            "backgroundColor": {
                                "red": 1.0,
                                "green": 0.949,
                                "blue": 0.878,
                            },
                        },
                    },
                },
                "index": 0,
            },
        }],
    })


def push_ebony_to_joint_staging(gc, gs: dict) -> int:
    ws = ensure_joint_staging_tab(gc, gs)
    existing_values = ws.get_all_values()
    existing_ids = {
        row[0].strip()
        for row in existing_values[1:]
        if row and row[0].strip()
    }
    ebony_rows = read_csv(DATA_DIR / "transactions_ebony.csv")
    to_push = [
        row for row in ebony_rows
        if row.get("id") and row["id"] not in existing_ids
    ]
    if not to_push:
        return 0

    first_row = len(existing_values) + 1
    ws.append_rows(
        [
            [
                row["id"],
                row["date"],
                row.get("merchant", ""),
                row["amount"],
                row.get("value_date", ""),
                row["description"],
                row["row_type"],
                False,
                "ebony",
            ]
            for row in to_push
        ],
        value_input_option="USER_ENTERED",
    )
    _format_new_joint_staging_rows(
        ws,
        first_row,
        first_row + len(to_push) - 1,
    )
    return len(to_push)


def compute_50_50_split(amount: float) -> Tuple[float, float]:
    half = round(amount / 2, 2)
    return half, round(amount - half, 2)


def pull_confirmed_joint_rows_to_form(gc, gs: dict) -> int:
    staging_ws = ensure_joint_staging_tab(gc, gs)
    staging_rows = staging_ws.get_all_records()

    sheet_id = gs.get("joint_sheet_id", "")
    log_tab = gs.get("joint_log_tab", "Form")
    spreadsheet = gc.open_by_key(sheet_id)
    form_ws = spreadsheet.worksheet(log_tab)
    existing_form_rows = form_ws.get_all_values()[1:]
    existing_keys = {
        (str(row[1]).strip(), str(row[2]).strip())
        for row in existing_form_rows
        if len(row) > 2
    }

    new_rows = []
    for row in staging_rows:
        if str(row.get("Joint?", "")).strip().upper() != "TRUE":
            continue
        merchant = str(row.get("Merchant", "")).strip()
        description = merchant or str(row.get("Description", "")).strip()
        value_date = str(row.get("Value Date", "")).strip()
        date_val = value_date or str(row.get("Date", "")).strip()
        if (date_val, description) in existing_keys:
            continue
        try:
            amount = abs(float(row.get("Amount", 0)))
        except (TypeError, ValueError):
            continue

        angus_share, ebony_share = compute_50_50_split(amount)
        who_paid = (
            "Ebony"
            if str(row.get("Source", "")).strip().lower() == "ebony"
            else "Angus"
        )
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        new_rows.append([
            timestamp,
            date_val,
            description,
            who_paid,
            f"{angus_share:.2f}",
            f"{ebony_share:.2f}",
            "",
            "",
        ])
        existing_keys.add((date_val, description))

    if new_rows:
        form_ws.append_rows(new_rows, value_input_option="USER_ENTERED")
    return len(new_rows)


def clean_joint_money(value) -> str:
    raw = str(value or "").replace("$", "").replace(",", "").strip()
    if not raw:
        return "0.00"
    try:
        return f"{float(raw):.2f}"
    except ValueError:
        return "0.00"


def refresh_joint_ledger_cache(gc, gs: dict) -> int:
    sheet_id = gs.get("joint_sheet_id", "")
    log_tab = gs.get("joint_log_tab", "Form")
    spreadsheet = gc.open_by_key(sheet_id)
    form_ws = spreadsheet.worksheet(log_tab)
    records = form_ws.get_all_records()

    ledger_rows = []
    for record in records:
        date_val = str(record.get("Date", "")).strip()
        if not date_val:
            continue
        ledger_rows.append({
            "date": date_val,
            "description": str(record.get("Description", "")).strip(),
            "who_paid": str(record.get("Who paid?", "")).strip(),
            "angus_amount": clean_joint_money(record.get("Angus amount", "")),
            "ebony_amount": clean_joint_money(record.get("Ebony amount", "")),
            "joint_amount": clean_joint_money(record.get("Joint amount", "")),
            "category": str(record.get("Category", "")).strip(),
        })
    write_csv(JOINT_LEDGER_CSV, JOINT_LEDGER_FIELDS, ledger_rows)
    return len(ledger_rows)


def migrate_joint_ledger_cache_to_shared() -> Dict[str, int]:
    ledger_rows = read_csv(JOINT_LEDGER_CSV)
    allocations = load_allocations(DATA_DIR)
    existing_ids = {
        row.get("allocation_id", "")
        for row in allocations
        if row.get("allocation_id")
    }
    added = 0
    for row_number, row in enumerate(ledger_rows, start=1):
        allocation = allocation_from_legacy_row(row, row_number=row_number)
        if allocation["allocation_id"] in existing_ids:
            continue
        allocations.append(allocation)
        existing_ids.add(allocation["allocation_id"])
        added += 1

    allocations.sort(
        key=lambda row: (row.get("date", ""), row.get("description", "")),
        reverse=True,
    )
    save_allocations(DATA_DIR, allocations)
    return {
        "ledger_rows": len(ledger_rows),
        "legacy_allocations_added": added,
        "allocations_total": len(allocations),
    }


@app.get("/joint")
def joint_page():
    return send_file(BASE_DIR / "joint.html")


@app.post("/api/joint/sync")
def api_joint_sync():
    sheet_result = {
        "configured": False,
        "pushed_ebony": 0,
        "confirmed": 0,
        "ledger_rows": 0,
        "legacy_allocations_added": 0,
    }
    warnings = []

    try:
        config = load_config()
        gs_cfg = config.get("google_sheets", {})
        if gs_cfg.get("joint_sheet_id"):
            sheet_result["configured"] = True
            gc, gs = _get_gspread_client()
            sheet_result["pushed_ebony"] = push_ebony_to_joint_staging(gc, gs)
            sheet_result["confirmed"] = pull_confirmed_joint_rows_to_form(gc, gs)
            sheet_result["ledger_rows"] = refresh_joint_ledger_cache(gc, gs)
            migrated = migrate_joint_ledger_cache_to_shared()
            sheet_result.update(migrated)
    except Exception as exc:
        warnings.append(f"Google Sheets joint sync: {exc}")

    allocations = load_allocations(DATA_DIR)
    merged, up_stats = sync_up_allocations(
        read_all_up_transactions(),
        allocations,
    )
    save_allocations(DATA_DIR, merged)

    summary = shared_summary(
        merged,
        load_settlements(DATA_DIR),
    )
    return jsonify({
        "ok": True,
        "sheet": sheet_result,
        "up": up_stats,
        "summary": summary,
        "warnings": warnings,
    })


@app.get("/api/joint/transactions")
def api_joint_transactions():
    allocations = load_allocations(DATA_DIR)
    settlements = load_settlements(DATA_DIR)
    summary = shared_summary(allocations, settlements)

    transactions = []
    for row in allocations:
        if row.get("status") != "confirmed":
            continue
        transactions.append({
            "allocation_id": row.get("allocation_id", ""),
            "source_transaction_id": row.get("source_transaction_id", ""),
            "date": row.get("date", ""),
            "description": row.get("description", ""),
            "who_paid": row.get("payer", ""),
            "angus_amount": parse_float(row.get("angus_share")) or 0.0,
            "ebony_amount": parse_float(row.get("ebony_share")) or 0.0,
            "other_amount": parse_float(row.get("other_share")) or 0.0,
            "joint_amount": 0.0,
            "category": row.get("category", ""),
            "total": parse_float(row.get("gross_amount")) or 0.0,
            "allocation_type": row.get("allocation_type", ""),
            "event_key": row.get("event_key", ""),
            "status": row.get("status", ""),
        })

    if summary["ebony_owes_angus"] > 0.005:
        balance = {
            "direction": "ebony_owes_angus",
            "amount": summary["ebony_owes_angus"],
        }
    elif summary["angus_owes_ebony"] > 0.005:
        balance = {
            "direction": "angus_owes_ebony",
            "amount": summary["angus_owes_ebony"],
        }
    else:
        balance = {"direction": "even", "amount": 0.0}

    return jsonify({
        "ok": True,
        "transactions": transactions,
        "balance": balance,
        "review": summary["review"],
        "shared_summary": summary,
    })


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
