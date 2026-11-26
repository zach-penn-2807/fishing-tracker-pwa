"""
Step 3: Catch Parsing & Schema Mapping for Dad's Legacy Fishing Notes.

Reads scripts/etl/output/step2_segmented.json, re-splits any swallowed
session headers (e.g. 'October 7-8 m94%', 'October 31- 2 Nov m55%'),
refines session/stint timestamps, parses valid Mirror/Common carp catches
(defaulting weight-bearing lines without an explicit species to 'Mirror'),
deduplicates photo-caption weight lines into catch notes, computes moon
illumination % and phase via src/utils/moon.py, and writes
scripts/etl/output/step3_parsed.json.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from src.utils.moon import get_moon_info  # type: ignore
except Exception:
    get_moon_info = None

LB_TO_GRAMS = 453.59237
OZ_TO_GRAMS = 28.349523125

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
_SEASON_RE = re.compile(r"\bseason\s+(\d{2,4})\s*[-/]\s*(\d{2,4})\b", re.IGNORECASE)

# Matches session headers starting with either:
# - Month name + day/range ("October 7-8 m94%", "October 31- 2 Nov m55%", "August 20-21 0730-")
# - Day/range + month ("9-10th March 0700-1500", "31-2 September 22", "23-25 October 24")
# - Slash dates ("31/7-2/8", "9/8/25 am session", "2-4/10/25")
_MONTH_FIRST_HEADER_RE = re.compile(
    r"^\s*(?P<month>" + "|".join(MONTHS.keys()) + r")\s+(?P<d1>\d{1,2})\b",
    flags=re.IGNORECASE,
)
_DAY_FIRST_HEADER_RE = re.compile(
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

_TIME_TOKEN_PATTERN = r"(?:\d{3,4}|\d{1,2}(?:[.:]\d{2})?\s*(?:am|pm)?)"
_TIME_PAIR_RE = re.compile(
    rf"\b(?P<t1>{_TIME_TOKEN_PATTERN})\s*-\s*(?P<t2>{_TIME_TOKEN_PATTERN})?",
    re.IGNORECASE,
)
_MOVE_RE = re.compile(r"\b(moved?|move)\b", re.IGNORECASE)

_ROD_RE = re.compile(r"\b(lh|left|md|middle|rh|right|m)\b", re.IGNORECASE)
_CATCH_TIME_RE = re.compile(
    r"^\s*(?:(?P<day>\d{1,2})/)?(?P<clock>\d{1,2}(?:[.:]\d{2})?\s*(?:am|pm)?|\d{3,4})\b",
    re.IGNORECASE,
)

_HYPHEN_WEIGHT_RE = re.compile(r"\b(?P<lb>\d{1,3})\s*[-–]\s*(?P<oz>\d{1,2})\b")
_DECIMAL_WEIGHT_RE = re.compile(r"\b(?P<lb>\d{1,3})\.(?P<oz>\d{1,2})\b")
_WHOLE_LB_RE = re.compile(r"\b(?P<lb>\d{1,3})\s*(?:lb|lbs)\b", re.IGNORECASE)

COMMON_KEYWORDS = ("common",)

EXCLUSION_PHRASES = (
    "tench",
    "cat 16",
    "catfish",
    "lost one",
    "lost fish",
    "hook pull",
    "hook link broke",
    "guest",
)

METADATA_ONLY_PHRASES = (
    "blank",
    "lockdown",
    "closed",
    "spawning",
    "khv",
    "receiver",
    "reciever",
    "battery",
    "varta",
    "duracell",
    "energiser",
)


def imperial_to_grams(lb: int, oz: int = 0) -> int:
    """Convert UK lb + oz to integer grams."""
    return int(round(lb * LB_TO_GRAMS + oz * OZ_TO_GRAMS))


def parse_season_years(header: str | None) -> tuple[int, int] | None:
    """Return (start_year, end_year) as 4-digit years from a season header."""
    if not header:
        return None
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


def is_session_header(line: str) -> bool:
    """
    True if line starts a fishing session (month-first like 'October 7-8 m94%',
    day-first like '9-10th March', or slash-date like '9/8/25 am session'),
    excluding standalone date notes like 'Sept 2nd' or '21/8' or '12/1915 Rh'.
    """
    stripped = line.strip()
    if not stripped:
        return False
    # Exclude catch timestamps like '12/1915 Rh' or '19/0720 Rh' or bare '21/8' or 'Sept 2nd'
    if re.match(r"^\d{1,2}/\d{3,4}\b", stripped):
        return False
    if re.match(r"^\d{1,2}/\d{1,2}$", stripped):
        return False
    if re.match(r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?$", stripped, re.IGNORECASE):
        return False

    if "dovecote" in stripped.lower():
        return True

    m_first = _MONTH_FIRST_HEADER_RE.match(stripped)
    if m_first:
        # Must have a day range (October 7-8) or moon/time info (September 25 m.75%)
        after = stripped[m_first.end() :]
        if re.match(r"^\s*-\s*\d{1,2}", after) or re.search(r"(\d{3,4}|m\.?\s*\d+%)", stripped, re.IGNORECASE):
            return True

    lead = _DAY_FIRST_HEADER_RE.match(stripped)
    if not lead:
        return False

    has_month_name = bool(_MONTH_NAME_RE.search(stripped))
    has_slash_range = bool(_SLASH_RANGE_RE.search(stripped))
    has_day_range = bool(_DAY_RANGE_RE.match(stripped))
    return has_month_name or has_slash_range or has_day_range


def parse_clock_time(token: str | None, fallback: time) -> time:
    """Parse clock tokens like '0700', '1500', '18.30', '11pm', '9.30am' into time."""
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
        elif len(cleaned) <= 2:
            hour = int(cleaned)
            minute = 0
        else:
            return fallback
    else:
        return fallback

    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0

    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return time(hour=hour, minute=minute)
    return fallback


def resegment_swallowed_headers(sessions: list[dict]) -> list[dict]:
    """
    Scan raw_lines inside each session from Step 2; if a subsequent line is
    actually a session header that Step 2 missed (e.g. 'October 7-8 m94%'),
    split it out into its own session block with its own swim stints.
    """
    rebuilt: list[dict] = []
    counter = 0

    for orig in sessions:
        raw_lines = orig.get("raw_lines", [])
        if not raw_lines:
            continue

        buckets: list[list[str]] = [[raw_lines[0]]]
        for ln in raw_lines[1:]:
            if is_session_header(ln):
                buckets.append([ln])
            else:
                buckets[-1].append(ln)

        for bucket in buckets:
            counter += 1
            sess_id = f"sess_{counter:03d}"
            header = bucket[0]
            lake = detect_lake_override(header, orig.get("lake_name", "Pit 2"))
            if "dovecote" not in header.lower() and "little lake" not in header.lower():
                lake = "Pit 2"

            stints: list[dict] = []
            for ln in bucket:
                lake = detect_lake_override(ln, lake)
                swims = find_swims_in_line(ln)
                is_move = bool(_MOVE_RE.search(ln))
                for sw in swims:
                    existing = [st["swim_name"] for st in stints]
                    if is_move or sw not in existing:
                        t_m = re.search(r"\b(\d{1,2}[:.]\d{2}|\d{3,4})\b", ln)
                        stints.append(
                            {
                                "temp_stint_id": f"{sess_id}_stint_{len(stints) + 1:02d}",
                                "swim_name": sw,
                                "raw_time_token": t_m.group(1) if t_m else None,
                                "started_at": orig["start_time"],
                                "ended_at": orig["end_time"],
                            }
                        )

            if not stints:
                stints.append(
                    {
                        "temp_stint_id": f"{sess_id}_stint_01",
                        "swim_name": "Unknown Swim",
                        "raw_time_token": None,
                        "started_at": orig["start_time"],
                        "ended_at": orig["end_time"],
                    }
                )

            rebuilt.append(
                {
                    "temp_session_id": sess_id,
                    "season": orig.get("season"),
                    "lake_name": lake,
                    "header_raw": header,
                    "start_time": orig["start_time"],
                    "end_time": orig["end_time"],
                    "notes": f"Season: {orig['season']}" if orig.get("season") else "",
                    "swim_stints": stints,
                    "raw_lines": bucket,
                }
            )

    return rebuilt


def refine_session_timestamps(sessions: list[dict]) -> list[dict]:
    """
    Compute clean ISO-8601 start_time/end_time for every session (including
    re-split headers) and align swim_stints within each session window.
    """
    season_first_month: dict[str, int] = {}
    for s in sessions:
        season_key = s.get("season") or ""
        header = s.get("header_raw", "")
        m_match = _MONTH_NAME_RE.search(header)
        lead = _DAY_FIRST_HEADER_RE.match(header)
        if season_key and season_key not in season_first_month:
            if m_match:
                season_first_month[season_key] = MONTHS[m_match.group(1).lower()]
            elif lead and lead.group("m1"):
                season_first_month[season_key] = int(lead.group("m1"))

    last_resolved_month = 3
    for s in sessions:
        header = s.get("header_raw", "")
        season_key = s.get("season") or ""
        season_years = parse_season_years(season_key)
        first_month = season_first_month.get(season_key)

        m_first = _MONTH_FIRST_HEADER_RE.match(header)
        lead = _DAY_FIRST_HEADER_RE.match(header)
        d1 = d2 = None
        m1_raw = m2_raw = None

        if m_first:
            d1 = int(m_first.group("d1"))
            end_m = _END_DAY_RE.search(header[m_first.end() :])
            d2 = int(end_m.group("d2")) if end_m and end_m.group("d2") else d1
            m2_raw = end_m.group("m2") if end_m else None
        elif lead:
            d1 = int(lead.group("d1"))
            m1_raw = lead.group("m1")
            end_m = _END_DAY_RE.search(header[lead.end() :])
            d2 = int(end_m.group("d2")) if end_m and end_m.group("d2") else d1
            m2_raw = end_m.group("m2") if end_m else None
        elif "dovecote" in header.lower():
            dm = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", header)
            if dm:
                d1 = d2 = int(dm.group(1))
                m1_raw = m2_raw = dm.group(2)

        if d1 is not None:
            all_months = [MONTHS[m.group(1).lower()] for m in _MONTH_NAME_RE.finditer(header)]
            if all_months:
                start_month = all_months[0]
                end_month = all_months[-1] if len(all_months) > 1 else (int(m2_raw) if m2_raw else start_month)
            elif m1_raw:
                start_month = int(m1_raw)
                end_month = int(m2_raw) if m2_raw else start_month
            else:
                start_month = end_month = last_resolved_month

            last_resolved_month = end_month

            yr_match = _YEAR_SUFFIX_RE.search(header)
            if yr_match:
                yr = int(yr_match.group("yr2"))
                if yr < 100:
                    yr += 2000
                start_year = end_year = yr
            elif season_years:
                start_yr, end_yr = season_years
                if first_month is not None and start_yr != end_yr:
                    start_year = start_yr if start_month >= first_month else end_yr
                    end_year = start_yr if end_month >= first_month else end_yr
                else:
                    start_year = end_yr if start_month <= 2 else start_yr
                    end_year = end_yr if end_month <= 2 else start_yr
            else:
                start_year = end_year = datetime.fromisoformat(s["start_time"]).year

            if end_month < start_month and end_year == start_year:
                end_year += 1

            # Find time pair on header or first body line (e.g. '1800-2100')
            combined_header_text = " ".join(s.get("raw_lines", [])[:3])
            t_match = _TIME_PAIR_RE.search(combined_header_text)
            start_clock = parse_clock_time(t_match.group("t1") if t_match else None, time(8, 0))
            end_clock = parse_clock_time(t_match.group("t2") if t_match else None, time(12, 0))

            try:
                start_dt = datetime.combine(datetime(start_year, start_month, d1).date(), start_clock)
            except ValueError:
                start_dt = datetime.combine(datetime(start_year, start_month, min(d1, 28)).date(), start_clock)

            try:
                end_dt = datetime.combine(datetime(end_year, end_month, d2).date(), end_clock)
            except ValueError:
                end_dt = datetime.combine(datetime(end_year, end_month, min(d2, 28)).date(), end_clock)

            if end_dt < start_dt:
                end_dt = start_dt + timedelta(hours=12)

            s["start_time"] = start_dt.isoformat()
            s["end_time"] = end_dt.isoformat()

        sess_start = datetime.fromisoformat(s["start_time"])
        sess_end = datetime.fromisoformat(s["end_time"])
        stints = s.get("swim_stints", [])
        for idx, stint in enumerate(stints):
            if idx == 0:
                stint["started_at"] = sess_start.isoformat()
            else:
                tok = stint.get("raw_time_token")
                clk = parse_clock_time(tok, time(12, 0))
                cand = datetime.combine(sess_start.date(), clk)
                if cand < sess_start and sess_end.date() > sess_start.date():
                    cand = datetime.combine(sess_start.date() + timedelta(days=1), clk)
                if cand < sess_start:
                    cand = sess_start
                if cand > sess_end:
                    cand = sess_end
                stint["started_at"] = cand.isoformat()

        for idx, stint in enumerate(stints):
            stint.pop("raw_time_token", None)
            if idx + 1 < len(stints):
                stint["ended_at"] = stints[idx + 1]["started_at"]
            else:
                stint["ended_at"] = sess_end.isoformat()

    return sessions


def normalize_rod(token: str) -> str:
    """Map rod shorthand to v2 schema rod values ('Left', 'Middle', 'Right')."""
    low = token.lower()
    if low in ("lh", "left"):
        return "Left"
    if low in ("md", "m", "middle"):
        return "Middle"
    return "Right"


def extract_weight_grams(line: str) -> tuple[int | None, str | None]:
    """
    Extract integer weight_grams and optional note from a line.
    Supports '43lb8oz', '38lb 8oz', '30lb-10oz', '38-8', '33.8', '30lb4', '40lb plus'.
    Ignores moon percentages ('99%') and date ranges ('10-11th').
    """
    # Strip moon percentage tokens and date-range tokens so they aren't parsed as weights
    cleaned = re.sub(r"\bm\.?\s*\d+(?:\s*[-/~]\s*\d+)*%", "", line, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d{1,2}\s*-\s*\d{1,2}(?:st|nd|rd|th)\b", "", cleaned, flags=re.IGNORECASE)
    # Strip leading day/time prefix like '12/1915' or '0930'
    cleaned = re.sub(r"^\s*(?:\d{1,2}/)?\d{3,4}\b", "", cleaned)

    m_plus = re.search(r"\b(\d{1,3})\s*(?:lb|lbs)?\s*(?:plus|\+)\b", cleaned, re.IGNORECASE)
    if m_plus:
        lb = int(m_plus.group(1))
        return imperial_to_grams(lb, 0), f"Approximate weight from '{m_plus.group(0).strip()}'"

    # e.g., '38lb 8oz', '30lb-10oz', '43lb8oz', '31lb 10', '30lb4'
    m_lb_oz = re.search(
        r"\b(?P<lb>\d{1,3})\s*(?:lb|lbs)\s*(?:[-–\s])?\s*(?P<oz>\d{1,2})?\s*(?:oz)?\b",
        cleaned,
        re.IGNORECASE,
    )
    if m_lb_oz:
        lb = int(m_lb_oz.group("lb"))
        oz = int(m_lb_oz.group("oz")) if m_lb_oz.group("oz") else 0
        if oz <= 15:
            return imperial_to_grams(lb, oz), None

    m_hyphen = _HYPHEN_WEIGHT_RE.search(cleaned)
    if m_hyphen:
        lb = int(m_hyphen.group("lb"))
        oz = int(m_hyphen.group("oz"))
        if oz <= 15 and lb >= 5:
            return imperial_to_grams(lb, oz), f"Parsed '{m_hyphen.group(0)}' as {lb}lb {oz}oz"

    m_dec = _DECIMAL_WEIGHT_RE.search(cleaned)
    if m_dec:
        lb = int(m_dec.group("lb"))
        oz = int(m_dec.group("oz"))
        if oz <= 15 and lb >= 5:
            return (
                imperial_to_grams(lb, oz),
                f"Parsed decimal '{m_dec.group(0)}' as {lb}lb {oz}oz",
            )

    m_whole = _WHOLE_LB_RE.search(cleaned)
    if m_whole:
        lb = int(m_whole.group("lb"))
        return imperial_to_grams(lb, 0), None

    return None, None


def resolve_catch_timestamp(line: str, session: dict) -> str:
    """Resolve an ISO-8601 caught_at timestamp within the session's date range."""
    sess_start = datetime.fromisoformat(session["start_time"])
    sess_end = datetime.fromisoformat(session["end_time"])

    m = _CATCH_TIME_RE.search(line)
    if not m:
        midpoint = sess_start + (sess_end - sess_start) / 2
        return midpoint.replace(microsecond=0).isoformat()

    day_str = m.group("day")
    clock_str = m.group("clock")
    clock = parse_clock_time(clock_str, sess_start.time())

    target_date = sess_start.date()
    if day_str:
        day_num = int(day_str)
        cur = sess_start.date()
        while cur <= sess_end.date():
            if cur.day == day_num:
                target_date = cur
                break
            cur += timedelta(days=1)
    else:
        candidate_start = datetime.combine(sess_start.date(), clock)
        if candidate_start < sess_start and sess_end.date() > sess_start.date():
            target_date = sess_start.date() + timedelta(days=1)

    dt = datetime.combine(target_date, clock)
    if dt < sess_start:
        dt = sess_start
    elif dt > sess_end:
        dt = sess_end
    return dt.replace(microsecond=0).isoformat()


