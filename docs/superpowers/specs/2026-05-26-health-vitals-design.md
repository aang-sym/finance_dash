# Health Vitals Section — Design Spec

## Goal

Add a new top-level **HEALTH** section (pill in the header, alongside FINANCE and CARE) containing 7 tabs: DASHBOARD · RECOVERY · SLEEP · STRAIN · NUTRITION · STRENGTH · IMPORT. The existing tabs (STOCKTAKE · ANTI-AGE · SKIN · HAIR · EYES · FACE) move to a renamed **CARE** section. The IMPORT tab moves from CARE into HEALTH only.

---

## Navigation Restructure

### Header pills (all pages)
```
FINANCE  ·  CARE  ·  HEALTH
```
- FINANCE → `/dashboard`
- CARE → `/care/anti-age` (first CARE tab)
- HEALTH → `/health/dashboard` (first HEALTH tab)

### CARE tabs (formerly "health" grooming tabs)
`STOCKTAKE · ANTI-AGE · SKIN · HAIR · EYES · FACE`

Routes: `/care/<tab>` — server serves `care/<tab>.html`  
Files moved from `health/` to `care/` directory.  
IMPORT tab removed from CARE entirely.

### HEALTH tabs (new data section)
`DASHBOARD · RECOVERY · SLEEP · STRAIN · NUTRITION · STRENGTH · IMPORT`

Routes: `/health/<tab>` — server serves `health/<tab>.html`  
Files live in `health/` directory (which currently has the grooming tabs — these move to `care/`).

---

## Architecture

All score computation happens **server-side in Python** at request time — no client-side computation. The Flask API exposes pre-computed scores via JSON endpoints. The HTML tabs are static files that `fetch()` from these endpoints on load. All data stays local (SQLite).

New API endpoints needed:
- `GET /api/health/scores` — all 5 scores for today
- `GET /api/health/scores/history?days=30` — daily score history for trend charts
- `GET /api/health/strain/workouts?days=30` — per-workout strain breakdown
- `GET /api/health/nutrition/detail?days=30` — macro + micro detail
- `GET /api/health/strength/exercises` — exercise list for progression selector
- `GET /api/health/strength/progression?exercise=X&days=90` — sets for one exercise

New Python module: `health_pipeline/scores.py` — all score computation logic, called by the API endpoints.

---

## Score Formulas

