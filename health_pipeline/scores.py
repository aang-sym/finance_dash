"""
Score computation for the health vitals section.
All scores use 60-day rolling personal baselines (Bevel methodology).
Sigmoid: 100 / (1 + exp(-1.5 * z))
"""
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from itertools import takewhile
from typing import Optional

from health_pipeline.db import get_conn
from health_pipeline.metrics import (
    hrv_daily, resting_hr_daily, sleep_daily,
    nutrition_daily, workout_sessions, get_config,
)


def _sigmoid(z: float) -> float:
    return 100.0 / (1.0 + math.exp(-1.5 * z))


def _baseline(values: list) -> tuple:
    """Return (mean, std) of values, or (None, None) if <14 samples."""
    vals = [v for v in values if v is not None]
    if len(vals) < 14:
        return None, None
    mean = sum(vals) / len(vals)
    variance = sum((v - mean) ** 2 for v in vals) / len(vals)
    std = math.sqrt(variance) if variance > 0 else 1.0
    return mean, std


def _hrv_60d():
    rows = hrv_daily(60)
    vals = [r["hrv_avg"] for r in rows]
    mean, std = _baseline(vals)
    return rows, mean, std


def _rhr_60d():
    rows = resting_hr_daily(60)
    vals = [r["rhr"] for r in rows]
    mean, std = _baseline(vals)
    return rows, mean, std


def recovery_score() -> dict:
    hrv_rows, hrv_mean, hrv_std = _hrv_60d()
    rhr_rows, rhr_mean, rhr_std = _rhr_60d()
    sleep_rows = sleep_daily(2)

    calibrating = hrv_mean is None
    score = None
    components = {}

    if not calibrating and hrv_rows and rhr_rows:
        today_hrv = hrv_rows[-1]["hrv_avg"] if hrv_rows else None
        today_rhr = rhr_rows[-1]["rhr"] if rhr_rows else None
        last_sleep = sleep_rows[-1] if sleep_rows else None
        sleep_hrs = (last_sleep["total_sleep_hrs"] or 0) if last_sleep else 0

        hrv_z = (today_hrv - hrv_mean) / (hrv_std or 1) if today_hrv else 0
        rhr_z = (rhr_mean - today_rhr) / (rhr_std or 1) if today_rhr else 0
        sleep_pf = min(sleep_hrs / 8.0, 1.0)

        score = max(0.0, min(100.0,
            0.65 * _sigmoid(hrv_z) +
            0.20 * _sigmoid(rhr_z) +
            0.15 * sleep_pf * 100
        ))
        components = {
            "hrv_ms": today_hrv,
            "hrv_z": round(hrv_z, 2),
            "rhr_bpm": today_rhr,
            "rhr_z": round(rhr_z, 2),
            "sleep_hrs": round(sleep_hrs, 2),
            "sleep_pf": round(sleep_pf, 2),
        }

    zone = "green" if (score or 0) >= 67 else ("red" if (score or 50) <= 33 else "yellow")
    return {
        "score": round(score, 1) if score is not None else None,
        "calibrating": calibrating,
        "zone": zone,
        "components": components,
        "hrv_baseline_mean": round(hrv_mean, 1) if hrv_mean else None,
        "rhr_baseline_mean": round(rhr_mean, 1) if rhr_mean else None,
    }


def sleep_score() -> dict:
    rows = sleep_daily(30)
    if not rows:
        return {"score": None, "calibrating": True, "zone": "red", "last_night": None, "components": {}}

    last = rows[-1]
    total = last["total_sleep_hrs"] or 0
    rem = last["rem_hrs"] or 0
    deep = last["deep_hrs"] or 0
    awake_count = last["awake_count"] or 0

    # Bedtime consistency vs 7-day mean
    bedtimes = []
    for r in rows[-7:]:
        if r.get("bedtime"):
            try:
                dt = datetime.fromisoformat(r["bedtime"])
                mins = dt.hour * 60 + dt.minute
                if mins < 6 * 60:
                    mins += 24 * 60  # treat early-AM as continuation of previous evening
                bedtimes.append(mins)
            except Exception:
                pass

    if len(bedtimes) >= 2:
        mean_bt = sum(bedtimes) / len(bedtimes)
        deviation_mins = abs(bedtimes[-1] - mean_bt)
    else:
        deviation_mins = 0

    dur_score = min(total / 8.0, 1.0) * 100
    stage_ratio = (rem + deep) / total if total > 0 else 0
    stage_score = min(stage_ratio / 0.50, 1.0) * 100
    cont_score = max(0.0, 100 - awake_count * 10)
    cons_score = max(0.0, 100 - deviation_mins / 60 * 20)

    score = (0.40 * dur_score + 0.30 * stage_score +
             0.20 * cont_score + 0.10 * cons_score)
    zone = "green" if score >= 67 else ("red" if score <= 33 else "yellow")

    return {
        "score": round(score, 1),
        "calibrating": False,
        "zone": zone,
        "last_night": {
            "total_hrs": round(total, 2),
            "rem_hrs": round(rem, 2),
            "deep_hrs": round(deep, 2),
            "core_hrs": round(last["core_hrs"] or 0, 2),
            "awake_hrs": round(last["awake_hrs"] or 0, 2),
            "awake_count": awake_count,
            "bedtime": last["bedtime"],
            "wake_time": last["wake_time"],
            "source": last["source"],
        },
        "components": {
            "duration": round(dur_score, 1),
            "stage": round(stage_score, 1),
            "continuity": round(cont_score, 1),
            "consistency": round(cons_score, 1),
        },
    }


