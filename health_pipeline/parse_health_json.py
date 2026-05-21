import ijson
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from health_pipeline.db import get_conn, init_db

ICLOUD_HEALTH_DIR = Path(
    "/Users/anguss/Library/Mobile Documents/iCloud~com~ifunography~HealthExport/Documents"
)

METRIC_INSERTERS: dict = {}  # populated below


def latest_health_json() -> Optional[Path]:
    if not ICLOUD_HEALTH_DIR.exists():
        return None
    jsons = sorted(ICLOUD_HEALTH_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return jsons[0] if jsons else None


def _norm_ts(s: str) -> str:
    try:
        from dateutil import parser as dp
        return dp.parse(s).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return s


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _insert_hrv(conn: sqlite3.Connection, sample: dict) -> None:
    ts = _norm_ts(sample.get("date") or sample.get("start", ""))
    qty = _f(sample.get("qty"))
    if not ts or qty is None:
        return
    conn.execute(
        "INSERT OR IGNORE INTO hrv_samples(ts, qty_ms, source) VALUES (?,?,?)",
        (ts, qty, sample.get("source"))
    )


def _insert_resting_hr(conn: sqlite3.Connection, sample: dict) -> None:
    ts = _norm_ts(sample.get("date", ""))
    qty = _f(sample.get("qty"))
    if not ts or qty is None:
        return
    date = ts[:10]
    conn.execute(
        "INSERT OR REPLACE INTO resting_hr(date, qty_bpm, source) VALUES (?,?,?)",
        (date, qty, sample.get("source"))
    )


def _insert_heart_rate(conn: sqlite3.Connection, sample: dict) -> None:
    ts = _norm_ts(sample.get("date") or sample.get("start", ""))
    if not ts:
        return
    conn.execute(
        "INSERT INTO heart_rate_samples(ts, min_bpm, avg_bpm, max_bpm, context, source) VALUES (?,?,?,?,?,?)",
        (ts, _f(sample.get("Min")), _f(sample.get("Avg")), _f(sample.get("Max")),
         sample.get("context"), sample.get("source"))
    )


SLEEP_STAGE_MAP = {
    "in bed": "InBed", "asleep": "Asleep", "core": "Core",
    "rem": "REM", "deep": "Deep", "awake": "Awake",
    "inbed": "InBed", "asleepcore": "Core", "asleeprem": "REM",
    "asleepdeep": "Deep",
}


def _insert_sleep(conn: sqlite3.Connection, sample: dict) -> None:
    start = _norm_ts(sample.get("startDate") or sample.get("start", ""))
    end = _norm_ts(sample.get("endDate") or sample.get("end", ""))
    raw_stage = (sample.get("value") or "").strip()
    stage = SLEEP_STAGE_MAP.get(raw_stage.lower(), raw_stage)
    if not start or not end or not stage:
        return
    conn.execute(
        "INSERT INTO sleep_segments(start_ts, end_ts, stage, source, qty_hrs) VALUES (?,?,?,?,?)",
        (start, end, stage, sample.get("source"), _f(sample.get("qty")))
    )


def _insert_simple(conn: sqlite3.Connection, table: str, col: str, sample: dict) -> None:
    ts = _norm_ts(sample.get("date") or sample.get("start", ""))
    qty = _f(sample.get("qty"))
    if not ts or qty is None:
        return
    conn.execute(
        f"INSERT INTO {table}(ts, {col}, source) VALUES (?,?,?)",
        (ts, qty, sample.get("source"))
    )


def _insert_vo2(conn: sqlite3.Connection, sample: dict) -> None:
    ts = _norm_ts(sample.get("date", ""))
    qty = _f(sample.get("qty"))
    if not ts or qty is None:
        return
    conn.execute(
        "INSERT INTO vo2_max(date, qty, source) VALUES (?,?,?)",
        (ts[:10], qty, sample.get("source"))
    )


METRIC_INSERTERS = {
    "heart_rate_variability": _insert_hrv,
    "resting_heart_rate": _insert_resting_hr,
    "heart_rate": _insert_heart_rate,
    "sleep_analysis": _insert_sleep,
    "respiratory_rate": lambda c, s: _insert_simple(c, "respiratory_rate", "qty_bpm", s),
    "blood_oxygen_saturation": lambda c, s: _insert_simple(c, "blood_oxygen", "qty_pct", s),
    "vo2_max": _insert_vo2,
    "step_count": lambda c, s: _insert_simple(c, "step_samples", "qty", s),
    "active_energy": lambda c, s: _insert_simple(c, "active_energy", "qty_kcal", s),
}


def _insert_workout(conn: sqlite3.Connection, w: dict) -> Optional[int]:
    ext_id = w.get("id")
    name = w.get("name", "")
    start = _norm_ts(w.get("start", ""))
    end = _norm_ts(w.get("end", ""))
    if not start or not end:
        return None
    duration = _f(w.get("duration"))
    avg_hr = _f((w.get("heartRate") or {}).get("avg", {}).get("qty")) or _f((w.get("avgHeartRate") or {}).get("qty"))
    max_hr = _f((w.get("heartRate") or {}).get("max", {}).get("qty")) or _f((w.get("maxHeartRate") or {}).get("qty"))
    active_kcal = _f((w.get("activeEnergyBurned") or {}).get("qty"))
    distance_km = _f((w.get("distance") or {}).get("qty"))
    location = w.get("location")
    is_indoor = 1 if w.get("isIndoor") else 0
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO workouts
               (external_id, name, start_ts, end_ts, duration_s, avg_hr, max_hr,
                active_kcal, distance_km, location, is_indoor)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (ext_id, name, start, end, duration, avg_hr, max_hr,
             active_kcal, distance_km, location, is_indoor)
        )
        return cur.lastrowid if cur.rowcount > 0 else None
    except sqlite3.IntegrityError:
        return None


