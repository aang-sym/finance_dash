# Joint Expenses with Ebony — Design

## Purpose

Angus and Ebony split joint purchases (meals out, groceries, events, etc.).
Today this is tracked entirely by hand in a Google Sheet, "AJ + EJ Expenses"
(`1zXUBHExmiZqUxc5v54wbN0njO_1pqSa5QvrPlXoM0h4`), with tabs:
- `Form` — the confirmed ledger (fed today by a Google Form): Timestamp,
  Date, Description, Who paid?, Angus amount, Ebony amount, Joint amount,
  Category.
- `Calc` — a computed running-balance view, presumably formula-driven off
  `Form` (exact formulas not yet inspected — to confirm during
  implementation so appending rows doesn't break it).
- `Sheet2` / `Sheet2 (2)` — ad hoc pastes of Ebony's CBA transactions used
  to eyeball what's joint, not wired to anything.

The service account already used for read-only Sheets access elsewhere in
this project (`aang-sym@finance-dash-496812.iam.gserviceaccount.com`) is
already an Editor on this sheet, confirmed 2026-07-26 — no sharing changes
needed, only a code-side scope change (see Components §2).

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
- Not replacing `Form` or `Calc` — this augments them. `Form` stays the one
  and only confirmed ledger; nothing writes to it except the pull-confirmed
  step below.
- `Sheet2` / `Sheet2 (2)` are left alone (not reused) — a new dedicated tab
  replaces their purpose so the raw dump and the confirmed ledger don't mix.

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
    - ALL of Ebony's parsed rows (every transaction, unfiltered — she needs
      the complete history to review, not just guessed candidates),
      each flagged with a `row_type` for known non-spending patterns so she
      can filter in-sheet
          |
          v
  New sheet tab `Ebony_Transactions` -- full raw dump + blank "Joint?"
  checkbox column. Ebony ticks it for shared purchases. This tab is a
  permanent staging area, not one-off (replaces Sheet2/Sheet2 (2))
          |
          v
  "pull confirmed" step: reads rows where "Joint?" is ticked
  (from Ebony_Transactions) plus Angus's tag=="joint" rows, excluding
  anything already appended to Form (tracked by row id)
          |
          v
  `Form` tab -- appended, 50/50 split by default, matching Form's existing
  columns exactly (Timestamp, Date, Description, Who paid?, Angus amount,
  Ebony amount, Joint amount, Category)
          |
          v
  Calc tab -- untouched by our code; if it's formula-driven off Form's full
  range it picks up new rows automatically (to confirm when implementing)
          |
          v
  data/joint_ledger.csv (local mirror, written after each pull, used by API)
          |
          v
  /joint dashboard tab: transaction list + running balance ("Ebony -> Angus $X")
```

Nothing is ever appended to `Form` until a person has explicitly ticked/
tagged a transaction AND a sync has been run — there is no live/automatic
write the instant Ebony ticks a box in the sheet (see "Pull-confirmed step"
below for exactly when this runs).

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
  credentials per scope on one service account call. No sharing/permission
  changes needed — the service account is already Editor on this sheet.
- For Angus: reads `transactions_spending.csv` + `transactions_2up.csv`,
  filters rows where `tags` contains `joint`, excludes ones already present
  in `Form` (by transaction id, tracked in a small local
  `data/joint_pushed.csv` state file).
- For Ebony: reads unpushed rows from `transactions_ebony.csv` — *all* rows,
  not just likely candidates.
- Appends rows to the `Ebony_Transactions` tab (new tab, created once during
  implementation): Date, Amount, Description, Row Type, Joint? (blank
  checkbox for her to tick).
- Marks rows as pushed locally so re-running doesn't duplicate rows already
  sitting in `Ebony_Transactions` awaiting her review.

### 3. Pull-confirmed step

- Reads `Ebony_Transactions`, finds rows where "Joint?" is
  checked/non-empty AND not yet present in `Form` (by row id).
- Also reads Angus's tag=="joint" rows not yet in `Form`.
- Default split: 50/50 of the absolute amount into "Angus amount" /
  "Ebony amount" columns — matches `Form`'s existing shape, editable by
  either person afterward directly in Sheets (script never overwrites an
  existing `Form` row).
- Appends to `Form` in its exact existing column order: `Timestamp, Date,
  Description, Who paid?, Angus amount, Ebony amount, Joint amount,
  Category`. "Who paid?" is inferred from the source (Angus tag → Angus;
  Ebony_Transactions row → Ebony).
- `Calc` is not written to directly. If, on inspection, `Calc` references a
  fixed range rather than the full `Form` column, extending that range is
  an implementation task — flagged here since it wasn't verified while
  writing this spec (Drive's content reader only exposes values, not
  formulas).
- After appending, writes `data/joint_ledger.csv` as a local mirror (a
  fresh pull of `Form`'s full contents) — this is what the dashboard reads,
  avoiding a live Sheets API call on every page load.

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
  "joint_staging_tab": "Ebony_Transactions",
  "joint_log_tab": "Form"
}
```
`Ebony_Transactions` is a new tab, created during implementation (does not
exist yet — confirmed the sheet currently only has `Form`, `Calc`,
`Sheet2`, `Sheet2 (2)`).

## Error handling

- Missing/malformed CBA CSV rows (unparseable date/amount): skipped, logged
  to stdout with the raw line — matches existing importer behaviour
  elsewhere (e.g. bills-from-sheets skip-on-parse-failure pattern).
- Sheets write failures surface as a 400/500 JSON error from the API
  endpoint, same convention as existing `/api/networth/import-sheets`.
- No network retry logic needed — manual "Sync" button, user can just
  click again.

## Note on sheet sharing

Confirmed 2026-07-26: this sheet's general access is "Anyone with the
link" set to **Editor** — anyone possessing the URL can edit it without a
Google login, not just Angus/Ebony. Out of scope to change as part of this
feature, but flagging since the URL has been shared in this chat/session.

## Testing

- Unit-level: CBA CSV row parser against the sample file's known rows
  (date/amount/description/row_type for a handful of representative lines:
  a card purchase, a "Transfer to", a "Direct Debit").
- Manual: push/pull cycle exercised against a scratch copy of the sheet
  before pointing at the real one, since this is the first *write* path
  this codebase has ever had to Sheets.
