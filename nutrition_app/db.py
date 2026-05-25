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