All baselines use a **60-day rolling personal mean and standard deviation** (Bevel methodology — more stable for medicated users than Whoop's 30-day). z-scores map to 0–100 via sigmoid: `100 / (1 + exp(-1.5 × z))`, so baseline = 50%, +1 SD ≈ 70%, -1 SD ≈ 30%.

### Recovery Score (0–100%)

```
hrv_z    = (today_hrv_ms  - hrv_60d_mean)  / hrv_60d_std   # higher = better
rhr_z    = (rhr_60d_mean  - today_rhr_bpm) / rhr_60d_std   # inverted: lower = better
sleep_pf = min(last_night_sleep_hrs / 8.0, 1.0)            # 0–1, capped at 1

recovery = clip(0.65 × sigmoid(hrv_z) + 0.20 × sigmoid(rhr_z) + 0.15 × sleep_pf × 100, 0, 100)
```

- HRV measured from sleep window only (22:00–09:00 AEST = UTC 12:00–23:00)
- If <14 days of HRV data: show "calibrating" state, display raw HRV trend only
- Zones: Green ≥67%, Yellow 34–66%, Red ≤33% (Whoop thresholds)

### Sleep Score (0–100%)

```
duration_score   = min(total_sleep_hrs / 8.0, 1.0) × 100
stage_score      = min((rem_hrs + deep_hrs) / total_sleep_hrs / 0.50, 1.0) × 100
                   # target: 50% of sleep in REM+Deep (Whoop benchmark)
continuity_score = max(0, 100 - awake_count × 10)
                   # -10 per awakening, floor 0
consistency_score = max(0, 100 - abs(bedtime_deviation_mins) / 60 × 20)
                   # bedtime deviation vs 7-day mean bedtime, -20 per hour off

sleep_score = 0.40 × duration_score + 0.30 × stage_score +
              0.20 × continuity_score + 0.10 × consistency_score
```

- Falls back to Sleep Cycle data when Apple Watch sleep not available (current situation for most nights)
- Sleep Cycle provides stage breakdown; Apple Watch provides more accurate stages when available

### Strain Score (0–21, Whoop scale)

Uses Edwards zone method (most implementable with per-minute workout HR data):

```
Zone boundaries (% of HR max, default 170 bpm, user-configurable):
  Z1: <57%  → multiplier 1  (recovery)
  Z2: 57–63% → multiplier 2  (aerobic base)
  Z3: 63–75% → multiplier 3  (tempo)
  Z4: 75–87% → multiplier 4  (threshold)
  Z5: >87%  → multiplier 5  (max)

edwards_trimp = Σ (minutes_in_zone × zone_multiplier)   # across all workouts for the day

# Map to 0–21 logarithmic scale (calibrated: 60-min Z3 run ≈ 12–13 strain)
strain = min(21, a × ln(1 + edwards_trimp) + b)
# a = 3.0, b = 0.5  (rough calibration, revisable as data accumulates)
```

- Uses `workout_hr` table (per-minute HR during workouts)
- Falls back to `workouts.avg_hr` estimate if per-minute data missing
- Note shown on any HR-zone chart: *"HR zones are RPE-calibrated. Age-based formulas not used due to medication."*

### Stress Score (1–100)

```
daytime_hrv_mean = mean(hrv_samples where hour in AEST 09–21)
sleep_hrv_mean   = mean(hrv_samples where hour in AEST 22–08)

# Stress = daytime HRV suppression below sleep baseline
hrv_suppression = (sleep_hrv_mean - daytime_hrv_mean) / sleep_hrv_mean

# Also factor elevated daytime HR above personal mean
hr_elevation = (today_daytime_hr_mean - hr_60d_mean) / hr_60d_std

stress = clip(50 + hrv_suppression × 40 + hr_elevation × 10, 1, 100)
# 50 = baseline; higher suppression = higher stress
```

- If insufficient daytime HRV (<3 samples): show "insufficient data" state
- Shows hourly breakdown chart using `heart_rate_samples`

### Energy Bank (0–100%)

```
morning_charge = recovery_score           # starts each day at recovery level
strain_drain   = (strain_score / 21) × 40  # max strain drains 40 points
stress_drain   = (stress_score / 100) × 20 # max stress drains 20 points

energy_bank = clip(morning_charge - strain_drain - stress_drain, 0, 100)
```

- Static daily value (not real-time intraday) — computed once using today's data
- Shown on dashboard as the composite "how are you doing today" number

---

## Tab Designs

### DASHBOARD tab (`health/dashboard.html`)

Layout: full-width, max 1200px

**Top row — 5 score cards (equal width, horizontal):**
Each card: score name, large number, colour ring (green/amber/red by zone), 7-day sparkline, "calibrating" state if <14 days data.

Scores shown: Recovery · Sleep · Strain · Stress · Energy Bank

**Below scores — 3 summary panels (2-col grid):**
- Last night's sleep: total hours, stage bar (Core/REM/Deep/Awake)
- Today's workouts: name, duration, strain contribution
- Nutrition today: calories, protein bar vs target (2×bodyweight g if body_mass in DB, else 160g default)

**Empty state (no data imported):** Full-width prompt card: "No health data imported yet — go to IMPORT tab to sync Apple Health and MacroFactor."

### RECOVERY tab (`health/recovery.html`)

- HRV 30-day line chart (sleep-window only, daily avg)
- RHR 30-day line chart with 60-day baseline reference line
- SpO₂ 30-day area chart
- Respiratory rate 30-day line chart
- Recovery Score 30-day history chart (the composite score over time)
- Medication note shown persistently above HR zone content

### SLEEP tab (`health/sleep.html`)

- Last 30 nights stacked bar: Core / REM / Deep / Awake per night
- Sleep score trend line (30 days)
- Summary stats row: avg total, avg REM, avg Deep, avg efficiency
- Bedtime consistency scatter: dots per night on clock-face or simple line chart
- Source attribution shown per night (Sleep Cycle vs Apple Watch)

### STRAIN tab (`health/strain.html`)

- Workout list (30 days): name, date, duration, strain score, zone breakdown bar
- Zone distribution donut for last 30 days (% time in each zone)
- Cardio load chart: 7-day rolling Edwards TRIMP (acute load) vs 42-day rolling (chronic load) — shows ATL/CTL
- VO₂ Max trend (90 days, points only — sparse data)
- HR zone reference table (from config HR max)
- Medication note persistent

### NUTRITION tab (`health/nutrition.html`)

- Daily calories 30-day bar chart with target reference line
- Protein 30-day line chart with target reference (160g default or 2×body_mass)
- Macro ratio donut for last 7 days (carbs/fat/protein % of calories)
- Micronutrient panel: fiber, magnesium, potassium, calcium, iron, vitamin D — each as % of RDI with colour coding
- Caffeine 30-day bar chart
- Sodium 30-day bar chart (flagged red >2300mg)
- Data from `nutrition_log` table

### STRENGTH tab (`health/strength.html`)

- Workout session list (30 days): name, working sets, exercise count
- Exercise selector dropdown → progression chart (1RM estimate: weight × (1 + reps/30), plotted over time)
- Weekly volume by muscle group — requires exercise→muscle mapping table (hardcoded dict for common exercises)
- Data from `workout_sets` table

### IMPORT tab

Already exists at `health/import.html`. Moves to HEALTH section, removed from CARE. No changes to the file itself.

---

## Files Created / Modified

```
care/                          NEW directory
  anti-age.html                MOVED from health/
  skin.html                    MOVED from health/
  hair.html                    MOVED from health/
  eyes.html                    MOVED from health/
  face.html                    MOVED from health/
  stocktake.html               MOVED from health/

health/                        existing directory — grooming files removed
  dashboard.html               NEW
  recovery.html                NEW
  sleep.html                   NEW
  strain.html                  NEW
  nutrition.html               NEW
  strength.html                NEW
  import.html                  STAYS (already exists)

health_pipeline/
  scores.py                    NEW — all score computation

server.py                      MODIFY
  - Add /care/<tab> route (serves care/*.html)
  - Update /health/<tab> route (serves health/*.html, no longer care files)
  - Add /care redirect → /care/anti-age
  - Update /health redirect → /health/dashboard
  - Add /api/health/scores endpoint
  - Add /api/health/scores/history endpoint
  - Add /api/health/strain/workouts endpoint
  - Add /api/health/nutrition/detail endpoint
  - Add /api/health/strength/exercises endpoint
  - Add /api/health/strength/progression endpoint
```

All 6 moved CARE files need:
- Header pill: CARE becomes active (not HEALTH)
- Nav bar: updated to CARE tabs (STOCKTAKE · ANTI-AGE · SKIN · HAIR · EYES · FACE)
- IMPORT nav item removed
- `href` links: `/health/...` → `/care/...`

---

## Empty States

Every data tab handles missing data gracefully:
- No data at all → prompt card linking to IMPORT
- <14 days data → "calibrating" badge on score cards, raw data shown without composite score
- Missing specific metric → that chart shows "no data" placeholder, other charts still render

---

## Design System

Inherits existing JetBrains Mono terminal aesthetic:
- `--bg:#080a08`, `--green:#7ee787`, `--amber:#f0b86e`, `--red:#ff7b72`, `--blue:#79c0ff`
- Chart.js 4.4.0 via CDN, all chart colours use literal hex (not CSS vars)
- SVG icons where used: literal hex values
- Score ring: SVG circle with `stroke-dasharray` for fill percentage
- Zone colours: Z1 dim green → Z5 red (matching existing HR zone table in import.html)
