# Nutrition App — Design Spec
**Date:** 2026-05-24  
**Status:** Approved

## Overview

A standalone nutrition sub-app at `/nutrition` within the existing Flask dashboard. Designed primarily for Ebony: helps her hit protein goals without triggering calorie-tracking anxiety. Protein is tracked numerically (good, wanted). Calories are computed internally but **never shown as a number** — only qualitative phrases. Visual style is warm consumer-app (not finance terminal). Built on the existing Flask server and `health.db` SQLite database.

---

## Goals

1. Help Ebony consistently hit her protein goal without the anxiety of calorie tracking
2. Make weekly meal planning easy — pick recipes, get a shopping list, reduce the Sunday stressor
3. Build a shared recipe library for meals you both like
4. Frame everything around fuelling, building, and growing — not restricting or counting

---

## Non-Goals

- Multi-user auth / login system (single shared view for now)
- Calorie counting or macro breakdown for Ebony (only protein + qualitative energy)
- Real-time notifications (page-level nudges only, no push notifications)
- A food barcode scanner
- Hosting / deployment (separate task)

---

## Architecture

### URL Structure

```
/nutrition              → redirects to /nutrition/today
/nutrition/today        → daily protein tracker + meal log
/nutrition/plan         → weekly + monthly meal planner
/nutrition/recipes      → recipe library (browse, add, import)
/nutrition/settings     → protein goal, calorie goal (hidden after setup), name
```

### Flask

Served by existing `server.py`. New routes added in a `nutrition_routes.py` Blueprint registered at prefix `/nutrition`. HTML files live in `nutrition/` directory alongside `health/`.

### Database

Five new tables in `data/health/health.db` (existing SQLite DB):

```sql
-- Recipe master record
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    source_url TEXT,            -- scraped from URL, nullable
    servings INTEGER DEFAULT 1,
    total_time_mins INTEGER,    -- optional
    instructions TEXT,          -- optional, markdown
    notes TEXT,                 -- personal notes
    image_url TEXT,             -- scraped or null
    tags TEXT,                  -- JSON array: ["high-protein","quick","dinner",...]
    use_count INTEGER DEFAULT 0, -- incremented each time logged or planned
    is_favourite INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Per-ingredient nutrition (one row per ingredient per recipe)
CREATE TABLE IF NOT EXISTS recipe_ingredients (
    id INTEGER PRIMARY KEY,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    food_name TEXT NOT NULL,
    amount_g REAL,
    protein_g REAL DEFAULT 0,
    calories REAL DEFAULT 0,
    fat_g REAL DEFAULT 0,
    carbs_g REAL DEFAULT 0
);

-- Daily food log (one row per item logged)
CREATE TABLE IF NOT EXISTS daily_log (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,             -- YYYY-MM-DD
    logged_at TEXT DEFAULT (datetime('now')),
    recipe_id INTEGER REFERENCES recipes(id),  -- null if quick-add
    custom_name TEXT,               -- used when recipe_id is null
    servings REAL DEFAULT 1,
    protein_g REAL NOT NULL,
    calories REAL,                  -- stored always, never shown
    calorie_band TEXT               -- 'snack'/'light'/'medium'/'big' for quick-adds
);
CREATE INDEX IF NOT EXISTS idx_log_date ON daily_log(date);

-- Meal plan (one row per planned meal slot)
CREATE TABLE IF NOT EXISTS meal_plan (
    id INTEGER PRIMARY KEY,
    plan_date TEXT NOT NULL,        -- YYYY-MM-DD (the actual date)
    week_start TEXT NOT NULL,       -- YYYY-MM-DD (Monday of that week)
    meal_slot TEXT NOT NULL,        -- 'breakfast'/'lunch'/'dinner'/'snack'
    recipe_id INTEGER NOT NULL REFERENCES recipes(id),
    servings REAL DEFAULT 1,
    planned_protein_g REAL,         -- denormalised for fast queries
    planned_calories REAL           -- denormalised, never shown
);
CREATE INDEX IF NOT EXISTS idx_plan_date ON meal_plan(plan_date);
CREATE INDEX IF NOT EXISTS idx_plan_week ON meal_plan(week_start);

-- Nutrition config (key-value)
CREATE TABLE IF NOT EXISTS nutrition_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Seed defaults:
-- INSERT OR IGNORE INTO nutrition_config VALUES ('protein_goal_g', '120')
-- INSERT OR IGNORE INTO nutrition_config VALUES ('calorie_goal_kcal', '')  -- empty until setup
-- INSERT OR IGNORE INTO nutrition_config VALUES ('setup_complete', '0')
-- INSERT OR IGNORE INTO nutrition_config VALUES ('display_name', 'Ebony')
-- INSERT OR IGNORE INTO nutrition_config VALUES ('workout_streak', '0')
```

