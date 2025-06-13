# utils.py
import re

def clean_price(price_str: str) -> float | None:
    """Cleans a raw price string to a float."""
    if not price_str:
        return None
    # Remove currency symbols, commas, and common rental duration texts
    cleaned = re.sub(r'[$,/mo/month]+', '', price_str, flags=re.IGNORECASE).strip()
    try:
        return float(cleaned)
    except ValueError:
        return None