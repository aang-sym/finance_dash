"""
parse_hevy.py — Import Hevy workout CSV into workout_sets table.

Hevy CSV columns:
  title, start_time, end_time, description, exercise_title,
  superset_id, exercise_notes, set_index, set_type, weight_kg,
  reps, distance_km, duration_seconds, rpe

set_type values: "normal", "warmup", "drop_set", "failure"
Date format: "13 Jan 2026, 09:40"

Mapping to workout_sets:
  date         ← start_time (date part)
  workout_name ← title
  duration_s   ← end_time - start_time (seconds)
  exercise     ← exercise_title
  set_type     ← normalised (normal→Standard Set, warmup→Warm-Up Set, etc.)
  weight_kg    ← weight_kg
  reps         ← reps
  rir          ← None (Hevy tracks RPE not RIR; store in base_weight_kg field? No — leave None)
  base_weight_kg ← None

De-duplication: existing rows with same date + workout_name + exercise + set_index are skipped.
We add a source column if missing, but since the table doesn't have one we use
(date, workout_name, exercise, weight_kg, reps, set_type) as a natural key via INSERT OR IGNORE
after adding a unique constraint — but that's risky. Instead we just DELETE rows for sessions
whose dates appear in the import (replace-session strategy) then re-insert.

Actually safest: check if a set already exists by counting matching rows for the session date +
workout_name + exercise. If count ≥ rows in this file for that session, skip it. Otherwise do
a full session replace. Use a simpler approach: add a unique_key column or use INSERT OR IGNORE
with a derived key stored in exercise field.

Simplest clean approach:
1. Collect all (date, workout_name) session keys from the CSV.
2. Delete existing workout_sets rows for those sessions where source IS NULL or source = 'hevy'.
   (We need a source column for this — add it if missing.)
3. Insert fresh from CSV.
"""

import csv
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Union

DB_PATH = Path(__file__).parent.parent / "data" / "health" / "health.db"
HEVY_DATE_FMT = "%d %b %Y, %H:%M"

SET_TYPE_MAP = {
    "normal": "Standard Set",
    "warmup": "Warm-Up Set",
    "drop_set": "Drop Set",
    "failure": "Failure Set",
}


def _ensure_source_column(conn: sqlite3.Connection) -> None:
    """Add source column to workout_sets if it doesn't exist."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(workout_sets)").fetchall()]
    if "source" not in cols:
        conn.execute("ALTER TABLE workout_sets ADD COLUMN source TEXT")
        conn.commit()


def _ensure_rpe_column(conn: sqlite3.Connection) -> None:
    """Add rpe column to workout_sets if it doesn't exist (for Hevy data)."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(workout_sets)").fetchall()]
    if "rpe" not in cols:
        conn.execute("ALTER TABLE workout_sets ADD COLUMN rpe REAL")
        conn.commit()


def parse_hevy_csv(csv_path: Union[str, Path], progress_cb=None) -> dict:
    """
    Parse a Hevy workout CSV and insert into workout_sets.
    Returns counts dict: {inserted, skipped_sessions, total_rows}.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Hevy CSV not found: {csv_path}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA journal_mode = WAL")

    _ensure_source_column(conn)
    _ensure_rpe_column(conn)

    # Parse CSV into session-grouped structure
    sessions: dict[tuple, list] = {}  # (date_str, workout_name) → [row, ...]

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dt = datetime.strptime(row["start_time"], HEVY_DATE_FMT)
                end_dt = datetime.strptime(row["end_time"], HEVY_DATE_FMT)
            except ValueError:
                continue

            date_str = dt.strftime("%Y-%m-%d")
            duration_s = (end_dt - dt).total_seconds()
            key = (date_str, row["title"])

            if key not in sessions:
                sessions[key] = {"duration_s": duration_s, "rows": []}

            weight_kg = float(row["weight_kg"]) if row.get("weight_kg") else None
            reps = float(row["reps"]) if row.get("reps") else None
            rpe = float(row["rpe"]) if row.get("rpe") else None
            set_type = SET_TYPE_MAP.get(row["set_type"], "Standard Set")

            sessions[key]["rows"].append({
                "date": date_str,
                "workout_name": row["title"],
                "duration_s": duration_s,
                "exercise": row["exercise_title"],
                "set_type": set_type,
                "weight_kg": weight_kg,
                "reps": reps,
                "rpe": rpe,
            })

    total_sessions = len(sessions)
    inserted = 0
    skipped_sessions = 0

    for i, ((date_str, workout_name), session_data) in enumerate(sessions.items()):
        # Check if this session already exists from Hevy source
        existing = conn.execute(
            "SELECT COUNT(*) FROM workout_sets WHERE date=? AND workout_name=? AND source='hevy'",
            (date_str, workout_name),
        ).fetchone()[0]

        if existing > 0:
            skipped_sessions += 1
            continue

        # Also check if it exists from MacroFactor (same session, different source)
        # In this case we leave MacroFactor data alone and also insert Hevy data
        # (they may have different exercises tracked)
        mf_existing = conn.execute(
            "SELECT COUNT(*) FROM workout_sets WHERE date=? AND workout_name LIKE ? AND (source IS NULL OR source='macrofactor')",
            (date_str, f"%{workout_name[:20]}%"),
        ).fetchone()[0]

        # Insert Hevy rows for this session
        rows_to_insert = session_data["rows"]

        # If MacroFactor already has this exact workout name+date, skip to avoid duplication
        # (MacroFactor is more detailed — has RIR data which Hevy lacks)
        mf_exact = conn.execute(
            "SELECT COUNT(*) FROM workout_sets WHERE date=? AND (source IS NULL OR source='macrofactor')",
            (date_str,),
        ).fetchone()[0]

        if mf_exact > 0:
            # MacroFactor already has data for this date — skip Hevy for that date
            skipped_sessions += 1
            continue

        for r in rows_to_insert:
            conn.execute(
                """INSERT INTO workout_sets
                   (date, workout_name, duration_s, exercise, set_type, weight_kg, reps, rpe, source)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (r["date"], r["workout_name"], r["duration_s"], r["exercise"],
                 r["set_type"], r["weight_kg"], r["reps"], r["rpe"], "hevy"),
            )
            inserted += 1

        conn.commit()

        if progress_cb and i % 10 == 0:
            progress_cb(i, total_sessions)

    conn.close()

    return {
        "inserted": inserted,
        "skipped_sessions": skipped_sessions,
        "total_sessions": total_sessions,
        "total_rows_in_file": sum(len(s["rows"]) for s in sessions.values()),
    }


if __name__ == "__main__":
    import json

    hevy_path = (
        Path.home()
        / "Library"
        / "Mobile Documents"
        / "iCloud~com~ifunography~HealthExport"
        / "Documents"
        / "hevy_workout_data.csv"
    )

    def prog(i, total):
        print(f"  {i}/{total} sessions processed...")

    result = parse_hevy_csv(hevy_path, progress_cb=prog)
    print(json.dumps(result, indent=2))
