# Finance Dashboard Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Net Worth, Portfolio, CGT Calculator, and House Planner pages to the existing Flask/vanilla JS finance dashboard, with a persistent nav bar across all pages.

**Architecture:** Flask serves static HTML files directly via `send_file`; all new pages are self-contained HTML with inline CSS/JS using Chart.js from CDN. New CSV files in `data/` act as the data layer; no database. A single `server.py` handles all endpoints — new routes appended to the existing file without restructuring it.

**Tech Stack:** Python/Flask, vanilla JS, Chart.js (CDN), openpyxl (already installed in venv), CSV files.

---

## Key Facts (read before implementing)

- **Venv:** `venv/` at project root — use `venv/bin/python3` / `venv/bin/flask`
- **Excel file:** `data/Net worth calculator.xlsx` — sheet `Historical`, columns: idx0=Date(datetime), idx1=Everyday(cash), idx2=Savings, idx3=SelfWealth, idx4=IBKR, idx5=Total, idx6=WoW%, idx7=Portfolio
- **Super:** No super column in Excel. Import endpoint accepts `super_aud` param from UI (pre-filled from last CSV row, currently 67806.44). `total_aud` = cash_aud + investments_aud + super_aud (recalculated, not from Excel col5)
- **House planner timeline:** uses `cash_aud` from latest `networth.csv` row only — NOT super. FHSS (section B) feeds as a separate stacked layer.
- **Design language:** bills.html uses CSS vars `--bg, --panel, --ink, --muted, --accent, --ok, --danger, --radius, --shadow`. Match this aesthetic across all new pages.
- **Existing routes unchanged:** `/, /bills, /spending, /api/status, /sync, /api/bills, /api/bills/history, POST /api/bills, POST /api/bills/<id>/override, /api/spending, /api/spending/summary`

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `server.py` | Modify | Add 7 new routes |
| `bills.html` | Modify | Add nav bar |
| `spending.html` | Modify | Add nav bar |
| `networth.html` | Create | Net worth page |
| `portfolio.html` | Create | Portfolio page |
| `cgt.html` | Create | CGT calculator page |
| `house.html` | Create | House planner page |
| `data/networth.csv` | Create | date,cash_aud,investments_aud,super_aud,total_aud |
| `data/holdings.csv` | Create | ticker,platform,currency,units,cost_base_aud,current_price_aud,current_value_aud,unrealised_gain_aud,acquisition_date |
| `data/attribution.csv` | Create | date,deposits,interest,investment_gains,fx_movement |
| `.gitignore` | Modify | Add new entries |

---

## Task 1: Create empty CSV data files and update .gitignore

**Files:**
- Create: `data/networth.csv`
- Create: `data/holdings.csv`
- Create: `data/attribution.csv`
- Modify: `.gitignore`

- [ ] **Step 1: Create the three CSV files with headers only**

```bash
echo "date,cash_aud,investments_aud,super_aud,total_aud" > data/networth.csv
echo "ticker,platform,currency,units,cost_base_aud,current_price_aud,current_value_aud,unrealised_gain_aud,acquisition_date" > data/holdings.csv
echo "date,deposits,interest,investment_gains,fx_movement" > data/attribution.csv
```

- [ ] **Step 2: Update .gitignore**

Open `.gitignore` and replace its entire contents with:

```
config.json
data/transactions_spending.csv
data/transactions_2up.csv
data/networth.csv
data/holdings.csv
__pycache__/
*.pyc
venv/
data/Net worth calculator.xlsx
```

- [ ] **Step 3: Verify**

```bash
head -1 data/networth.csv data/holdings.csv data/attribution.csv
```

Expected output:
```
==> data/networth.csv <==
date,cash_aud,investments_aud,super_aud,total_aud

==> data/holdings.csv <==
ticker,platform,currency,units,cost_base_aud,current_price_aud,current_value_aud,unrealised_gain_aud,acquisition_date

==> data/attribution.csv <==
date,deposits,interest,investment_gains,fx_movement
```

---

## Task 2: Add nav bar to bills.html and spending.html

**Files:**
- Modify: `bills.html`
- Modify: `spending.html`

The nav bar is a shared HTML+CSS snippet injected at the top of `<body>` on every page. It highlights the active page.

- [ ] **Step 1: Define the nav bar snippet**

The nav bar HTML to insert immediately after `<body>` on every page:

```html
<nav class="sitenav">
  <a href="/networth" class="sitenav-link">Net Worth</a>
  <a href="/portfolio" class="sitenav-link">Portfolio</a>
  <a href="/cgt" class="sitenav-link">CGT</a>
  <a href="/house" class="sitenav-link">House</a>
  <a href="/bills" class="sitenav-link">Bills</a>
  <a href="/spending" class="sitenav-link">Spending</a>
</nav>
```

The nav bar CSS to insert inside `<style>` (before the closing `</style>` tag) on every page:

```css
.sitenav {
  display: flex;
  gap: 4px;
  padding: 10px 20px;
  background: rgba(255,255,255,0.6);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid rgba(31,42,31,0.08);
  position: sticky;
  top: 0;
  z-index: 100;
}
.sitenav-link {
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 0.88rem;
  font-weight: 500;
  color: var(--muted);
  text-decoration: none;
  transition: background 0.15s, color 0.15s;
}
.sitenav-link:hover { background: var(--accent-soft); color: var(--ink); }
.sitenav-link.active { background: var(--accent); color: #fff; }
```

Active-link JS to insert just before `</body>` on every page:

```html
<script>
  document.querySelectorAll('.sitenav-link').forEach(a => {
    if (a.getAttribute('href') === location.pathname) a.classList.add('active');
  });
</script>
```

- [ ] **Step 2: Apply to bills.html**

In `bills.html`:
1. Add the CSS block inside `<style>` before `</style>`
2. Add the nav HTML immediately after `<body>`
3. Add the active-link script just before `</body>`

- [ ] **Step 3: Apply to spending.html**

Same three insertions in `spending.html`. Note that `spending.html` uses `--muted: #67727e` and `--accent-soft: rgba(191, 95, 54, 0.14)` — the nav will inherit those, which is fine (each page has its own palette).

- [ ] **Step 4: Smoke test**

```bash
venv/bin/python3 server.py &
# Open http://localhost:5000/bills — nav bar appears, Bills link is highlighted
# Open http://localhost:5000/spending — nav bar appears, Spending link is highlighted
kill %1
```

---

## Task 3: Add new Flask routes to server.py

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Add imports at the top of server.py**

Add to the existing import block (after `from pathlib import Path`):

```python
from datetime import datetime as dt_class
from openpyxl import load_workbook
```

- [ ] **Step 2: Add data path constants**

After the existing `BILL_CYCLES_PATH` / `BILL_TYPES_PATH` constants, add:

```python
NETWORTH_CSV = DATA_DIR / "networth.csv"
HOLDINGS_CSV = DATA_DIR / "holdings.csv"
EXCEL_PATH = DATA_DIR / "Net worth calculator.xlsx"
NETWORTH_FIELDS = ["date", "cash_aud", "investments_aud", "super_aud", "total_aud"]
HOLDINGS_FIELDS = [
    "ticker", "platform", "currency", "units",
    "cost_base_aud", "current_price_aud", "current_value_aud",
    "unrealised_gain_aud", "acquisition_date",
]
```

- [ ] **Step 3: Add the networth import helper function**

Add this function before the route definitions (e.g. after `group_spending_by_period`):

```python
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
        # super only applied to the most recent row; historical rows get 0
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

    # Apply super_aud to the most recent row and recalculate its total
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
```

- [ ] **Step 4: Add the seven new routes**

Append these routes to `server.py` before `if __name__ == "__main__":`:

```python
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
```

- [ ] **Step 5: Verify server starts**

```bash
venv/bin/python3 server.py &
sleep 1
curl -s http://localhost:5000/api/networth | head -c 100
curl -s http://localhost:5000/api/holdings | head -c 100
kill %1
```

Expected: both return `[]` (empty arrays — CSVs have headers only).

---

## Task 4: Build networth.html

**Files:**
- Create: `networth.html`

This page shows a net worth line chart (Chart.js), summary cards, an "Import from Excel" button with a super input, and an attribution panel (hidden if `attribution.csv` is empty).