### Calorie Bands (quick-add)

| Band | Label shown to Ebony | Approximate kcal stored |
|------|---------------------|------------------------|
| `snack` | Light snack | 150 |
| `light` | Light meal | 350 |
| `medium` | Medium meal | 550 |
| `big` | Big meal | 800 |

Stored as `calories` in `daily_log`. **Never displayed back.**

### Qualitative Calorie Language

Computed as `sum(calories today) / calorie_goal_kcal`:

| Ratio | Message shown |
|-------|--------------|
| < 0.55 | 🌿 "You're well below your energy goal today — there's plenty of room to add more" |
| 0.55–0.75 | 🌱 "You're tracking toward your energy goal — keep going" |
| 0.75–0.92 | ✅ "You're tracking nicely toward your energy goal" |
| 0.92–1.10 | 💛 "You're just about at your energy goal today" |
| 1.10–1.28 | 🌸 "You've gone a little over your energy goal today — that's completely okay" |
| > 1.28 | 💚 "You've had a full day of eating — tomorrow is a fresh start" |

If `calorie_goal_kcal` is not set (setup incomplete): hide the calorie status section entirely.

---

## TODAY Tab

### Layout

```
┌─────────────────────────────────────────────────────────┐
│  [TODAY]  [PLAN]  [RECIPES]  [SETTINGS]                  │
├──────────────────┬──────────────────────────────────────┤
│                  │                                       │
│  Protein ring    │  7-day protein trend (sparkline/bars) │
│  "87g / 120g"    │  Mon Tue Wed Thu Fri Sat Sun          │
│  (ring fills)    │  ██  ██  ░░  ██  ██  ██  (today)     │
│                  │                                       │
├──────────────────┴──────────────────────────────────────┤
│  ✅ "You're tracking nicely toward your energy goal"     │
├─────────────────────────────────────────────────────────┤
│  🔥 3-day protein streak!                                │
│  (or: contextual nudge based on time of day / workout)  │
├─────────────────────────────────────────────────────────┤
│  Today's meals                          [ + ADD MEAL ]  │
│  ─────────────────────────────────────────────────────  │
│  🍳 Greek yoghurt bowl          32g protein  09:14      │
│  🥗 Chicken & rice              41g protein  13:02      │
│  ─────────────────────────────────────────────────────  │
│  Still to go: 40g protein                               │
└─────────────────────────────────────────────────────────┘
```

### Protein Ring

- SVG ring, fills as percentage of goal
- Colour: red (< 40%) → amber (40–70%) → green (70–100%+)
- Shows `Xg / Xg` in centre — **both numbers shown** (protein tracking is the explicit goal)
- At 100%+: ring glows green, shows a small ✅ or confetti moment

### 7-Day Trend

- Small bar chart, last 7 days including today
- Bars coloured: green (≥ goal), amber (70–99%), red (< 70%)
- Today's bar is slightly wider / highlighted
- No labels except day abbreviation

### Positivity Features

**Protein streak** (shown when ≥ 2 consecutive days at goal):
- `🔥 {N}-day protein streak — keep it up!`
- Resets silently — no "streak broken" message

**Weekly wins** (shown on any day, reflects back):
- `💚 This week you've hit your protein goal {N} days — brilliant work`
- Never mentions missed days

**Workout-day context** (shown when "lifting today" toggle is on):
- Pre-workout (< 3pm): `💪 Lifting day! Your muscles need fuel — protein is extra important today`
- Post-workout (toggle flipped to "done"): `🏋️ Great session! Make sure to get some protein in soon`

**Recipe of the day** (shown in morning, rotates through library):
- `🍽️ Dinner idea: {recipe name} — {protein}g protein per serving`
- Picks a recipe not used in the last 7 days, prioritises high-protein

**Afternoon nudge** (shown after 2pm if < 50% protein goal hit):
- `🌿 Afternoon check-in: {X}g to go — dinner could get you there`
- Hidden if protein goal already hit

