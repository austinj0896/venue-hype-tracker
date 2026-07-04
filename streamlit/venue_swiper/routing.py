"""Walking routes via OpenRouteService (free tier) with haversine fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from geo import estimate_walk_minutes, haversine_m

ORS_MATRIX_URL = "https://api.openrouteservice.org/v2/matrix/foot-walking"


@dataclass(frozen=True)
class WalkRoute:
    distance_m: float
    duration_min: float
    source: str  # "ors" | "estimate"


def walk_route_pair(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    *,
    api_key: str | None = None,
    timeout: int = 15,
) -> WalkRoute:
    """Single origin→destination walk route."""
    straight_m = haversine_m(lat1, lon1, lat2, lon2)
    if not api_key:
        return WalkRoute(
            distance_m=straight_m,
            duration_min=estimate_walk_minutes(straight_m),
            source="estimate",
        )

    try:
        result = ors_walk_matrix(
            locations=[(lon1, lat1), (lon2, lat2)],
            sources=[0],
            destinations=[1],
            api_key=api_key,
            timeout=timeout,
        )
        if result:
            return result[0]
    except Exception:
        pass

    return WalkRoute(
        distance_m=straight_m,
        duration_min=estimate_walk_minutes(straight_m),
        source="estimate",
    )


def ors_walk_matrix(
    *,
    locations: list[tuple[float, float]],
    sources: list[int],
    destinations: list[int],
    api_key: str,
    timeout: int = 20,
) -> list[WalkRoute]:
    """
    ORS matrix for foot-walking. locations are (lon, lat) pairs.
    Returns one WalkRoute per (source, destination) pair in row-major order.
    """
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "locations": [[lon, lat] for lon, lat in locations],
        "sources": sources,
        "destinations": destinations,
        "metrics": ["distance", "duration"],
    }
    resp = requests.post(ORS_MATRIX_URL, headers=headers, json=body, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    distances = data.get("distances") or []
    durations = data.get("durations") or []
    routes: list[WalkRoute] = []

    for i, src_idx in enumerate(sources):
        row_d = distances[i] if i < len(distances) else []
        row_t = durations[i] if i < len(durations) else []
        for j, dst_idx in enumerate(destinations):
            dist = row_d[j] if j < len(row_d) else None
            dur_s = row_t[j] if j < len(row_t) else None
            if dist is None or dur_s is None:
                lon_a, lat_a = locations[src_idx]
                lon_b, lat_b = locations[dst_idx]
                straight = haversine_m(lat_a, lon_a, lat_b, lon_b)
                routes.append(
                    WalkRoute(
                        distance_m=straight,
                        duration_min=estimate_walk_minutes(straight),
                        source="estimate",
                    )
                )
            else:
                routes.append(
                    WalkRoute(
                        distance_m=float(dist),
                        duration_min=float(dur_s) / 60.0,
                        source="ors",
                    )
                )
    return routes


def refine_pair_routes(
    pairs: list[tuple[dict, dict]],
    *,
    api_key: str | None,
    max_ors_calls: int = 25,
) -> list[tuple[dict, dict, WalkRoute]]:
    """
    Hybrid Option C: pairs should already be haversine-filtered.
    Refines up to max_ors_calls with ORS; rest use straight-line estimate.
    """
    refined: list[tuple[dict, dict, WalkRoute]] = []
    for idx, (a, b) in enumerate(pairs):
        lat_a, lon_a = float(a["LATITUDE"]), float(a["LONGITUDE"])
        lat_b, lon_b = float(b["LATITUDE"]), float(b["LONGITUDE"])
        if api_key and idx < max_ors_calls:
            route = walk_route_pair(lat_a, lon_a, lat_b, lon_b, api_key=api_key)
        else:
            straight = haversine_m(lat_a, lon_a, lat_b, lon_b)
            route = WalkRoute(
                distance_m=straight,
                duration_min=estimate_walk_minutes(straight),
                source="estimate",
            )
        refined.append((a, b, route))
    return refined