def find_matching_stint(session: dict, caught_at_iso: str) -> dict:
    """Return the swim stint covering caught_at_iso, falling back to the last stint."""
    stints = session.get("swim_stints", [])
    if not stints:
        return {
            "temp_stint_id": f"{session['temp_session_id']}_stint_01",
            "swim_name": "Unknown Swim",
        }
    caught_dt = datetime.fromisoformat(caught_at_iso)
    for stint in stints:
        st_start = datetime.fromisoformat(stint["started_at"])
        st_end = datetime.fromisoformat(stint["ended_at"])
        if st_start <= caught_dt <= st_end:
            return stint
    return stints[-1]


def compute_moon(caught_at_iso: str) -> tuple[float, str]:
    """Compute (moon_illumination_pct, moon_phase) via src/utils/moon.py."""
    dt = datetime.fromisoformat(caught_at_iso)
    if callable(get_moon_info):
        info = get_moon_info(dt)
        if isinstance(info, dict):
            pct = float(info.get("illumination_pct", info.get("moon_illumination_pct", 0.0)))
            phase = str(info.get("phase_name", info.get("moon_phase", "Unknown")))
            return round(pct, 1), phase
        if isinstance(info, (tuple, list)) and len(info) >= 2:
            return round(float(info[0]), 1), str(info[1])
    return 0.0, "Unknown"