### Add Meal Modal

Two tabs:
1. **From recipes** — search box + recent + favourite recipes. Tap to select. Set servings. Protein auto-calculated.
2. **Quick add** — Name field + protein grams field + calorie band dropdown (Light snack / Light meal / Medium meal / Big meal). Calories stored, never shown.

---

## PLAN Tab

### Week View

```
         Mon   Tue   Wed   Thu   Fri   Sat   Sun
Breakfast  +    🍳    🥣    +     🍳    🥞    +
Lunch      🥗   +     🥙    🌯    +     +     🥗
Dinner     🍗   🐟    +     🍝    🥩    🍛    +
Snack      +    +     +     +     +     +     +
──────────────────────────────────────────────────
Protein   85g  112g  78g  134g  90g   105g  --
          ██   ████  ███  ████  ███   ████  (empty)
          amber green amber green amber green
```

- Click any cell → recipe picker drawer
- Planned protein shown as bar + number per day
- Hover a recipe cell → tooltip with recipe name + protein
- "Copy last week" button at top right
- Navigate weeks with `< prev` `next >`

### Month View

- Calendar grid (month at a glance)
- Each day shows a small coloured dot: green (planned + meets goal), amber (planned + under goal), grey (no plan)
- Click a day → jumps to that week in week view

### Shopping List

Generated from all planned recipes for the selected week:
- Deduplicated ingredients, quantities summed
- Grouped by category: 🥬 Produce, 🥩 Protein, 🥛 Dairy, 🍞 Pantry, 🧊 Frozen
- Copy to clipboard button
- Print-friendly view

---

## RECIPES Tab

### Layout

```
[ Search...        ] [ Tags ▾ ] [ + NEW RECIPE ] [ Import ▾ ]

★ Favourites & Most Used
┌────────┐ ┌────────┐ ┌────────┐
│  🍗    │ │  🥗    │ │  🥛    │
│  Chkn  │ │  Bowl  │ │  Shake │
│  34g ✦ │ │  28g ✦ │ │  40g ✦ │
└────────┘ └────────┘ └────────┘

All Recipes
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│ ...    │ │ ...    │ │ ...    │ │ ...    │
└────────┘ └────────┘ └────────┘ └────────┘
```

Each card shows: recipe name, protein per serving (large), time (if set), tag chips, favourite star.

### Tags

`high-protein` `quick` `breakfast` `lunch` `dinner` `snack` `vegetarian` `bulk-cook`

Multiple tags can be active at once (filter intersection).

### Recipe Detail Panel (slide-in or modal)

- Recipe name + source URL link (if scraped)
- Protein per serving (large, prominent)
- Ingredient list with per-ingredient protein (if available)
- Total macros: protein / carbs / fat (no calorie number)
- Instructions (collapsible)
- Tags
- Actions: "Log today", "Add to plan", "Edit", "Delete"

### Adding a Recipe

**Flow 1 — URL import:**
1. User pastes a URL
2. Server calls `recipe-scrapers` library to extract title, ingredients, servings, image
3. For each ingredient: server calls Open Food Facts API to look up nutrition by ingredient name
4. Editable confirmation form — user can correct protein/cal values before saving
5. Tags auto-suggested based on recipe title keywords

**Flow 2 — Manual entry:**
1. Form: Name, servings, total time (optional), tags
2. Ingredient table: food name + weight (g) + protein (g) + calories. "Look up" button per row queries Open Food Facts by name.
3. Instructions text area (optional)
4. Notes field

**Flow 3 — MacroFactor recipe export:**
- MacroFactor allows exporting custom foods/recipes as a CSV
- Upload the CSV; server maps `Food Name`, `Protein (g)`, `Calories (kcal)` columns to recipe records
- Each row becomes either a recipe or a recipe ingredient depending on structure
- User reviews and confirms mappings before saving

---

## SETTINGS Tab

```
Display name:  [ Ebony              ]

Protein goal:  [ 120  ] g per day

Daily energy goal:
  ● Set during setup (hidden after saving)
  [ Change goal ]  ← reveals input field, saves, hides again
  Current status: goal is set ✓

```

- **Display name:** used in personalised messages ("Morning Ebony! 🌿")
- **Protein goal:** editable, shown in grams
- **Calorie goal:** one-time setup flow on first visit. After saving, the number is hidden. A "Change goal" button reveals an input field, saves, then hides again. The number is **never shown in the settings UI** after first save — only a "goal is set ✓" indicator.

