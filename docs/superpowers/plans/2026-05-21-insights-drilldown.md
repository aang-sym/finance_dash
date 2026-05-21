# Insights Drill-Down Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking any category or merchant row on `/insights` opens a slide-in panel showing a 6-month bar chart, top merchants within the category, and individual transactions for the selected month.

**Architecture:** All UI lives inside `insights.html` — no new page or route. Two new Flask endpoints (`GET /api/insights/category` and `GET /api/insights/merchant`) supply panel data. The panel is a fixed-position `<div id="drill-panel">` toggled via a CSS class, with a Chart.js bar chart instance managed separately from the main page charts.

**Tech Stack:** Flask (Python), Vanilla JS, Chart.js 4.4.0 (already loaded on the page), same CSV/config data layer as the rest of the dash.

---

## File Map

- **Modify:** `server.py` — add two endpoints after the existing `/api/insights/subscription-tag` route (~line 1590)
- **Modify:** `insights.html` — add panel HTML before `</body>`, panel CSS in `<style>`, click handlers on `<tr>` elements in `renderCategories()` and `renderMerchants()`, and four new JS functions: `fetchDrillDown()`, `renderPanel()`, `closePanel()`, chart instance cleanup

---

### Task 1: Add `GET /api/insights/category` endpoint to server.py

**Files:**
- Modify: `server.py` (insert after line ~1590, before `@app.get("/api/spending/summary")`)

This endpoint returns 6-month spend history for one category, top merchants within that category for the requested month, and all individual transactions in that category for the requested month.

- [ ] **Step 1: Open `server.py` on the `feature/spending-insights` branch**

The file is at `/Users/anguss/dev/finance_dash/server.py` but the working directory is on `feature/health-data-layer`. You must work on the `feature/spending-insights` branch. Check it out first:

```bash
git checkout feature/spending-insights
```

Confirm you're on the right branch: `git branch` should show `* feature/spending-insights`.

- [ ] **Step 2: Find the insertion point**

Search for the line:
```python
@app.get("/api/spending/summary")
```
Insert the new endpoint directly above this line.

- [ ] **Step 3: Insert the category endpoint**

Insert this code directly before `@app.get("/api/spending/summary")`:

```python
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
    account_ids = status.get("account_ids", {})
    internal_ids = {
        tid for tid in (
            account_ids.get("two_up", ""),
            account_ids.get("savings", ""),
            account_ids.get("grow", ""),
        ) if tid
    }

    # Build 6-month history window ending at month_str
    hist_months: List[str] = []
    d = datetime(year, month, 1)
    for _ in range(6):
        hist_months.append(f"{d.year}-{d.month:02d}")
        d = (d - timedelta(days=1)).replace(day=1)
    hist_months.reverse()

    all_rows = read_csv(DATA_DIR / "transactions_spending.csv")

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
```

- [ ] **Step 4: Verify the endpoint returns data**

```bash
curl -s "http://localhost:5001/api/insights/category?slug=takeaway&month=2026-04" | python3 -m json.tool | head -40
```

Expected: JSON with `slug`, `month`, `history` (6 items), `top_merchants` (array), `transactions` (array). If the server isn't running, restart it from the `feature/spending-insights` branch directory first.

- [ ] **Step 5: Commit**

```bash
git add server.py
git commit -m "feat(insights): add GET /api/insights/category endpoint"
```

---

### Task 2: Add `GET /api/insights/merchant` endpoint to server.py

**Files:**
- Modify: `server.py` (insert after the `api_insights_category` function from Task 1, still before `@app.get("/api/spending/summary")`)

- [ ] **Step 1: Find the insertion point**

After the `api_insights_category` function body from Task 1, insert the merchant endpoint directly below it.

- [ ] **Step 2: Insert the merchant endpoint**

```python
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
    account_ids = status.get("account_ids", {})
    internal_ids = {
        tid for tid in (
            account_ids.get("two_up", ""),
            account_ids.get("savings", ""),
            account_ids.get("grow", ""),
        ) if tid
    }

    hist_months: List[str] = []
    d = datetime(year, month, 1)
    for _ in range(6):
        hist_months.append(f"{d.year}-{d.month:02d}")
        d = (d - timedelta(days=1)).replace(day=1)
    hist_months.reverse()

    all_rows = read_csv(DATA_DIR / "transactions_spending.csv")
    sel_start, sel_end = _get_month_range(month_str)

    history: Dict[str, float] = {m: 0.0 for m in hist_months}
    transactions: List[Dict] = []

    for row in all_rows:
        amount = parse_float(row.get("amount")) or 0.0
        if amount >= 0:
            continue
        if row.get("transfer_account_id", "") in internal_ids:
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
```

