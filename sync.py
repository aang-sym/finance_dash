import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = BASE_DIR / "config.json"
API_BASE = "https://api.up.com.au/api/v1"
PAGE_SIZE = 100
MIN_SYNC_SINCE = "2020-01-01T00:00:00+00:00"


def _read_json(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def load_config() -> Dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing config file at {CONFIG_PATH}")
    config = _read_json(CONFIG_PATH)
    if not config.get("token"):
        raise ValueError('config.json is missing "token". Paste your Up Personal Access Token into config.json.')
    return config


def save_config(config: Dict) -> None:
    _write_json(CONFIG_PATH, config)


def up_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def up_get(url: str, token: str, params: Optional[Dict[str, str]] = None) -> Dict:
    response = requests.get(url, headers=up_headers(token), params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def effective_since(since: Optional[str]) -> str:
    if not since:
        return MIN_SYNC_SINCE
    return max(since, MIN_SYNC_SINCE)


def discover_account_ids(config: Dict) -> Dict:
    account_ids = config.setdefault(
        "account_ids",
        {"spending": "", "savings": "", "grow": "", "two_up": ""},
    )
    if all(account_ids.get(key) for key in ("spending", "savings", "grow", "two_up")):
        return config

    payload = up_get(f"{API_BASE}/accounts", config["token"])
    for account in payload.get("data", []):
        attrs = account.get("attributes", {})
        account_id = account.get("id", "")
        ownership = attrs.get("ownershipType", "")
        account_type = attrs.get("accountType", "")
        display_name = (attrs.get("displayName") or "").lower()

        if ownership == "JOINT":
            account_ids["two_up"] = account_id
        elif ownership == "INDIVIDUAL" and account_type == "TRANSACTIONAL":
            account_ids["spending"] = account_id
        elif ownership == "INDIVIDUAL" and account_type == "SAVER":
            if "savings" in display_name:
                account_ids["savings"] = account_id
            elif "grow" in display_name:
                account_ids["grow"] = account_id

    missing = [key for key, value in account_ids.items() if not value]
    if missing:
        raise RuntimeError(f"Unable to discover all account IDs from Up API. Missing: {', '.join(missing)}")

    save_config(config)
    return config


def parse_amount(transaction: Dict) -> float:
    amount = transaction.get("attributes", {}).get("amount", {}).get("value")
    if amount in (None, ""):
        return 0.0
    return float(amount)


def extract_tags(transaction: Dict) -> str:
    tag_data = (
        transaction.get("relationships", {})
        .get("tags", {})
        .get("data", [])
    )
    return ",".join(tag.get("id", "") for tag in tag_data if tag.get("id"))


def extract_transfer_account_id(transaction: Dict) -> str:
    transfer_data = (
        transaction.get("relationships", {})
        .get("transferAccount", {})
        .get("data")
    )
    if not transfer_data:
        return ""
    return transfer_data.get("id", "")


def transaction_row(transaction: Dict) -> Dict[str, str]:
    attrs = transaction.get("attributes", {})
    raw_text = " ".join(
        filter(
            None,
            [
                attrs.get("description", ""),
                attrs.get("message", ""),
                attrs.get("rawText", ""),
            ],
        )
    ).strip()
    return {
        "id": transaction.get("id", ""),
        "created_at": attrs.get("createdAt", ""),
        "settled_at": attrs.get("settledAt", "") or "",
        "description": attrs.get("description", "") or "",
        "message": attrs.get("message", "") or "",
        "amount": f"{parse_amount(transaction):.2f}",
        "status": attrs.get("status", "") or "",
        "category": (transaction.get("relationships", {}).get("category", {}).get("data") or {}).get("id", ""),
        "parent_category": (transaction.get("relationships", {}).get("parentCategory", {}).get("data") or {}).get("id", ""),
        "transaction_type": attrs.get("transactionType", "") or "",
        "tags": extract_tags(transaction),
        "transfer_account_id": extract_transfer_account_id(transaction),
        "raw_text": raw_text,
    }


def read_existing_rows(csv_path: Path) -> Dict[str, Dict[str, str]]:
    if not csv_path.exists():
        return {}
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return {row["id"]: row for row in reader if row.get("id")}


def merge_rows(csv_path: Path, rows: List[Dict[str, str]]) -> Dict[str, int]:
    fieldnames = [
        "id",
        "created_at",
        "settled_at",
        "description",
        "message",
        "amount",
        "status",
        "category",
        "parent_category",
        "tags",
        "transfer_account_id",
        "transaction_type",
        "raw_text",
    ]

    existing_rows = read_existing_rows(csv_path)
    added = 0
    updated = 0
    for row in rows:
        row_id = row["id"]
        if row_id in existing_rows:
            if existing_rows[row_id] != row:
                updated += 1
        else:
            added += 1
        existing_rows[row_id] = row

    merged_rows = sorted(
        existing_rows.values(),
        key=lambda row: row.get("created_at", ""),
        reverse=True,
    )

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged_rows)
    return {"added": added, "updated": updated}


def replace_rows(csv_path: Path, rows: List[Dict[str, str]]) -> Dict[str, int]:
    fieldnames = [
        "id",
        "created_at",
        "settled_at",
        "description",
        "message",
        "amount",
        "status",
        "category",
        "parent_category",
        "tags",
        "transfer_account_id",
        "transaction_type",
        "raw_text",
    ]
    existing_count = len(read_existing_rows(csv_path))
    unique_rows = {row["id"]: row for row in rows if row.get("id")}
    snapshot_rows = sorted(
        unique_rows.values(),
        key=lambda row: row.get("created_at", ""),
        reverse=True,
    )
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(snapshot_rows)
    return {
        "added": max(len(snapshot_rows) - existing_count, 0),
        "updated": min(existing_count, len(snapshot_rows)),
    }


def fetch_account_transactions(token: str, account_id: str, since: Optional[str]) -> List[Dict[str, str]]:
    params = {
        "page[size]": str(PAGE_SIZE),
        "filter[since]": effective_since(since),
    }

    url = f"{API_BASE}/accounts/{account_id}/transactions"
    rows: List[Dict[str, str]] = []
    while url:
        payload = up_get(url, token, params=params)
        rows.extend(transaction_row(transaction) for transaction in payload.get("data", []))
        url = payload.get("links", {}).get("next")
        params = None
    return rows


def sync_transactions(full_refresh: bool = False) -> Dict[str, int]:
    config = discover_account_ids(load_config())
    account_ids = config["account_ids"]

    spending_rows = fetch_account_transactions(
        config["token"],
        account_ids["spending"],
        None if full_refresh else config.get("last_sync_spending"),
    )
    two_up_rows = fetch_account_transactions(
        config["token"],
        account_ids["two_up"],
        None if full_refresh else config.get("last_sync_2up"),
    )
    savings_rows = fetch_account_transactions(
        config["token"],
        account_ids["savings"],
        None if full_refresh else config.get("last_sync_savings"),
    )

    writer = replace_rows if full_refresh else merge_rows
    spending_result = writer(DATA_DIR / "transactions_spending.csv", spending_rows)
    two_up_result = writer(DATA_DIR / "transactions_2up.csv", two_up_rows)
    savings_result = writer(DATA_DIR / "transactions_savings.csv", savings_rows)

    now_iso = datetime.now(timezone.utc).isoformat()
    config["last_sync_spending"] = now_iso
    config["last_sync_2up"] = now_iso
    config["last_sync_savings"] = now_iso
    save_config(config)

    return {
        "spending_added": spending_result["added"],
        "spending_updated": spending_result["updated"],
        "two_up_added": two_up_result["added"],
        "two_up_updated": two_up_result["updated"],
        "savings_added": savings_result["added"],
        "savings_updated": savings_result["updated"],
        "full_refresh": full_refresh,
    }


if __name__ == "__main__":
    counts = sync_transactions()
    print(json.dumps(counts, indent=2))