def _hr_max() -> int:
    cfg = get_config()
    return int(cfg.get("hr_max", 170))


def _zone_multiplier(bpm: float, hr_max: int) -> int:
    pct = bpm / hr_max
    if pct < 0.57:
        return 1
    elif pct < 0.63:
        return 2
    elif pct < 0.75:
        return 3
    elif pct < 0.87:
        return 4
    else:
        return 5


def _edwards_trimp_for_workout(workout_id: int, conn) -> float:
    hr_max = _hr_max()
    rows = conn.execute(
        "SELECT qty_bpm FROM workout_hr WHERE workout_id=? ORDER BY ts",
        (workout_id,)
    ).fetchall()
    return sum(_zone_multiplier(r[0], hr_max) for r in rows)


def _trimp_from_avg_hr(avg_hr: float, duration_s: float) -> float:
    hr_max = _hr_max()
    duration_min = (duration_s or 0) / 60.0
    mult = _zone_multiplier(avg_hr, hr_max)
    return duration_min * mult


def strain_score(days: int = 1) -> dict:
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    workouts = conn.execute(
        "SELECT id, name, start_ts, duration_s, avg_hr FROM workouts "
        "WHERE DATE(start_ts) >= ? ORDER BY start_ts",
        (cutoff,)
    ).fetchall()

    total_trimp = 0.0
    workout_list = []
    for w in workouts:
        wid = w["id"]
        hr_count = conn.execute(
            "SELECT COUNT(*) FROM workout_hr WHERE workout_id=?", (wid,)
        ).fetchone()[0]
        if hr_count > 0:
            trimp = _edwards_trimp_for_workout(wid, conn)
            used_per_min = True
        elif w["avg_hr"]:
            trimp = _trimp_from_avg_hr(w["avg_hr"], w["duration_s"])
            used_per_min = False
        else:
            trimp = 0.0
            used_per_min = False
        strain = round(min(21.0, 3.0 * math.log1p(trimp) + 0.5), 1) if trimp > 0 else 0.0
        total_trimp += trimp
        workout_list.append({
            "name": w["name"],
            "start_ts": w["start_ts"],
            "duration_min": round((w["duration_s"] or 0) / 60),
            "trimp": round(trimp, 1),
            "strain": strain,
            "used_per_minute": used_per_min,
        })
    conn.close()

    daily_strain = round(min(21.0, 3.0 * math.log1p(total_trimp) + 0.5), 1) if total_trimp > 0 else 0.0
    zone = "green" if daily_strain <= 7 else ("red" if daily_strain >= 14 else "yellow")
    return {
        "score": daily_strain,
        "calibrating": False,
        "zone": zone,
        "trimp": round(total_trimp, 1),
        "workouts": workout_list,
        "hr_max": _hr_max(),
    }