- [ ] **Step 3: Verify the endpoint returns data**

```bash
curl -s "http://localhost:5001/api/insights/merchant?name=Revo+Fitness&month=2026-04" | python3 -m json.tool
```

Expected: JSON with `name`, `month`, `history` (6 items), `transactions` (array). Try a merchant you know exists in the data.

- [ ] **Step 4: Commit**

```bash
git add server.py
git commit -m "feat(insights): add GET /api/insights/merchant endpoint"
```

---

### Task 3: Add panel HTML and CSS to insights.html

**Files:**
- Modify: `insights.html` (add before `</body>`, add CSS in `<style>`)

- [ ] **Step 1: Add the panel CSS**

In `insights.html`, inside `<style>`, find the line:
```css
@media(max-width:768px){...}
```

Insert this block directly before that `@media` rule:

```css
/* drill-down panel */
.drill-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.55);z-index:200;opacity:0;pointer-events:none;transition:opacity 0.2s}
.drill-overlay.open{opacity:1;pointer-events:all}
.drill-panel{position:fixed;top:0;right:0;bottom:0;width:480px;max-width:100vw;background:var(--panel);border-left:1px solid var(--rule);z-index:201;transform:translateX(100%);transition:transform 0.22s cubic-bezier(.4,0,.2,1);overflow-y:auto;display:flex;flex-direction:column}
.drill-panel.open{transform:translateX(0)}
.drill-hdr{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--rule);flex-shrink:0}
.drill-title{font-size:13px;font-weight:600;color:var(--green);display:flex;align-items:center;gap:8px}
.drill-close{background:transparent;border:1px solid var(--rule);color:var(--dim2);font-family:var(--font);font-size:11px;padding:3px 8px;cursor:pointer;transition:color 0.15s}
.drill-close:hover{color:var(--txt)}
.drill-body{padding:14px 16px;display:flex;flex-direction:column;gap:16px;flex:1}
.drill-sec{font-size:10px;font-weight:600;color:var(--dim2);letter-spacing:0.08em;text-transform:uppercase;margin-bottom:6px}
.drill-empty{font-size:11px;color:var(--dim2);padding:8px 0}
.chart-wrap{position:relative;height:140px}
.tbl-row-click{cursor:pointer}
.tbl-row-click:hover td{background:rgba(126,231,135,0.05)!important}
```

- [ ] **Step 2: Add the panel HTML**

In `insights.html`, directly before `</body>`, insert:

```html
<!-- drill-down overlay + panel -->
<div class="drill-overlay" id="drillOverlay" onclick="closePanel()"></div>
<div class="drill-panel" id="drillPanel">
  <div class="drill-hdr">
    <div class="drill-title" id="drillTitle"></div>
    <button class="drill-close" onclick="closePanel()">[X] CLOSE</button>
  </div>
  <div class="drill-body" id="drillBody">
    <div class="drill-empty">Loading...</div>
  </div>
</div>
```

- [ ] **Step 3: Verify HTML structure**

Open `http://localhost:5001/insights` (ensure the test server from `/tmp/insights-test` is running, or restart it with `cd /tmp/insights-test && /Users/anguss/dev/finance_dash/venv/bin/python3 server.py &`). The page should load without errors. The panel is invisible by default — no visual change yet.

- [ ] **Step 4: Commit**

```bash
git add insights.html
git commit -m "feat(insights): add drill-down panel HTML and CSS"
```

---

### Task 4: Add panel JS — fetchDrillDown, renderPanel, closePanel

**Files:**
- Modify: `insights.html` (add JS functions inside `<script>`, before `init()`)

- [ ] **Step 1: Add panel state and close function**

Inside `<script>` in `insights.html`, find the line:
```js
async function init(){
```

Insert the following block directly before it:

```js
let drillChart = null;

function closePanel() {
  document.getElementById('drillOverlay').classList.remove('open');
  document.getElementById('drillPanel').classList.remove('open');
  if (drillChart) { drillChart.destroy(); drillChart = null; }
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closePanel();
});
```

Note: there is already a `keydown` listener for nav keys at the top of the script. This second listener is fine — they handle different keys and don't conflict.

- [ ] **Step 2: Add fetchDrillDown function**

Directly after the `closePanel` function (still before `init()`), insert:

