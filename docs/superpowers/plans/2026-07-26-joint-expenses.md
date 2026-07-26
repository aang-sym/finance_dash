# Joint Expenses with Ebony — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate tracking of joint (Angus + Ebony) purchases: parse Ebony's CBA CSV export, stage her full transaction history plus Angus's Up-tagged transactions in the shared "AJ + EJ Expenses" Google Sheet, let each person flag what's joint, then push confirmed rows into the sheet's existing `Form` ledger tab and surface a running balance on a new `/joint` dashboard page.

**Architecture:** A new standalone parser module (`import_ebony_cba.py`) turns Ebony's headerless CBA CSV into a local CSV cache. `server.py` gains a write-capable gspread helper and two functions — push-to-staging and pull-confirmed — wired to one `POST /api/joint/sync` endpoint, triggered by a button on a new `joint.html` page (styled like the existing `bills.html`/`spending.html`). The Google Sheet's `Form` tab remains the single source of truth for the ledger; `Calc` already auto-updates via its existing `FILTER(Form!A2:H, ...)` array formula, confirmed live on the real sheet — no changes needed there.

**Tech Stack:** Python 3.14, Flask, gspread + google-auth (already in `requirements.txt`), csv/hashlib stdlib, vanilla JS/CSS (no framework) matching existing pages.

## Global Constraints

