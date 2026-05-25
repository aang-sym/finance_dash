# Nutrition App Phase 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the MVP nutrition app at `/nutrition` — SQLite schema, TODAY tab (protein tracking + meal logging + qualitative calorie status), SETTINGS tab (onboarding), and basic RECIPES tab (manual entry + browse).

**Architecture:** Flask routes added directly to `server.py` (no Blueprint — codebase doesn't use them). HTML pages in `nutrition/` directory. Backend logic in `nutrition_app/` package. All data in existing `data/health/health.db` SQLite DB via new tables. Calorie goal is write-only — stored but never returned by any GET endpoint.

**Tech Stack:** Python/Flask (existing), SQLite3 stdlib, vanilla JS fetch in HTML, Chart.js (already loaded in health tabs), Inter font (warm consumer style — not JetBrains Mono).

---

## File Map

**Create:**
- `nutrition_app/__init__.py` — empty package init
- `nutrition_app/db.py` — schema migration + query helpers for all nutrition tables
- `nutrition_app/queries.py` — business logic: daily totals, calorie status string, streak, trend
- `nutrition/today.html` — TODAY tab UI
- `nutrition/recipes.html` — RECIPES tab UI (manual entry + browse)
- `nutrition/settings.html` — SETTINGS tab + first-visit onboarding

**Modify:**
- `server.py` — add `NUTRITION_DIR`, nutrition page routes, nutrition API routes
- `requirements.txt` — no new packages needed for Phase 1

---

## Task 1: Branch + SQLite schema

**Files:**
- Create: `nutrition_app/__init__.py`
- Create: `nutrition_app/db.py`

- [ ] **Step 1: Create branch**

```bash
cd /Users/anguss/dev/finance_dash && git checkout main && git pull && git checkout -b feature/nutrition-app
```

Expected: `Switched to a new branch 'feature/nutrition-app'`

- [ ] **Step 2: Create package init**

Create `/Users/anguss/dev/finance_dash/nutrition_app/__init__.py` — empty file.

- [ ] **Step 3: Create nutrition_app/db.py**

Create `/Users/anguss/dev/finance_dash/nutrition_app/db.py`:

```python
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "health" / "health.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_nutrition_db() -> None:
    """Create nutrition tables if they don't exist. Safe to call on every startup."""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            source_url TEXT,
            servings INTEGER DEFAULT 1,
            total_time_mins INTEGER,
            instructions TEXT,
            notes TEXT,
            image_url TEXT,
            tags TEXT DEFAULT '[]',
            use_count INTEGER DEFAULT 0,
            is_favourite INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

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
        CREATE INDEX IF NOT EXISTS idx_ri_recipe ON recipe_ingredients(recipe_id);

        CREATE TABLE IF NOT EXISTS daily_log (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL,
            logged_at TEXT DEFAULT (datetime('now')),
            recipe_id INTEGER REFERENCES recipes(id),
            custom_name TEXT,
            servings REAL DEFAULT 1,
            protein_g REAL NOT NULL,
            calories REAL,
            calorie_band TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_log_date ON daily_log(date);

        CREATE TABLE IF NOT EXISTS meal_plan (
            id INTEGER PRIMARY KEY,
            plan_date TEXT NOT NULL,
            week_start TEXT NOT NULL,
            meal_slot TEXT NOT NULL,
            recipe_id INTEGER NOT NULL REFERENCES recipes(id),
            servings REAL DEFAULT 1,
            planned_protein_g REAL,
            planned_calories REAL
        );
        CREATE INDEX IF NOT EXISTS idx_plan_date ON meal_plan(plan_date);
        CREATE INDEX IF NOT EXISTS idx_plan_week ON meal_plan(week_start);

        CREATE TABLE IF NOT EXISTS nutrition_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        INSERT OR IGNORE INTO nutrition_config(key, value) VALUES
            ('protein_goal_g', '120'),
            ('calorie_goal_kcal', ''),
            ('setup_complete', '0'),
            ('display_name', 'Ebony');
    """)
    conn.commit()
    conn.close()


def get_config() -> dict:
    """Return all config keys EXCEPT calorie_goal_kcal (write-only)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT key, value FROM nutrition_config WHERE key != 'calorie_goal_kcal'"
    ).fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


def set_config(updates: dict) -> None:
    """Save config keys. All keys allowed including calorie_goal_kcal."""
    conn = get_conn()
    for k, v in updates.items():
        conn.execute(
            "INSERT OR REPLACE INTO nutrition_config(key, value) VALUES (?,?)",
            (k, str(v))
        )
    conn.commit()
    conn.close()


def _get_raw_calorie_goal() -> float | None:
    """Internal use only — never expose via API."""
    conn = get_conn()
    row = conn.execute(
        "SELECT value FROM nutrition_config WHERE key = 'calorie_goal_kcal'"
    ).fetchone()
    conn.close()
    val = row["value"] if row else ""
    try:
        return float(val) if val else None
    except ValueError:
        return None
```

- [ ] **Step 4: Smoke-test schema creation**

```bash
cd /Users/anguss/dev/finance_dash && source venv/bin/activate
python3 -c "
from nutrition_app.db import init_nutrition_db, get_conn
init_nutrition_db()
conn = get_conn()
tables = conn.execute(
    \"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%recipe%' OR name IN ('daily_log','meal_plan','nutrition_config') ORDER BY name\"
).fetchall()
print([r[0] for r in tables])
"
```

Expected: `['daily_log', 'meal_plan', 'nutrition_config', 'recipe_ingredients', 'recipes']`

- [ ] **Step 5: Commit**

```bash
git add nutrition_app/
git commit -m "feat(nutrition): SQLite schema for recipes, daily_log, meal_plan, nutrition_config"
```

---

## Task 2: Query layer

**Files:**
- Create: `nutrition_app/queries.py`

- [ ] **Step 1: Create nutrition_app/queries.py**

Create `/Users/anguss/dev/finance_dash/nutrition_app/queries.py`:

```python
"""
Business logic for the nutrition app.
All functions return plain dicts/lists suitable for jsonify().
Calorie numbers are NEVER returned by public functions — only the qualitative status string.
"""
from datetime import date, timedelta
from typing import Optional
from nutrition_app.db import get_conn, _get_raw_calorie_goal


# ── Calorie status ────────────────────────────────────────────────────────────

CALORIE_TIERS = [
    (0.55, "🌿 You're well below your energy goal today — there's plenty of room to add more"),
    (0.75, "🌱 You're tracking toward your energy goal — keep going"),
    (0.92, "✅ You're tracking nicely toward your energy goal"),
    (1.10, "💛 You're just about at your energy goal today"),
    (1.28, "🌸 You've gone a little over your energy goal today — that's completely okay"),
    (float("inf"), "💚 You've had a full day of eating — tomorrow is a fresh start"),
]


def calorie_status_string(total_calories: float) -> Optional[str]:
    """Return qualitative calorie message, or None if no goal is set."""
    goal = _get_raw_calorie_goal()
    if not goal:
        return None
    ratio = total_calories / goal
    for threshold, message in CALORIE_TIERS:
        if ratio < threshold:
            return message
    return CALORIE_TIERS[-1][1]


# ── Daily log ─────────────────────────────────────────────────────────────────

def get_today_summary(today: Optional[str] = None) -> dict:
    """
    Returns today's protein total, meal log, calorie status string, and streak.
    Never returns calorie numbers.
    """
    if today is None:
        today = date.today().isoformat()

    conn = get_conn()

    # Today's meals
    rows = conn.execute("""
        SELECT dl.id, dl.logged_at, dl.recipe_id, dl.custom_name,
               dl.servings, dl.protein_g, dl.calorie_band,
               r.name as recipe_name
        FROM daily_log dl
        LEFT JOIN recipes r ON dl.recipe_id = r.id
        WHERE dl.date = ?
        ORDER BY dl.logged_at ASC
    """, (today,)).fetchall()

    total_protein = sum(r["protein_g"] for r in rows)

    # Calorie total for status string (internal only)
    cal_rows = conn.execute(
        "SELECT COALESCE(SUM(calories), 0) as total FROM daily_log WHERE date = ?",
        (today,)
    ).fetchone()
    total_cals = cal_rows["total"] if cal_rows else 0.0

    meals = []
    for r in rows:
        name = r["recipe_name"] if r["recipe_id"] else r["custom_name"]
        meals.append({
            "id": r["id"],
            "name": name,
            "servings": r["servings"],
            "protein_g": r["protein_g"],
            "logged_at": r["logged_at"],
            "calorie_band": r["calorie_band"],
            "is_recipe": r["recipe_id"] is not None,
        })

    conn.close()

    return {
        "date": today,
        "total_protein_g": round(total_protein, 1),
        "meals": meals,
        "calorie_status": calorie_status_string(total_cals),
        "streak": get_protein_streak(),
    }


def log_meal(
    date_str: str,
    protein_g: float,
    recipe_id: Optional[int] = None,
    custom_name: Optional[str] = None,
    servings: float = 1.0,
    calories: Optional[float] = None,
    calorie_band: Optional[str] = None,
) -> int:
    """Insert a meal log entry. Returns the new row id."""
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO daily_log
           (date, recipe_id, custom_name, servings, protein_g, calories, calorie_band)
           VALUES (?,?,?,?,?,?,?)""",
        (date_str, recipe_id, custom_name, servings, protein_g, calories, calorie_band)
    )
    new_id = cur.lastrowid
    # Bump recipe use_count
    if recipe_id:
        conn.execute(
            "UPDATE recipes SET use_count = use_count + 1 WHERE id = ?", (recipe_id,)
        )
    conn.commit()
    conn.close()
    return new_id


def delete_log_entry(entry_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM daily_log WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ── Protein trend ─────────────────────────────────────────────────────────────

def get_protein_trend(days: int = 7) -> list:
    """Return daily protein totals for the last N days."""
    conn = get_conn()
    cutoff = (date.today() - timedelta(days=days - 1)).isoformat()
    rows = conn.execute("""
        SELECT date, ROUND(SUM(protein_g), 1) as total_protein_g
        FROM daily_log
        WHERE date >= ?
        GROUP BY date
        ORDER BY date ASC
    """, (cutoff,)).fetchall()
    conn.close()

    # Fill in missing days with 0
    result = {}
    for r in rows:
        result[r["date"]] = r["total_protein_g"]

    trend = []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        trend.append({"date": d, "protein_g": result.get(d, 0)})
    return trend


# ── Protein streak ────────────────────────────────────────────────────────────

def get_protein_streak() -> int:
    """
    Count consecutive days (going back from yesterday) where protein_g >= goal.
    Today is excluded from streak (not yet complete).
    Returns 0 if no streak.
    """
    conn = get_conn()
    goal_row = conn.execute(
        "SELECT value FROM nutrition_config WHERE key = 'protein_goal_g'"
    ).fetchone()
    goal = float(goal_row["value"]) if goal_row else 120.0

    streak = 0
    check_date = date.today() - timedelta(days=1)
    for _ in range(365):  # safety limit
        row = conn.execute(
            "SELECT COALESCE(SUM(protein_g), 0) as total FROM daily_log WHERE date = ?",
            (check_date.isoformat(),)
        ).fetchone()
        if row and row["total"] >= goal:
            streak += 1
            check_date -= timedelta(days=1)
        else:
            break

    conn.close()
    return streak


# ── Recipes ───────────────────────────────────────────────────────────────────

def list_recipes(tag: Optional[str] = None, search: Optional[str] = None) -> dict:
    """
    Returns {'favourites': [...], 'all': [...]}.
    Each recipe dict includes per-serving protein/cal totals (cal is included
    for internal use but NOT exposed in the API response).
    """
    conn = get_conn()
    base_sql = """
        SELECT r.id, r.name, r.servings, r.total_time_mins, r.tags,
               r.use_count, r.is_favourite, r.source_url, r.image_url,
               ROUND(COALESCE(SUM(ri.protein_g), 0), 1) as total_protein_g,
               ROUND(COALESCE(SUM(ri.calories), 0), 0) as total_calories
        FROM recipes r
        LEFT JOIN recipe_ingredients ri ON ri.recipe_id = r.id
        GROUP BY r.id
        ORDER BY r.is_favourite DESC, r.use_count DESC, r.name ASC
    """
    rows = conn.execute(base_sql).fetchall()
    conn.close()

    recipes = []
    for r in rows:
        import json as _json
        tags_list = _json.loads(r["tags"]) if r["tags"] else []
        if tag and tag not in tags_list:
            continue
        if search and search.lower() not in r["name"].lower():
            continue
        servings = r["servings"] or 1
        recipes.append({
            "id": r["id"],
            "name": r["name"],
            "servings": servings,
            "total_time_mins": r["total_time_mins"],
            "tags": tags_list,
            "use_count": r["use_count"],
            "is_favourite": bool(r["is_favourite"]),
            "source_url": r["source_url"],
            "image_url": r["image_url"],
            "protein_per_serving_g": round(r["total_protein_g"] / servings, 1),
            # NOTE: calories_per_serving intentionally excluded from public output
        })

    favourites = [r for r in recipes if r["is_favourite"] or r["use_count"] >= 3]
    return {"favourites": favourites, "all": recipes}


def get_recipe_detail(recipe_id: int) -> Optional[dict]:
    conn = get_conn()
    r = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if not r:
        conn.close()
        return None

    ingredients = conn.execute(
        "SELECT * FROM recipe_ingredients WHERE recipe_id = ? ORDER BY id",
        (recipe_id,)
    ).fetchall()
    conn.close()

    import json as _json
    servings = r["servings"] or 1
    total_protein = sum(i["protein_g"] or 0 for i in ingredients)
    total_fat = sum(i["fat_g"] or 0 for i in ingredients)
    total_carbs = sum(i["carbs_g"] or 0 for i in ingredients)

    return {
        "id": r["id"],
        "name": r["name"],
        "source_url": r["source_url"],
        "servings": servings,
        "total_time_mins": r["total_time_mins"],
        "instructions": r["instructions"],
        "notes": r["notes"],
        "image_url": r["image_url"],
        "tags": _json.loads(r["tags"]) if r["tags"] else [],
        "is_favourite": bool(r["is_favourite"]),
        "use_count": r["use_count"],
        "protein_per_serving_g": round(total_protein / servings, 1),
        "fat_per_serving_g": round(total_fat / servings, 1),
        "carbs_per_serving_g": round(total_carbs / servings, 1),
        "ingredients": [
            {
                "id": i["id"],
                "food_name": i["food_name"],
                "amount_g": i["amount_g"],
                "protein_g": i["protein_g"],
                "fat_g": i["fat_g"],
                "carbs_g": i["carbs_g"],
                # calories excluded
            }
            for i in ingredients
        ],
    }


def create_recipe(data: dict) -> int:
    """
    Create a recipe with its ingredients.
    data keys: name, servings, total_time_mins, instructions, notes,
               source_url, image_url, tags (list), ingredients (list of dicts)
    Returns new recipe id.
    """
    import json as _json
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO recipes
           (name, servings, total_time_mins, instructions, notes, source_url, image_url, tags)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            data["name"],
            data.get("servings", 1),
            data.get("total_time_mins"),
            data.get("instructions"),
            data.get("notes"),
            data.get("source_url"),
            data.get("image_url"),
            _json.dumps(data.get("tags", [])),
        )
    )
    recipe_id = cur.lastrowid

    for ing in data.get("ingredients", []):
        conn.execute(
            """INSERT INTO recipe_ingredients
               (recipe_id, food_name, amount_g, protein_g, calories, fat_g, carbs_g)
               VALUES (?,?,?,?,?,?,?)""",
            (
                recipe_id,
                ing.get("food_name", ""),
                ing.get("amount_g"),
                ing.get("protein_g", 0),
                ing.get("calories", 0),
                ing.get("fat_g", 0),
                ing.get("carbs_g", 0),
            )
        )

    conn.commit()
    conn.close()
    return recipe_id


def toggle_favourite(recipe_id: int) -> bool:
    """Toggle is_favourite. Returns new value."""
    conn = get_conn()
    row = conn.execute(
        "SELECT is_favourite FROM recipes WHERE id = ?", (recipe_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    new_val = 0 if row["is_favourite"] else 1
    conn.execute(
        "UPDATE recipes SET is_favourite = ? WHERE id = ?", (new_val, recipe_id)
    )
    conn.commit()
    conn.close()
    return bool(new_val)


def delete_recipe(recipe_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0
```

- [ ] **Step 2: Smoke-test queries**

```bash
cd /Users/anguss/dev/finance_dash && source venv/bin/activate
python3 -c "
from nutrition_app.db import init_nutrition_db
from nutrition_app.queries import get_today_summary, get_protein_trend, list_recipes

init_nutrition_db()
print('today:', get_today_summary())
print('trend:', get_protein_trend())
print('recipes:', list_recipes())
"
```

Expected: `today:` shows `total_protein_g: 0`, no meals, `calorie_status: None` (no goal set yet). `trend:` shows 7 days all 0. `recipes:` shows empty lists.

- [ ] **Step 3: Commit**

```bash
git add nutrition_app/queries.py
git commit -m "feat(nutrition): query layer — daily summary, protein trend, streak, recipe CRUD"
```

---

## Task 3: Flask routes

**Files:**
- Modify: `server.py` — add NUTRITION_DIR, page routes, API routes

- [ ] **Step 1: Add nutrition routes to server.py**

Open `server.py`. Find the block:
```python
HEALTH_DIR = BASE_DIR / "health"
```

Add immediately after it:
```python
NUTRITION_DIR = BASE_DIR / "nutrition"
```

- [ ] **Step 2: Add page routes**

Find the block at the bottom of `server.py` that starts:
```python
@app.get("/health")
def health_root():
    return redirect("/health/anti-age")
```

Add the following **before** that block:

```python
# ── Nutrition app ─────────────────────────────────────────────────────────────

from nutrition_app.db import init_nutrition_db
from nutrition_app.queries import (
    get_today_summary, get_protein_trend, get_protein_streak,
    log_meal, delete_log_entry,
    list_recipes, get_recipe_detail, create_recipe, toggle_favourite, delete_recipe,
    get_config, set_config,
)

init_nutrition_db()


@app.get("/nutrition")
def nutrition_root():
    return redirect("/nutrition/today")


@app.get("/nutrition/<tab>")
def nutrition_page(tab: str):
    page = NUTRITION_DIR / f"{tab}.html"
    if not page.exists():
        return "Not found", 404
    return send_file(page)


@app.get("/api/nutrition/today")
def api_nutrition_today():
    from nutrition_app.queries import get_today_summary, get_protein_trend
    today = request.args.get("date")
    data = get_today_summary(today)
    trend = get_protein_trend(7)
    config = get_config()
    return jsonify({
        **data,
        "trend": trend,
        "protein_goal_g": float(config.get("protein_goal_g", 120)),
        "display_name": config.get("display_name", ""),
        "setup_complete": config.get("setup_complete", "0") == "1",
    })


@app.post("/api/nutrition/log")
def api_nutrition_log():
    body = request.get_json(force=True) or {}
    # Calorie band → approximate kcal (stored, never returned)
    BAND_KCAL = {"snack": 150, "light": 350, "medium": 550, "big": 800}
    band = body.get("calorie_band")
    calories = BAND_KCAL.get(band) if band else None

    # If logging a recipe, derive protein from recipe
    recipe_id = body.get("recipe_id")
    protein_g = body.get("protein_g")
    servings = float(body.get("servings", 1))

    if recipe_id and protein_g is None:
        detail = get_recipe_detail(int(recipe_id))
        if detail:
            protein_g = detail["protein_per_serving_g"] * servings
            # Derive calories from recipe ingredients (internal)
            conn = __import__("nutrition_app.db", fromlist=["get_conn"]).get_conn()
            row = conn.execute(
                "SELECT COALESCE(SUM(calories),0) as c FROM recipe_ingredients WHERE recipe_id=?",
                (recipe_id,)
            ).fetchone()
            conn.close()
            recipe_servings = detail["servings"]
            calories = (row["c"] / recipe_servings) * servings if recipe_servings else None

    if protein_g is None:
        return jsonify({"ok": False, "error": "protein_g required"}), 400

    entry_id = log_meal(
        date_str=body.get("date", __import__("datetime").date.today().isoformat()),
        protein_g=float(protein_g),
        recipe_id=recipe_id,
        custom_name=body.get("custom_name"),
        servings=servings,
        calories=calories,
        calorie_band=band,
    )
    return jsonify({"ok": True, "id": entry_id})


@app.delete("/api/nutrition/log/<int:entry_id>")
def api_nutrition_log_delete(entry_id: int):
    ok = delete_log_entry(entry_id)
    return jsonify({"ok": ok})


@app.get("/api/nutrition/recipes")
def api_nutrition_recipes():
    tag = request.args.get("tag")
    search = request.args.get("search")
    return jsonify(list_recipes(tag=tag, search=search))


@app.get("/api/nutrition/recipes/<int:recipe_id>")
def api_nutrition_recipe_detail(recipe_id: int):
    detail = get_recipe_detail(recipe_id)
    if not detail:
        return jsonify({"error": "not found"}), 404
    return jsonify(detail)


@app.post("/api/nutrition/recipes")
def api_nutrition_recipe_create():
    data = request.get_json(force=True) or {}
    if not data.get("name"):
        return jsonify({"ok": False, "error": "name required"}), 400
    recipe_id = create_recipe(data)
    return jsonify({"ok": True, "id": recipe_id})


@app.post("/api/nutrition/recipes/<int:recipe_id>/favourite")
def api_nutrition_recipe_favourite(recipe_id: int):
    new_val = toggle_favourite(recipe_id)
    return jsonify({"ok": True, "is_favourite": new_val})


@app.delete("/api/nutrition/recipes/<int:recipe_id>")
def api_nutrition_recipe_delete(recipe_id: int):
    ok = delete_recipe(recipe_id)
    return jsonify({"ok": ok})


@app.get("/api/nutrition/config")
def api_nutrition_config_get():
    from nutrition_app.db import get_config as _get_config
    return jsonify(_get_config())  # calorie_goal_kcal excluded by get_config()


@app.post("/api/nutrition/config")
def api_nutrition_config_set():
    body = request.get_json(force=True) or {}
    allowed = {"protein_goal_g", "display_name", "setup_complete", "calorie_goal_kcal"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if updates:
        from nutrition_app.db import set_config as _set_config
        _set_config(updates)
    return jsonify({"ok": True})
```

- [ ] **Step 3: Create the nutrition/ directory**

```bash
mkdir -p /Users/anguss/dev/finance_dash/nutrition
```

- [ ] **Step 4: Start server and test routes**

```bash
cd /Users/anguss/dev/finance_dash && source venv/bin/activate && python3 server.py &
sleep 2

# Test API
curl -s http://localhost:5001/api/nutrition/today | python3 -m json.tool
curl -s http://localhost:5001/api/nutrition/recipes | python3 -m json.tool
```

Expected: `today` returns `{"date":"...","total_protein_g":0,"meals":[],"calorie_status":null,"streak":0,"trend":[...],"protein_goal_g":120.0,"display_name":"Ebony","setup_complete":false}`. Recipes returns `{"favourites":[],"all":[]}`.

- [ ] **Step 5: Kill server**

```bash
pkill -f "python3 server.py"
```

- [ ] **Step 6: Commit**

```bash
git add server.py nutrition/
git commit -m "feat(nutrition): Flask routes for nutrition app — pages + API endpoints"
```

---

## Task 4: SETTINGS tab + onboarding

**Files:**
- Create: `nutrition/settings.html`

- [ ] **Step 1: Create nutrition/settings.html**

Create `/Users/anguss/dev/finance_dash/nutrition/settings.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nutrition · Settings</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#faf9f7;--surface:#ffffff;--surface2:#f5f3ef;
  --border:#e8e4de;--border2:#d6d0c8;
  --text:#2d2926;--text2:#6b6560;--text3:#9b958e;
  --green:#4a7c59;--green-light:#e8f0eb;--green-mid:#6fa882;
  --amber:#c17f3a;--amber-light:#fdf3e6;
  --red:#b85450;--red-light:#fdecea;
  --radius:12px;--radius-sm:8px;
  --font:'Inter',sans-serif;
}
html,body{min-height:100%;background:var(--bg);color:var(--text);font-family:var(--font);font-size:15px;line-height:1.6}
a{color:inherit;text-decoration:none}
/* Nav */
.app-nav{display:flex;align-items:center;border-bottom:1px solid var(--border);background:var(--surface);padding:0 20px;gap:2px;position:sticky;top:0;z-index:10}
.app-nav a{padding:14px 16px;font-size:14px;font-weight:500;color:var(--text2);border-bottom:2px solid transparent;transition:color .15s}
.app-nav a:hover{color:var(--text)}
.app-nav a.active{color:var(--green);border-bottom-color:var(--green)}
.app-nav .logo{font-weight:700;font-size:16px;color:var(--green);margin-right:12px;padding:14px 0}
/* Page */
.page{max-width:560px;margin:0 auto;padding:32px 20px;display:flex;flex-direction:column;gap:24px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:24px}
.card-title{font-size:17px;font-weight:600;margin-bottom:4px}
.card-sub{font-size:14px;color:var(--text2);margin-bottom:20px}
.field{margin-bottom:16px}
.field label{display:block;font-size:13px;font-weight:500;color:var(--text2);margin-bottom:6px;text-transform:uppercase;letter-spacing:0.04em}
.field input[type=text],.field input[type=number],.field input[type=password]{
  width:100%;padding:10px 14px;border:1px solid var(--border2);border-radius:var(--radius-sm);
  font-family:var(--font);font-size:15px;background:var(--bg);color:var(--text);
  transition:border-color .15s
}
.field input:focus{outline:none;border-color:var(--green)}
.field .hint{font-size:13px;color:var(--text3);margin-top:4px}
.btn{display:inline-flex;align-items:center;gap:6px;padding:10px 20px;border-radius:var(--radius-sm);font-family:var(--font);font-size:14px;font-weight:600;cursor:pointer;border:none;transition:background .15s,transform .1s}
.btn:active{transform:scale(0.98)}
.btn-primary{background:var(--green);color:#fff}
.btn-primary:hover{background:#3d6b4a}
.btn-ghost{background:var(--surface2);color:var(--text)}
.btn-ghost:hover{background:var(--border)}
.status-row{display:flex;align-items:center;gap:10px;padding:12px 14px;border-radius:var(--radius-sm);background:var(--green-light);color:var(--green);font-size:14px;font-weight:500}
.status-icon{font-size:18px}
.cal-reveal{display:none;margin-top:16px}
.cal-reveal.open{display:block}
.save-msg{font-size:13px;color:var(--green);margin-top:8px;min-height:20px}
.save-msg.err{color:var(--red)}

/* Onboarding overlay */
.onboarding{position:fixed;inset:0;background:rgba(245,243,239,0.97);display:flex;align-items:center;justify-content:center;z-index:100;padding:20px}
.onboarding.hidden{display:none}
.ob-card{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:40px;max-width:480px;width:100%;text-align:center}
.ob-emoji{font-size:48px;margin-bottom:16px}
.ob-title{font-size:24px;font-weight:700;margin-bottom:8px}
.ob-sub{font-size:15px;color:var(--text2);margin-bottom:32px;line-height:1.6}
.ob-step{display:none}.ob-step.active{display:block}
.ob-field{text-align:left;margin-bottom:20px}
.ob-field label{display:block;font-size:13px;font-weight:500;color:var(--text2);margin-bottom:6px;text-transform:uppercase;letter-spacing:0.04em}
.ob-field input{width:100%;padding:12px 16px;border:1px solid var(--border2);border-radius:var(--radius-sm);font-family:var(--font);font-size:16px;background:var(--bg)}
.ob-field input:focus{outline:none;border-color:var(--green)}
.ob-field .hint{font-size:13px;color:var(--text3);margin-top:5px}
.ob-skip{font-size:13px;color:var(--text3);margin-top:12px;cursor:pointer;text-decoration:underline}
.ob-skip:hover{color:var(--text2)}
.ob-nav{display:flex;gap:10px;justify-content:center;margin-top:8px}
.progress-dots{display:flex;gap:6px;justify-content:center;margin-bottom:24px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--border2);transition:background .2s}
.dot.active{background:var(--green)}
</style>
</head>
<body>

<!-- Onboarding overlay (shown on first visit) -->
<div class="onboarding" id="onboarding">
  <div class="ob-card">
    <div class="ob-emoji">🌿</div>
    <div class="ob-title" id="ob-title">Hi there!</div>
    <div class="ob-sub" id="ob-sub">Let's get a couple of things set up so we can make this work for you.</div>
    <div class="progress-dots">
      <div class="dot active" id="dot-0"></div>
      <div class="dot" id="dot-1"></div>
      <div class="dot" id="dot-2"></div>
    </div>

    <!-- Step 0: Name -->
    <div class="ob-step active" id="ob-step-0">
      <div class="ob-field">
        <label>What's your name?</label>
        <input type="text" id="ob-name" placeholder="e.g. Ebony" autocomplete="off">
      </div>
      <div class="ob-nav">
        <button class="btn btn-primary" onclick="obNext()">Next →</button>
      </div>
    </div>

    <!-- Step 1: Protein goal -->
    <div class="ob-step" id="ob-step-1">
      <div class="ob-field">
        <label>Daily protein goal</label>
        <input type="number" id="ob-protein" placeholder="e.g. 120" min="40" max="300">
        <div class="hint">In grams. This is what we'll track toward each day.</div>
      </div>
      <div class="ob-nav">
        <button class="btn btn-ghost" onclick="obPrev()">← Back</button>
        <button class="btn btn-primary" onclick="obNext()">Next →</button>
      </div>
    </div>

    <!-- Step 2: Calorie goal (optional) -->
    <div class="ob-step" id="ob-step-2">
      <div class="ob-field">
        <label>Daily energy goal <span style="font-weight:400;text-transform:none;font-size:12px;color:var(--text3)">(optional)</span></label>
        <input type="number" id="ob-calories" placeholder="e.g. 2000" min="1000" max="5000">
        <div class="hint">Used only for gentle guidance — you'll never see this number again after saving. Skip if you'd rather not set one.</div>
      </div>
      <div class="ob-nav">
        <button class="btn btn-ghost" onclick="obPrev()">← Back</button>
        <button class="btn btn-primary" onclick="obFinish()">Let's go 🌱</button>
      </div>
      <div class="ob-skip" onclick="obFinish()">Skip this step</div>
    </div>
  </div>
</div>

<!-- Main nav -->
<nav class="app-nav">
  <span class="logo">🌿 nourish</span>
  <a href="/nutrition/today">Today</a>
  <a href="/nutrition/plan">Plan</a>
  <a href="/nutrition/recipes">Recipes</a>
  <a href="/nutrition/settings" class="active">Settings</a>
</nav>

<main class="page">

  <div class="card">
    <div class="card-title">Your profile</div>
    <div class="card-sub">Personalise how the app talks to you</div>

    <div class="field">
      <label>Display name</label>
      <input type="text" id="cfg-name" placeholder="Your name">
    </div>

    <div class="field">
      <label>Daily protein goal</label>
      <input type="number" id="cfg-protein" min="40" max="300">
      <div class="hint">Grams per day. Shown on your tracker.</div>
    </div>

    <button class="btn btn-primary" onclick="saveProfile()">Save changes</button>
    <div class="save-msg" id="msg-profile"></div>
  </div>

  <div class="card">
    <div class="card-title">Energy goal</div>
    <div class="card-sub">This is used to give you gentle guidance — the number stays private.</div>

    <div id="cal-status-row" class="status-row" style="display:none">
      <span class="status-icon">✓</span>
      <span>Energy goal is set — it's kept private</span>
    </div>

    <div id="cal-no-goal" style="font-size:14px;color:var(--text2);margin-bottom:12px;display:none">
      No energy goal set yet.
    </div>

    <button class="btn btn-ghost" id="btn-change-cal" onclick="toggleCalReveal()" style="margin-top:12px">
      Change goal
    </button>

    <div class="cal-reveal" id="cal-reveal">
      <div class="field" style="margin-top:16px">
        <label>Daily energy goal (kcal)</label>
        <input type="number" id="cfg-calories" min="1000" max="5000" placeholder="e.g. 2000">
        <div class="hint">Enter your goal and save — the number will be hidden again immediately.</div>
      </div>
      <button class="btn btn-primary" onclick="saveCalGoal()">Save &amp; hide</button>
      <div class="save-msg" id="msg-cal"></div>
    </div>
  </div>

</main>

<script>
let obStep = 0;

function obNext() {
  if (obStep === 0) {
    const name = document.getElementById('ob-name').value.trim();
    if (!name) { document.getElementById('ob-name').focus(); return; }
  }
  if (obStep === 1) {
    const p = document.getElementById('ob-protein').value;
    if (!p || parseInt(p) < 40) { document.getElementById('ob-protein').focus(); return; }
  }
  obStep++;
  showObStep(obStep);
}

function obPrev() {
  obStep--;
  showObStep(obStep);
}

function showObStep(n) {
  document.querySelectorAll('.ob-step').forEach((el, i) => el.classList.toggle('active', i === n));
  document.querySelectorAll('.dot').forEach((el, i) => el.classList.toggle('active', i === n));
}

async function obFinish() {
  const name = document.getElementById('ob-name').value.trim();
  const protein = document.getElementById('ob-protein').value;
  const calories = document.getElementById('ob-calories').value;

  const updates = {
    display_name: name || 'Ebony',
    protein_goal_g: protein || '120',
    setup_complete: '1',
  };
  if (calories) updates.calorie_goal_kcal = calories;

  await fetch('/api/nutrition/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(updates),
  });

  document.getElementById('onboarding').classList.add('hidden');
  location.href = '/nutrition/today';
}

async function loadSettings() {
  const res = await fetch('/api/nutrition/config');
  const cfg = await res.json();

  if (cfg.setup_complete !== '1') {
    document.getElementById('onboarding').classList.remove('hidden');
    return;
  }
  document.getElementById('onboarding').classList.add('hidden');

  document.getElementById('cfg-name').value = cfg.display_name || '';
  document.getElementById('cfg-protein').value = cfg.protein_goal_g || 120;

  // Calorie goal — just show presence indicator, never the value
  const hasGoal = cfg.has_calorie_goal; // server returns this flag
  document.getElementById('cal-status-row').style.display = hasGoal ? 'flex' : 'none';
  document.getElementById('cal-no-goal').style.display = hasGoal ? 'none' : 'block';
}

function toggleCalReveal() {
  document.getElementById('cal-reveal').classList.toggle('open');
}

async function saveProfile() {
  const name = document.getElementById('cfg-name').value.trim();
  const protein = document.getElementById('cfg-protein').value;
  const res = await fetch('/api/nutrition/config', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({display_name: name, protein_goal_g: protein}),
  });
  const data = await res.json();
  showMsg('msg-profile', data.ok ? 'Saved ✓' : 'Error saving', !data.ok);
}

async function saveCalGoal() {
  const cal = document.getElementById('cfg-calories').value;
  if (!cal) { showMsg('msg-cal', 'Please enter a value', true); return; }
  await fetch('/api/nutrition/config', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({calorie_goal_kcal: cal}),
  });
  document.getElementById('cfg-calories').value = '';
  document.getElementById('cal-reveal').classList.remove('open');
  document.getElementById('cal-status-row').style.display = 'flex';
  document.getElementById('cal-no-goal').style.display = 'none';
  showMsg('msg-cal', 'Goal saved — it\'s kept private ✓', false);
}

function showMsg(id, msg, isErr) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.className = 'save-msg' + (isErr ? ' err' : '');
  setTimeout(() => { el.textContent = ''; }, 3000);
}

loadSettings();
</script>
</body>
</html>
```

- [ ] **Step 2: Update `/api/nutrition/config` GET to include `has_calorie_goal` flag**

In `server.py`, find the `api_nutrition_config_get` route and update it:

```python
@app.get("/api/nutrition/config")
def api_nutrition_config_get():
    from nutrition_app.db import get_config as _get_config, _get_raw_calorie_goal
    cfg = _get_config()  # calorie_goal_kcal excluded
    cfg["has_calorie_goal"] = _get_raw_calorie_goal() is not None
    return jsonify(cfg)
```

- [ ] **Step 3: Test settings page**

```bash
cd /Users/anguss/dev/finance_dash && source venv/bin/activate && python3 server.py &
sleep 1
```

Open `http://localhost:5001/nutrition/settings`

Verify:
- Onboarding overlay appears (setup_complete is 0)
- Step 0: name input, Next works
- Step 1: protein goal input, Next works
- Step 2: optional calorie goal, "Skip this step" works
- After finishing: redirects to `/nutrition/today`
- Revisiting settings: no overlay, profile fields populated, calorie status row shows "goal is set"

```bash
pkill -f "python3 server.py"
```

- [ ] **Step 4: Commit**

```bash
git add nutrition/settings.html server.py
git commit -m "feat(nutrition): settings tab with first-visit onboarding flow"
```

---

## Task 5: TODAY tab

**Files:**
- Create: `nutrition/today.html`

- [ ] **Step 1: Create nutrition/today.html**

Create `/Users/anguss/dev/finance_dash/nutrition/today.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nutrition · Today</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#faf9f7;--surface:#ffffff;--surface2:#f5f3ef;
  --border:#e8e4de;--border2:#d6d0c8;
  --text:#2d2926;--text2:#6b6560;--text3:#9b958e;
  --green:#4a7c59;--green-light:#e8f0eb;--green-mid:#6fa882;
  --amber:#c17f3a;--amber-light:#fdf3e6;
  --red:#b85450;--red-light:#fdecea;
  --radius:12px;--radius-sm:8px;
  --font:'Inter',sans-serif;
}
html,body{min-height:100%;background:var(--bg);color:var(--text);font-family:var(--font);font-size:15px;line-height:1.6}
a{color:inherit;text-decoration:none}
.app-nav{display:flex;align-items:center;border-bottom:1px solid var(--border);background:var(--surface);padding:0 20px;gap:2px;position:sticky;top:0;z-index:10}
.app-nav a{padding:14px 16px;font-size:14px;font-weight:500;color:var(--text2);border-bottom:2px solid transparent;transition:color .15s}
.app-nav a:hover{color:var(--text)}
.app-nav a.active{color:var(--green);border-bottom-color:var(--green)}
.app-nav .logo{font-weight:700;font-size:16px;color:var(--green);margin-right:12px;padding:14px 0}
.page{max-width:680px;margin:0 auto;padding:28px 20px;display:flex;flex-direction:column;gap:20px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:24px}
.card-title{font-size:17px;font-weight:600;margin-bottom:16px}
/* Hero row */
.hero{display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:center}
@media(max-width:500px){.hero{grid-template-columns:1fr}}
/* Protein ring */
.ring-wrap{display:flex;flex-direction:column;align-items:center;gap:10px}
.ring-container{position:relative;width:160px;height:160px}
.ring-svg{transform:rotate(-90deg)}
.ring-bg{fill:none;stroke:var(--surface2);stroke-width:14}
.ring-fill{fill:none;stroke-width:14;stroke-linecap:round;transition:stroke-dashoffset 0.8s ease,stroke 0.4s}
.ring-center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}
.ring-value{font-size:28px;font-weight:700;line-height:1}
.ring-unit{font-size:13px;color:var(--text2);margin-top:2px}
.ring-goal{font-size:13px;color:var(--text3)}
/* Trend */
.trend-wrap{display:flex;flex-direction:column;gap:8px}
.trend-title{font-size:13px;font-weight:500;color:var(--text2);text-transform:uppercase;letter-spacing:0.05em}
/* Calorie status */
.cal-banner{padding:14px 18px;border-radius:var(--radius-sm);background:var(--green-light);color:var(--green);font-size:15px;font-weight:500;line-height:1.5}
/* Streak */
.streak-banner{display:flex;align-items:center;gap:10px;padding:12px 16px;border-radius:var(--radius-sm);background:var(--amber-light);color:var(--amber);font-size:14px;font-weight:500}
/* Nudge */
.nudge-banner{padding:12px 16px;border-radius:var(--radius-sm);background:var(--green-light);color:var(--green);font-size:14px;line-height:1.5}
/* Meal log */
.meals-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
.meals-title{font-size:17px;font-weight:600}
.add-btn{display:inline-flex;align-items:center;gap:6px;padding:9px 18px;background:var(--green);color:#fff;border:none;border-radius:var(--radius-sm);font-family:var(--font);font-size:14px;font-weight:600;cursor:pointer;transition:background .15s}
.add-btn:hover{background:#3d6b4a}
.meal-item{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--border)}
.meal-item:last-child{border-bottom:none}
.meal-icon{font-size:22px;width:36px;text-align:center}
.meal-info{flex:1;min-width:0}
.meal-name{font-size:15px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.meal-meta{font-size:13px;color:var(--text3)}
.meal-protein{font-size:15px;font-weight:600;color:var(--green)}
.meal-del{background:none;border:none;color:var(--text3);cursor:pointer;font-size:18px;padding:4px;border-radius:6px;transition:color .15s,background .15s}
.meal-del:hover{color:var(--red);background:var(--red-light)}
.empty-state{text-align:center;padding:32px 0;color:var(--text3);font-size:14px}
.still-to-go{font-size:14px;color:var(--text2);padding:10px 0;border-top:1px solid var(--border);margin-top:8px}

/* Modal */
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,0.35);display:flex;align-items:flex-end;justify-content:center;z-index:50;padding:0}
.modal-bg.hidden{display:none}
.modal{background:var(--surface);border-radius:16px 16px 0 0;width:100%;max-width:600px;padding:28px 24px 40px;max-height:80vh;overflow-y:auto}
.modal-title{font-size:18px;font-weight:700;margin-bottom:20px}
.modal-tabs{display:flex;gap:0;border:1px solid var(--border2);border-radius:var(--radius-sm);overflow:hidden;margin-bottom:20px}
.modal-tab{flex:1;padding:9px;text-align:center;font-size:14px;font-weight:500;cursor:pointer;color:var(--text2);background:var(--surface2);border:none;font-family:var(--font);transition:background .15s,color .15s}
.modal-tab.active{background:var(--green);color:#fff}
.modal-pane{display:none}.modal-pane.active{display:block}
.recipe-list{display:flex;flex-direction:column;gap:8px;max-height:40vh;overflow-y:auto}
.recipe-pick{display:flex;align-items:center;gap:12px;padding:12px;border:1px solid var(--border);border-radius:var(--radius-sm);cursor:pointer;transition:border-color .15s,background .15s}
.recipe-pick:hover{border-color:var(--green);background:var(--green-light)}
.recipe-pick.selected{border-color:var(--green);background:var(--green-light)}
.rp-name{font-size:15px;font-weight:500;flex:1}
.rp-protein{font-size:14px;font-weight:600;color:var(--green)}
.field{margin-bottom:14px}
.field label{display:block;font-size:13px;font-weight:500;color:var(--text2);margin-bottom:5px;text-transform:uppercase;letter-spacing:.04em}
.field input,.field select{width:100%;padding:10px 12px;border:1px solid var(--border2);border-radius:var(--radius-sm);font-family:var(--font);font-size:15px;background:var(--bg);color:var(--text)}
.field input:focus,.field select:focus{outline:none;border-color:var(--green)}
.servings-row{display:flex;align-items:center;gap:10px;margin-top:12px}
.servings-row label{font-size:13px;font-weight:500;color:var(--text2)}
.servings-row input{width:70px}
.modal-footer{display:flex;gap:10px;margin-top:20px}
.btn-primary{background:var(--green);color:#fff;border:none;border-radius:var(--radius-sm);padding:11px 22px;font-family:var(--font);font-size:15px;font-weight:600;cursor:pointer}
.btn-primary:hover{background:#3d6b4a}
.btn-cancel{background:var(--surface2);color:var(--text);border:none;border-radius:var(--radius-sm);padding:11px 22px;font-family:var(--font);font-size:15px;font-weight:500;cursor:pointer}
.search-box{width:100%;padding:10px 12px;border:1px solid var(--border2);border-radius:var(--radius-sm);font-family:var(--font);font-size:15px;margin-bottom:12px;background:var(--bg)}
.search-box:focus{outline:none;border-color:var(--green)}
</style>
</head>
<body>

<nav class="app-nav">
  <span class="logo">🌿 nourish</span>
  <a href="/nutrition/today" class="active">Today</a>
  <a href="/nutrition/plan">Plan</a>
  <a href="/nutrition/recipes">Recipes</a>
  <a href="/nutrition/settings">Settings</a>
</nav>

<main class="page" id="main-page">

  <!-- Protein ring + trend -->
  <div class="card">
    <div class="hero">
      <div class="ring-wrap">
        <div class="ring-container">
          <svg class="ring-svg" width="160" height="160" viewBox="0 0 160 160">
            <circle class="ring-bg" cx="80" cy="80" r="66"/>
            <circle class="ring-fill" id="ring-fill" cx="80" cy="80" r="66"
                    stroke-dasharray="414.69" stroke-dashoffset="414.69"/>
          </svg>
          <div class="ring-center">
            <div class="ring-value" id="ring-value">0g</div>
            <div class="ring-unit">protein today</div>
            <div class="ring-goal" id="ring-goal">/ 120g goal</div>
          </div>
        </div>
      </div>
      <div class="trend-wrap">
        <div class="trend-title">7-day trend</div>
        <canvas id="trend-chart" height="120"></canvas>
      </div>
    </div>
  </div>

  <!-- Calorie status (hidden if no goal) -->
  <div class="cal-banner" id="cal-banner" style="display:none"></div>

  <!-- Streak (hidden if streak = 0) -->
  <div class="streak-banner" id="streak-banner" style="display:none">
    <span id="streak-text"></span>
  </div>

  <!-- Afternoon nudge (shown contextually) -->
  <div class="nudge-banner" id="nudge-banner" style="display:none"></div>

  <!-- Meal log -->
  <div class="card">
    <div class="meals-header">
      <div class="meals-title">Today's meals</div>
      <button class="add-btn" onclick="openModal()">+ Add meal</button>
    </div>
    <div id="meal-list"></div>
  </div>

</main>

<!-- Add meal modal -->
<div class="modal-bg hidden" id="modal-bg" onclick="closeModalOnBg(event)">
  <div class="modal" id="modal">
    <div class="modal-title">Add a meal</div>
    <div class="modal-tabs">
      <button class="modal-tab active" onclick="switchTab('recipes')">From recipes</button>
      <button class="modal-tab" onclick="switchTab('quick')">Quick add</button>
    </div>

    <!-- Recipes tab -->
    <div class="modal-pane active" id="pane-recipes">
      <input class="search-box" id="recipe-search" placeholder="Search recipes…" oninput="filterRecipes()">
      <div class="recipe-list" id="recipe-list"></div>
      <div class="servings-row" id="servings-row" style="display:none">
        <label>Servings</label>
        <input type="number" id="recipe-servings" value="1" min="0.5" step="0.5">
      </div>
    </div>

    <!-- Quick add tab -->
    <div class="modal-pane" id="pane-quick">
      <div class="field">
        <label>Name</label>
        <input type="text" id="quick-name" placeholder="e.g. Protein bar">
      </div>
      <div class="field">
        <label>Protein (g)</label>
        <input type="number" id="quick-protein" min="0" step="1" placeholder="e.g. 25">
      </div>
      <div class="field">
        <label>About how much was it?</label>
        <select id="quick-band">
          <option value="">— not sure —</option>
          <option value="snack">Light snack (small)</option>
          <option value="light">Light meal</option>
          <option value="medium">Medium meal</option>
          <option value="big">Big meal</option>
        </select>
      </div>
    </div>

    <div class="modal-footer">
      <button class="btn-primary" onclick="logMeal()">Log it</button>
      <button class="btn-cancel" onclick="closeModal()">Cancel</button>
    </div>
  </div>
</div>

<script>
let state = {goal: 120, meals: [], recipes: [], selectedRecipe: null};
let trendChart = null;
let activeTab = 'recipes';

// ── Load ───────────────────────────────────────────────────────────────────

async function loadAll() {
  const [todayRes, recipesRes] = await Promise.all([
    fetch('/api/nutrition/today'),
    fetch('/api/nutrition/recipes'),
  ]);
  const today = await todayRes.json();
  const recipes = await recipesRes.json();

  if (!today.setup_complete) {
    location.href = '/nutrition/settings';
    return;
  }

  state.goal = today.protein_goal_g || 120;
  state.meals = today.meals || [];
  state.recipes = [...(recipes.favourites || []), ...(recipes.all || [])];
  // deduplicate
  const seen = new Set();
  state.recipes = state.recipes.filter(r => {
    if (seen.has(r.id)) return false;
    seen.add(r.id); return true;
  });

  renderRing(today.total_protein_g, state.goal);
  renderTrend(today.trend, state.goal);
  renderMeals(state.meals, today.total_protein_g, state.goal);

  if (today.calorie_status) {
    const cb = document.getElementById('cal-banner');
    cb.textContent = today.calorie_status;
    cb.style.display = 'block';
  }

  if (today.streak >= 2) {
    const sb = document.getElementById('streak-banner');
    sb.style.display = 'flex';
    document.getElementById('streak-text').textContent =
      `🔥 ${today.streak}-day protein streak — keep it up!`;
  }

  // Afternoon nudge: after 2pm, less than 50% goal
  const hour = new Date().getHours();
  const pct = today.total_protein_g / state.goal;
  if (hour >= 14 && pct < 0.5) {
    const remaining = Math.round(state.goal - today.total_protein_g);
    const nb = document.getElementById('nudge-banner');
    nb.textContent = `🌿 Afternoon check-in: ${remaining}g to go — dinner could get you there`;
    nb.style.display = 'block';
  }

  renderRecipeList(state.recipes);
}

// ── Ring ───────────────────────────────────────────────────────────────────

function renderRing(protein, goal) {
  const pct = Math.min(protein / goal, 1.0);
  const circumference = 2 * Math.PI * 66; // 414.69
  const offset = circumference * (1 - pct);
  const fill = document.getElementById('ring-fill');
  fill.style.strokeDashoffset = offset;

  const colour = pct >= 1 ? '#4a7c59' : pct >= 0.7 ? '#6fa882' : pct >= 0.4 ? '#c17f3a' : '#b85450';
  fill.style.stroke = colour;

  document.getElementById('ring-value').textContent = Math.round(protein) + 'g';
  document.getElementById('ring-goal').textContent = `/ ${Math.round(goal)}g goal`;
}

// ── Trend chart ────────────────────────────────────────────────────────────

function renderTrend(trend, goal) {
  const labels = trend.map(d => {
    const day = new Date(d.date + 'T00:00:00');
    return ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][day.getDay()];
  });
  const values = trend.map(d => d.protein_g);
  const colours = values.map(v => v >= goal ? '#4a7c59' : v >= goal * 0.7 ? '#c17f3a' : '#d4c4b8');

  if (trendChart) trendChart.destroy();
  trendChart = new Chart(document.getElementById('trend-chart'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colours,
        borderRadius: 4,
        borderSkipped: false,
      }]
    },
    options: {
      responsive: true,
      plugins: {legend:{display:false}, tooltip:{
        callbacks: {label: ctx => `${ctx.raw}g protein`}
      }},
      scales: {
        x: {grid:{display:false}, ticks:{font:{size:12}}},
        y: {
          display: false,
          suggestedMax: Math.max(goal * 1.2, Math.max(...values) * 1.1)
        }
      }
    }
  });
}

// ── Meal list ──────────────────────────────────────────────────────────────

function renderMeals(meals, total, goal) {
  const el = document.getElementById('meal-list');
  if (!meals.length) {
    el.innerHTML = '<div class="empty-state">No meals logged yet — add your first one above 🌿</div>';
    return;
  }

  const icons = ['🍳','🥗','🍗','🥩','🐟','🍝','🌯','🥙','🍛','🥣','🥛','🍜'];
  let html = meals.map((m, i) => {
    const time = new Date(m.logged_at).toLocaleTimeString('en-AU', {hour:'2-digit', minute:'2-digit'});
    const icon = icons[i % icons.length];
    return `<div class="meal-item">
      <div class="meal-icon">${icon}</div>
      <div class="meal-info">
        <div class="meal-name">${escHtml(m.name || 'Meal')}</div>
        <div class="meal-meta">${time}${m.servings !== 1 ? ` · ${m.servings} servings` : ''}</div>
      </div>
      <div class="meal-protein">${Math.round(m.protein_g)}g</div>
      <button class="meal-del" onclick="deleteMeal(${m.id})" title="Remove">×</button>
    </div>`;
  }).join('');

  const remaining = goal - total;
  if (remaining > 5) {
    html += `<div class="still-to-go">Still to go: <strong>${Math.round(remaining)}g</strong> protein</div>`;
  } else if (remaining <= 0) {
    html += `<div class="still-to-go" style="color:var(--green)">✅ Protein goal hit today — great work!</div>`;
  }

  el.innerHTML = html;
}

// ── Delete meal ────────────────────────────────────────────────────────────

async function deleteMeal(id) {
  await fetch(`/api/nutrition/log/${id}`, {method: 'DELETE'});
  loadAll();
}

// ── Modal ──────────────────────────────────────────────────────────────────

function openModal() {
  document.getElementById('modal-bg').classList.remove('hidden');
  renderRecipeList(state.recipes);
}

function closeModal() {
  document.getElementById('modal-bg').classList.add('hidden');
  state.selectedRecipe = null;
  document.querySelectorAll('.recipe-pick').forEach(el => el.classList.remove('selected'));
  document.getElementById('servings-row').style.display = 'none';
  document.getElementById('recipe-search').value = '';
  document.getElementById('quick-name').value = '';
  document.getElementById('quick-protein').value = '';
  document.getElementById('quick-band').value = '';
}

function closeModalOnBg(e) {
  if (e.target === document.getElementById('modal-bg')) closeModal();
}

function switchTab(tab) {
  activeTab = tab;
  document.querySelectorAll('.modal-tab').forEach((el, i) => {
    el.classList.toggle('active', (i === 0) === (tab === 'recipes'));
  });
  document.getElementById('pane-recipes').classList.toggle('active', tab === 'recipes');
  document.getElementById('pane-quick').classList.toggle('active', tab === 'quick');
}

function renderRecipeList(recipes) {
  const el = document.getElementById('recipe-list');
  if (!recipes.length) {
    el.innerHTML = '<div style="color:var(--text3);font-size:14px;padding:12px 0">No recipes yet — add some in the Recipes tab</div>';
    return;
  }
  el.innerHTML = recipes.map(r =>
    `<div class="recipe-pick" onclick="selectRecipe(${r.id})" data-name="${escHtml(r.name).toLowerCase()}" id="rp-${r.id}">
       <div class="rp-name">${escHtml(r.name)}</div>
       <div class="rp-protein">${r.protein_per_serving_g}g protein</div>
     </div>`
  ).join('');
}

function filterRecipes() {
  const q = document.getElementById('recipe-search').value.toLowerCase();
  document.querySelectorAll('.recipe-pick').forEach(el => {
    el.style.display = el.dataset.name.includes(q) ? '' : 'none';
  });
}

function selectRecipe(id) {
  state.selectedRecipe = state.recipes.find(r => r.id === id);
  document.querySelectorAll('.recipe-pick').forEach(el => el.classList.remove('selected'));
  document.getElementById(`rp-${id}`)?.classList.add('selected');
  document.getElementById('servings-row').style.display = 'flex';
}

async function logMeal() {
  if (activeTab === 'recipes') {
    if (!state.selectedRecipe) return;
    const servings = parseFloat(document.getElementById('recipe-servings').value) || 1;
    await fetch('/api/nutrition/log', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        date: new Date().toISOString().slice(0,10),
        recipe_id: state.selectedRecipe.id,
        servings,
      })
    });
  } else {
    const name = document.getElementById('quick-name').value.trim();
    const protein = parseFloat(document.getElementById('quick-protein').value);
    const band = document.getElementById('quick-band').value;
    if (!name || isNaN(protein)) return;
    await fetch('/api/nutrition/log', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        date: new Date().toISOString().slice(0,10),
        custom_name: name,
        protein_g: protein,
        calorie_band: band || null,
      })
    });
  }
  closeModal();
  loadAll();
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

loadAll();
</script>
</body>
</html>
```

- [ ] **Step 2: Test TODAY tab end-to-end**

```bash
cd /Users/anguss/dev/finance_dash && source venv/bin/activate && python3 server.py &
sleep 1
```

Open `http://localhost:5001/nutrition/today`

Verify:
- If no setup done: redirects to `/nutrition/settings`
- After setup: ring shows 0g / goal
- Trend chart renders 7 bars
- No calorie numbers appear anywhere
- `+ Add meal` → modal opens with recipes tab
- Quick add: enter name + protein grams + band → logged → ring updates
- Recipe add: (if any recipes exist) search, select, log → ring updates
- Delete meal (×) → removes from log, ring updates
- Calorie status banner shows qualitative text (after config set)

```bash
pkill -f "python3 server.py"
```

- [ ] **Step 3: Commit**

```bash
git add nutrition/today.html
git commit -m "feat(nutrition): TODAY tab — protein ring, trend chart, meal log, qualitative calorie status"
```

---

## Task 6: RECIPES tab (basic)

**Files:**
- Create: `nutrition/recipes.html`

- [ ] **Step 1: Create nutrition/recipes.html**

Create `/Users/anguss/dev/finance_dash/nutrition/recipes.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nutrition · Recipes</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#faf9f7;--surface:#ffffff;--surface2:#f5f3ef;
  --border:#e8e4de;--border2:#d6d0c8;
  --text:#2d2926;--text2:#6b6560;--text3:#9b958e;
  --green:#4a7c59;--green-light:#e8f0eb;--green-mid:#6fa882;
  --amber:#c17f3a;--amber-light:#fdf3e6;
  --red:#b85450;--red-light:#fdecea;
  --radius:12px;--radius-sm:8px;
  --font:'Inter',sans-serif;
}
html,body{min-height:100%;background:var(--bg);color:var(--text);font-family:var(--font);font-size:15px;line-height:1.6}
a{color:inherit;text-decoration:none}
.app-nav{display:flex;align-items:center;border-bottom:1px solid var(--border);background:var(--surface);padding:0 20px;gap:2px;position:sticky;top:0;z-index:10}
.app-nav a{padding:14px 16px;font-size:14px;font-weight:500;color:var(--text2);border-bottom:2px solid transparent;transition:color .15s}
.app-nav a:hover{color:var(--text)}
.app-nav a.active{color:var(--green);border-bottom-color:var(--green)}
.app-nav .logo{font-weight:700;font-size:16px;color:var(--green);margin-right:12px;padding:14px 0}
.page{max-width:900px;margin:0 auto;padding:28px 20px}
.toolbar{display:flex;align-items:center;gap:10px;margin-bottom:20px;flex-wrap:wrap}
.search-box{flex:1;min-width:180px;padding:10px 14px;border:1px solid var(--border2);border-radius:var(--radius-sm);font-family:var(--font);font-size:15px;background:var(--surface)}
.search-box:focus{outline:none;border-color:var(--green)}
.tag-filter{display:flex;gap:6px;flex-wrap:wrap}
.tag-btn{padding:6px 12px;border:1px solid var(--border2);border-radius:20px;font-family:var(--font);font-size:13px;cursor:pointer;background:var(--surface);color:var(--text2);transition:all .15s}
.tag-btn.active{background:var(--green);color:#fff;border-color:var(--green)}
.add-btn{display:inline-flex;align-items:center;gap:6px;padding:10px 18px;background:var(--green);color:#fff;border:none;border-radius:var(--radius-sm);font-family:var(--font);font-size:14px;font-weight:600;cursor:pointer;white-space:nowrap}
.add-btn:hover{background:#3d6b4a}
.section-title{font-size:13px;font-weight:600;color:var(--text2);text-transform:uppercase;letter-spacing:.06em;margin-bottom:12px}
.recipe-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px;margin-bottom:32px}
.recipe-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:18px;cursor:pointer;transition:border-color .15s,box-shadow .15s;position:relative}
.recipe-card:hover{border-color:var(--green-mid);box-shadow:0 2px 8px rgba(74,124,89,0.1)}
.card-name{font-size:15px;font-weight:600;margin-bottom:6px;line-height:1.3}
.card-protein{font-size:22px;font-weight:700;color:var(--green);margin-bottom:4px}
.card-protein span{font-size:13px;font-weight:400;color:var(--text3)}
.card-meta{font-size:13px;color:var(--text3)}
.card-tags{display:flex;flex-wrap:wrap;gap:4px;margin-top:8px}
.card-tag{padding:2px 8px;border-radius:10px;background:var(--green-light);color:var(--green);font-size:11px;font-weight:500}
.fav-btn{position:absolute;top:12px;right:12px;background:none;border:none;font-size:18px;cursor:pointer;opacity:0.5;transition:opacity .15s}
.fav-btn:hover,.fav-btn.active{opacity:1}
.empty-state{text-align:center;padding:60px 0;color:var(--text3);font-size:15px}
/* Detail panel */
.detail-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.3);z-index:40;display:flex;justify-content:flex-end}
.detail-overlay.hidden{display:none}
.detail-panel{background:var(--surface);width:100%;max-width:480px;height:100%;overflow-y:auto;padding:28px 24px;display:flex;flex-direction:column;gap:16px}
.detail-close{background:none;border:none;font-size:22px;cursor:pointer;color:var(--text2);margin-bottom:4px;align-self:flex-start}
.detail-name{font-size:22px;font-weight:700;line-height:1.3}
.detail-protein{font-size:32px;font-weight:700;color:var(--green)}
.detail-protein span{font-size:16px;font-weight:400;color:var(--text3)}
.detail-macros{display:flex;gap:16px;font-size:14px;color:var(--text2)}
.detail-section-title{font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--text2);margin-bottom:8px}
.ingredient-row{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);font-size:14px}
.ingredient-row:last-child{border-bottom:none}
.ing-name{flex:1}
.ing-amount{color:var(--text3);margin-right:12px}
.ing-protein{font-weight:600;color:var(--green)}
.detail-actions{display:flex;gap:10px;flex-wrap:wrap}
.btn-primary{background:var(--green);color:#fff;border:none;border-radius:var(--radius-sm);padding:10px 18px;font-family:var(--font);font-size:14px;font-weight:600;cursor:pointer}
.btn-ghost{background:var(--surface2);color:var(--text);border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 18px;font-family:var(--font);font-size:14px;cursor:pointer}
.btn-danger{background:var(--red-light);color:var(--red);border:none;border-radius:var(--radius-sm);padding:10px 18px;font-family:var(--font);font-size:14px;cursor:pointer}
/* Add recipe modal */
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,0.4);display:flex;align-items:center;justify-content:center;z-index:50;padding:16px}
.modal-bg.hidden{display:none}
.modal{background:var(--surface);border-radius:var(--radius);padding:28px;width:100%;max-width:560px;max-height:90vh;overflow-y:auto}
.modal-title{font-size:19px;font-weight:700;margin-bottom:20px}
.field{margin-bottom:14px}
.field label{display:block;font-size:13px;font-weight:500;color:var(--text2);margin-bottom:5px;text-transform:uppercase;letter-spacing:.04em}
.field input,.field textarea,.field select{width:100%;padding:10px 12px;border:1px solid var(--border2);border-radius:var(--radius-sm);font-family:var(--font);font-size:15px;background:var(--bg);color:var(--text)}
.field input:focus,.field textarea:focus,.field select:focus{outline:none;border-color:var(--green)}
.field textarea{resize:vertical;min-height:80px}
.row-2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.ingredient-entry{display:grid;grid-template-columns:1fr 80px 70px 70px 24px;gap:6px;align-items:center;margin-bottom:8px}
.ingredient-entry input{padding:8px 10px;font-size:14px}
.ingredient-entry .del-ing{background:none;border:none;cursor:pointer;color:var(--text3);font-size:18px;padding:0}
.ingredient-entry .del-ing:hover{color:var(--red)}
.ing-header{display:grid;grid-template-columns:1fr 80px 70px 70px 24px;gap:6px;font-size:11px;font-weight:500;color:var(--text3);text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px}
.add-ing-btn{background:none;border:1px dashed var(--border2);border-radius:var(--radius-sm);padding:8px;width:100%;font-family:var(--font);font-size:13px;color:var(--text2);cursor:pointer;margin-bottom:14px;transition:border-color .15s,color .15s}
.add-ing-btn:hover{border-color:var(--green);color:var(--green)}
.tags-wrap{display:flex;flex-wrap:wrap;gap:6px}
.tag-toggle{padding:5px 12px;border:1px solid var(--border2);border-radius:16px;font-family:var(--font);font-size:13px;cursor:pointer;background:var(--surface);color:var(--text2);transition:all .15s}
.tag-toggle.active{background:var(--green);color:#fff;border-color:var(--green)}
.modal-footer{display:flex;gap:10px;margin-top:20px}
</style>
</head>
<body>

<nav class="app-nav">
  <span class="logo">🌿 nourish</span>
  <a href="/nutrition/today">Today</a>
  <a href="/nutrition/plan">Plan</a>
  <a href="/nutrition/recipes" class="active">Recipes</a>
  <a href="/nutrition/settings">Settings</a>
</nav>

<main class="page">
  <div class="toolbar">
    <input class="search-box" id="search" placeholder="Search recipes…" oninput="renderAll()">
    <div class="tag-filter" id="tag-filter">
      <button class="tag-btn active" data-tag="" onclick="setTag('')">All</button>
      <button class="tag-btn" data-tag="high-protein" onclick="setTag('high-protein')">High protein</button>
      <button class="tag-btn" data-tag="quick" onclick="setTag('quick')">Quick</button>
      <button class="tag-btn" data-tag="breakfast" onclick="setTag('breakfast')">Breakfast</button>
      <button class="tag-btn" data-tag="dinner" onclick="setTag('dinner')">Dinner</button>
      <button class="tag-btn" data-tag="bulk-cook" onclick="setTag('bulk-cook')">Bulk cook</button>
    </div>
    <button class="add-btn" onclick="openAddModal()">+ New recipe</button>
  </div>

  <div id="favourites-section" style="display:none">
    <div class="section-title">⭐ Favourites &amp; most used</div>
    <div class="recipe-grid" id="favourites-grid"></div>
  </div>

  <div>
    <div class="section-title" id="all-label">All recipes</div>
    <div class="recipe-grid" id="all-grid"></div>
  </div>
</main>

<!-- Recipe detail panel -->
<div class="detail-overlay hidden" id="detail-overlay" onclick="closeDetailOnBg(event)">
  <div class="detail-panel" id="detail-panel">
    <button class="detail-close" onclick="closeDetail()">✕</button>
    <div class="detail-name" id="d-name"></div>
    <div class="detail-protein" id="d-protein"></div>
    <div class="detail-macros" id="d-macros"></div>
    <div>
      <div class="detail-section-title">Ingredients</div>
      <div id="d-ingredients"></div>
    </div>
    <div id="d-instructions-wrap" style="display:none">
      <div class="detail-section-title">Instructions</div>
      <div id="d-instructions" style="font-size:14px;color:var(--text2);white-space:pre-wrap;line-height:1.7"></div>
    </div>
    <div class="detail-actions">
      <button class="btn-primary" onclick="logFromDetail()">Log today</button>
      <button class="btn-danger" onclick="deleteFromDetail()">Delete</button>
    </div>
  </div>
</div>

<!-- Add recipe modal -->
<div class="modal-bg hidden" id="add-modal-bg" onclick="closeAddOnBg(event)">
  <div class="modal">
    <div class="modal-title">Add a recipe</div>

    <div class="row-2">
      <div class="field">
        <label>Recipe name *</label>
        <input type="text" id="r-name" placeholder="e.g. Chicken & rice bowl">
      </div>
      <div class="field">
        <label>Servings</label>
        <input type="number" id="r-servings" value="1" min="1" max="20">
      </div>
    </div>

    <div class="row-2">
      <div class="field">
        <label>Total time (mins)</label>
        <input type="number" id="r-time" placeholder="e.g. 30" min="1">
      </div>
      <div class="field">
        <label>Source URL</label>
        <input type="text" id="r-url" placeholder="Optional">
      </div>
    </div>

    <div class="field">
      <label>Tags</label>
      <div class="tags-wrap" id="tag-toggles">
        <button class="tag-toggle" data-tag="high-protein" onclick="toggleTag(this)">High protein</button>
        <button class="tag-toggle" data-tag="quick" onclick="toggleTag(this)">Quick</button>
        <button class="tag-toggle" data-tag="breakfast" onclick="toggleTag(this)">Breakfast</button>
        <button class="tag-toggle" data-tag="lunch" onclick="toggleTag(this)">Lunch</button>
        <button class="tag-toggle" data-tag="dinner" onclick="toggleTag(this)">Dinner</button>
        <button class="tag-toggle" data-tag="snack" onclick="toggleTag(this)">Snack</button>
        <button class="tag-toggle" data-tag="vegetarian" onclick="toggleTag(this)">Vegetarian</button>
        <button class="tag-toggle" data-tag="bulk-cook" onclick="toggleTag(this)">Bulk cook</button>
      </div>
    </div>

    <div class="field">
      <label>Ingredients</label>
      <div class="ing-header">
        <span>Name</span><span>Amount (g)</span><span>Protein (g)</span><span>Calories</span><span></span>
      </div>
      <div id="ingredients-list"></div>
      <button class="add-ing-btn" onclick="addIngredient()">+ Add ingredient</button>
    </div>

    <div class="field">
      <label>Instructions <span style="font-weight:400;text-transform:none;font-size:12px">(optional)</span></label>
      <textarea id="r-instructions" placeholder="Step-by-step instructions…"></textarea>
    </div>

    <div class="field">
      <label>Notes <span style="font-weight:400;text-transform:none;font-size:12px">(optional)</span></label>
      <input type="text" id="r-notes" placeholder="e.g. Great for batch cooking">
    </div>

    <div class="modal-footer">
      <button class="btn-primary" onclick="saveRecipe()">Save recipe</button>
      <button class="btn-ghost" onclick="closeAddModal()">Cancel</button>
    </div>
  </div>
</div>

<script>
let allRecipes = {favourites: [], all: []};
let activeTag = '';
let detailId = null;
let ingCount = 0;

async function loadRecipes() {
  const res = await fetch('/api/nutrition/recipes');
  allRecipes = await res.json();
  renderAll();
}

function setTag(tag) {
  activeTag = tag;
  document.querySelectorAll('.tag-btn').forEach(el => el.classList.toggle('active', el.dataset.tag === tag));
  renderAll();
}

function renderAll() {
  const q = document.getElementById('search').value.toLowerCase();

  function filter(list) {
    return list.filter(r => {
      const matchTag = !activeTag || r.tags.includes(activeTag);
      const matchSearch = !q || r.name.toLowerCase().includes(q);
      return matchTag && matchSearch;
    });
  }

  const favs = filter(allRecipes.favourites || []);
  const all = filter(allRecipes.all || []);

  document.getElementById('favourites-section').style.display = favs.length ? 'block' : 'none';
  document.getElementById('favourites-grid').innerHTML = favs.map(recipeCard).join('');
  document.getElementById('all-grid').innerHTML = all.length
    ? all.map(recipeCard).join('')
    : '<div class="empty-state">No recipes yet — add your first one! 🍽️</div>';
}

function recipeCard(r) {
  const timeTxt = r.total_time_mins ? `${r.total_time_mins} min` : '';
  const tags = (r.tags || []).slice(0, 2).map(t => `<span class="card-tag">${t}</span>`).join('');
  return `<div class="recipe-card" onclick="openDetail(${r.id})">
    <button class="fav-btn ${r.is_favourite ? 'active' : ''}" onclick="event.stopPropagation();toggleFav(${r.id})" title="Favourite">
      ${r.is_favourite ? '★' : '☆'}
    </button>
    <div class="card-name">${escHtml(r.name)}</div>
    <div class="card-protein">${r.protein_per_serving_g}g <span>protein / serving</span></div>
    <div class="card-meta">${timeTxt}</div>
    ${tags ? `<div class="card-tags">${tags}</div>` : ''}
  </div>`;
}

async function openDetail(id) {
  const res = await fetch(`/api/nutrition/recipes/${id}`);
  const r = await res.json();
  detailId = id;
  document.getElementById('d-name').textContent = r.name;
  document.getElementById('d-protein').innerHTML = `${r.protein_per_serving_g}g <span>protein per serving</span>`;
  document.getElementById('d-macros').innerHTML =
    `<span>${r.carbs_per_serving_g}g carbs</span><span>${r.fat_per_serving_g}g fat</span>`;

  const ings = r.ingredients || [];
  document.getElementById('d-ingredients').innerHTML = ings.length
    ? ings.map(i => `<div class="ingredient-row">
        <span class="ing-name">${escHtml(i.food_name)}</span>
        <span class="ing-amount">${i.amount_g ? i.amount_g + 'g' : ''}</span>
        <span class="ing-protein">${i.protein_g || 0}g</span>
      </div>`).join('')
    : '<div style="color:var(--text3);font-size:14px">No ingredients recorded</div>';

  if (r.instructions) {
    document.getElementById('d-instructions').textContent = r.instructions;
    document.getElementById('d-instructions-wrap').style.display = 'block';
  } else {
    document.getElementById('d-instructions-wrap').style.display = 'none';
  }

  document.getElementById('detail-overlay').classList.remove('hidden');
}

function closeDetail() {
  document.getElementById('detail-overlay').classList.add('hidden');
  detailId = null;
}

function closeDetailOnBg(e) {
  if (e.target === document.getElementById('detail-overlay')) closeDetail();
}

async function toggleFav(id) {
  await fetch(`/api/nutrition/recipes/${id}/favourite`, {method: 'POST'});
  loadRecipes();
}

async function logFromDetail() {
  if (!detailId) return;
  const r = allRecipes.all.find(x => x.id === detailId) || allRecipes.favourites.find(x => x.id === detailId);
  await fetch('/api/nutrition/log', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      date: new Date().toISOString().slice(0,10),
      recipe_id: detailId,
      servings: 1,
    })
  });
  closeDetail();
  alert(`Logged "${r?.name}" for today! ✅`);
}

async function deleteFromDetail() {
  if (!detailId) return;
  if (!confirm('Delete this recipe?')) return;
  await fetch(`/api/nutrition/recipes/${detailId}`, {method: 'DELETE'});
  closeDetail();
  loadRecipes();
}

// ── Add recipe modal ───────────────────────────────────────────────────────

function openAddModal() {
  ingCount = 0;
  document.getElementById('ingredients-list').innerHTML = '';
  document.getElementById('r-name').value = '';
  document.getElementById('r-servings').value = '1';
  document.getElementById('r-time').value = '';
  document.getElementById('r-url').value = '';
  document.getElementById('r-instructions').value = '';
  document.getElementById('r-notes').value = '';
  document.querySelectorAll('.tag-toggle').forEach(el => el.classList.remove('active'));
  document.getElementById('add-modal-bg').classList.remove('hidden');
  addIngredient();
}

function closeAddModal() {
  document.getElementById('add-modal-bg').classList.add('hidden');
}

function closeAddOnBg(e) {
  if (e.target === document.getElementById('add-modal-bg')) closeAddModal();
}

function addIngredient() {
  const i = ingCount++;
  const row = document.createElement('div');
  row.className = 'ingredient-entry';
  row.id = `ing-${i}`;
  row.innerHTML = `
    <input type="text" placeholder="e.g. Chicken breast" id="ing-name-${i}">
    <input type="number" placeholder="200" min="0" id="ing-amt-${i}">
    <input type="number" placeholder="0" min="0" step="0.1" id="ing-prot-${i}">
    <input type="number" placeholder="0" min="0" id="ing-cal-${i}">
    <button class="del-ing" onclick="document.getElementById('ing-${i}').remove()">×</button>
  `;
  document.getElementById('ingredients-list').appendChild(row);
}

function toggleTag(btn) {
  btn.classList.toggle('active');
}

async function saveRecipe() {
  const name = document.getElementById('r-name').value.trim();
  if (!name) { document.getElementById('r-name').focus(); return; }

  const tags = [...document.querySelectorAll('.tag-toggle.active')].map(el => el.dataset.tag);

  const ingredients = [];
  for (let i = 0; i < ingCount; i++) {
    const nameEl = document.getElementById(`ing-name-${i}`);
    if (!nameEl) continue;
    const ingName = nameEl.value.trim();
    if (!ingName) continue;
    ingredients.push({
      food_name: ingName,
      amount_g: parseFloat(document.getElementById(`ing-amt-${i}`).value) || null,
      protein_g: parseFloat(document.getElementById(`ing-prot-${i}`).value) || 0,
      calories: parseFloat(document.getElementById(`ing-cal-${i}`).value) || 0,
    });
  }

  const payload = {
    name,
    servings: parseInt(document.getElementById('r-servings').value) || 1,
    total_time_mins: parseInt(document.getElementById('r-time').value) || null,
    source_url: document.getElementById('r-url').value.trim() || null,
    instructions: document.getElementById('r-instructions').value.trim() || null,
    notes: document.getElementById('r-notes').value.trim() || null,
    tags,
    ingredients,
  };

  const res = await fetch('/api/nutrition/recipes', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (data.ok) {
    closeAddModal();
    loadRecipes();
  }
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

loadRecipes();
</script>
</body>
</html>
```

- [ ] **Step 2: Test RECIPES tab end-to-end**

```bash
cd /Users/anguss/dev/finance_dash && source venv/bin/activate && python3 server.py &
sleep 1
```

Open `http://localhost:5001/nutrition/recipes`

Verify:
- Empty state shows "No recipes yet"
- `+ New recipe` opens modal
- Add a recipe: name "Chicken Rice Bowl", 2 servings, tag "high-protein" + "dinner", add 2 ingredients (chicken 200g 40g protein 250cal, rice 150g 5g protein 200cal)
- Save → card appears with `22.5g protein / serving` (45g / 2 servings)
- Click card → detail panel slides in showing ingredients, macros
- ☆ favourite button → card moves to favourites section
- "Log today" from detail → logs to today's tracker
- Delete → card removed

```bash
pkill -f "python3 server.py"
```

- [ ] **Step 3: Add a placeholder plan page so nav link doesn't 404**

Create `/Users/anguss/dev/finance_dash/nutrition/plan.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nutrition · Plan</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#faf9f7;--surface:#fff;--border:#e8e4de;--text:#2d2926;--text2:#6b6560;--green:#4a7c59;--font:'Inter',sans-serif}
html,body{min-height:100%;background:var(--bg);color:var(--text);font-family:var(--font)}
.app-nav{display:flex;align-items:center;border-bottom:1px solid var(--border);background:var(--surface);padding:0 20px;gap:2px}
.app-nav a{padding:14px 16px;font-size:14px;font-weight:500;color:var(--text2);border-bottom:2px solid transparent;text-decoration:none}
.app-nav a.active{color:var(--green);border-bottom-color:var(--green)}
.app-nav .logo{font-weight:700;font-size:16px;color:var(--green);margin-right:12px;padding:14px 0}
.coming{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:60vh;gap:12px;text-align:center;padding:40px}
.coming .emoji{font-size:48px}
.coming h2{font-size:22px;font-weight:600}
.coming p{color:var(--text2);font-size:15px;max-width:380px;line-height:1.6}
</style>
</head>
<body>
<nav class="app-nav">
  <span class="logo">🌿 nourish</span>
  <a href="/nutrition/today">Today</a>
  <a href="/nutrition/plan" class="active">Plan</a>
  <a href="/nutrition/recipes">Recipes</a>
  <a href="/nutrition/settings">Settings</a>
</nav>
<div class="coming">
  <div class="emoji">📅</div>
  <h2>Meal planner coming soon</h2>
  <p>Weekly meal planning, shopping lists, and monthly overviews — coming in Phase 2.</p>
</div>
</body>
</html>
```

- [ ] **Step 4: Commit everything**

```bash
git add nutrition/recipes.html nutrition/plan.html
git commit -m "feat(nutrition): recipes tab with card grid, detail panel, manual entry; placeholder plan page"
```

---

## Task 7: Wire up server init + final smoke test

**Files:**
- Modify: `server.py` — ensure `init_nutrition_db()` is called at startup (not just on first import)

- [ ] **Step 1: Verify init_nutrition_db is called at server startup**

Check that in `server.py`, the line:
```python
init_nutrition_db()
```
appears at module level (not inside a route). It should already be there from Task 3. If not, add it directly after the `from nutrition_app.db import init_nutrition_db` import line.

- [ ] **Step 2: Full flow smoke test**

```bash
cd /Users/anguss/dev/finance_dash && source venv/bin/activate && python3 server.py &
sleep 2
```

Run through this checklist in a browser:

1. `http://localhost:5001/nutrition` → redirects to `/nutrition/today` → shows onboarding (if fresh DB)
2. Complete onboarding: name "Ebony", protein goal 130, energy goal 2100
3. TODAY: ring shows 0g / 130g, trend chart renders, no calorie number anywhere
4. Add meal via quick add: "Protein shake", 35g protein, "Light meal"
5. Ring updates to 35g. Still-to-go shows 95g.
6. Calorie status banner shows qualitative text (not a number)
7. RECIPES: add recipe "Egg white omelette", 1 serving, breakfast + high-protein, 1 ingredient (egg whites 200g, 22g protein, 100cal)
8. Recipe card shows 22g protein/serving
9. Detail panel: "Log today" → goes back to TODAY, ring updates to 57g
10. SETTINGS: protein goal field shows 130, calorie status shows "goal is set ✓" (not the number 2100)
11. Check API directly: `curl http://localhost:5001/api/nutrition/config` — confirm `calorie_goal_kcal` is NOT in the response

```bash
pkill -f "python3 server.py"
```

- [ ] **Step 3: Commit**

```bash
git add server.py
git commit -m "chore(nutrition): verify startup init, full flow smoke tested"
```

---

## Task 8: Update requirements.txt + final commit

- [ ] **Step 1: Update requirements.txt**

No new packages are needed for Phase 1 (all dependencies are stdlib or already installed). Verify:

```bash
cd /Users/anguss/dev/finance_dash && source venv/bin/activate
python3 -c "import sqlite3, json, datetime; print('all stdlib deps ok')"
python3 -c "from flask import Flask; print('flask ok')"
```

Expected: both print ok.

- [ ] **Step 2: Final commit + push**

```bash
git add -A
git status  # confirm no unexpected files
git commit -m "feat(nutrition): Phase 1 complete — TODAY, RECIPES, SETTINGS tabs + SQLite schema"
git push origin feature/nutrition-app
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| 5 new SQLite tables | Task 1 |
| Calorie goal write-only, never returned by GET | Task 2 (`get_config` excludes it), Task 3 (`has_calorie_goal` flag) |
| Qualitative calorie tiers (6 phrases) | Task 2 (`calorie_status_string`) |
| Protein ring + 7-day trend | Task 5 |
| Protein streak | Task 2 + Task 5 |
| Afternoon nudge | Task 5 |
| Add meal: from recipe + quick add with calorie band | Task 5 |
| RECIPES: card grid, favourites/most-used section | Task 6 |
| RECIPES: manual entry form with ingredients | Task 6 |
| Recipe detail panel with macros (no calories) | Task 6 |
| SETTINGS: onboarding flow | Task 4 |
| SETTINGS: protein goal visible, calorie goal hidden | Task 4 |
| First-visit setup flow | Task 4 |
| `/nutrition` redirects to `/nutrition/today` | Task 3 |
| Plan tab placeholder (no 404) | Task 6 |

**Phase 2 items NOT in this plan (by design):**
- URL recipe scraping (recipe-scrapers library)
- Open Food Facts ingredient lookup
- Protein streaks "weekly wins" summary
- Recipe of the day
- MacroFactor recipe CSV import

**Placeholder scan:** No TBDs found. All code blocks complete.

**Type consistency:**
- `get_config()` in `db.py` excludes `calorie_goal_kcal` ✓
- `_get_raw_calorie_goal()` is only called from `queries.py::calorie_status_string()` ✓
- `log_meal()` signature matches call in `api_nutrition_log` route ✓
- `create_recipe(data)` dict keys match what `saveRecipe()` JS sends ✓
- `list_recipes()` returns `protein_per_serving_g` — matches what `today.html` reads ✓
