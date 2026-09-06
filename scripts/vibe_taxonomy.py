"""Canonical Après vibe tags for local LLM classification."""

from __future__ import annotations

RESTAURANT_BAR_VIBES = [
    "Themed",
    "International - Globally inspired",
    "Vintage",
    "Funky",
    "Kitschy",
    "Contemporary",
    "Intimate",
    "Lively/Electric",
    "Moody",
    "Bubbly/vibrant",
    "Parents picking up the tab",
    "First date",
    "Staple (common date night)",
    "Casual",
    "Trendy",
    "Swanky",
    "Hole in the wall/ don't judge a book by it's cover",
    "Chill",
    "Farm to table",
    "Classic",
    "Rustic",
    "Exclusive",
]

BAR_SPECIFIC_VIBES = [
    "Sports bar",
    "Sport team bar",
    "Local beers",
    "Geographically diverse beers",
    "Innovative cocktails",
    "Unique wines",
    "Girlfriend friendly",
    "Standing room only",
    "Quick drink",
    "Make yourself at home",
    "Dive bar",
    "Dancing",
    "Karaoke",
    "Pool table",
    "Darts",
    "TV count",
    "Cigs inside",
]

GENERAL_TAGS = [
    "Loud",
    "Quiet",
    "Lively (high energy)",
    "Experience",
    "Pre-fixe",
    "Large menu",
    "Picky eater friendly",
    "Good for big groups",
    "Dog friendly",
    "Shared plates",
    "Dress code enforced",
    "Cash only",
    "Outdoor",
    "Indoor",
    "BYOB",
    "Wine bar",
    "Michelin rated",
    "Michelin recommended",
    "Grab and go",
    "Happy hour",
    "Local favorite",
    "Live music",
    "No reservations",
    "Walk-ins only",
    "Walk-in friendly",
    "Scenic",
    "Rooftop",
]

BARISH_TYPES = {
    "bar",
    "pub",
    "night_club",
    "wine_bar",
    "cocktail_bar",
    "sports_bar",
    "beer_garden",
}

TAXONOMY_GROUPS: list[tuple[str, list[str]]] = [
    ("restaurant_bar_vibes", RESTAURANT_BAR_VIBES),
    ("bar_specific", BAR_SPECIFIC_VIBES),
    ("general", GENERAL_TAGS),
]


def all_tags() -> list[str]:
    return [*RESTAURANT_BAR_VIBES, *BAR_SPECIFIC_VIBES, *GENERAL_TAGS]


def taxonomy_rows() -> list[dict[str, str | int]]:
    """Flat rows for syncing into Neon vibe_taxonomy."""
    rows: list[dict[str, str | int]] = []
    sort_order = 0
    for category, tags in TAXONOMY_GROUPS:
        for tag in tags:
            rows.append({"tag": tag, "category": category, "sort_order": sort_order})
            sort_order += 1
    return rows


def allowed_tags_for_type(primary_type: str | None) -> list[str]:
    """Bar-specific tags only for bar-ish Google types."""
    tags = [*RESTAURANT_BAR_VIBES, *GENERAL_TAGS]
    pt = (primary_type or "").strip().lower()
    if pt in BARISH_TYPES or "bar" in pt or "pub" in pt or "club" in pt:
        tags = [*tags, *BAR_SPECIFIC_VIBES]
    return tags


def taxonomy_prompt_block(allowed: list[str]) -> str:
    return "\n".join(f"- {tag}" for tag in allowed)
