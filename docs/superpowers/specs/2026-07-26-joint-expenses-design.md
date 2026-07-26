# Joint Expenses with Ebony — Design

## Purpose

Angus and Ebony split joint purchases (meals out, groceries, events, etc.).
Today this is tracked entirely by hand in a Google Sheet
(`1zXUBHExmiZqUxc5v54wbN0njO_1pqSa5QvrPlXoM0h4`): a manual log tab, a
computed running-balance tab, and a staging tab where Ebony pastes her
Commonwealth Bank (CBA) transactions to review.

Angus is on Up (this dashboard already syncs his transactions and supports
tagging). Ebony is on CBA, which has no public consumer API — CommBank's
developer portal is a CDR (Consumer Data Right) program requiring formal
accreditation as a data recipient, not something available for personal use.
Her transactions come in as a manual NetBank CSV export instead.

Goal: automate the mechanical parts of this workflow (parsing her CSV,
pushing candidates to the sheet, computing the split/balance, visualizing it)
while keeping the Google Sheet as the source of truth, matching how the
household bill-splitting system already works with Up tags.

## Non-goals

- No CBA API integration (not available to individual customers).
- No automatic classification of *which* transactions are joint — both
  people always make that call explicitly (Angus via Up tag, Ebony via a
  sheet checkbox).
- Not replacing the existing sheet's manual-entry tab — this augments it.

## Data flow

```
Angus: tags transactions "joint" in the Up app
          |
          v
  existing sync.py -> data/transactions_spending.csv / transactions_2up.csv
          |                       (tags column already captured)
          v
Ebony: exports CBA CSV from NetBank -> saves into data/ebony_cba_*.csv
          |
          v
  new import script parses CBA CSV -> data/transactions_ebony.csv
          |
          v
  "push candidates" step:
    - Angus's tag=="joint" rows
    - all of Ebony's parsed rows (unfiltered, but flagged with a `row_type`
      for known non-spending patterns so she can filter in-sheet)
          |
          v
  Google Sheet staging tab (existing 3rd tab) -- Ebony ticks "Joint" column
          |
          v
  "pull confirmed" step: reads back rows where Joint is ticked
  (from Angus's push OR Ebony's ticks) that aren't already in the ledger
          |
          v
  Google Sheet main log tab (existing 1st/2nd tab) -- appended, 50/50 split
  by default, columns match existing sheet exactly
          |
          v
  data/joint_ledger.csv (local mirror, written after each pull, used by API)
          |
          v
  /joint dashboard tab: transaction list + running balance ("Ebony -> Angus $X")
```

The sheet stays authoritative for the ledger; the local CSV is a read cache
so the dashboard doesn't hit the Sheets API on every page load.

## Components

### 1. CBA CSV importer (`health_pipeline`-style script, new file `import_ebony_cba.py` at repo root, alongside `sync.py`)

CBA's NetBank export format (confirmed from `data/ebony_cba_feb_jul_26.csv`):
headerless CSV, columns `Date (DD/MM/YYYY), Amount, Description, Balance`,
all fields quoted, amounts signed (negative = debit).

- Input: a file path (defaults to newest `data/ebony_cba_*.csv` if not given).
- Parses each row into: `date` (ISO), `amount` (float, sign preserved),
  `description` (trimmed), `row_type`.
- `row_type` classification (regex/substring match on description), used as
  a filter toggle in the sheet — not a hard exclude:
  - `transfer` — "Transfer to", "Transfer from"
  - `direct_debit` — "Direct Debit"
  - `card_purchase` — "AUS Card xx" present (default/common case)
  - `other` — anything else

`row_type` is purely an in-sheet filter aid (e.g. hide "transfer" rows while
scanning). It never blocks a row from being confirmed — if Ebony ticks
"Joint" on a `direct_debit` row (e.g. a shared subscription), it's pulled
into the ledger exactly like any other confirmed row.
- Row ID: `sha1(date + amount + description)` — stable across repeated
  overlapping exports, used for de-dup against what's already been pushed.
