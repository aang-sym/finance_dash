"""
Streaming parser for Apple Health native XML export (export.xml).

Apple exports a zip containing:
  export.xml          — all health records (can be 1–5 GB)
  export_cda.xml      — clinical summary (small, skip)
  electrocardiograms/ — one CSV per ECG
  workout-routes/     — one GPX per workout route

All timestamps in Apple Health XML are local time with offset, e.g.
  "2024-06-05 18:12:54 +1000"
We normalise everything to UTC ISO8601.

Uses iterparse for streaming — safe on files of any size.
"""
import csv
import io
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from health_pipeline.db import get_conn, init_db

# ── Timestamp normalisation ───────────────────────────────────────────────────

def _to_utc(s: str) -> Optional[str]:
    """Parse Apple Health datetime string → UTC ISO8601."""
    if not s:
        return None
    try:
        # Format: "2024-06-05 18:12:54 +1000"
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z")
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return s[:19].replace(" ", "T") + "Z"


def _date_only(s: str) -> Optional[str]:
    if not s:
        return None
    return s[:10]


# ── GPX route parser ──────────────────────────────────────────────────────────

_GPX_NS = {"gpx": "http://www.topografix.com/GPX/1/1"}


def _parse_gpx(content: bytes, route_filename: str, conn) -> int:
    """Parse a GPX file and insert into workout_routes / workout_route_points."""
    # Ensure tables exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workout_routes (
            id INTEGER PRIMARY KEY,
            route_id TEXT UNIQUE NOT NULL,
            start_ts TEXT,
            end_ts TEXT,
            point_count INTEGER,
            avg_speed_ms REAL,
            distance_km REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workout_route_points (
            id INTEGER PRIMARY KEY,
            route_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            speed_ms REAL,
            elevation REAL,
            course REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_route_points_route ON workout_route_points(route_id)")

    route_id = Path(route_filename).stem
    if conn.execute("SELECT id FROM workout_routes WHERE route_id=?", (route_id,)).fetchone():
        return 0  # already imported

    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return 0

    ns = _GPX_NS
    points = []
    for trkpt in root.findall(".//gpx:trkpt", ns):
        lat = float(trkpt.get("lat", 0))
        lon = float(trkpt.get("lon", 0))
        ele_el = trkpt.find("gpx:ele", ns)
        time_el = trkpt.find("gpx:time", ns)
        ext = trkpt.find(".//gpx:speed", ns)
        elevation = float(ele_el.text) if ele_el is not None else None
        ts = _to_utc(time_el.text.replace("T", " ").replace("Z", " +0000")) if time_el is not None else None
        speed = float(ext.text) if ext is not None else None
        if lat and lon:
            points.append((route_id, ts, lat, lon, speed, elevation, None))

    if not points:
        return 0

    start_ts = points[0][1]
    end_ts = points[-1][1]
    speeds = [p[4] for p in points if p[4] and p[4] > 0]
    avg_speed = round(sum(speeds) / len(speeds), 3) if speeds else None

    # Estimate distance using Haversine
    distance_km = 0.0
    for i in range(1, len(points)):
        la1, lo1 = math.radians(points[i-1][2]), math.radians(points[i-1][3])
        la2, lo2 = math.radians(points[i][2]), math.radians(points[i][3])
        dlat, dlon = la2 - la1, lo2 - lo1
        a = math.sin(dlat/2)**2 + math.cos(la1)*math.cos(la2)*math.sin(dlon/2)**2
        distance_km += 6371 * 2 * math.asin(math.sqrt(a))
    distance_km = round(distance_km, 3)

    conn.execute(
        "INSERT OR IGNORE INTO workout_routes (route_id, start_ts, end_ts, point_count, avg_speed_ms, distance_km) VALUES (?,?,?,?,?,?)",
        (route_id, start_ts, end_ts, len(points), avg_speed, distance_km)
    )
    conn.executemany(
        "INSERT INTO workout_route_points (route_id, ts, lat, lon, speed_ms, elevation, course) VALUES (?,?,?,?,?,?,?)",
        points
    )
    return 1


# ── ECG CSV parser ────────────────────────────────────────────────────────────

def _parse_ecg_csv(content: bytes, filename: str, conn) -> int:
    """Parse Apple ECG CSV → ecg_results table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ecg_results (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL,
            hr_bpm REAL,
            qtc_ms REAL,
            qt_ms REAL,
            rr_ms REAL,
            p_ms REAL,
            pq_ms REAL,
            qrs_ms REAL,
            p_axis_deg REAL,
            qrs_axis_deg REAL,
            t_axis_deg REAL,
            rhythm TEXT,
            interpretation TEXT,
            source_file TEXT
        )
    """)

    text = content.decode("utf-8", errors="replace")
    lines = text.splitlines()

    recorded_date = None
    classification = None
    hr = None
    for line in lines[:20]:
        if line.startswith("Recorded Date"):
            parts = line.split(",", 1)
            if len(parts) > 1:
                recorded_date = _to_utc(parts[1].strip().strip('"').replace("T", " ").replace("Z", " +0000"))
                if recorded_date:
                    recorded_date = recorded_date[:10]
        elif line.startswith("Classification"):
            parts = line.split(",", 1)
            if len(parts) > 1:
                classification = parts[1].strip().strip('"')
        elif "Heart Rate" in line or line.startswith("Heart Rate"):
            parts = line.split(",")
            for p in parts:
                try:
                    hr = float(p.strip())
                    break
                except ValueError:
                    pass

    if not recorded_date:
        # Parse from filename: ecg_2021-06-21.csv
        m = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
        if m:
            recorded_date = m.group(1)

    if not recorded_date:
        return 0

    existing = conn.execute("SELECT id FROM ecg_results WHERE date=? AND source_file=?",
                            (recorded_date, Path(filename).name)).fetchone()
    if existing:
        return 0

    conn.execute(
        "INSERT INTO ecg_results (date, hr_bpm, rhythm, interpretation, source_file) VALUES (?,?,?,?,?)",
        (recorded_date, hr, classification, classification, Path(filename).name)
    )
    return 1


