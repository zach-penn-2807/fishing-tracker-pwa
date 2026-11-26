from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any

from src.utils.moon import calculate_moon_details

DB_PATH = Path("data/fishing.db")


def get_connection() -> sqlite3.Connection:
    """Open a SQLite connection with Row dict-like access and foreign keys enabled."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    """Create v2 tables and indexes if they do not already exist."""
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lake_name TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS swim_stints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                swim_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS catches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                swim_stint_id INTEGER,
                lake_name TEXT NOT NULL,
                swim_name TEXT NOT NULL,
                carp_type TEXT NOT NULL CHECK (carp_type IN ('Mirror', 'Common')),
                rod TEXT NOT NULL CHECK (rod IN ('Left', 'Middle', 'Right')),
                weight_grams INTEGER NOT NULL CHECK (weight_grams > 0),
                caught_at TEXT NOT NULL,
                moon_illumination_pct REAL NOT NULL,
                moon_phase TEXT NOT NULL,
                description TEXT,
                notes TEXT,
                synced INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (swim_stint_id) REFERENCES swim_stints(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_catches_lake_swim ON catches(lake_name, swim_name);
            CREATE INDEX IF NOT EXISTS idx_catches_carp_rod ON catches(carp_type, rod);
            CREATE INDEX IF NOT EXISTS idx_catches_weight ON catches(weight_grams);
            CREATE INDEX IF NOT EXISTS idx_catches_moon ON catches(moon_phase);
            """
        )


# --- Session & Swim Stint Lifecycle ---

def start_session(
    lake_name: str,
    starting_swim: str,
    start_time: str | None = None,
    notes: str = "",
) -> int:
    """Start a new session and open its initial swim stint."""
    ts = start_time or datetime.now().isoformat(timespec="minutes")
    with get_connection() as conn:
        # Close any lingering active session cleanly at the new start time
        active = conn.execute(
            "SELECT id FROM sessions WHERE end_time IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if active:
            end_session(active["id"], end_time=ts)

        cur = conn.execute(
            "INSERT INTO sessions (lake_name, start_time, notes) VALUES (?, ?, ?)",
            (lake_name.strip(), ts, notes.strip()),
        )
        session_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO swim_stints (session_id, swim_name, started_at) VALUES (?, ?, ?)",
            (session_id, starting_swim.strip(), ts),
        )
        return session_id


def get_active_session() -> dict[str, Any] | None:
    """Return the active session merged with its current open swim stint, if any."""
    with get_connection() as conn:
        session = conn.execute(
            "SELECT * FROM sessions WHERE end_time IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not session:
            return None

        stint = conn.execute(
            """
            SELECT * FROM swim_stints
            WHERE session_id = ? AND ended_at IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            (session["id"],),
        ).fetchone()

        result = dict(session)
        result["active_stint"] = dict(stint) if stint else None
        return result


def switch_swim(
    session_id: int,
    new_swim_name: str,
    switched_at: str | None = None,
) -> int:
    """Close the current open swim stint at switched_at and open a new stint."""
    ts = switched_at or datetime.now().isoformat(timespec="minutes")
    clean_swim = new_swim_name.strip()

    with get_connection() as conn:
        current_stint = conn.execute(
            """
            SELECT * FROM swim_stints
            WHERE session_id = ? AND ended_at IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            (session_id,),
        ).fetchone()

        if current_stint:
            if ts < current_stint["started_at"]:
                raise ValueError(
                    f"Switch time ({ts}) cannot be earlier than current swim start ({current_stint['started_at']})."
                )
            conn.execute(
                "UPDATE swim_stints SET ended_at = ? WHERE id = ?",
                (ts, current_stint["id"]),
            )

        cur = conn.execute(
            "INSERT INTO swim_stints (session_id, swim_name, started_at) VALUES (?, ?, ?)",
            (session_id, clean_swim, ts),
        )
        return int(cur.lastrowid)


def end_session(session_id: int, end_time: str | None = None) -> None:
    """Close an active session and its currently open swim stint."""
    ts = end_time or datetime.now().isoformat(timespec="minutes")
    with get_connection() as conn:
        conn.execute(
            "UPDATE swim_stints SET ended_at = ? WHERE session_id = ? AND ended_at IS NULL",
            (ts, session_id),
        )
        conn.execute(
            "UPDATE sessions SET end_time = ? WHERE id = ? AND end_time IS NULL",
            (ts, session_id),
        )


def get_session_stints(session_id: int) -> list[dict[str, Any]]:
    """Return all swim stints for a session in chronological order."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM swim_stints
            WHERE session_id = ?
            ORDER BY started_at ASC, id ASC
            """,
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def find_stint_for_timestamp(session_id: int, caught_at_iso: str) -> dict[str, Any] | None:
    """Find which swim stint in the session covers the given catch timestamp."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM swim_stints
            WHERE session_id = ?
              AND started_at <= ?
              AND (ended_at IS NULL OR ? < ended_at)
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """,
            (session_id, caught_at_iso, caught_at_iso),
        ).fetchone()
        return dict(row) if row else None


# --- Catch Logging & Lookup Helpers ---

