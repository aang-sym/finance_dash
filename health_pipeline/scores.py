"""
Score computation for the health vitals section.
All scores use 60-day rolling personal baselines (Bevel methodology).
Sigmoid: 100 / (1 + exp(-1.5 * z))
"""
import math
from datetime import date, datetime, timedelta
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
        "SELECT id, workout_name, start_ts, duration_s, avg_hr FROM workouts "
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
            "name": w["workout_name"],
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
        "SELECT id, workout_name, start_ts, duration_s, avg_hr FROM workouts "
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
            "name": w["workout_name"],
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
