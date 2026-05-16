# History Tab & Spending Insights Improvements — Implementation Plan

**Goal:** Add a `bill_types.csv` lookup table with provider info, move bill history into its own tab with group-by filtering, and significantly improve the spending insights page with time-grouped charts, month-over-month comparison, merchant drill-down, and noise filtering.

**Architecture:** Three loosely coupled areas of change — (1) data layer: new `bill_types.csv`, backfilled provider data, enriched `bill_cycles.csv`; (2) `bills.html`: tab switcher between current bill cards and a new history view with group-by; (3) `spending.html` + `server.py`: new API params and richer frontend charts. No new pages or files beyond the CSV. All changes are additive — existing behaviour is preserved.

**Tech Stack:** Python/Flask backend, vanilla JS frontend, Chart.js (CDN, already loaded on spending.html), CSV flat files as the data layer.

---

## File map

| File | Change |
|---|---|
| `data/bill_types.csv` | **Create** — slug, label, provider, recurrence_default, split_type_default |
| `data/bills.csv` | **Backfill** — no schema change, provider comes from bill_types |
| `data/bill_cycles.csv` | **Schema change** — add `provider` column (written by server) |
| `server.py` | **Modify** — read bill_types, enrich history response, new spending query params |
| `bills.html` | **Modify** — add tab switcher, history tab with group-by dropdown and per-group tables |
| `spending.html` | **Modify** — trend chart, month-over-month panel, merchant table, noise filters |

---

## Task 1: Create `bill_types.csv`

**Files:**
- Create: `data/bill_types.csv`

- [ ] **Step 1: Create the file with headers and all 5 bill types**

```csv
slug,label,provider,recurrence_default,split_type_default
rent,Rent,Deft Real Estate,monthly,fixed
elec,Electricity,OVO Energy,quarterly,equal
water,Water,Yarra Valley Water,quarterly,equal
internet,Internet,Superloop,monthly,equal
gas,Gas,Alinta Energy,quarterly,equal
```

Save to `data/bill_types.csv`.

- [ ] **Step 2: Verify the file exists and is valid**

```bash
python -c "
import csv
from pathlib import Path
rows = list(csv.DictReader(open('data/bill_types.csv')))
assert len(rows) == 5, f'Expected 5 rows, got {len(rows)}'
assert all(r['provider'] for r in rows), 'Missing provider'
print('OK:', [(r['slug'], r['provider']) for r in rows])
"
```

Expected output:
```
OK: [('rent', 'Deft Real Estate'), ('elec', 'OVO Energy'), ('water', 'Yarra Valley Water'), ('internet', 'Superloop'), ('gas', 'Alinta Energy')]
```

- [ ] **Step 3: Commit**

```bash
git add data/bill_types.csv
git commit -m "data: add bill_types.csv with provider info for all 5 bill slugs"
```

---

## Task 2: Load bill_types in server.py and enrich history responses

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Add `read_bill_types()` helper and `BILL_TYPES_PATH` constant near the top of `server.py`, after the existing `DATA_DIR` imports**

Add after line 15 (`BILL_CYCLES_PATH = DATA_DIR / "bill_cycles.csv"`):

```python
BILL_TYPES_PATH = DATA_DIR / "bill_types.csv"
```

Add after the `read_housemates()` function (around line 110):

```python
def read_bill_types() -> Dict[str, Dict[str, str]]:
    rows = read_csv(BILL_TYPES_PATH)
    return {row["slug"]: row for row in rows if row.get("slug")}
```

- [ ] **Step 2: Add `provider` to `write_bill_cycles()` fieldnames**

In `write_bill_cycles()` (around line 121), change the fieldnames list to include `provider`:

```python
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
```

- [ ] **Step 3: Enrich `compute_bill_history()` to include provider**

In `compute_bill_history()`, add a `bill_types` lookup at the top of the function (after line 314 `rows = read_csv(...)`):

```python
    bill_types = read_bill_types()
```

In the `payload.append(...)` block, add `"provider"` to each item:

```python
                "provider": bill_types.get(entry["slug"], {}).get("provider", ""),
```

In the `cycle_csv_rows.append(...)` block, add `"provider"`:

```python
                "provider": bill_types.get(entry["slug"], {}).get("provider", ""),
```

- [ ] **Step 4: Verify the history endpoint returns provider**

Start the server and run:

```bash
python server.py &
sleep 1
curl -s http://localhost:5000/api/bills/history | python -m json.tool | grep -A1 '"provider"'
```

Expected: each history entry has `"provider": "Deft Real Estate"` (or equivalent). Kill the server after (`kill %1`).

- [ ] **Step 5: Commit**

```bash
git add server.py
git commit -m "feat: enrich bill history API with provider from bill_types.csv"
```

---

## Task 3: Add group-by to the spending API

**Files:**
- Modify: `server.py`

The existing `/api/spending` endpoint returns flat rows. We need a new endpoint `/api/spending/summary` that returns data pre-grouped for the trend chart and month-over-month panel. The existing endpoint stays unchanged.

- [ ] **Step 1: Add `group_spending_by_period()` function to `server.py`, before the Flask route definitions**

```python
def group_spending_by_period(
    rows: List[Dict],
    group_by: str,
) -> List[Dict]:
    """
    Groups filtered spending rows by 'week' or 'month'.
    Returns list of {period, total_spend, transaction_count} sorted ascending by period.
    group_by: 'week' | 'month'
    """
    from collections import defaultdict
    buckets: Dict[str, float] = defaultdict(float)
    counts: Dict[str, int] = defaultdict(int)

    for row in rows:
        amount = float(row.get("amount", 0))
        if amount >= 0:
            continue  # outgoing only
        dt_str = row.get("settled_at") or row.get("created_at") or ""
        if not dt_str:
            continue
        dt = parse_datetime_or_date(dt_str)
        if group_by == "week":
            # ISO week: YYYY-Www
            period = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
        else:
            period = f"{dt.year}-{dt.month:02d}"
        buckets[period] += abs(amount)
        counts[period] += 1

    return [
        {"period": period, "total_spend": round(buckets[period], 2), "transaction_count": counts[period]}
        for period in sorted(buckets.keys())
    ]
```

- [ ] **Step 2: Add `GET /api/spending/summary` route**

Add after the existing `@app.get("/api/spending")` route:

```python
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
        filtered = [r for r in filtered if float(r.get("amount", 0)) < 0]

    if min_amount:
        try:
            threshold = abs(float(min_amount))
            filtered = [r for r in filtered if abs(float(r.get("amount", 0))) >= threshold]
        except ValueError:
            pass

    if group_by not in ("week", "month"):
        group_by = "month"

    grouped = group_spending_by_period(filtered, group_by)

    # Merchant breakdown: top 20 by absolute spend
    from collections import defaultdict
    merchant_totals: Dict[str, float] = defaultdict(float)
    merchant_counts: Dict[str, int] = defaultdict(int)
    for row in filtered:
        amount = float(row.get("amount", 0))
        if amount >= 0:
            continue
        desc = (row.get("description") or "").strip()
        if not desc:
            continue
        merchant_totals[desc] += abs(amount)
        merchant_counts[desc] += 1

    merchants = sorted(
        [
            {"description": desc, "total_spend": round(merchant_totals[desc], 2), "transaction_count": merchant_counts[desc]}
            for desc in merchant_totals
        ],
        key=lambda m: m["total_spend"],
        reverse=True,
    )[:20]

    total_spend = round(sum(abs(float(r.get("amount", 0))) for r in filtered if float(r.get("amount", 0)) < 0), 2)
    total_in = round(sum(float(r.get("amount", 0)) for r in filtered if float(r.get("amount", 0)) > 0), 2)

    return jsonify({
        "group_by": group_by,
        "periods": grouped,
        "merchants": merchants,
        "total_spend": total_spend,
        "total_in": total_in,
        "transaction_count": len(filtered),
    })
```

- [ ] **Step 3: Verify the endpoint works**

```bash
python server.py &
sleep 1
curl -s "http://localhost:5000/api/spending/summary?group_by=month" | python -m json.tool | head -40
```

Expected: JSON with `"group_by": "month"`, `"periods": [...]`, `"merchants": [...]`, `"total_spend": <number>`.

Kill server: `kill %1`

- [ ] **Step 4: Commit**

```bash
git add server.py
git commit -m "feat: add /api/spending/summary with period grouping, merchant breakdown, noise filters"
```

---

## Task 4: Add history tab to `bills.html`

**Files:**
- Modify: `bills.html`

The page currently has two visual sections: the bill cards layout and the history panel at the bottom. We convert these into two tabs: **Bills** and **History**. The existing history table becomes the History tab content. The group-by dropdown lives inside the History tab.

