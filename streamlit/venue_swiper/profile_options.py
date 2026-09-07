"""Canonical options for Après user profile questionnaire.

Kept separate from scripts/vibe_taxonomy.py (catalog tags for venues).
"""

from __future__ import annotations

from typing import Any

# Cities we support for profile + neighbourhood selection (forced pick).
DEFAULT_CITIES = [
    "Manhattan Beach",
    "Hermosa Beach",
    "Redondo Beach",
    "El Segundo",
    "Torrance",
    "Lawndale",
    "Hawthorne",
    "Gardena",
    "Lomita",
    "Carson",
    "Palos Verdes Estates",
    "Rancho Palos Verdes",
    "Rolling Hills Estates",
    "Playa del Rey",
    "Marina del Rey",
    "Venice",
    "Westchester",
    "Culver City",
    "Santa Monica",
    "Inglewood",
    "Los Angeles",
    "New York",
]

# Neighbourhoods / sections keyed by city. Keep exhaustive for supported cities.
NEIGHBOURHOODS_BY_CITY: dict[str, list[str]] = {
    "Manhattan Beach": [
        "El Porto",
        "Sand Section",
        "Tree Section",
        "Hill Section",
        "Downtown / Pier",
        "The Strand",
        "East Manhattan Beach",
        "Marine Avenue corridor",
        "Polliwog Park area",
    ],
    "Hermosa Beach": [
        "Pier Avenue / Downtown",
        "The Strand",
        "North Hermosa",
        "South Hermosa",
        "Hermosa Valley (Upper Hermosa)",
        "Hermosa Avenue corridor",
    ],
    "Redondo Beach": [
        "North Redondo",
        "South Redondo",
        "Riviera Village",
        "King Harbor / Harbor area",
        "Esplanade",
        "The Pier / International Boardwalk",
        "Avenues / South Bay Galleria area",
        "Torrance Blvd corridor",
    ],
    "El Segundo": [
        "Downtown El Segundo",
        "Smoky Hollow",
        "Hilltop",
        "East El Segundo",
        "Imperial / Beach corridor",
        "Main Street corridor",
    ],
    "Torrance": [
        "Old Torrance",
        "Downtown Torrance",
        "Walteria",
        "Hollywood Riviera",
        "Southwood",
        "West Torrance",
        "East Torrance",
        "Torrance Heights",
        "Madrona",
        "Seaside",
        "Del Amo / Plaza area",
        "New Horizons",
        "Southeast Torrance",
    ],
    "Lawndale": [
        "North Lawndale",
        "South Lawndale",
        "Downtown Lawndale",
        "Marine Avenue corridor",
        "Hawthorne Blvd corridor",
    ],
    "Hawthorne": [
        "Downtown Hawthorne",
        "North Hawthorne",
        "South Hawthorne",
        "Holly Park",
        "Ramona",
        "Bodger Park area",
        "Hawthorne Blvd corridor",
    ],
    "Gardena": [
        "Downtown Gardena",
        "North Gardena",
        "South Gardena",
        "West Gardena",
        "East Gardena",
        "Gardena Blvd corridor",
    ],
    "Lomita": [
        "Downtown Lomita",
        "North Lomita",
        "South Lomita",
        "West Lomita",
        "Pacific Coast Highway corridor",
    ],
    "Carson": [
        "North Carson",
        "South Carson",
        "East Carson",
        "West Carson",
        "Carson Street corridor",
        "Dominguez area",
    ],
    "Palos Verdes Estates": [
        "Malaga Cove",
        "Lunada Bay",
        "Valmonte",
        "Margate",
        "PV Drive corridor",
    ],
    "Rancho Palos Verdes": [
        "Portuguese Bend",
        "Trump National / Oceanfront",
        "Eastview",
        "Ridgecrest",
        "Miraleste",
        "Hesse Park area",
        "PV Drive East / West corridor",
    ],
    "Rolling Hills Estates": [
        "The Village / Peninsula Center",
        "Dapplegray area",
        "Empty Saddle area",
        "PV Drive North corridor",
    ],
    "Playa del Rey": [
        "The Bluffs",
        "Beach / Culver corridor",
        "Surfridge / Dockweiler area",
        "Westchester bluffs edge",
    ],
    "Marina del Rey": [
        "Harbor / Marina waterside",
        "Washington Blvd corridor",
        "Admiralty Way corridor",
        "Villa Marina area",
        "Mother's Beach area",
    ],
    "Venice": [
        "Venice Beach / Boardwalk",
        "Abbot Kinney",
        "Oakwood",
        "Milwood",
        "Silver Triangle",
        "Oxford Triangle",
        "Venice Canals",
        "North Venice",
    ],
    "Westchester": [
        "Downtown Westchester / Loyola",
        "Kentwood",
        "LMU area",
        "Westchester Park area",
        "Airport corridor",
    ],
    "Culver City": [
        "Downtown Culver City",
        "Culver City Arts District",
        "Fox Hills",
        "Blair Hills",
        "Sunkist Park",
        "Culver West",
        "Studio District / Lucerne",
        "Jefferson / Hayden corridor",
    ],
    "Santa Monica": [
        "Downtown / Promenade",
        "Ocean Park",
        "Montana Avenue",
        "North of Montana",
        "Pico",
        "Mid-City",
        "Sunset Park",
        "Wilshire / Montana",
        "Main Street corridor",
    ],
    "Inglewood": [
        "Downtown Inglewood",
        "North Inglewood",
        "Morningside Park",
        "Lockhaven",
        "Centinela area",
        "Forum / SoFi Stadium area",
    ],
    "Los Angeles": [
        "Venice",
        "Mar Vista",
        "Palms",
        "West LA / Sawtelle",
        "Brentwood",
        "Westwood",
        "Century City",
        "Beverly Grove",
        "Mid-Wilshire",
        "Koreatown",
        "Hancock Park",
        "Hollywood",
        "East Hollywood",
        "Los Feliz",
        "Silver Lake",
        "Echo Park",
        "Downtown LA",
        "Arts District",
        "Highland Park",
        "Eagle Rock",
        "Atwater Village",
        "South LA",
        "Crenshaw",
        "Leimert Park",
        "Jefferson Park",
        "Exposition Park",
        "San Pedro",
        "Wilmington",
        "Harbor City",
        "Other LA neighbourhood",
    ],
    "New York": [
        "Kips Bay",
        "Murray Hill",
        "Gramercy",
        "Flatiron",
        "Nomad",
        "Rose Hill",
        "Stuyvesant Town / Peter Cooper Village",
        "East Village",
        "West Village",
        "Greenwich Village",
        "Union Square",
        "Chelsea",
        "Midtown East",
        "Midtown West",
        "Upper East Side",
        "Upper West Side",
        "Lower East Side",
        "SoHo",
        "Tribeca",
        "Financial District",
        "Hell's Kitchen",
        "Harlem",
        "Williamsburg",
        "Greenpoint",
        "DUMBO",
        "Brooklyn Heights",
        "Park Slope",
        "Astoria",
        "Long Island City",
        "Other NYC neighbourhood",
    ],
}

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