def log_catch(
    session_id: int,
    lake_name: str,
    swim_name: str,
    carp_type: str,
    rod: str,
    weight_grams: int,
    caught_at: str | None = None,
    swim_stint_id: int | None = None,
    moon_illumination_pct: float | None = None,
    moon_phase: str | None = None,
    description: str = "",
    notes: str = "",
) -> int:
    """Insert a carp catch record with automatic moon illumination % and phase."""
    ts = caught_at or datetime.now().isoformat(timespec="minutes")
    if moon_illumination_pct is None or moon_phase is None:
        moon_info = calculate_moon_details(datetime.fromisoformat(ts))
        moon_illumination_pct = moon_info["illumination_pct"]
        moon_phase = moon_info["phase_name"]

    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO catches (
                session_id, swim_stint_id, lake_name, swim_name,
                carp_type, rod, weight_grams, caught_at,
                moon_illumination_pct, moon_phase, description, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                swim_stint_id,
                lake_name.strip(),
                swim_name.strip(),
                carp_type,
                rod,
                int(weight_grams),
                ts,
                float(moon_illumination_pct),
                moon_phase,
                description.strip(),
                notes.strip(),
            ),
        )
        return int(cur.lastrowid)


def get_all_sessions() -> list[dict[str, Any]]:
    """Return all sessions newest first with catch counts and swims fished."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                s.*,
                COUNT(c.id) AS total_catches,
                SUM(CASE WHEN c.carp_type = 'Mirror' THEN 1 ELSE 0 END) AS mirror_count,
                SUM(CASE WHEN c.carp_type = 'Common' THEN 1 ELSE 0 END) AS common_count
            FROM sessions s
            LEFT JOIN catches c ON c.session_id = s.id
            GROUP BY s.id
            ORDER BY s.start_time DESC, s.id DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def get_known_lakes() -> list[str]:
    """Return distinct lake names sorted alphabetically."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT lake_name FROM (
                SELECT lake_name FROM sessions
                UNION
                SELECT lake_name FROM catches
            )
            ORDER BY lake_name ASC
            """
        ).fetchall()
        return [r["lake_name"] for r in rows]


def get_swims_for_lake(lake_name: str | None = None) -> list[str]:
    """Return distinct swim names (optionally scoped to a specific lake)."""
    with get_connection() as conn:
        if lake_name:
            rows = conn.execute(
                """
                SELECT DISTINCT swim_name FROM (
                    SELECT st.swim_name
                    FROM swim_stints st
                    JOIN sessions s ON s.id = st.session_id
                    WHERE s.lake_name = ?
                    UNION
                    SELECT swim_name FROM catches WHERE lake_name = ?
                )
                ORDER BY swim_name ASC
                """,
                (lake_name, lake_name),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT DISTINCT swim_name FROM (
                    SELECT swim_name FROM swim_stints
                    UNION
                    SELECT swim_name FROM catches
                )
                ORDER BY swim_name ASC
                """
            ).fetchall()
        return [r["swim_name"] for r in rows]


def query_catches(
    session_id: int | None = None,
    lake_name: str | None = None,
    swim_name: str | None = None,
    carp_type: str | None = None,
    rod: str | None = None,
    moon_phase: str | None = None,
    min_grams: int | None = None,
    max_grams: int | None = None,
) -> list[dict[str, Any]]:
    """Query catches with optional compound filters (size > X / < Y, lake, swim, rod, variety, moon)."""
    clauses: list[str] = []
    params: list[Any] = []

    if session_id is not None:
        clauses.append("session_id = ?")
        params.append(session_id)
    if lake_name:
        clauses.append("lake_name = ?")
        params.append(lake_name)
    if swim_name:
        clauses.append("swim_name = ?")
        params.append(swim_name)
    if carp_type:
        clauses.append("carp_type = ?")
        params.append(carp_type)
    if rod:
        clauses.append("rod = ?")
        params.append(rod)
    if moon_phase:
        clauses.append("moon_phase = ?")
        params.append(moon_phase)
    if min_grams is not None:
        clauses.append("weight_grams > ?")
        params.append(int(min_grams))
    if max_grams is not None:
        clauses.append("weight_grams < ?")
        params.append(int(max_grams))

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM catches {where_sql} ORDER BY caught_at DESC, id DESC"

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def summarize_catches(catches: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute counts, Mirror/Common split, PB, average weight, and rod breakdown for a catch list."""
    total = len(catches)
    mirrors = sum(1 for c in catches if c["carp_type"] == "Mirror")
    commons = sum(1 for c in catches if c["carp_type"] == "Common")
    weights = [c["weight_grams"] for c in catches]

    rod_breakdown = {}
    for rod_name in ("Left", "Middle", "Right"):
        rod_catches = [c for c in catches if c["rod"] == rod_name]
        rod_breakdown[rod_name] = {
            "total": len(rod_catches),
            "mirrors": sum(1 for c in rod_catches if c["carp_type"] == "Mirror"),
            "commons": sum(1 for c in rod_catches if c["carp_type"] == "Common"),
            "max_grams": max((c["weight_grams"] for c in rod_catches), default=0),
        }

    return {
        "total": total,
        "mirrors": mirrors,
        "commons": commons,
        "max_grams": max(weights, default=0),
        "avg_grams": int(round(sum(weights) / total)) if total else 0,
        "rods": rod_breakdown,
    }