```js
async function fetchDrillDown(type, key) {
  const month = state.currentMonth;
  document.getElementById('drillTitle').textContent = 'Loading...';
  document.getElementById('drillBody').innerHTML = '<div class="drill-empty">Loading...</div>';
  document.getElementById('drillOverlay').classList.add('open');
  document.getElementById('drillPanel').classList.add('open');
  if (drillChart) { drillChart.destroy(); drillChart = null; }

  try {
    let url;
    if (type === 'category') {
      url = `/api/insights/category?slug=${encodeURIComponent(key)}&month=${month}`;
    } else {
      url = `/api/insights/merchant?name=${encodeURIComponent(key)}&month=${month}`;
    }
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderPanel(type, data);
  } catch (e) {
    document.getElementById('drillBody').innerHTML = `<div class="drill-empty" style="color:var(--red)">Failed to load: ${e.message}</div>`;
  }
}
```

- [ ] **Step 3: Add renderPanel function**

Directly after `fetchDrillDown`, insert:

```js
function renderPanel(type, data) {
  // Header
  if (type === 'category') {
    const meta = catMeta(data.slug);
    document.getElementById('drillTitle').innerHTML =
      `${meta.icon} ${data.slug.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase())} · ${fmtMonth(data.month)}`;
  } else {
    document.getElementById('drillTitle').innerHTML =
      `${merchantIconHtml(data.name)} ${data.name} · ${fmtMonth(data.month)}`;
  }

  const parts = [];

  // 1. 6-month bar chart
  const chartId = 'drillChartCanvas';
  parts.push(`
    <div>
      <div class="drill-sec">6-MONTH TREND</div>
      <div class="chart-wrap"><canvas id="${chartId}"></canvas></div>
    </div>
  `);

  // 2. Top merchants (category only)
  if (type === 'category' && data.top_merchants && data.top_merchants.length) {
    const rows = data.top_merchants.map(m => `
      <tr class="tbl-row-click" onclick="fetchDrillDown('merchant','${m.description.replace(/'/g, "\\'")}')">
        <td>${merchantIconHtml(m.description)}</td>
        <td style="font-weight:500">${m.description}</td>
        <td style="text-align:right;color:var(--dim2)">${m.count}</td>
        <td style="text-align:right;color:var(--amber)">${formatCurrency(m.total)}</td>
      </tr>`).join('');
    parts.push(`
      <div>
        <div class="drill-sec">TOP MERCHANTS THIS MONTH</div>
        <table class="tbl">
          <thead><tr><th style="width:20px"></th><th>MERCHANT</th><th style="text-align:right">TXN</th><th style="text-align:right">TOTAL</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `);
  } else if (type === 'category') {
    parts.push(`<div><div class="drill-sec">TOP MERCHANTS THIS MONTH</div><div class="drill-empty">No transactions this month</div></div>`);
  }

  // 3. Transactions
  const txns = data.transactions || [];
  let txnHtml;
  if (txns.length) {
    const txnRows = txns.map(t => {
      const meta = catMeta(t.category);
      return `<tr>
        <td style="color:var(--dim2);font-size:11px">${t.date.slice(5)}</td>
        <td>${merchantIconHtml(t.description)}</td>
        <td style="font-weight:500">${t.description}</td>
        <td><span style="font-size:10px;color:${meta.color};border:1px solid ${meta.color}44;padding:1px 5px">${t.category}</span></td>
        <td style="text-align:right;color:var(--amber)">${formatCurrency(t.amount)}</td>
      </tr>`;
    }).join('');
    txnHtml = `<table class="tbl">
      <thead><tr><th>DATE</th><th style="width:20px"></th><th>DESCRIPTION</th><th>CATEGORY</th><th style="text-align:right">AMOUNT</th></tr></thead>
      <tbody>${txnRows}</tbody>
    </table>`;
  } else {
    txnHtml = `<div class="drill-empty">No transactions this month</div>`;
  }
  parts.push(`<div><div class="drill-sec">TRANSACTIONS THIS MONTH</div>${txnHtml}</div>`);

  document.getElementById('drillBody').innerHTML = parts.join('');

  // Render chart after DOM is updated
  const canvas = document.getElementById(chartId);
  if (canvas) {
    const labels = data.history.map(h => fmtMonth(h.month).split(' ')[0]);
    const values = data.history.map(h => h.total);
    const barColor = type === 'category'
      ? (catMeta(data.slug).color + '99')
      : 'rgba(126,231,135,0.6)';
    drillChart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: barColor,
          borderColor: barColor,
          borderWidth: 0,
          borderRadius: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: {
          callbacks: { label: ctx => formatCurrency(ctx.parsed.y) }
        }},
        scales: {
          x: { grid: { color: 'rgba(120,180,120,0.08)' }, ticks: { color: 'rgba(207,234,207,0.4)', font: { family: "'JetBrains Mono',monospace", size: 10 } } },
          y: { grid: { color: 'rgba(120,180,120,0.08)' }, ticks: { color: 'rgba(207,234,207,0.4)', font: { family: "'JetBrains Mono',monospace", size: 10 }, callback: v => '$' + v } },
        },
      },
    });
  }
}
```

