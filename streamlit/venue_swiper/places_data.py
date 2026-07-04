"""Load venue catalog rows for date planning."""

from __future__ import annotations

from typing import Any

import streamlit as st

from date_planner import RatingLookup, VenueRatingStats
from db import places_table, ratings_table, run_query


@st.cache_data(show_spinner=False)
def fetch_community_ratings(borough: str | None = None) -> RatingLookup:
    """Aggregate rated venues across all Après users."""
    params: list[Any] = []
    borough_filter = ""
    if borough:
        borough_filter = "and borough = ?"
        params.append(borough)

    sql = f"""
        select
            google_place_id,
            avg(rating)::float as avg_rating,
            count(*)::int as rating_count
        from {ratings_table()}
        where status = 'rated'
          and rating is not null
          {borough_filter}
        group by google_place_id
    """
    rows = run_query(sql, params)
    out: RatingLookup = {}
    for row in rows:
        pid = str(row.get("GOOGLE_PLACE_ID") or "")
        if not pid:
            continue
        out[pid] = VenueRatingStats(
            avg_rating=float(row["AVG_RATING"] or 0),
            rating_count=int(row["RATING_COUNT"] or 0),
        )
    return out


@st.cache_data(show_spinner=False)
def fetch_venues_with_coords(borough: str, allowed_types: tuple[str, ...]) -> list[dict[str, Any]]:
    if not allowed_types:
        return []
    placeholders = ", ".join("?" for _ in allowed_types)
    sql = f"""
        select
            google_place_id,
            place_name,
            formatted_address,
            short_formatted_address,
            latitude,
            longitude,
            primary_type,
            venue_category,
            price_level,
            website_uri,
            borough
        from {places_table()}
        where borough = ?
          and latitude is not null
          and longitude is not null
          and primary_type in ({placeholders})
        order by place_name
    """
    return run_query(sql, [borough, *allowed_types])
