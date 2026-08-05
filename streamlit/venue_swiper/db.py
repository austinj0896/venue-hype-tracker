"""Database backend for Après: Neon Postgres (Community Cloud) or Snowflake (SiS)."""

from __future__ import annotations

import os
from typing import Any

import streamlit as st

DEFAULT_POSTGRES_PLACES = "places"
DEFAULT_POSTGRES_RATINGS = "venue_ratings"
DEFAULT_POSTGRES_TAGS = "venue_tags"
DEFAULT_POSTGRES_HOURS = "venue_hours"
DEFAULT_SF_DIM = "VENUE_HYPE.STAGING_MARTS.DIM_PLACES"
DEFAULT_SF_RATINGS = "VENUE_HYPE.APP.VENUE_RATINGS"
DEFAULT_SF_TAGS = "VENUE_HYPE.APP.VENUE_TAGS"
DEFAULT_SF_HOURS = "VENUE_HYPE.APP.VENUE_HOURS"


def backend() -> str:
    """Return ``postgres`` or ``snowflake``."""
    try:
        forced = str(st.secrets.get("app", {}).get("database_backend", "")).strip().lower()
        if forced in ("postgres", "snowflake"):
            return forced
    except Exception:
        pass

    try:
        from snowflake.snowpark.context import get_active_session

        get_active_session()
        return "snowflake"
    except Exception:
        pass

    if postgres_url():
        return "postgres"

    if _has_snowflake_secrets():
        return "snowflake"

    raise RuntimeError(
        "No database configured. Add [connections.postgresql] url (Neon) or "
        "[connections.snowflake] (Snowflake) to Streamlit secrets."
    )


def postgres_url() -> str | None:
    try:
        if "connections" in st.secrets:
            for key in ("postgresql", "postgres", "neon"):
                if key in st.secrets.connections:
                    url = str(st.secrets.connections[key].get("url", "")).strip()
                    if url:
                        return url
    except Exception:
        pass
    return os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")


def _has_snowflake_secrets() -> bool:
    try:
        return "connections" in st.secrets and "snowflake" in st.secrets.connections
    except Exception:
        return False


def places_table() -> str:
    if backend() == "postgres":
        try:
            return str(st.secrets.get("app", {}).get("places_table", DEFAULT_POSTGRES_PLACES))
        except Exception:
            return DEFAULT_POSTGRES_PLACES
    try:
        return str(st.secrets.get("app", {}).get("dim_places", DEFAULT_SF_DIM))
    except Exception:
        return DEFAULT_SF_DIM


def ratings_table() -> str:
    if backend() == "postgres":
        try:
            return str(st.secrets.get("app", {}).get("ratings_table", DEFAULT_POSTGRES_RATINGS))
        except Exception:
            return DEFAULT_POSTGRES_RATINGS
    try:
        return str(st.secrets.get("app", {}).get("ratings_table", DEFAULT_SF_RATINGS))
    except Exception:
        return DEFAULT_SF_RATINGS


def venue_tags_table() -> str:
    if backend() == "postgres":
        try:
            return str(st.secrets.get("app", {}).get("venue_tags_table", DEFAULT_POSTGRES_TAGS))
        except Exception:
            return DEFAULT_POSTGRES_TAGS
    try:
        return str(st.secrets.get("app", {}).get("venue_tags_table", DEFAULT_SF_TAGS))
    except Exception:
        return DEFAULT_SF_TAGS


def venue_hours_table() -> str:
    if backend() == "postgres":
        try:
            return str(st.secrets.get("app", {}).get("venue_hours_table", DEFAULT_POSTGRES_HOURS))
        except Exception:
            return DEFAULT_POSTGRES_HOURS
    try:
        return str(st.secrets.get("app", {}).get("venue_hours_table", DEFAULT_SF_HOURS))
    except Exception:
        return DEFAULT_SF_HOURS


def _to_upper_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{str(k).upper(): v for k, v in row.items()} for row in rows]


def _bind_sql(sql: str) -> str:
    if backend() == "postgres":
        return sql.replace("?", "%s")
    return sql


def clear_db_caches() -> None:
    st.session_state.pop("postgres_conn", None)
    st.session_state.pop("snowflake_session", None)


def _get_postgres_conn():
    import psycopg2
    from psycopg2.extras import RealDictCursor

    url = postgres_url()
    if not url:
        raise RuntimeError("Missing Postgres connection url in secrets or DATABASE_URL.")

    conn = st.session_state.get("postgres_conn")
    if conn is None or conn.closed:
        conn = psycopg2.connect(url, cursor_factory=RealDictCursor)
        st.session_state.postgres_conn = conn
    return conn


def _postgres_query(sql: str, params: list[Any]) -> list[dict[str, Any]]:
    conn = _get_postgres_conn()
    with conn.cursor() as cur:
        cur.execute(_bind_sql(sql), params)
        if cur.description is None:
            conn.commit()
            return []
        rows = cur.fetchall()
        return _to_upper_rows([dict(row) for row in rows])


def _postgres_execute(sql: str, params: list[Any]) -> None:
    conn = _get_postgres_conn()
    with conn.cursor() as cur:
        cur.execute(_bind_sql(sql), params)
    conn.commit()