# Relationship / connection (Après-flavored keys + labels).
RELATIONSHIP_STATUS_SOLO = frozenset({"flying_solo", "complicated"})
RELATIONSHIP_STATUS_PARTNERED = frozenset({"seeing_someone", "coupled_up"})
RELATIONSHIP_STATUS_KEYS = (
    "flying_solo",
    "complicated",
    "seeing_someone",
    "coupled_up",
)
RELATIONSHIP_STATUS_LABELS: dict[str, str] = {
    "flying_solo": "Flying solo",
    "complicated": "It's complicated",
    "seeing_someone": "Seeing someone",
    "coupled_up": "Coupled up",
}
OPEN_TO_DATES_LABELS: dict[bool, str] = {
    True: "Open to dates",
    False: "Not right now",
}


# --- Extended profile mini-quests (post-signup, optional) -----------------

CUISINE_OPTIONS = [
    "Italian",
    "Sushi / Japanese",
    "Mexican",
    "French",
    "Mediterranean",
    "Steak / American",
    "Thai",
    "Indian",
    "Seafood",
    "Korean",
    "Chinese",
    "Something unexpected",
]

FOOD_VIBE_OPTIONS = [
    "Intimate",
    "Shared plates",
    "Tasting menu",
    "Casual & easy",
    "Celebration",
    "Late-night bites",
]

DRINKING_VIBE_OPTIONS: list[tuple[str, str]] = [
    ("dry", "Mostly dry"),
    ("wine_forward", "Wine-forward"),
    ("cocktails_forward", "Cocktails-forward"),
    ("beer_casual", "Beer & casual"),
    ("anything_goes", "Anything goes"),
]

BUDGET_LEVEL_OPTIONS: list[tuple[str, str]] = [
    ("easy", "Easygoing"),
    ("nice", "A nice night"),
    ("treat", "Treat yourself"),
    ("splurge", "Special occasion"),
]

NIGHT_PACE_OPTIONS: list[tuple[str, str]] = [
    ("early_soft", "Early soft landing"),
    ("golden_hour_into_dinner", "Golden hour into dinner"),
    ("dinner_then_drinks", "Dinner then drinks"),
    ("late_last_call", "Late last call"),
]