def stress_score() -> dict:
    """Stress from daytime HRV suppression vs sleep-window HRV baseline."""
    conn = get_conn()
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    # Sleep HRV: UTC 12–23 (AEST 22–09)
    sleep_row = conn.execute("""
        SELECT AVG(qty_ms) as avg, COUNT(*) as cnt FROM hrv_samples
        WHERE DATE(ts) IN (?, ?)
          AND (CAST(strftime('%H', ts) AS INTEGER) >= 12
               OR CAST(strftime('%H', ts) AS INTEGER) <= 9)
    """, (today, yesterday)).fetchone()

    # Daytime HRV: UTC 23–11 (AEST 09–21) — approximate via inverse filter
    daytime_row = conn.execute("""
        SELECT AVG(qty_ms) as avg, COUNT(*) as cnt FROM hrv_samples
        WHERE DATE(ts) IN (?, ?)
          AND CAST(strftime('%H', ts) AS INTEGER) BETWEEN 10 AND 21
    """, (today, yesterday)).fetchone()

    conn.close()

    sleep_hrv = sleep_row["avg"] if sleep_row else None
    daytime_hrv = daytime_row["avg"] if daytime_row else None
    daytime_cnt = daytime_row["cnt"] if daytime_row else 0

    if not sleep_hrv or not daytime_hrv or daytime_cnt < 3:
        return {
            "score": None,
            "calibrating": True,
            "zone": "yellow",
            "insufficient_data": True,
        }

    suppression = (sleep_hrv - daytime_hrv) / sleep_hrv
    score = max(1.0, min(100.0, 50 + suppression * 40))
    zone = "green" if score <= 33 else ("red" if score >= 67 else "yellow")
    return {
        "score": round(score, 1),
        "calibrating": False,
        "zone": zone,
        "sleep_hrv_mean": round(sleep_hrv, 1),
        "daytime_hrv_mean": round(daytime_hrv, 1),
        "suppression": round(suppression, 3),
        "insufficient_data": False,
    }


def energy_bank(recovery: dict, strain: dict, stress: dict) -> dict:
    rec = recovery["score"] if recovery["score"] is not None else 50.0
    str_score = strain["score"] or 0.0
    sts_score = stress["score"] if stress["score"] is not None else 50.0
    drain_strain = (str_score / 21) * 40
    drain_stress = (sts_score / 100) * 20
    bank = max(0.0, min(100.0, rec - drain_strain - drain_stress))
    zone = "green" if bank >= 67 else ("red" if bank <= 33 else "yellow")
    return {
        "score": round(bank, 1),
        "calibrating": recovery["calibrating"],
        "zone": zone,
        "morning_charge": round(rec, 1),
        "strain_drain": round(drain_strain, 1),
        "stress_drain": round(drain_stress, 1),
    }


def compute_scores() -> dict:
    rec = recovery_score()
    slp = sleep_score()
    str_ = strain_score(days=1)
    sts = stress_score()
    enrg = energy_bank(rec, str_, sts)

    nutr = nutrition_daily(1)
    nutr_today = nutr[-1] if nutr else None
    wkts = workout_sessions(1)

    return {
        "scores": {
            "recovery": rec,
            "sleep": slp,
            "strain": str_,
            "stress": sts,
            "energy_bank": enrg,
        },
        "nutrition_today": nutr_today,
        "workouts_today": wkts,
    }


def scores_history(days: int = 30) -> list:
    """Daily score history for trend charts."""
    hrv_rows = hrv_daily(days + 60)
    rhr_rows = resting_hr_daily(days + 60)
    sleep_rows = sleep_daily(days)

    hrv_by_day = {r["day"]: r["hrv_avg"] for r in hrv_rows}
    rhr_by_day = {r["date"]: r["rhr"] for r in rhr_rows}
    sleep_by_day = {r["night"]: r for r in sleep_rows}

    today = date.today()
    result = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        baseline_cutoff = (today - timedelta(days=i + 60)).isoformat()

        hrv_vals = [v for k, v in hrv_by_day.items() if baseline_cutoff <= k < d and v]
        rhr_vals = [v for k, v in rhr_by_day.items() if baseline_cutoff <= k < d and v]
        hrv_mean, hrv_std = _baseline(hrv_vals)
        rhr_mean, rhr_std = _baseline(rhr_vals)

        today_hrv = hrv_by_day.get(d)
        today_rhr = rhr_by_day.get(d)
        sleep = sleep_by_day.get(d)

        rec = None
        if hrv_mean and today_hrv and today_rhr:
            hrv_z = (today_hrv - hrv_mean) / (hrv_std or 1)
            rhr_z = (rhr_mean - today_rhr) / (rhr_std or 1)
            sleep_hrs = (sleep["total_sleep_hrs"] or 0) if sleep else 0
            sleep_pf = min(sleep_hrs / 8.0, 1.0)
            rec = round(max(0.0, min(100.0,
                0.65 * _sigmoid(hrv_z) +
                0.20 * _sigmoid(rhr_z) +
                0.15 * sleep_pf * 100
            )), 1)

        slp = None
        if sleep:
            total = sleep["total_sleep_hrs"] or 0
            rem = sleep["rem_hrs"] or 0
            deep = sleep["deep_hrs"] or 0
            stage_ratio = (rem + deep) / total if total > 0 else 0
            slp = round(
                0.40 * min(total / 8.0, 1.0) * 100 +
                0.30 * min(stage_ratio / 0.50, 1.0) * 100 +
                0.20 * max(0.0, 100 - (sleep["awake_count"] or 0) * 10),
                1
            )

        result.append({"date": d, "recovery": rec, "sleep": slp})

    return result


