"""Two-stop date pairing: restaurant + bar/cafe/club within walking distance."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Iterable

from geo import haversine_m, miles_to_meters
from routing import WalkRoute, refine_pair_routes

# --- Venue type buckets (Google primary_type values) ---

RESTAURANT_TYPES = frozenset(
    {
        "restaurant",
        "american_restaurant",
        "breakfast_restaurant",
        "brunch_restaurant",
        "chinese_restaurant",
        "diner",
        "fast_food_restaurant",
        "french_restaurant",
        "greek_restaurant",
        "italian_restaurant",
        "japanese_restaurant",
        "mexican_restaurant",
        "pizza_restaurant",
        "sandwich_shop",
        "seafood_restaurant",
        "steak_house",
        "sushi_restaurant",
        "thai_restaurant",
    }
)

BAR_TYPES = frozenset(
    {
        "bar",
        "pub",
        "sports_bar",
        "irish_pub",
        "wine_bar",
        "cocktail_bar",
    }
)

CLUB_TYPES = frozenset({"night_club"})

CAFE_TYPES = frozenset(
    {
        "cafe",
        "coffee_shop",
        "bakery",
        "bagel_shop",
        "juice_shop",
    }
)


@dataclass(frozen=True)
class DateCombo:
    id: str
    label: str
    first_label: str
    second_label: str
    first_types: frozenset[str]
    second_types: frozenset[str]


DATE_COMBOS: tuple[DateCombo, ...] = (
    DateCombo(
        id="dinner_drinks",
        label="Dinner + Drinks",
        first_label="Dinner",
        second_label="Drinks",
        first_types=RESTAURANT_TYPES,
        second_types=BAR_TYPES,
    ),
    DateCombo(
        id="dinner_coffee",
        label="Dinner + Coffee",
        first_label="Dinner",
        second_label="Coffee",
        first_types=RESTAURANT_TYPES,
        second_types=CAFE_TYPES,
    ),
    DateCombo(
        id="dinner_club",
        label="Dinner + Club",
        first_label="Dinner",
        second_label="Club",
        first_types=RESTAURANT_TYPES,
        second_types=CLUB_TYPES,
    ),
    DateCombo(
        id="coffee_drinks",
        label="Coffee + Drinks",
        first_label="Coffee",
        second_label="Drinks",
        first_types=CAFE_TYPES,
        second_types=BAR_TYPES,
    ),
    DateCombo(
        id="coffee_club",
        label="Coffee + Club",
        first_label="Coffee",
        second_label="Club",
        first_types=CAFE_TYPES,
        second_types=CLUB_TYPES,
    ),
)


@dataclass(frozen=True)
class VenueRatingStats:
    avg_rating: float
    rating_count: int


RatingLookup = dict[str, VenueRatingStats]


def venue_pick_weight(stats: VenueRatingStats | None) -> float:
    """
    Weight for random selection: favor community favorites and unrated spots.
    Low-rated venues can still appear but rarely.
    """
    if stats is None or stats.rating_count == 0:
        return 1.0
    avg = stats.avg_rating
    if avg >= 4.5:
        return 1.0
    if avg >= 4.0:
        return 0.92
    if avg >= 3.5:
        return 0.5
    if avg >= 3.0:
        return 0.25
    return 0.08


def _stats_for_venue(venue: dict[str, Any], rating_stats: RatingLookup) -> VenueRatingStats | None:
    pid = str(venue.get("GOOGLE_PLACE_ID") or "")
    return rating_stats.get(pid)


def plan_pick_weight(plan: DatePlan, rating_stats: RatingLookup) -> float:
    w1 = venue_pick_weight(_stats_for_venue(plan.first_stop, rating_stats))
    w2 = venue_pick_weight(_stats_for_venue(plan.second_stop, rating_stats))
    return (w1 * w2) ** 0.5


def shuffle_date_plans(
    plans: list[DatePlan],
    rating_stats: RatingLookup,
    *,
    max_results: int = 12,
    rng: random.Random | None = None,
) -> list[DatePlan]:
    """
    Weighted random order: high-rated and unrated venues surface more often,
    but each shuffle differs.
    """
    if not plans:
        return []
    rng = rng or random.Random()

    def sort_key(plan: DatePlan) -> float:
        weight = max(plan_pick_weight(plan, rating_stats), 0.05)
        walk_bonus = 1.0 / (1.0 + plan.walk.duration_min / 25.0)
        # Higher weight → larger random key on average (random ** (1/weight))
        return (rng.random() ** (1.0 / weight)) * walk_bonus

    ranked = sorted(plans, key=sort_key, reverse=True)
    return ranked[:max_results]


def rating_badge_label(stats: VenueRatingStats | None) -> str:
    if stats is None or stats.rating_count == 0:
        return "New · unrated"
    return f"★ {stats.avg_rating:.1f} ({stats.rating_count} ratings)"


@dataclass
class DatePlan:
    combo: DateCombo
    first_stop: dict[str, Any]
    second_stop: dict[str, Any]
    walk: WalkRoute
    score: float


def _primary_type(venue: dict) -> str:
    return str(venue.get("PRIMARY_TYPE") or "").strip()


def _matches_types(venue: dict, allowed: frozenset[str]) -> bool:
    pt = _primary_type(venue)
    return pt in allowed


def split_venues_for_combo(
    venues: Iterable[dict],
    combo: DateCombo,
) -> tuple[list[dict], list[dict]]:
    first: list[dict] = []
    second: list[dict] = []
    for venue in venues:
        pt = _primary_type(venue)
        if pt in combo.first_types:
            first.append(venue)
        if pt in combo.second_types:
            second.append(venue)
    return first, second


def candidate_pairs_haversine(
    first_venues: list[dict],
    second_venues: list[dict],
    *,
    max_walk_m: float,
    max_candidates: int = 80,
) -> list[tuple[dict, dict, float]]:
    """
    Find (first, second) pairs within max_walk_m straight-line (Phase 1 filter).
    Returns list of (a, b, straight_m) sorted by distance.
    """
    pairs: list[tuple[dict, dict, float]] = []
    seen: set[tuple[str, str]] = set()

    for a in first_venues:
        lat_a = a.get("LATITUDE")
        lon_a = a.get("LONGITUDE")
        if lat_a is None or lon_a is None:
            continue
        id_a = a.get("GOOGLE_PLACE_ID") or ""

        for b in second_venues:
            id_b = b.get("GOOGLE_PLACE_ID") or ""
            if not id_b or id_a == id_b:
                continue
            lat_b = b.get("LATITUDE")
            lon_b = b.get("LONGITUDE")
            if lat_b is None or lon_b is None:
                continue

            dist = haversine_m(float(lat_a), float(lon_a), float(lat_b), float(lon_b))
            if dist > max_walk_m:
                continue

            key = (id_a, id_b)
            if key in seen:
                continue
            seen.add(key)
            pairs.append((a, b, dist))

    pairs.sort(key=lambda row: row[2])
    return pairs[:max_candidates]


def find_date_plans(
    venues_near_origin: list[dict],
    combo: DateCombo,
    *,
    max_walk_minutes: float,
    ors_api_key: str | None = None,
    max_results: int = 12,
    max_ors_calls: int = 25,
    rating_stats: RatingLookup | None = None,
    rng: random.Random | None = None,
) -> list[DatePlan]:
    """
    Hybrid pipeline:
      1. Split venues by combo type buckets
      2. Haversine pair filter (~15 min walk ≈ 0.75 mi straight line)
      3. ORS refine top candidates
      4. Filter by max_walk_minutes
      5. Weighted random shuffle (favor high-rated + unrated venues)
    """
    rating_stats = rating_stats or {}
    first_venues, second_venues = split_venues_for_combo(venues_near_origin, combo)
    if not first_venues or not second_venues:
        return []

    # Straight-line cap: ~4 mph effective → 15 min ≈ 1 mi; use generous 1.25 mi
    walk_mi = max(max_walk_minutes / 15.0 * 0.75, 0.25)
    max_walk_m = miles_to_meters(walk_mi)

    raw_pairs = candidate_pairs_haversine(
        first_venues,
        second_venues,
        max_walk_m=max_walk_m,
        max_candidates=120,
    )
    if not raw_pairs:
        return []

    pair_dicts = [(a, b) for a, b, _ in raw_pairs]
    refined = refine_pair_routes(pair_dicts, api_key=ors_api_key, max_ors_calls=max_ors_calls)

    plans: list[DatePlan] = []
    for (a, b, walk) in refined:
        if walk.duration_min > max_walk_minutes:
            continue
        origin_dist = float(a.get("_DIST_FROM_ORIGIN_M", 0)) + float(
            b.get("_DIST_FROM_ORIGIN_M", 0)
        )
        plans.append(
            DatePlan(
                combo=combo,
                first_stop=a,
                second_stop=b,
                walk=walk,
                score=walk.duration_min + origin_dist / 200.0,
            )
        )

    if not plans:
        return []

    return shuffle_date_plans(plans, rating_stats, max_results=max_results, rng=rng)


def combo_by_id(combo_id: str) -> DateCombo | None:
    for combo in DATE_COMBOS:
        if combo.id == combo_id:
            return combo
    return None


def venues_for_stop(
    nearby_venues: list[dict],
    combo: DateCombo,
    *,
    stop_index: int,
) -> list[dict]:
    """Venues eligible for stop 1 (index 0) or stop 2 (index 1)."""
    allowed = combo.first_types if stop_index == 0 else combo.second_types
    out: list[dict] = []
    for venue in nearby_venues:
        pt = str(venue.get("PRIMARY_TYPE") or "").strip()
        if pt in allowed:
            out.append(venue)
    out.sort(key=lambda v: (v.get("PLACE_NAME") or "").lower())
    return out


def rebuild_plan(
    combo: DateCombo,
    stop1: dict[str, Any],
    stop2: dict[str, Any],
    *,
    ors_api_key: str | None = None,
) -> DatePlan:
    from routing import walk_route_pair

    lat1, lon1 = float(stop1["LATITUDE"]), float(stop1["LONGITUDE"])
    lat2, lon2 = float(stop2["LATITUDE"]), float(stop2["LONGITUDE"])
    walk = walk_route_pair(lat1, lon1, lat2, lon2, api_key=ors_api_key)
    origin_dist = float(stop1.get("_DIST_FROM_ORIGIN_M", 0)) + float(
        stop2.get("_DIST_FROM_ORIGIN_M", 0)
    )
    return DatePlan(
        combo=combo,
        first_stop=stop1,
        second_stop=stop2,
        walk=walk,
        score=walk.duration_min + origin_dist / 200.0,
    )


def plan_pair_key(plan: DatePlan) -> tuple[str, str]:
    return (
        str(plan.first_stop.get("GOOGLE_PLACE_ID") or ""),
        str(plan.second_stop.get("GOOGLE_PLACE_ID") or ""),
    )


def pick_random_plan(
    pool: list[DatePlan],
    rating_stats: RatingLookup,
    *,
    exclude: DatePlan | None = None,
    rng: random.Random | None = None,
) -> DatePlan | None:
    if not pool:
        return None
    candidates = pool
    if exclude is not None:
        ex = plan_pair_key(exclude)
        filtered = [p for p in pool if plan_pair_key(p) != ex]
        if filtered:
            candidates = filtered
    shuffled = shuffle_date_plans(candidates, rating_stats, max_results=1, rng=rng)
    return shuffled[0] if shuffled else None