def parse_and_import(path: Path, progress_cb=None) -> dict:
    """Stream-parse a Health Auto Export JSON file into the SQLite DB.
    Returns counts dict: {metric_name: record_count, 'workouts': count}
    progress_cb(pct: float | None, msg: str) called periodically if provided.

    Uses ijson.items per-metric to handle JSON objects where 'name' appears
    after 'data' (e.g. sleep_analysis) — a single forward pass over all metrics.
    """
    init_db()
    conn = get_conn()
    counts: dict = {}

    # --- Pass 1: all metrics via ijson.items (handles any key ordering) ---
    with open(path, "rb") as f:
        for metric in ijson.items(f, "data.metrics.item", use_float=True):
            metric_name = metric.get("name", "")
            inserter = METRIC_INSERTERS.get(metric_name)
            if not inserter:
                continue
            data = metric.get("data") or []
            metric_count = 0
            for sample in data:
                inserter(conn, sample)
                metric_count += 1
                if metric_count % 10000 == 0:
                    conn.commit()
                    if progress_cb:
                        progress_cb(None, f"Parsing {metric_name}: {metric_count:,} records")
            counts[metric_name] = metric_count
            conn.commit()
            if progress_cb:
                progress_cb(None, f"Imported {metric_name}: {metric_count:,} records")

    if progress_cb:
        progress_cb(50, "Parsing workouts...")

    # --- Pass 2: workouts ---
    workout_count = 0
    with open(path, "rb") as f:
        for w in ijson.items(f, "data.workouts.item", use_float=True):
            workout_id = _insert_workout(conn, w)
            if workout_id:
                for hr in (w.get("heartRateData") or []):
                    ts = _norm_ts(hr.get("date", ""))
                    if ts:
                        conn.execute(
                            "INSERT INTO workout_hr(workout_id, ts, min_bpm, avg_bpm, max_bpm) VALUES (?,?,?,?,?)",
                            (workout_id, ts, _f(hr.get("Min")), _f(hr.get("Avg")), _f(hr.get("Max")))
                        )
                for hr in (w.get("heartRateRecovery") or []):
                    ts = _norm_ts(hr.get("date", ""))
                    avg = _f(hr.get("Avg"))
                    if ts and avg:
                        conn.execute(
                            "INSERT INTO workout_hr_recovery(workout_id, ts, hr_bpm) VALUES (?,?,?)",
                            (workout_id, ts, avg)
                        )
            workout_count += 1
            if workout_count % 100 == 0:
                conn.commit()

    conn.commit()
    counts["workouts"] = workout_count

    # Record import in log
    all_dates = []
    for tbl, col in [("hrv_samples", "ts"), ("resting_hr", "date"), ("sleep_segments", "start_ts")]:
        rows = conn.execute(f"SELECT MIN({col}), MAX({col}) FROM {tbl}").fetchone()
        if rows and rows[0]:
            all_dates += [rows[0], rows[1]]
    date_from = min(all_dates)[:10] if all_dates else None
    date_to = max(all_dates)[:10] if all_dates else None

    conn.execute(
        "INSERT INTO import_log(source, imported_at, record_count, date_from, date_to, filename) VALUES (?,datetime('now'),?,?,?,?)",
        ("apple_health", sum(v for v in counts.values() if isinstance(v, int)), date_from, date_to, path.name)
    )
    conn.commit()
    conn.close()

    if progress_cb:
        progress_cb(100, "Apple Health import complete")

    return counts
