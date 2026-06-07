"""SQLite helpers: schema init and place upserts."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection, schema_path: Path) -> None:
    sql = schema_path.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def upsert_place(
    conn: sqlite3.Connection,
    *,
    google_place_id: str,
    name: str | None,
    formatted_address: str | None,
    short_formatted_address: str | None,
    latitude: float | None,
    longitude: float | None,
    primary_type: str | None,
    types: list[str] | None,
    business_status: str | None,
    rating: float | None,
    user_rating_count: int | None,
    price_level: str | None,
    website_uri: str | None,
    borough: str,
    source: str,
    now_iso: str,
) -> None:
    types_json = json.dumps(types or [], ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO places (
          google_place_id, name, formatted_address, short_formatted_address,
          latitude, longitude, primary_type, types_json, business_status,
          rating, user_rating_count, price_level, website_uri,
          borough, source, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(google_place_id) DO UPDATE SET
          name = excluded.name,
          formatted_address = excluded.formatted_address,
          short_formatted_address = excluded.short_formatted_address,
          latitude = excluded.latitude,
          longitude = excluded.longitude,
          primary_type = excluded.primary_type,
          types_json = excluded.types_json,
          business_status = excluded.business_status,
          rating = excluded.rating,
          user_rating_count = excluded.user_rating_count,
          price_level = excluded.price_level,
          website_uri = excluded.website_uri,
          borough = excluded.borough,
          source = excluded.source,
          last_seen_at = excluded.last_seen_at
        """,
        (
            google_place_id,
            name,
            formatted_address,
            short_formatted_address,
            latitude,
            longitude,
            primary_type,
            types_json,
            business_status,
            rating,
            user_rating_count,
            price_level,
            website_uri,
            borough,
            source,
            now_iso,
            now_iso,
        ),
    )