- [ ] **Step 1: Create networth.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Finance – Net Worth</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root {
      --bg: #f6f1e7;
      --panel: rgba(255,250,242,0.92);
      --panel-strong: #fffaf2;
      --ink: #1f2a1f;
      --muted: #667166;
      --line: rgba(31,42,31,0.1);
      --accent: #246a4d;
      --accent-soft: rgba(36,106,77,0.14);
      --danger: #b44532;
      --ok: #2d7a4a;
      --ok-soft: rgba(45,122,74,0.12);
      --shadow: 0 24px 60px rgba(60,53,40,0.12);
      --radius: 24px;
      --font-display: "Avenir Next","Segoe UI",sans-serif;
      --font-body: "IBM Plex Sans","Segoe UI",sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh;
      font-family: var(--font-body); color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(255,227,186,0.55), transparent 34%),
        radial-gradient(circle at top right, rgba(181,230,211,0.5), transparent 28%),
        linear-gradient(180deg,#f8f4ec 0%,#f3eadb 100%);
    }
    .sitenav {
      display: flex; gap: 4px; padding: 10px 20px;
      background: rgba(255,255,255,0.6); backdrop-filter: blur(8px);
      border-bottom: 1px solid rgba(31,42,31,0.08);
      position: sticky; top: 0; z-index: 100;
    }
    .sitenav-link {
      padding: 6px 14px; border-radius: 20px; font-size: 0.88rem;
      font-weight: 500; color: var(--muted); text-decoration: none;
      transition: background 0.15s, color 0.15s;
    }
    .sitenav-link:hover { background: var(--accent-soft); color: var(--ink); }
    .sitenav-link.active { background: var(--accent); color: #fff; }
    .shell { max-width: 1200px; margin: 0 auto; padding: 32px 20px 60px; }
    h1 {
      margin: 0 0 4px; font-family: var(--font-display);
      font-size: clamp(2rem,3vw,3rem); letter-spacing: -0.04em;
    }
    .subtitle { color: var(--muted); margin: 0 0 28px; font-size: 1rem; }
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px; margin-bottom: 24px;
    }
    .card {
      background: var(--panel); border-radius: var(--radius);
      box-shadow: var(--shadow); padding: 22px 24px;
      border: 1px solid rgba(255,255,255,0.7);
    }
    .card-label { font-size: 0.82rem; color: var(--muted); margin-bottom: 6px; }
    .card-value { font-size: 1.65rem; font-weight: 700; letter-spacing: -0.02em; }
    .card-change { font-size: 0.85rem; margin-top: 4px; }
    .up { color: var(--ok); } .down { color: var(--danger); }
    .panel {
      background: var(--panel); border-radius: var(--radius);
      box-shadow: var(--shadow); border: 1px solid rgba(255,255,255,0.7);
      padding: 24px; margin-bottom: 20px;
    }
    .panel-header {
      display: flex; justify-content: space-between; align-items: center;
      margin-bottom: 18px;
    }
    .panel-title { font-weight: 600; font-size: 1rem; }
    .toggles { display: flex; gap: 8px; flex-wrap: wrap; }
    .toggle-btn {
      padding: 5px 14px; border-radius: 16px; border: 1.5px solid var(--line);
      background: transparent; cursor: pointer; font-size: 0.83rem;
      color: var(--muted); font-family: var(--font-body); transition: all 0.15s;
    }
    .toggle-btn.on { border-color: var(--accent); background: var(--accent-soft); color: var(--ink); }
    .chart-wrap { position: relative; height: 340px; }
    .import-row {
      display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap;
      margin-bottom: 20px;
    }
    .import-row label { font-size: 0.85rem; color: var(--muted); display: grid; gap: 5px; }
    .import-row input[type=number] {
      padding: 9px 13px; border-radius: 12px; border: 1.5px solid var(--line);
      font-size: 0.95rem; background: var(--panel-strong); font-family: var(--font-body);
      color: var(--ink); width: 160px;
    }
    button {
      padding: 9px 20px; border-radius: 12px; border: none;
      background: var(--accent); color: #fff; font-size: 0.9rem;
      font-weight: 600; cursor: pointer; font-family: var(--font-body);
      transition: opacity 0.15s;
    }
    button:hover { opacity: 0.85; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    .import-status { font-size: 0.85rem; color: var(--muted); align-self: center; }
    .hidden { display: none !important; }
  </style>
</head>
<body>
<nav class="sitenav">
  <a href="/networth" class="sitenav-link">Net Worth</a>
  <a href="/portfolio" class="sitenav-link">Portfolio</a>
  <a href="/cgt" class="sitenav-link">CGT</a>
  <a href="/house" class="sitenav-link">House</a>
  <a href="/bills" class="sitenav-link">Bills</a>
  <a href="/spending" class="sitenav-link">Spending</a>
</nav>
<div class="shell">
  <h1>Net Worth</h1>
  <p class="subtitle">Historical wealth tracking — updated weekly</p>

  <div class="cards">
    <div class="card">
      <div class="card-label">Total net worth</div>
      <div class="card-value" id="card-total">—</div>
    </div>
    <div class="card">
      <div class="card-label">30-day change</div>
      <div class="card-value" id="card-30d">—</div>
      <div class="card-change" id="card-30d-pct"></div>
    </div>
    <div class="card">
      <div class="card-label">All-time growth</div>
      <div class="card-value" id="card-alltime">—</div>
      <div class="card-change" id="card-alltime-pct"></div>
    </div>
    <div class="card">
      <div class="card-label">Cash</div>
      <div class="card-value" id="card-cash">—</div>
    </div>
    <div class="card">
      <div class="card-label">Investments</div>
      <div class="card-value" id="card-inv">—</div>
    </div>
    <div class="card">
      <div class="card-label">Super</div>
      <div class="card-value" id="card-super">—</div>
    </div>
  </div>

  <div class="import-row">
    <label>
      Super balance (AUD)
      <input type="number" id="super-input" step="0.01" placeholder="67806.44">
    </label>
    <button id="import-btn" onclick="doImport()">Import from Excel</button>
    <span class="import-status" id="import-status"></span>
  </div>

  <div class="panel">
    <div class="panel-header">
      <span class="panel-title">Net Worth Over Time</span>
      <div class="toggles">
        <button class="toggle-btn on" id="tog-total" onclick="toggleSeries('total')">Total</button>
        <button class="toggle-btn" id="tog-cash" onclick="toggleSeries('cash')">Cash</button>
        <button class="toggle-btn" id="tog-inv" onclick="toggleSeries('inv')">Investments</button>
        <button class="toggle-btn" id="tog-super" onclick="toggleSeries('super')">Super</button>
      </div>
    </div>
    <div class="chart-wrap"><canvas id="nw-chart"></canvas></div>
  </div>

  <div class="panel hidden" id="attribution-panel">
    <div class="panel-header"><span class="panel-title">Attribution Breakdown</span></div>
    <div id="attribution-body"></div>
  </div>
</div>

<script>
const fmt = v => '$' + Number(v).toLocaleString('en-AU', {minimumFractionDigits: 0, maximumFractionDigits: 0});
const fmtPct = v => (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%';

let chart = null;
let rows = [];
const seriesOn = { total: true, cash: false, inv: false, super: false };

const SERIES = {
  total: { key: 'total_aud', label: 'Total', color: '#246a4d' },
  cash:  { key: 'cash_aud',  label: 'Cash',  color: '#bf8f36' },
  inv:   { key: 'investments_aud', label: 'Investments', color: '#3a6abf' },
  super: { key: 'super_aud', label: 'Super', color: '#8a46bf' },
};

async function load() {
  const res = await fetch('/api/networth');
  rows = await res.json();
  if (!rows.length) return;

  // Pre-fill super input from latest row
  const latest = rows[rows.length - 1];
  const lastSuper = parseFloat(latest.super_aud) || 0;
  if (lastSuper > 0) document.getElementById('super-input').value = lastSuper.toFixed(2);

  updateCards();
  renderChart();
  loadAttribution();
}

function updateCards() {
  if (!rows.length) return;
  const latest = rows[rows.length - 1];
  document.getElementById('card-total').textContent = fmt(latest.total_aud);
  document.getElementById('card-cash').textContent = fmt(latest.cash_aud);
  document.getElementById('card-inv').textContent = fmt(latest.investments_aud);
  document.getElementById('card-super').textContent = fmt(latest.super_aud);

  // 30-day change: find row closest to 30 days ago
  const now = new Date(latest.date);
  const target = new Date(now); target.setDate(target.getDate() - 30);
  const ref30 = rows.reduce((best, r) => {
    const d = new Date(r.date);
    return Math.abs(d - target) < Math.abs(new Date(best.date) - target) ? r : best;
  }, rows[0]);
  const delta30 = parseFloat(latest.total_aud) - parseFloat(ref30.total_aud);
  const pct30 = delta30 / parseFloat(ref30.total_aud);
  const el30 = document.getElementById('card-30d');
  el30.textContent = (delta30 >= 0 ? '+' : '') + fmt(Math.abs(delta30));
  el30.className = 'card-value ' + (delta30 >= 0 ? 'up' : 'down');
  document.getElementById('card-30d-pct').textContent = fmtPct(pct30);
  document.getElementById('card-30d-pct').className = 'card-change ' + (pct30 >= 0 ? 'up' : 'down');

  // All-time
  const first = rows[0];
  const deltaAll = parseFloat(latest.total_aud) - parseFloat(first.total_aud);
  const pctAll = deltaAll / parseFloat(first.total_aud);
  const elAll = document.getElementById('card-alltime');
  elAll.textContent = (deltaAll >= 0 ? '+' : '') + fmt(Math.abs(deltaAll));
  elAll.className = 'card-value ' + (deltaAll >= 0 ? 'up' : 'down');
  document.getElementById('card-alltime-pct').textContent = fmtPct(pctAll);
  document.getElementById('card-alltime-pct').className = 'card-change ' + (pctAll >= 0 ? 'up' : 'down');
}

function renderChart() {
  const labels = rows.map(r => r.date);
  const datasets = Object.entries(SERIES)
    .filter(([k]) => seriesOn[k])
    .map(([, s]) => ({
      label: s.label,
      data: rows.map(r => parseFloat(r[s.key]) || 0),
      borderColor: s.color,
      backgroundColor: s.color + '18',
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.3,
      fill: false,
    }));

  if (chart) { chart.destroy(); }
  chart = new Chart(document.getElementById('nw-chart'), {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: datasets.length > 1 } },
      scales: {
        x: { ticks: { maxTicksLimit: 12, color: '#667166' }, grid: { color: 'rgba(31,42,31,0.06)' } },
        y: {
          ticks: { color: '#667166', callback: v => '$' + (v/1000).toFixed(0) + 'k' },
          grid: { color: 'rgba(31,42,31,0.06)' }
        }
      }
    }
  });
}

