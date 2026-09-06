"""Persist and load Après user profiles (separate from ratings / tags / hours)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import streamlit as st

from db import backend, execute_write, run_query, user_profiles_table

_SCHEMA_APPLIED_KEY = "_user_profiles_schema_ok"


def ensure_schema() -> None:
    """Create user_profiles on Neon if missing. No-op on Snowflake for now."""
    if backend() != "postgres":
        return
    if st.session_state.get(_SCHEMA_APPLIED_KEY):
        return
    # Single statement — more reliable than multi-statement execute via psycopg2.
    table = user_profiles_table()
    execute_write(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
            user_email            TEXT PRIMARY KEY,
            first_name            TEXT NOT NULL,
            last_name             TEXT NOT NULL,
            date_of_birth         DATE,
            phone                 TEXT,
            city                  TEXT NOT NULL,
            neighbourhood         TEXT NOT NULL,
            dietary_needs         TEXT[] NOT NULL DEFAULT '{{}}',
            activity_preferences  TEXT[] NOT NULL DEFAULT '{{}}',
            accepted_terms_at     TIMESTAMPTZ NOT NULL,
            marketing_opt_in      BOOLEAN NOT NULL DEFAULT FALSE,
            profile_complete      BOOLEAN NOT NULL DEFAULT FALSE,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        [],
    )
    try:
        execute_write(
            f"CREATE INDEX IF NOT EXISTS idx_user_profiles_complete ON {table} (profile_complete)",
            [],
        )
        execute_write(
            f"CREATE INDEX IF NOT EXISTS idx_user_profiles_updated ON {table} (updated_at DESC)",
            [],
        )
    except Exception:
        pass
    st.session_state[_SCHEMA_APPLIED_KEY] = True


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, tuple):
        return [str(v) for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    # Postgres array text form: {a,b}
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1]
        if not inner:
            return []
        return [p.strip().strip('"') for p in inner.split(",") if p.strip()]
    return [text]


def normalize_profile_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "USER_EMAIL": row.get("USER_EMAIL"),
        "FIRST_NAME": (row.get("FIRST_NAME") or "").strip(),
        "LAST_NAME": (row.get("LAST_NAME") or "").strip(),
        "DATE_OF_BIRTH": row.get("DATE_OF_BIRTH"),
        "PHONE": (row.get("PHONE") or "").strip() or None,
        "CITY": (row.get("CITY") or "").strip(),
        "NEIGHBOURHOOD": (row.get("NEIGHBOURHOOD") or row.get("NEIGHBORHOOD") or "").strip(),
        "DIETARY_NEEDS": _as_list(row.get("DIETARY_NEEDS")),
        "ACTIVITY_PREFERENCES": _as_list(row.get("ACTIVITY_PREFERENCES")),
        "ACCEPTED_TERMS_AT": row.get("ACCEPTED_TERMS_AT"),
        "MARKETING_OPT_IN": bool(row.get("MARKETING_OPT_IN")),
        "PROFILE_COMPLETE": bool(row.get("PROFILE_COMPLETE")),
        "CREATED_AT": row.get("CREATED_AT"),
        "UPDATED_AT": row.get("UPDATED_AT"),
    }


def is_profile_complete(profile: dict[str, Any] | None) -> bool:
    """True only when all required basic-setup fields are present.

    Ratings / planned dates do not count. On non-Postgres backends the
    profile feature is skipped so SiS keeps working until a table exists.
    """
    if backend() != "postgres":
        return True
    if not profile:
        return False
    if profile.get("PROFILE_COMPLETE") is True:
        # Still verify required fields in case of a bad write.
        pass
    first = (profile.get("FIRST_NAME") or "").strip()
    last = (profile.get("LAST_NAME") or "").strip()
    city = (profile.get("CITY") or "").strip()
    neighbourhood = (profile.get("NEIGHBOURHOOD") or "").strip()
    dietary = _as_list(profile.get("DIETARY_NEEDS"))
    activities = _as_list(profile.get("ACTIVITY_PREFERENCES"))
    terms = profile.get("ACCEPTED_TERMS_AT")
    return bool(
        first
        and last
        and city
        and neighbourhood
        and dietary
        and activities
        and terms
    )


def compute_profile_complete_flag(payload: dict[str, Any]) -> bool:
    return is_profile_complete(
        {
            "FIRST_NAME": payload.get("first_name"),
            "LAST_NAME": payload.get("last_name"),
            "CITY": payload.get("city"),
            "NEIGHBOURHOOD": payload.get("neighbourhood"),
            "DIETARY_NEEDS": payload.get("dietary_needs"),
            "ACTIVITY_PREFERENCES": payload.get("activity_preferences"),
            "ACCEPTED_TERMS_AT": payload.get("accepted_terms_at"),
            "PROFILE_COMPLETE": False,
        }
    )


@st.cache_data(show_spinner=False, ttl=30)
def fetch_profile(email: str) -> dict[str, Any] | None:
    if not email or backend() != "postgres":
        return None
    ensure_schema()
    table = user_profiles_table()
    sql = f"""
        select
            user_email,
            first_name,
            last_name,
            date_of_birth,
            phone,
            city,
            neighbourhood,
            dietary_needs,
            activity_preferences,
            accepted_terms_at,
            marketing_opt_in,
            profile_complete,
            created_at,
            updated_at
        from {table}
        where user_email = %s
        limit 1
    """
    try:
        rows = run_query(sql, [email.strip().lower()])
    except Exception:
        # Table may not exist yet on a fresh deploy — try schema once more.
        st.session_state.pop(_SCHEMA_APPLIED_KEY, None)
        try:
            ensure_schema()
            rows = run_query(sql, [email.strip().lower()])
        except Exception:
            return None
    return normalize_profile_row(rows[0] if rows else None)


def clear_profile_cache() -> None:
    try:
        fetch_profile.clear()
    except Exception:
        pass


def upsert_profile(
    *,
    email: str,
    first_name: str,
    last_name: str,
    city: str,
    neighbourhood: str,
    dietary_needs: list[str],
    activity_preferences: list[str],
    accepted_terms_at: datetime | None,
    marketing_opt_in: bool = False,
    date_of_birth: date | None = None,
    phone: str | None = None,
    mark_complete: bool = True,
) -> dict[str, Any]:
    if backend() != "postgres":
        raise RuntimeError("User profiles are only supported on Neon Postgres.")

    ensure_schema()
    email_n = email.strip().lower()
    first = first_name.strip()
    last = last_name.strip()
    city_n = city.strip()
    hood = neighbourhood.strip()
    dietary = [d.strip() for d in dietary_needs if str(d).strip()]
    activities = [a.strip() for a in activity_preferences if str(a).strip()]
    phone_n = (phone or "").strip() or None

    terms_at = accepted_terms_at
    if terms_at is None:
        # Preserve existing terms timestamp if already accepted.
        existing = fetch_profile(email_n)
        if existing and existing.get("ACCEPTED_TERMS_AT"):
            terms_at = existing["ACCEPTED_TERMS_AT"]
        else:
            terms_at = datetime.utcnow()

    complete = bool(mark_complete) and compute_profile_complete_flag(
        {
            "first_name": first,
            "last_name": last,
            "city": city_n,
            "neighbourhood": hood,
            "dietary_needs": dietary,
            "activity_preferences": activities,
            "accepted_terms_at": terms_at,
        }
    )

    table = user_profiles_table()
    sql = f"""
        insert into {table} (
            user_email, first_name, last_name, date_of_birth, phone,
            city, neighbourhood, dietary_needs, activity_preferences,
            accepted_terms_at, marketing_opt_in, profile_complete,
            created_at, updated_at
        ) values (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            NOW(), NOW()
        )
        on conflict (user_email) do update set
            first_name = excluded.first_name,
            last_name = excluded.last_name,
            date_of_birth = excluded.date_of_birth,
            phone = excluded.phone,
            city = excluded.city,
            neighbourhood = excluded.neighbourhood,
            dietary_needs = excluded.dietary_needs,
            activity_preferences = excluded.activity_preferences,
            accepted_terms_at = excluded.accepted_terms_at,
            marketing_opt_in = excluded.marketing_opt_in,
            profile_complete = excluded.profile_complete,
            updated_at = NOW()
    """
    execute_write(
        sql,
        [
            email_n,
            first,
            last,
            date_of_birth,
            phone_n,
            city_n,
            hood,
            dietary,
            activities,
            terms_at,
            bool(marketing_opt_in),
            complete,
        ],
    )
    clear_profile_cache()
    return fetch_profile(email_n) or {
        "USER_EMAIL": email_n,
        "FIRST_NAME": first,
        "LAST_NAME": last,
        "PROFILE_COMPLETE": complete,
    }
