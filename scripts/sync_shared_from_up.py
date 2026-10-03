#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from shared_expenses import load_allocations, read_rows, save_allocations, sync_up_allocations


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"


def main() -> None:
    transactions_path = DATA_DIR / "transactions_all.csv"
    if not transactions_path.exists():
        raise SystemExit("data/transactions_all.csv not found. Run python sync.py first.")

    transactions = read_rows(transactions_path)
    allocations = load_allocations(DATA_DIR)
    merged, stats = sync_up_allocations(transactions, allocations)
    save_allocations(DATA_DIR, merged)
    print(stats)


if __name__ == "__main__":
    main()