- Output: merges into `data/transactions_ebony.csv` (same merge-by-id
  pattern as `sync.py`'s `merge_rows`), fields:
  `id, date, amount, description, row_type, pushed`.
- `pushed` is a local flag (not written back to CBA obviously) marking rows
  already sent to the sheet staging tab, so re-running the importer/pusher
  doesn't duplicate staging rows.

### 2. Push-to-staging step (function in `server.py`, reuses `_get_gspread_client`)

- Requires **write** scope now (`https://www.googleapis.com/auth/spreadsheets`
  instead of the current `.readonly`) — this is a scope change to the
  existing shared gspread helper, since Sheets doesn't allow separate
  credentials per scope on one service account call.
- For Angus: reads `transactions_spending.csv` + `transactions_2up.csv`,
  filters rows where `tags` contains `joint`, excludes ones already present
  in the ledger (by transaction id, tracked in a small local
  `data/joint_pushed.csv` state file).
- For Ebony: reads unpushed rows from `transactions_ebony.csv`.
- Appends rows to the sheet's 3rd (staging) tab, matching its existing
  columns, adding a `Row Type` column (new) and leaving `Joint` blank for
  her to tick.
- Marks rows as pushed locally so re-running doesn't duplicate.

### 3. Pull-confirmed step

- Reads the staging tab, finds rows where the "Joint" column is
  checked/non-empty AND not yet in the main ledger tab.
- Default split: 50/50 of the absolute amount into "Angus $" / "Ebony $"
  columns — matches the sheet's existing shape, editable by either person
  afterward directly in Sheets (script never overwrites an existing ledger
  row).
- Appends to the main log tab (tab 1) in the exact existing column order:
  `Timestamp, Date, Description, Who paid?, Angus amount, Ebony amount,
  Joint amount, Category`. "Who paid?" is inferred from the source (Angus
  tag → Angus; Ebony CBA row → Ebony).
- After appending, re-reads the whole main tab and recomputes the running
  balance the same way tab 2 already does (Total, A share, E share, Net,
  cumulative Balance), writing `data/joint_ledger.csv` as a local mirror —
  this is what the dashboard reads. The existing tab 2 in the sheet is left
  as-is (still manually looking at tab 1); we don't touch it to avoid
  clobbering formulas already there.

### 4. Dashboard: new `/joint` tab

- New route `@app.get("/joint")` serving `joint.html`, added to nav
  (`dashboard.html` and all other pages' shared nav block) next to
  `/spending`, e.g. `[J]OINT`.
- New API endpoints:
  - `GET /api/joint/transactions` — reads `data/joint_ledger.csv`, returns
    list + running balance.
  - `GET /api/joint/staging` — returns unconfirmed candidates (for a
    "pending review" count/badge).
  - `POST /api/joint/sync` — triggers push-to-staging + pull-confirmed in
    one call (button on the page, mirrors the existing "Sync from Up" /
    "Import from Sheets" buttons elsewhere).
- Page content: current balance banner ("Ebony owes Angus $X" /
  "Angus owes Ebony $X"), transaction table (date, description, who paid,
  split, category), category breakdown, sync button. Styled consistently
  with `spending.html` / `bills.html` (same CSS/JS conventions, no new
  framework).

## Config additions (`config.json` / `config.example.json`)

```json
"google_sheets": {
  "joint_sheet_id": "1zXUBHExmiZqUxc5v54wbN0njO_1pqSa5QvrPlXoM0h4",
  "joint_staging_tab": "<name of 3rd tab>",
  "joint_log_tab": "<name of 1st tab>"
}
```
Exact tab names to be confirmed against the live sheet when implementing
(the read-only fetch used above didn't expose tab names, only content).

## Error handling

- Missing/malformed CBA CSV rows (unparseable date/amount): skipped, logged
  to stdout with the raw line — matches existing importer behaviour
  elsewhere (e.g. bills-from-sheets skip-on-parse-failure pattern).
- Sheets write failures surface as a 400/500 JSON error from the API
  endpoint, same convention as existing `/api/networth/import-sheets`.
- No network retry logic needed — manual "Sync" button, user can just
  click again.

## Testing

- Unit-level: CBA CSV row parser against the sample file's known rows
  (date/amount/description/row_type for a handful of representative lines:
  a card purchase, a "Transfer to", a "Direct Debit").
- Manual: push/pull cycle exercised against a scratch copy of the sheet
  before pointing at the real one, since this is the first *write* path
  this codebase has ever had to Sheets.
