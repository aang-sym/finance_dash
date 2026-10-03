# Health Vitals Implementation Plan

**Branch:** `feature/health-vitals`  
**Goal:** Add HEALTH data section (7 tabs) + rename existing grooming tabs to CARE section.  
**Spec:** `docs/superpowers/specs/2026-05-26-health-vitals-design.md`

---

## File map

| Action | File |
|--------|------|
| MOVED (done) | `health/{anti-age,skin,hair,eyes,face,stocktake}.html` → `care/` |
| MODIFY ×6 | `care/*.html` — update nav/links/header pill to CARE |
| MODIFY | `server.py` — add `/care` routes, update `/health` redirect, add score API endpoints |
| CREATE | `health_pipeline/scores.py` — all 5 score computations |
| CREATE ×6 | `health/{dashboard,recovery,sleep,strain,nutrition,strength}.html` |
| STAYS | `health/import.html` — no changes needed |

---

## Task 1 — Update care/ files (nav + header pill)

**Files:** `care/anti-age.html`, `care/skin.html`, `care/hair.html`, `care/eyes.html`, `care/face.html`, `care/stocktake.html`

Each file needs:
- Header pill: replace `<a class="section-pill" href="/dashboard">FINANCE</a> <a class="section-pill active" href="/health/anti-age">HEALTH</a>` with three pills — FINANCE (inactive), CARE (active), HEALTH (inactive)
- Nav bar: replace old nav with CARE nav (no IMPORT item), update all `href="/health/..."` → `href="/care/..."`, mark correct tab active
- `<span class="hdr-sub">health</span>` → `care`

New header pills block (same in all 6):
```html
<a class="section-pill" href="/dashboard">FINANCE</a>
<a class="section-pill active" href="/care/anti-age">CARE</a>
<a class="section-pill" href="/health/dashboard">HEALTH</a>
```

New nav block (only `active` class differs per file):
```html
<a class="nav-item [active?]" href="/care/stocktake"><span class="nav-key">[S]</span>TOCKTAKE</a>
<a class="nav-item [active?]" href="/care/anti-age"><span class="nav-key">[A]</span>NTI-AGE</a>
<a class="nav-item [active?]" href="/care/skin"><span class="nav-key">[S]</span>KIN</a>
<a class="nav-item [active?]" href="/care/hair"><span class="nav-key">[H]</span>AIR</a>
<a class="nav-item [active?]" href="/care/eyes"><span class="nav-key">[E]</span>YES</a>
<a class="nav-item [active?]" href="/care/face"><span class="nav-key">[F]</span>ACE</a>
```

**Verify:** `curl -s http://localhost:5001/care/stocktake | grep "section-pill active"` → should show CARE

---

## Task 2 — Update server.py

**File:** `server.py`

Changes needed (around line 2179):

```python
# Add after HEALTH_DIR line:
CARE_DIR = BASE_DIR / "care"

# Replace /health redirect:
@app.get("/health")
def health_root():
    return redirect("/health/dashboard")

# Add /care routes:
@app.get("/care")
def care_root():
    return redirect("/care/anti-age")

@app.get("/care/<tab>")
def care_page(tab: str):
    page = CARE_DIR / f"{tab}.html"
    if not page.exists():
        return "Not found", 404
    return send_file(page)
```

New API endpoints to add (after existing `/api/health/workouts`):

```python
from health_pipeline.scores import compute_scores, scores_history, strain_workouts_detail

@app.get("/api/health/scores")
def api_health_scores():
    return jsonify(compute_scores())

@app.get("/api/health/scores/history")
def api_health_scores_history():
    days = int(request.args.get("days", 30))
    return jsonify(scores_history(days))

@app.get("/api/health/strain/workouts")
def api_health_strain_workouts():
    days = int(request.args.get("days", 30))
    return jsonify(strain_workouts_detail(days))

@app.get("/api/health/nutrition/detail")
def api_health_nutrition_detail():
    days = int(request.args.get("days", 30))
    return jsonify(nutrition_daily(days))

@app.get("/api/health/strength/exercises")
def api_health_strength_exercises():
    from health_pipeline.scores import strength_exercises
    return jsonify(strength_exercises())

@app.get("/api/health/strength/progression")
def api_health_strength_progression():
    from health_pipeline.scores import strength_progression
    exercise = request.args.get("exercise", "")
    days = int(request.args.get("days", 90))
    return jsonify(strength_progression(exercise, days))
```

