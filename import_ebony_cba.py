import csv
import hashlib
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
EBONY_CSV_FIELDS = ["id", "date", "amount", "description", "row_type", "merchant", "value_date", "pushed"]

TRANSFER_RE = re.compile(r"\btransfer\b", re.IGNORECASE)
DIRECT_DEBIT_RE = re.compile(r"\bdirect debit\b", re.IGNORECASE)
CARD_RE = re.compile(r"\bAUS Card\b", re.IGNORECASE)
VALUE_DATE_RE = re.compile(r"Value Date:\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
# Everything up to "AUS" (plus an optional state code right before it, e.g.
# "VI") is kept as the merchant; CBA doesn't delimit merchant from location
# within that leading portion, so location words are kept in rather than
# guessed at and risk truncating real multi-word business names.
CARD_SUFFIX_RE = re.compile(r"\s+(?:VIC|NSW|QLD|SA|WA|TAS|NT|ACT|VI)?\s*AUS Card\s+xx\d+\s+Value Date:\s*\d{2}/\d{2}/\d{4}\s*$", re.IGNORECASE)
PAYPAL_RE = re.compile(r"^PAYPAL\s*\*\s*(.+)$", re.IGNORECASE)


def classify_row_type(description: str) -> str:
    if TRANSFER_RE.search(description):
        return "transfer"
    if DIRECT_DEBIT_RE.search(description):
        return "direct_debit"
    if CARD_RE.search(description):
        return "card_purchase"
    return "other"


def extract_value_date(description: str) -> Optional[str]:
    match = VALUE_DATE_RE.search(description)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")


def _sentence_case(text: str) -> str:
    words = text.split(" ")
    return " ".join(w.capitalize() if w.isupper() or w.islower() else w for w in words)


def extract_merchant(description: str) -> str:
    core = CARD_SUFFIX_RE.sub("", description).strip()

    paypal_match = PAYPAL_RE.match(core)
    if paypal_match:
        payee = paypal_match.group(1).strip()
        payee = re.sub(r"\s*\d{6,}.*$", "", payee).strip()
        payee = re.sub(r"\s+(?:AU|GBR|USA|CA)\s*$", "", payee, flags=re.IGNORECASE).strip()
        return "Paypal - " + _sentence_case(payee)

    return _sentence_case(core)


def row_id(date_iso: str, amount: float, description: str) -> str:
    payload = f"{date_iso}|{amount:.2f}|{description}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()


def parse_cba_row(raw_row: List[str]) -> Optional[Dict[str, object]]:
    if len(raw_row) < 4:
        return None
    date_str, amount_str, description, _balance = raw_row[0], raw_row[1], raw_row[2], raw_row[3]
    try:
        date_iso = datetime.strptime(date_str.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None
    try:
        amount = float(amount_str.strip())
    except ValueError:
        return None
    description = description.strip()
    row_type = classify_row_type(description)
    merchant = extract_merchant(description) if row_type == "card_purchase" else ""
    value_date = extract_value_date(description) if row_type == "card_purchase" else ""
    return {
        "id": row_id(date_iso, amount, description),
        "date": date_iso,
        "amount": amount,
        "description": description,
        "row_type": row_type,
        "merchant": merchant,
        "value_date": value_date or "",
        "pushed": "",
    }


def read_existing_ebony_rows(csv_path: Path) -> Dict[str, Dict[str, str]]:
    if not csv_path.exists():
        return {}
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return {row["id"]: row for row in reader if row.get("id")}


def import_cba_csv(csv_path: Path) -> Dict[str, int]:
    existing = read_existing_ebony_rows(DATA_DIR / "transactions_ebony.csv")
    added = 0
    skipped = 0
    total_rows = 0
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for raw_row in reader:
            if not raw_row:
                continue
            total_rows += 1
            parsed = parse_cba_row(raw_row)
            if parsed is None:
                skipped += 1
                continue
            row_key = parsed["id"]
            if row_key in existing:
                continue
            existing[row_key] = {**parsed, "amount": f"{parsed['amount']:.2f}"}
            added += 1

    merged_rows = sorted(existing.values(), key=lambda r: r.get("date", ""), reverse=True)
    with (DATA_DIR / "transactions_ebony.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EBONY_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(merged_rows)

    return {"added": added, "updated": 0, "total_rows": total_rows, "skipped": skipped}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
    else:
        candidates = sorted(DATA_DIR.glob("ebony_cba_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            print("No data/ebony_cba_*.csv file found. Pass a path explicitly.")
            sys.exit(1)
        target = candidates[0]
    result = import_cba_csv(target)
    print(f"Imported from {target}: {result}")