def parse_session_catches(session: dict) -> tuple[list[dict], list[dict], int]:
    """
    Parse raw_lines inside a session into (catches, excluded_items, context_count).
    - Weight-bearing lines without explicit 'Common' default to 'Mirror'.
    - Caption-style weight lines immediately after a catch with matching weight
      (within ~60g) are attached to the preceding catch's notes instead of
      creating a duplicate catch.
    """
    catches: list[dict] = []
    excluded: list[dict] = []
    context_count = 0
    extra_session_notes: list[str] = []
    in_guest_block = False

    body_lines = session.get("raw_lines", [])[1:]

    for line in body_lines:
        stripped = line.strip()
        if not stripped:
            continue

        low = stripped.lower()

        if "guest" in low:
            in_guest_block = True
            excluded.append(
                {
                    "temp_session_id": session["temp_session_id"],
                    "line": stripped,
                    "reason": "Guest session block marker",
                }
            )
            continue

        if low.startswith("me ") or low == "me":
            in_guest_block = False

        if in_guest_block:
            excluded.append(
                {
                    "temp_session_id": session["temp_session_id"],
                    "line": stripped,
                    "reason": "Guest catch (excluded per rule)",
                }
            )
            continue

        if any(phrase in low for phrase in EXCLUSION_PHRASES):
            excluded.append(
                {
                    "temp_session_id": session["temp_session_id"],
                    "line": stripped,
                    "reason": "Non-carp or lost fish / hook pull",
                }
            )
            continue

        if any(phrase in low for phrase in METADATA_ONLY_PHRASES):
            context_count += 1
            if any(
                k in low
                for k in ("receiver", "reciever", "battery", "varta", "duracell", "energiser", "spawning", "khv", "lockdown")
            ):
                extra_session_notes.append(stripped)
            continue

        # Pure swim, move, moon %, or time-window lines belong to session/stint metadata
        if (
            _MOVE_RE.search(stripped)
            or re.match(r"^[mM]\.?\s*\d+", stripped)
            or re.match(r"^\d{1,2}(?:[:.]\d{2})?\s*-\s*\d{0,4}", stripped)
            or (find_swims_in_line(stripped) and not extract_weight_grams(stripped)[0])
        ):
            context_count += 1
            continue

        weight_grams, weight_note = extract_weight_grams(stripped)
        rod_match = _ROD_RE.search(stripped)
        time_match = _CATCH_TIME_RE.search(stripped)

        if weight_grams is None:
            # Qualitative follow-up note (rig, bait, named fish caption without weight)
            context_count += 1
            if catches:
                catches[-1]["notes"] += f" | {stripped}"
            else:
                extra_session_notes.append(stripped)
            continue

        # Photo-caption duplicate check: no rod, no catch time, and within ~60g of previous catch
        if catches and not rod_match and not time_match:
            prev = catches[-1]
            if abs(prev["weight_grams"] - weight_grams) <= 65:
                prev["notes"] += f" | Caption: {stripped}"
                context_count += 1
                continue

        carp_type = "Common" if any(kw in low for kw in COMMON_KEYWORDS) else "Mirror"
        rod = normalize_rod(rod_match.group(1)) if rod_match else "Middle"
        caught_at = resolve_catch_timestamp(stripped, session)
        stint = find_matching_stint(session, caught_at)
        moon_pct, moon_phase = compute_moon(caught_at)

        notes_parts = [f"Raw line: {stripped}"]
        if weight_note:
            notes_parts.append(weight_note)

        catches.append(
            {
                "temp_stint_id": stint["temp_stint_id"],
                "lake_name": session["lake_name"],
                "swim_name": stint["swim_name"],
                "carp_type": carp_type,
                "rod": rod,
                "weight_grams": weight_grams,
                "caught_at": caught_at,
                "moon_illumination_pct": moon_pct,
                "moon_phase": moon_phase,
                "description": stripped,
                "notes": " | ".join(notes_parts),
            }
        )

    if extra_session_notes:
        existing = session.get("notes", "")
        session["notes"] = " | ".join([existing] + extra_session_notes).strip(" |")

    return catches, excluded, context_count