- Service account `aang-sym@finance-dash-496812.iam.gserviceaccount.com` is already Editor on sheet `1zXUBHExmiZqUxc5v54wbN0njO_1pqSa5QvrPlXoM0h4` ("AJ + EJ Expenses") — confirmed 2026-07-26. No sharing changes needed.
- Sheet's current tabs (confirmed live via gspread): `Form` (id 1604834100, 157 rows x 14 cols), `Calc` (id 0, formula-driven off `Form`), `Sheet2` (id 1989843406), `Sheet2 (2)` (id 1902426717). A new tab `Ebony_Transactions` will be created by code on first run (via `gc.open_by_key(...).add_worksheet(...)`), not manually.
- `Form` header row (confirmed): `Timestamp, Date, Description, Who paid?, Angus amount, Ebony amount, Joint amount, Category, Column 1`. Appends must supply exactly these 8 data columns (leave `Column 1` blank — it's unused scratch space in existing rows).
- `Calc`'s row 2 uses `=IFERROR(FILTER(Form!A2:H, Form!A2:A<>""),"")` — this auto-expands as `Form` grows. **Never write directly to `Calc`.**
- No CBA API integration — CSV import only, manual export by Ebony.
- Never write to `Form` except via the pull-confirmed step, and never overwrite an existing `Form` row — appends only.
- Sync is manually triggered by a button on `/joint` (confirmed by user) — no cron/background job.
- Match existing code conventions: `read_csv`/`write_csv` helpers in `server.py`, `jsonify({"ok": True/False, ...})` response shape, `fetchJson` JS helper, JetBrains Mono terminal theme (`--green`/`--dim`/`--panel` CSS vars), nav bar pattern shared across all pages.

---

## File Structure

- Create: `import_ebony_cba.py` — CBA CSV parser + local CSV merge, standalone script (run via `python3 import_ebony_cba.py [path]`), importable from `server.py`.
- Create: `data/transactions_ebony.csv` — parsed/merged output of the importer (gitignored, like other `data/transactions_*.csv`).
- Create: `data/joint_pushed.csv` — local state tracking which row ids have already been pushed to the sheet's staging tab (prevents duplicate staging rows on repeat syncs).
- Create: `data/joint_ledger.csv` — local mirror of `Form`'s contents after each sync, read by the dashboard API.
- Create: `joint.html` — new dashboard page (balance banner, transaction table, sync button), following `bills.html`'s structure.
- Modify: `server.py` — add write-capable gspread helper, push/pull functions, `/joint` page route, `/api/joint/*` routes; add nav link to all existing `*.html` pages.
- Modify: `config.json` / `config.example.json` — add `joint_sheet_id`, `joint_staging_tab`, `joint_log_tab` under `google_sheets`.
- Modify: `.gitignore` — add the three new `data/*.csv` files.

---

### Task 1: CBA CSV importer

**Files:**
- Create: `import_ebony_cba.py`
- Test: `test_import_ebony_cba.py` (repo root, matches no existing test convention in this repo — confirmed no `tests/` dir exists; colocate at root like `sync.py`/`server.py`)

**Interfaces:**
- Produces: `parse_cba_row(raw_row: list[str]) -> dict | None` — returns `None` for unparseable rows.
- Produces: `row_id(date_iso: str, amount: float, description: str) -> str` — sha1 hex digest.
- Produces: `classify_row_type(description: str) -> str` — one of `"transfer"`, `"direct_debit"`, `"card_purchase"`, `"other"`.
- Produces: `import_cba_csv(csv_path: Path) -> dict` — returns `{"added": int, "updated": int, "total_rows": int, "skipped": int}`, merges into `data/transactions_ebony.csv`.
- Produces: `EBONY_CSV_FIELDS = ["id", "date", "amount", "description", "row_type", "pushed"]` module-level constant.
- Consumes: nothing (standalone).

- [ ] **Step 1: Write failing tests for row parsing**

```python
# test_import_ebony_cba.py
from pathlib import Path
from import_ebony_cba import parse_cba_row, row_id, classify_row_type

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/anguss/dev/finance_dash && venv/bin/python3 -m pytest test_import_ebony_cba.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'import_ebony_cba'`

- [ ] **Step 3: Implement the parser**

```python
# import_ebony_cba.py
import csv
import hashlib
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
EBONY_CSV_FIELDS = ["id", "date", "amount", "description", "row_type", "pushed"]

TRANSFER_RE = re.compile(r"\btransfer\b", re.IGNORECASE)
DIRECT_DEBIT_RE = re.compile(r"\bdirect debit\b", re.IGNORECASE)
CARD_RE = re.compile(r"\bAUS Card\b", re.IGNORECASE)


def classify_row_type(description: str) -> str:
    if TRANSFER_RE.search(description):
        return "transfer"
    if DIRECT_DEBIT_RE.search(description):
        return "direct_debit"
    if CARD_RE.search(description):
        return "card_purchase"
    return "other"


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
    return {
        "id": row_id(date_iso, amount, description),
        "date": date_iso,
        "amount": amount,
        "description": description,
        "row_type": classify_row_type(description),
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/anguss/dev/finance_dash && venv/bin/python3 -m pytest test_import_ebony_cba.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the importer against the real sample file and verify output**

Run: `cd /Users/anguss/dev/finance_dash && venv/bin/python3 import_ebony_cba.py data/ebony_cba_feb_jul_26.csv`
Expected: `Imported from data/ebony_cba_feb_jul_26.csv: {'added': 343, 'updated': 0, 'total_rows': 343, 'skipped': 0}` (343 confirmed via `wc -l` on the sample file; adjust if the file has changed since spec-writing)

Then inspect: `head -3 data/transactions_ebony.csv` — expect header `id,date,amount,description,row_type,pushed` followed by rows sorted newest-first.

- [ ] **Step 6: Add new data files to .gitignore**

Add to `.gitignore` (after the existing `data/transactions_2up.csv` line):
```
data/transactions_ebony.csv
data/joint_pushed.csv
data/joint_ledger.csv
```

- [ ] **Step 7: Commit**

```bash
cd /Users/anguss/dev/finance_dash
git add import_ebony_cba.py test_import_ebony_cba.py .gitignore
git commit -m "feat(joint): add CBA CSV importer for Ebony's transactions"
```

---

### Task 2: Write-capable gspread helper + config

**Files:**
- Modify: `server.py:2894-2907` (the `_get_gspread_client` function)
- Modify: `config.json`
- Modify: `config.example.json`

**Interfaces:**
- Consumes: `load_config()` (existing, `server.py`), `BASE_DIR` (existing module-level constant).
- Produces: `_get_gspread_client()` now returns a client authorized with **both** read and write scopes — same signature/return shape as before (`Tuple[gspread.Client, dict]`), so every existing caller (`import_networth_from_sheets`, `import_bills_from_sheets`, `import_gut_from_sheets`) keeps working unchanged.

- [ ] **Step 1: Change the scopes list**

In `server.py`, locate:
```python
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
```
(inside `_get_gspread_client`, around line 2905)

Replace with:
```python
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
```

- [ ] **Step 2: Verify existing read-only Sheets features still work**

Run: `cd /Users/anguss/dev/finance_dash && venv/bin/python3 -c "
from server import _get_gspread_client
gc, gs = _get_gspread_client()
sh = gc.open_by_key('1gU1yIdPwbkcVfukcEyk14tfTtmZdONB0OKV0t2gAXHc')
print('OK, sheet title:', sh.title)
"`

Expected: prints `OK, sheet title: <networth sheet's actual title>` with no exception — confirms the broader scope doesn't break existing read access (the `networth_sheet_id` value is read from `config.json`; if it's empty, skip this check and just confirm no exception is raised by `_get_gspread_client()` alone).

- [ ] **Step 3: Add joint config keys**

In `config.json`, inside the `"google_sheets"` object, add:
```json
    "joint_sheet_id": "1zXUBHExmiZqUxc5v54wbN0njO_1pqSa5QvrPlXoM0h4",
    "joint_staging_tab": "Ebony_Transactions",
    "joint_log_tab": "Form",
```