MUSIC_VIBE_OPTIONS = [
    "Jazz",
    "Soft electronic",
    "Indie / acoustic",
    "Latin",
    "Classic lounge",
    "Upbeat dance",
    "Quiet enough to talk",
    "Whatever the room wants",
]

USUALLY_FREE_OPTIONS = [
    "Mon",
    "Tue",
    "Wed",
    "Thu",
    "Fri",
    "Sat",
    "Sun",
    "Weeknights",
    "Weekends",
]

ADVENTURE_LEVEL_OPTIONS: list[tuple[str, str]] = [
    ("favorites", "Stick to favorites"),
    ("mix", "A healthy mix"),
    ("firsts", "Always chasing firsts"),
]

DEAL_BREAKER_OPTIONS = [
    "Loud sports bars",
    "Crowded clubs",
    "Long waits",
    "Very formal dress codes",
    "Smoke-heavy rooms",
    "Far from transit / parking",
    "Too quiet / dead rooms",
    "Overly touristy spots",
]


def _quest_field(
    *,
    key: str,
    label: str,
    kind: str,
    options: list[Any],
    max_choices: int | None = None,
) -> dict[str, Any]:
    field: dict[str, Any] = {
        "key": key,
        "label": label,
        "kind": kind,
        "options": options,
    }
    if max_choices is not None:
        field["max"] = max_choices
    return field


# Driven UI metadata for the Go deeper hub + quest screens.
QUESTS: list[dict[str, Any]] = [
    {
        "id": "taste",
        "title": "Tonight’s taste",
        "eyebrow": "Chapter 01",
        "blurb": "What do you lean toward when the night starts with food?",
        "fields": [
            _quest_field(
                key="cuisines",
                label="Cuisines you reach for",
                kind="multi",
                options=CUISINE_OPTIONS,
                max_choices=5,
            ),
            _quest_field(
                key="food_vibes",
                label="The mood at the table",
                kind="multi",
                options=FOOD_VIBE_OPTIONS,
                max_choices=3,
            ),
        ],
    },
    {
        "id": "drink",
        "title": "How you drink",
        "eyebrow": "Chapter 02",
        "blurb": "From dry to deep pour — what’s your default?",
        "fields": [
            _quest_field(
                key="drinking_vibe",
                label="Your drinking vibe",
                kind="single",
                options=DRINKING_VIBE_OPTIONS,
            ),
        ],
    },
    {
        "id": "budget",
        "title": "The bill",
        "eyebrow": "Chapter 03",
        "blurb": "Comfort zone for a night out — no judgment.",
        "fields": [
            _quest_field(
                key="budget_level",
                label="Spend comfort",
                kind="single",
                options=BUDGET_LEVEL_OPTIONS,
            ),
        ],
    },
    {
        "id": "pace",
        "title": "Pace of night",
        "eyebrow": "Chapter 04",
        "blurb": "Soft landing, or still going when the lights come up?",
        "fields": [
            _quest_field(
                key="night_pace",
                label="How the evening usually unfolds",
                kind="single",
                options=NIGHT_PACE_OPTIONS,
            ),
        ],
    },
    {
        "id": "soundtrack",
        "title": "Soundtrack",
        "eyebrow": "Chapter 05",
        "blurb": "What should the room sound like?",
        "fields": [
            _quest_field(
                key="music_vibes",
                label="Sounds that fit",
                kind="multi",
                options=MUSIC_VIBE_OPTIONS,
                max_choices=4,
            ),
        ],
    },
    {
        "id": "free",
        "title": "Usually free",
        "eyebrow": "Chapter 06",
        "blurb": "When plans actually happen.",
        "fields": [
            _quest_field(
                key="usually_free",
                label="You’re most free",
                kind="multi",
                options=USUALLY_FREE_OPTIONS,
                max_choices=5,
            ),
        ],
    },
    {
        "id": "adventure",
        "title": "Adventure level",
        "eyebrow": "Chapter 07",
        "blurb": "Familiar favorites, or always chasing firsts?",
        "fields": [
            _quest_field(
                key="adventure_level",
                label="Your appetite for new",
                kind="single",
                options=ADVENTURE_LEVEL_OPTIONS,
            ),
        ],
    },
    {
        "id": "hard_nos",
        "title": "Hard nos",
        "eyebrow": "Chapter 08",
        "blurb": "Soft passes and true deal-breakers.",
        "fields": [
            _quest_field(
                key="deal_breakers",
                label="Rather skip",
                kind="multi",
                options=DEAL_BREAKER_OPTIONS,
                max_choices=5,
            ),
        ],
    },
]

