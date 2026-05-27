"""
Parser for Health Auto Export .hae files (lzfse-compressed JSON).

AutoSync folder structure:
  AutoSync/HealthMetrics/<metric_name>/<YYYYMMDD>.hae  — daily metric files
  AutoSync/Routes/<UUID>.hae                            — GPS walk routes

Apple's Core Data epoch: 2001-01-01 00:00:00 UTC = Unix 978307200
All timestamps in .hae are seconds since Apple epoch.
"""
import json
import subprocess
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Optional

from health_pipeline.db import get_conn

APPLE_EPOCH = 978307200  # seconds between Unix epoch and Apple epoch (2001-01-01)

AUTOSYNC_DIR = Path(
    "/Users/anguss/Library/Mobile Documents/iCloud~com~ifunography~HealthExport/Documents/AutoSync"
)
METRICS_DIR = AUTOSYNC_DIR / "HealthMetrics"
ROUTES_DIR = AUTOSYNC_DIR / "Routes"


def _decode_hae(path: Path) -> Optional[dict]:
    """Decompress lzfse .hae file → parsed JSON dict."""
    result = subprocess.run(
        ["compression_tool", "-decode", "-i", str(path), "-o", "/dev/stdout", "-a", "lzfse"],
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _apple_ts_to_iso(apple_ts: float) -> str:
    """Convert Apple epoch timestamp → ISO8601 UTC string."""
    return datetime.fromtimestamp(apple_ts + APPLE_EPOCH, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _apple_ts_to_date(apple_ts: float) -> str:
    """Convert Apple epoch timestamp → date string YYYY-MM-DD."""
    return datetime.fromtimestamp(apple_ts + APPLE_EPOCH, tz=timezone.utc).strftime("%Y-%m-%d")


# ── Weight ────────────────────────────────────────────────────────────────────

def import_weight_hae() -> int:
    """
    Import all weight_body_mass .hae files into body_measurements table.
    Uses daily average when multiple readings exist for one day.
    Returns number of rows inserted/updated.
    """
    metric_dir = METRICS_DIR / "weight_body_mass"
    if not metric_dir.exists():
        return 0

    # Collect all kg readings by date
    daily: dict[str, list[float]] = {}
    for hae_file in sorted(metric_dir.glob("*.hae")):
        data = _decode_hae(hae_file)
        if not data:
            continue
        for item in data.get("data", []):
            if item.get("unit") != "kg":
                continue
            d = _apple_ts_to_date(item["start"])
            qty = item.get("qty")
            if qty and qty > 30:  # sanity check — exclude clearly wrong readings
                daily.setdefault(d, []).append(qty)

    if not daily:
        return 0

    conn = get_conn()
    count = 0
    for d, weights in daily.items():
        avg_kg = round(sum(weights) / len(weights), 2)
        # Upsert: insert if no row for that date, update weight if it exists
        existing = conn.execute(
            "SELECT id, body_weight_kg FROM body_measurements WHERE date=?", (d,)
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO body_measurements (date, body_weight_kg) VALUES (?,?)",
                (d, avg_kg),
            )
            count += 1
        elif existing["body_weight_kg"] is None:
            conn.execute(
                "UPDATE body_measurements SET body_weight_kg=? WHERE date=?",
                (avg_kg, d),
            )
            count += 1
        # If weight already logged manually, don't overwrite

    conn.commit()
    conn.close()
    return count


# ── Routes (GPS walks) ────────────────────────────────────────────────────────

def import_routes_hae() -> int:
    """
    Import GPS route .hae files into a new workout_routes table.
    Each route is a sequence of (ts, lat, lon, speed) points.
    Returns number of route files imported.
    """
    if not ROUTES_DIR.exists():
        return 0

    conn = get_conn()

    # Ensure table exists
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
            route_id TEXT NOT NULL REFERENCES workout_routes(route_id),
            ts TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            speed_ms REAL,
            elevation REAL,
            course REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_route_points_route ON workout_route_points(route_id)")
    conn.commit()

    count = 0
    for hae_file in sorted(ROUTES_DIR.glob("*.hae")):
        route_id = hae_file.stem
        # Skip already imported
        existing = conn.execute(
            "SELECT id FROM workout_routes WHERE route_id=?", (route_id,)
        ).fetchone()
        if existing:
            continue

        data = _decode_hae(hae_file)
        if not data:
            continue

        locations = data.get("locations", [])
        if not locations:
            continue

        # Convert timestamps
        points = []
        for loc in locations:
            t = loc.get("time")
            if t is None:
                continue
            points.append({
                "ts": _apple_ts_to_iso(t),
                "lat": loc.get("latitude"),
                "lon": loc.get("longitude"),
                "speed_ms": loc.get("speed"),
                "elevation": loc.get("elevation"),
                "course": loc.get("course"),
            })

        if not points:
            continue

        start_ts = points[0]["ts"]
        end_ts = points[-1]["ts"]
        speeds = [p["speed_ms"] for p in points if p["speed_ms"] and p["speed_ms"] > 0]
        avg_speed = round(sum(speeds) / len(speeds), 3) if speeds else None

        # Estimate distance from speed × time (rough)
        distance_km = None
        if len(points) >= 2:
            try:
                from datetime import datetime as _dt
                total_dist = 0.0
                for i in range(1, len(points)):
                    t1 = _dt.fromisoformat(points[i-1]["ts"].replace("Z", "+00:00"))
                    t2 = _dt.fromisoformat(points[i]["ts"].replace("Z", "+00:00"))
                    dt_s = (t2 - t1).total_seconds()
                    avg_s = ((points[i-1]["speed_ms"] or 0) + (points[i]["speed_ms"] or 0)) / 2
                    total_dist += avg_s * dt_s
                distance_km = round(total_dist / 1000, 3)
            except Exception:
                pass

        conn.execute(
            "INSERT OR IGNORE INTO workout_routes (route_id, start_ts, end_ts, point_count, avg_speed_ms, distance_km) VALUES (?,?,?,?,?,?)",
            (route_id, start_ts, end_ts, len(points), avg_speed, distance_km),
        )
        conn.executemany(
            "INSERT INTO workout_route_points (route_id, ts, lat, lon, speed_ms, elevation, course) VALUES (?,?,?,?,?,?,?)",
            [(route_id, p["ts"], p["lat"], p["lon"], p["speed_ms"], p["elevation"], p["course"]) for p in points],
        )
        count += 1

    conn.commit()
    conn.close()
    return count


# ── Convenience: import all AutoSync data ─────────────────────────────────────

def import_autosync_all() -> dict:
    """Import all supported .hae metrics. Returns counts dict."""
    return {
        "weight_entries": import_weight_hae(),
        "routes_imported": import_routes_hae(),
    }
