import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/fishing.db")


@contextmanager
def get_connection():
    """Yield a SQLite connection with row dicts and foreign keys enabled."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create the 3 core tables if they do not exist yet."""
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS spots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                center_lat REAL NOT NULL,
                center_lon REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS catches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id INTEGER NOT NULL,
                spot_id INTEGER,
                species TEXT NOT NULL,
                weight_grams INTEGER NOT NULL,
                lat REAL,
                lon REAL,
                caught_at TEXT NOT NULL,
                synced INTEGER DEFAULT 1,
                FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE,
                FOREIGN KEY (spot_id) REFERENCES spots(id) ON DELETE SET NULL
            );
            """
        )


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance in meters between two GPS coordinates."""
    r = 6_371_000  # Earth's radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_or_create_spot(lat: float, lon: float, custom_name: str | None = None, radius_m: float = 200.0) -> int:
    """Snap coordinates to an existing spot within 200m, or create a new named spot."""
    with get_connection() as conn:
        spots = conn.execute("SELECT id, name, center_lat, center_lon FROM spots").fetchall()
        for spot in spots:
            if _haversine_meters(lat, lon, spot["center_lat"], spot["center_lon"]) <= radius_m:
                return spot["id"]

        spot_name = custom_name.strip() if custom_name and custom_name.strip() else f"Spot ({lat:.4f}, {lon:.4f})"
        cursor = conn.execute(
            "INSERT INTO spots (name, center_lat, center_lon) VALUES (?, ?, ?)",
            (spot_name, lat, lon),
        )
        return cursor.lastrowid


def start_trip(name: str, notes: str = "") -> int:
    """Close any open trip and start a new active trip."""
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.execute("UPDATE trips SET end_time = ? WHERE end_time IS NULL", (now,))
        cursor = conn.execute(
            "INSERT INTO trips (name, start_time, notes) VALUES (?, ?, ?)",
            (name.strip(), now, notes.strip()),
        )
        return cursor.lastrowid


def get_active_trip() -> dict | None:
    """Return the currently open trip (where end_time is NULL), if one exists."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM trips WHERE end_time IS NULL ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def log_catch(trip_id: int, species: str, weight_grams: int, lat: float | None = None, lon: float | None = None, spot_name: str | None = None) -> int:
    """Record a single fish catch and auto-link it to a GPS spot if coordinates exist."""
    spot_id = find_or_create_spot(lat, lon, spot_name) if (lat is not None and lon is not None) else None
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO catches (trip_id, spot_id, species, weight_grams, lat, lon, caught_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (trip_id, spot_id, species.strip(), weight_grams, lat, lon, now),
        )
        return cursor.lastrowid


def get_spot_stats() -> list[dict]:
    """Aggregate total catches, heaviest fish (PB), and average weight per spot."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                s.id,
                s.name AS spot_name,
                s.center_lat,
                s.center_lon,
                COUNT(c.id) AS total_fish,
                MAX(c.weight_grams) AS max_weight_grams,
                ROUND(AVG(c.weight_grams)) AS avg_weight_grams
            FROM spots s
            LEFT JOIN catches c ON c.spot_id = s.id
            GROUP BY s.id
            ORDER BY total_fish DESC, max_weight_grams DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def get_trip_stats() -> list[dict]:
    """Aggregate catch count and heaviest fish per trip (morning or multi-day)."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                t.id,
                t.name AS trip_name,
                t.start_time,
                t.end_time,
                COUNT(c.id) AS total_fish,
                COALESCE(MAX(c.weight_grams), 0) AS max_weight_grams
            FROM trips t
            LEFT JOIN catches c ON c.trip_id = t.id
            GROUP BY t.id
            ORDER BY t.start_time DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_catches() -> list[dict]:
    """Return all catches joined with their spot name and trip name, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id,
                c.trip_id,
                t.name AS trip_name,
                c.spot_id,
                COALESCE(s.name, 'Unassigned Spot') AS spot_name,
                c.species,
                c.weight_grams,
                c.lat,
                c.lon,
                c.caught_at
            FROM catches c
            LEFT JOIN spots s ON c.spot_id = s.id
            LEFT JOIN trips t ON c.trip_id = t.id
            ORDER BY c.caught_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]