function toggleSeries(key) {
  seriesOn[key] = !seriesOn[key];
  document.getElementById('tog-' + key).classList.toggle('on', seriesOn[key]);
  if (rows.length) renderChart();
}

async function loadAttribution() {
  try {
    const res = await fetch('/api/attribution');
    const data = await res.json();
    if (!data || !data.length) return;
    document.getElementById('attribution-panel').classList.remove('hidden');
    document.getElementById('attribution-body').innerHTML =
      '<p style="color:var(--muted);font-size:0.9rem">Attribution data present (' + data.length + ' rows)</p>';
  } catch { /* attribution.csv absent or endpoint missing — hide panel */ }
}

async function doImport() {
  const btn = document.getElementById('import-btn');
  const status = document.getElementById('import-status');
  const superVal = parseFloat(document.getElementById('super-input').value) || 0;
  btn.disabled = true;
  status.textContent = 'Importing…';
  try {
    const res = await fetch('/api/networth/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ super_aud: superVal }),
    });
    const data = await res.json();
    if (data.ok) {
      status.textContent = `Imported ${data.imported} rows.`;
      await load();
    } else {
      status.textContent = 'Error: ' + data.error;
    }
  } catch (e) {
    status.textContent = 'Network error.';
  } finally {
    btn.disabled = false;
  }
}

load();
</script>
<script>
  document.querySelectorAll('.sitenav-link').forEach(a => {
    if (a.getAttribute('href') === location.pathname) a.classList.add('active');
  });
</script>
</body>
</html>
```

- [ ] **Step 2: Smoke test**

```bash
venv/bin/python3 server.py &
sleep 1
curl -s http://localhost:5000/networth | head -c 200
kill %1
```

Expected: HTML response starting with `<!DOCTYPE html>`

---

## Task 5: Test the Excel import endpoint

- [ ] **Step 1: Run a test import**

```bash
venv/bin/python3 server.py &
sleep 1
curl -s -X POST http://localhost:5000/api/networth/import \
  -H 'Content-Type: application/json' \
  -d '{"super_aud": 67806.44}'
```

Expected response:
```json
{"imported": 90, "ok": true}
```

- [ ] **Step 2: Verify CSV was written correctly**

```bash
head -3 data/networth.csv
tail -3 data/networth.csv
```

Expected — last row should be today's date with super included and recalculated total:
```
date,cash_aud,investments_aud,super_aud,total_aud
2024-08-23,15080.7,118473.68,0,133554.38
...
2026-05-15,28590.47,206448.0,67806.44,302844.91
```

- [ ] **Step 3: Re-run import to verify idempotency (no duplicates)**

```bash
curl -s -X POST http://localhost:5000/api/networth/import \
  -H 'Content-Type: application/json' \
  -d '{"super_aud": 67806.44}'
wc -l data/networth.csv
```

Expected: same row count as before (91 lines = 90 data rows + 1 header).

```bash
kill %1
```

---

## Task 6: Build portfolio.html

**Files:**
- Create: `portfolio.html`

- [ ] **Step 1: Create portfolio.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Finance – Portfolio</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root {
      --bg: #f6f1e7; --panel: rgba(255,250,242,0.92); --panel-strong: #fffaf2;
      --ink: #1f2a1f; --muted: #667166; --line: rgba(31,42,31,0.1);
      --accent: #246a4d; --accent-soft: rgba(36,106,77,0.14);
      --danger: #b44532; --ok: #2d7a4a; --ok-soft: rgba(45,122,74,0.12);
      --shadow: 0 24px 60px rgba(60,53,40,0.12); --radius: 24px;
      --font-display: "Avenir Next","Segoe UI",sans-serif;
      --font-body: "IBM Plex Sans","Segoe UI",sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; font-family: var(--font-body); color: var(--ink);
      background: radial-gradient(circle at top left,rgba(255,227,186,0.55),transparent 34%),
        radial-gradient(circle at top right,rgba(181,230,211,0.5),transparent 28%),
        linear-gradient(180deg,#f8f4ec 0%,#f3eadb 100%);
    }
    .sitenav {
      display: flex; gap: 4px; padding: 10px 20px;
      background: rgba(255,255,255,0.6); backdrop-filter: blur(8px);
      border-bottom: 1px solid rgba(31,42,31,0.08); position: sticky; top: 0; z-index: 100;
    }
    .sitenav-link {
      padding: 6px 14px; border-radius: 20px; font-size: 0.88rem;
      font-weight: 500; color: var(--muted); text-decoration: none; transition: all 0.15s;
    }
    .sitenav-link:hover { background: var(--accent-soft); color: var(--ink); }
    .sitenav-link.active { background: var(--accent); color: #fff; }
    .shell { max-width: 1200px; margin: 0 auto; padding: 32px 20px 60px; }
    h1 { margin: 0 0 4px; font-family: var(--font-display); font-size: clamp(2rem,3vw,3rem); letter-spacing: -0.04em; }
    .subtitle { color: var(--muted); margin: 0 0 28px; font-size: 1rem; }
    .cards { display: grid; grid-template-columns: repeat(auto-fit,minmax(200px,1fr)); gap: 16px; margin-bottom: 24px; }
    .card { background: var(--panel); border-radius: var(--radius); box-shadow: var(--shadow); padding: 22px 24px; border: 1px solid rgba(255,255,255,0.7); }
    .card-label { font-size: 0.82rem; color: var(--muted); margin-bottom: 6px; }
    .card-value { font-size: 1.65rem; font-weight: 700; letter-spacing: -0.02em; }
    .up { color: var(--ok); } .down { color: var(--danger); }
    .layout { display: grid; grid-template-columns: 1fr 320px; gap: 20px; align-items: start; }
    @media (max-width: 800px) { .layout { grid-template-columns: 1fr; } }
    .panel { background: var(--panel); border-radius: var(--radius); box-shadow: var(--shadow); border: 1px solid rgba(255,255,255,0.7); padding: 24px; }
    .panel-title { font-weight: 600; font-size: 1rem; margin-bottom: 16px; }
    table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    th { color: var(--muted); font-weight: 500; text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); font-size: 0.82rem; }
    td { padding: 10px 10px; border-bottom: 1px solid var(--line); }
    tr:last-child td { border-bottom: none; }
    .gain-pos { color: var(--ok); font-weight: 600; }
    .gain-neg { color: var(--danger); font-weight: 600; }
    .note { font-size: 0.8rem; color: var(--muted); margin-top: 12px; }
    .chart-wrap { position: relative; height: 300px; }
    .empty { color: var(--muted); font-size: 0.92rem; padding: 20px 0; }
  </style>
</head>
<body>
<nav class="sitenav">
  <a href="/networth" class="sitenav-link">Net Worth</a>
  <a href="/portfolio" class="sitenav-link">Portfolio</a>
  <a href="/cgt" class="sitenav-link">CGT</a>
  <a href="/house" class="sitenav-link">House</a>
  <a href="/bills" class="sitenav-link">Bills</a>
  <a href="/spending" class="sitenav-link">Spending</a>
</nav>
<div class="shell">
  <h1>Portfolio</h1>
  <p class="subtitle">Investment holdings — prices updated manually</p>

  <div class="cards">
    <div class="card">
      <div class="card-label">Total portfolio value</div>
      <div class="card-value" id="card-value">—</div>
    </div>
    <div class="card">
      <div class="card-label">Total unrealised gain</div>
      <div class="card-value" id="card-gain">—</div>
    </div>
    <div class="card">
      <div class="card-label">Holdings</div>
      <div class="card-value" id="card-count">—</div>
    </div>
  </div>

  <div class="layout">
    <div class="panel">
      <div class="panel-title">Holdings</div>
      <div id="holdings-body"><p class="empty">No holdings in data/holdings.csv yet. Add rows manually to get started.</p></div>
      <p class="note">Prices entered manually in data/holdings.csv</p>
    </div>
    <div class="panel">
      <div class="panel-title">Allocation</div>
      <div class="chart-wrap"><canvas id="pie-chart"></canvas></div>
      <div id="pie-empty" class="empty" style="text-align:center">No data</div>
    </div>
  </div>
</div>

<script>
const fmt = v => '$' + Number(v).toLocaleString('en-AU', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const PIE_COLORS = ['#246a4d','#3a6abf','#bf8f36','#bf4a46','#8a46bf','#46a8bf','#6abf46','#bf6a46'];

async function load() {
  const res = await fetch('/api/holdings');
  const rows = await res.json();

  const totalValue = rows.reduce((s, r) => s + parseFloat(r.current_value_aud || 0), 0);
  const totalGain = rows.reduce((s, r) => s + parseFloat(r.unrealised_gain_aud || 0), 0);

  document.getElementById('card-value').textContent = fmt(totalValue);
  const gainEl = document.getElementById('card-gain');
  gainEl.textContent = (totalGain >= 0 ? '+' : '') + fmt(Math.abs(totalGain));
  gainEl.className = 'card-value ' + (totalGain >= 0 ? 'up' : 'down');
  document.getElementById('card-count').textContent = rows.length;

  if (!rows.length) return;

  // Table
  const tbody = rows.map(r => {
    const gain = parseFloat(r.unrealised_gain_aud || 0);
    const cls = gain >= 0 ? 'gain-pos' : 'gain-neg';
    const pct = parseFloat(r.cost_base_aud) > 0 ? (gain / parseFloat(r.cost_base_aud) * 100).toFixed(1) + '%' : '—';
    return `<tr>
      <td><strong>${r.ticker}</strong></td>
      <td>${r.platform}</td>
      <td>${r.currency}</td>
      <td>${parseFloat(r.units).toLocaleString()}</td>
      <td>${fmt(r.cost_base_aud)}</td>
      <td>${fmt(r.current_value_aud)}</td>
      <td class="${cls}">${(gain >= 0 ? '+' : '') + fmt(Math.abs(gain))} (${pct})</td>
      <td>${r.acquisition_date}</td>
    </tr>`;
  }).join('');

  document.getElementById('holdings-body').innerHTML = `
    <table>
      <thead><tr>
        <th>Ticker</th><th>Platform</th><th>Currency</th><th>Units</th>
        <th>Cost Base</th><th>Current Value</th><th>Unrealised G/L</th><th>Acquired</th>
      </tr></thead>
      <tbody>${tbody}</tbody>
    </table>`;

  // Pie chart — group by ticker, sum current_value_aud
  const byTicker = {};
  rows.forEach(r => {
    byTicker[r.ticker] = (byTicker[r.ticker] || 0) + parseFloat(r.current_value_aud || 0);
  });
  const labels = Object.keys(byTicker);
  const values = labels.map(k => byTicker[k]);

  document.getElementById('pie-empty').style.display = 'none';
  new Chart(document.getElementById('pie-chart'), {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{ data: values, backgroundColor: PIE_COLORS.slice(0, labels.length), borderWidth: 0 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { font: { size: 12 }, color: '#667166' } },
        tooltip: { callbacks: { label: ctx => ' ' + fmt(ctx.raw) } }
      }
    }
  });
}

load();
</script>
<script>
  document.querySelectorAll('.sitenav-link').forEach(a => {
    if (a.getAttribute('href') === location.pathname) a.classList.add('active');
  });
</script>
</body>
</html>
```