def strain_workouts_detail(days: int = 30) -> list:
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    hr_max = _hr_max()
    workouts = conn.execute(
        "SELECT id, name, start_ts, duration_s, avg_hr FROM workouts "
        "WHERE DATE(start_ts) >= ? ORDER BY start_ts DESC",
        (cutoff,)
    ).fetchall()

    result = []
    for w in workouts:
        wid = w["id"]
        hr_rows = conn.execute(
            "SELECT qty_bpm FROM workout_hr WHERE workout_id=? ORDER BY ts",
            (wid,)
        ).fetchall()

        zone_mins = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        if hr_rows:
            for (bpm,) in hr_rows:
                z = _zone_multiplier(bpm, hr_max)
                zone_mins[z] += 1
            trimp = sum(zone_mins[z] * z for z in range(1, 6))
        elif w["avg_hr"]:
            trimp = _trimp_from_avg_hr(w["avg_hr"], w["duration_s"])
            zone_mins = {}
        else:
            trimp = 0.0
            zone_mins = {}

        strain = round(min(21.0, 3.0 * math.log1p(trimp) + 0.5), 1) if trimp > 0 else 0.0
        result.append({
            "name": w["name"],
            "start_ts": w["start_ts"],
            "duration_min": round((w["duration_s"] or 0) / 60),
            "trimp": round(trimp, 1),
            "strain": strain,
            "zone_mins": zone_mins,
        })

    conn.close()
    return result


def strength_exercises() -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT exercise FROM workout_sets WHERE exercise IS NOT NULL ORDER BY exercise"
    ).fetchall()
    conn.close()
    return [r["exercise"] for r in rows]


