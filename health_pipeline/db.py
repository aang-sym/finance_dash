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


def init_db() -> None:
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS hrv_samples (
            id INTEGER PRIMARY KEY,
            ts TEXT NOT NULL,
            qty_ms REAL NOT NULL,
            source TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_hrv_ts ON hrv_samples(ts);

        CREATE TABLE IF NOT EXISTS resting_hr (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL,
            qty_bpm REAL NOT NULL,
            source TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_rhr_date ON resting_hr(date);

        CREATE TABLE IF NOT EXISTS heart_rate_samples (
            id INTEGER PRIMARY KEY,
            ts TEXT NOT NULL,
            min_bpm REAL,
            avg_bpm REAL,
            max_bpm REAL,
            context TEXT,
            source TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_hr_ts ON heart_rate_samples(ts);

        CREATE TABLE IF NOT EXISTS sleep_segments (
            id INTEGER PRIMARY KEY,
            start_ts TEXT NOT NULL,
            end_ts TEXT NOT NULL,
            stage TEXT NOT NULL,
            source TEXT,
            qty_hrs REAL
        );
        CREATE INDEX IF NOT EXISTS idx_sleep_start ON sleep_segments(start_ts);

        CREATE TABLE IF NOT EXISTS respiratory_rate (
            id INTEGER PRIMARY KEY,
            ts TEXT NOT NULL,
            qty_bpm REAL NOT NULL,
            source TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_resp_ts ON respiratory_rate(ts);

        CREATE TABLE IF NOT EXISTS blood_oxygen (
            id INTEGER PRIMARY KEY,
            ts TEXT NOT NULL,
            qty_pct REAL NOT NULL,
            source TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_spo2_ts ON blood_oxygen(ts);

        CREATE TABLE IF NOT EXISTS vo2_max (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL,
            qty REAL NOT NULL,
            source TEXT
        );

        CREATE TABLE IF NOT EXISTS step_samples (
            id INTEGER PRIMARY KEY,
            ts TEXT NOT NULL,
            qty REAL NOT NULL,
            source TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_steps_ts ON step_samples(ts);

        CREATE TABLE IF NOT EXISTS active_energy (
            id INTEGER PRIMARY KEY,
            ts TEXT NOT NULL,
            qty_kcal REAL NOT NULL,
            source TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_energy_ts ON active_energy(ts);

        CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY,
            external_id TEXT UNIQUE,
            name TEXT,
            start_ts TEXT NOT NULL,
            end_ts TEXT NOT NULL,
            duration_s REAL,
            avg_hr REAL,
            max_hr REAL,
            active_kcal REAL,
            distance_km REAL,
            location TEXT,
            is_indoor INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_workout_start ON workouts(start_ts);

        CREATE TABLE IF NOT EXISTS workout_hr (
            id INTEGER PRIMARY KEY,
            workout_id INTEGER NOT NULL REFERENCES workouts(id),
            ts TEXT NOT NULL,
            min_bpm REAL,
            avg_bpm REAL,
            max_bpm REAL
        );

        CREATE TABLE IF NOT EXISTS workout_hr_recovery (
            id INTEGER PRIMARY KEY,
            workout_id INTEGER NOT NULL REFERENCES workouts(id),
            ts TEXT NOT NULL,
            hr_bpm REAL
        );

        CREATE TABLE IF NOT EXISTS nutrition_log (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL,
            time TEXT,
            food_name TEXT,
            serving_weight_g REAL,
            calories REAL,
            fat_g REAL,
            carbs_g REAL,
            protein_g REAL,
            alcohol_g REAL,
            caffeine_mg REAL,
            fiber_g REAL,
            sodium_mg REAL,
            potassium_mg REAL,
            magnesium_mg REAL,
            calcium_mg REAL,
            iron_mg REAL,
            vitamin_d_mcg REAL,
            zinc_mg REAL
        );
        CREATE INDEX IF NOT EXISTS idx_nutr_date ON nutrition_log(date);

        CREATE TABLE IF NOT EXISTS workout_sets (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL,
            workout_name TEXT,
            duration_s REAL,
            exercise TEXT,
            base_weight_kg REAL,
            set_type TEXT,
            weight_kg REAL,
            reps REAL,
            rir REAL
        );
        CREATE INDEX IF NOT EXISTS idx_sets_date ON workout_sets(date);

        CREATE TABLE IF NOT EXISTS import_log (
            id INTEGER PRIMARY KEY,
            source TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            record_count INTEGER,
            date_from TEXT,
            date_to TEXT,
            filename TEXT
        );

        CREATE TABLE IF NOT EXISTS health_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        INSERT OR IGNORE INTO health_config(key, value) VALUES
            ('hr_max', '170'),
            ('sleep_goal_hrs', '8.0'),
            ('sleep_source_preference', 'Angus''s Apple Watch');
        CREATE TABLE IF NOT EXISTS body_measurements (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL,
            body_weight_kg REAL,
            body_fat_pct REAL,
            chest_cm REAL,
            waist_cm REAL,
            hip_cm REAL,
            left_arm_cm REAL,
            right_arm_cm REAL,
            left_thigh_cm REAL,
            right_thigh_cm REAL,
            notes TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_measurements_date ON body_measurements(date);
    """)
    conn.commit()
    conn.close()
