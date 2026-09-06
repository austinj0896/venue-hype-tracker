"""Greeting helpers (time-of-day from profile city timezone)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

# South Bay / LA–area cities in the profile list → local wall clock for greetings.
CITY_TIMEZONES: dict[str, str] = {
    "Manhattan Beach": "America/Los_Angeles",
    "Hermosa Beach": "America/Los_Angeles",
    "Redondo Beach": "America/Los_Angeles",
    "El Segundo": "America/Los_Angeles",
    "Torrance": "America/Los_Angeles",
    "Lawndale": "America/Los_Angeles",
    "Hawthorne": "America/Los_Angeles",
    "Gardena": "America/Los_Angeles",
    "Lomita": "America/Los_Angeles",
    "Carson": "America/Los_Angeles",
    "Palos Verdes Estates": "America/Los_Angeles",
    "Rancho Palos Verdes": "America/Los_Angeles",
    "Rolling Hills Estates": "America/Los_Angeles",
    "Playa del Rey": "America/Los_Angeles",
    "Marina del Rey": "America/Los_Angeles",
    "Venice": "America/Los_Angeles",
    "Westchester": "America/Los_Angeles",
    "Culver City": "America/Los_Angeles",
    "Santa Monica": "America/Los_Angeles",
    "Inglewood": "America/Los_Angeles",
    "Los Angeles": "America/Los_Angeles",
    "New York": "America/New_York",
}

DEFAULT_TZ = "America/Los_Angeles"


def timezone_for_city(city: str | None) -> str:
    return CITY_TIMEZONES.get((city or "").strip(), DEFAULT_TZ)


def time_of_day_greeting(city: str | None = None, *, now: datetime | None = None) -> str:
    """Return 'Good morning/afternoon/evening' from the profile city's clock."""
    tz_name = timezone_for_city(city)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(DEFAULT_TZ)
    local = now.astimezone(tz) if now is not None else datetime.now(tz)
    hour = local.hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


def personalized_greeting(first_name: str, city: str | None = None) -> str:
    name = (first_name or "").strip() or "there"
    return f"{time_of_day_greeting(city)}, {name}."
