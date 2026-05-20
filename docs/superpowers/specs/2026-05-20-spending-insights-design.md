# Spending Insights Page — Design Spec

**Date:** 2026-05-20  
**Branch:** feature/spending-insights  
**Status:** Approved

---

## Overview

A new `/insights` page (`insights.html`) that gives Angus a dense, readable snapshot of his most recent month's spending — designed to be shared with Claude for contextual commentary ("you spent $487 on takeaway, here's what that actually means relative to your income and savings rate").

Not a budget-management tool. Not alert-driven. A rich data surface optimised for human + AI interpretation.

---

## Goals

- Show what's being spent the most on, in plain numbers
- Anchor all spend figures to take-home and savings rate so amounts have context
- Surface frivolity (weighted wants vs needs ratio) trended over time
- Show which subscription costs are potentially wasteful, with a keep/review/cut tag
- Allow comparison to any previous month via a pill picker

---

## Architecture

### New files
- `insights.html` — single-file page, vanilla JS + Chart.js, same stack as rest of dash

### Modified files
- `server.py` — add `GET /insights` route + 2 new API endpoints

### New API endpoints

#### `GET /api/insights/monthly?month=2026-04`

Returns everything the insights page needs in one call. `month` param is `YYYY-MM`; defaults to the most recent complete calendar month if omitted.

```json
{
  "month": "2026-04",
  "prev_month": "2026-03",
  "available_months": ["2025-05", "2025-06", ..., "2026-04"],
  "income": 8869.00,
  "saved": 5150.00,
  "discretionary": 3241.00,
  "savings_rate": 58.1,
  "top_categories": [
    {"slug": "takeaway", "total": 487.0, "prev_total": 361.0, "pct_of_disc": 15.0}
  ],
  "top_merchants": [
    {"description": "Woolworths", "total": 412.0, "count": 11, "cumulative": 412.0, "category": "groceries"}
  ],
  "frivolity": {
    "score": 38.2,
    "weighted_total": 738.0,
    "drivers": [
      {"slug": "takeaway", "total": 487.0, "weight": 0.90, "contribution": 438.3}
    ],
    "history": [
      {"month": "2025-11", "score": 29.1},
      {"month": "2025-12", "score": 27.4},
      ...
    ]
  },
  "trends": [
    {"slug": "takeaway", "slope_per_month": 42.0, "avg_3mo": 361.0, "this_month": 487.0}
  ]
}
```

Server logic:
- `income`, `saved`, `discretionary` — same computation as `_cashflow_monthly()`, scoped to the requested month
- `top_categories` — spend per category for the month + same category's spend in `prev_month`
- `top_merchants` — top 15 by spend for the month, with running cumulative added client-side
- `frivolity.score` — `sum(spend[cat] * FRIVOLITY_WEIGHTS.get(cat, 0.5)) / discretionary * 100`
- `frivolity.history` — frivolity score for each of the last 6 months (reuses category-history data)
- `trends` — linear regression slope (least squares) over last 6 months per category, returning $/month

#### `POST /api/insights/subscription-tag`

Tags a recurring subscription as KEEP / REVIEW / CUT.

Request: `{"description": "Uber One", "tag": "KEEP"}` (tag is one of `"KEEP"`, `"REVIEW"`, `"CUT"`, `null` to clear)

Stores under `config.json["subscription_tags"]`: `{"Uber One": "KEEP", "Adobe": "CUT"}`.

Response: `{"ok": true}`

---

## Page Layout

### Nav
- Key: `[I]` → `/insights`
- Added to nav bar on all pages

### 1. Month picker
Compact pill row showing the last 12 complete months, newest first. Defaults to most recent complete month on load. Clicking a pill calls `fetchInsights(month)` and re-renders the whole page. No date range inputs.

### 2. Reality check strip
Horizontal band: **TAKE-HOME → SAVED+INVESTED → DISCRETIONARY → FRIVOLITY SCORE**

Each cell shows the value + a delta badge vs previous month (`↑ +$287 vs Mar`, coloured red/green). An income allocation bar (blue = saved, amber = spent) sits underneath with a one-line contextual label (e.g. "You spent 37% of take-home — still saved 58%, well above target").

### 3. Top categories + Top merchants (side by side)

**Top categories table** columns: CATEGORY | SPENT | % OF DISC | SHARE (bar) | Δ VS PREV MO

**Top merchants table** (top 15) columns: FAVICON | MERCHANT | TXN | TOTAL | CUMULATIVE | SHARE (bar)  
Cumulative column shows running total as you scroll down (e.g. row 1 = $412, row 2 = $716...). Favicons from Google Favicons API via existing `merchantIconHtml()`.

### 4. Frivolity breakdown + Category trends (side by side)

**Frivolity panel:**
- Score ring showing current month % in amber/red depending on level
- 6-month mini bar chart (coloured green < 30%, amber 30–50%, red > 50%)
- Drivers table: CATEGORY | SPEND | WEIGHT | CONTRIBUTION — sorted by contribution desc

**Category trends panel:**
- Table: CATEGORY | 3MO AVG | THIS MONTH | SLOPE | DIR
- Slope shown as `+$42/mo` or `−$11/mo`
- Direction arrows: `↑↑` slope > $30/mo (red), `↑` $10–30 (amber), `→` ±$10 (dim), `↓` −$10 to −$30 (green), `↓↓` < −$30 (green)
- Top 8 categories by total spend shown

### 5. Recurring subscriptions

Table of all detected recurring charges (from `/api/spending/recurring`), showing:

FAVICON | MERCHANT | INTERVAL | AMT/TXN | ~MONTHLY | LAST | NEXT | TAG

**TAG column:** Three-state toggle button cycling `unmarked → KEEP → REVIEW → CUT → unmarked`. Colours: KEEP = green, REVIEW = amber, CUT = red. State persisted immediately on click via `POST /api/insights/subscription-tag`. Tags survive page reload.

Total monthly recurring cost shown in section header. CUT-tagged subscriptions shown with strikethrough + dimmed to signal "earmarked for cancellation."

---

## Frivolity Weights

Hardcoded in `server.py`. Any category not listed defaults to `0.50`.

```python
FRIVOLITY_WEIGHTS = {
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
```

---

## Trend Slope Calculation

Ordinary least squares over the last 6 complete months of spend per category. Uses the same raw data as `/api/spending/category-history`. Months with zero spend are included as 0 (not excluded — a zero month is meaningful data). Returns slope in $/month rounded to 2dp.

```python
def linear_slope(values: list[float]) -> float:
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

---

## Data Flow

```
Page load
  → fetchInsights('2026-04')
      → GET /api/insights/monthly?month=2026-04   (one call, all data)
      → GET /api/spending/recurring                (subscription list)
  → render all sections
  → subscription tag clicks → POST /api/insights/subscription-tag (immediate)
```

Month pill click → same flow with new month param.

---

## Keyboard shortcuts

- `[I]` navigates to `/insights` from any page (added to `KEYS` map in all HTML files)
- Left/right arrow keys on insights page step through months (prev/next pill)

---

## Files changed

| File | Change |
|---|---|
| `insights.html` | New file — full page |
| `server.py` | Add `GET /insights`, `GET /api/insights/monthly`, `POST /api/insights/subscription-tag`, `FRIVOLITY_WEIGHTS` constant, `linear_slope()` helper |
| All existing `.html` files | Add `i: '/insights'` to `KEYS` map |

---

## Out of scope

- Editable frivolity weights (hardcoded for now)
- AI-generated text on the page (commentary happens in Claude Code chat)
- Date range mode (month-at-a-time only)
- Savings rate chart enhancements (existing chart is sufficient)
