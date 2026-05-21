import csv
from pathlib import Path
from typing import Optional
from health_pipeline.db import get_conn, init_db

ICLOUD_MF_DIR = Path(
    "/Users/anguss/Library/Mobile Documents/com~apple~CloudDocs/MacroFactor"
)
NUTRITION_PATH = ICLOUD_MF_DIR / "nutrition.csv"
WORKOUTS_PATH = ICLOUD_MF_DIR / "workouts.csv"


def _f(v: str) -> Optional[float]:
    try:
        s = (v or "").strip()
        return float(s) if s else None
    except (TypeError, ValueError):
        return None


def _date_key(fieldnames: list) -> str:
    """Return the actual Date field name, handling BOM and quotes."""
    for name in (fieldnames or []):
        if name.replace('﻿', '').strip('"') == 'Date':
            return name
    return 'Date'


def import_nutrition(path: Path = NUTRITION_PATH) -> int:
    """Parse MacroFactor nutrition CSV and upsert into nutrition_log.
    Delete existing rows for dates in the file, then re-insert.
    """
    init_db()
    conn = get_conn()

    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        date_key = _date_key(reader.fieldnames)
        for row in reader:
            date = (row.get(date_key) or row.get("Date") or "").strip().strip('"')
            if not date:
                continue
            row["_date"] = date
            rows.append(row)

    if not rows:
        conn.close()
        return 0

    dates_in_file = {r["_date"] for r in rows}
    placeholders = ",".join("?" * len(dates_in_file))
    conn.execute(f"DELETE FROM nutrition_log WHERE date IN ({placeholders})", list(dates_in_file))

    inserted = 0
    for row in rows:
        conn.execute(
            """INSERT INTO nutrition_log
               (date, time, food_name, serving_weight_g, calories, fat_g, carbs_g, protein_g,
                alcohol_g, caffeine_mg, fiber_g, sodium_mg, potassium_mg, magnesium_mg,
                calcium_mg, iron_mg, vitamin_d_mcg, zinc_mg)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["_date"],
                row.get("Time", "").strip(),
                row.get("Food Name", "").strip(),
                _f(row.get("Serving Weight (g)")),
                _f(row.get("Calories (kcal)")),
                _f(row.get("Fat (g)")),
                _f(row.get("Carbs (g)")),
                _f(row.get("Protein (g)")),
                _f(row.get("Alcohol (g)")),
                _f(row.get("Caffeine (mg)")),
                _f(row.get("Fiber (g)")),
                _f(row.get("Sodium (mg)")),
                _f(row.get("Potassium (mg)")),
                _f(row.get("Magnesium (mg)")),
                _f(row.get("Calcium (mg)")),
                _f(row.get("Iron (mg)")),
                _f(row.get("Vitamin D (mcg)")),
                _f(row.get("Zinc (mg)")),
            )
        )
        inserted += 1

    conn.execute(
        "INSERT INTO import_log(source, imported_at, record_count, date_from, date_to, filename) "
        "VALUES (?,datetime('now'),?,?,?,?)",
        ("macrofactor_nutrition", inserted, min(dates_in_file), max(dates_in_file), path.name)
    )
    conn.commit()
    conn.close()
    return inserted


def import_workouts(path: Path = WORKOUTS_PATH) -> int:
    """Parse MacroFactor workouts CSV (one row per set) into workout_sets."""
    init_db()
    conn = get_conn()

    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        date_key = _date_key(reader.fieldnames)
        for row in reader:
            date = (row.get(date_key) or row.get("Date") or "").strip().strip('"')
            if not date:
                continue
            row["_date"] = date
            rows.append(row)

    if not rows:
        conn.close()
        return 0

    dates_in_file = {r["_date"] for r in rows}
    placeholders = ",".join("?" * len(dates_in_file))
    conn.execute(f"DELETE FROM workout_sets WHERE date IN ({placeholders})", list(dates_in_file))

    inserted = 0
    for row in rows:
        exercise = (row.get("Exercise") or "").strip()
        if " ∈ " in exercise:
            exercise = exercise.split(" ∈ ")[0].strip()

        conn.execute(
            """INSERT INTO workout_sets
               (date, workout_name, duration_s, exercise, base_weight_kg,
                set_type, weight_kg, reps, rir)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                row["_date"],
                row.get("Workout", "").strip(),
                _f(row.get("Workout Duration")),
                exercise,
                _f(row.get("Exercise Base Weight (kg)")),
                row.get("Set Type", "").strip(),
                _f(row.get("Weight (kg)")),
                _f(row.get("Reps")),
                _f(row.get("RIR")),
            )
        )
        inserted += 1

    conn.execute(
        "INSERT INTO import_log(source, imported_at, record_count, date_from, date_to, filename) VALUES (?,datetime('now'),?,?,?,?)",
        ("macrofactor_workouts", inserted, min(dates_in_file), max(dates_in_file), path.name)
    )
    conn.commit()
    conn.close()
    return inserted
