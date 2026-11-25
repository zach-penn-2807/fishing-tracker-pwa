from datetime import datetime


def grams_to_lb_oz(grams: int) -> str:
    """Convert integer grams into UK angler format, e.g., '9 lb 6 oz (4.25 kg)'."""
    if not grams or grams <= 0:
        return "0 lb 0 oz"
    total_oz = round(grams / 28.349523125)
    lbs, oz = divmod(total_oz, 16)
    kg = grams / 1000
    return f"{lbs} lb {oz} oz ({kg:.2f} kg)"


def lb_oz_to_grams(lbs: int, oz: float) -> int:
    """Convert pounds and ounces back into integer grams for database storage."""
    total_oz = (lbs * 16) + oz
    return max(1, round(total_oz * 28.349523125))


def kg_to_grams(kg: float) -> int:
    """Convert kilograms into integer grams for database storage."""
    return max(1, round(kg * 1000))


def format_timestamp(iso_str: str) -> str:
    """Turn an ISO timestamp like '2026-11-25T19:48:19' into '25 Nov, 19:48'."""
    dt = datetime.fromisoformat(iso_str)
    return dt.strftime("%d %b, %H:%M")