# Spending Insights Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new `/insights` page that shows a dense, month-by-month spending analysis — reality check strip, top categories/merchants, frivolity score, category trends, and subscription tagging — designed to be read alongside Claude for commentary.

**Architecture:** Single-call API endpoint `GET /api/insights/monthly?month=YYYY-MM` returns all data for the page. A second endpoint `POST /api/insights/subscription-tag` persists KEEP/REVIEW/CUT tags to `config.json`. `insights.html` is a self-contained single-file page following the same stack as the rest of the dashboard (Flask, vanilla JS, Chart.js 4.4.0, JetBrains Mono dark theme). All new server logic lives in `server.py`. Keyboard nav key `[I]` added to all existing pages.

**Tech Stack:** Flask (Python), vanilla JS, Chart.js 4.4.0, JetBrains Mono dark terminal theme (`--bg:#080a08`, `--green:#7ee787`, etc.). CSV data layer, `config.json` for subscription tag persistence. Server runs on port 5001 via `venv/bin/python server.py`.

---

## File Structure

| File | Role |
|---|---|
| `insights.html` | New — full insights page, all HTML/CSS/JS |
| `server.py` | Modified — add `GET /insights`, `GET /api/insights/monthly`, `POST /api/insights/subscription-tag`, `FRIVOLITY_WEIGHTS` dict, `linear_slope()` helper |
| `spending.html` | Modified — add `i:'/insights'` to `KEYS` nav map |
| `budget.html` | Modified — add `i:'/insights'` to `KEYS` nav map |
| `networth.html` | Modified — add `i:'/insights'` to `KEYS` nav map |
| `portfolio.html` | Modified — add `i:'/insights'` to `KEYS` nav map |
| `cgt.html` | Modified — add `i:'/insights'` to `KEYS` nav map |
| `house.html` | Modified — add `i:'/insights'` to `KEYS` nav map |
| `bills.html` | Modified — add `i:'/insights'` to `KEYS` nav map |
| `dashboard.html` | Modified — add `i:'/insights'` to `KEYS` nav map |
| `performance.html` | Modified — add `i:'/insights'` to `KEYS` nav map |
| `tax.html` | Modified — add `i:'/insights'` to `KEYS` nav map |

---

## Task 1: Server helpers — `linear_slope()` and `FRIVOLITY_WEIGHTS`

**Files:**
- Modify: `server.py` (after `detect_recurring`, around line 780)

- [ ] **Step 1: Add `FRIVOLITY_WEIGHTS` constant and `linear_slope()` helper** in `server.py` after the `detect_recurring` function (around line 780, before `import_networth_from_excel`):

```python
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
```

- [ ] **Step 2: Verify the helper works at the Python prompt**

```bash
cd /Users/anguss/dev/finance_dash
venv/bin/python -c "
from server import linear_slope
# Flat series → slope ~0
print(linear_slope([100, 100, 100, 100]))   # expected: 0.0
# Rising series → positive slope
print(linear_slope([100, 200, 300, 400]))   # expected: 100.0
# Falling series → negative slope
print(linear_slope([400, 300, 200, 100]))   # expected: -100.0
# Single value → 0
print(linear_slope([500]))                  # expected: 0.0
"
```

Expected output:
```
0.0
100.0
-100.0
0.0
```

- [ ] **Step 3: Commit**

```bash
git add server.py
git commit -m "feat(insights): add FRIVOLITY_WEIGHTS and linear_slope helper"
```

---

## Task 2: `GET /api/insights/monthly` endpoint

**Files:**
- Modify: `server.py` (add after `api_spending_category_history`, around line 1205)

This is the main data endpoint. It accepts `?month=YYYY-MM` (defaults to most recent complete month) and returns all data needed by the insights page in one call.

- [ ] **Step 1: Add the `_get_month_range(month_str)` helper** in `server.py` immediately before the new route (after `api_spending_category_history`):

```python
def _get_month_range(month_str: str) -> tuple:
    """Return (start_dt, end_dt) for a YYYY-MM string."""
    year, month = int(month_str[:4]), int(month_str[5:7])
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start, end
```

- [ ] **Step 2: Add `_compute_month_cashflow(month_str)` helper** immediately after `_get_month_range`:

```python
def _compute_month_cashflow(month_str: str) -> Dict:
    """Return income, saved, discretionary for a single calendar month."""
    start, end = _get_month_range(month_str)
    status = get_status()
    account_ids = status.get("account_ids", {})
    savings_id = account_ids.get("savings", "")
    grow_id = account_ids.get("grow", "")
    two_up_id = account_ids.get("two_up", "")
    spending_id = account_ids.get("spending", "")
    internal_ids_savings = {tid for tid in (spending_id, grow_id, two_up_id) if tid}

    INVESTMENT_DESCRIPTIONS = {"ibkr", "selfwealth", "stake", "commsec", "pearler"}

    income = 0.0
    saved = 0.0
    invested = 0.0
    disc = 0.0

    for row in read_csv(DATA_DIR / "transactions_spending.csv"):
        dt_str = row.get("settled_at") or row.get("created_at") or ""
        if not dt_str:
            continue
        dt = parse_datetime_or_date(dt_str)
        if not (start <= dt < end):
            continue
        amount = parse_float(row.get("amount")) or 0.0
        tid = row.get("transfer_account_id", "")
        if amount > 0 and not tid:
            income += amount
        elif tid == savings_id and amount < 0:
            saved += abs(amount)
        elif tid == grow_id and amount < 0:
            saved += abs(amount)
        elif amount < 0 and not tid:
            disc += abs(amount)

    savings_csv = DATA_DIR / "transactions_savings.csv"
    if savings_csv.exists():
        for row in read_csv(savings_csv):
            dt_str = row.get("settled_at") or row.get("created_at") or ""
            if not dt_str:
                continue
            dt = parse_datetime_or_date(dt_str)
            if not (start <= dt < end):
                continue
            amount = parse_float(row.get("amount")) or 0.0
            if amount >= 0:
                continue
            tid = row.get("transfer_account_id", "")
            if tid in internal_ids_savings:
                continue
            desc = (row.get("description") or "").lower()
            if any(kw in desc for kw in INVESTMENT_DESCRIPTIONS):
                invested += abs(amount)

    savings_rate = round((saved + invested) / income * 100, 1) if income > 0 else 0.0
    return {
        "income": round(income, 2),
        "saved": round(saved + invested, 2),
        "discretionary": round(disc, 2),
        "savings_rate": savings_rate,
    }
```

- [ ] **Step 3: Add `GET /api/insights/monthly` route** immediately after the two helpers:

