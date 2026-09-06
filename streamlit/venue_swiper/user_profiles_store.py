"""Persist and load Après user profiles (separate from ratings / tags / hours)."""

from __future__ import annotations

import base64
import io
from datetime import date, datetime
from typing import Any

import streamlit as st

from db import backend, execute_write, run_query, user_profiles_table

_SCHEMA_APPLIED_KEY = "_user_profiles_schema_ok"

# Upload/compress limits for profile photos stored in Neon as base64.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PHOTO_EDGE = 512
JPEG_QUALITY = 85


def ensure_schema() -> None:
    """Create user_profiles on Neon if missing. No-op on Snowflake for now."""
    if backend() != "postgres":
        return
    if st.session_state.get(_SCHEMA_APPLIED_KEY):
        return
    # Single statement — more reliable than multi-statement execute via psycopg2.
    table = user_profiles_table()
    try:
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
                profile_photo_b64     TEXT,
                profile_photo_mime    TEXT,
                created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            [],
        )
        for col_sql in (
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS profile_photo_b64 TEXT",
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS profile_photo_mime TEXT",
        ):
            try:
                execute_write(col_sql, [])
            except Exception:
                pass
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
    except Exception:
        # Leave flag unset so the next request can retry.
        raise


def prepare_profile_photo(uploaded_file: Any) -> tuple[str, str]:
    """Resize/compress an uploaded image; return (base64, mime)."""
    from PIL import Image

    raw = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()
    if not raw:
        raise ValueError("Empty image file.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("Photo must be under 5 MB.")

    img = Image.open(io.BytesIO(raw))
    if getattr(img, "n_frames", 1) > 1:
        img.seek(0)
    img = img.convert("RGB")
    img.thumbnail((MAX_PHOTO_EDGE, MAX_PHOTO_EDGE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"


def photo_data_uri(b64: str | None, mime: str | None = None) -> str | None:
    if not b64:
        return None
    return f"data:{mime or 'image/jpeg'};base64,{b64}"


def photo_bytes(b64: str | None) -> bytes | None:
    if not b64:
        return None
    try:
        return base64.b64decode(b64)
    except Exception:
        return None


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
    has_photo = row.get("HAS_PROFILE_PHOTO")
    if has_photo is None:
        has_photo = bool(row.get("PROFILE_PHOTO_B64"))
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
        "PROFILE_PHOTO_B64": row.get("PROFILE_PHOTO_B64") or None,
        "PROFILE_PHOTO_MIME": (row.get("PROFILE_PHOTO_MIME") or "").strip() or None,
        "HAS_PROFILE_PHOTO": bool(has_photo),
        "CREATED_AT": row.get("CREATED_AT"),
        "UPDATED_AT": row.get("UPDATED_AT"),
    }


def is_profile_complete(profile: dict[str, Any] | None) -> bool:
    """True only when all required basic-setup fields are present.

    Ratings / planned dates do not count. On non-Postgres backends the
    profile feature is skipped so SiS keeps working until a table exists.
    Photo is optional.
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
def fetch_profile(email: str, include_photo: bool = False) -> dict[str, Any] | None:
    """Load profile. Photo bytes are opt-in — base64 blobs stall mobile after login.

    Does not run DDL on the hot path (schema is ensured on profile save).
    """
    if not email or backend() != "postgres":
        return None
    table = user_profiles_table()
    photo_cols = (
        "profile_photo_b64, profile_photo_mime,"
        if include_photo
        else ""
    )
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
            {photo_cols}
            (profile_photo_b64 is not null and length(profile_photo_b64) > 0)
                as has_profile_photo,
            created_at,
            updated_at
        from {table}
        where lower(user_email) = lower(%s)
        limit 1
    """
    email_n = email.strip().lower()
    try:
        rows = run_query(sql, [email_n])
    except Exception:
        # Don't swallow DB errors as "no profile" — that sends returning users
        # through setup again when Neon/pooler flaps.
        raise
    row = normalize_profile_row(rows[0] if rows else None)
    if row and not include_photo:
        row["PROFILE_PHOTO_B64"] = None
        row["PROFILE_PHOTO_MIME"] = None
    return row


def _profile_has_photo(email: str) -> bool:
    """Cheap flag for avatar without loading base64."""
    if backend() != "postgres":
        return False
    table = user_profiles_table()
    try:
        rows = run_query(
            f"""
            select 1 as ok
            from {table}
            where user_email = %s
              and profile_photo_b64 is not null
              and length(profile_photo_b64) > 0
            limit 1
            """,
            [email],
        )
        return bool(rows)
    except Exception:
        return False


@st.cache_data(show_spinner=False, ttl=60)
def fetch_profile_photo(email: str) -> dict[str, str | None] | None:
    if not email or backend() != "postgres":
        return None
    table = user_profiles_table()
    try:
        rows = run_query(
            f"""
            select profile_photo_b64, profile_photo_mime
            from {table}
            where user_email = %s
            limit 1
            """,
            [email.strip().lower()],
        )
    except Exception:
        return None
    if not rows:
        return None
    row = rows[0]
    b64 = row.get("PROFILE_PHOTO_B64")
    if not b64:
        return None
    return {
        "PROFILE_PHOTO_B64": b64,
        "PROFILE_PHOTO_MIME": (row.get("PROFILE_PHOTO_MIME") or "").strip() or "image/jpeg",
    }


def clear_profile_cache() -> None:
    try:
        fetch_profile.clear()
    except Exception:
        pass
    try:
        fetch_profile_photo.clear()
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
    profile_photo_b64: str | None = None,
    profile_photo_mime: str | None = None,
    update_photo: bool = False,
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

    existing = fetch_profile(email_n, include_photo=True)

    terms_at = accepted_terms_at
    if terms_at is None:
        # Preserve existing terms timestamp if already accepted.
        if existing and existing.get("ACCEPTED_TERMS_AT"):
            terms_at = existing["ACCEPTED_TERMS_AT"]
        else:
            terms_at = datetime.utcnow()

    if update_photo:
        photo_b64 = profile_photo_b64 or None
        photo_mime = (profile_photo_mime or "").strip() or None if photo_b64 else None
    else:
        photo_b64 = (existing or {}).get("PROFILE_PHOTO_B64")
        photo_mime = (existing or {}).get("PROFILE_PHOTO_MIME")

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
            profile_photo_b64, profile_photo_mime,
            created_at, updated_at
        ) values (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s,
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
            profile_photo_b64 = excluded.profile_photo_b64,
            profile_photo_mime = excluded.profile_photo_mime,
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
            photo_b64,
            photo_mime,
        ],
    )
    clear_profile_cache()
    return fetch_profile(email_n, include_photo=True) or {
        "USER_EMAIL": email_n,
        "FIRST_NAME": first,
        "LAST_NAME": last,
        "PROFILE_COMPLETE": complete,
        "PROFILE_PHOTO_B64": photo_b64,
        "PROFILE_PHOTO_MIME": photo_mime,
    }
