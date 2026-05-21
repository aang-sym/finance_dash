# Bevel Feature Parity Tracker

Progress tracking for health data layer. Check off features as they're built.

## Core Scores
- [ ] Recovery Score (0–100%) — HRV 35%, RHR 25%, Sleep 25%, SpO₂ 10%, RespRate 5%
- [ ] Sleep Score (0–100%) — time asleep, stage balance, HR dip, efficiency, continuity
- [ ] Strain Score (0–100%+) — active (HR zones) + passive (elevated resting HR)
- [ ] Stress Score (1–100) — daytime HR/HRV imbalance, hourly breakdown
- [ ] Energy Bank — starts at Recovery Score, drains/recharges through day

## Fitness / Cardio
- [ ] Cardio Load (ATL/CTL model, TRIMP-based)
- [ ] Cardio Status (7 states: Calibrating → Overtraining)
- [ ] Cardio Focus (zone distribution donut: Low Aerobic / High Aerobic / Anaerobic)
- [ ] Heart Rate Recovery (HRR = peak − HR 2min post-workout, Zone 4+ only)
- [ ] VO₂ Max trend with age/sex reference ranges

## Sleep
- [ ] Per-night stage breakdown (Core/REM/Deep/Awake stacked bar)
- [ ] Sleep Bank (cumulative sleep debt)
- [ ] Sleep Need (personalised target)
- [ ] Bedtime/wake consistency score
- [ ] Sleeping HR / HRV / SpO₂ / respiratory rate sub-charts

## Wearable Vitals
- [x] HRV trend (data pipeline ✓)
- [x] Resting HR trend (data pipeline ✓)
- [ ] Daytime HR (hourly breakdown)
- [x] Step count vs 10k target (data pipeline ✓)
- [ ] Wrist temperature deviation from baseline
- [x] SpO₂ daily average (data pipeline ✓)
- [x] Respiratory rate trend (data pipeline ✓)

## Nutrition (MacroFactor)
- [x] Daily macros (calories, protein, carbs, fat) — data pipeline ✓
- [ ] Macro ratio chart
- [ ] Micronutrient targets (fiber, magnesium, potassium, calcium, iron, vitamin D)
- [ ] Caffeine intake trend
- [ ] Sodium trend (relates to facial bloating — links to skin tab)

## Strength (MacroFactor)
- [x] Workout log import (sets, reps, weight) — data pipeline ✓
- [ ] Strength progression per exercise (line chart)
- [ ] Muscle distribution chart (balance across muscle groups)
- [ ] Weekly volume by muscle group

## Data Infrastructure
- [x] SQLite schema
- [x] Streaming Apple Health JSON parser
- [x] MacroFactor CSV parsers
- [x] Flask API endpoints
- [x] Import tab UI (iCloud sync + file upload + config)
