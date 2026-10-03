#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from shared_expenses import (
    allocation_from_legacy_row,
    load_allocations,
    read_rows,
    save_allocations,
)


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"


def migrate(source: Path, data_dir: Path = DATA_DIR) -> dict:
    legacy_rows = read_rows(source)
    allocations = load_allocations(data_dir)
    existing_ids = {row.get("allocation_id", "") for row in allocations}

    added = 0
    for index, row in enumerate(legacy_rows, start=1):
        allocation = allocation_from_legacy_row(row, row_number=index)
        if allocation["allocation_id"] in existing_ids:
            continue
        allocations.append(allocation)
        existing_ids.add(allocation["allocation_id"])
        added += 1

    allocations.sort(key=lambda row: (row.get("date", ""), row.get("description", "")), reverse=True)
    save_allocations(data_dir, allocations)
    return {"source_rows": len(legacy_rows), "added": added, "total": len(allocations)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy joint_ledger.csv into shared_allocations.csv")
    parser.add_argument(
        "source",
        nargs="?",
        default=str(DATA_DIR / "joint_ledger.csv"),
        help="Path to legacy joint_ledger.csv",
    )
    args = parser.parse_args()
    result = migrate(Path(args.source))
    print(result)


if __name__ == "__main__":
    main()