- [ ] **Step 2: Smoke test**

```bash
venv/bin/python3 server.py &
sleep 1
curl -s http://localhost:5000/portfolio | grep -c "Portfolio"
kill %1
```

Expected: `1` or more

---

## Task 7: Build cgt.html

**Files:**
- Create: `cgt.html`

All CGT logic is in vanilla JS. Holdings are loaded via `GET /api/holdings` to populate the parcel checkboxes.

- [ ] **Step 1: Create cgt.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Finance – CGT Calculator</title>
  <style>
    :root {
      --bg: #f6f1e7; --panel: rgba(255,250,242,0.92); --panel-strong: #fffaf2;
      --ink: #1f2a1f; --muted: #667166; --line: rgba(31,42,31,0.1);
      --accent: #246a4d; --accent-soft: rgba(36,106,77,0.14);
      --danger: #b44532; --ok: #2d7a4a;
      --shadow: 0 24px 60px rgba(60,53,40,0.12); --radius: 24px;
      --font-display: "Avenir Next","Segoe UI",sans-serif;
      --font-body: "IBM Plex Sans","Segoe UI",sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; font-family: var(--font-body); color: var(--ink);
      background: radial-gradient(circle at top left,rgba(255,227,186,0.55),transparent 34%),
        radial-gradient(circle at top right,rgba(181,230,211,0.5),transparent 28%),
        linear-gradient(180deg,#f8f4ec 0%,#f3eadb 100%);
    }
    .sitenav {
      display: flex; gap: 4px; padding: 10px 20px;
      background: rgba(255,255,255,0.6); backdrop-filter: blur(8px);
      border-bottom: 1px solid rgba(31,42,31,0.08); position: sticky; top: 0; z-index: 100;
    }
    .sitenav-link {
      padding: 6px 14px; border-radius: 20px; font-size: 0.88rem;
      font-weight: 500; color: var(--muted); text-decoration: none; transition: all 0.15s;
    }
    .sitenav-link:hover { background: var(--accent-soft); color: var(--ink); }
    .sitenav-link.active { background: var(--accent); color: #fff; }
    .shell { max-width: 900px; margin: 0 auto; padding: 32px 20px 60px; }
    h1 { margin: 0 0 4px; font-family: var(--font-display); font-size: clamp(2rem,3vw,3rem); letter-spacing: -0.04em; }
    .subtitle { color: var(--muted); margin: 0 0 28px; font-size: 1rem; }
    .panel { background: var(--panel); border-radius: var(--radius); box-shadow: var(--shadow); border: 1px solid rgba(255,255,255,0.7); padding: 28px; margin-bottom: 20px; }
    .panel-title { font-weight: 600; font-size: 1rem; margin-bottom: 18px; }
    .form-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(200px,1fr)); gap: 16px; margin-bottom: 20px; }
    .field { display: grid; gap: 6px; }
    .field label { font-size: 0.83rem; color: var(--muted); }
    .field input { padding: 10px 14px; border-radius: 12px; border: 1.5px solid var(--line); font-size: 0.95rem; background: var(--panel-strong); font-family: var(--font-body); color: var(--ink); width: 100%; }
    .field input:focus { outline: none; border-color: var(--accent); }
    .parcels { display: grid; gap: 8px; margin-bottom: 20px; }
    .parcel-row {
      display: flex; align-items: center; gap: 12px;
      padding: 10px 14px; border-radius: 12px; border: 1.5px solid var(--line);
      background: var(--panel-strong); cursor: pointer; transition: border-color 0.15s;
    }
    .parcel-row:hover { border-color: var(--accent); }
    .parcel-row.selected { border-color: var(--accent); background: var(--accent-soft); }
    .parcel-row input[type=checkbox] { width: 16px; height: 16px; accent-color: var(--accent); }
    .parcel-info { flex: 1; font-size: 0.9rem; }
    .parcel-ticker { font-weight: 600; }
    .parcel-detail { color: var(--muted); font-size: 0.82rem; }
    .discount-badge {
      font-size: 0.75rem; padding: 3px 8px; border-radius: 10px;
      background: var(--ok-soft); color: var(--ok); font-weight: 600;
    }
    .no-discount { background: rgba(180,69,50,0.1); color: var(--danger); }
    button.calc-btn {
      padding: 11px 28px; border-radius: 14px; border: none;
      background: var(--accent); color: #fff; font-size: 0.95rem;
      font-weight: 600; cursor: pointer; font-family: var(--font-body); transition: opacity 0.15s;
    }
    button.calc-btn:hover { opacity: 0.85; }
    .results { display: grid; grid-template-columns: repeat(auto-fit,minmax(180px,1fr)); gap: 14px; margin-top: 24px; }
    .result-card { background: var(--panel-strong); border-radius: 18px; padding: 18px 20px; border: 1px solid var(--line); }
    .result-label { font-size: 0.8rem; color: var(--muted); margin-bottom: 5px; }
    .result-value { font-size: 1.4rem; font-weight: 700; }
    .comparison { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 20px; }
    @media (max-width: 600px) { .comparison { grid-template-columns: 1fr; } }
    .comp-card { background: var(--panel-strong); border-radius: 18px; padding: 20px; border: 1.5px solid var(--line); }
    .comp-card h3 { margin: 0 0 12px; font-size: 0.95rem; }
    .comp-row { display: flex; justify-content: space-between; font-size: 0.88rem; padding: 4px 0; border-bottom: 1px solid var(--line); }
    .comp-row:last-child { border-bottom: none; font-weight: 700; }
    .hidden { display: none !important; }
    .empty { color: var(--muted); font-size: 0.9rem; }
    .up { color: var(--ok); } .down { color: var(--danger); }
  </style>
</head>
<body>
<nav class="sitenav">
  <a href="/networth" class="sitenav-link">Net Worth</a>
  <a href="/portfolio" class="sitenav-link">Portfolio</a>
  <a href="/cgt" class="sitenav-link">CGT</a>
  <a href="/house" class="sitenav-link">House</a>
  <a href="/bills" class="sitenav-link">Bills</a>
  <a href="/spending" class="sitenav-link">Spending</a>