In `config.example.json`, inside the `"google_sheets"` object, add (same keys, blank sheet id per that file's existing convention of blank example values):
```json
    "joint_sheet_id": "",
    "joint_staging_tab": "Ebony_Transactions",
    "joint_log_tab": "Form",
```

- [ ] **Step 4: Commit**

```bash
cd /Users/anguss/dev/finance_dash
git add server.py config.json config.example.json
git commit -m "feat(joint): switch gspread to read-write scope, add joint sheet config"
```

---

### Task 3: Push-to-staging function

**Files:**
- Modify: `server.py` (add new functions after `import_gut_from_sheets`, before its route — find via `grep -n "def import_gut_from_sheets" server.py`)
- Test: `test_joint_sync.py` (repo root)

**Interfaces:**
- Consumes: `_get_gspread_client()` (Task 2), `read_csv`/`write_csv` (existing `server.py` helpers), `DATA_DIR` (existing constant), `import_ebony_cba.EBONY_CSV_FIELDS` (Task 1).
- Produces: `JOINT_PUSHED_CSV = DATA_DIR / "joint_pushed.csv"` module constant.
- Produces: `get_angus_joint_candidates() -> List[Dict[str, str]]` — rows from `transactions_spending.csv` + `transactions_2up.csv` where `"joint"` is in the comma-split `tags` field, each dict has keys `id, date, description, amount` (amount as string, sign as stored — spending amounts are negative for debits per the existing CSV format).
- Produces: `push_ebony_to_staging(gc, gs: dict) -> int` — returns count of newly staged rows.
- Produces: `push_angus_to_staging(gc, gs: dict) -> int` — returns count of newly staged rows.
- Produces: `ensure_staging_tab(gc, gs: dict)` — creates `Ebony_Transactions` worksheet with header row if it doesn't already exist; idempotent.

- [ ] **Step 1: Write failing test for Angus candidate filtering**

```python
# test_joint_sync.py
import csv
from pathlib import Path

import pytest

from server import get_angus_joint_candidates, DATA_DIR


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("server.DATA_DIR", tmp_path)
    spending_fields = [
        "id", "created_at", "settled_at", "description", "message", "amount",
        "status", "category", "parent_category", "tags", "transfer_account_id",
        "transaction_type", "raw_text",
    ]
    rows = [
        {"id": "tx1", "created_at": "2026-07-01T10:00:00+10:00", "settled_at": "", "description": "Woolworths", "message": "", "amount": "-25.00", "status": "SETTLED", "category": "groceries", "parent_category": "home", "tags": "joint", "transfer_account_id": "", "transaction_type": "Purchase", "raw_text": ""},
        {"id": "tx2", "created_at": "2026-07-02T10:00:00+10:00", "settled_at": "", "description": "Rent", "message": "", "amount": "-100.00", "status": "SETTLED", "category": "rent", "parent_category": "home", "tags": "rent-jul-2026", "transfer_account_id": "", "transaction_type": "Purchase", "raw_text": ""},
        {"id": "tx3", "created_at": "2026-07-03T10:00:00+10:00", "settled_at": "", "description": "Dinner", "message": "", "amount": "-50.00", "status": "SETTLED", "category": "restaurants", "parent_category": "good-life", "tags": "joint,jarrod", "transfer_account_id": "", "transaction_type": "Purchase", "raw_text": ""},
    ]
    with (tmp_path / "transactions_spending.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=spending_fields)
        writer.writeheader()
        writer.writerows(rows)
    with (tmp_path / "transactions_2up.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=spending_fields)
        writer.writeheader()
    return tmp_path


def test_get_angus_joint_candidates_filters_by_tag(tmp_data_dir):
    candidates = get_angus_joint_candidates()
    ids = {c["id"] for c in candidates}
    assert ids == {"tx1", "tx3"}


def test_get_angus_joint_candidates_extracts_fields(tmp_data_dir):
    candidates = get_angus_joint_candidates()
    tx1 = next(c for c in candidates if c["id"] == "tx1")
    assert tx1["date"] == "2026-07-01"
    assert tx1["description"] == "Woolworths"
    assert tx1["amount"] == "-25.00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/anguss/dev/finance_dash && venv/bin/python3 -m pytest test_joint_sync.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_angus_joint_candidates'`

- [ ] **Step 3: Implement `get_angus_joint_candidates` and staging helpers**

Add to `server.py` after the `import_gut_from_sheets` function block (find its end via `grep -n "^def \|^@app" server.py` around that region):

```python
JOINT_PUSHED_CSV = DATA_DIR / "joint_pushed.csv"
JOINT_PUSHED_FIELDS = ["id", "source"]


def get_angus_joint_candidates() -> List[Dict[str, str]]:
    candidates = []
    for filename in ("transactions_spending.csv", "transactions_2up.csv"):
        for row in read_csv(DATA_DIR / filename):
            tags = {t.strip() for t in (row.get("tags") or "").split(",") if t.strip()}
            if "joint" not in tags:
                continue
            created_at = row.get("created_at", "")
            date_str = created_at[:10] if created_at else ""
            candidates.append({
                "id": row["id"],
                "date": date_str,
                "description": row.get("description", "") or row.get("raw_text", ""),
                "amount": row.get("amount", "0.00"),
            })
    return candidates


def read_joint_pushed_ids() -> set:
    return {row["id"] for row in read_csv(JOINT_PUSHED_CSV) if row.get("id")}


def mark_joint_pushed(ids_with_source: List[Dict[str, str]]) -> None:
    existing = read_csv(JOINT_PUSHED_CSV)
    existing_ids = {row["id"] for row in existing}
    for entry in ids_with_source:
        if entry["id"] not in existing_ids:
            existing.append(entry)
    write_csv(JOINT_PUSHED_CSV, JOINT_PUSHED_FIELDS, existing)


def ensure_staging_tab(gc, gs: dict):
    sheet_id = gs.get("joint_sheet_id", "")
    if not sheet_id:
        raise ValueError("google_sheets.joint_sheet_id not set in config.json")
    tab_name = gs.get("joint_staging_tab", "Ebony_Transactions")
    spreadsheet = gc.open_by_key(sheet_id)
    try:
        ws = spreadsheet.worksheet(tab_name)
    except Exception:
        ws = spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=7)
        ws.append_row(["ID", "Date", "Amount", "Description", "Row Type", "Joint?", "Source"])
    return ws


def push_ebony_to_staging(gc, gs: dict) -> int:
    ws = ensure_staging_tab(gc, gs)
    pushed_ids = read_joint_pushed_ids()
    ebony_rows = read_csv(DATA_DIR / "transactions_ebony.csv")
    to_push = [row for row in ebony_rows if row["id"] not in pushed_ids]
    if not to_push:
        return 0
    ws.append_rows(
        [[row["id"], row["date"], row["amount"], row["description"], row["row_type"], "", "ebony"] for row in to_push],
        value_input_option="USER_ENTERED",
    )
    mark_joint_pushed([{"id": row["id"], "source": "ebony"} for row in to_push])
    return len(to_push)


def push_angus_to_staging(gc, gs: dict) -> int:
    ws = ensure_staging_tab(gc, gs)
    pushed_ids = read_joint_pushed_ids()
    candidates = [c for c in get_angus_joint_candidates() if c["id"] not in pushed_ids]
    if not candidates:
        return 0
    ws.append_rows(
        [[c["id"], c["date"], c["amount"], c["description"], "up_tagged", "x", "angus"] for c in candidates],
        value_input_option="USER_ENTERED",
    )
    mark_joint_pushed([{"id": c["id"], "source": "angus"} for c in candidates])
    return len(candidates)
```

Add `JOINT_PUSHED_FIELDS` uses `List`, `Dict` — already imported at top of `server.py` (`from typing import Dict, List, Optional, Tuple`), no new import needed.

Angus's rows are pre-ticked (`"x"` in the Joint? column) since he already explicitly tagged them in Up — no separate review step for his own transactions, matching the spec's design (only Ebony's *unfiltered* dump needs her review).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/anguss/dev/finance_dash && venv/bin/python3 -m pytest test_joint_sync.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/anguss/dev/finance_dash
git add server.py test_joint_sync.py
git commit -m "feat(joint): add push-to-staging for Angus and Ebony transactions"
```

---

### Task 4: Pull-confirmed function

**Files:**
- Modify: `server.py` (add after Task 3's functions)
- Test: `test_joint_sync.py` (append to existing file from Task 3)

**Interfaces:**
- Consumes: `ensure_staging_tab`, `_get_gspread_client` (Task 3/2), `JOINT_LEDGER_CSV` (new constant this task defines).
- Produces: `JOINT_LEDGER_CSV = DATA_DIR / "joint_ledger.csv"` module constant.
- Produces: `JOINT_LEDGER_FIELDS = ["date", "description", "who_paid", "angus_amount", "ebony_amount", "joint_amount", "category"]`.
- Produces: `pull_confirmed_to_form(gc, gs: dict) -> int` — returns count of rows newly appended to `Form`.
- Produces: `refresh_joint_ledger_cache(gc, gs: dict) -> int` — re-reads `Form` fully, writes `data/joint_ledger.csv`, returns row count.

- [ ] **Step 1: Write failing test for the split calculation helper**

Append to `test_joint_sync.py`:

```python
from server import compute_50_50_split


def test_compute_50_50_split_even():
    angus, ebony = compute_50_50_split(50.00)
    assert angus == 25.00
    assert ebony == 25.00


def test_compute_50_50_split_odd_cents():
    angus, ebony = compute_50_50_split(45.42)
    assert round(angus + ebony, 2) == 45.42
    assert angus == 22.71
    assert ebony == 22.71
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/anguss/dev/finance_dash && venv/bin/python3 -m pytest test_joint_sync.py::test_compute_50_50_split_even -v`
Expected: FAIL with `ImportError: cannot import name 'compute_50_50_split'`

- [ ] **Step 3: Implement pull-confirmed and split helper**

Add to `server.py` after Task 3's functions:

```python
JOINT_LEDGER_CSV = DATA_DIR / "joint_ledger.csv"
JOINT_LEDGER_FIELDS = ["date", "description", "who_paid", "angus_amount", "ebony_amount", "joint_amount", "category"]


def compute_50_50_split(amount: float) -> Tuple[float, float]:
    half = round(amount / 2, 2)
    other_half = round(amount - half, 2)
    return half, other_half


def pull_confirmed_to_form(gc, gs: dict) -> int:
    staging_ws = ensure_staging_tab(gc, gs)
    staging_rows = staging_ws.get_all_records()

    sheet_id = gs.get("joint_sheet_id", "")
    log_tab = gs.get("joint_log_tab", "Form")
    spreadsheet = gc.open_by_key(sheet_id)
    form_ws = spreadsheet.worksheet(log_tab)
    existing_form_rows = form_ws.get_all_values()[1:]
    existing_descriptions_dates = {(r[1], r[2]) for r in existing_form_rows if len(r) > 2}

    new_rows = []
    for row in staging_rows:
        joint_flag = str(row.get("Joint?", "")).strip().lower()
        if joint_flag not in {"x", "true", "yes", "1"}:
            continue
        date_val = str(row.get("Date", "")).strip()
        description = str(row.get("Description", "")).strip()
        if (date_val, description) in existing_descriptions_dates:
            continue
        try:
            amount = abs(float(row.get("Amount", 0)))
        except (TypeError, ValueError):
            continue
        angus_share, ebony_share = compute_50_50_split(amount)
        who_paid = "Ebony" if str(row.get("Source", "")).strip().lower() == "ebony" else "Angus"
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        new_rows.append([timestamp, date_val, description, who_paid, f"{angus_share:.2f}", f"{ebony_share:.2f}", "", ""])

    if new_rows:
        form_ws.append_rows(new_rows, value_input_option="USER_ENTERED")
    return len(new_rows)


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
            "angus_amount": str(record.get("Angus amount", "") or "0"),
            "ebony_amount": str(record.get("Ebony amount", "") or "0"),
            "joint_amount": str(record.get("Joint amount", "") or "0"),
            "category": str(record.get("Category", "")).strip(),
        })
    write_csv(JOINT_LEDGER_CSV, JOINT_LEDGER_FIELDS, ledger_rows)
    return len(ledger_rows)
