"""Geospatial helpers — free, no external API."""

from __future__ import annotations

import math
from typing import Iterable

EARTH_RADIUS_M = 6_371_000
METERS_PER_MILE = 1609.344
DEFAULT_WALK_SPEED_MPH = 3.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return haversine_m(lat1, lon1, lat2, lon2) / METERS_PER_MILE


def miles_to_meters(mi: float) -> float:
    return mi * METERS_PER_MILE


def estimate_walk_minutes(distance_m: float, *, speed_mph: float = DEFAULT_WALK_SPEED_MPH) -> float:
    """Fallback when ORS is unavailable."""
    if distance_m <= 0:
        return 0.0
    miles = distance_m / METERS_PER_MILE
    return (miles / speed_mph) * 60.0


def bbox_for_radius(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """Approximate bounding box (south, north, west, east) for SQL pre-filter."""
    lat_delta = radius_m / EARTH_RADIUS_M * (180 / math.pi)
    lon_delta = radius_m / (EARTH_RADIUS_M * math.cos(math.radians(lat))) * (180 / math.pi)
    return (lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta)


def filter_by_radius(
    venues: Iterable[dict],
    *,
    origin_lat: float,
    origin_lon: float,
    radius_m: float,
    lat_key: str = "LATITUDE",
    lon_key: str = "LONGITUDE",
) -> list[dict]:
    out: list[dict] = []
    for venue in venues:
        lat = venue.get(lat_key)
        lon = venue.get(lon_key)
        if lat is None or lon is None:
            continue
        dist = haversine_m(origin_lat, origin_lon, float(lat), float(lon))
        if dist <= radius_m:
            row = dict(venue)
            row["_DIST_FROM_ORIGIN_M"] = dist
            out.append(row)
    out.sort(key=lambda v: v["_DIST_FROM_ORIGIN_M"])
    return out