</nav>
<div class="shell">
  <h1>CGT Calculator</h1>
  <p class="subtitle">Estimate capital gains tax on a hypothetical sale</p>

  <div class="panel">
    <div class="panel-title">Inputs</div>
    <div class="form-grid">
      <div class="field">
        <label>Sale date</label>
        <input type="date" id="sale-date">
      </div>
      <div class="field">
        <label>Marginal tax rate (%)</label>
        <input type="number" id="tax-rate" value="39" step="0.5" min="0" max="100">
      </div>
    </div>

    <div class="panel-title" style="margin-top:4px">Select parcels to sell</div>
    <div id="parcels-list"><p class="empty">Loading holdings…</p></div>

    <div style="margin-top:16px">
      <button class="calc-btn" onclick="calculate()">Calculate CGT</button>
    </div>

    <div id="results-wrap" class="hidden">
      <div class="results">
        <div class="result-card">
          <div class="result-label">Sale proceeds</div>
          <div class="result-value" id="r-proceeds">—</div>
        </div>
        <div class="result-card">
          <div class="result-label">Cost base</div>
          <div class="result-value" id="r-cost">—</div>
        </div>
        <div class="result-card">
          <div class="result-label">Gross gain</div>
          <div class="result-value" id="r-gross">—</div>
        </div>
        <div class="result-card">
          <div class="result-label">Taxable gain (after 50% discount if eligible)</div>
          <div class="result-value" id="r-taxable">—</div>
        </div>
        <div class="result-card">
          <div class="result-label">CGT payable</div>
          <div class="result-value down" id="r-cgt">—</div>
        </div>
        <div class="result-card">
          <div class="result-label">Net proceeds after CGT</div>
          <div class="result-value up" id="r-net">—</div>
        </div>
      </div>

      <div style="margin-top:24px">
        <div class="panel-title">Sell now vs in 6 months</div>
        <div class="comparison">
          <div class="comp-card" id="comp-now">
            <h3>Sell now (<span id="comp-now-date"></span>)</h3>
            <div id="comp-now-body"></div>
          </div>
          <div class="comp-card" id="comp-6m">
            <h3>Sell in 6 months (<span id="comp-6m-date"></span>)</h3>
            <div id="comp-6m-body"></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
const fmt = v => '$' + Number(v).toLocaleString('en-AU', {minimumFractionDigits: 2, maximumFractionDigits: 2});
let holdings = [];

// Set default sale date to today
document.getElementById('sale-date').value = new Date().toISOString().slice(0, 10);

async function load() {
  const res = await fetch('/api/holdings');
  holdings = await res.json();
  renderParcels(new Date().toISOString().slice(0, 10));
}

function daysBetween(a, b) {
  return (new Date(b) - new Date(a)) / 86400000;
}

function discountEligible(acquisitionDate, saleDate) {
  return daysBetween(acquisitionDate, saleDate) > 365;
}

function renderParcels(saleDate) {
  const el = document.getElementById('parcels-list');
  if (!holdings.length) {
    el.innerHTML = '<p class="empty">No holdings in data/holdings.csv. Add rows manually to get started.</p>';
    return;
  }
  el.innerHTML = holdings.map((h, i) => {
    const eligible = discountEligible(h.acquisition_date, saleDate);
    const badge = eligible
      ? '<span class="discount-badge">50% discount eligible</span>'
      : '<span class="discount-badge no-discount">No discount yet</span>';
    return `<label class="parcel-row" id="parcel-row-${i}">
      <input type="checkbox" id="chk-${i}" onchange="toggleParcel(${i})">
      <div class="parcel-info">
        <div class="parcel-ticker">${h.ticker} <span style="font-weight:400;color:var(--muted)">${h.platform}</span></div>
        <div class="parcel-detail">${h.units} units · cost base ${fmt(h.cost_base_aud)} · current value ${fmt(h.current_value_aud)} · acquired ${h.acquisition_date}</div>
      </div>
      ${badge}
    </label>`;
  }).join('');
}

function toggleParcel(i) {
  document.getElementById('parcel-row-' + i).classList.toggle(
    'selected', document.getElementById('chk-' + i).checked
  );
}

document.getElementById('sale-date').addEventListener('change', e => {
  renderParcels(e.target.value);
});

function calcForDate(selectedHoldings, saleDate, taxRate) {
  let proceeds = 0, costBase = 0, taxableGain = 0;
  selectedHoldings.forEach(h => {
    const val = parseFloat(h.current_value_aud);
    const cost = parseFloat(h.cost_base_aud);
    const gain = val - cost;
    proceeds += val;
    costBase += cost;
    const eligible = discountEligible(h.acquisition_date, saleDate);
    taxableGain += eligible && gain > 0 ? gain * 0.5 : gain;
  });
  const grossGain = proceeds - costBase;
  const cgt = Math.max(taxableGain * (taxRate / 100), 0);
  const net = proceeds - cgt;
  return { proceeds, costBase, grossGain, taxableGain, cgt, net };
}

function compHtml(r) {
  return `
    <div class="comp-row"><span>Sale proceeds</span><span>${fmt(r.proceeds)}</span></div>
    <div class="comp-row"><span>Cost base</span><span>${fmt(r.costBase)}</span></div>
    <div class="comp-row"><span>Gross gain</span><span>${fmt(r.grossGain)}</span></div>
    <div class="comp-row"><span>Taxable gain</span><span>${fmt(r.taxableGain)}</span></div>
    <div class="comp-row"><span>CGT payable</span><span style="color:var(--danger)">${fmt(r.cgt)}</span></div>
    <div class="comp-row"><span>Net proceeds</span><span style="color:var(--ok)">${fmt(r.net)}</span></div>`;
}

function calculate() {
  const saleDate = document.getElementById('sale-date').value;
  const taxRate = parseFloat(document.getElementById('tax-rate').value) || 39;
  const selected = holdings.filter((_, i) => document.getElementById('chk-' + i)?.checked);

  if (!selected.length) { alert('Select at least one parcel.'); return; }

  const now = calcForDate(selected, saleDate, taxRate);

  document.getElementById('r-proceeds').textContent = fmt(now.proceeds);
  document.getElementById('r-cost').textContent = fmt(now.costBase);
  document.getElementById('r-gross').textContent = fmt(now.grossGain);
  document.getElementById('r-taxable').textContent = fmt(now.taxableGain);
  document.getElementById('r-cgt').textContent = fmt(now.cgt);
  document.getElementById('r-net').textContent = fmt(now.net);

  // 6-month comparison
  const d6m = new Date(saleDate);
  d6m.setMonth(d6m.getMonth() + 6);
  const date6m = d6m.toISOString().slice(0, 10);
  const future = calcForDate(selected, date6m, taxRate);

  document.getElementById('comp-now-date').textContent = saleDate;
  document.getElementById('comp-6m-date').textContent = date6m;
  document.getElementById('comp-now-body').innerHTML = compHtml(now);
  document.getElementById('comp-6m-body').innerHTML = compHtml(future);

  document.getElementById('results-wrap').classList.remove('hidden');
}

load();
</script>
<script>
  document.querySelectorAll('.sitenav-link').forEach(a => {
    if (a.getAttribute('href') === location.pathname) a.classList.add('active');
  });