**Verify:** `python -c "import server"` exits 0

---

## Task 3 — Create health_pipeline/scores.py

**File:** `health_pipeline/scores.py`

Full module — compute all 5 scores + strength helpers:

```python
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
    nutrition_daily, workout_sessions, vo2_trend, get_config,
)


def _sigmoid(z: float) -> float:
    return 100.0 / (1.0 + math.exp(-1.5 * z))


def _baseline_60(values: list[float]) -> tuple[Optional[float], Optional[float]]:
    """Return (mean, std) of last 60 values, or (None, None) if <14 samples."""
    if len(values) < 14:
        return None, None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std = math.sqrt(variance) if variance > 0 else 1.0
    return mean, std


def _hrv_60d() -> tuple[list, Optional[float], Optional[float]]:
    rows = hrv_daily(60)
    vals = [r["hrv_avg"] for r in rows if r["hrv_avg"]]
    mean, std = _baseline_60(vals)
    return rows, mean, std


def _rhr_60d() -> tuple[list, Optional[float], Optional[float]]:
    rows = resting_hr_daily(60)
    vals = [r["rhr"] for r in rows if r["rhr"]]
    mean, std = _baseline_60(vals)
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
        sleep_hrs = last_sleep["total_sleep_hrs"] if last_sleep else 0

        hrv_z = (today_hrv - hrv_mean) / hrv_std if today_hrv and hrv_std else 0
        rhr_z = (rhr_mean - today_rhr) / rhr_std if today_rhr and rhr_std else 0
        sleep_pf = min(sleep_hrs / 8.0, 1.0)

        hrv_contrib = 0.65 * _sigmoid(hrv_z)
        rhr_contrib = 0.20 * _sigmoid(rhr_z)
        sleep_contrib = 0.15 * sleep_pf * 100

        score = max(0, min(100, hrv_contrib + rhr_contrib + sleep_contrib))
        components = {
            "hrv_ms": today_hrv,
            "hrv_z": round(hrv_z, 2),
            "rhr_bpm": today_rhr,
            "rhr_z": round(rhr_z, 2),
            "sleep_hrs": round(sleep_hrs, 2),
            "sleep_pf": round(sleep_pf, 2),
        }

    zone = "green" if score and score >= 67 else ("red" if score and score <= 33 else "yellow")
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
        return {"score": None, "calibrating": True, "zone": "red", "last_night": None}

    last = rows[-1]
    total = last["total_sleep_hrs"] or 0
    rem = last["rem_hrs"] or 0
    deep = last["deep_hrs"] or 0
    awake_count = last["awake_count"] or 0

    # Bedtime consistency vs 7-day mean
    bedtimes = []
    for r in rows[-7:]:
        if r["bedtime"]:
            try:
                dt = datetime.fromisoformat(r["bedtime"])
                # Normalise to minutes past midnight (treat 20:00–02:00 as same night)
                mins = dt.hour * 60 + dt.minute
                if mins < 6 * 60:
                    mins += 24 * 60
                bedtimes.append(mins)
            except Exception:
                pass
    if len(bedtimes) >= 2:
        mean_bt = sum(bedtimes) / len(bedtimes)
        deviation_mins = abs(bedtimes[-1] - mean_bt) if bedtimes else 0
    else:
        deviation_mins = 0

    dur_score = min(total / 8.0, 1.0) * 100
    stage_ratio = (rem + deep) / total if total > 0 else 0
    stage_score = min(stage_ratio / 0.50, 1.0) * 100
    cont_score = max(0, 100 - awake_count * 10)
    cons_score = max(0, 100 - deviation_mins / 60 * 20)

    score = 0.40 * dur_score + 0.30 * stage_score + 0.20 * cont_score + 0.10 * cons_score
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


def _edwards_trimp_for_workout(workout_id: int, conn) -> float:
    """Compute Edwards TRIMP for one workout using per-minute HR data."""
    hr_max = _hr_max()
    rows = conn.execute(
        "SELECT qty_bpm FROM workout_hr WHERE workout_id=? ORDER BY ts",
        (workout_id,)
    ).fetchall()
    if not rows:
        return 0.0
    trimp = 0.0
    for (bpm,) in rows:
        pct = bpm / hr_max
        if pct < 0.57:
            trimp += 1
        elif pct < 0.63:
            trimp += 2
        elif pct < 0.75:
            trimp += 3
        elif pct < 0.87:
            trimp += 4
        else:
            trimp += 5
    return trimp


def _trimp_from_avg_hr(avg_hr: float, duration_s: float) -> float:
    """Fallback TRIMP estimate when no per-minute data."""
    hr_max = _hr_max()
    pct = avg_hr / hr_max
    duration_min = duration_s / 60.0
    if pct < 0.57:
        mult = 1
    elif pct < 0.63:
        mult = 2
    elif pct < 0.75:
        mult = 3
    elif pct < 0.87:
        mult = 4
    else:
        mult = 5
    return duration_min * mult


def strain_score(days: int = 1) -> dict:
    """Strain for today (or most recent workout day in last `days`)."""
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    workouts = conn.execute(
        "SELECT id, workout_name, start_ts, duration_s, avg_hr FROM workouts WHERE DATE(start_ts) >= ? ORDER BY start_ts",
        (cutoff,)
    ).fetchall()

    total_trimp = 0.0
    workout_strains = []
    for w in workouts:
        wid, name, start_ts, duration_s, avg_hr = w["id"], w["workout_name"], w["start_ts"], w["duration_s"] or 0, w["avg_hr"]
        hr_rows = conn.execute("SELECT COUNT(*) FROM workout_hr WHERE workout_id=?", (wid,)).fetchone()[0]
        if hr_rows > 0:
            trimp = _edwards_trimp_for_workout(wid, conn)
        elif avg_hr:
            trimp = _trimp_from_avg_hr(avg_hr, duration_s)
        else:
            trimp = 0.0
        strain = min(21.0, 3.0 * math.log1p(trimp) + 0.5) if trimp > 0 else 0.0
        total_trimp += trimp
        workout_strains.append({
            "name": name,
            "start_ts": start_ts,
            "duration_min": round(duration_s / 60),
            "trimp": round(trimp, 1),
            "strain": round(strain, 1),
            "used_per_minute": hr_rows > 0,
        })

    conn.close()
    daily_strain = min(21.0, 3.0 * math.log1p(total_trimp) + 0.5) if total_trimp > 0 else 0.0
    zone = "green" if daily_strain <= 7 else ("red" if daily_strain >= 14 else "yellow")
    return {
        "score": round(daily_strain, 1),
        "calibrating": False,
        "zone": zone,
        "trimp": round(total_trimp, 1),
        "workouts": workout_strains,
        "hr_max": _hr_max(),
    }


def stress_score() -> dict:
    """Stress from daytime HRV suppression vs sleep HRV."""
    conn = get_conn()
    today = date.today().isoformat()
    # Sleep HRV: UTC 12:00–23:00 (AEST 22:00–09:00)
    sleep_hrv = conn.execute("""
        SELECT AVG(qty_ms) FROM hrv_samples
        WHERE DATE(ts) = ? AND (CAST(strftime('%H',ts) AS INTEGER) >= 12
              OR CAST(strftime('%H',ts) AS INTEGER) <= 9)
    """, (today,)).fetchone()[0]
    # Daytime HRV: UTC 23:00–11:00 (AEST 09:00–21:00) — note: cross-day UTC
    daytime_hrv = conn.execute("""
        SELECT AVG(qty_ms), COUNT(*) FROM hrv_samples
        WHERE DATE(ts) = ? AND CAST(strftime('%H',ts) AS INTEGER) BETWEEN 23 AND 23
    """, (today,)).fetchone()
    # Simpler: just split on hour
    daytime_rows = conn.execute("""
        SELECT AVG(qty_ms) as avg, COUNT(*) as cnt FROM hrv_samples
        WHERE DATE(ts) >= ? AND CAST(strftime('%H',ts) AS INTEGER) BETWEEN 23 AND 23
    """, ((date.today() - timedelta(days=1)).isoformat(),)).fetchone()
    conn.close()

    if not sleep_hrv or not daytime_rows or daytime_rows["cnt"] < 3:
        return {"score": None, "calibrating": True, "zone": "yellow", "insufficient_data": True}

    daytime_avg = daytime_rows["avg"]
    suppression = (sleep_hrv - daytime_avg) / sleep_hrv if sleep_hrv > 0 else 0
    score = max(1, min(100, 50 + suppression * 40))
    zone = "green" if score <= 33 else ("red" if score >= 67 else "yellow")
    return {
        "score": round(score, 1),
        "calibrating": False,
        "zone": zone,
        "sleep_hrv_mean": round(sleep_hrv, 1),
        "daytime_hrv_mean": round(daytime_avg, 1),
        "suppression": round(suppression, 3),
        "insufficient_data": False,
    }


def energy_bank(recovery: dict, strain: dict, stress: dict) -> dict:
    rec = recovery["score"] or 50
    str_score = strain["score"] or 0
    sts_score = stress["score"] or 50
    drain_strain = (str_score / 21) * 40
    drain_stress = (sts_score / 100) * 20
    bank = max(0, min(100, rec - drain_strain - drain_stress))
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

    # Today's nutrition summary
    nutr = nutrition_daily(1)
    nutr_today = nutr[-1] if nutr else None

    # Today's workouts summary
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
    """Daily score history. Computes recovery + sleep for each day in range.
    Strain per day from workouts table. Returns list of {date, recovery, sleep, strain}."""
    hrv_rows = hrv_daily(days + 60)
    rhr_rows = resting_hr_daily(days + 60)
    sleep_rows = sleep_daily(days)

    hrv_by_day = {r["day"]: r["hrv_avg"] for r in hrv_rows}
    rhr_by_day = {r["date"]: r["rhr"] for r in rhr_rows}
    sleep_by_day = {r["night"]: r for r in sleep_rows}

    result = []
    today = date.today()
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        # 60-day baseline up to this day
        cutoff = (today - timedelta(days=i + 60)).isoformat()
        hrv_vals = [v for k, v in hrv_by_day.items() if cutoff <= k < d and v]
        rhr_vals = [v for k, v in rhr_by_day.items() if cutoff <= k < d and v]
        hrv_mean, hrv_std = _baseline_60(hrv_vals)
        rhr_mean, rhr_std = _baseline_60(rhr_vals)

        today_hrv = hrv_by_day.get(d)
        today_rhr = rhr_by_day.get(d)
        sleep = sleep_by_day.get(d)

        rec = None
        if hrv_mean and today_hrv and today_rhr:
            hrv_z = (today_hrv - hrv_mean) / (hrv_std or 1)
            rhr_z = (rhr_mean - today_rhr) / (rhr_std or 1)
            sleep_hrs = sleep["total_sleep_hrs"] if sleep else 0
            sleep_pf = min((sleep_hrs or 0) / 8.0, 1.0)
            rec = round(max(0, min(100,
                0.65 * _sigmoid(hrv_z) + 0.20 * _sigmoid(rhr_z) + 0.15 * sleep_pf * 100
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
                0.20 * max(0, 100 - (sleep["awake_count"] or 0) * 10),
                1
            )

        result.append({"date": d, "recovery": rec, "sleep": slp})

    return result


def strain_workouts_detail(days: int = 30) -> list:
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    workouts = conn.execute(
        "SELECT id, workout_name, start_ts, duration_s, avg_hr FROM workouts WHERE DATE(start_ts) >= ? ORDER BY start_ts DESC",
        (cutoff,)
    ).fetchall()
    result = []
    hr_max = _hr_max()
    for w in workouts:
        wid = w["id"]
        hr_rows = conn.execute(
            "SELECT qty_bpm FROM workout_hr WHERE workout_id=? ORDER BY ts",
            (wid,)
        ).fetchall()
        zone_mins = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        if hr_rows:
            for (bpm,) in hr_rows:
                pct = bpm / hr_max
                if pct < 0.57: zone_mins[1] += 1
                elif pct < 0.63: zone_mins[2] += 1
                elif pct < 0.75: zone_mins[3] += 1
                elif pct < 0.87: zone_mins[4] += 1
                else: zone_mins[5] += 1
            trimp = sum(zone_mins[z] * z for z in range(1, 6))
        elif w["avg_hr"]:
            trimp = _trimp_from_avg_hr(w["avg_hr"], w["duration_s"] or 0)
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
        SELECT date, MAX(weight_kg * (1 + reps / 30.0)) as est_1rm,
               MAX(weight_kg) as max_weight, MAX(reps) as max_reps
        FROM workout_sets
        WHERE exercise = ? AND date >= ? AND weight_kg > 0 AND reps > 0
        GROUP BY date ORDER BY date
    """, (exercise, cutoff)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
```