```python
@app.get("/api/insights/monthly")
def api_insights_monthly():
    today = datetime.now()
    # Default to most recent complete calendar month
    first_of_this_month = today.replace(day=1)
    default_month_dt = (first_of_this_month - timedelta(days=1)).replace(day=1)
    default_month = f"{default_month_dt.year}-{default_month_dt.month:02d}"
    month_str = request.args.get("month", default_month)

    # Validate format
    try:
        year, month = int(month_str[:4]), int(month_str[5:7])
        if not (2020 <= year <= 2099 and 1 <= month <= 12):
            raise ValueError
    except (ValueError, IndexError):
        return jsonify({"error": "invalid month format, use YYYY-MM"}), 400

    # Prev month
    prev_dt = datetime(year, month, 1) - timedelta(days=1)
    prev_month = f"{prev_dt.year}-{prev_dt.month:02d}"

    # Available months — all months from first transaction to last complete month
    all_rows = read_csv(DATA_DIR / "transactions_spending.csv")
    month_set: set = set()
    for row in all_rows:
        dt_str = row.get("settled_at") or row.get("created_at") or ""
        if not dt_str:
            continue
        try:
            dt = parse_datetime_or_date(dt_str)
            mk = f"{dt.year}-{dt.month:02d}"
            if mk < default_month or mk == default_month:
                month_set.add(mk)
        except Exception:
            continue
    available_months = sorted(month_set, reverse=True)

    # Cashflow for selected + prev month
    cf = _compute_month_cashflow(month_str)
    cf_prev = _compute_month_cashflow(prev_month)

    # Category spend for selected + prev month
    start, end = _get_month_range(month_str)
    prev_start, prev_end = _get_month_range(prev_month)

    status = get_status()
    account_ids = status.get("account_ids", {})
    two_up_id = account_ids.get("two_up", "")
    savings_id = account_ids.get("savings", "")
    grow_id = account_ids.get("grow", "")
    internal_ids = {tid for tid in (two_up_id, savings_id, grow_id) if tid}

    cat_spend: Dict[str, float] = {}
    cat_spend_prev: Dict[str, float] = {}
    merchant_totals: Dict[str, float] = {}
    merchant_counts: Dict[str, int] = {}
    merchant_cats: Dict[str, str] = {}

    for row in all_rows:
        amount = parse_float(row.get("amount")) or 0.0
        if amount >= 0:
            continue
        tid = row.get("transfer_account_id", "")
        if tid in internal_ids:
            continue
        dt_str = row.get("settled_at") or row.get("created_at") or ""
        if not dt_str:
            continue
        try:
            dt = parse_datetime_or_date(dt_str)
        except Exception:
            continue
        cat = (row.get("category") or "").strip() or "uncategorised"
        desc = (row.get("description") or "").strip()

        if start <= dt < end:
            cat_spend[cat] = cat_spend.get(cat, 0.0) + abs(amount)
            if desc:
                merchant_totals[desc] = merchant_totals.get(desc, 0.0) + abs(amount)
                merchant_counts[desc] = merchant_counts.get(desc, 0) + 1
                if desc not in merchant_cats:
                    merchant_cats[desc] = cat
        elif prev_start <= dt < prev_end:
            cat_spend_prev[cat] = cat_spend_prev.get(cat, 0.0) + abs(amount)

    disc = cf["discretionary"] or 1.0  # avoid div/0

    top_categories = sorted(
        [
            {
                "slug": cat,
                "total": round(total, 2),
                "prev_total": round(cat_spend_prev.get(cat, 0.0), 2),
                "pct_of_disc": round(total / disc * 100, 1),
            }
            for cat, total in cat_spend.items()
        ],
        key=lambda x: x["total"],
        reverse=True,
    )[:15]

    # Merchants with running cumulative (added here, not client-side)
    sorted_merchants = sorted(merchant_totals.items(), key=lambda x: x[1], reverse=True)[:15]
    cumulative = 0.0
    top_merchants = []
    for desc, total in sorted_merchants:
        cumulative += total
        top_merchants.append({
            "description": desc,
            "total": round(total, 2),
            "count": merchant_counts[desc],
            "cumulative": round(cumulative, 2),
            "category": merchant_cats.get(desc, ""),
        })

    # Frivolity score for selected month
    weighted_total = sum(
        cat_spend.get(cat, 0.0) * FRIVOLITY_WEIGHTS.get(cat, 0.5)
        for cat in cat_spend
    )
    frivolity_score = round(weighted_total / disc * 100, 1)
    drivers = sorted(
        [
            {
                "slug": cat,
                "total": round(cat_spend[cat], 2),
                "weight": FRIVOLITY_WEIGHTS.get(cat, 0.5),
                "contribution": round(cat_spend[cat] * FRIVOLITY_WEIGHTS.get(cat, 0.5), 2),
            }
            for cat in cat_spend
            if cat_spend[cat] * FRIVOLITY_WEIGHTS.get(cat, 0.5) > 0
        ],
        key=lambda x: x["contribution"],
        reverse=True,
    )[:8]

    # Frivolity history — last 6 complete months
    frivolity_history = []
    hist_months: List[str] = []
    d = default_month_dt
    for _ in range(6):
        hist_months.append(f"{d.year}-{d.month:02d}")
        d = (d - timedelta(days=1)).replace(day=1)
    hist_months.reverse()

    for hm in hist_months:
        hs, he = _get_month_range(hm)
        hm_cat: Dict[str, float] = {}
        hm_disc = 0.0
        for row in all_rows:
            amount = parse_float(row.get("amount")) or 0.0
            if amount >= 0:
                continue
            tid = row.get("transfer_account_id", "")
            if tid in internal_ids:
                continue
            dt_str = row.get("settled_at") or row.get("created_at") or ""
            if not dt_str:
                continue
            try:
                dt = parse_datetime_or_date(dt_str)
            except Exception:
                continue
            if hs <= dt < he:
                cat = (row.get("category") or "").strip() or "uncategorised"
                hm_cat[cat] = hm_cat.get(cat, 0.0) + abs(amount)
                hm_disc += abs(amount)
        hm_weighted = sum(hm_cat.get(c, 0.0) * FRIVOLITY_WEIGHTS.get(c, 0.5) for c in hm_cat)
        hm_score = round(hm_weighted / hm_disc * 100, 1) if hm_disc > 0 else 0.0
        frivolity_history.append({"month": hm, "score": hm_score})

    # Trends — linear slope over last 6 months per category
    # Reuse hist_months built above
    cat_monthly: Dict[str, List[float]] = {}
    for hm in hist_months:
        hs, he = _get_month_range(hm)
        hm_cat2: Dict[str, float] = {}
        for row in all_rows:
            amount = parse_float(row.get("amount")) or 0.0
            if amount >= 0:
                continue
            tid = row.get("transfer_account_id", "")
            if tid in internal_ids:
                continue
            dt_str = row.get("settled_at") or row.get("created_at") or ""
            if not dt_str:
                continue
            try:
                dt = parse_datetime_or_date(dt_str)
            except Exception:
                continue
            if hs <= dt < he:
                cat = (row.get("category") or "").strip() or "uncategorised"
                hm_cat2[cat] = hm_cat2.get(cat, 0.0) + abs(amount)
        for cat in set(list(cat_monthly.keys()) + list(hm_cat2.keys())):
            cat_monthly.setdefault(cat, [0.0] * len(hist_months))
            cat_monthly[cat][hist_months.index(hm)] = hm_cat2.get(cat, 0.0)

    all_cat_totals = {cat: sum(vals) for cat, vals in cat_monthly.items()}
    top_trend_cats = sorted(all_cat_totals, key=lambda c: all_cat_totals[c], reverse=True)[:8]
    trends = []
    for cat in top_trend_cats:
        vals = cat_monthly[cat]
        recent_3 = [v for v in vals[-3:] if v > 0]
        avg_3mo = round(sum(recent_3) / len(recent_3), 2) if recent_3 else 0.0
        this_month_val = cat_spend.get(cat, 0.0)
        trends.append({
            "slug": cat,
            "slope_per_month": linear_slope(vals),
            "avg_3mo": avg_3mo,
            "this_month": round(this_month_val, 2),
        })

    return jsonify({
        "month": month_str,
        "prev_month": prev_month,
        "available_months": available_months,
        "income": cf["income"],
        "saved": cf["saved"],
        "discretionary": cf["discretionary"],
        "savings_rate": cf["savings_rate"],
        "prev_savings_rate": cf_prev["savings_rate"],
        "prev_discretionary": cf_prev["discretionary"],
        "top_categories": top_categories,
        "top_merchants": top_merchants,
        "frivolity": {
            "score": frivolity_score,
            "weighted_total": round(weighted_total, 2),
            "drivers": drivers,
            "history": frivolity_history,
        },
        "trends": trends,
    })
```

- [ ] **Step 4: Restart server and test the endpoint**