```

`datetime` is already imported at the top of `server.py` (`from datetime import date, datetime, timedelta`) — no new import needed.

De-duplication against `Form` uses `(date, description)` pairs rather than a stored row id, since `Form`'s existing 157 historical rows have no id column to match against — this is a pragmatic choice given the sheet's current shape; note it as a known limitation (a genuinely repeated date+description pair, e.g. two separate "Sushi Hub" purchases on the same day, would be treated as a duplicate and skipped on the second sync). Flag this to the user after implementation; do not silently under-report it.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/anguss/dev/finance_dash && venv/bin/python3 -m pytest test_joint_sync.py -v`
Expected: PASS (4 tests total: 2 from Task 3, 2 new)

- [ ] **Step 5: Commit**

```bash
cd /Users/anguss/dev/finance_dash
git add server.py test_joint_sync.py
git commit -m "feat(joint): add pull-confirmed step appending to Form and ledger cache"
```

---

### Task 5: API routes

**Files:**
- Modify: `server.py` (add routes near the other Sheets routes, after `api_bills_sync_sheets` — `grep -n "def api_bills_sync_sheets" server.py`)

**Interfaces:**
- Consumes: `push_ebony_to_staging`, `push_angus_to_staging`, `pull_confirmed_to_form`, `refresh_joint_ledger_cache`, `_get_gspread_client`, `load_config` (all existing/Task 3-4).
- Produces: `POST /api/joint/sync` → `{"ok": true, "pushed_ebony": int, "pushed_angus": int, "confirmed": int, "ledger_rows": int}`.
- Produces: `GET /api/joint/transactions` → `{"ok": true, "transactions": [...], "balance": {"direction": "ebony_owes_angus"|"angus_owes_ebony"|"even", "amount": float}}`.
- Produces: `GET /joint` → serves `joint.html` (Task 6).

