"""Google Places API (New) Nearby Search helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

import requests

PLACES_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"

FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.shortFormattedAddress,"
    "places.location,places.types,places.primaryType,places.businessStatus,"
    "places.rating,places.userRatingCount,places.priceLevel,places.websiteUri"
)

MANHATTAN_BOUNDS = {
    "south": 40.700,
    "north": 40.880,
    "west": -74.026,
    "east": -73.907,
}

KIPS_BAY_BOUNDS = {
    "south": 40.736,
    "north": 40.749,
    "west": -73.985,
    "east": -73.965,
}

# Murray Hill (~34th–42nd St, Madison Ave to East River).
MURRAY_HILL_BOUNDS = {
    "south": 40.747,
    "north": 40.757,
    "west": -73.988,
    "east": -73.962,
}

# Manhattan Beach, CA — land bbox (Strand/Sepulveda); west edge avoids Pacific grid cells.
MANHATTAN_BEACH_BOUNDS = {
    "south": 33.874,
    "north": 33.900,
    "west": -118.422,
    "east": -118.400,
}

DEFAULT_INCLUDED_TYPES = ("restaurant", "bar", "night_club", "cafe", "event_venue")


@dataclass(frozen=True)
class AreaPreset:
    bounds: dict[str, float]
    label: str
    borough: str
    lat_steps: int = 1
    lon_steps: int = 1
    radius_m: float = 800.0
    dense_lat_steps: int = 3
    dense_lon_steps: int = 3
    dense_radius_m: float = 550.0

    @property
    def slug(self) -> str:
        return self.label.lower().replace(" ", "_")

    def grid(self, *, dense: bool) -> tuple[int, int, float]:
        if dense:
            return (self.dense_lat_steps, self.dense_lon_steps, self.dense_radius_m)
        return (self.lat_steps, self.lon_steps, self.radius_m)


AREA_PRESETS: dict[str, AreaPreset] = {
    "kips_bay": AreaPreset(KIPS_BAY_BOUNDS, "Kips Bay", "Manhattan"),
    "murray_hill": AreaPreset(MURRAY_HILL_BOUNDS, "Murray Hill", "Manhattan"),
    "manhattan_beach": AreaPreset(
        MANHATTAN_BEACH_BOUNDS,
        "Manhattan Beach",
        "Manhattan Beach",
        radius_m=750.0,
        dense_lat_steps=2,
        dense_lon_steps=4,
        dense_radius_m=650.0,
    ),
}


def iter_grid(
    *,
    south: float,
    north: float,
    west: float,
    east: float,
    lat_steps: int,
    lon_steps: int,
) -> Iterable[tuple[float, float]]:
    if lat_steps < 1 or lon_steps < 1:
        raise ValueError("lat_steps and lon_steps must be >= 1")
    lat_delta = (north - south) / lat_steps
    lon_delta = (east - west) / lon_steps
    for r in range(lat_steps):
        lat = south + (r + 0.5) * lat_delta
        for c in range(lon_steps):
            lon = west + (c + 0.5) * lon_delta
            yield (lat, lon)


def nearby_search(
    *,
    api_key: str,
    latitude: float,
    longitude: float,
    radius_m: float,
    included_types: list[str],
    max_result_count: int = 20,
) -> dict[str, Any]:
    body = {
        "includedTypes": included_types,
        "maxResultCount": max_result_count,
        "rankPreference": "POPULARITY",
        "locationRestriction": {
            "circle": {
                "center": {"latitude": latitude, "longitude": longitude},
                "radius": radius_m,
            }
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    resp = requests.post(PLACES_NEARBY_URL, headers=headers, json=body, timeout=60)
    if not resp.ok:
        try:
            detail = resp.json()
        except Exception:  # noqa: BLE001
            detail = resp.text
        raise RuntimeError(f"Places API error {resp.status_code}: {detail}")
    return resp.json()


def parse_place_row(p: dict[str, Any], *, borough: str, source: str) -> dict[str, Any]:
    place_id = (p.get("id") or "").strip()
    if not place_id:
        res = (p.get("name") or "").strip()
        if res.startswith("places/"):
            place_id = res.split("/", 1)[1]
    if not place_id:
        raise ValueError(f"Missing place id in response: {json.dumps(p)[:500]}")

    dn = p.get("displayName") or {}
    name = (dn.get("text") or "").strip() or None

    loc = p.get("location") or {}
    lat = loc.get("latitude")
    lng = loc.get("longitude")
    lat_f = float(lat) if lat is not None else None
    lng_f = float(lng) if lng is not None else None

    types = list(p.get("types") or [])
    primary = p.get("primaryType")
    primary_s = str(primary) if primary else None

    rating = p.get("rating")
    rating_f = float(rating) if rating is not None else None

    urc = p.get("userRatingCount")
    urc_i = int(urc) if urc is not None else None

    pl = p.get("priceLevel")
    pl_s = str(pl) if pl is not None else None

    return {
        "google_place_id": place_id,
        "name": name,
        "formatted_address": p.get("formattedAddress"),
        "short_formatted_address": p.get("shortFormattedAddress"),
        "latitude": lat_f,
        "longitude": lng_f,
        "primary_type": primary_s,
        "types": types,
        "business_status": p.get("businessStatus"),
        "rating": rating_f,
        "user_rating_count": urc_i,
        "price_level": pl_s,
        "website_uri": p.get("websiteUri"),
        "borough": borough,
        "source": source,
    }