- [ ] **Step 1: Add tab switcher CSS to the `<style>` block in `bills.html`**

Add before the closing `</style>` tag:

```css
.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 24px;
}

.tab-btn {
  appearance: none;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 10px 20px;
  background: var(--panel);
  color: var(--muted);
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  transition: background 160ms ease, color 160ms ease;
}

.tab-btn.active {
  background: var(--ink);
  color: white;
  border-color: transparent;
}

.tab-pane { display: none; }
.tab-pane.active { display: block; }

.history-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}

.history-controls label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.92rem;
  color: var(--muted);
  font-weight: 600;
}

.history-controls select {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 8px 12px;
  background: var(--panel-strong);
  color: var(--ink);
  font: inherit;
  cursor: pointer;
}

.history-group {
  margin-bottom: 28px;
}

.history-group-heading {
  font-family: var(--font-display);
  font-size: 1.05rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin: 0 0 10px;
  color: var(--ink);
}

.history-group-sub {
  color: var(--muted);
  font-size: 0.88rem;
  margin-left: 8px;
  font-weight: 400;
}
```

- [ ] **Step 2: Replace the existing HTML structure in `bills.html`**

Wrap the existing content in tab panes. Replace the current body content (everything inside `<div class="shell">`) with:

```html
<div class="shell">
  <div class="topbar">
    <div class="title-block">
      <h1>House Bills</h1>
      <p>Track tagged Beem receipts, see who still owes each cycle, and push manual overrides for edge cases without leaving the browser.</p>
      <div class="links">
        <a href="/spending">Open spending view</a>
      </div>
    </div>
    <div class="toolbar">
      <div class="status-chip" id="lastSynced">Last synced: loading...</div>
      <button class="button secondary" id="toggleForm">Add bill</button>
      <button class="button secondary" id="fullRefreshButton">Full resync</button>
      <button class="button" id="refreshButton">Refresh</button>
    </div>
  </div>

  <div class="tabs">
    <button class="tab-btn active" data-tab="bills">Bills</button>
    <button class="tab-btn" data-tab="history">History</button>
  </div>

  <div id="tab-bills" class="tab-pane active">
    <div class="layout">
      <section class="stack" id="billList"></section>
      <aside class="stack">
        <section class="panel sidebar-panel">
          <div class="sidebar-heading">
            <h2>Upcoming</h2>
            <span class="subtle">Next 30 days</span>
          </div>
          <div id="upcomingList" class="upcoming-list"></div>
        </section>
        <section class="panel sidebar-panel">
          <div class="sidebar-heading">
            <h2>Add bill</h2>
            <span class="subtle">Append to `bills.csv`</span>
          </div>
          <div id="addForm" class="add-form">
            <div class="field-grid">
              <label>
                Bill type
                <select id="billSlug">
                  <option value="rent">Rent</option>
                  <option value="elec">Electricity</option>
                  <option value="water">Water</option>
                  <option value="internet">Internet</option>
                  <option value="gas">Gas</option>
                </select>
              </label>
              <label>
                Label
                <input id="billLabel" type="text" value="Rent">
              </label>
              <label>
                Amount
                <input id="billAmount" type="number" step="0.01" min="0" placeholder="Optional">
              </label>
              <label>
                Due date
                <input id="billDueDate" type="date">
              </label>
              <label>
                Recurrence
                <select id="billRecurrence">
                  <option value="monthly">monthly</option>
                  <option value="quarterly">quarterly</option>
                  <option value="annual">annual</option>
                  <option value="once">once</option>
                </select>
              </label>
              <label>
                Split type
                <select id="billSplitType">
                  <option value="equal">equal</option>
                  <option value="fixed">fixed</option>
                </select>
              </label>
            </div>
            <label>
              Notes
              <textarea id="billNotes" placeholder="Optional notes"></textarea>
            </label>
            <div class="error" id="formError"></div>
            <button class="button" id="submitBill">Save bill</button>
          </div>
        </section>
      </aside>
    </div>
  </div>

  <div id="tab-history" class="tab-pane">
    <section class="panel history-panel">
      <div class="history-controls">
        <label>
          Group by
          <select id="historyGroupBy">
            <option value="month">Month</option>
            <option value="bill">Bill type</option>
            <option value="person">Person</option>
          </select>
        </label>
      </div>
      <div id="historyContent"></div>
    </section>
  </div>
</div>
```