**Verify:** `python -c "from health_pipeline.scores import compute_scores; print('ok')"` exits 0

---

## Task 4 — Update server.py

See Task 2 above for the exact edits. After adding:

**Verify:** `curl -s http://localhost:5001/care/stocktake | head -5` → returns HTML  
**Verify:** `curl -s http://localhost:5001/api/health/scores | python -m json.tool` → returns JSON  

---

## Task 5 — Create health/dashboard.html

Full-width page. Fetches `/api/health/scores`. Shows:
- 5 score cards in a row with SVG ring + 7-day sparkline
- Empty state if no data
- 3 summary panels below: last night sleep, today's workouts, today's nutrition

Design system: JetBrains Mono, --bg:#080a08, greens/ambers/reds.

---

## Task 6 — Create health/recovery.html

Fetches `/api/health/hrv`, `/api/health/resting-hr`, `/api/health/spo2`, `/api/health/respiratory-rate`, `/api/health/scores/history`. Shows 5 Chart.js line/area charts.

---

## Task 7 — Create health/sleep.html

Fetches `/api/health/sleep`. Shows 30-night stacked bar (Chart.js), sleep score trend, summary stats row, bedtime scatter.

---

## Task 8 — Create health/strain.html

Fetches `/api/health/strain/workouts`, `/api/health/vo2`. Shows workout list table, zone donut, ATL/CTL load chart, VO2 trend. Persistent medication note.