- [ ] **Step 4: Verify JS loads without errors**

Open `http://localhost:5001/insights` in a browser. Open DevTools console. There should be no JS errors on page load. The panel is still invisible.

- [ ] **Step 5: Commit**

```bash
git add insights.html
git commit -m "feat(insights): add panel JS — fetchDrillDown, renderPanel, closePanel"
```

---

### Task 5: Wire click handlers to category and merchant rows

**Files:**
- Modify: `insights.html` — update `renderCategories()` and `renderMerchants()` to add `onclick` and `.tbl-row-click` class to each `<tr>`

- [ ] **Step 1: Update renderCategories to add click handler**

In `insights.html`, inside `renderCategories()`, find:
```js
    return`<tr>
      <td style="color:${meta.color}">${meta.icon} ${cat.slug==='uncategorised'?'Uncategorised':cat.slug.replace(/-/g,' ').replace(/\b\w/g,c=>c.toUpperCase())}</td>
```

Replace with:
```js
    return`<tr class="tbl-row-click" onclick="fetchDrillDown('category','${cat.slug}')">
      <td style="color:${meta.color}">${meta.icon} ${cat.slug==='uncategorised'?'Uncategorised':cat.slug.replace(/-/g,' ').replace(/\b\w/g,c=>c.toUpperCase())}</td>
```

- [ ] **Step 2: Update renderMerchants to add click handler**

In `insights.html`, inside `renderMerchants()`, find:
```js
    return`<tr>
      <td>${merchantIconHtml(m.description)}</td>
```

Replace with:
```js
    return`<tr class="tbl-row-click" onclick="fetchDrillDown('merchant','${m.description.replace(/'/g,"\\'")}')">
      <td>${merchantIconHtml(m.description)}</td>
```

- [ ] **Step 3: Verify the panel opens**

Open `http://localhost:5001/insights`. Click any category row — the panel should slide in from the right showing the title, a 6-month bar chart, top merchants table, and transactions. Click the overlay or `[X] CLOSE` to dismiss. Click a merchant row — panel should show the title, bar chart, and transactions (no top-merchants table). Press `Esc` to close.

Also verify: switching months via pills while the panel is closed still works normally.

- [ ] **Step 4: Commit**

```bash
git add insights.html
git commit -m "feat(insights): wire click handlers to category and merchant rows"
```

---

### Task 6: Final checks

**Files:** None changed — verification only.

- [ ] **Step 1: Check the full interaction flow**

On `http://localhost:5001/insights`:
1. Page loads with April 2026 data (or most recent month)
2. Click "Takeaway" category row → panel slides in with chart, top merchants, transactions
3. Inside panel, click a merchant within the category → panel updates to that merchant's view (chart + transactions, no top-merchants table)
4. Press `Esc` → panel closes
5. Click a merchant row in the main merchants table → panel slides in with merchant chart and transactions
6. Click overlay → panel closes
7. Change month via pill → `state.currentMonth` updates; re-opening a drill-down fetches data for the new month

- [ ] **Step 2: Check error case**

Test with a category that has no transactions this month by selecting a very old month:

```bash
curl -s "http://localhost:5001/api/insights/category?slug=lottery-and-gambling&month=2026-04" | python3 -m json.tool
```

Expected: `transactions: []`, `top_merchants: []`. In the browser, the panel should show "No transactions this month" text for both sections.

- [ ] **Step 3: Commit any fixes, then push**

```bash
git add -p  # stage any fixes
git commit -m "fix(insights): drill-down panel final adjustments"
git log --oneline -6
```

Expected recent commits:
```
fix(insights): drill-down panel final adjustments
feat(insights): wire click handlers to category and merchant rows
feat(insights): add panel JS — fetchDrillDown, renderPanel, closePanel
feat(insights): add drill-down panel HTML and CSS
feat(insights): add GET /api/insights/merchant endpoint
feat(insights): add GET /api/insights/category endpoint
```