### First-Visit Setup Flow

If `setup_complete = 0` in `nutrition_config`: show a simple onboarding card on the TODAY tab:

> "Hi! Before we start, let's set a couple of things up."
> 1. What's your name? → text input
> 2. What's your protein goal? → number input (grams)  
> 3. (Optional) Set an energy goal — this is used to give you gentle guidance, and you'll never see the number again: → number input (kcal)

After saving: `setup_complete = 1`. The setup card disappears and the full TODAY view loads.

---

## API Endpoints

All under `/api/nutrition/`:

```
GET  /api/nutrition/today            → daily log + protein total + calorie ratio
GET  /api/nutrition/trend?days=7     → protein totals per day (last N days)
POST /api/nutrition/log              → add a log entry
DELETE /api/nutrition/log/{id}       → remove a log entry

GET  /api/nutrition/plan?week=YYYY-MM-DD  → meal plan for a week
POST /api/nutrition/plan                  → save/update a plan entry
DELETE /api/nutrition/plan/{id}           → remove a plan entry
GET  /api/nutrition/shopping?week=YYYY-MM-DD  → generate shopping list

GET  /api/nutrition/recipes          → list all recipes (+ use_count, is_favourite)
GET  /api/nutrition/recipes/{id}     → recipe detail + ingredients
POST /api/nutrition/recipes          → create recipe
PUT  /api/nutrition/recipes/{id}     → update recipe
DELETE /api/nutrition/recipes/{id}   → delete recipe
POST /api/nutrition/recipes/scrape   → scrape URL → returns pre-filled form data
POST /api/nutrition/recipes/import-macrofactor  → parse MacroFactor CSV

GET  /api/nutrition/config           → get all config keys (calorie_goal_kcal excluded)
POST /api/nutrition/config           → update config keys
```

Note: `calorie_goal_kcal` is **never returned** by any GET endpoint. It is write-only via the settings setup flow. The today endpoint returns only the qualitative `calorie_status` string.

---

## Python Dependencies (new)

- `recipe-scrapers` — URL recipe extraction (~500 sites supported)
- Open Food Facts API — free REST API, no key needed, called at ingredient-lookup time

Both are pip-installable; `recipe-scrapers` is the only new package to add to the environment.

---

## File Structure

```
nutrition/
  today.html           — TODAY tab
  plan.html            — PLAN tab  
  recipes.html         — RECIPES tab
  settings.html        — SETTINGS tab

nutrition_app/
  __init__.py
  routes.py            — Flask Blueprint registered at /nutrition + /api/nutrition
  db.py                — schema creation + query helpers
  recipe_scraper.py    — URL scraping (calls recipe-scrapers + Open Food Facts)
  shopping.py          — shopping list generation logic

server.py              — MODIFY: register nutrition Blueprint
data/health/health.db  — MODIFY: new tables via migration in nutrition_app/db.py
```

---

## Body-Positive Design Principles

These apply everywhere in the UI:

1. **Protein numbers are shown** — this is the goal, and seeing progress is motivating
2. **Calorie numbers are never shown** — stored for computation, invisible to Ebony
3. **Language focuses on fuelling and building**, not restricting or burning
4. **Misses are invisible** — only wins surface (streaks count up, never down)
5. **Food is neutral** — no "good" vs "bad" framing, no labels like "cheat" or "treat"
6. **Copy is warm and personal** — uses her name, uses emojis, never clinical language
7. **Goals are hers to set** — protein goal is visible and changeable; calorie goal is self-chosen and then private

---

## Scope & Phasing

This spec describes the full design. Implementation will be phased:

**Phase 1 (MVP):** DB schema, TODAY tab (protein tracking + meal logging + qualitative calorie status), SETTINGS tab (onboarding), basic RECIPES tab (manual entry + view)

**Phase 2:** URL recipe import + Open Food Facts lookup, positivity features (streaks, nudges, recipe of the day)

**Phase 3:** PLAN tab (week view + shopping list), month view, MacroFactor recipe import

---

## Out of Scope (for now)

- Authentication / per-user login
- Push notifications
- Barcode scanner
- Progress photo log (noted as optional — can be added in Phase 3+)
- Hosting/deployment setup
