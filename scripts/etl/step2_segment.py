"""
Step 2: Session & Swim Stint Segmentation for Dad's Legacy Fishing Notes.

Reads scripts/etl/output/step1_cleaned.txt, tracks season headers and lake
overrides, groups lines into session blocks, builds chronological swim_stints
(including mid-session swim moves), infers approximate start/end timestamps,
and writes scripts/etl/output/step2_segmented.json for review before Step 3.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

MONTHS: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

CANONICAL_SWIMS: list[str] = [
    "Motorway Swim",
    "Back Middle",
    "Side Bay",
    "Car Park",
    "Point",
    "Creek",
    "Posh",
    "Becks",
    "Reeds",
    "Lonely",
    "Bay",
]

_SWIM_REGEX = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in CANONICAL_SWIMS) + r")\b",
    flags=re.IGNORECASE,
)

# Matches season headers like:
# "Season 2020-21", "Pit 2 SEASON 2021/22", "PIT 2 SEASON 22/23", "SEASON 25/26"
_SEASON_RE = re.compile(r"\bseason\s+(\d{2,4})\s*[-/]\s*(\d{2,4})\b", re.IGNORECASE)

# Modular session header building blocks
_LEADING_DAY_RE = re.compile(
    r"^\s*(?P<d1>\d{1,2})(?:/(?P<m1>\d{1,2}))?(?:st|nd|rd|th)?\b"
)
_END_DAY_RE = re.compile(
    r"(?:\s*-\s*(?P<d2>\d{1,2})(?:/(?P<m2>\d{1,2}))?(?:st|nd|rd|th)?)"
)
_MONTH_NAME_RE = re.compile(
    r"\b(" + "|".join(MONTHS.keys()) + r")\b",
    flags=re.IGNORECASE,
)
_SLASH_RANGE_RE = re.compile(
    r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\s*-\s*\d{1,2}(?:/\d{1,2})?(?:/\d{2,4})?\b"
)
_DAY_RANGE_RE = re.compile(
    r"^\s*\d{1,2}(?:st|nd|rd|th)?\s*-\s*\d{1,2}(?:/\d{1,2})?(?:st|nd|rd|th)?\b"
)
_YEAR_SUFFIX_RE = re.compile(r"(?:\b\d{1,2}/\d{1,2})/(?P<yr2>\d{2,4})\b")

_TIME_PAIR_RE = re.compile(
    r"\b(?P<t1>\d{1,2}(?:[.:]\d{2})?\s*(?:am|pm)?)\s*-\s*(?P<t2>\d{1,2}(?:[.:]\d{2})?\s*(?:am|pm)?)?",
    re.IGNORECASE,
)

_MOVE_RE = re.compile(r"\b(moved?|move)\b", re.IGNORECASE)


def parse_season_years(header: str) -> tuple[int, int] | None:
    """Return (start_year, end_year) as 4-digit years from a season header."""
    m = _SEASON_RE.search(header)
    if not m:
        return None
    y1 = int(m.group(1))
    y2 = int(m.group(2))
    if y1 < 100:
        y1 += 2000
    if y2 < 100:
        y2 = (y1 // 100) * 100 + y2
        if y2 < y1:
            y2 += 100
    return y1, y2


def infer_year_for_month(month: int, season_years: tuple[int, int] | None) -> int:
    """
    Infer calendar year for a given month within a season (e.g., 2020-2021).
    Jan–May maps to end_year; Jun–Dec maps to start_year.
    """
    if not season_years:
        return 2023
    start_yr, end_yr = season_years
    if start_yr == end_yr:
        return start_yr
    return end_yr if month <= 5 else start_yr


def parse_clock_time(token: str | None, fallback: time) -> time:
    """Parse tokens like '0700', '18.30', '11pm', '9.30am' into datetime.time."""
    if not token:
        return fallback
    cleaned = token.strip().lower()
    meridiem = None
    if cleaned.endswith("am") or cleaned.endswith("pm"):
        meridiem = cleaned[-2:]
        cleaned = cleaned[:-2].strip()

    cleaned = cleaned.replace(".", ":")
    hour = fallback.hour
    minute = fallback.minute

    if ":" in cleaned:
        parts = cleaned.split(":", 1)
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError:
            return fallback
    elif cleaned.isdigit():
        if len(cleaned) in (3, 4):
            hour = int(cleaned[:-2])
            minute = int(cleaned[-2:])
        else:
            hour = int(cleaned)
            minute = 0
    else:
        return fallback

    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0

    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return time(hour=hour, minute=minute)
    return fallback


def find_swims_in_line(line: str) -> list[str]:
    """Return canonical swim names present in a line in order of appearance."""
    seen: list[str] = []
    for match in _SWIM_REGEX.finditer(line):
        canonical = next(s for s in CANONICAL_SWIMS if s.lower() == match.group(0).lower())
        if canonical not in seen:
            seen.append(canonical)
    return seen


def detect_lake_override(line: str, current_lake: str) -> str:
    """Detect explicit lake overrides in headers/lines; otherwise keep current_lake."""
    lower = line.lower()
    if "dovecote" in lower:
        return "Dovecote"
    if "little lake" in lower:
        return "Little Lake"
    return current_lake


def is_session_start(line: str) -> re.Match[str] | None:
    """
    Identify session start lines while avoiding false positives on catch lines
    like '12/1915 Rh Comm' or '19/0720 Rh Mirror'.
    """
    stripped = line.strip()
    if re.match(r"^\d{1,2}/\d{3,4}\b", stripped):
        return None

    lead = _LEADING_DAY_RE.match(stripped)
    if not lead:
        return None

    has_month_name = bool(_MONTH_NAME_RE.search(stripped))
    has_slash_range = bool(_SLASH_RANGE_RE.search(stripped))
    has_day_range = bool(_DAY_RANGE_RE.match(stripped))

    if has_month_name or has_slash_range or has_day_range:
        return lead
    return None


def build_session_dates(
    line: str,
    lead_match: re.Match[str],
    season_years: tuple[int, int] | None,
    last_month: int,
) -> tuple[datetime, datetime, int]:
    """Return (start_dt, end_dt, resolved_month) with sensible defaults."""
    d1 = int(lead_match.group("d1"))
    m1_raw = lead_match.group("m1")

    end_match = _END_DAY_RE.search(line[lead_match.end() :])
    d2 = int(end_match.group("d2")) if end_match and end_match.group("d2") else d1
    m2_raw = end_match.group("m2") if end_match else None

    month_match = _MONTH_NAME_RE.search(line)
    if month_match:
        start_month = MONTHS[month_match.group(1).lower()]
    elif m1_raw:
        start_month = int(m1_raw)
    else:
        start_month = last_month

    end_month = int(m2_raw) if m2_raw else start_month

    yr_match = _YEAR_SUFFIX_RE.search(line)
    if yr_match:
        explicit_yr = int(yr_match.group("yr2"))
        if explicit_yr < 100:
            explicit_yr += 2000
        start_year = explicit_yr
        end_year = explicit_yr
    else:
        start_year = infer_year_for_month(start_month, season_years)
        end_year = infer_year_for_month(end_month, season_years)

    if end_month < start_month and end_year == start_year:
        end_year += 1

    t_match = _TIME_PAIR_RE.search(line)
    start_clock = parse_clock_time(t_match.group("t1") if t_match else None, time(8, 0))
    end_clock = parse_clock_time(t_match.group("t2") if t_match else None, time(12, 0))

    try:
        start_dt = datetime.combine(datetime(start_year, start_month, d1).date(), start_clock)
    except ValueError:
        start_dt = datetime.combine(
            datetime(start_year, start_month, min(d1, 28)).date(), start_clock
        )

    try:
        end_dt = datetime.combine(datetime(end_year, end_month, d2).date(), end_clock)
    except ValueError:
        end_dt = datetime.combine(
            datetime(end_year, end_month, min(d2, 28)).date(), end_clock
        )

    if end_dt < start_dt:
        end_dt = start_dt + timedelta(hours=12)

    return start_dt, end_dt, end_month


def segment_lines(lines: list[str]) -> list[dict]:
    """Segment cleaned lines into structured session blocks and swim stints."""
    sessions: list[dict] = []
    current_session: dict | None = None
    current_season_label: str | None = None
    current_season_years: tuple[int, int] | None = None
    current_lake: str = "Pit 2"
    last_month: int = 3
    session_counter = 0

    def finalize_session(sess: dict | None) -> None:
        if not sess:
            return
        stints = sess["swim_stints"]
        for idx, stint in enumerate(stints):
            if idx + 1 < len(stints):
                next_start = stints[idx + 1]["started_at"]
                if not stint["ended_at"] or stint["ended_at"] > next_start:
                    stint["ended_at"] = next_start
            elif not stint["ended_at"]:
                stint["ended_at"] = sess["end_time"]

        if not stints:
            stints.append(
                {
                    "temp_stint_id": f"{sess['temp_session_id']}_stint_01",
                    "swim_name": "Unknown Swim",
                    "started_at": sess["start_time"],
                    "ended_at": sess["end_time"],
                    "inferred": True,
                }
            )

        sessions.append(sess)

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        season_years = parse_season_years(line)
        if season_years:
            finalize_session(current_session)
            current_session = None
            current_season_label = line
            current_season_years = season_years
            current_lake = "Pit 2"
            continue

        header_match = is_session_start(line)
        if header_match:
            finalize_session(current_session)
            session_counter += 1
            current_lake = detect_lake_override(line, "Pit 2")
            start_dt, end_dt, last_month = build_session_dates(
                line, header_match, current_season_years, last_month
            )
            sess_id = f"sess_{session_counter:03d}"
            initial_swims = find_swims_in_line(line)
            stints: list[dict] = []
            for s_idx, swim_name in enumerate(initial_swims, start=1):
                stints.append(
                    {
                        "temp_stint_id": f"{sess_id}_stint_{s_idx:02d}",
                        "swim_name": swim_name,
                        "started_at": start_dt.isoformat(),
                        "ended_at": end_dt.isoformat() if len(initial_swims) == 1 else None,
                        "inferred": False,
                    }
                )

            current_session = {
                "temp_session_id": sess_id,
                "season": current_season_label,
                "lake_name": current_lake,
                "header_raw": line,
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat(),
                "notes": f"Season: {current_season_label}" if current_season_label else "",
                "swim_stints": stints,
                "raw_lines": [line],
            }
            continue

        if current_session is None:
            continue

        current_session["raw_lines"].append(line)
        current_session["lake_name"] = detect_lake_override(line, current_session["lake_name"])

        line_swims = find_swims_in_line(line)
        if line_swims:
            stints = current_session["swim_stints"]
            is_move = bool(_MOVE_RE.search(line))
            for swim_name in line_swims:
                existing_names = [s["swim_name"] for s in stints]
                if is_move or swim_name not in existing_names:
                    move_time_match = re.search(r"\b(\d{1,2}[:.]\d{2}|\d{3,4})\b", line)
                    move_clock = parse_clock_time(
                        move_time_match.group(1) if move_time_match else None,
                        time(12, 0),
                    )
                    start_date = datetime.fromisoformat(current_session["start_time"]).date()
                    end_date = datetime.fromisoformat(current_session["end_time"]).date()
                    move_dt = datetime.combine(start_date, move_clock)
                    if move_dt < datetime.fromisoformat(current_session["start_time"]):
                        move_dt = datetime.combine(end_date, move_clock)

                    stint_num = len(stints) + 1
                    stints.append(
                        {
                            "temp_stint_id": f"{current_session['temp_session_id']}_stint_{stint_num:02d}",
                            "swim_name": swim_name,
                            "started_at": move_dt.isoformat(),
                            "ended_at": current_session["end_time"],
                            "inferred": move_time_match is None,
                        }
                    )

    finalize_session(current_session)
    return sessions


def main() -> None:
    etl_dir = Path(__file__).resolve().parent
    input_path = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else etl_dir / "output" / "step1_cleaned.txt"
    )
    output_path = etl_dir / "output" / "step2_segmented.json"

    if not input_path.exists():
        print(f"Error: Cleaned file not found at {input_path}")
        print("Run step1_normalize.py first.")
        sys.exit(1)

    lines = input_path.read_text(encoding="utf-8").splitlines()
    sessions = segment_lines(lines)

    payload = {
        "step": 2,
        "source_file": str(input_path),
        "session_count": len(sessions),
        "total_swim_stints": sum(len(s["swim_stints"]) for s in sessions),
        "sessions": sessions,
    }

    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote segmented sessions to: {output_path}")
    print(f"Sessions detected:           {payload['session_count']}")
    print(f"Swim stints generated:         {payload['total_swim_stints']}")
    print("\nSample first 3 sessions:")
    for s in sessions[:3]:
        swims_summary = ", ".join(
            f"{st['swim_name']} ({st['started_at']} -> {st['ended_at']})"
            for st in s["swim_stints"]
        )
        print(f"  • {s['temp_session_id']} [{s['lake_name']}] {s['header_raw']} | Stints: {swims_summary}")


if __name__ == "__main__":
    main()