def strength_progression(exercise: str, days: int = 90) -> list:
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT date,
               ROUND(MAX(weight_kg * (1 + reps / 30.0)), 1) as est_1rm,
               MAX(weight_kg) as max_weight,
               MAX(reps) as max_reps
        FROM workout_sets
        WHERE exercise = ? AND date >= ? AND weight_kg > 0 AND reps > 0
        GROUP BY date ORDER BY date
    """, (exercise, cutoff)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# Exercise → primary muscle groups (working sets count once per listed muscle)
HYPERTROPHY = {
    "chest":        {"min": 8,  "target": 12, "max": 20},
    "back":         {"min": 10, "target": 14, "max": 22},
    "quads":        {"min": 8,  "target": 12, "max": 20},
    "hamstrings":   {"min": 6,  "target": 10, "max": 16},
    "glutes":       {"min": 6,  "target": 10, "max": 16},
    "front delts":  {"min": 0,  "target": 6,  "max": 12},
    "side delts":   {"min": 6,  "target": 12, "max": 20},
    "rear delts":   {"min": 6,  "target": 12, "max": 20},
    "triceps":      {"min": 6,  "target": 10, "max": 18},
    "biceps":       {"min": 6,  "target": 10, "max": 18},
    "abs":          {"min": 0,  "target": 8,  "max": 16},
    "traps":        {"min": 0,  "target": 6,  "max": 12},
    "abductors":    {"min": 0,  "target": 6,  "max": 12},
}

MUSCLE_MAP = {
    "45° Incline Barbell Press":           ["chest", "front delts"],
    "Barbell Box Squat":                   ["quads", "glutes"],
    "Barbell Overhead Press":              ["front delts", "triceps"],
    "Barbell Romanian Deadlift":           ["hamstrings", "glutes"],
    "Cable Straight Bar Overhead Triceps Extension": ["triceps"],
    "Chest-Supported Wide Grip T-Bar Row": ["back", "rear delts"],
    "Close Grip Bench Press":              ["triceps", "chest"],
    "Decline Weighted Sit-Up":             ["abs"],
    "Dumbbell Step-Up":                    ["quads", "glutes"],
    "EZ Bar Preacher Curl":                ["biceps"],
    "Incline Dumbbell T-Raise":            ["rear delts", "traps"],
    "Lying Hamstring Curl":                ["hamstrings"],
    "Machine Crunch (With Overhead Handles)": ["abs"],
    "Neutral Close Grip Cable Lat Pulldown": ["back", "biceps"],
    "Neutral Grip Machine Rear Delt Fly":  ["rear delts"],
    "Seated Dumbbell Lateral Raise":       ["side delts"],
    "Seated Machine Hip Abduction":        ["glutes", "abductors"],
    "Single Arm High Cable Lateral Raise": ["side delts"],
    "Single Arm Neutral Grip Cable Triceps Pushdown": ["triceps"],
    "Smith Machine Hip Thrust":            ["glutes", "hamstrings"],
    "Standing Dumbbell Biceps Curl":       ["biceps"],
    "Weighted Glute Ham Developer Back Extension": ["hamstrings", "glutes"],
    "Weighted Sit-Up":                     ["abs"],
    "Wide Grip Cable Row":                 ["back", "rear delts"],
}


def strength_weekly_sets(days: int = 7) -> dict:
    """Working sets per muscle group.
    days=7: current Mon–Sun week (absolute count).
    days>7: rolling window, returns both total and avg_per_week.
    """
    today = date.today()
    if days <= 7:
        # Current week only
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        cutoff = week_start.isoformat()
        end_date = week_end.isoformat()
        num_weeks = 1
    else:
        cutoff = (today - timedelta(days=days)).isoformat()
        end_date = today.isoformat()
        num_weeks = max(1, days // 7)
        week_start = today - timedelta(days=days)
        week_end = today

    conn = get_conn()
    rows = conn.execute("""
        SELECT exercise, COUNT(*) as sets
        FROM workout_sets
        WHERE date >= ? AND date <= ? AND set_type = 'Standard Set'
        GROUP BY exercise
    """, (cutoff, end_date)).fetchall()
    conn.close()

    muscle_sets: dict = {}
    for r in rows:
        ex = r["exercise"]
        sets = r["sets"]
        for muscle in MUSCLE_MAP.get(ex, []):
            muscle_sets[muscle] = muscle_sets.get(muscle, 0) + sets

    # For multi-week periods, compute avg per week
    muscle_avg: dict = {m: round(v / num_weeks, 1) for m, v in muscle_sets.items()}

    return {
        "week_start": week_start.isoformat() if hasattr(week_start, 'isoformat') else str(week_start),
        "week_end": week_end.isoformat() if hasattr(week_end, 'isoformat') else str(week_end),
        "days": days,
        "num_weeks": num_weeks,
        "muscle_sets": muscle_sets,       # total sets in period
        "muscle_avg_per_week": muscle_avg, # avg sets/week
    }


def strength_muscle_detail(muscle: str, days: int = 84) -> dict:
    """Per-week set counts + per-session breakdown for one muscle group."""
    target_exercises = [ex for ex, ms in MUSCLE_MAP.items() if muscle in ms]
    if not target_exercises:
        return {
            "muscle": muscle, "weekly_sets": {}, "sessions": [],
            "streak_mev": 0, "streak_target": 0,
            "best_week": None, "best_week_sets": 0,
            "mev": 6, "target": 10,
        }

    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    placeholders = ",".join("?" * len(target_exercises))
    rows = conn.execute(f"""
        SELECT date, workout_name, exercise,
               SUM(CASE WHEN set_type='Standard Set' THEN 1 ELSE 0 END) as sets,
               ROUND(AVG(CASE WHEN set_type='Standard Set' AND rir IS NOT NULL THEN rir END), 1) as avg_rir
        FROM workout_sets
        WHERE exercise IN ({placeholders}) AND date >= ?
        GROUP BY date, workout_name, exercise
        ORDER BY date DESC
    """, target_exercises + [cutoff]).fetchall()
    conn.close()

    weekly: dict = defaultdict(int)
    session_map: dict = defaultdict(list)
    for r in rows:
        d = date.fromisoformat(r["date"])
        week = (d - timedelta(days=d.weekday())).isoformat()
        weekly[week] += r["sets"]
        session_map[(r["date"], r["workout_name"])].append(
            {"exercise": r["exercise"], "sets": r["sets"], "avg_rir": r["avg_rir"]}
        )

    sessions = [
        {"date": k[0], "workout": k[1], "exercises": v,
         "total_sets": sum(e["sets"] for e in v)}
        for k, v in sorted(session_map.items(), reverse=True)
    ]

    mev = HYPERTROPHY.get(muscle, {}).get("min", 6)
    target_sets = HYPERTROPHY.get(muscle, {}).get("target", 10)
    sorted_weeks = sorted(weekly.keys(), reverse=True)
    streak_mev = sum(1 for _ in takewhile(lambda w: weekly[w] >= mev, sorted_weeks))
    streak_target = sum(1 for _ in takewhile(lambda w: weekly[w] >= target_sets, sorted_weeks))
    best_week = max(weekly, key=lambda w: weekly[w]) if weekly else None

    return {
        "muscle": muscle,
        "mev": mev,
        "target": target_sets,
        "weekly_sets": dict(weekly),
        "sessions": sessions,
        "streak_mev": streak_mev,
        "streak_target": streak_target,
        "best_week": best_week,
        "best_week_sets": weekly.get(best_week, 0) if best_week else 0,
    }


def strength_set_analysis(exercise: str, days: int = 90) -> list:
    """Per-set RPE/RIR data for an exercise. RPE = 10 - RIR."""
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT date, workout_name, set_type, weight_kg, reps, rir,
               CASE WHEN rir IS NOT NULL THEN ROUND(10.0 - rir, 1) END as rpe,
               CASE WHEN set_type = 'Failure Set' THEN 'failure'
                    WHEN rir IS NOT NULL AND rir <= 1 THEN 'near-failure'
                    WHEN rir IS NOT NULL AND rir > 2 THEN 'undertrained'
                    ELSE 'standard' END as intensity_flag
        FROM workout_sets
        WHERE exercise = ? AND date >= ? AND set_type != 'Warm-Up Set'
        ORDER BY date DESC, id
    """, (exercise, cutoff)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def strength_overload_forecast(exercise: str, days: int = 180) -> dict:
    """Linear regression on est_1RM → project +4/8/12 week 1RM."""
    data = strength_progression(exercise, days)
    if len(data) < 4:
        return {"exercise": exercise, "insufficient_data": True, "data": data,
                "slope_kg_per_week": None, "projections": []}

    origin = date.fromisoformat(data[0]["date"])
    xs = [(date.fromisoformat(d["date"]) - origin).days for d in data]
    ys = [d["est_1rm"] for d in data]

    n = len(xs)
    sx = sum(xs); sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sx2 = sum(x * x for x in xs)
    denom = n * sx2 - sx * sx
    slope = (n * sxy - sx * sy) / denom if denom else 0
    intercept = (sy - slope * sx) / n

    today_x = (date.today() - origin).days
    projections = []
    for weeks in [4, 8, 12]:
        future_x = today_x + weeks * 7
        projections.append({
            "weeks": weeks,
            "est_1rm": round(intercept + slope * future_x, 1),
            "date": (date.today() + timedelta(weeks=weeks)).isoformat(),
        })

    return {
        "exercise": exercise,
        "insufficient_data": False,
        "slope_kg_per_week": round(slope * 7, 2),
        "current_est_1rm": round(intercept + slope * today_x, 1),
        "projections": projections,
        "data": data,
    }