```bash
pkill -f "venv/bin/python server.py" 2>/dev/null; sleep 1
venv/bin/python server.py &
sleep 2
curl -s "http://localhost:5001/api/insights/monthly" | python3 -m json.tool | head -60
```

Expected: JSON with keys `month`, `prev_month`, `available_months`, `income`, `saved`, `discretionary`, `savings_rate`, `top_categories`, `top_merchants`, `frivolity`, `trends`. Values should be non-zero if transactions_spending.csv has data.

- [ ] **Step 5: Test with explicit month param**

```bash
curl -s "http://localhost:5001/api/insights/monthly?month=2026-03" | python3 -m json.tool | grep -E '"month"|"income"|"savings_rate"'
```

Expected: `"month": "2026-03"` and non-zero income/savings_rate if March data exists.

- [ ] **Step 6: Test invalid month returns 400**

```bash
curl -s -o /dev/null -w "%{http_code}" "http://localhost:5001/api/insights/monthly?month=badval"
```

Expected: `400`

- [ ] **Step 7: Commit**

```bash
git add server.py
git commit -m "feat(insights): add GET /api/insights/monthly endpoint"
```

---

## Task 3: `POST /api/insights/subscription-tag` endpoint

**Files:**
- Modify: `server.py` (add after `api_insights_monthly`)

- [ ] **Step 1: Add `get_subscription_tags()` and `save_subscription_tag()` helpers** in `server.py` immediately after `api_insights_monthly`:

```python
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
```

- [ ] **Step 2: Add the Flask route** immediately after the helpers:

```python
@app.post("/api/insights/subscription-tag")
def api_subscription_tag():
    payload = request.get_json(force=True) or {}
    description = (payload.get("description") or "").strip()
    tag = payload.get("tag")  # "KEEP", "REVIEW", "CUT", or null
    if not description:
        return jsonify({"ok": False, "error": "description required"}), 400
    if tag is not None and tag not in {"KEEP", "REVIEW", "CUT"}:
        return jsonify({"ok": False, "error": "tag must be KEEP, REVIEW, CUT, or null"}), 400
    save_subscription_tag(description, tag)
    return jsonify({"ok": True, "description": description, "tag": tag})
```

- [ ] **Step 3: Test the endpoint**

```bash
# Tag a subscription
curl -s -X POST http://localhost:5001/api/insights/subscription-tag \
  -H 'Content-Type: application/json' \
  -d '{"description": "Spotify", "tag": "KEEP"}' | python3 -m json.tool
# Expected: {"ok": true, "description": "Spotify", "tag": "KEEP"}

# Verify it persisted in config.json
python3 -c "import json; d=json.load(open('config.json')); print(d.get('subscription_tags'))"
# Expected: {'Spotify': 'KEEP'}

# Clear a tag
curl -s -X POST http://localhost:5001/api/insights/subscription-tag \
  -H 'Content-Type: application/json' \
  -d '{"description": "Spotify", "tag": null}' | python3 -m json.tool
# Expected: {"ok": true, "description": "Spotify", "tag": null}

# Invalid tag
curl -s -X POST http://localhost:5001/api/insights/subscription-tag \
  -H 'Content-Type: application/json' \
  -d '{"description": "Spotify", "tag": "MAYBE"}' | python3 -m json.tool
# Expected: {"ok": false, "error": "tag must be KEEP, REVIEW, CUT, or null"}
```

- [ ] **Step 4: Add `GET /insights` page route** in `server.py` alongside the other page routes (near `GET /spending`, around line 843):

```python
@app.get("/insights")
def insights_page():
    return send_file(BASE_DIR / "insights.html")
```

- [ ] **Step 5: Commit**

```bash
git add server.py
git commit -m "feat(insights): add subscription tag endpoint and /insights route"
```

---

## Task 4: Add `[I]` nav key to all existing pages

**Files:** `spending.html`, `budget.html`, `networth.html`, `portfolio.html`, `cgt.html`, `house.html`, `bills.html`, `dashboard.html`, `performance.html`, `tax.html`

Each of these files has a line like:
```javascript
const KEYS={d:'/dashboard',n:'/networth', ...};
```

- [ ] **Step 1: Add `i:'/insights'` to the KEYS map in every existing HTML file**

For each file, find the line starting with `const KEYS=` and add `i:'/insights'` to the object. Run this sed to do all at once:

```bash
for f in spending.html budget.html networth.html portfolio.html cgt.html house.html bills.html dashboard.html performance.html tax.html; do
  sed -i '' "s/const KEYS={/const KEYS={i:'\/insights',/" "$f"
done
```

- [ ] **Step 2: Verify the change looks correct in spending.html**

```bash
grep "const KEYS" spending.html
```

Expected: `const KEYS={i:'/insights',d:'/dashboard',n:'/networth',...}`

- [ ] **Step 3: Add `[I]NSIGHTS` to the nav bar in every existing HTML file**

Each file has a `<nav class="nav">` block. Add the insights link after the existing nav items. Run:

```bash
for f in spending.html budget.html networth.html portfolio.html cgt.html house.html bills.html dashboard.html performance.html tax.html; do
  sed -i '' 's|<a class="nav-item" href="/tax">|<a class="nav-item" href="/insights"><span class="nav-key">[I]</span>NSIGHTS</a>\n  <a class="nav-item" href="/tax">|' "$f"
done
```

- [ ] **Step 4: Verify nav was inserted correctly in spending.html**

```bash
grep -A1 "NSIGHTS" spending.html
```

Expected: `<a class="nav-item" href="/insights"><span class="nav-key">[I]</span>NSIGHTS</a>` followed by the tax nav item.

- [ ] **Step 5: Commit**

```bash
git add spending.html budget.html networth.html portfolio.html cgt.html house.html bills.html dashboard.html performance.html tax.html
git commit -m "feat(insights): add [I] nav key and INSIGHTS nav link to all pages"
```

---

## Task 5: `insights.html` — skeleton, styles, and month picker

**Files:**
- Create: `insights.html`

This task creates the full page shell with CSS, the nav bar (active on INSIGHTS), the month pill picker, and the fetch/render scaffolding. Sections render as empty until Task 6+.

