"""Canonical options for Après user profile questionnaire.

Kept separate from scripts/vibe_taxonomy.py (catalog tags for venues).
"""

from __future__ import annotations

# Seed cities; app also offers free-text "Add my city".
DEFAULT_CITIES = [
    "Manhattan Beach",
    "Hermosa Beach",
    "Redondo Beach",
    "El Segundo",
    "Torrance",
    "Santa Monica",
    "Los Angeles",
]

DIETARY_OPTIONS = [
    "None",
    "Vegetarian",
    "Vegan",
    "Gluten-free",
    "Halal",
    "Kosher",
    "Nut allergy",
    "Dairy-free",
    "Pescatarian",
    "Other",
]

ACTIVITY_OPTIONS = [
    "Dining",
    "Coffee & cafes",
    "Wine bars",
    "Cocktail bars",
    "Live music",
    "Rooftop / scenic",
    "Outdoor dining",
    "Casual bites",
    "Fine dining",
    "Nightlife / dancing",
    "Culture / galleries",
    "Wellness",
    "Sports / active",
    "Experiences / tasting menus",
]

CUSTOM_CITY_SENTINEL = "Add my city…"
