from datetime import datetime
import math

GRAMS_PER_OZ = 28.349523125
OZ_PER_LB = 16


def lb_oz_to_grams(pounds: int, ounces: float = 0.0) -> int:
    """Convert UK pounds and ounces to integer grams."""
    total_oz = (pounds * OZ_PER_LB) + ounces
    return int(round(total_oz * GRAMS_PER_OZ))


def kg_to_grams(kilograms: float) -> int:
    """Convert kilograms to integer grams."""
    return int(round(kilograms * 1000.0))


def grams_to_lb_oz(grams: int) -> tuple[int, int]:
    """Convert integer grams to (pounds, whole_ounces), carrying 16 oz -> +1 lb."""
    total_oz = round(grams / GRAMS_PER_OZ)
    pounds = total_oz // OZ_PER_LB
    ounces = total_oz % OZ_PER_LB
    return int(pounds), int(ounces)


def grams_to_kg(grams: int) -> float:
    """Convert integer grams to kilograms rounded to 2 decimal places."""
    return round(grams / 1000.0, 2)


def format_weight(grams: int, primary_unit: str = "lb", show_secondary: bool = True) -> str:
    """Format integer grams with either UK lb/oz or kg first."""
    lbs, oz = grams_to_lb_oz(grams)
    kg = grams_to_kg(grams)
    lb_str = f"{lbs} lb {oz} oz"
    kg_str = f"{kg:.2f} kg"

    if primary_unit == "kg":
        return f"{kg_str} ({lb_str})" if show_secondary else kg_str
    return f"{lb_str} ({kg_str})" if show_secondary else lb_str


def format_duration(start_iso: str, end_iso: str | None = None) -> str:
    """Format elapsed duration between ISO timestamps as 'Xh Ym'."""
    start_dt = datetime.fromisoformat(start_iso)
    end_dt = datetime.fromisoformat(end_iso) if end_iso else datetime.now()
    total_minutes = max(0, int((end_dt - start_dt).total_seconds() // 60))
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes}m"


def format_time_window(start_iso: str, end_iso: str | None = None) -> str:
    """Format a swim stint window like '12:00 – 13:00' or '12:00 – Ongoing'."""
    start_str = datetime.fromisoformat(start_iso).strftime("%H:%M")
    end_str = datetime.fromisoformat(end_iso).strftime("%H:%M") if end_iso else "Ongoing"
    return f"{start_str} – {end_str}"


def format_carp_ratio(mirror_count: int, common_count: int) -> str:
    """Format Mirror vs. Common share, simplified ratio, and raw counts."""
    total = mirror_count + common_count
    if total == 0:
        return "0% Mirror / 0% Common (0M / 0C)"
    mirror_pct = round((mirror_count / total) * 100)
    common_pct = 100 - mirror_pct
    divisor = math.gcd(mirror_count, common_count) if (mirror_count and common_count) else 1
    m_ratio = mirror_count // divisor
    c_ratio = common_count // divisor
    return f"{mirror_pct}% Mirror / {common_pct}% Common ({m_ratio}:{c_ratio} • {mirror_count}M / {common_count}C)"