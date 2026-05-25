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
    Each recipe dict includes per-serving protein totals.
    Calories are excluded from the returned dicts.
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