- [ ] **Step 1: Implement the routes**

Add to `server.py` after `api_bills_sync_sheets`:

```python
@app.get("/joint")
def joint_page():
    return send_file(BASE_DIR / "joint.html")


@app.post("/api/joint/sync")
def api_joint_sync():
    try:
        config = load_config()
        gs = config.get("google_sheets", {})
        gc, gs = _get_gspread_client()
        pushed_ebony = push_ebony_to_staging(gc, gs)
        pushed_angus = push_angus_to_staging(gc, gs)
        confirmed = pull_confirmed_to_form(gc, gs)
        ledger_rows = refresh_joint_ledger_cache(gc, gs)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({
        "ok": True,
        "pushed_ebony": pushed_ebony,
        "pushed_angus": pushed_angus,
        "confirmed": confirmed,
        "ledger_rows": ledger_rows,
    })


@app.get("/api/joint/transactions")
def api_joint_transactions():
    rows = read_csv(JOINT_LEDGER_CSV)
    net = 0.0
    transactions = []
    for row in rows:
        angus_amt = parse_float(row.get("angus_amount")) or 0.0
        ebony_amt = parse_float(row.get("ebony_amount")) or 0.0
        joint_amt = parse_float(row.get("joint_amount")) or 0.0
        total = angus_amt + ebony_amt + joint_amt
        who_paid = row.get("who_paid", "")
        a_share = angus_amt + joint_amt / 2 if joint_amt else angus_amt
        e_share = ebony_amt + joint_amt / 2 if joint_amt else ebony_amt
        row_net = a_share if who_paid == "Angus" else -e_share
        net += row_net
        transactions.append({
            "date": row.get("date", ""),
            "description": row.get("description", ""),
            "who_paid": who_paid,
            "angus_amount": angus_amt,
            "ebony_amount": ebony_amt,
            "joint_amount": joint_amt,
            "category": row.get("category", ""),
            "total": round(total, 2),
        })

    if net > 0.005:
        balance = {"direction": "ebony_owes_angus", "amount": round(net, 2)}
    elif net < -0.005:
        balance = {"direction": "angus_owes_ebony", "amount": round(-net, 2)}
    else:
        balance = {"direction": "even", "amount": 0.0}

    return jsonify({"ok": True, "transactions": transactions, "balance": balance})
```