</script>
</body>
</html>
```

- [ ] **Step 2: Smoke test**

```bash
venv/bin/python3 server.py &
sleep 1
curl -s http://localhost:5000/cgt | grep -c "CGT"
kill %1
```

Expected: `1` or more.

---

## Task 8: Build house.html — Section A & B (Property target + FHSS calculator)

**Files:**
- Create: `house.html` (partial — sections A and B)

- [ ] **Step 1: Create house.html with sections A and B**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Finance – House Planner</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root {
      --bg: #f6f1e7; --panel: rgba(255,250,242,0.92); --panel-strong: #fffaf2;
      --ink: #1f2a1f; --muted: #667166; --line: rgba(31,42,31,0.1);
      --accent: #246a4d; --accent-soft: rgba(36,106,77,0.14);
      --danger: #b44532; --ok: #2d7a4a; --ok-soft: rgba(45,122,74,0.12);
      --warn: #bf8f36; --warn-soft: rgba(191,143,54,0.14);
      --shadow: 0 24px 60px rgba(60,53,40,0.12); --radius: 24px;
      --font-display: "Avenir Next","Segoe UI",sans-serif;
      --font-body: "IBM Plex Sans","Segoe UI",sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; font-family: var(--font-body); color: var(--ink);
      background: radial-gradient(circle at top left,rgba(255,227,186,0.55),transparent 34%),
        radial-gradient(circle at top right,rgba(181,230,211,0.5),transparent 28%),
        linear-gradient(180deg,#f8f4ec 0%,#f3eadb 100%);
    }
    .sitenav {
      display: flex; gap: 4px; padding: 10px 20px;
      background: rgba(255,255,255,0.6); backdrop-filter: blur(8px);
      border-bottom: 1px solid rgba(31,42,31,0.08); position: sticky; top: 0; z-index: 100;
    }
    .sitenav-link {
      padding: 6px 14px; border-radius: 20px; font-size: 0.88rem;
      font-weight: 500; color: var(--muted); text-decoration: none; transition: all 0.15s;
    }
    .sitenav-link:hover { background: var(--accent-soft); color: var(--ink); }
    .sitenav-link.active { background: var(--accent); color: #fff; }
    .shell { max-width: 1100px; margin: 0 auto; padding: 32px 20px 60px; }
    h1 { margin: 0 0 4px; font-family: var(--font-display); font-size: clamp(2rem,3vw,3rem); letter-spacing: -0.04em; }
    .subtitle { color: var(--muted); margin: 0 0 28px; font-size: 1rem; }
    details { margin-bottom: 16px; }
    summary {
      background: var(--panel); border-radius: var(--radius); box-shadow: var(--shadow);
      border: 1px solid rgba(255,255,255,0.7); padding: 20px 24px;
      font-weight: 600; font-size: 1.05rem; cursor: pointer; list-style: none;
      display: flex; justify-content: space-between; align-items: center;
      transition: background 0.15s;
    }
    summary::-webkit-details-marker { display: none; }
    summary::after { content: '▾'; font-size: 0.9rem; color: var(--muted); transition: transform 0.2s; }
    details[open] summary::after { transform: rotate(180deg); }
    details[open] summary { border-radius: var(--radius) var(--radius) 0 0; border-bottom: 1px solid var(--line); }
    .section-body {
      background: var(--panel); border: 1px solid rgba(255,255,255,0.7);
      border-top: none; border-radius: 0 0 var(--radius) var(--radius);
      box-shadow: var(--shadow); padding: 28px;
    }
    .form-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(200px,1fr)); gap: 16px; margin-bottom: 24px; }
    .field { display: grid; gap: 6px; }
    .field label { font-size: 0.83rem; color: var(--muted); }
    .field input, .field select {
      padding: 10px 14px; border-radius: 12px; border: 1.5px solid var(--line);
      font-size: 0.95rem; background: var(--panel-strong);
      font-family: var(--font-body); color: var(--ink); width: 100%;
    }
    .field input:focus, .field select:focus { outline: none; border-color: var(--accent); }
    .output-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(180px,1fr)); gap: 14px; margin-bottom: 20px; }
    .output-card { background: var(--panel-strong); border-radius: 18px; padding: 18px 20px; border: 1px solid var(--line); }
    .output-label { font-size: 0.8rem; color: var(--muted); margin-bottom: 5px; }
    .output-value { font-size: 1.35rem; font-weight: 700; }
    .alert {
      padding: 12px 16px; border-radius: 14px; font-size: 0.88rem; margin-bottom: 16px;
    }
    .alert-warn { background: var(--warn-soft); color: var(--warn); border: 1px solid rgba(191,143,54,0.3); }
    .alert-ok { background: var(--ok-soft); color: var(--ok); border: 1px solid rgba(45,122,74,0.3); }
    .gap-bar-wrap { margin: 16px 0; }
    .gap-label { font-size: 0.83rem; color: var(--muted); margin-bottom: 6px; }
    .gap-bar { height: 10px; border-radius: 6px; background: var(--line); overflow: hidden; }
    .gap-fill { height: 100%; border-radius: 6px; background: var(--accent); transition: width 0.4s; }
    button.recalc {
      padding: 10px 22px; border-radius: 12px; border: none;
      background: var(--accent); color: #fff; font-size: 0.9rem;
      font-weight: 600; cursor: pointer; font-family: var(--font-body);
      transition: opacity 0.15s; margin-bottom: 20px;
    }
    button.recalc:hover { opacity: 0.85; }
    table { width: 100%; border-collapse: collapse; font-size: 0.88rem; margin-top: 16px; }
    th { color: var(--muted); font-weight: 500; text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); font-size: 0.8rem; }
    td { padding: 8px 10px; border-bottom: 1px solid var(--line); }
    tr:last-child td { border-bottom: none; font-weight: 700; background: var(--accent-soft); }
    .side-by-side { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }
    @media (max-width: 600px) { .side-by-side { grid-template-columns: 1fr; } }
    .compare-card { background: var(--panel-strong); border-radius: 16px; padding: 18px; border: 1px solid var(--line); }
    .compare-card h4 { margin: 0 0 10px; font-size: 0.9rem; }
    .compare-row { display: flex; justify-content: space-between; font-size: 0.85rem; padding: 4px 0; border-bottom: 1px solid var(--line); }
    .compare-row:last-child { border: none; font-weight: 700; }
    .up { color: var(--ok); } .down { color: var(--danger); }
  </style>
</head>
<body>
<nav class="sitenav">
  <a href="/networth" class="sitenav-link">Net Worth</a>
  <a href="/portfolio" class="sitenav-link">Portfolio</a>
  <a href="/cgt" class="sitenav-link">CGT</a>
  <a href="/house" class="sitenav-link">House</a>
  <a href="/bills" class="sitenav-link">Bills</a>
  <a href="/spending" class="sitenav-link">Spending</a>
</nav>
<div class="shell">
  <h1>House Planner</h1>
  <p class="subtitle">Plan your path to property ownership</p>

  <!-- Section A: Property Target -->
  <details open>
    <summary>A. Property Target</summary>
    <div class="section-body">
      <div class="form-grid">
        <div class="field">
          <label>Target property price ($)</label>
          <input type="number" id="prop-price" value="850000" step="5000" oninput="calcA()">
        </div>
        <div class="field">
          <label>Deposit % (default 20%)</label>
          <input type="number" id="deposit-pct" value="20" min="5" max="50" step="1" oninput="calcA()">
        </div>
      </div>

      <div id="lmi-alert" class="alert alert-warn" style="display:none">
        ⚠ Deposit &lt; 20% — Lenders Mortgage Insurance (LMI) will apply. Budget an extra ~1–3% of the loan value.
      </div>

      <div class="output-grid">
        <div class="output-card"><div class="output-label">Deposit required</div><div class="output-value" id="a-deposit">—</div></div>
        <div class="output-card"><div class="output-label">Stamp duty (VIC)</div><div class="output-value" id="a-stamp">—</div></div>
        <div class="output-card"><div class="output-label">Total cash needed</div><div class="output-value" id="a-total-cash">—</div></div>
        <div class="output-card"><div class="output-label">Current savings (cash)</div><div class="output-value" id="a-savings">—</div></div>
        <div class="output-card"><div class="output-label">Gap to target</div><div class="output-value" id="a-gap">—</div></div>
      </div>

      <div class="gap-bar-wrap">
        <div class="gap-label">Progress to deposit target</div>
        <div class="gap-bar"><div class="gap-fill" id="a-progress" style="width:0%"></div></div>
      </div>
    </div>
  </details>

  <!-- Section B: FHSS Calculator -->
  <details open>
    <summary>B. FHSS Calculator</summary>
    <div class="section-body">
      <div class="form-grid">
        <div class="field">
          <label>Annual contribution ($)</label>
          <input type="number" id="fhss-contrib" value="15000" step="1000" oninput="calcB()">
        </div>
        <div class="field">
          <label>Start year</label>
          <input type="number" id="fhss-start" value="2026" min="2024" max="2035" oninput="calcB()">
        </div>
        <div class="field">
          <label>Withdrawal year (planned purchase year)</label>
          <input type="number" id="fhss-withdraw" value="2029" min="2025" max="2040" oninput="calcB()">
        </div>
        <div class="field">
          <label>Income ($)</label>
          <input type="number" id="fhss-income" value="150000" step="5000" oninput="calcB()">
        </div>
        <div class="field">
          <label>Marginal rate (%) — auto-calculated, editable</label>
          <input type="number" id="fhss-rate" step="0.5" oninput="calcB()">
        </div>
      </div>

      <div class="output-grid">
        <div class="output-card"><div class="output-label">Total gross contributed</div><div class="output-value" id="b-gross">—</div></div>
        <div class="output-card"><div class="output-label">FHSS net to deposit</div><div class="output-value up" id="b-net">—</div></div>
        <div class="output-card"><div class="output-label">Cash saving equivalent</div><div class="output-value" id="b-cash-equiv">—</div></div>
        <div class="output-card"><div class="output-label">FHSS advantage</div><div class="output-value up" id="b-advantage">—</div></div>
      </div>

      <div id="fhss-cap-alert" class="alert alert-warn" style="display:none">
        ⚠ $50,000 lifetime cap reached — contributions above the cap are excluded from FHSS.
      </div>

      <table id="fhss-table">
        <thead><tr>
          <th>Year</th>
          <th>Gross contrib</th>
          <th>Into super (after 15% tax)</th>
          <th>Cumulative in super</th>
          <th>Deemed earnings</th>
          <th>Gross withdrawal</th>
          <th>Withdrawal tax</th>
          <th>Net to deposit</th>
        </tr></thead>
        <tbody id="fhss-tbody"></tbody>
      </table>

      <div style="margin-top:24px">
        <div style="font-weight:600;margin-bottom:12px;font-size:0.95rem">FHSS vs cash saving — side-by-side</div>
        <div class="side-by-side">
          <div class="compare-card">
            <h4>FHSS route</h4>
            <div id="fhss-compare-fhss"></div>
          </div>
          <div class="compare-card">
            <h4>Cash saving (same gross income)</h4>
            <div id="fhss-compare-cash"></div>
          </div>
        </div>
      </div>
    </div>
  </details>

  <!-- Section C: Timeline (populated in Task 9) -->
  <details>
    <summary>C. Timeline &amp; Savings Rate</summary>
    <div class="section-body" id="section-c-body">
      <div class="form-grid">
        <div class="field">
          <label>Monthly savings contribution ($)</label>
          <input type="number" id="c-monthly" value="3000" step="500" oninput="calcC()">
        </div>
      </div>
      <div class="output-grid">
        <div class="output-card"><div class="output-label">Months to deposit target</div><div class="output-value" id="c-months">—</div></div>
        <div class="output-card"><div class="output-label">Projected purchase date</div><div class="output-value" id="c-date">—</div></div>
      </div>
      <div style="position:relative;height:320px;margin-top:16px"><canvas id="timeline-chart"></canvas></div>
    </div>
  </details>

  <!-- Section D: CGT impact (populated in Task 9) -->
  <details>
    <summary>D. CGT Impact of Liquidating Portfolio</summary>
    <div class="section-body" id="section-d-body">
      <div class="output-grid">
        <div class="output-card"><div class="output-label">Total portfolio value</div><div class="output-value" id="d-port-value">—</div></div>
        <div class="output-card"><div class="output-label">Estimated CGT payable</div><div class="output-value down" id="d-cgt">—</div></div>
        <div class="output-card"><div class="output-label">Net proceeds after CGT</div><div class="output-value up" id="d-net">—</div></div>
      </div>
      <label style="display:flex;align-items:center;gap:10px;font-size:0.9rem;cursor:pointer;margin-top:8px">
        <input type="checkbox" id="d-include" onchange="calcC()" style="accent-color:var(--accent);width:16px;height:16px">
        Include portfolio net proceeds in timeline (section C)
      </label>
    </div>
  </details>
</div>

<script>
const fmt = v => '$' + Number(v).toLocaleString('en-AU', {minimumFractionDigits: 0, maximumFractionDigits: 0});
const fmt2 = v => '$' + Number(v).toLocaleString('en-AU', {minimumFractionDigits: 2, maximumFractionDigits: 2});

// ── Shared state ──────────────────────────────────────────────────────────────
let currentCash = 0;        // from latest networth.csv row (cash_aud only)
let totalCashNeeded = 0;    // from section A
let fhssNetToDeposit = 0;   // from section B
let portfolioNetAfterCGT = 0;
let timelineChart = null;

// ── Stamp duty (VIC first home buyer) ────────────────────────────────────────
function stampDuty(price) {
  if (price <= 600000) return 0;
  if (price <= 750000) {
    // Graduated concession: scales from 0 at $600k to full duty at $750k
    const fullDuty = price * 0.055;
    const concessionFraction = (price - 600000) / 150000;
    return fullDuty * concessionFraction;
  }
  return price * 0.055;
}

// ── Marginal rate auto-calc (ATO 2024-25) ────────────────────────────────────
function marginalRate(income) {
  if (income <= 18200) return 0;
  if (income <= 45000) return 19 + 2;  // +2% Medicare
  if (income <= 135000) return 32.5 + 2;
  if (income <= 190000) return 37 + 2;
  return 45 + 2;
}

// ── Section A ─────────────────────────────────────────────────────────────────
function calcA() {
  const price = parseFloat(document.getElementById('prop-price').value) || 0;
  const pct = parseFloat(document.getElementById('deposit-pct').value) || 20;
  const deposit = price * pct / 100;
  const stamp = stampDuty(price);
  const totalCash = deposit + stamp;
  totalCashNeeded = totalCash;

  document.getElementById('a-deposit').textContent = fmt(deposit);
  document.getElementById('a-stamp').textContent = fmt(stamp);
  document.getElementById('a-total-cash').textContent = fmt(totalCash);
  document.getElementById('a-savings').textContent = fmt(currentCash);
  const gap = Math.max(totalCash - currentCash, 0);
  document.getElementById('a-gap').textContent = fmt(gap);
  document.getElementById('lmi-alert').style.display = pct < 20 ? 'block' : 'none';
  const progress = totalCash > 0 ? Math.min(currentCash / totalCash * 100, 100) : 0;
  document.getElementById('a-progress').style.width = progress.toFixed(1) + '%';
  calcC();
}

// ── Section B — FHSS ─────────────────────────────────────────────────────────
function calcB() {
  const annualContrib = parseFloat(document.getElementById('fhss-contrib').value) || 0;
  const startYear = parseInt(document.getElementById('fhss-start').value) || 2026;
  const withdrawYear = parseInt(document.getElementById('fhss-withdraw').value) || 2029;
  const income = parseFloat(document.getElementById('fhss-income').value) || 0;

  // Auto-fill marginal rate if not manually edited
  const rateInput = document.getElementById('fhss-rate');
  if (!rateInput.dataset.manual) {
    rateInput.value = marginalRate(income);
  }
  const margRate = parseFloat(rateInput.value) || 39;

  const LIFETIME_CAP = 50000;
  const SUPER_TAX = 0.15;
  const DEEMED_RATE = 0.0477;

  let rows = [];
  let cumulativeGross = 0;
  let cumulativeInSuper = 0;
  let capHit = false;

  for (let year = startYear; year < withdrawYear; year++) {
    const yearsToWithdraw = withdrawYear - year;
    let gross = annualContrib;
    if (cumulativeGross + gross > LIFETIME_CAP) {
      gross = Math.max(LIFETIME_CAP - cumulativeGross, 0);
      capHit = true;
    }
    cumulativeGross += gross;
    const intoSuper = gross * (1 - SUPER_TAX);
    cumulativeInSuper += intoSuper;
    const deemedEarnings = cumulativeInSuper * Math.pow(1 + DEEMED_RATE, yearsToWithdraw) - cumulativeInSuper;
    const grossWithdrawal = cumulativeInSuper + deemedEarnings;
    // Withdrawal tax: marginal rate minus 30% ATO offset
    const withdrawTaxRate = Math.max(margRate - 30, 0) / 100;
    const withdrawalTax = grossWithdrawal * withdrawTaxRate;
    const netToDeposit = grossWithdrawal - withdrawalTax;
    rows.push({ year, gross, intoSuper, cumulativeInSuper, deemedEarnings, grossWithdrawal, withdrawalTax, netToDeposit });
  }

  document.getElementById('fhss-cap-alert').style.display = capHit ? 'block' : 'none';

  const lastRow = rows[rows.length - 1];
  const totalNet = lastRow ? lastRow.netToDeposit : 0;
  fhssNetToDeposit = totalNet;

  document.getElementById('b-gross').textContent = fmt(cumulativeGross);
  document.getElementById('b-net').textContent = fmt(totalNet);

  // Cash equivalent: same gross income, after-tax cash savings
  const cashEquiv = cumulativeGross * (1 - margRate / 100);
  document.getElementById('b-cash-equiv').textContent = fmt(cashEquiv);
  const advantage = totalNet - cashEquiv;
  const advEl = document.getElementById('b-advantage');
  advEl.textContent = (advantage >= 0 ? '+' : '') + fmt(advantage);
  advEl.className = 'output-value ' + (advantage >= 0 ? 'up' : 'down');

  // Table
  const tbody = rows.map((r, i) => {
    const isLast = i === rows.length - 1;
    return `<tr ${isLast ? 'style="font-weight:700"' : ''}>
      <td>${r.year}</td>
      <td>${fmt2(r.gross)}</td>
      <td>${fmt2(r.intoSuper)}</td>
      <td>${fmt2(r.cumulativeInSuper)}</td>
      <td>${fmt2(r.deemedEarnings)}</td>
      <td>${fmt2(r.grossWithdrawal)}</td>
      <td>${fmt2(r.withdrawalTax)}</td>
      <td>${fmt2(r.netToDeposit)}</td>
    </tr>`;
  }).join('');
  document.getElementById('fhss-tbody').innerHTML = tbody;

  // Side-by-side compare
  const fhssHtml = `
    <div class="compare-row"><span>Gross contributed</span><span>${fmt2(cumulativeGross)}</span></div>
    <div class="compare-row"><span>Super tax (15%)</span><span style="color:var(--danger)">-${fmt2(cumulativeGross * SUPER_TAX)}</span></div>
    <div class="compare-row"><span>Deemed earnings</span><span style="color:var(--ok)">+${lastRow ? fmt2(lastRow.deemedEarnings) : fmt2(0)}</span></div>
    <div class="compare-row"><span>Withdrawal tax</span><span style="color:var(--danger)">-${lastRow ? fmt2(lastRow.withdrawalTax) : fmt2(0)}</span></div>
    <div class="compare-row"><span>Net to deposit</span><span style="color:var(--ok)">${fmt2(totalNet)}</span></div>`;
  document.getElementById('fhss-compare-fhss').innerHTML = fhssHtml;

  const cashHtml = `
    <div class="compare-row"><span>Gross income</span><span>${fmt2(cumulativeGross)}</span></div>
    <div class="compare-row"><span>Income tax (${margRate}%)</span><span style="color:var(--danger)">-${fmt2(cumulativeGross * margRate / 100)}</span></div>
    <div class="compare-row"><span>Net cash saved</span><span>${fmt2(cashEquiv)}</span></div>
    <div class="compare-row"><span>vs FHSS</span><span class="${advantage >= 0 ? 'up' : 'down'}">${advantage >= 0 ? 'FHSS wins by ' + fmt2(advantage) : 'Cash wins by ' + fmt2(-advantage)}</span></div>`;
  document.getElementById('fhss-compare-cash').innerHTML = cashHtml;

  calcC();
}

// Set up manual-edit flag on tax rate input
document.getElementById('fhss-rate').addEventListener('input', function() {
  this.dataset.manual = '1';
});

// ── Section C — Timeline ──────────────────────────────────────────────────────
function calcC() {
  const monthly = parseFloat(document.getElementById('c-monthly').value) || 0;
  const includePortfolio = document.getElementById('d-include').checked;
  const target = totalCashNeeded;

  const startCash = currentCash + (includePortfolio ? portfolioNetAfterCGT : 0);
  const gap = Math.max(target - startCash - fhssNetToDeposit, 0);
  const months = monthly > 0 ? Math.ceil(gap / monthly) : Infinity;

  if (months === Infinity || months > 600) {
    document.getElementById('c-months').textContent = '—';
    document.getElementById('c-date').textContent = 'Increase savings rate';
  } else {
    const purchaseDate = new Date();
    purchaseDate.setMonth(purchaseDate.getMonth() + months);
    document.getElementById('c-months').textContent = months;
    document.getElementById('c-date').textContent = purchaseDate.toLocaleDateString('en-AU', { month: 'long', year: 'numeric' });
  }

  renderTimelineChart(monthly, startCash, target, months);
}

function renderTimelineChart(monthly, startCash, target, totalMonths) {
  const cap = Math.min(totalMonths === Infinity ? 120 : totalMonths + 12, 120);
  const labels = [];
  const cashData = [];
  const fhssData = [];

  for (let m = 0; m <= cap; m++) {
    const d = new Date();
    d.setMonth(d.getMonth() + m);
    labels.push(d.toLocaleDateString('en-AU', { month: 'short', year: '2-digit' }));
    cashData.push(Math.min(startCash + monthly * m, target));
    // FHSS accrues linearly to fhssNetToDeposit by totalMonths
    fhssData.push(totalMonths > 0 ? Math.min(fhssNetToDeposit * m / Math.max(totalMonths, 1), fhssNetToDeposit) : 0);
  }

  if (timelineChart) timelineChart.destroy();
  timelineChart = new Chart(document.getElementById('timeline-chart'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Cash savings',
          data: cashData,
          borderColor: '#246a4d',
          backgroundColor: 'rgba(36,106,77,0.12)',
          fill: true,
          tension: 0.2,
          pointRadius: 0,
          borderWidth: 2,
        },
        {
          label: 'FHSS',
          data: fhssData,
          borderColor: '#8a46bf',
          backgroundColor: 'rgba(138,70,191,0.1)',
          fill: true,
          tension: 0.2,
          pointRadius: 0,
          borderWidth: 2,
        },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true },
        annotation: {},
      },
      scales: {
        x: { ticks: { maxTicksLimit: 12, color: '#667166' }, grid: { color: 'rgba(31,42,31,0.06)' } },
        y: {
          ticks: { color: '#667166', callback: v => '$' + (v/1000).toFixed(0) + 'k' },
          grid: { color: 'rgba(31,42,31,0.06)' }
        }
      }
    }
  });
}

// ── Section D — CGT impact ────────────────────────────────────────────────────
async function loadPortfolio() {
  try {
    const res = await fetch('/api/holdings');
    const holdings = await res.json();
    if (!holdings.length) return;

    const today = new Date().toISOString().slice(0, 10);
    const TAX_RATE = parseFloat(document.getElementById('fhss-rate').value) || 39;
    let proceeds = 0, costBase = 0, taxableGain = 0;

    holdings.forEach(h => {
      const val = parseFloat(h.current_value_aud || 0);
      const cost = parseFloat(h.cost_base_aud || 0);
      const gain = val - cost;
      const daysDiff = (new Date(today) - new Date(h.acquisition_date)) / 86400000;
      const eligible = daysDiff > 365 && gain > 0;
      proceeds += val;
      costBase += cost;
      taxableGain += eligible ? gain * 0.5 : gain;
    });

    const cgt = Math.max(taxableGain * (TAX_RATE / 100), 0);
    portfolioNetAfterCGT = proceeds - cgt;

    document.getElementById('d-port-value').textContent = fmt(proceeds);
    document.getElementById('d-cgt').textContent = fmt(cgt);
    document.getElementById('d-net').textContent = fmt(portfolioNetAfterCGT);
    calcC();
  } catch (e) {
    console.error('Portfolio load error', e);
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────
async function boot() {
  try {
    const res = await fetch('/api/networth');
    const rows = await res.json();
    if (rows.length) {
      const latest = rows[rows.length - 1];
      currentCash = parseFloat(latest.cash_aud) || 0;
    }
  } catch (e) {
    console.error('Networth load error', e);
  }
  calcA();
  calcB();
  await loadPortfolio();
}

boot();
</script>
<script>
  document.querySelectorAll('.sitenav-link').forEach(a => {
    if (a.getAttribute('href') === location.pathname) a.classList.add('active');
  });
</script>
</body>
</html>
```