QUEST_IDS: tuple[str, ...] = tuple(str(q["id"]) for q in QUESTS)

# Keys that belong to each quest — used for completion checks / partial saves.
QUEST_KEYS: dict[str, tuple[str, ...]] = {
    str(q["id"]): tuple(str(f["key"]) for f in q["fields"]) for q in QUESTS
}


def quest_by_id(quest_id: str) -> dict[str, Any] | None:
    key = (quest_id or "").strip()
    for quest in QUESTS:
        if quest["id"] == key:
            return quest
    return None


def label_for_choice(options: list[Any], value: str | None) -> str:
    """Resolve a stored single-select key to its display label."""
    if not value:
        return ""
    for opt in options:
        if isinstance(opt, tuple) and len(opt) >= 2:
            if opt[0] == value:
                return str(opt[1])
        elif str(opt) == value:
            return str(opt)
    return str(value)


def relationship_status_label(status: str | None) -> str:
    key = (status or "").strip()
    return RELATIONSHIP_STATUS_LABELS.get(key, "")


def relationship_preview_line(
    status: str | None,
    open_to_dates: bool | None = None,
) -> str:
    """Short line for the dating-style preview card."""
    label = relationship_status_label(status)
    if not label:
        return ""
    key = (status or "").strip()
    if key in RELATIONSHIP_STATUS_SOLO and open_to_dates is True:
        return f"{label} · Open to dates"
    if key in RELATIONSHIP_STATUS_SOLO and open_to_dates is False:
        return f"{label} · Not right now"
    return label


def compute_profile_visibility(
    status: str | None,
    open_to_dates: bool | None,
) -> str:
    """public only when solo/complicated and explicitly open to dates."""
    key = (status or "").strip()
    if key in RELATIONSHIP_STATUS_PARTNERED:
        return "private"
    if key in RELATIONSHIP_STATUS_SOLO and open_to_dates is True:
        return "public"
    return "private"

# Soft Discover bias: profile activities → Google Places primary_type values.
ACTIVITY_TO_PRIMARY_TYPES: dict[str, tuple[str, ...]] = {
    "Dining": (
        "restaurant",
        "american_restaurant",
        "italian_restaurant",
        "mexican_restaurant",
        "japanese_restaurant",
        "chinese_restaurant",
        "thai_restaurant",
        "french_restaurant",
        "greek_restaurant",
        "seafood_restaurant",
        "sushi_restaurant",
        "steak_house",
        "pizza_restaurant",
        "brunch_restaurant",
        "breakfast_restaurant",
        "diner",
    ),
    "Coffee & cafes": ("cafe", "coffee_shop", "bakery", "bagel_shop", "juice_shop"),
    "Wine bars": ("bar", "pub", "irish_pub"),
    "Cocktail bars": ("bar", "pub", "irish_pub", "night_club"),
    "Live music": ("bar", "night_club", "event_venue", "pub"),
    "Rooftop / scenic": ("bar", "restaurant", "night_club", "american_restaurant"),
    "Outdoor dining": (
        "restaurant",
        "cafe",
        "american_restaurant",
        "mexican_restaurant",
        "brunch_restaurant",
        "seafood_restaurant",
    ),
    "Casual bites": (
        "fast_food_restaurant",
        "sandwich_shop",
        "pizza_restaurant",
        "bagel_shop",
        "bakery",
        "cafe",
        "diner",
        "mexican_restaurant",
    ),
    "Fine dining": (
        "steak_house",
        "french_restaurant",
        "seafood_restaurant",
        "sushi_restaurant",
        "japanese_restaurant",
        "restaurant",
    ),
    "Nightlife / dancing": ("night_club", "bar", "event_venue"),
    "Culture / galleries": ("cafe", "event_venue", "restaurant"),
    "Wellness": ("juice_shop", "cafe", "coffee_shop"),
    "Sports / active": ("sports_bar", "bar", "pub", "american_restaurant"),
    "Experiences / tasting menus": (
        "restaurant",
        "steak_house",
        "sushi_restaurant",
        "french_restaurant",
        "japanese_restaurant",
        "bar",
    ),
}


def neighbourhoods_for_city(city: str) -> list[str]:
    """Return forced neighbourhood options for a city (empty if unsupported)."""
    return list(NEIGHBOURHOODS_BY_CITY.get((city or "").strip(), []))


def preferred_types_from_activities(activities: list[str] | None) -> list[str]:
    """Flatten activity prefs into primary_type values for soft Discover ranking."""
    preferred: set[str] = set()
    for activity in activities or []:
        preferred.update(ACTIVITY_TO_PRIMARY_TYPES.get(str(activity).strip(), ()))
    return sorted(preferred)