- [ ] **Step 1: Create `insights.html`** with styles, nav, month picker, and fetch skeleton:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FINTERM · INSIGHTS</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#080a08;--panel:#0d100d;--panel2:#111411;--rule:rgba(120,180,120,0.13);--rule2:rgba(120,180,120,0.06);--txt:#cfeacf;--dim:rgba(207,234,207,0.55);--dim2:rgba(207,234,207,0.28);--green:#7ee787;--amber:#f0b86e;--red:#ff7b72;--blue:#79c0ff;--purple:#a371f7;--font:'JetBrains Mono',monospace}
html,body{height:100%;background:var(--bg);color:var(--txt);font-family:var(--font);font-size:13px;line-height:1.5;overflow-x:hidden}
a{color:inherit;text-decoration:none}
body::after{content:'';position:fixed;inset:0;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,0.04) 2px,rgba(0,0,0,0.04) 4px);pointer-events:none;z-index:9999}
.hdr{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;border-bottom:1px solid var(--rule);background:var(--panel)}
.hdr-left{display:flex;align-items:center;gap:12px}
.hdr-dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green);animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.3}}
.hdr-title{color:var(--green);font-weight:700;font-size:14px;letter-spacing:0.05em}
.hdr-sub{color:var(--dim);font-size:11px}
.hdr-right{color:var(--dim2);font-size:11px}
.nav{display:flex;align-items:center;border-bottom:1px solid var(--rule);background:var(--panel);overflow-x:auto;-webkit-overflow-scrolling:touch}
.nav-item{padding:8px 14px;color:var(--dim);font-size:12px;white-space:nowrap;border-bottom:2px solid transparent;transition:color 0.15s}
.nav-item:hover{color:var(--txt)}
.nav-item.active{color:var(--green);border-bottom-color:var(--green)}
.nav-key{color:var(--dim2)}
.page{padding:12px 16px;display:flex;flex-direction:column;gap:12px;max-width:1400px;margin:0 auto}
.box{background:var(--panel);border:1px solid var(--rule);padding:14px}
.sec-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
.sec-label{font-size:11px;font-weight:600;color:var(--dim);letter-spacing:0.08em;text-transform:uppercase}
.sec-count{font-size:11px;color:var(--dim2)}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.tbl{width:100%;border-collapse:collapse}
.tbl th{font-size:10px;color:var(--dim2);text-transform:uppercase;letter-spacing:0.08em;padding:5px 8px;border-bottom:1px solid var(--rule);text-align:left;font-weight:500}
.tbl td{padding:5px 8px;border-bottom:1px solid var(--rule2);font-size:12px}
.tbl tr:last-child td{border-bottom:none}
.tbl tr:hover td{background:rgba(126,231,135,0.02)}
.bar-wrap{height:4px;background:var(--rule);position:relative;overflow:hidden;min-width:60px}
.bar{height:100%}
.green{color:var(--green)}.amber{color:var(--amber)}.red{color:var(--red)}.dim{color:var(--dim)}.dim2{color:var(--dim2)}
.delta-up{color:var(--red)}.delta-down{color:var(--green)}.delta-flat{color:var(--dim2)}
/* month pills */
.month-pills{display:flex;gap:4px;flex-wrap:wrap}
.mpill{padding:3px 9px;border:1px solid var(--rule);color:var(--dim2);font-size:11px;font-family:var(--font);cursor:pointer;background:transparent;transition:color 0.15s,border-color 0.15s}
.mpill:hover{border-color:rgba(120,180,120,0.4);color:var(--txt)}
.mpill.active{border-color:var(--green);color:var(--green)}
/* reality strip */
.reality-strip{display:flex;border-top:1px solid var(--rule)}
.rc{flex:1;padding:12px 14px;border-right:1px solid var(--rule)}
.rc:last-child{border-right:none}
.rc-label{font-size:10px;color:var(--dim2);letter-spacing:0.1em;text-transform:uppercase;margin-bottom:3px}
.rc-val{font-size:20px;font-weight:700;line-height:1.2}
.rc-sub{font-size:10px;color:var(--dim2);margin-top:2px}
.rc-delta{font-size:10px;margin-top:3px}
/* allocation bar */
.alloc-bar{display:flex;height:6px;gap:1px}
.alloc-seg{height:100%}
/* score ring */
.score-ring{width:76px;height:76px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-direction:column;flex-shrink:0}
.score-ring .sr-val{font-size:18px;font-weight:700;line-height:1}
.score-ring .sr-lbl{font-size:9px;color:var(--dim2);letter-spacing:0.06em;margin-top:2px}
/* mini bar chart for frivolity trend */
.mini-bars{display:flex;gap:3px;align-items:flex-end;height:36px}
.mini-bar{width:16px;border-radius:1px 1px 0 0;min-height:2px}
/* subscription tag buttons */
.tag-btn{padding:2px 7px;font-size:10px;font-family:var(--font);border:1px solid var(--rule);background:transparent;color:var(--dim2);cursor:pointer;transition:all 0.15s;letter-spacing:0.04em}
.tag-btn.keep{border-color:var(--green);color:var(--green)}
.tag-btn.review{border-color:var(--amber);color:var(--amber)}
.tag-btn.cut{border-color:var(--red);color:var(--red)}
.cut-row td{opacity:0.45;text-decoration:line-through}
.cut-row .tag-btn{text-decoration:none;opacity:1}
.cmd{display:flex;align-items:center;gap:16px;padding:8px 16px;border-top:1px solid var(--rule);background:var(--panel);font-size:11px;color:var(--dim2);flex-wrap:wrap}
.cmd-key{color:var(--green)}
@media(max-width:768px){.two-col{grid-template-columns:1fr}.page{padding:8px}.hdr-right{display:none}.reality-strip{flex-direction:column}}
</style>
</head>
<body>
<header class="hdr">
  <div class="hdr-left"><div class="hdr-dot"></div><span class="hdr-title">FINTERM/ANGUS</span><span class="hdr-sub">INSIGHTS</span></div>
  <div class="hdr-right" id="hdr-month"></div>
</header>
<nav class="nav">
  <a class="nav-item" href="/dashboard"><span class="nav-key">[D]</span>ASH</a>
  <a class="nav-item" href="/networth"><span class="nav-key">[N]</span>ET.WORTH</a>
  <a class="nav-item" href="/portfolio"><span class="nav-key">[P]</span>ORTFOLIO</a>
  <a class="nav-item" href="/cgt"><span class="nav-key">[C]</span>GT</a>
  <a class="nav-item" href="/house"><span class="nav-key">[H]</span>OUSE</a>
  <a class="nav-item" href="/bills"><span class="nav-key">[B]</span>ILLS</a>
  <a class="nav-item" href="/spending"><span class="nav-key">[S]</span>PEND</a>
  <a class="nav-item" href="/budget"><span class="nav-key">[U]</span>DGET</a>
  <a class="nav-item active" href="/insights"><span class="nav-key">[I]</span>NSIGHTS</a>
  <a class="nav-item" href="/performance"><span class="nav-key">[F]</span>PERF</a>
  <a class="nav-item" href="/tax"><span class="nav-key">[T]</span>AX</a>
</nav>

<main class="page">
  <!-- month picker -->
  <div class="box" id="month-picker-box">
    <div class="sec-hdr" style="margin-bottom:8px"><span class="sec-label">PERIOD</span><span class="sec-count">last full calendar month · click to compare</span></div>
    <div class="month-pills" id="monthPills"></div>
  </div>

  <!-- reality check -->
  <div class="box" style="padding:0;overflow:hidden" id="reality-box">
    <div style="padding:8px 14px 6px;border-bottom:1px solid var(--rule);display:flex;align-items:center;justify-content:space-between">
      <span class="sec-label">REALITY.CHECK</span>
      <span class="sec-count" id="reality-label">loading...</span>
    </div>
    <div class="reality-strip" id="reality-strip"></div>
    <div class="alloc-bar" id="alloc-bar"></div>
    <div style="padding:4px 14px 6px;display:flex;gap:16px;flex-wrap:wrap" id="alloc-legend"></div>
  </div>

  <!-- top categories + merchants -->
  <div class="two-col">
    <div class="box">
      <div class="sec-hdr"><span class="sec-label">TOP.CATEGORIES</span><span class="sec-count" id="cat-period"></span></div>
      <table class="tbl">
        <thead><tr><th>CATEGORY</th><th style="text-align:right">SPENT</th><th style="text-align:right">% DISC</th><th style="min-width:60px">SHARE</th><th style="text-align:right">Δ PREV MO</th></tr></thead>
        <tbody id="catBody"></tbody>
      </table>
    </div>
    <div class="box">
      <div class="sec-hdr"><span class="sec-label">TOP.MERCHANTS</span><span class="sec-count" id="merch-period"></span></div>
      <table class="tbl">
        <thead><tr><th style="width:20px"></th><th>MERCHANT</th><th style="text-align:right">TXN</th><th style="text-align:right">TOTAL</th><th style="text-align:right">CUMUL.</th><th style="min-width:60px">SHARE</th></tr></thead>
        <tbody id="merchBody"></tbody>
      </table>
    </div>
  </div>

  <!-- frivolity + trends -->
  <div class="two-col">
    <div class="box" id="frivolity-box">
      <div class="sec-hdr"><span class="sec-label">FRIVOLITY.SCORE</span><span class="sec-count">weighted wants vs needs</span></div>
      <div style="display:flex;gap:16px;align-items:flex-start" id="frivolity-inner"></div>
    </div>
    <div class="box">
      <div class="sec-hdr"><span class="sec-label">CATEGORY.TRENDS</span><span class="sec-count">6-month slope · ↑ spending more</span></div>
      <table class="tbl">
        <thead><tr><th>CATEGORY</th><th style="text-align:right">3MO AVG</th><th style="text-align:right">THIS MO</th><th style="text-align:right">SLOPE</th><th style="text-align:center">DIR</th></tr></thead>
        <tbody id="trendsBody"></tbody>
      </table>
    </div>
  </div>

  <!-- subscriptions -->
  <div class="box" id="subs-box">
    <div class="sec-hdr">
      <span class="sec-label">RECURRING.SUBSCRIPTIONS</span>
      <span class="sec-count" id="subs-count"></span>
    </div>
    <table class="tbl">
      <thead><tr>
        <th style="width:20px"></th>
        <th>MERCHANT</th>
        <th style="text-align:right">INTERVAL</th>
        <th style="text-align:right">AMT/TXN</th>
        <th style="text-align:right">~MONTHLY</th>
        <th style="text-align:right">LAST</th>
        <th style="text-align:right">NEXT</th>
        <th style="text-align:center">TAG</th>
      </tr></thead>
      <tbody id="subsBody"></tbody>
    </table>
  </div>
