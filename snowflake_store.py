"""Snowflake persistence for venue places and fetch runs."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

import snowflake.connector

from config import snowflake_settings


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _connect_kwargs() -> dict[str, Any]:
    s = snowflake_settings()
    kwargs: dict[str, Any] = {
        "account": s["account"],
        "user": s["user"],
        "warehouse": s["warehouse"],
        "database": s["database"],
        "schema": s["schema"],
    }
    if s.get("role"):
        kwargs["role"] = s["role"]
    if s.get("password"):
        kwargs["password"] = s["password"]
    if s.get("authenticator"):
        kwargs["authenticator"] = s["authenticator"]
    return kwargs


@contextmanager
def snowflake_connection() -> Generator[Any, None, None]:
    conn = snowflake.connector.connect(**_connect_kwargs())
    try:
        yield conn
    finally:
        conn.close()


def snowflake_target_label() -> str:
    s = snowflake_settings()
    return f"{s['database']}.{s['schema']}"


def start_fetch_run(
    conn: Any,
    *,
    started_at: str,
    source: str,
    grid_rows: int,
    grid_cols: int,
    search_radius_m: float,
    types_requested: str,
) -> int:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO FETCH_RUNS (
                STARTED_AT, SOURCE, GRID_ROWS, GRID_COLS, SEARCH_RADIUS_M,
                TYPES_REQUESTED, API_CALLS, PLACES_UPSERTED
            )
            VALUES (%s, %s, %s, %s, %s, %s, 0, 0)
            """,
            (started_at, source, grid_rows, grid_cols, search_radius_m, types_requested),
        )
        cur.execute("SELECT MAX(RUN_KEY) FROM FETCH_RUNS")
        row = cur.fetchone()
        return int(row[0])
    finally:
        cur.close()


def finish_fetch_run(
    conn: Any,
    *,
    run_key: int,
    finished_at: str,
    api_calls: int,
    places_upserted: int,
    error_message: str | None,
) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE FETCH_RUNS
            SET FINISHED_AT = %s,
                API_CALLS = %s,
                PLACES_UPSERTED = %s,
                ERROR_MESSAGE = %s
            WHERE RUN_KEY = %s
            """,
            (finished_at, api_calls, places_upserted, error_message, run_key),
        )
    finally:
        cur.close()


def upsert_place(conn: Any, *, now_iso: str, **row: Any) -> None:
    types_variant = json.dumps(row.get("types") or [], ensure_ascii=False)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            MERGE INTO PLACES AS t
            USING (
                SELECT
                    %(google_place_id)s AS GOOGLE_PLACE_ID,
                    %(name)s AS NAME,
                    %(formatted_address)s AS FORMATTED_ADDRESS,
                    %(short_formatted_address)s AS SHORT_FORMATTED_ADDRESS,
                    %(latitude)s AS LATITUDE,
                    %(longitude)s AS LONGITUDE,
                    %(primary_type)s AS PRIMARY_TYPE,
                    PARSE_JSON(%(types_json)s) AS TYPES,
                    %(business_status)s AS BUSINESS_STATUS,
                    %(rating)s AS RATING,
                    %(user_rating_count)s AS USER_RATING_COUNT,
                    %(price_level)s AS PRICE_LEVEL,
                    %(website_uri)s AS WEBSITE_URI,
                    %(borough)s AS BOROUGH,
                    %(source)s AS SOURCE,
                    TO_TIMESTAMP_NTZ(%(now_iso)s) AS SEEN_AT
            ) AS s
            ON t.GOOGLE_PLACE_ID = s.GOOGLE_PLACE_ID
            WHEN MATCHED THEN UPDATE SET
                NAME = s.NAME,
                FORMATTED_ADDRESS = s.FORMATTED_ADDRESS,
                SHORT_FORMATTED_ADDRESS = s.SHORT_FORMATTED_ADDRESS,
                LATITUDE = s.LATITUDE,
                LONGITUDE = s.LONGITUDE,
                PRIMARY_TYPE = s.PRIMARY_TYPE,
                TYPES = s.TYPES,
                BUSINESS_STATUS = s.BUSINESS_STATUS,
                RATING = s.RATING,
                USER_RATING_COUNT = s.USER_RATING_COUNT,
                PRICE_LEVEL = s.PRICE_LEVEL,
                WEBSITE_URI = s.WEBSITE_URI,
                BOROUGH = s.BOROUGH,
                SOURCE = s.SOURCE,
                LAST_SEEN_AT = s.SEEN_AT,
                LOADED_AT = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT (
                GOOGLE_PLACE_ID, NAME, FORMATTED_ADDRESS, SHORT_FORMATTED_ADDRESS,
                LATITUDE, LONGITUDE, PRIMARY_TYPE, TYPES, BUSINESS_STATUS,
                RATING, USER_RATING_COUNT, PRICE_LEVEL, WEBSITE_URI,
                BOROUGH, SOURCE, FIRST_SEEN_AT, LAST_SEEN_AT
            ) VALUES (
                s.GOOGLE_PLACE_ID, s.NAME, s.FORMATTED_ADDRESS, s.SHORT_FORMATTED_ADDRESS,
                s.LATITUDE, s.LONGITUDE, s.PRIMARY_TYPE, s.TYPES, s.BUSINESS_STATUS,
                s.RATING, s.USER_RATING_COUNT, s.PRICE_LEVEL, s.WEBSITE_URI,
                s.BOROUGH, s.SOURCE, s.SEEN_AT, s.SEEN_AT
            )
            """,
            {
                "google_place_id": row["google_place_id"],
                "name": row.get("name"),
                "formatted_address": row.get("formatted_address"),
                "short_formatted_address": row.get("short_formatted_address"),
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "primary_type": row.get("primary_type"),
                "types_json": types_variant,
                "business_status": row.get("business_status"),
                "rating": row.get("rating"),
                "user_rating_count": row.get("user_rating_count"),
                "price_level": row.get("price_level"),
                "website_uri": row.get("website_uri"),
                "borough": row.get("borough"),
                "source": row.get("source"),
                "now_iso": now_iso,
            },
        )
    finally:
        cur.close()