def body_measurements_get(days: int = 90) -> list:
    """Return body measurement log entries."""
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM body_measurements WHERE date >= ? ORDER BY date DESC",
        (cutoff,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def body_measurements_add(payload: dict) -> None:
    """Insert a body measurement entry."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO body_measurements
            (date, body_weight_kg, body_fat_pct, chest_cm, waist_cm, hip_cm,
             left_arm_cm, right_arm_cm, left_thigh_cm, right_thigh_cm, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        payload.get("date", date.today().isoformat()),
        payload.get("body_weight_kg"),
        payload.get("body_fat_pct"),
        payload.get("chest_cm"),
        payload.get("waist_cm"),
        payload.get("hip_cm"),
        payload.get("left_arm_cm"),
        payload.get("right_arm_cm"),
        payload.get("left_thigh_cm"),
        payload.get("right_thigh_cm"),
        payload.get("notes"),
    ))
    conn.commit()
    conn.close()


def body_composition_forecast(days_back: int = 90) -> dict:
    """Projects weight and estimates lean mass gain rate.
    Requires ≥2 body_weight_kg entries in body_measurements.
    """
    rows = body_measurements_get(days_back)
    weights = [(r["date"], r["body_weight_kg"]) for r in rows if r["body_weight_kg"]]

    if len(weights) < 2:
        return {
            "insufficient_data": True,
            "message": "Log at least 2 body weight entries to enable projection.",
        }

    # Linear regression on weight over time
    origin = date.fromisoformat(weights[-1][0])  # oldest first
    pairs = [(date.fromisoformat(d) - origin).days for d, _ in reversed(weights)]
    ys = [w for _, w in reversed(weights)]
    xs = pairs

    n = len(xs)
    sx = sum(xs); sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sx2 = sum(x * x for x in xs)
    denom = n * sx2 - sx * sx
    slope = (n * sxy - sx * sy) / denom if denom else 0
    intercept = (sy - slope * sx) / n

    today_x = (date.today() - origin).days
    current_weight = round(intercept + slope * today_x, 1)
    weight_trend_per_week = round(slope * 7, 2)

    projected = [
        {"weeks": w, "weight_kg": round(intercept + slope * (today_x + w * 7), 1),
         "date": (date.today() + timedelta(weeks=w)).isoformat()}
        for w in [4, 8, 12]
    ]

    # Nutrition context
    nutr = nutrition_daily(30)
    avg_protein = sum(r["protein_g"] or 0 for r in nutr) / max(len(nutr), 1)
    avg_kcal = sum(r["calories"] or 0 for r in nutr) / max(len(nutr), 1)

    # Rough lean mass gain estimate
    # Natural rate: ~0.5–1 kg/month in surplus, protein-dependent
    # Estimate: if gaining weight AND protein adequate (≥1.6g/kg), 70% of gain is lean
    # If losing weight, not building muscle (maintenance/cut)
    protein_adequate = avg_protein >= (current_weight * 1.6) if current_weight else False
    lean_ratio = 0.65 if protein_adequate else 0.4
    lean_gain_kg_per_month = round(weight_trend_per_week * 4 * lean_ratio, 2)

    return {
        "insufficient_data": False,
        "current_weight_kg": current_weight,
        "weight_trend_kg_per_week": weight_trend_per_week,
        "avg_protein_g": round(avg_protein, 1),
        "avg_kcal": round(avg_kcal),
        "protein_adequate": protein_adequate,
        "lean_gain_est_kg_per_month": lean_gain_kg_per_month,
        "projected_weights": projected,
        "entries": weights,
    }


# ── Cardio functions ──────────────────────────────────────────────────────────

def cardio_weekly_summary(weeks: int = 12) -> dict:
    """
    Weekly cardio minutes (Zone 2–3 aerobic: 63–75% HR max) for the past N weeks.
    Also returns weekly Zone 4–5 vigorous minutes.
    Target: 150 min/week moderate (WHO/AHA).
    Counts Outdoor Walk + any non-strength workout in aerobic zones.
    """
    conn = get_conn()
    hr_max = _hr_max()
    z2_lo = hr_max * 0.57   # Zone 2 lower (any cardio)
    z3_hi = hr_max * 0.75   # Zone 3 upper (moderate)
    z4_hi = hr_max * 0.87   # Zone 4 upper (vigorous)

    cutoff = (date.today() - timedelta(weeks=weeks)).isoformat()

    workouts = conn.execute("""
        SELECT id, name, start_ts, duration_s, avg_hr
        FROM workouts
        WHERE DATE(start_ts) >= ? AND name != 'Traditional Strength Training'
        ORDER BY start_ts
    """, (cutoff,)).fetchall()

    from collections import defaultdict
    weekly_moderate = defaultdict(float)   # minutes in Z2–3
    weekly_vigorous = defaultdict(float)   # minutes in Z4–5
    weekly_sessions = defaultdict(list)

    for w in workouts:
        d = date.fromisoformat(w["start_ts"][:10])
        week_start = (d - timedelta(days=d.weekday())).isoformat()
        dur_min = (w["duration_s"] or 0) / 60.0
        avg = w["avg_hr"]
        if not avg or avg < z2_lo:
            continue
        if avg <= z3_hi:
            weekly_moderate[week_start] += dur_min
        elif avg <= z4_hi:
            weekly_vigorous[week_start] += dur_min
            weekly_moderate[week_start] += dur_min  # vigorous also counts toward 150
        else:
            weekly_vigorous[week_start] += dur_min
            weekly_moderate[week_start] += dur_min

        weekly_sessions[week_start].append({
            "name": w["name"],
            "date": d.isoformat(),
            "dur_min": round(dur_min),
            "avg_hr": round(avg) if avg else None,
        })

    conn.close()

    # Build ordered week list
    today = date.today()
    result = []
    for i in range(weeks - 1, -1, -1):
        wk = today - timedelta(days=today.weekday()) - timedelta(weeks=i)
        wk_iso = wk.isoformat()
        mod = round(weekly_moderate.get(wk_iso, 0))
        vig = round(weekly_vigorous.get(wk_iso, 0))
        result.append({
            "week": wk_iso,
            "moderate_min": mod,
            "vigorous_min": vig,
            "target_min": 150,
            "on_target": mod >= 150,
            "pct": round(min(mod / 150 * 100, 150)),
            "sessions": weekly_sessions.get(wk_iso, []),
        })

    # Current week stats
    this_week = result[-1] if result else {}
    # Rolling 4-week average
    last4 = result[-4:] if len(result) >= 4 else result
    avg4 = round(sum(w["moderate_min"] for w in last4) / max(len(last4), 1))
    on_target_streak = 0
    for w in reversed(result):
        if w["on_target"]:
            on_target_streak += 1
        else:
            break

    # Suggestion for this week
    done = this_week.get("moderate_min", 0)
    remaining = max(0, 150 - done)
    if remaining == 0:
        suggestion = "Target hit this week ✓"
    elif remaining <= 30:
        suggestion = f"{remaining} min remaining — one walk closes it"
    elif remaining <= 90:
        suggestion = f"{remaining} min remaining — 2–3 walks of 20–30 min"
    else:
        suggestion = f"{remaining} min remaining — aim for 3 × 30 min walks this week"

    return {
        "weeks": result,
        "this_week_moderate_min": done,
        "avg_4w_min": avg4,
        "on_target_streak": on_target_streak,
        "suggestion": suggestion,
        "target_min": 150,
    }


def cardio_rhr_trend(days: int = 90) -> dict:
    """RHR trend with goal line and projected time-to-goal."""
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT date, qty_bpm FROM resting_hr WHERE date >= ? ORDER BY date",
        (cutoff,)
    ).fetchall()
    conn.close()

    if not rows:
        return {"data": [], "trend_bpm_per_week": None, "current": None,
                "goal": 65, "weeks_to_goal": None}

    data = [{"date": r["date"], "rhr": r["qty_bpm"]} for r in rows]
    current = data[-1]["rhr"]

    # Linear regression for trend
    origin = date.fromisoformat(data[0]["date"])
    xs = [(date.fromisoformat(d["date"]) - origin).days for d in data]
    ys = [d["rhr"] for d in data]
    n = len(xs)
    if n >= 4:
        sx, sy = sum(xs), sum(ys)
        sxy = sum(x * y for x, y in zip(xs, ys))
        sx2 = sum(x * x for x in xs)
        denom = n * sx2 - sx * sx
        slope = (n * sxy - sx * sy) / denom if denom else 0
        trend_per_week = round(slope * 7, 2)
    else:
        slope = 0
        trend_per_week = None

    # Weeks to reach 65 bpm goal (realistic floor given medication)
    goal = 65
    weeks_to_goal = None
    if slope < 0 and current > goal:
        days_to_goal = (goal - current) / slope
        weeks_to_goal = round(days_to_goal / 7)

    return {
        "data": data,
        "current": current,
        "goal": goal,
        "trend_bpm_per_week": trend_per_week,
        "weeks_to_goal": weeks_to_goal,
        "note": "Target 65 bpm (medication-adjusted; true baseline ~55–60 without amitriptyline)",
    }


def cardio_zone_minutes_history(days: int = 84) -> list:
    """Per-workout zone breakdown for the past N days — for the zone chart."""
    conn = get_conn()
    hr_max = _hr_max()
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    workouts = conn.execute("""
        SELECT id, name, start_ts, duration_s, avg_hr
        FROM workouts WHERE DATE(start_ts) >= ? ORDER BY start_ts
    """, (cutoff,)).fetchall()

    result = []
    for w in workouts:
        dur_min = (w["duration_s"] or 0) / 60.0
        avg = w["avg_hr"]
        if not avg:
            continue
        pct = avg / hr_max
        if pct < 0.57:
            zone = 1
        elif pct < 0.63:
            zone = 2
        elif pct < 0.75:
            zone = 3
        elif pct < 0.87:
            zone = 4
        else:
            zone = 5
        result.append({
            "date": w["start_ts"][:10],
            "name": w["name"],
            "dur_min": round(dur_min),
            "avg_hr": round(avg),
            "zone": zone,
        })

    conn.close()
    return result


def cardio_ecg_results() -> list:
    """Return stored ECG results."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM ecg_results ORDER BY date DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def cardio_blood_panel(test_names: list = None) -> list:
    """Return stored blood panel values, optionally filtered."""
    conn = get_conn()
    try:
        if test_names:
            placeholders = ",".join("?" * len(test_names))
            rows = conn.execute(
                f"SELECT * FROM blood_panel WHERE test_name IN ({placeholders}) ORDER BY date DESC, test_name",
                test_names
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM blood_panel ORDER BY date DESC, test_name"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()