def _snowflake_connection_params() -> dict[str, str]:
    if not _has_snowflake_secrets():
        raise RuntimeError("Missing [connections.snowflake] in Streamlit secrets.")

    raw = dict(st.secrets.connections.snowflake)
    required = ("account", "user", "password", "role", "warehouse", "database", "schema")
    missing_keys = [key for key in required if not str(raw.get(key, "")).strip()]
    if missing_keys:
        raise RuntimeError("Snowflake secrets missing: " + ", ".join(missing_keys))

    params = {key: str(raw[key]).strip() for key in required}
    if "host" in raw and str(raw["host"]).strip():
        params["host"] = str(raw["host"]).strip()
    return params


def _get_snowflake_session():
    try:
        from snowflake.snowpark.context import get_active_session

        return get_active_session()
    except Exception:
        pass

    if "snowflake_session" not in st.session_state:
        from snowflake.snowpark import Session

        params = _snowflake_connection_params()
        session = Session.builder.configs(params).create()
        safe_role = params["role"].replace('"', '""')
        session.sql(f'USE ROLE "{safe_role}"').collect()
        st.session_state.snowflake_session = session
    return st.session_state.snowflake_session


def _snowflake_query(sql: str, params: list[Any]) -> list[dict[str, Any]]:
    session = _get_snowflake_session()
    rows = session.sql(sql, params=params).collect()
    return [row.as_dict() for row in rows]


def _snowflake_execute(sql: str, params: list[Any]) -> None:
    session = _get_snowflake_session()
    session.sql(sql, params=params).collect()


def run_query(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    params = params or []
    try:
        if backend() == "postgres":
            return _postgres_query(sql, params)
        return _snowflake_query(sql, params)
    except Exception as exc:
        label = "Postgres" if backend() == "postgres" else "Snowflake"
        raise RuntimeError(f"{label} query failed: {exc}") from exc


def execute_write(sql: str, params: list[Any] | None = None) -> None:
    params = params or []
    try:
        if backend() == "postgres":
            _postgres_execute(sql, params)
        else:
            _snowflake_execute(sql, params)
    except Exception as exc:
        label = "Postgres" if backend() == "postgres" else "Snowflake"
        raise RuntimeError(f"{label} write failed: {exc}") from exc


def upsert_rating(
    *,
    email: str,
    borough: str,
    google_place_id: str,
    place_name: str,
    status: str,
    rating: float | None,
) -> None:
    table = ratings_table()
    if backend() == "postgres":
        if status == "skipped":
            sql = f"""
                insert into {table} (
                    user_email, google_place_id, place_name, borough, rating, status
                ) values (%s, %s, %s, %s, null, %s)
                on conflict (user_email, google_place_id) do update set
                    place_name = excluded.place_name,
                    borough = excluded.borough,
                    rating = null,
                    status = excluded.status,
                    updated_at = now()
            """
            params = [email, google_place_id, place_name, borough, status]
        else:
            if rating is None:
                raise ValueError("Rated rows require a numeric rating.")
            sql = f"""
                insert into {table} (
                    user_email, google_place_id, place_name, borough, rating, status
                ) values (%s, %s, %s, %s, %s, %s)
                on conflict (user_email, google_place_id) do update set
                    place_name = excluded.place_name,
                    borough = excluded.borough,
                    rating = excluded.rating,
                    status = excluded.status,
                    updated_at = now()
            """
            params = [email, google_place_id, place_name, borough, float(rating), status]
        execute_write(sql, params)
        return

    if status == "skipped":
        sql = f"""
            merge into {table} as target
            using (
                select ? as user_email, ? as google_place_id, ? as place_name,
                       ? as borough, ? as status
            ) as source
            on target.user_email = source.user_email
               and target.google_place_id = source.google_place_id
            when matched then update set
                place_name = source.place_name,
                borough = source.borough,
                rating = null,
                status = source.status,
                updated_at = current_timestamp()
            when not matched then insert (
                user_email, google_place_id, place_name, borough, rating, status
            ) values (
                source.user_email, source.google_place_id, source.place_name,
                source.borough, null, source.status
            )
        """
        params = [email, google_place_id, place_name, borough, status]
    else:
        if rating is None:
            raise ValueError("Rated rows require a numeric rating.")
        sql = f"""
            merge into {table} as target
            using (
                select ? as user_email, ? as google_place_id, ? as place_name,
                       ? as borough, ?::float as rating, ? as status
            ) as source
            on target.user_email = source.user_email
               and target.google_place_id = source.google_place_id
            when matched then update set
                place_name = source.place_name,
                borough = source.borough,
                rating = source.rating,
                status = source.status,
                updated_at = current_timestamp()
            when not matched then insert (
                user_email, google_place_id, place_name, borough, rating, status
            ) values (
                source.user_email, source.google_place_id, source.place_name,
                source.borough, source.rating, source.status
            )
        """
        params = [email, google_place_id, place_name, borough, float(rating), status]
    execute_write(sql, params)


def fetch_db_identity() -> dict[str, str] | None:
    try:
        if backend() == "postgres":
            row = run_query(
                "select current_database() as db_name, current_user as db_user"
            )[0]
            return {k.lower(): str(v) for k, v in row.items()}
        row = run_query(
            """
            select
                current_user() as snowflake_user,
                current_role() as snowflake_role,
                current_account() as account_locator,
                current_region() as region
            """
        )[0]
        return {k.lower(): str(v) for k, v in row.items()}
    except Exception:
        return None
