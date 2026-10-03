# Finance Dashboard

Local Flask dashboard for Angus's personal finances. Tracks Up Bank transactions, house bill cycles, spending, net worth, investments, and property planning.

## Setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install flask requests python-dateutil openpyxl

cp config.example.json config.json
# Paste your Up Personal Access Token into "token"

python server.py
# Open http://localhost:5001
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

- `data/transactions_all.csv` — unified local Up transaction history across every owned account (gitignored)

- `data/networth.csv` — weekly net worth snapshots (gitignored)
- `data/transactions_essentials.csv` — current Up Essentials transactions (gitignored)
- `data/transactions_savings.csv` — Savings transactions (gitignored)
- `data/transactions_2up.csv` — legacy 2Up transactions retained for historical bill classification (gitignored)
- `data/holdings.csv` — investment parcels (gitignored), update prices manually
- `data/attribution.csv` — optional attribution breakdown (safe to commit)
- `data/bills.csv` — bill definitions (committed)
- `data/housemates.csv` — housemate rent shares (committed)
- `data/Net worth calculator.xlsx` — source Excel file (gitignored)

## Net Worth Import

1. Open `/networth`
2. Enter your current super balance in the field (pre-filled from last recorded value)
3. Click "Import from Excel"

The importer reads `data/Net worth calculator.xlsx` (sheet: `Historical`) and upserts rows into `data/networth.csv`. Re-running is safe — existing rows are overwritten by date, no duplicates. `total_aud` is recalculated as `cash + investments + super`.

## Portfolio

Add holdings manually to `data/holdings.csv`. Update `current_price_aud` and `current_value_aud` to keep the CGT calculator and house planner accurate.

## Tag Convention (Up Bank)

- Housemate: `angus`, `sean`, `alex`, `jarrod`, `ryan`
- Bill cycle: `{slug}-{mmm}-{yyyy}` e.g. `rent-apr-2026`
- Canonical slugs: `rent`, `elec`, `water`, `internet`, `gas`

## Refresh Behaviour

The `Refresh` button on the bills page calls `/sync`, which:

- validates the Up token in `config.json`
- auto-discovers missing account IDs from `/accounts`
- auto-discovers the active Spending, Savings, Grow, and Essentials account IDs
- fetches new Spending, Savings, and Essentials transactions since the last sync timestamp
- keeps the old 2Up account ID and transaction CSV only for historical classification
- appends only new transaction IDs to the CSVs
- updates the saved sync timestamps in `config.json`

## Runway / clean spending analysis

Open `/runway` for the since-income-stopped view. It separates ordinary spend from planned one-offs, treats travel as a one-off by default, excludes transfers between every currently owned Up account, compares lifestyle spending with the 90 days before the selected stop date, and calculates cash runway from the latest net-worth snapshot.

The Up sync now refreshes the full account catalogue on every run and keeps a unified local transaction file so transfers to saver accounts such as Ridley Bills or tipping accounts are recognised as internal rather than spending.

Spend treatment defaults live in `config.json` under `spending_treatments`. Category or merchant overrides can be set to `essential`, `lifestyle`, `one_off`, or `exclude`.
