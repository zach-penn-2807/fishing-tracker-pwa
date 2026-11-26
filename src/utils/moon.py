from datetime import datetime, timezone
import math

SYNODIC_MONTH_DAYS = 29.53058867
NEW_MOON_EPOCH_UTC = datetime(2000, 1, 6, 18, 14, 0, tzinfo=timezone.utc)

MOON_PHASES = [
    "New Moon",
    "Waxing Crescent",
    "First Quarter",
    "Waxing Gibbous",
    "Full Moon",
    "Waning Gibbous",
    "Third Quarter",
    "Waning Crescent",
]


def calculate_moon_details(caught_at: datetime) -> dict:
    """Return moon illumination percentage, phase name, and cycle age for a timestamp."""
    dt_utc = (
        caught_at.replace(tzinfo=timezone.utc)
        if caught_at.tzinfo is None
        else caught_at.astimezone(timezone.utc)
    )
    elapsed_days = (dt_utc - NEW_MOON_EPOCH_UTC).total_seconds() / 86400.0
    age_days = elapsed_days % SYNODIC_MONTH_DAYS
    fraction = age_days / SYNODIC_MONTH_DAYS

    illumination_pct = round(((1.0 - math.cos(2.0 * math.pi * fraction)) / 2.0) * 100.0, 1)
    bucket_index = int(((fraction + (1.0 / 16.0)) % 1.0) * 8.0)
    phase_name = MOON_PHASES[bucket_index]

    return {
        "illumination_pct": illumination_pct,
        "phase_name": phase_name,
        "age_days": round(age_days, 2),
    }


def format_moon_label(illumination_pct: float, phase_name: str) -> str:
    """Format moon data consistently for badges and analytics labels."""
    return f"{illumination_pct:.1f}% ({phase_name})"