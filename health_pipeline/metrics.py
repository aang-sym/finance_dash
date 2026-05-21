"""
Pre-aggregated health metric queries for the API layer.
All functions return plain dicts/lists suitable for jsonify().
"""
import sqlite3
from datetime import date, timedelta
from typing import Optional
from health_pipeline.db import get_conn


def _get_config(conn: sqlite3.Connection, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM health_config WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


# ── HRV ─────────────────────────────────────────────────────────────────────

def hrv_daily(days: int = 30) -> list:
    """Daily median HRV — sleep-window only (22:00–09:00 AEST = 12:00–23:00 UTC)."""
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT DATE(ts) as day,
               ROUND(AVG(qty_ms), 1) as hrv_avg,
               ROUND(MIN(qty_ms), 1) as hrv_min,
               ROUND(MAX(qty_ms), 1) as hrv_max,
               COUNT(*) as sample_count
        FROM hrv_samples
        WHERE ts >= ?
          AND (CAST(strftime('%H', ts) AS INTEGER) >= 12
               OR CAST(strftime('%H', ts) AS INTEGER) <= 9)
        GROUP BY day
        ORDER BY day
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def hrv_baseline(days: int = 30) -> Optional[float]:
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    row = conn.execute(
        "SELECT ROUND(AVG(qty_ms), 1) FROM hrv_samples WHERE ts >= ?", (cutoff,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


# ── Resting HR ───────────────────────────────────────────────────────────────

def resting_hr_daily(days: int = 30) -> list:
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT date, ROUND(qty_bpm, 1) as rhr FROM resting_hr WHERE date >= ? ORDER BY date",
        (cutoff,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resting_hr_baseline(days: int = 30) -> Optional[float]:
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    row = conn.execute(
        "SELECT ROUND(AVG(qty_bpm), 1) FROM resting_hr WHERE date >= ?", (cutoff,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


# ── Sleep ────────────────────────────────────────────────────────────────────

def sleep_daily(days: int = 30) -> list:
    """Per-night sleep summary.
    Uses Apple Watch source when available for a given night, else Sleep Cycle.
    Night attributed to date of sleep session end.
    Stage breakdown only available when Watch or Sleep Cycle provides it.
    """
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    # Get all nights and sources; prefer Apple Watch over Sleep Cycle over AutoSleep
    rows = conn.execute("""
        WITH ranked AS (
            SELECT DATE(end_ts) as night,
                   source,
                   SUM(CASE WHEN stage IN ('Core','Asleep') THEN qty_hrs ELSE 0 END) as core_hrs,
                   SUM(CASE WHEN stage = 'REM' THEN qty_hrs ELSE 0 END) as rem_hrs,
                   SUM(CASE WHEN stage = 'Deep' THEN qty_hrs ELSE 0 END) as deep_hrs,
                   SUM(CASE WHEN stage = 'Awake' THEN qty_hrs ELSE 0 END) as awake_hrs,
                   SUM(CASE WHEN stage = 'InBed' THEN qty_hrs ELSE 0 END) as inbed_hrs,
                   SUM(CASE WHEN stage NOT IN ('InBed','Awake') THEN qty_hrs ELSE 0 END) as total_sleep_hrs,
                   MIN(start_ts) as bedtime,
                   MAX(end_ts) as wake_time,
                   COUNT(CASE WHEN stage = 'Awake' THEN 1 END) as awake_count,
                   CASE
                       WHEN source LIKE '%Watch%' THEN 1
                       WHEN source LIKE '%Sleep Cycle%' THEN 2
                       ELSE 3
                   END as src_rank
            FROM sleep_segments
            WHERE end_ts >= ?
              AND stage NOT IN ('InBed')
            GROUP BY night, source
        ),
        best AS (
            SELECT night, MIN(src_rank) as best_rank
            FROM ranked GROUP BY night
        )
        SELECT r.night, r.core_hrs, r.rem_hrs, r.deep_hrs, r.awake_hrs,
               r.inbed_hrs, r.total_sleep_hrs, r.bedtime, r.wake_time,
               r.awake_count, r.source
        FROM ranked r
        JOIN best b ON r.night = b.night AND r.src_rank = b.best_rank
        ORDER BY r.night
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── SpO2 ─────────────────────────────────────────────────────────────────────

def spo2_daily(days: int = 30) -> list:
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT DATE(ts) as day,
               ROUND(AVG(qty_pct), 1) as avg_spo2,
               ROUND(MIN(qty_pct), 1) as min_spo2
        FROM blood_oxygen
        WHERE ts >= ?
        GROUP BY day ORDER BY day
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Respiratory Rate ─────────────────────────────────────────────────────────

def resp_rate_daily(days: int = 30) -> list:
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT DATE(ts) as day,
               ROUND(AVG(qty_bpm), 1) as avg_resp
        FROM respiratory_rate
        WHERE ts >= ?
        GROUP BY day ORDER BY day
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Steps ────────────────────────────────────────────────────────────────────

def steps_daily(days: int = 30) -> list:
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT DATE(ts) as day,
               ROUND(SUM(qty)) as steps
        FROM step_samples
        WHERE ts >= ?
          AND source LIKE '%Apple%Watch%'
        GROUP BY day ORDER BY day
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── VO2 Max ──────────────────────────────────────────────────────────────────

def vo2_trend(days: int = 90) -> list:
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT date, ROUND(qty, 2) as vo2 FROM vo2_max WHERE date >= ? ORDER BY date",
        (cutoff,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Nutrition daily totals ────────────────────────────────────────────────────

def nutrition_daily(days: int = 30) -> list:
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT date,
               ROUND(SUM(calories)) as calories,
               ROUND(SUM(protein_g), 1) as protein_g,
               ROUND(SUM(carbs_g), 1) as carbs_g,
               ROUND(SUM(fat_g), 1) as fat_g,
               ROUND(SUM(fiber_g), 1) as fiber_g,
               ROUND(SUM(sodium_mg)) as sodium_mg,
               ROUND(SUM(potassium_mg)) as potassium_mg,
               ROUND(SUM(caffeine_mg)) as caffeine_mg,
               ROUND(SUM(magnesium_mg)) as magnesium_mg,
               ROUND(SUM(calcium_mg)) as calcium_mg,
               ROUND(SUM(vitamin_d_mcg), 1) as vitamin_d_mcg
        FROM nutrition_log
        WHERE date >= ?
        GROUP BY date ORDER BY date
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Strength workouts ─────────────────────────────────────────────────────────

def workout_sessions(days: int = 30) -> list:
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    sessions = conn.execute("""
        SELECT date, workout_name,
               MAX(duration_s) as duration_s,
               COUNT(DISTINCT exercise) as exercise_count,
               SUM(CASE WHEN set_type = 'Standard Set' THEN 1 ELSE 0 END) as working_sets
        FROM workout_sets
        WHERE date >= ?
        GROUP BY date, workout_name
        ORDER BY date DESC
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in sessions]


# ── Import status ─────────────────────────────────────────────────────────────

def import_status() -> list:
    conn = get_conn()
    rows = conn.execute("""
        SELECT source, MAX(imported_at) as last_import, SUM(record_count) as total_records,
               MIN(date_from) as date_from, MAX(date_to) as date_to, filename
        FROM import_log
        GROUP BY source
        ORDER BY last_import DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_config() -> dict:
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM health_config").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


def set_config(key: str, value: str) -> None:
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO health_config(key, value) VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()