</main>

<footer class="cmd">
  <span><span class="cmd-key">[S]</span>pend</span> · <span><span class="cmd-key">[B]</span>ills</span> · <span><span class="cmd-key">[←/→]</span> prev/next month</span>
</footer>

<script>
const KEYS={i:'/insights',d:'/dashboard',n:'/networth',p:'/portfolio',c:'/cgt',h:'/house',b:'/bills',s:'/spending',u:'/budget',f:'/performance',t:'/tax'};
document.addEventListener('keydown',e=>{
  if(e.metaKey||e.ctrlKey)return;
  if(e.target.tagName==='INPUT'||e.target.tagName==='SELECT')return;
  if(e.key==='ArrowLeft'){stepMonth(-1);return;}
  if(e.key==='ArrowRight'){stepMonth(1);return;}
  const dest=KEYS[e.key.toLowerCase()];
  if(dest)window.location=dest;
});

const CAT_META={
  'takeaway':{color:'#56d364',icon:'🥡'},'restaurants-and-cafes':{color:'#56d364',icon:'🍽️'},
  'booze':{color:'#56d364',icon:'🍺'},'pubs-and-bars':{color:'#56d364',icon:'🍻'},
  'events-and-gigs':{color:'#56d364',icon:'🎟️'},'holidays-and-travel':{color:'#56d364',icon:'✈️'},
  'hobbies':{color:'#56d364',icon:'🎨'},'games-and-software':{color:'#56d364',icon:'🎮'},
  'tv-and-music':{color:'#56d364',icon:'🎵'},'lottery-and-gambling':{color:'#56d364',icon:'🎲'},
  'groceries':{color:'#79c0ff',icon:'🛒'},'rent-and-mortgage':{color:'#79c0ff',icon:'🏠'},
  'utilities':{color:'#79c0ff',icon:'💡'},'internet':{color:'#79c0ff',icon:'📶'},
  'homeware-and-appliances':{color:'#79c0ff',icon:'🛋️'},'home-maintenance-and-improvements':{color:'#79c0ff',icon:'🔧'},
  'home-insurance-and-rates':{color:'#79c0ff',icon:'🏡'},'pets':{color:'#79c0ff',icon:'🐾'},
  'fuel':{color:'#f0b86e',icon:'⛽'},'public-transport':{color:'#f0b86e',icon:'🚌'},
  'taxis-and-share-cars':{color:'#f0b86e',icon:'🚕'},'parking':{color:'#f0b86e',icon:'🅿️'},
  'car-insurance-and-maintenance':{color:'#f0b86e',icon:'🚗'},'toll-roads':{color:'#f0b86e',icon:'🛣️'},
  'health-and-medical':{color:'#a371f7',icon:'🏥'},'clothing-and-accessories':{color:'#a371f7',icon:'👕'},
  'hair-and-beauty':{color:'#a371f7',icon:'💇'},'fitness-and-wellbeing':{color:'#a371f7',icon:'🏋️'},
  'gifts-and-charity':{color:'#a371f7',icon:'🎁'},'life-admin':{color:'#a371f7',icon:'📋'},
  'mobile-phone':{color:'#a371f7',icon:'📱'},'technology':{color:'#a371f7',icon:'💻'},
  'investments':{color:'#a371f7',icon:'📈'},'education-and-student-loans':{color:'#a371f7',icon:'📚'},
};
const CAT_DEFAULT={color:'rgba(207,234,207,0.28)',icon:'•'};
function catMeta(slug){return CAT_META[slug]||CAT_DEFAULT;}
function fmtCat(slug){
  if(!slug||slug==='uncategorised')return'• Uncategorised';
  const m=CAT_META[slug];
  return m?m.icon+' '+slug.replace(/-/g,' ').replace(/\b\w/g,c=>c.toUpperCase()):slug.replace(/-/g,' ').replace(/\b\w/g,c=>c.toUpperCase());
}

const MERCHANT_DOMAINS={
  'amazon':'amazon.com.au','apple':'apple.com','woolworths':'woolworths.com.au',
  'coles':'coles.com.au','aldi':'aldi.com.au','uber':'uber.com','uber eats':'ubereats.com',
  'uber one':'uber.com','guzman y gomez':'guzman.com.au',"mcdonald's":'mcdonalds.com.au',
  'kfc':'kfc.com.au',"domino's":'dominos.com.au','netflix':'netflix.com','spotify':'spotify.com',
  'microsoft':'microsoft.com','google':'google.com','ikea':'ikea.com','jb hi-fi':'jbhifi.com.au',
  'harvey norman':'harveynorman.com.au','chemist warehouse':'chemistwarehouse.com.au',
  'bunnings':'bunnings.com.au','officeworks':'officeworks.com.au','uniqlo':'uniqlo.com',
  'h&m':'hm.com','zara':'zara.com','myer':'myer.com.au','david jones':'davidjones.com',
  'united petroleum':'unitedpetroleum.com.au','bp':'bp.com.au','shell':'shell.com.au',
  'airbnb':'airbnb.com.au','booking.com':'booking.com','qantas':'qantas.com.au',
  'jetstar':'jetstar.com','virgin australia':'virginaustralia.com','afterpay':'afterpay.com',
  'paypal':'paypal.com','boost juice':'boostjuice.com.au',
};
function merchantDomain(name){
  const key=(name||'').toLowerCase().trim();
  if(MERCHANT_DOMAINS[key])return MERCHANT_DOMAINS[key];
  for(const[k,v]of Object.entries(MERCHANT_DOMAINS)){if(key.startsWith(k)||k.startsWith(key))return v;}
  return null;
}
function merchantIconHtml(name){
  const domain=merchantDomain(name);
  if(!domain)return'<span style="display:inline-block;width:16px;height:16px;background:var(--rule);border-radius:2px"></span>';
  return`<img src="https://www.google.com/s2/favicons?domain=${domain}&sz=32" width="16" height="16" style="border-radius:2px;vertical-align:middle;object-fit:contain" onerror="this.style.display='none'">`;
}