- [ ] **Step 2: Smoke test**

```bash
venv/bin/python3 server.py &
sleep 1
curl -s http://localhost:5000/house | grep -c "House Planner"
kill %1
```

Expected: `1` or more.

---

## Task 9: Update README.md and verify all routes

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace README.md content**

```markdown
# Finance Dashboard

Local Flask dashboard for Angus's personal finances. Tracks Up Bank transactions, house bill cycles, spending, net worth, investments, and property planning.

## Setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install flask requests python-dateutil openpyxl

cp config.example.json config.json
# Paste your Up Personal Access Token into "token"

python server.py
# Open http://localhost:5000
```

## Pages

| Page | URL | Description |
|------|-----|-------------|
| Net Worth | `/networth` | Weekly net worth chart + Excel import |
| Portfolio | `/portfolio` | Holdings table + allocation pie chart |
| CGT Calculator | `/cgt` | Estimate CGT on hypothetical sales |
| House Planner | `/house` | Deposit target, FHSS, timeline, CGT impact |
| Bills | `/bills` | House bill tracker with housemate splits |
| Spending | `/spending` | Personal spend report |

## Data Files

- `data/networth.csv` — weekly net worth snapshots (gitignored)
- `data/holdings.csv` — investment parcels (gitignored), update prices manually
- `data/attribution.csv` — optional attribution breakdown (commit-safe if present)
- `data/bills.csv` — bill definitions (committed)
- `data/housemates.csv` — housemate rent shares (committed)
- `data/Net worth calculator.xlsx` — source Excel file (gitignored)