---

## Task 9 — Create health/nutrition.html

Fetches `/api/health/nutrition/detail`. Shows calories bar, protein line, macro ratio donut, micronutrient panel, caffeine/sodium bars.

---

## Task 10 — Create health/strength.html

Fetches `/api/health/strength/exercises` + `/api/health/strength/progression`. Shows session list, exercise dropdown → progression line chart.

---

## Navigation used in all new health/ tabs

Header pills:
```html
<a class="section-pill" href="/dashboard">FINANCE</a>
<a class="section-pill" href="/care/anti-age">CARE</a>
<a class="section-pill active" href="/health/dashboard">HEALTH</a>
```

Nav:
```html
<a class="nav-item [active?]" href="/health/dashboard"><span class="nav-key">[D]</span>ASHBOARD</a>
<a class="nav-item [active?]" href="/health/recovery"><span class="nav-key">[R]</span>ECOVERY</a>
<a class="nav-item [active?]" href="/health/sleep"><span class="nav-key">[S]</span>LEEP</a>
<a class="nav-item [active?]" href="/health/strain"><span class="nav-key">[S]</span>TRAIN</a>
<a class="nav-item [active?]" href="/health/nutrition"><span class="nav-key">[N]</span>UTRITION</a>
<a class="nav-item [active?]" href="/health/strength"><span class="nav-key">[S]</span>TRENGTH</a>
<a class="nav-item [active?]" href="/health/import"><span class="nav-key">[I]</span>MPORT</a>
```

---

## Execution order

1. Task 1 — Update care/ files ✅ (files copied, now need nav edits)
2. Task 2 + 4 — server.py changes
3. Task 3 — scores.py
4. Tasks 5–10 — health HTML tabs (one at a time)

Test after each task: `python server.py &` then `curl` the relevant route.
