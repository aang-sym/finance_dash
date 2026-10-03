import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from shared_expenses import load_allocations, save_allocations, sync_up_allocations

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
    """Refresh the Up account catalogue and maintain named compatibility IDs."""
    account_ids = config.setdefault("account_ids", {})
    for key in ("spending", "savings", "grow", "two_up", "essentials"):
        account_ids.setdefault(key, "")

    payload = up_get(f"{API_BASE}/accounts", config["token"])
    accounts = []
    for account in payload.get("data", []):
        attrs = account.get("attributes", {})
        account_id = account.get("id", "")
        ownership = attrs.get("ownershipType", "")
        account_type = attrs.get("accountType", "")
        display_name_raw = attrs.get("displayName") or ""
        display_name = display_name_raw.lower()
        balance_value = (attrs.get("balance") or {}).get("value")

        accounts.append({
            "id": account_id,
            "display_name": display_name_raw,
            "account_type": account_type,
            "ownership_type": ownership,
            "balance": str(balance_value or ""),
        })

        if ownership == "INDIVIDUAL" and account_type == "TRANSACTIONAL":
            account_ids["spending"] = account_id
        elif ownership == "INDIVIDUAL" and account_type == "SAVER":
            if "essentials" in display_name:
                account_ids["essentials"] = account_id
            elif "savings" in display_name:
                account_ids["savings"] = account_id
            elif "grow" in display_name:
                account_ids["grow"] = account_id

    active_keys = ("spending", "savings", "grow", "essentials")
    missing = [key for key in active_keys if not account_ids.get(key)]
    if missing:
        raise RuntimeError(f"Unable to discover required account IDs from Up API. Missing: {', '.join(missing)}")

    # All currently visible Up accounts are stored so analytics can recognise
    # transfers to any owned saver (e.g. Ridley Bills or tipping accounts) as
    # internal rather than spending. The retired 2Up ID remains in account_ids
    # for historical classification even though Up no longer returns it.
    config["up_accounts"] = accounts
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


def transaction_row(transaction: Dict, account_id: str = "", account_name: str = "") -> Dict[str, str]:
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
        "account_id": account_id,
        "account_name": account_name,
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
        "account_id",
        "account_name",
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
        "account_id",
        "account_name",
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


def fetch_account_transactions(
    token: str,
    account_id: str,
    since: Optional[str],
    account_name: str = "",
) -> List[Dict[str, str]]:
    params = {
        "page[size]": str(PAGE_SIZE),
        "filter[since]": effective_since(since),
    }

    url = f"{API_BASE}/accounts/{account_id}/transactions"
    rows: List[Dict[str, str]] = []
    while url:
        payload = up_get(url, token, params=params)
        rows.extend(
            transaction_row(transaction, account_id=account_id, account_name=account_name)
            for transaction in payload.get("data", [])
        )
        url = payload.get("links", {}).get("next")
        params = None
    return rows


def read_csv_rows(csv_path: Path) -> List[Dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def seed_account_rows(csv_path: Path, account_id: str, account_name: str) -> List[Dict[str, str]]:
    rows = read_csv_rows(csv_path)
    for row in rows:
        row["account_id"] = row.get("account_id") or account_id
        row["account_name"] = row.get("account_name") or account_name
    return rows


def sync_transactions(full_refresh: bool = False) -> Dict[str, int]:
    config = discover_account_ids(load_config())
    account_ids = config["account_ids"]
    accounts = config.get("up_accounts", [])
    account_by_id = {a.get("id", ""): a for a in accounts if a.get("id")}
    last_sync_accounts = config.setdefault("last_sync_accounts", {})

    special_since = {
        account_ids.get("spending", ""): config.get("last_sync_spending"),
        account_ids.get("essentials", ""): config.get("last_sync_essentials"),
        account_ids.get("savings", ""): config.get("last_sync_savings"),
    }

    rows_by_account: Dict[str, List[Dict[str, str]]] = {}
    now_iso = datetime.now(timezone.utc).isoformat()

    for account in accounts:
        account_id = account.get("id", "")
        if not account_id:
            continue
        account_name = account.get("display_name", "")
        since = None if full_refresh else last_sync_accounts.get(account_id)
        if since is None and not full_refresh:
            since = special_since.get(account_id)
        rows_by_account[account_id] = fetch_account_transactions(
            config["token"],
            account_id,
            since,
            account_name=account_name,
        )
        last_sync_accounts[account_id] = now_iso

    writer = replace_rows if full_refresh else merge_rows

    spending_rows = rows_by_account.get(account_ids["spending"], [])
    essentials_rows = rows_by_account.get(account_ids["essentials"], [])
    savings_rows = rows_by_account.get(account_ids["savings"], [])

    spending_result = writer(DATA_DIR / "transactions_spending.csv", spending_rows)
    essentials_result = writer(DATA_DIR / "transactions_essentials.csv", essentials_rows)
    savings_result = writer(DATA_DIR / "transactions_savings.csv", savings_rows)

    # Unified transaction file powers analytics across every owned Up account.
    # On the first run, seed it from the existing specialised CSVs so historical
    # Spending/Savings/Essentials data is immediately available without a large
    # refetch. Other currently visible accounts are fetched from 2020 on first use.
    all_path = DATA_DIR / "transactions_all.csv"
    all_rows: List[Dict[str, str]] = []
    if not full_refresh and not all_path.exists():
        all_rows.extend(seed_account_rows(
            DATA_DIR / "transactions_spending.csv",
            account_ids.get("spending", ""),
            account_by_id.get(account_ids.get("spending", ""), {}).get("display_name", "Spending"),
        ))
        all_rows.extend(seed_account_rows(
            DATA_DIR / "transactions_savings.csv",
            account_ids.get("savings", ""),
            account_by_id.get(account_ids.get("savings", ""), {}).get("display_name", "Savings"),
        ))
        all_rows.extend(seed_account_rows(
            DATA_DIR / "transactions_essentials.csv",
            account_ids.get("essentials", ""),
            account_by_id.get(account_ids.get("essentials", ""), {}).get("display_name", "Essentials"),
        ))

    legacy_two_up_id = account_ids.get("two_up", "")
    if legacy_two_up_id:
        all_rows.extend(seed_account_rows(
            DATA_DIR / "transactions_2up.csv",
            legacy_two_up_id,
            "Legacy 2Up",
        ))

    for rows in rows_by_account.values():
        all_rows.extend(rows)

    all_result = writer(all_path, all_rows)

    config["last_sync_spending"] = now_iso
    config["last_sync_essentials"] = now_iso
    config["last_sync_savings"] = now_iso
    config["last_sync_accounts"] = last_sync_accounts
    save_config(config)

    shared_rows = load_allocations(DATA_DIR)
    shared_rows, shared_stats = sync_up_allocations(
        read_csv_rows(all_path),
        shared_rows,
    )
    save_allocations(DATA_DIR, shared_rows)

    return {
        "spending_added": spending_result["added"],
        "spending_updated": spending_result["updated"],
        "essentials_added": essentials_result["added"],
        "essentials_updated": essentials_result["updated"],
        "savings_added": savings_result["added"],
        "savings_updated": savings_result["updated"],
        "all_accounts_added": all_result["added"],
        "all_accounts_updated": all_result["updated"],
        "accounts_synced": len(rows_by_account),
        "shared_allocations_added": shared_stats["added"],
        "shared_allocations_review": shared_stats["review"],
        "full_refresh": full_refresh,
    }


if __name__ == "__main__":
    counts = sync_transactions()
    print(json.dumps(counts, indent=2))
