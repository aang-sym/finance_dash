# Insights Drill-Down Panel Design

**Goal:** Clicking any category or merchant row on the `/insights` page opens a slide-in panel showing a 6-month trend chart, top merchants (for categories), and individual transactions for the selected month.

**Architecture:** All UI lives inside `insights.html` — no new route or page. Two new Flask endpoints supply the panel data. The panel is a fixed-position overlay rendered into a `<div id="drill-panel">` that already exists in the DOM, toggled via CSS class.

**Tech Stack:** Vanilla JS, Chart.js 4.4.0 (already loaded), Flask, same CSV data layer as the rest of the dash.

---

## Panel Behaviour

- Slides in from the right, fixed width ~480px, full viewport height.
- Semi-transparent dark overlay (`rgba(0,0,0,0.5)`) covers the rest of the page.
- Closed by: `[X]` button in panel header, clicking the overlay, or pressing `Esc`.
- Respects `state.currentMonth` — data is always scoped to the month currently selected on the insights page.
- Only one panel open at a time. Opening a second drill-down replaces the first.
- Panel header shows: category slug (formatted, e.g. "Restaurants & Cafes") or merchant name + favicon.

## Panel Content

### Category drill-down (e.g. clicking "takeaway")

1. **6-month bar chart** — monthly spend for that category over the 6 months ending at `state.currentMonth`. Uses Chart.js bar chart, `--green` colour, consistent with the rest of the dash.
2. **Top merchants this month** — table of merchants within the category for the selected month: favicon | name | txn count | total spend. Sorted by total descending. Max 10 rows.
3. **Transactions this month** — all individual transactions in this category for the selected month. Columns: date | favicon | description | category chip | amount. Sorted by date descending.

### Merchant drill-down (e.g. clicking "Uber Eats")

1. **6-month bar chart** — monthly spend at this merchant over the 6 months ending at `state.currentMonth`.
2. **Transactions this month** — all individual transactions from this merchant for the selected month. Same columns as above. No top-merchants sub-table (already at merchant level).

## API Endpoints

### `GET /api/insights/category`

**Query params:** `slug` (category string, e.g. `takeaway`), `month` (YYYY-MM, defaults to most recent complete month)

**Response:**
```json
{
  "slug": "takeaway",
  "month": "2026-04",
  "history": [
    {"month": "2025-11", "total": 420.50},
    {"month": "2025-12", "total": 380.00},
    {"month": "2026-01", "total": 510.25},
    {"month": "2026-02", "total": 295.00},
    {"month": "2026-03", "total": 460.10},
    {"month": "2026-04", "total": 613.93}
  ],
  "top_merchants": [
    {"description": "Uber Eats", "total": 210.50, "count": 8},
    {"description": "DoorDash", "total": 180.00, "count": 5}
  ],
  "transactions": [
    {"date": "2026-04-22", "description": "Uber Eats", "category": "takeaway", "amount": 34.50},
    {"date": "2026-04-19", "description": "DoorDash", "category": "takeaway", "amount": 28.00}
  ]
}
```

### `GET /api/insights/merchant`

**Query params:** `name` (merchant description string, e.g. `Uber Eats`), `month` (YYYY-MM)

**Response:**
```json
{
  "name": "Uber Eats",
  "month": "2026-04",
  "history": [
    {"month": "2025-11", "total": 95.00},
    {"month": "2025-12", "total": 120.50},
    {"month": "2026-01", "total": 88.00},
    {"month": "2026-02", "total": 60.00},
    {"month": "2026-03", "total": 145.00},
    {"month": "2026-04", "total": 210.50}
  ],
  "transactions": [
    {"date": "2026-04-22", "description": "Uber Eats", "category": "takeaway", "amount": 34.50},
    {"date": "2026-04-18", "description": "Uber Eats", "category": "takeaway", "amount": 42.00}
  ]
}
```

Both endpoints filter out internal transfers (savings, grow, two_up account IDs) using the same logic as `api_insights_monthly`. History always covers the 6 months ending at the requested month (not the current date), so historical month selections show the correct 6-month window for that point in time.

## Files

- **Modify:** `server.py` — add `GET /api/insights/category` and `GET /api/insights/merchant`
- **Modify:** `insights.html` — add panel HTML structure, panel CSS, click handlers on category/merchant rows, `fetchDrillDown(type, key)`, `renderPanel(data, type)`, `closePanel()`, Chart.js instance management for panel chart

## Error Handling

- If a category or merchant has no data for the selected month, `top_merchants` and `transactions` return empty arrays; `history` may contain zeros. The panel renders gracefully with "No transactions this month" text.
- Network errors on drill-down fetch show a brief inline error in the panel rather than an `alert()`.