# ── Main XML record handlers ──────────────────────────────────────────────────

def _batch_insert(conn, table: str, cols: list, rows: list):
    if not rows:
        return
    ph = ",".join("?" * len(cols))
    conn.executemany(f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({ph})", rows)


def parse_apple_xml(xml_path: Path, progress_cb=None) -> dict:
    """
    Stream-parse Apple Health export.xml and import all supported record types.
    Returns counts dict.
    """
    init_db()
    conn = get_conn()

    counts = defaultdict(int)
    BATCH = 5000

    # Buffers for batch inserts
    bufs = {
        "heart_rate_samples": [],
        "resting_hr": [],
        "hrv_samples": [],
        "blood_oxygen": [],
        "respiratory_rate": [],
        "step_samples": [],
        "active_energy": [],
        "body_measurements_weight": [],   # interim
        "body_measurements_fat": [],
        "body_measurements_lean": [],
        "body_measurements_waist": [],
        "vo2_max": [],
        "sleep_segments": [],
        "nutrition_calories": [],
        "nutrition_protein": [],
        "nutrition_carbs": [],
        "nutrition_fat": [],
        "nutrition_fiber": [],
        "nutrition_sodium": [],
        "nutrition_potassium": [],
        "nutrition_magnesium": [],
        "nutrition_calcium": [],
        "nutrition_iron": [],
        "nutrition_vitd": [],
        "nutrition_zinc": [],
        "nutrition_caffeine": [],
        "workouts": [],
        "hr_recovery": [],
    }

    def flush(key=None):
        keys = [key] if key else list(bufs.keys())
        for k in keys:
            if not bufs[k]:
                continue
            if k == "heart_rate_samples":
                _batch_insert(conn, "heart_rate_samples", ["ts","avg_bpm","source"], bufs[k])
            elif k == "resting_hr":
                conn.executemany(
                    "INSERT OR IGNORE INTO resting_hr (date, qty_bpm, source) VALUES (?,?,?)",
                    bufs[k]
                )
            elif k == "hrv_samples":
                _batch_insert(conn, "hrv_samples", ["ts","qty_ms","source"], bufs[k])
            elif k == "blood_oxygen":
                _batch_insert(conn, "blood_oxygen", ["ts","qty_pct","source"], bufs[k])
            elif k == "respiratory_rate":
                _batch_insert(conn, "respiratory_rate", ["ts","qty_bpm","source"], bufs[k])
            elif k == "step_samples":
                _batch_insert(conn, "step_samples", ["ts","qty","source"], bufs[k])
            elif k == "active_energy":
                _batch_insert(conn, "active_energy", ["ts","qty_kcal","source"], bufs[k])
            elif k == "vo2_max":
                conn.executemany(
                    "INSERT OR IGNORE INTO vo2_max (date, qty, source) VALUES (?,?,?)",
                    bufs[k]
                )
            elif k == "sleep_segments":
                _batch_insert(conn, "sleep_segments", ["start_ts","end_ts","stage","source"], bufs[k])
            elif k in ("body_measurements_weight", "body_measurements_fat",
                       "body_measurements_lean", "body_measurements_waist"):
                for row in bufs[k]:
                    d, val, col = row
                    existing = conn.execute(
                        "SELECT id FROM body_measurements WHERE date=?", (d,)
                    ).fetchone()
                    if existing:
                        conn.execute(f"UPDATE body_measurements SET {col}=? WHERE date=? AND {col} IS NULL",
                                     (val, d))
                    else:
                        conn.execute(f"INSERT INTO body_measurements (date, {col}) VALUES (?,?)",
                                     (d, val))
            elif k == "hr_recovery":
                # HR recovery from standalone records (not linked to a specific workout)
                # Store in a separate table to avoid FK violation
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS hr_recovery_samples (
                        id INTEGER PRIMARY KEY,
                        ts TEXT NOT NULL UNIQUE,
                        hr_bpm REAL NOT NULL
                    )
                """)
                conn.executemany(
                    "INSERT OR IGNORE INTO hr_recovery_samples (ts, hr_bpm) VALUES (?,?)",
                    bufs[k]
                )
            # Nutrition — upsert into nutrition_log by date
            elif k.startswith("nutrition_"):
                col_map = {
                    "nutrition_calories": "calories",
                    "nutrition_protein": "protein_g",
                    "nutrition_carbs": "carbs_g",
                    "nutrition_fat": "fat_g",
                    "nutrition_fiber": "fiber_g",
                    "nutrition_sodium": "sodium_mg",
                    "nutrition_potassium": "potassium_mg",
                    "nutrition_magnesium": "magnesium_mg",
                    "nutrition_calcium": "calcium_mg",
                    "nutrition_iron": "iron_mg",
                    "nutrition_vitd": "vitamin_d_mcg",
                    "nutrition_zinc": "zinc_mg",
                    "nutrition_caffeine": "caffeine_mg",
                }
                col = col_map.get(k)
                if col:
                    for d, val, food_name in bufs[k]:
                        existing = conn.execute(
                            "SELECT id FROM nutrition_log WHERE date=? AND food_name=?", (d, food_name)
                        ).fetchone()
                        if existing:
                            conn.execute(f"UPDATE nutrition_log SET {col}=coalesce({col},0)+? WHERE id=?",
                                         (val, existing["id"]))
                        else:
                            conn.execute(
                                f"INSERT INTO nutrition_log (date, food_name, {col}) VALUES (?,?,?)",
                                (d, food_name, val)
                            )
            bufs[k] = []

    # Sleep stage mapping
    SLEEP_STAGE = {
        "HKCategoryValueSleepAnalysisInBed": "InBed",
        "HKCategoryValueSleepAnalysisAsleep": "Core",
        "HKCategoryValueSleepAnalysisAsleepCore": "Core",
        "HKCategoryValueSleepAnalysisAsleepREM": "REM",
        "HKCategoryValueSleepAnalysisAsleepDeep": "Deep",
        "HKCategoryValueSleepAnalysisAwake": "Awake",
    }

    total = 0
    for event, elem in ET.iterparse(str(xml_path), events=["start"]):
        if elem.tag not in ("Record", "Workout"):
            elem.clear()
            continue

        t = elem.get("type", "")
        src = elem.get("sourceName", "")
        val = elem.get("value", "")
        start = _to_utc(elem.get("startDate", ""))
        end = _to_utc(elem.get("endDate", ""))
        d = _date_only(elem.get("startDate", ""))

        try:
            fval = float(val) if val else None
        except ValueError:
            fval = None

        if t == "HKQuantityTypeIdentifierHeartRate" and fval and start:
            bufs["heart_rate_samples"].append((start, fval, src))
            counts["heart_rate"] += 1

        elif t == "HKQuantityTypeIdentifierRestingHeartRate" and fval and d:
            bufs["resting_hr"].append((d, fval, src))
            counts["resting_hr"] += 1

        elif t == "HKQuantityTypeIdentifierHeartRateVariabilitySDNN" and fval and start:
            bufs["hrv_samples"].append((start, fval, src))
            counts["hrv"] += 1

        elif t == "HKQuantityTypeIdentifierOxygenSaturation" and fval and start:
            bufs["blood_oxygen"].append((start, fval * 100 if fval < 2 else fval, src))
            counts["blood_oxygen"] += 1

        elif t == "HKQuantityTypeIdentifierRespiratoryRate" and fval and start:
            bufs["respiratory_rate"].append((start, fval, src))
            counts["respiratory_rate"] += 1

        elif t == "HKQuantityTypeIdentifierStepCount" and fval and start:
            bufs["step_samples"].append((start, fval, src))
            counts["steps"] += 1

        elif t == "HKQuantityTypeIdentifierActiveEnergyBurned" and fval and start:
            bufs["active_energy"].append((start, fval, src))
            counts["active_energy"] += 1

        elif t == "HKQuantityTypeIdentifierVO2Max" and fval and d:
            bufs["vo2_max"].append((d, fval, src))
            counts["vo2_max"] += 1

        elif t == "HKCategoryTypeIdentifierSleepAnalysis" and start and end:
            stage = SLEEP_STAGE.get(val, val)
            bufs["sleep_segments"].append((start, end, stage, src))
            counts["sleep"] += 1

        elif t == "HKQuantityTypeIdentifierBodyMass" and fval and d:
            bufs["body_measurements_weight"].append((d, round(fval, 2), "body_weight_kg"))
            counts["body_weight"] += 1

        elif t == "HKQuantityTypeIdentifierBodyFatPercentage" and fval and d:
            # Apple stores as fraction (0.22 = 22%) — convert
            pct = round(fval * 100 if fval < 1.0 else fval, 1)
            bufs["body_measurements_fat"].append((d, pct, "body_fat_pct"))
            counts["body_fat"] += 1

        elif t == "HKQuantityTypeIdentifierLeanBodyMass" and fval and d:
            bufs["body_measurements_lean"].append((d, round(fval, 2), "lean_mass_kg"))
            counts["lean_mass"] += 1

        elif t == "HKQuantityTypeIdentifierWaistCircumference" and fval and d:
            # Apple stores in metres — convert to cm
            cm = round(fval * 100 if fval < 5 else fval, 1)
            bufs["body_measurements_waist"].append((d, cm, "waist_cm"))
            counts["waist"] += 1

        elif t == "HKQuantityTypeIdentifierHeartRateRecoveryOneMinute" and fval and start:
            bufs["hr_recovery"].append((start, fval))
            counts["hr_recovery"] += 1

        elif t == "HKQuantityTypeIdentifierDietaryEnergyConsumed" and fval and d:
            food = elem.get("sourceName", "Apple Health")
            bufs["nutrition_calories"].append((d, fval, food))
            counts["nutrition"] += 1

        elif t == "HKQuantityTypeIdentifierDietaryProtein" and fval and d:
            bufs["nutrition_protein"].append((d, fval, elem.get("sourceName", "Apple Health")))

        elif t == "HKQuantityTypeIdentifierDietaryCarbohydrates" and fval and d:
            bufs["nutrition_carbs"].append((d, fval, elem.get("sourceName", "Apple Health")))

        elif t == "HKQuantityTypeIdentifierDietaryFatTotal" and fval and d:
            bufs["nutrition_fat"].append((d, fval, elem.get("sourceName", "Apple Health")))

        elif t == "HKQuantityTypeIdentifierDietaryFiber" and fval and d:
            bufs["nutrition_fiber"].append((d, fval, elem.get("sourceName", "Apple Health")))

        elif t == "HKQuantityTypeIdentifierDietarySodium" and fval and d:
            bufs["nutrition_sodium"].append((d, fval * 1000 if fval < 10 else fval, elem.get("sourceName", "")))

        elif t == "HKQuantityTypeIdentifierDietaryPotassium" and fval and d:
            bufs["nutrition_potassium"].append((d, fval * 1000 if fval < 10 else fval, elem.get("sourceName", "")))

        elif t == "HKQuantityTypeIdentifierDietaryMagnesium" and fval and d:
            bufs["nutrition_magnesium"].append((d, fval * 1000 if fval < 10 else fval, elem.get("sourceName", "")))

        elif t == "HKQuantityTypeIdentifierDietaryCalcium" and fval and d:
            bufs["nutrition_calcium"].append((d, fval * 1000 if fval < 10 else fval, elem.get("sourceName", "")))

        elif t == "HKQuantityTypeIdentifierDietaryIron" and fval and d:
            bufs["nutrition_iron"].append((d, fval * 1000 if fval < 10 else fval, elem.get("sourceName", "")))

        elif t == "HKQuantityTypeIdentifierDietaryVitaminD" and fval and d:
            bufs["nutrition_vitd"].append((d, fval * 1000000 if fval < 0.001 else fval, elem.get("sourceName", "")))

        elif t == "HKQuantityTypeIdentifierDietaryZinc" and fval and d:
            bufs["nutrition_zinc"].append((d, fval * 1000 if fval < 10 else fval, elem.get("sourceName", "")))

        elif t == "HKQuantityTypeIdentifierDietaryCaffeine" and fval and d:
            bufs["nutrition_caffeine"].append((d, fval * 1000 if fval < 10 else fval, elem.get("sourceName", "")))

        total += 1

        # Flush batches
        for key, buf in bufs.items():
            if len(buf) >= BATCH:
                flush(key)
                conn.commit()

        if progress_cb and total % 100000 == 0:
            progress_cb(total, counts)

        elem.clear()

    # Final flush
    flush()
    conn.commit()
    conn.close()

    return dict(counts)


def parse_apple_xml_zip(zip_path: Path, progress_cb=None) -> dict:
    """
    Accept either a .zip (Apple's export format) or a raw export.xml path.
    Extracts to a temp location if zip, then parses.
    Also processes ECG CSVs and GPX routes found in the zip.
    """
    import tempfile, shutil

    if zip_path.suffix == ".zip":
        tmp = Path(tempfile.mkdtemp())
        try:
            with zipfile.ZipFile(str(zip_path), "r") as zf:
                zf.extractall(str(tmp))
            # Find export.xml
            xml_candidates = list(tmp.rglob("export.xml"))
            if not xml_candidates:
                return {"error": "No export.xml found in zip"}
            xml_path = xml_candidates[0]
            base = xml_path.parent

            # Parse routes and ECGs first (fast)
            conn = get_conn()
            route_count = 0
            for gpx in (base / "workout-routes").glob("*.gpx") if (base / "workout-routes").exists() else []:
                route_count += _parse_gpx(gpx.read_bytes(), gpx.name, conn)
            ecg_count = 0
            for ecg in (base / "electrocardiograms").glob("*.csv") if (base / "electrocardiograms").exists() else []:
                ecg_count += _parse_ecg_csv(ecg.read_bytes(), ecg.name, conn)
            conn.commit()
            conn.close()

            counts = parse_apple_xml(xml_path, progress_cb)
            counts["routes"] = route_count
            counts["ecg_files"] = ecg_count
            return counts
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
    else:
        return parse_apple_xml(zip_path, progress_cb)
