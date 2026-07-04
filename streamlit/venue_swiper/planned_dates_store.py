"""Persist and load user planned dates."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from db import backend, execute_write, run_query

DEFAULT_POSTGRES_TABLE = "planned_dates"
DEFAULT_SF_TABLE = "VENUE_HYPE.APP.PLANNED_DATES"


def planned_dates_table() -> str:
    if backend() == "postgres":
        try:
            return str(
                st.secrets.get("app", {}).get("planned_dates_table", DEFAULT_POSTGRES_TABLE)
            )
        except Exception:
            return DEFAULT_POSTGRES_TABLE
    try:
        return str(st.secrets.get("app", {}).get("planned_dates_table", DEFAULT_SF_TABLE))
    except Exception:
        return DEFAULT_SF_TABLE


def save_planned_date(
    *,
    email: str,
    borough: str,
    combo_id: str,
    combo_label: str,
    stop1: dict[str, Any],
    stop2: dict[str, Any],
    walk_distance_m: float,
    walk_duration_min: float,
    scheduled_at: datetime,
) -> None:
    table = planned_dates_table()
    if backend() == "postgres":
        sql = f"""
            insert into {table} (
                user_email, borough, combo_id, combo_label,
                stop1_google_place_id, stop1_place_name, stop1_primary_type,
                stop2_google_place_id, stop2_place_name, stop2_primary_type,
                walk_distance_m, walk_duration_min, scheduled_at
            ) values (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s
            )
        """
        params = [
            email,
            borough,
            combo_id,
            combo_label,
            stop1.get("GOOGLE_PLACE_ID"),
            stop1.get("PLACE_NAME"),
            stop1.get("PRIMARY_TYPE"),
            stop2.get("GOOGLE_PLACE_ID"),
            stop2.get("PLACE_NAME"),
            stop2.get("PRIMARY_TYPE"),
            walk_distance_m,
            walk_duration_min,
            scheduled_at,
        ]
        execute_write(sql, params)
        return

    sql = f"""
        insert into {table} (
            user_email, borough, combo_id, combo_label,
            stop1_google_place_id, stop1_place_name, stop1_primary_type,
            stop2_google_place_id, stop2_place_name, stop2_primary_type,
            walk_distance_m, walk_duration_min, scheduled_at
        ) select ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::timestamp_tz
    """
    params = [
        email,
        borough,
        combo_id,
        combo_label,
        stop1.get("GOOGLE_PLACE_ID"),
        stop1.get("PLACE_NAME"),
        stop1.get("PRIMARY_TYPE"),
        stop2.get("GOOGLE_PLACE_ID"),
        stop2.get("PLACE_NAME"),
        stop2.get("PRIMARY_TYPE"),
        walk_distance_m,
        walk_duration_min,
        scheduled_at.isoformat(),
    ]
    execute_write(sql, params)


@st.cache_data(show_spinner=False)
def fetch_planned_dates(email: str, *, upcoming_only: bool = True) -> list[dict[str, Any]]:
    table = planned_dates_table()
    time_filter = ""
    params: list[Any] = [email]
    if upcoming_only:
        if backend() == "postgres":
            time_filter = "and scheduled_at >= now()"
        else:
            time_filter = "and scheduled_at >= current_timestamp()"

    if backend() == "postgres":
        sql = f"""
            select
                planned_date_id,
                borough,
                combo_id,
                combo_label,
                stop1_google_place_id,
                stop1_place_name,
                stop1_primary_type,
                stop2_google_place_id,
                stop2_place_name,
                stop2_primary_type,
                walk_distance_m,
                walk_duration_min,
                scheduled_at,
                created_at
            from {table}
            where user_email = %s
              {time_filter}
            order by scheduled_at asc
        """
    else:
        sql = f"""
            select
                planned_date_id,
                borough,
                combo_id,
                combo_label,
                stop1_google_place_id,
                stop1_place_name,
                stop1_primary_type,
                stop2_google_place_id,
                stop2_place_name,
                stop2_primary_type,
                walk_distance_m,
                walk_duration_min,
                scheduled_at,
                created_at
            from {table}
            where user_email = ?
              {time_filter}
            order by scheduled_at asc
        """
    return run_query(sql, params)