## Net Worth Import

1. Open `/networth`
2. Enter your current super balance in the field
3. Click "Import from Excel"

The importer reads `data/Net worth calculator.xlsx` (sheet: `Historical`) and upserts rows into `data/networth.csv`. Re-running is safe — existing rows are overwritten by date, no duplicates.

## Tag Convention (Up Bank)

- Housemate: `angus`, `sean`, `alex`, `jarrod`, `ryan`
- Bill cycle: `{slug}-{mmm}-{yyyy}` e.g. `rent-apr-2026`
- Canonical slugs: `rent`, `elec`, `water`, `internet`, `gas`
```

- [ ] **Step 2: Full route verification**

```bash
venv/bin/python3 server.py &
sleep 1
for path in / /bills /spending /networth /portfolio /cgt /house /api/networth /api/holdings; do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5000$path)
  echo "$path → $code"
done
kill %1
```

Expected: all return `200`.

- [ ] **Step 3: Verify gitignore covers all sensitive files**

```bash
cat .gitignore
```

Expected to include: `config.json`, `data/transactions_spending.csv`, `data/transactions_2up.csv`, `data/networth.csv`, `data/holdings.csv`, `data/Net worth calculator.xlsx`, `__pycache__/`, `*.pyc`, `venv/`

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|------------|------|
| Nav bar on all pages | Task 2 + inline in Tasks 4–8 |
| `GET /networth` route | Task 3 |
| `GET /portfolio` route | Task 3 |
| `GET /cgt` route | Task 3 |
| `GET /house` route | Task 3 |
| `POST /api/networth/import` with Excel read | Task 3 |
| `GET /api/networth` | Task 3 |
| `GET /api/holdings` | Task 3 |
| Net worth line chart with toggleable series | Task 4 |
| Import button with super input pre-filled from last row | Task 4 |
| Summary cards: current total, 30-day change, all-time growth | Task 4 |
| Attribution panel hidden if empty | Task 4 |
| Excel import: cash = Everyday + Savings | Task 3 |
| Excel import: investments = SelfWealth + IBKR | Task 3 |
| Excel import: total = cash + investments + super (recalculated) | Task 3 |
| Super stamped on latest row only | Task 3 |
| Upsert by date (no duplicates) | Task 3 |
| Holdings table with green/red unrealised gain | Task 6 |
| Pie chart by ticker | Task 6 |
| Cards: total value, total unrealised gain | Task 6 |
| "Prices updated manually" note | Task 6 |
| CGT inputs: sale date, tax rate | Task 7 |
| Holdings checkboxes populated from `/api/holdings` | Task 7 |
| 50% discount if held > 12 months | Task 7 |
| CGT outputs: gross gain, taxable gain, CGT payable, net proceeds | Task 7 |
| "Sell now vs in 6 months" comparison | Task 7 |
| House A: deposit, stamp duty (VIC FHB rates), total cash needed | Task 8 |
| House A: LMI warning if < 20% | Task 8 |
| House A: current savings and gap from networth.csv (cash_aud only) | Task 8 |
| House B: FHSS table with all columns | Task 8 |
| House B: $50k lifetime cap enforcement | Task 8 |
| House B: FHSS vs cash side-by-side | Task 8 |
| House C: monthly savings → months to target + purchase date | Task 8 |
| House C: stacked area chart cash + FHSS | Task 8 |
| House D: portfolio CGT estimate | Task 8 |
| House D: "include in timeline" toggle | Task 8 |
| Empty CSVs with correct headers | Task 1 |
| .gitignore updated | Task 1 |
| README updated | Task 9 |
| Existing routes unchanged | Not modified |