def main() -> None:
    etl_dir = Path(__file__).resolve().parent
    input_path = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else etl_dir / "output" / "step2_segmented.json"
    )
    output_path = etl_dir / "output" / "step3_parsed.json"

    if not input_path.exists():
        print(f"Error: Segmented file not found at {input_path}")
        print("Run step2_segment.py first.")
        sys.exit(1)

    raw_payload = json.loads(input_path.read_text(encoding="utf-8"))
    split_sessions = resegment_swallowed_headers(raw_payload.get("sessions", []))
    sessions = refine_session_timestamps(split_sessions)

    all_excluded: list[dict] = []
    total_catches = 0
    total_context = 0

    enriched_sessions: list[dict] = []
    for sess in sessions:
        catches, excluded, ctx_cnt = parse_session_catches(sess)
        total_catches += len(catches)
        total_context += ctx_cnt
        all_excluded.extend(excluded)
        enriched_sessions.append(
            {
                "temp_session_id": sess["temp_session_id"],
                "season": sess.get("season"),
                "lake_name": sess["lake_name"],
                "header_raw": sess.get("header_raw", ""),
                "start_time": sess["start_time"],
                "end_time": sess["end_time"],
                "notes": sess.get("notes", ""),
                "swim_stints": sess.get("swim_stints", []),
                "catches": catches,
            }
        )

    out_payload = {
        "step": 3,
        "session_count": len(enriched_sessions),
        "total_swim_stints": sum(len(s["swim_stints"]) for s in enriched_sessions),
        "total_catches": total_catches,
        "excluded_count": len(all_excluded),
        "context_lines_folded": total_context,
        "sessions": enriched_sessions,
        "excluded_items": all_excluded,
    }

    output_path.write_text(json.dumps(out_payload, indent=2), encoding="utf-8")
    print(f"Wrote parsed data to:  {output_path}")
    print(f"Sessions:              {out_payload['session_count']}")
    print(f"Swim stints:           {out_payload['total_swim_stints']}")
    print(f"Catches parsed:        {out_payload['total_catches']}")
    print(f"Excluded items:        {out_payload['excluded_count']}")
    print(f"Context lines folded:  {out_payload['context_lines_folded']}")
    print("\nSample first 5 parsed catches:")
    shown = 0
    for s in enriched_sessions:
        for c in s["catches"]:
            print(
                f"  • [{s['temp_session_id']}] {c['caught_at']} | {c['swim_name']} | "
                f"{c['rod']} | {c['carp_type']} | {c['weight_grams']}g | "
                f"{c['moon_illumination_pct']}% {c['moon_phase']}"
            )
            shown += 1
            if shown >= 5:
                break
        if shown >= 5:
            break


if __name__ == "__main__":
    main()