function formatCurrency(v){return new Intl.NumberFormat('en-AU',{style:'currency',currency:'AUD'}).format(v);}
function fmtMonth(m){const[y,mo]=m.split('-');return['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][parseInt(mo)-1]+' '+y;}

const state={data:null,recurring:[],subTags:{},currentMonth:null,availableMonths:[]};

async function fetchInsights(month){
  state.currentMonth=month;
  const[dataRes,recurRes]=await Promise.all([
    fetch(`/api/insights/monthly?month=${month}`),
    fetch('/api/spending/recurring'),
  ]);
  if(!dataRes.ok)throw new Error(`Insights fetch failed (${dataRes.status})`);
  state.data=await dataRes.json();
  state.availableMonths=state.data.available_months||[];
  state.recurring=recurRes.ok?await recurRes.json():[];
  // Load subscription tags from config via a quick GET budgets-style call
  // Tags come back embedded in the recurring data via config.json — we fetch them separately
  const tagsRes=await fetch('/api/insights/subscription-tags');
  state.subTags=tagsRes.ok?await tagsRes.json():{};
  renderAll();
}

function renderAll(){
  renderMonthPills();
  renderReality();
  renderCategories();
  renderMerchants();
  renderFrivolity();
  renderTrends();
  renderSubscriptions();
  document.getElementById('hdr-month').textContent=fmtMonth(state.currentMonth);
}

function stepMonth(dir){
  const idx=state.availableMonths.indexOf(state.currentMonth);
  const next=state.availableMonths[idx-dir]; // availableMonths is newest-first
  if(next)fetchInsights(next).catch(e=>alert(e.message));
}

async function init(){
  const res=await fetch('/api/insights/monthly');
  if(!res.ok){alert('Failed to load insights');return;}
  const d=await res.json();
  fetchInsights(d.month).catch(e=>alert(e.message));
}

init();
</script>
</body>
</html>
```

- [ ] **Step 2: Open http://localhost:5001/insights in browser**

Expected: Page loads, nav shows INSIGHTS as active. Month picker box visible (empty pills — no data rendered yet). No JS errors in console.

- [ ] **Step 3: Commit**

```bash
git add insights.html
git commit -m "feat(insights): add insights.html skeleton with nav, styles, and fetch scaffold"
```

---

## Task 6: Add `GET /api/insights/subscription-tags` endpoint and render month pills + reality check

**Files:**
- Modify: `server.py` — add `GET /api/insights/subscription-tags`
- Modify: `insights.html` — implement `renderMonthPills()` and `renderReality()`

- [ ] **Step 1: Add `GET /api/insights/subscription-tags` route** in `server.py` after `api_subscription_tag`:

```python
@app.get("/api/insights/subscription-tags")
def api_get_subscription_tags():
    return jsonify(get_subscription_tags())
```

- [ ] **Step 2: Restart server**

```bash
pkill -f "venv/bin/python server.py" 2>/dev/null; sleep 1
venv/bin/python server.py &
sleep 2
curl -s http://localhost:5001/api/insights/subscription-tags
```

Expected: `{}` (or existing tags if any were set in Task 3 testing).

- [ ] **Step 3: Implement `renderMonthPills()`** — add this function inside the `<script>` block in `insights.html`, before `renderAll()`:

```javascript
function renderMonthPills(){
  const pills=document.getElementById('monthPills');
  pills.innerHTML=state.availableMonths.map(m=>
    `<button class="mpill${m===state.currentMonth?' active':''}" onclick="fetchInsights('${m}').catch(e=>alert(e.message))">${fmtMonth(m)}</button>`
  ).join('');
}
```

- [ ] **Step 4: Implement `renderReality()`** — add after `renderMonthPills()`:

```javascript
function renderReality(){
  const d=state.data;
  if(!d)return;
  const prevLabel=fmtMonth(d.prev_month);
  document.getElementById('reality-label').textContent=`${fmtMonth(d.month)} · vs ${prevLabel}`;
  const discDelta=d.discretionary-(d.prev_discretionary||0);
  const rateDelta=d.savings_rate-(d.prev_savings_rate||0);
  const friv=d.frivolity?.score||0;
  const prevFriv=(d.frivolity?.history||[]).slice(-2,-1)[0]?.score||0;
  const frivDelta=friv-prevFriv;
  function deltaHtml(val,prefix='$',invert=false){
    if(Math.abs(val)<0.5)return`<span class="delta-flat">≈ flat</span>`;
    const up=val>0;
    const cls=invert?(up?'delta-down':'delta-up'):(up?'delta-up':'delta-down');
    const sign=up?'+':'';
    return`<span class="${cls}">${sign}${prefix==='$'?formatCurrency(val):val.toFixed(1)+'pp'} vs ${prevLabel}</span>`;
  }
  const saveRateColor=d.savings_rate>=40?'var(--green)':d.savings_rate>=20?'var(--amber)':'var(--red)';
  const frivColor=friv<30?'var(--green)':friv<50?'var(--amber)':'var(--red)';
  document.getElementById('reality-strip').innerHTML=`
    <div class="rc">
      <div class="rc-label">TAKE-HOME</div>
      <div class="rc-val green">${formatCurrency(d.income)}</div>
      <div class="rc-sub">salary · ${fmtMonth(d.month)}</div>
    </div>
    <div class="rc">
      <div class="rc-label">→ SAVED + INVESTED</div>
      <div class="rc-val" style="color:var(--blue)">${formatCurrency(d.saved)}</div>
      <div class="rc-sub">${d.income>0?Math.round(d.saved/d.income*100):0}% of take-home</div>
    </div>
    <div class="rc">
      <div class="rc-label">→ DISCRETIONARY</div>
      <div class="rc-val amber">${formatCurrency(d.discretionary)}</div>
      <div class="rc-delta">${deltaHtml(discDelta,'$',false)}</div>
    </div>
    <div class="rc">
      <div class="rc-label">SAVINGS RATE</div>
      <div class="rc-val" style="color:${saveRateColor}">${d.savings_rate}%</div>
      <div class="rc-delta">${deltaHtml(rateDelta,'pp',true)}</div>
    </div>
    <div class="rc">
      <div class="rc-label">FRIVOLITY SCORE</div>
      <div class="rc-val" style="color:${frivColor}">${friv}%</div>
      <div class="rc-delta">${deltaHtml(frivDelta,'pp',false)}</div>
    </div>
  `;
  // Allocation bar
  const saved_pct=d.income>0?d.saved/d.income*100:0;
  const disc_pct=d.income>0?d.discretionary/d.income*100:0;
  const leftover=Math.max(0,100-saved_pct-disc_pct);
  document.getElementById('alloc-bar').innerHTML=`
    <div class="alloc-seg" style="width:${saved_pct.toFixed(1)}%;background:#79c0ff88"></div>
    <div class="alloc-seg" style="width:${disc_pct.toFixed(1)}%;background:#f0b86e88"></div>
    <div class="alloc-seg" style="flex:1;background:var(--rule2)"></div>
  `;
  document.getElementById('alloc-legend').innerHTML=`
    <span style="font-size:10px;color:var(--dim2)"><span style="display:inline-block;width:8px;height:8px;background:#79c0ff88;margin-right:3px"></span>Saved ${saved_pct.toFixed(0)}%</span>
    <span style="font-size:10px;color:var(--dim2)"><span style="display:inline-block;width:8px;height:8px;background:#f0b86e88;margin-right:3px"></span>Spent ${disc_pct.toFixed(0)}%</span>
    ${d.savings_rate>=20?'<span style="font-size:10px;color:var(--green);margin-left:auto">Saving well — discretionary is comfortable at this rate</span>':'<span style="font-size:10px;color:var(--amber);margin-left:auto">Savings rate below 20% — worth reviewing discretionary spend</span>'}
  `;
}
```

- [ ] **Step 5: Reload http://localhost:5001/insights**

Expected: Month pills appear (most recent month active), reality check strip shows income / saved / discretionary / savings rate / frivolity score with delta badges. Allocation bar appears below. No JS errors.

- [ ] **Step 6: Commit**

```bash
git add server.py insights.html
git commit -m "feat(insights): render month pills and reality check strip"
```

---

## Task 7: Render top categories and top merchants tables

**Files:**
- Modify: `insights.html` — implement `renderCategories()` and `renderMerchants()`

- [ ] **Step 1: Implement `renderCategories()`** in `insights.html` script, after `renderReality()`:

```javascript
function renderCategories(){
  const d=state.data;
  if(!d)return;
  document.getElementById('cat-period').textContent=fmtMonth(d.month);
  const maxSpend=d.top_categories[0]?.total||1;
  document.getElementById('catBody').innerHTML=d.top_categories.map(cat=>{
    const meta=catMeta(cat.slug);
    const delta=cat.total-(cat.prev_total||0);
    const pct=cat.total/maxSpend*100;
    let deltaTxt='—';let deltaCls='dim2';
    if(Math.abs(delta)>1){
      const sign=delta>0?'+':'';
      deltaTxt=sign+formatCurrency(delta);
      deltaCls=delta>0?'delta-up':'delta-down';
    }
    return`<tr>
      <td style="color:${meta.color}">${meta.icon} ${cat.slug==='uncategorised'?'Uncategorised':cat.slug.replace(/-/g,' ').replace(/\b\w/g,c=>c.toUpperCase())}</td>
      <td style="text-align:right;color:var(--amber)">${formatCurrency(cat.total)}</td>
      <td style="text-align:right;color:var(--dim2)">${cat.pct_of_disc}%</td>
      <td><div class="bar-wrap"><div class="bar" style="width:${pct.toFixed(1)}%;background:${meta.color}99"></div></div></td>
      <td style="text-align:right" class="${deltaCls}">${deltaTxt}</td>
    </tr>`;
  }).join('');
}
```

- [ ] **Step 2: Implement `renderMerchants()`** after `renderCategories()`:

```javascript
function renderMerchants(){
  const d=state.data;
  if(!d)return;
  document.getElementById('merch-period').textContent=`top 15 · ${fmtMonth(d.month)}`;
  const maxTotal=d.top_merchants[0]?.total||1;
  document.getElementById('merchBody').innerHTML=d.top_merchants.map(m=>{
    const meta=catMeta(m.category);
    const pct=m.total/maxTotal*100;
    return`<tr>
      <td>${merchantIconHtml(m.description)}</td>
      <td style="font-weight:500">${m.description}</td>
      <td style="text-align:right;color:var(--dim2)">${m.count}</td>
      <td style="text-align:right;color:var(--amber)">${formatCurrency(m.total)}</td>
      <td style="text-align:right;color:var(--dim2);font-size:11px">${formatCurrency(m.cumulative)}</td>
      <td><div class="bar-wrap"><div class="bar" style="width:${pct.toFixed(1)}%;background:${meta.color}99"></div></div></td>
    </tr>`;
  }).join('');
}
```

- [ ] **Step 3: Reload http://localhost:5001/insights**

Expected: Top categories table shows up to 15 rows with category colour, spend, % of discretionary, share bar, and delta vs previous month. Top merchants table shows favicon, name, txn count, total, running cumulative. No broken layout.

- [ ] **Step 4: Commit**

```bash
git add insights.html
git commit -m "feat(insights): render top categories and merchants tables"
```

---

## Task 8: Render frivolity score panel and category trends table

**Files:**
- Modify: `insights.html` — implement `renderFrivolity()` and `renderTrends()`

- [ ] **Step 1: Implement `renderFrivolity()`** in `insights.html` script, after `renderMerchants()`:

```javascript
function renderFrivolity(){
  const d=state.data;
  if(!d||!d.frivolity)return;
  const f=d.frivolity;
  const score=f.score||0;
  const ringColor=score<30?'var(--green)':score<50?'var(--amber)':'var(--red)';
  const maxContrib=f.drivers[0]?.contribution||1;
  const driversHtml=f.drivers.map(dr=>{
    const meta=catMeta(dr.slug);
    return`<div style="display:flex;justify-content:space-between;align-items:center;font-size:11px;padding:2px 0;border-bottom:1px solid var(--rule2)">
      <span style="color:${meta.color}">${meta.icon} ${dr.slug.replace(/-/g,' ').replace(/\b\w/g,c=>c.toUpperCase())}</span>
      <span style="color:var(--dim2)">${formatCurrency(dr.total)} × ${dr.weight} = <strong style="color:var(--amber)">${formatCurrency(dr.contribution)}</strong></span>
    </div>`;
  }).join('');
  // Mini bar chart for 6-month trend
  const hist=f.history||[];
  const maxScore=Math.max(...hist.map(h=>h.score),1);
  const miniBars=hist.map(h=>{
    const ht=Math.max(h.score/maxScore*100,4);
    const col=h.score<30?'var(--green)':h.score<50?'var(--amber)':'var(--red)';
    const mo=h.month.split('-')[1];
    const moLabel=['J','F','M','A','M','J','J','A','S','O','N','D'][parseInt(mo)-1];
    return`<div style="display:flex;flex-direction:column;align-items:center;gap:2px">
      <div class="mini-bar" style="height:${ht.toFixed(0)}%;background:${col};width:16px;min-height:2px;border-radius:1px 1px 0 0"></div>
      <span style="font-size:9px;color:var(--dim2)">${moLabel}</span>
    </div>`;
  }).join('');
  document.getElementById('frivolity-inner').innerHTML=`
    <div style="display:flex;flex-direction:column;align-items:center;gap:8px;flex-shrink:0">
      <div class="score-ring" style="border:3px solid ${ringColor}">
        <div class="sr-val" style="color:${ringColor}">${score}%</div>
        <div class="sr-lbl">${fmtMonth(d.month).split(' ')[0].toUpperCase()}</div>
      </div>
      <div style="display:flex;gap:2px;align-items:flex-end;height:44px">${miniBars}</div>
      <div style="font-size:9px;color:var(--dim2);text-align:center">6mo trend</div>
    </div>
    <div style="flex:1">
      <div style="font-size:10px;color:var(--dim2);letter-spacing:0.06em;text-transform:uppercase;margin-bottom:6px">DRIVERS THIS MONTH</div>
      ${driversHtml}
      <div style="margin-top:6px;font-size:10px;color:var(--dim2)">
        Weighted "wants" total: <span style="color:var(--amber)">${formatCurrency(f.weighted_total)}</span>
        of <span style="color:var(--amber)">${formatCurrency(d.discretionary)}</span> discretionary
      </div>
    </div>
  `;
}
```

- [ ] **Step 2: Implement `renderTrends()`** after `renderFrivolity()`:

```javascript
function renderTrends(){
  const d=state.data;
  if(!d||!d.trends)return;
  document.getElementById('trendsBody').innerHTML=d.trends.map(t=>{
    const meta=catMeta(t.slug);
    const s=t.slope_per_month;
    let dirHtml='<span class="delta-flat">→</span>';
    if(s>30)dirHtml='<span class="delta-up">↑↑</span>';
    else if(s>10)dirHtml='<span style="color:var(--amber)">↑</span>';
    else if(s<-30)dirHtml='<span class="delta-down">↓↓</span>';
    else if(s<-10)dirHtml='<span class="delta-down">↓</span>';
    const slopeColor=s>10?'var(--red)':s<-10?'var(--green)':'var(--dim2)';
    const sign=s>0?'+':'';
    return`<tr>
      <td style="color:${meta.color};font-size:11px">${meta.icon} ${t.slug.replace(/-/g,' ').replace(/\b\w/g,c=>c.toUpperCase())}</td>
      <td style="text-align:right;color:var(--dim2);font-size:11px">${formatCurrency(t.avg_3mo)}</td>
      <td style="text-align:right;color:var(--amber);font-size:11px">${formatCurrency(t.this_month)}</td>
      <td style="text-align:right;font-size:11px;color:${slopeColor}">${sign}${formatCurrency(s)}/mo</td>
      <td style="text-align:center">${dirHtml}</td>
    </tr>`;
  }).join('');
}
```

- [ ] **Step 3: Reload http://localhost:5001/insights**

Expected: Frivolity panel shows score ring in correct colour (green <30%, amber 30–50%, red >50%), 6-month mini bars, and weighted driver list. Trends table shows top 8 categories with 3mo avg, this month, slope in $/mo, and directional arrows. No JS errors.

- [ ] **Step 4: Commit**

```bash
git add insights.html
git commit -m "feat(insights): render frivolity score panel and category trends table"
```

---

## Task 9: Render recurring subscriptions with KEEP/REVIEW/CUT tags

**Files:**
- Modify: `insights.html` — implement `renderSubscriptions()` and `toggleSubTag()`

- [ ] **Step 1: Implement `renderSubscriptions()` and `toggleSubTag()`** in `insights.html` script, after `renderTrends()`:

```javascript
const TAG_CYCLE={undefined:'KEEP',null:'KEEP','KEEP':'REVIEW','REVIEW':'CUT','CUT':null};

async function toggleSubTag(description){
  const current=state.subTags[description]||null;
  const next=TAG_CYCLE[current];
  try{
    await fetch('/api/insights/subscription-tag',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({description,tag:next}),
    });
    if(next===null){delete state.subTags[description];}
    else{state.subTags[description]=next;}
    renderSubscriptions();
  }catch(e){alert('Failed to save tag: '+e.message);}
}

function renderSubscriptions(){
  const data=state.recurring||[];
  const box=document.getElementById('subs-box');
  if(!data.length){box.style.display='none';return;}
  box.style.display='block';
  const total=data.reduce((s,r)=>s+r.monthly_cost,0);
  const cutTotal=data.filter(r=>state.subTags[r.description]==='CUT').reduce((s,r)=>s+r.monthly_cost,0);
  document.getElementById('subs-count').textContent=
    `${data.length} detected · ${formatCurrency(total)}/mo${cutTotal>0?' · '+formatCurrency(cutTotal)+'/mo earmarked to cut':''}`;
  const today=new Date().toISOString().slice(0,10);
  document.getElementById('subsBody').innerHTML=data.map(r=>{
    const tag=state.subTags[r.description]||null;
    const tagCls=tag?tag.toLowerCase():'';
    const due=r.next_expected<=today;
    const isCut=tag==='CUT';
    const tagLabel=tag||'TAG';
    return`<tr class="${isCut?'cut-row':''}">
      <td>${merchantIconHtml(r.description)}</td>
      <td style="font-weight:500">${r.description}</td>
      <td style="text-align:right;color:var(--dim2)">${r.interval_days}d</td>
      <td style="text-align:right;color:var(--dim2)">${formatCurrency(r.median_amount)}</td>
      <td style="text-align:right;color:var(--amber)">${formatCurrency(r.monthly_cost)}</td>
      <td style="text-align:right;color:var(--dim2);font-size:11px">${r.last_date}</td>
      <td style="text-align:right;font-size:11px;color:${due?'var(--amber)':'var(--dim2)'}">${r.next_expected}${due?' ⚠':''}</td>
      <td style="text-align:center">
        <button class="tag-btn ${tagCls}" onclick="toggleSubTag('${r.description.replace(/'/g,"\\'")}')">
          ${tagLabel}
        </button>
      </td>
    </tr>`;
  }).join('');
}
```

- [ ] **Step 2: Reload http://localhost:5001/insights**

Expected: Recurring subscriptions section shows detected recurring charges. Each row has a TAG button. Clicking cycles: untagged → KEEP (green) → REVIEW (amber) → CUT (red) → untagged. CUT rows are dimmed with strikethrough. Section header shows total monthly cost and earmarked-to-cut total if any. Tags survive page reload.

- [ ] **Step 3: Commit**

```bash
git add insights.html
git commit -m "feat(insights): render subscription table with KEEP/REVIEW/CUT tag cycling"
```

---

## Task 10: Final checks and cleanup

**Files:**
- Test: manual browser verification
- Modify: `insights.html` if any fixes needed

- [ ] **Step 1: Test month navigation with arrow keys**

Open http://localhost:5001/insights. Press `←` and `→` keys. Expected: page re-fetches and re-renders for the previous/next month. Active pill in the month picker updates accordingly. No JS errors.

- [ ] **Step 2: Test clicking a month pill**

Click a month pill that is not the current one. Expected: all sections update to reflect that month's data. Reality check deltas now compare to *that month's* previous month.

- [ ] **Step 3: Verify `[I]` key works from spending page**

Open http://localhost:5001/spending. Press `I`. Expected: navigates to `/insights`.

- [ ] **Step 4: Verify `[S]` key works from insights page**

Open http://localhost:5001/insights. Press `S`. Expected: navigates to `/spending`.

- [ ] **Step 5: Check mobile layout**

Open http://localhost:5001/insights, resize browser to ~375px wide. Expected: two-col grids stack to single column. Reality strip stacks vertically. No horizontal overflow. Text remains legible.

- [ ] **Step 6: Kill the background server**

```bash
pkill -f "venv/bin/python server.py"
```

- [ ] **Step 7: Final commit**

```bash
git add -A
git status  # verify only expected files are staged
git commit -m "feat(insights): complete spending insights page

New /insights page with reality check strip, top categories/merchants,
frivolity score (weighted by category), category trends (linear slope),
and subscription tagging (KEEP/REVIEW/CUT persisted to config.json).
Month picker with arrow key navigation.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| New `/insights` page | Task 5 |
| `GET /insights` Flask route | Task 3 |
| `GET /api/insights/monthly` endpoint | Task 2 |
| `POST /api/insights/subscription-tag` endpoint | Task 3 |
| `GET /api/insights/subscription-tags` endpoint | Task 6 |
| `FRIVOLITY_WEIGHTS` constant | Task 1 |
| `linear_slope()` helper | Task 1 |
| `[I]` nav key on all pages | Task 4 |
| Month picker pills (last 12 months) | Task 6 |
| Arrow key month navigation | Task 5 (KEYS handler) + Task 10 (verification) |
| Reality check strip with deltas | Task 6 |
| Income allocation bar | Task 6 |
| Top categories table with Δ prev month | Task 7 |
| Top merchants table with cumulative | Task 7 |
| Frivolity score ring + 6-month mini bars | Task 8 |
| Frivolity drivers breakdown | Task 8 |
| Category trends with slope + direction arrows | Task 8 |
| Recurring subscriptions table | Task 9 |
| KEEP/REVIEW/CUT tag cycling | Task 9 |
| Tags persisted to config.json | Task 3 + Task 9 |
| CUT rows dimmed with strikethrough | Task 9 |
| Favicon icons on merchants + subscriptions | Tasks 7, 9 (via `merchantIconHtml()`) |

**Placeholder scan:** No TBDs, no "implement later", all code blocks complete.

**Type consistency check:**
- `state.data` shape matches `api_insights_monthly` JSON response throughout
- `state.subTags` is `{[description: string]: string}` — used consistently in `toggleSubTag()` and `renderSubscriptions()`
- `state.recurring` is the array from `/api/spending/recurring` — shape `{description, monthly_cost, median_amount, interval_days, last_date, next_expected}` — matches `renderSubscriptions()` usage
- `_compute_month_cashflow()` returns `{income, saved, discretionary, savings_rate}` — `renderReality()` accesses `d.income`, `d.saved`, `d.discretionary`, `d.savings_rate`, `d.prev_savings_rate`, `d.prev_discretionary` — all present in the `api_insights_monthly` response
- `linear_slope()` takes `List[float]`, returns `float` — used correctly in trend computation
- `FRIVOLITY_WEIGHTS` is `Dict[str, float]` — accessed via `.get(cat, 0.5)` throughout