`parse_float` is an existing helper already defined in `server.py` (`server.py:57-60` approx — confirm via `grep -n "def parse_float" server.py`).

- [ ] **Step 2: Manual smoke test — sync endpoint**

With the dev server running (`venv/bin/python3 server.py`), run:
```bash
curl -s -X POST http://localhost:5001/api/joint/sync | python3 -m json.tool
```
Expected: JSON with `"ok": true` and non-negative integer counts. First run should show `pushed_ebony: 343` (or however many rows are in `transactions_ebony.csv` from Task 1's Step 5) and `pushed_angus` matching however many `joint`-tagged Up transactions currently exist (likely 0, since no transactions have been tagged `joint` yet — confirmed via the tag survey done during spec research).

- [ ] **Step 3: Manual smoke test — transactions endpoint**

```bash
curl -s http://localhost:5001/api/joint/transactions | python3 -m json.tool
```
Expected: JSON with `"ok": true`, a `transactions` array (should reflect `Form`'s 157 existing historical rows), and a `balance` object.

- [ ] **Step 4: Verify the sheet directly**

Open `https://docs.google.com/spreadsheets/d/1zXUBHExmiZqUxc5v54wbN0njO_1pqSa5QvrPlXoM0h4/edit` and confirm:
- A new `Ebony_Transactions` tab exists with header `ID, Date, Amount, Description, Row Type, Joint?, Source` and ~343 data rows.
- `Form` still has its original 157 rows (pull-confirmed should have added 0 new rows on this first run, since nothing in staging had `Joint?` ticked except Angus's pre-ticked `"x"` rows, which are likely empty if no Up transactions are tagged `joint` yet).

- [ ] **Step 5: Commit**

```bash
cd /Users/anguss/dev/finance_dash
git add server.py
git commit -m "feat(joint): add /api/joint/sync and /api/joint/transactions routes"
```

---

### Task 6: Dashboard page

**Files:**
- Create: `joint.html`
- Modify: `dashboard.html`, `networth.html`, `portfolio.html`, `cgt.html`, `house.html`, `bills.html`, `spending.html`, `budget.html`, `performance.html`, `insights.html`, `tax.html` (add nav link — same one-line addition to each file's shared nav block)

**Interfaces:**
- Consumes: `GET /api/joint/transactions`, `POST /api/joint/sync` (Task 5).
- Produces: a working page at `http://localhost:5001/joint`.

- [ ] **Step 1: Add the nav link to all existing pages**

In each of the 11 files listed above, find the line:
```html
  <a class="nav-item" href="/spending"><span class="nav-key">[S]</span>PEND</a>
```
and add immediately after it:
```html
  <a class="nav-item" href="/joint"><span class="nav-key">[J]</span>OINT</a>
```
(On `spending.html` itself and any page where `/joint` should be the active tab, that's handled per-page in Step 2 below — for now every *other* page just gets the plain non-active link.)

Run this check after editing to confirm all 11 got it:
```bash
cd /Users/anguss/dev/finance_dash
grep -l 'href="/joint"' dashboard.html networth.html portfolio.html cgt.html house.html bills.html spending.html budget.html performance.html insights.html tax.html
```
Expected: all 11 filenames printed.

- [ ] **Step 2: Create joint.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FINTERM · JOINT</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#080a08;--panel:#0d100d;--panel2:#111411;--rule:rgba(120,180,120,0.13);--rule2:rgba(120,180,120,0.06);--txt:#cfeacf;--dim:rgba(207,234,207,0.55);--dim2:rgba(207,234,207,0.28);--green:#7ee787;--amber:#f0b86e;--red:#ff7b72;--blue:#79c0ff;--font:'JetBrains Mono',monospace}
html,body{height:100%;background:var(--bg);color:var(--txt);font-family:var(--font);font-size:13px;line-height:1.5;overflow-x:hidden}
a{color:inherit;text-decoration:none}
.hdr{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;border-bottom:1px solid var(--rule);background:var(--panel)}
.hdr-left{display:flex;align-items:center;gap:12px}
.hdr-dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green);animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.3}}
.hdr-title{color:var(--green);font-weight:700;font-size:14px;letter-spacing:0.05em}
.hdr-sub{color:var(--dim);font-size:11px}
.nav{display:flex;align-items:center;border-bottom:1px solid var(--rule);background:var(--panel);overflow-x:auto;-webkit-overflow-scrolling:touch}
.nav-item{padding:8px 14px;color:var(--dim);font-size:12px;white-space:nowrap;border-bottom:2px solid transparent;transition:color 0.15s}
.nav-item:hover{color:var(--txt)}
.nav-item.active{color:var(--green);border-bottom-color:var(--green)}
.nav-key{color:var(--dim2)}
.page{padding:12px 16px;display:flex;flex-direction:column;gap:12px;max-width:1400px;margin:0 auto}
.box{background:var(--panel);border:1px solid var(--rule);padding:14px}
.btn{padding:6px 12px;font-size:11px;font-family:var(--font);border:1px solid var(--rule);background:transparent;color:var(--dim);cursor:pointer;transition:all 0.15s}
.btn:hover{border-color:var(--green);color:var(--green)}
.btn:disabled{opacity:0.4;cursor:not-allowed}
.green{color:var(--green)}.amber{color:var(--amber)}.red{color:var(--red)}.dim{color:var(--dim)}.dim2{color:var(--dim2)}
.balance-banner{font-size:20px;font-weight:700;text-align:center;padding:20px}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;padding:6px 8px;color:var(--dim);font-weight:600;text-transform:uppercase;font-size:10px;letter-spacing:0.06em;border-bottom:1px solid var(--rule)}
td{padding:6px 8px;border-bottom:1px solid var(--rule2)}
</style>
</head>
<body>
<div class="hdr">
  <div class="hdr-left"><span class="hdr-dot"></span><span class="hdr-title">FINTERM</span><span class="hdr-sub">joint expenses</span></div>
</div>
<nav class="nav">
  <a class="nav-item" href="/dashboard"><span class="nav-key">[D]</span>ASH</a>
  <a class="nav-item" href="/networth"><span class="nav-key">[N]</span>ET.WORTH</a>
  <a class="nav-item" href="/portfolio"><span class="nav-key">[P]</span>ORTFOLIO</a>
  <a class="nav-item" href="/cgt"><span class="nav-key">[C]</span>GT</a>
  <a class="nav-item" href="/house"><span class="nav-key">[H]</span>OUSE</a>
  <a class="nav-item" href="/bills"><span class="nav-key">[B]</span>ILLS</a>
  <a class="nav-item" href="/spending"><span class="nav-key">[S]</span>PEND</a>
  <a class="nav-item active" href="/joint"><span class="nav-key">[J]</span>OINT</a>
  <a class="nav-item" href="/budget"><span class="nav-key">[U]</span>DGET</a>
  <a class="nav-item" href="/performance"><span class="nav-key">[F]</span>PERF</a>
  <a class="nav-item" href="/insights"><span class="nav-key">[I]</span>NSIGHTS</a>
  <a class="nav-item" href="/tax"><span class="nav-key">[T]</span>AX</a>
</nav>
<div class="page">
  <div class="box">
    <div class="balance-banner" id="balanceBanner">Loading…</div>
    <div style="text-align:center"><button class="btn" id="syncButton">[ SYNC ]</button></div>
  </div>
  <div class="box">
    <table>
      <thead><tr><th>Date</th><th>Description</th><th>Who Paid</th><th>Angus $</th><th>Ebony $</th><th>Joint $</th><th>Category</th></tr></thead>
      <tbody id="txBody"></tbody>
    </table>
  </div>
</div>
<script>
async function fetchJson(url,options){const r=await fetch(url,options);if(!r.ok){const d=await r.json().catch(()=>({}));throw new Error(d.error||`Request failed: ${r.status}`);}return r.json();}

function fmtMoney(n){return `$${Number(n).toFixed(2)}`;}

async function loadTransactions(){
  const data = await fetchJson('/api/joint/transactions');
  const banner = document.getElementById('balanceBanner');
  const b = data.balance;
  if(b.direction === 'even'){
    banner.textContent = 'All settled up';
    banner.className = 'balance-banner dim';
  } else if(b.direction === 'ebony_owes_angus'){
    banner.textContent = `Ebony → Angus ${fmtMoney(b.amount)}`;
    banner.className = 'balance-banner green';
  } else {
    banner.textContent = `Angus → Ebony ${fmtMoney(b.amount)}`;
    banner.className = 'balance-banner amber';
  }
  const tbody = document.getElementById('txBody');
  tbody.innerHTML = data.transactions.map(t => `
    <tr>
      <td>${t.date}</td>
      <td>${t.description}</td>
      <td>${t.who_paid}</td>
      <td>${t.angus_amount ? fmtMoney(t.angus_amount) : ''}</td>
      <td>${t.ebony_amount ? fmtMoney(t.ebony_amount) : ''}</td>
      <td>${t.joint_amount ? fmtMoney(t.joint_amount) : ''}</td>
      <td>${t.category}</td>
    </tr>
  `).join('');
}

document.getElementById('syncButton').addEventListener('click', async () => {
  const btn = document.getElementById('syncButton');
  btn.disabled = true; btn.textContent = '[ SYNCING ]';
  try {
    const result = await fetchJson('/api/joint/sync', {method: 'POST'});
    await loadTransactions();
    window.alert(`Pushed ${result.pushed_ebony} Ebony rows, ${result.pushed_angus} Angus rows to staging. Confirmed ${result.confirmed} new joint transactions.`);
  } catch(e) {
    window.alert(e.message);
  } finally {
    btn.disabled = false; btn.textContent = '[ SYNC ]';
  }
});

loadTransactions().catch(e => {
  document.getElementById('balanceBanner').textContent = `Error: ${e.message}`;
});
</script>
</body>
</html>
```

- [ ] **Step 3: Manual browser check**

With the dev server running, open `http://localhost:5001/joint` in a browser (or `curl -s http://localhost:5001/joint | head -5` to confirm HTML is served) and verify:
- Page loads with the terminal theme (dark background, green accents) matching `/spending`.
- Balance banner shows a real value (not "Loading…" stuck, not an error) — reflecting `Form`'s current 157-row history.
- Table lists transactions.
- Clicking `[ SYNC ]` shows the syncing state, then an alert with counts, then the table stays consistent (no duplicate rows on a second click, since Task 1/3/4's dedup logic should prevent re-pushing/re-confirming already-processed rows).

- [ ] **Step 4: Commit**

```bash
cd /Users/anguss/dev/finance_dash
git add joint.html dashboard.html networth.html portfolio.html cgt.html house.html bills.html spending.html budget.html performance.html insights.html tax.html
git commit -m "feat(joint): add /joint dashboard page with balance and sync button"
```

---

## Post-implementation notes to surface to the user

- **`Ebony_Transactions` sheet review needed**: after Task 5 Step 4, the user should open the sheet and manually verify the staged data looks right before Ebony starts ticking boxes.
- **Date+description dedup limitation** (Task 4): flagged inline above — a rare true duplicate (same day, same description, different amount) on `Form` would be silently skipped on re-sync. If this becomes a real problem in practice, the fix is switching `Form` to carry a hidden row-id column, which is a bigger change deferred out of this plan's scope.
- **No transactions are currently tagged `joint` in Up** (confirmed via tag survey during spec research) — the user needs to actually start tagging before `push_angus_to_staging` will find anything.