- [ ] **Step 3: Replace `renderHistory()` in the `<script>` block with a grouped version**

Remove the existing `renderHistory()` function and the `document.getElementById("historyTable")` references. Add:

```javascript
function getGroupKey(row, groupBy) {
  if (groupBy === "month") return `${row.year}-${row.month}`;
  if (groupBy === "bill") return row.slug;
  if (groupBy === "person") return null; // person grouping is different — see renderHistoryByPerson
  return `${row.year}-${row.month}`;
}

function groupLabel(key, groupBy, history) {
  if (groupBy === "month") {
    const [year, month] = key.split("-");
    return `${month.charAt(0).toUpperCase() + month.slice(1)} ${year}`;
  }
  if (groupBy === "bill") {
    const row = history.find((r) => r.slug === key);
    return row ? row.label : key;
  }
  return key;
}

function historyTableHtml(rows) {
  if (!rows.length) return `<div class="empty">No data.</div>`;
  return `
    <div class="history-table-wrap">
      <table class="history-table">
        <thead>
          <tr>
            <th>Cycle</th>
            <th>Bill</th>
            <th>Provider</th>
            <th>Paid tags</th>
            <th>Collected</th>
            <th>Forwarded</th>
            <th>Latest activity</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => {
            const latest = row.latest_activity
              ? new Date(row.latest_activity).toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" })
              : "—";
            const paidTags = row.housemates_paid.length
              ? `<div class="pill-list">${row.housemates_paid.map((name) => `<span class="mini-pill">${escapeHtml(name)}</span>`).join("")}</div>`
              : `<span class="subtle">none</span>`;
            return `
              <tr>
                <td><strong>${escapeHtml(row.cycle_tag)}</strong></td>
                <td>${escapeHtml(row.label)}</td>
                <td>${escapeHtml(row.provider || "—")}</td>
                <td>${paidTags}<div class="subtle">${row.housemates_paid_count}/5 tagged</div></td>
                <td>${formatCurrency(row.incoming_total)}</td>
                <td>${formatCurrency(row.forwarded_total)}</td>
                <td>${latest}</td>
              </tr>
            `;
          }).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderHistoryByPerson(history) {
  const container = document.getElementById("historyContent");
  if (!history.length) {
    container.innerHTML = `<div class="empty">No bill cycle tags found in your synced transactions yet.</div>`;
    return;
  }

  // Build a map: person → list of {cycle_tag, label, provider, paid, incoming_total}
  const HOUSEMATES = ["angus", "sean", "alex", "jarrod", "ryan"];
  const personMap = {};
  HOUSEMATES.forEach((name) => { personMap[name] = []; });

  history.forEach((row) => {
    HOUSEMATES.forEach((name) => {
      personMap[name].push({
        cycle_tag: row.cycle_tag,
        label: row.label,
        provider: row.provider || "—",
        paid: row.housemates_paid.includes(name),
        latest_activity: row.latest_activity,
      });
    });
  });

  container.innerHTML = HOUSEMATES.map((name) => {
    const rows = personMap[name];
    const paidCount = rows.filter((r) => r.paid).length;
    return `
      <div class="history-group">
        <h3 class="history-group-heading">${escapeHtml(name.charAt(0).toUpperCase() + name.slice(1))} <span class="history-group-sub">${paidCount}/${rows.length} paid</span></h3>
        <div class="history-table-wrap">
          <table class="history-table">
            <thead><tr><th>Cycle</th><th>Bill</th><th>Provider</th><th>Paid</th><th>Latest activity</th></tr></thead>
            <tbody>
              ${rows.map((row) => {
                const latest = row.latest_activity
                  ? new Date(row.latest_activity).toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" })
                  : "—";
                return `
                  <tr>
                    <td><strong>${escapeHtml(row.cycle_tag)}</strong></td>
                    <td>${escapeHtml(row.label)}</td>
                    <td>${escapeHtml(row.provider)}</td>
                    <td>${row.paid ? '<span class="badge paid">paid</span>' : '<span class="badge pending">unpaid</span>'}</td>
                    <td>${latest}</td>
                  </tr>
                `;
              }).join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }).join("");
}

function renderHistory() {
  const groupBy = document.getElementById("historyGroupBy").value;
  const container = document.getElementById("historyContent");

  if (!state.history.length) {
    container.innerHTML = `<div class="empty">No bill cycle tags found in your synced transactions yet.</div>`;
    return;
  }

  if (groupBy === "person") {
    renderHistoryByPerson(state.history);
    return;
  }

  // Build groups
  const groups = {};
  state.history.forEach((row) => {
    const key = getGroupKey(row, groupBy);
    if (!groups[key]) groups[key] = [];
    groups[key].push(row);
  });

  // Sort group keys
  const sortedKeys = Object.keys(groups).sort((a, b) => {
    if (groupBy === "month") return b.localeCompare(a); // newest first
    return a.localeCompare(b);
  });

  container.innerHTML = sortedKeys.map((key) => {
    const rows = groups[key];
    const label = groupLabel(key, groupBy, state.history);
    const subLabel = groupBy === "month"
      ? `${rows.length} bill${rows.length !== 1 ? "s" : ""}`
      : `${rows.length} cycle${rows.length !== 1 ? "s" : ""}`;
    return `
      <div class="history-group">
        <h3 class="history-group-heading">${escapeHtml(label)} <span class="history-group-sub">${subLabel}</span></h3>
        ${historyTableHtml(rows)}
      </div>
    `;
  }).join("");
}
```

- [ ] **Step 4: Add tab switching logic and wire up the group-by dropdown**

Add at the bottom of the `<script>` block, before the `bootstrap()` call:

```javascript
// Tab switching
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
  });
});

// Group-by change
document.getElementById("historyGroupBy").addEventListener("change", renderHistory);
```

- [ ] **Step 5: Remove the old `renderHistory()` reference from `bootstrap()` and wire `loadHistory()` to call the new `renderHistory()`**

The existing `loadHistory()` function already calls `renderHistory()` — confirm it still does after the replacement above. The `bootstrap()` call at the bottom should remain unchanged. Verify in the script that `state.history` is still the data store used throughout.

- [ ] **Step 6: Open the browser and verify**

```bash
python server.py &
open http://localhost:5000/bills
```

Check:
- "Bills" and "History" tabs render
- Clicking "History" shows the history section
- Group by "Month" shows one table per month
- Group by "Bill type" shows one table per slug
- Group by "Person" shows one table per housemate with paid/unpaid per cycle
- Provider column shows "Deft Real Estate", "OVO Energy" etc.

Kill server: `kill %1`

- [ ] **Step 7: Commit**

```bash
git add bills.html
git commit -m "feat: history tab with group-by month/bill/person and provider column"
```

---

## Task 5: Improve spending.html

**Files:**
- Modify: `spending.html`

The spending page gets three new sections added to the existing layout:
1. **Noise filters** — a toggle row above the controls for "Exclude refunds" and a min-amount threshold
2. **Trend chart** — a line chart (spend per week or month) replacing or sitting alongside the existing bar chart
3. **Month-over-month panel** — a small comparison table showing current month vs previous month
4. **Merchant table** — top 20 merchants by spend, replacing nothing (new panel)

The existing category chart and transaction table are kept. The layout expands to accommodate the new panels.

- [ ] **Step 1: Add new CSS to `spending.html` `<style>` block**

Add before the closing `</style>` tag:

```css
.filter-row {
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

.filter-row label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.92rem;
  color: var(--muted);
  cursor: pointer;
}

.filter-row input[type="checkbox"] {
  width: 16px;
  height: 16px;
  accent-color: var(--accent);
  cursor: pointer;
}

.filter-row input[type="number"] {
  width: 100px;
  padding: 8px 10px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 18px;
}

.summary-card {
  padding: 16px 18px;
  border-radius: 18px;
  background: var(--panel);
  border: 1px solid rgba(255,255,255,0.7);
  box-shadow: var(--shadow);
}

.summary-card .label {
  display: block;
  font-size: 0.82rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.07em;
  margin-bottom: 6px;
}

.summary-card .value {
  font-size: 1.5rem;
  font-family: var(--font-display);
  font-weight: 700;
  letter-spacing: -0.03em;
}

.summary-card .delta {
  font-size: 0.85rem;
  margin-top: 4px;
}

.delta.up { color: #9d3b27; }
.delta.down { color: #1f7e52; }

.chart-group-row {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 14px;
}

.chart-group-row label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.88rem;
  color: var(--muted);
}

.chart-group-row select {
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: white;
  font: inherit;
}

.merchant-table {
  width: 100%;
  border-collapse: collapse;
}

.merchant-table th,
.merchant-table td {
  padding: 10px 10px;
  text-align: left;
  border-bottom: 1px solid var(--line);
  font-size: 0.92rem;
}

.merchant-bar-wrap {
  background: rgba(191,95,54,0.08);
  border-radius: 4px;
  height: 8px;
  width: 100%;
  margin-top: 4px;
}

.merchant-bar {
  background: rgba(191,95,54,0.7);
  height: 8px;
  border-radius: 4px;
}

.full-width-panel {
  margin-top: 18px;
  padding: 18px;
}
```

- [ ] **Step 2: Update the HTML body of `spending.html`**

Replace the entire `<body>` content with:

```html
<body>
  <div class="shell">
    <div class="hero">
      <div>
        <h1>Personal Spending</h1>
        <p class="subtle">Outgoing spend from the Up Spending account after excluding bill forwards and incoming savings transfers.</p>
        <a class="inline-link" href="/bills">Back to bills</a>
      </div>
    </div>

    <section class="controls">
      <div class="control-grid">
        <label>
          From
          <input type="date" id="fromDate">
        </label>
        <label>
          To
          <input type="date" id="toDate">
        </label>
        <label>
          Search description
          <input type="search" id="searchBox" placeholder="Coffee, Uber, groceries">
        </label>
        <button id="fetchButton">Fetch</button>
      </div>
      <div class="filter-row">
        <label>
          <input type="checkbox" id="excludeRefunds">
          Exclude refunds &amp; positive transactions
        </label>
        <label>
          Min amount $
          <input type="number" id="minAmount" min="0" step="1" placeholder="0">
        </label>
        <label>
          Group trend by
          <select id="groupBy">
            <option value="month">Month</option>
            <option value="week">Week</option>
          </select>
        </label>
      </div>
    </section>

    <div class="summary-grid">
      <div class="summary-card">
        <span class="label">Total spend</span>
        <div class="value" id="totalSpend">$0.00</div>
        <div class="delta" id="momDelta"></div>
      </div>
      <div class="summary-card">
        <span class="label">Transactions</span>
        <div class="value" id="totalCount">0</div>
      </div>
      <div class="summary-card">
        <span class="label">Avg per transaction</span>
        <div class="value" id="avgSpend">$0.00</div>
      </div>
    </div>

    <div class="layout">
      <section class="panel">
        <canvas id="categoryChart" height="320"></canvas>
      </section>

      <section class="panel">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Description</th>
              <th>Category</th>
              <th>Amount</th>
            </tr>
          </thead>
          <tbody id="transactionTable"></tbody>
        </table>
        <div id="emptyState" class="empty" style="display:none;">No transactions matched this filter.</div>
      </section>
    </div>

    <section class="panel full-width-panel">
      <div class="chart-group-row">
        <strong>Spend over time</strong>
      </div>
      <canvas id="trendChart" height="120"></canvas>
    </section>

    <section class="panel full-width-panel" style="margin-top:18px;">
      <strong>Top merchants</strong>
      <table class="merchant-table" id="merchantTable" style="margin-top:14px;">
        <thead>
          <tr>
            <th>Merchant</th>
            <th>Visits</th>
            <th>Total</th>
            <th style="width:30%"></th>
          </tr>
        </thead>
        <tbody id="merchantBody"></tbody>
      </table>
    </section>
  </div>

  <script>
    const state = {
      rows: [],
      summary: null,
      selectedCategory: null,
      chart: null,
      trendChart: null,
    };

    function formatCurrency(amount) {
      return new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(amount);
    }

    function defaultDates() {
      const today = new Date();
      const first = new Date(today.getFullYear(), today.getMonth(), 1);
      document.getElementById("fromDate").value = first.toISOString().slice(0, 10);
      document.getElementById("toDate").value = today.toISOString().slice(0, 10);
    }

    async function fetchRows() {
      const since = document.getElementById("fromDate").value;
      const until = document.getElementById("toDate").value;
      const excludeRefunds = document.getElementById("excludeRefunds").checked;
      const minAmount = document.getElementById("minAmount").value;
      const groupBy = document.getElementById("groupBy").value;

      const params = new URLSearchParams({ since, until });
      if (excludeRefunds) params.set("exclude_refunds", "1");
      if (minAmount) params.set("min_amount", minAmount);

      const summaryParams = new URLSearchParams({ since, until, group_by: groupBy });
      if (excludeRefunds) summaryParams.set("exclude_refunds", "1");
      if (minAmount) summaryParams.set("min_amount", minAmount);

      const [rows, summary] = await Promise.all([
        fetch(`/api/spending?${params}`).then((r) => { if (!r.ok) throw new Error(`Spending fetch failed (${r.status})`); return r.json(); }),
        fetch(`/api/spending/summary?${summaryParams}`).then((r) => { if (!r.ok) throw new Error(`Summary fetch failed (${r.status})`); return r.json(); }),
      ]);

      state.rows = rows;
      state.summary = summary;
      state.selectedCategory = null;
      render();
    }

    function filteredRows() {
      const search = document.getElementById("searchBox").value.trim().toLowerCase();
      return state.rows.filter((row) => {
        const desc = `${row.description || ""} ${row.message || ""}`.toLowerCase();
        const matchesSearch = !search || desc.includes(search);
        const matchesCategory = !state.selectedCategory || (row.category || "Uncategorised") === state.selectedCategory;
        return matchesSearch && matchesCategory;
      });
    }

    function categorySpend(rows) {
      const map = new Map();
      rows.forEach((row) => {
        const amount = Number(row.amount);
        if (amount >= 0) return;
        const category = row.category || "Uncategorised";
        map.set(category, (map.get(category) || 0) + Math.abs(amount));
      });
      return [...map.entries()].sort((a, b) => b[1] - a[1]);
    }

    function renderChart(rows) {
      const series = categorySpend(rows);
      const labels = series.map(([label]) => label);
      const data = series.map(([, total]) => total);
      const canvas = document.getElementById("categoryChart");
      if (state.chart) state.chart.destroy();
      state.chart = new Chart(canvas, {
        type: "bar",
        data: {
          labels,
          datasets: [{
            label: "Spend",
            data,
            borderRadius: 8,
            backgroundColor: labels.map((label) =>
              label === state.selectedCategory ? "rgba(191, 95, 54, 0.95)" : "rgba(191, 95, 54, 0.55)"
            ),
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          onClick(_event, elements) {
            if (!elements.length) return;
            const index = elements[0].index;
            const nextCategory = labels[index];
            state.selectedCategory = state.selectedCategory === nextCategory ? null : nextCategory;
            render();
          },
          scales: {
            x: { ticks: { color: "#67727e" } },
            y: { ticks: { color: "#67727e", callback(value) { return formatCurrency(value); } } },
          },
        },
      });
    }

    function renderTrendChart() {
      if (!state.summary) return;
      const periods = state.summary.periods;
      const canvas = document.getElementById("trendChart");
      if (state.trendChart) state.trendChart.destroy();
      if (!periods.length) return;
      state.trendChart = new Chart(canvas, {
        type: "line",
        data: {
          labels: periods.map((p) => p.period),
          datasets: [{
            label: "Spend",
            data: periods.map((p) => p.total_spend),
            borderColor: "rgba(191, 95, 54, 0.9)",
            backgroundColor: "rgba(191, 95, 54, 0.08)",
            fill: true,
            tension: 0.35,
            pointRadius: 4,
            pointBackgroundColor: "rgba(191, 95, 54, 0.9)",
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { ticks: { color: "#67727e" } },
            y: { ticks: { color: "#67727e", callback(value) { return formatCurrency(value); } } },
          },
        },
      });
    }

    function renderMerchants() {
      if (!state.summary) return;
      const merchants = state.summary.merchants;
      const tbody = document.getElementById("merchantBody");
      if (!merchants.length) {
        tbody.innerHTML = `<tr><td colspan="4" class="empty">No data.</td></tr>`;
        return;
      }
      const max = merchants[0].total_spend;
      tbody.innerHTML = merchants.map((m) => {
        const pct = max > 0 ? (m.total_spend / max) * 100 : 0;
        return `
          <tr>
            <td>${m.description}</td>
            <td>${m.transaction_count}</td>
            <td>${formatCurrency(m.total_spend)}</td>
            <td><div class="merchant-bar-wrap"><div class="merchant-bar" style="width:${pct.toFixed(1)}%"></div></div></td>
          </tr>
        `;
      }).join("");
    }

    function renderSummaryCards() {
      if (!state.summary) return;
      const total = state.summary.total_spend;
      const count = state.summary.transaction_count;
      const avg = count > 0 ? total / count : 0;
      document.getElementById("totalSpend").textContent = formatCurrency(total);
      document.getElementById("totalCount").textContent = count;
      document.getElementById("avgSpend").textContent = formatCurrency(avg);

      // Month-over-month delta: compare last two periods
      const periods = state.summary.periods;
      const momEl = document.getElementById("momDelta");
      if (periods.length >= 2) {
        const prev = periods[periods.length - 2].total_spend;
        const curr = periods[periods.length - 1].total_spend;
        const diff = curr - prev;
        const pct = prev > 0 ? ((diff / prev) * 100).toFixed(1) : null;
        if (pct !== null) {
          const sign = diff > 0 ? "+" : "";
          momEl.textContent = `${sign}${pct}% vs prior period`;
          momEl.className = `delta ${diff > 0 ? "up" : "down"}`;
        } else {
          momEl.textContent = "";
        }
      } else {
        momEl.textContent = "";
      }
    }

    function renderTable(rows) {
      const tbody = document.getElementById("transactionTable");
      const emptyState = document.getElementById("emptyState");
      if (!rows.length) {
        tbody.innerHTML = "";
        emptyState.style.display = "block";
        return;
      }
      emptyState.style.display = "none";
      tbody.innerHTML = rows.map((row) => {
        const amount = Number(row.amount);
        const date = (row.settled_at || row.created_at || "").slice(0, 10);
        return `
          <tr>
            <td>${date}</td>
            <td>${row.description || ""}</td>
            <td>${row.category || "Uncategorised"}</td>
            <td class="${amount < 0 ? "amount-negative" : "amount-positive"}">${formatCurrency(amount)}</td>
          </tr>
        `;
      }).join("");
    }

    function render() {
      const rows = filteredRows();
      renderChart(rows);
      renderTable(rows);
      renderTrendChart();
      renderMerchants();
      renderSummaryCards();
      document.getElementById("activeFilter") && (document.getElementById("activeFilter").textContent =
        state.selectedCategory ? `Filtered by ${state.selectedCategory}` : "All categories");
    }

    document.getElementById("fetchButton").addEventListener("click", () => {
      fetchRows().catch((error) => window.alert(error.message));
    });

    document.getElementById("searchBox").addEventListener("input", render);

    defaultDates();
    fetchRows().catch((error) => window.alert(error.message));
  </script>
</body>
```

- [ ] **Step 3: Remove the `<div class="totals">` block from the old HTML**

The summary cards now replace the old `totalSpend` + `activeFilter` elements. Make sure there is no duplicate `id="totalSpend"` or `id="activeFilter"` in the final file. Check after editing:

```bash
grep -c 'id="totalSpend"' spending.html
```

Expected: `1`

- [ ] **Step 4: Open browser and verify**

```bash
python server.py &
open http://localhost:5000/spending
```

Check:
- Summary cards show total spend, transaction count, avg
- Month-over-month delta appears if there are 2+ periods
- Category bar chart still works and filters the table on click
- Trend line chart renders periods over time
- Top merchants table shows top 20 with inline bar
- "Exclude refunds" checkbox and "Min amount" filter work on re-fetch
- "Group trend by" dropdown switches between month/week on re-fetch

Kill server: `kill %1`

- [ ] **Step 5: Commit**

```bash
git add spending.html
git commit -m "feat: spending insights — trend chart, merchant table, summary cards, noise filters"
```

---

## Self-review

**Spec coverage:**
- [x] `bill_types.csv` with provider info for all 5 slugs — Task 1
- [x] Provider enriched in history API response — Task 2
- [x] `bill_cycles.csv` `provider` column — Task 2
- [x] History in its own tab — Task 4
- [x] Group-by month / bill type / person — Task 4
- [x] `/api/spending/summary` with group_by, exclude_refunds, min_amount — Task 3
- [x] Trend chart (spend over time, weekly/monthly) — Task 5
- [x] Month-over-month comparison — Task 5 (delta card)
- [x] Merchant drill-down — Task 5
- [x] Noise filters (exclude refunds, min amount) — Tasks 3 + 5

**Placeholder scan:** No TBDs or TODOs found.

**Type consistency:**
- `state.summary.periods` used in `renderTrendChart()` and `renderSummaryCards()` — matches shape returned by `/api/spending/summary`
- `state.summary.merchants` used in `renderMerchants()` — matches shape
- `row.provider` in history table — matches field added in Task 2
- `historyGroupBy` select ID matches `document.getElementById("historyGroupBy")` references
- `tab-bills` / `tab-history` IDs match `data-tab` attributes
