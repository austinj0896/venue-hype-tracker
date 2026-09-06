"""Persist and load Après user profiles (separate from ratings / tags / hours)."""

from __future__ import annotations

import base64
import uuid
import io
from datetime import date, datetime
from typing import Any

import streamlit as st

from db import (
    backend,
    execute_write,
    media_photos_table,
    run_query,
    user_profile_photo_links_table,
    user_profile_photos_table,
    user_profiles_table,
)

_SCHEMA_APPLIED_KEY = "_user_profiles_schema_ok"
_PHOTOS_SCHEMA_KEY = "_user_profile_photos_schema_ok"

# Upload/compress limits for profile photos stored in Neon as base64.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PHOTO_EDGE = 512
JPEG_QUALITY = 85
MAX_PROFILE_PHOTOS = 6


def ensure_schema() -> None:
    """Create user_profiles on Neon if missing. No-op on Snowflake for now."""
    if backend() != "postgres":
        return
    if st.session_state.get(_SCHEMA_APPLIED_KEY):
        return
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
        raise


def ensure_photos_schema() -> None:
    """Create media_photos + link tables. Safe to call from photo paths."""
    if backend() != "postgres":
        return
    if st.session_state.get(_PHOTOS_SCHEMA_KEY):
        return

    media_t = media_photos_table()
    links_t = user_profile_photo_links_table()
    legacy_t = user_profile_photos_table()

    try:
        execute_write("CREATE EXTENSION IF NOT EXISTS pgcrypto", [])
    except Exception:
        pass

    execute_write(
        f"""
        CREATE TABLE IF NOT EXISTS {media_t} (
            photo_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            photo_b64          TEXT NOT NULL,
            photo_mime         TEXT NOT NULL DEFAULT 'image/jpeg',
            uploaded_by_email  TEXT,
            byte_length        INTEGER,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        [],
    )
    execute_write(
        f"""
        CREATE TABLE IF NOT EXISTS {links_t} (
            user_email  TEXT NOT NULL,
            photo_id    UUID NOT NULL REFERENCES {media_t} (photo_id) ON DELETE CASCADE,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            linked_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_email, photo_id)
        )
        """,
        [],
    )
    for idx_sql in (
        f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{links_t}_order ON {links_t} (user_email, sort_order)",
        f"CREATE INDEX IF NOT EXISTS idx_{links_t}_user ON {links_t} (user_email, sort_order)",
        f"CREATE INDEX IF NOT EXISTS idx_{links_t}_photo ON {links_t} (photo_id)",
        f"CREATE INDEX IF NOT EXISTS idx_{media_t}_uploader ON {media_t} (uploaded_by_email)",
        f"CREATE INDEX IF NOT EXISTS idx_{media_t}_created ON {media_t} (created_at DESC)",
    ):
        try:
            execute_write(idx_sql, [])
        except Exception:
            pass

    # One-shot migrate from legacy combined gallery table if it still has rows.
    try:
        execute_write(
            f"""
            INSERT INTO {media_t} (photo_id, photo_b64, photo_mime, uploaded_by_email, created_at, updated_at)
            SELECT
                gen_random_uuid(),
                upp.photo_b64,
                coalesce(nullif(upp.photo_mime, ''), 'image/jpeg'),
                lower(upp.user_email),
                upp.created_at,
                upp.updated_at
            FROM {legacy_t} upp
            WHERE upp.photo_b64 IS NOT NULL
              AND length(upp.photo_b64) > 0
              AND NOT EXISTS (
                  SELECT 1 FROM {media_t} mp
                  WHERE lower(mp.uploaded_by_email) = lower(upp.user_email)
                    AND mp.photo_b64 = upp.photo_b64
              )
            """,
            [],
        )
        execute_write(
            f"""
            INSERT INTO {links_t} (user_email, photo_id, sort_order, linked_at)
            SELECT DISTINCT ON (lower(upp.user_email), upp.sort_order)
                lower(upp.user_email),
                mp.photo_id,
                upp.sort_order,
                coalesce(upp.created_at, NOW())
            FROM {legacy_t} upp
            JOIN {media_t} mp
              ON lower(mp.uploaded_by_email) = lower(upp.user_email)
             AND mp.photo_b64 = upp.photo_b64
            ORDER BY lower(upp.user_email), upp.sort_order, mp.created_at DESC
            ON CONFLICT DO NOTHING
            """,
            [],
        )
    except Exception:
        pass

    st.session_state[_PHOTOS_SCHEMA_KEY] = True


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
        "PHOTO_COUNT": int(row.get("PHOTO_COUNT") or (1 if has_photo else 0)),
        "CREATED_AT": row.get("CREATED_AT"),
        "UPDATED_AT": row.get("UPDATED_AT"),
    }


def is_profile_complete(profile: dict[str, Any] | None) -> bool:
    if backend() != "postgres":
        return True
    if not profile:
        return False
    first = (profile.get("FIRST_NAME") or "").strip()
    last = (profile.get("LAST_NAME") or "").strip()
    city = (profile.get("CITY") or "").strip()
    neighbourhood = (profile.get("NEIGHBOURHOOD") or "").strip()
    dietary = _as_list(profile.get("DIETARY_NEEDS"))
    activities = _as_list(profile.get("ACTIVITY_PREFERENCES"))
    terms = profile.get("ACCEPTED_TERMS_AT")
    return bool(
        first and last and city and neighbourhood and dietary and activities and terms
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


def _normalize_photo_row(row: dict[str, Any], *, include_bytes: bool) -> dict[str, Any]:
    b64 = row.get("PHOTO_B64") or row.get("PROFILE_PHOTO_B64")
    mime = (row.get("PHOTO_MIME") or row.get("PROFILE_PHOTO_MIME") or "image/jpeg").strip()
    photo_id = row.get("PHOTO_ID")
    out: dict[str, Any] = {
        "PHOTO_ID": str(photo_id) if photo_id is not None else None,
        "SORT_ORDER": int(row.get("SORT_ORDER") or 0),
        "PHOTO_MIME": mime or "image/jpeg",
        "IS_PRIMARY": int(row.get("SORT_ORDER") or 0) == 0,
    }
    if include_bytes:
        out["PHOTO_B64"] = b64
    return out


def _migrate_legacy_column_photo(email_n: str) -> list[dict[str, Any]]:
    """Copy user_profiles.profile_photo_b64 into media_photos + link if gallery empty."""
    profiles = user_profiles_table()
    media_t = media_photos_table()
    links_t = user_profile_photo_links_table()
    rows = run_query(
        f"""
        select profile_photo_b64, profile_photo_mime
        from {profiles}
        where lower(user_email) = lower(%s)
          and profile_photo_b64 is not null
          and length(profile_photo_b64) > 0
        limit 1
        """,
        [email_n],
    )
    if not rows:
        return []
    b64 = rows[0].get("PROFILE_PHOTO_B64")
    mime = (rows[0].get("PROFILE_PHOTO_MIME") or "image/jpeg").strip() or "image/jpeg"
    if not b64:
        return []
    photo_id = str(uuid.uuid4())
    execute_write(
        f"""
        insert into {media_t} (
            photo_id, photo_b64, photo_mime, uploaded_by_email, byte_length, created_at, updated_at
        ) values (
            %s, %s, %s, %s, %s, NOW(), NOW()
        )
        """,
        [photo_id, b64, mime, email_n, len(b64)],
    )
    execute_write(
        f"""
        insert into {links_t} (user_email, photo_id, sort_order, linked_at)
        values (%s, %s, 0, NOW())
        on conflict do nothing
        """,
        [email_n, photo_id],
    )
    return [
        {
            "PHOTO_ID": photo_id,
            "SORT_ORDER": 0,
            "PHOTO_B64": b64,
            "PHOTO_MIME": mime,
            "IS_PRIMARY": True,
        }
    ]


def _sync_legacy_primary(email_n: str, primary: dict[str, Any] | None) -> None:
    profiles_t = user_profiles_table()
    if primary and primary.get("PHOTO_B64"):
        execute_write(
            f"""
            update {profiles_t}
            set profile_photo_b64 = %s,
                profile_photo_mime = %s,
                updated_at = NOW()
            where lower(user_email) = lower(%s)
            """,
            [
                primary.get("PHOTO_B64"),
                primary.get("PHOTO_MIME") or "image/jpeg",
                email_n,
            ],
        )
    else:
        execute_write(
            f"""
            update {profiles_t}
            set profile_photo_b64 = null,
                profile_photo_mime = null,
                updated_at = NOW()
            where lower(user_email) = lower(%s)
            """,
            [email_n],
        )


@st.cache_data(show_spinner=False, ttl=60)
def list_profile_photos(email: str, include_bytes: bool = True) -> list[dict[str, Any]]:
    """Ordered gallery photos linked to the profile. First entry is primary/avatar."""
    if not email or backend() != "postgres":
        return []
    email_n = email.strip().lower()
    try:
        ensure_photos_schema()
    except Exception:
        st.session_state[_PHOTOS_SCHEMA_KEY] = True

    media_t = media_photos_table()
    links_t = user_profile_photo_links_table()
    try:
        rows = run_query(
            f"""
            select
                l.photo_id,
                l.sort_order,
                m.photo_b64,
                m.photo_mime
            from {links_t} l
            join {media_t} m on m.photo_id = l.photo_id
            where lower(l.user_email) = lower(%s)
            order by l.sort_order asc, l.linked_at asc
            limit {MAX_PROFILE_PHOTOS}
            """,
            [email_n],
        )
    except Exception:
        rows = []
    if rows:
        return [_normalize_photo_row(r, include_bytes=include_bytes) for r in rows]
    try:
        migrated = _migrate_legacy_column_photo(email_n)
    except Exception:
        migrated = []
    if migrated:
        clear_profile_cache()
        if include_bytes:
            return migrated
        return [{k: v for k, v in migrated[0].items() if k != "PHOTO_B64"}]
    return []


@st.cache_data(show_spinner=False, ttl=60)
def fetch_profile_photo(email: str) -> dict[str, str | None] | None:
    """Primary linked photo for header avatar."""
    photos = list_profile_photos(email, include_bytes=True)
    if photos:
        p0 = photos[0]
        b64 = p0.get("PHOTO_B64")
        if b64:
            return {
                "PROFILE_PHOTO_B64": b64,
                "PROFILE_PHOTO_MIME": p0.get("PHOTO_MIME") or "image/jpeg",
                "PHOTO_ID": p0.get("PHOTO_ID"),
            }
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
        "PHOTO_ID": None,
    }


def save_profile_photos(email: str, photos: list[dict[str, Any]]) -> int:
    """Sync profile links to the given ordered gallery.

    New uploads create durable media_photos rows (UUID). Removing a photo from
    the profile only deletes the link — the asset remains until admin purge.
    """
    if backend() != "postgres":
        raise RuntimeError("User photos are only supported on Neon Postgres.")
    ensure_photos_schema()
    email_n = email.strip().lower()
    media_t = media_photos_table()
    links_t = user_profile_photo_links_table()

    desired: list[dict[str, Any]] = []
    for item in photos[:MAX_PROFILE_PHOTOS]:
        photo_id = item.get("PHOTO_ID") or item.get("photo_id")
        b64 = (item.get("PHOTO_B64") or item.get("photo_b64") or "").strip()
        mime = item.get("PHOTO_MIME") or item.get("photo_mime") or "image/jpeg"
        mime_n = str(mime).strip() or "image/jpeg"

        if photo_id:
            pid = str(photo_id)
            exists = run_query(
                f"select photo_id, photo_b64, photo_mime from {media_t} where photo_id = %s limit 1",
                [pid],
            )
            if not exists:
                if not b64:
                    continue
                pid = str(uuid.uuid4())
                execute_write(
                    f"""
                    insert into {media_t} (
                        photo_id, photo_b64, photo_mime, uploaded_by_email, byte_length, created_at, updated_at
                    ) values (%s, %s, %s, %s, %s, NOW(), NOW())
                    """,
                    [pid, b64, mime_n, email_n, len(b64)],
                )
            else:
                if not b64:
                    b64 = exists[0].get("PHOTO_B64") or ""
                    mime_n = (exists[0].get("PHOTO_MIME") or mime_n)
        else:
            if not b64:
                continue
            pid = str(uuid.uuid4())
            execute_write(
                f"""
                insert into {media_t} (
                    photo_id, photo_b64, photo_mime, uploaded_by_email, byte_length, created_at, updated_at
                ) values (%s, %s, %s, %s, %s, NOW(), NOW())
                """,
                [pid, b64, mime_n, email_n, len(b64)],
            )

        desired.append({"PHOTO_ID": pid, "PHOTO_B64": b64, "PHOTO_MIME": mime_n})

    # Unlink entire profile gallery, then relink desired order (assets untouched).
    execute_write(
        f"delete from {links_t} where lower(user_email) = lower(%s)",
        [email_n],
    )
    for idx, row in enumerate(desired):
        execute_write(
            f"""
            insert into {links_t} (user_email, photo_id, sort_order, linked_at)
            values (%s, %s, %s, NOW())
            """,
            [email_n, row["PHOTO_ID"], idx],
        )

    primary = desired[0] if desired else None
    _sync_legacy_primary(email_n, primary)
    clear_profile_cache()
    return len(desired)


@st.cache_data(show_spinner=False, ttl=30)
def fetch_profile(email: str, include_photo: bool = False) -> dict[str, Any] | None:
    """Load profile. Does not run DDL on the hot path.

    Uses only ``user_profiles`` for the primary read so a missing gallery
    table can never block login. Photo counts are enriched best-effort.
    """
    if not email or backend() != "postgres":
        return None
    table = user_profiles_table()
    email_n = email.strip().lower()
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
    rows = run_query(sql, [email_n])
    row = normalize_profile_row(rows[0] if rows else None)
    if not row:
        return None
    if not include_photo:
        row["PROFILE_PHOTO_B64"] = None
        row["PROFILE_PHOTO_MIME"] = None

    # Best-effort gallery enrichment (never fail the profile load).
    try:
        links_t = user_profile_photo_links_table()
        counts = run_query(
            f"""
            select count(*)::int as photo_count
            from {links_t}
            where lower(user_email) = lower(%s)
            """,
            [email_n],
        )
        if counts:
            n = int(counts[0].get("PHOTO_COUNT") or 0)
            row["PHOTO_COUNT"] = n
            if n > 0:
                row["HAS_PROFILE_PHOTO"] = True
    except Exception:
        pass
    return row


def clear_profile_cache() -> None:
    for fn in (fetch_profile, fetch_profile_photo, list_profile_photos):
        try:
            fn.clear()
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
    photos: list[dict[str, Any]] | None = None,
    update_photos: bool = False,
    mark_complete: bool = True,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if backend() != "postgres":
        raise RuntimeError("User profiles are only supported on Neon Postgres.")

    email_n = email.strip().lower()
    first = first_name.strip()
    last = last_name.strip()
    city_n = city.strip()
    hood = neighbourhood.strip()
    dietary = [d.strip() for d in dietary_needs if str(d).strip()]
    activities = [a.strip() for a in activity_preferences if str(a).strip()]
    phone_n = (phone or "").strip() or None

    prior = existing
    terms_at = accepted_terms_at
    if terms_at is None:
        if prior and prior.get("ACCEPTED_TERMS_AT"):
            terms_at = prior["ACCEPTED_TERMS_AT"]
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
    params: list[Any] = [
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
    ]
    execute_write(sql, params)

    photo_count = int((prior or {}).get("PHOTO_COUNT") or 0)
    has_photo = bool((prior or {}).get("HAS_PROFILE_PHOTO"))
    primary_b64 = None
    primary_mime = None

    if update_photos:
        gallery = list(photos or [])
        photo_count = save_profile_photos(email_n, gallery)
        has_photo = photo_count > 0
        if gallery:
            primary_b64 = gallery[0].get("PHOTO_B64") or gallery[0].get("photo_b64")
            primary_mime = gallery[0].get("PHOTO_MIME") or gallery[0].get("photo_mime")
    elif update_photo:
        if profile_photo_b64:
            photo_count = save_profile_photos(
                email_n,
                [
                    {
                        "PHOTO_B64": profile_photo_b64,
                        "PHOTO_MIME": profile_photo_mime or "image/jpeg",
                    }
                ],
            )
            has_photo = True
            primary_b64 = profile_photo_b64
            primary_mime = profile_photo_mime
        else:
            photo_count = save_profile_photos(email_n, [])
            has_photo = False

    clear_profile_cache()
    return {
        "USER_EMAIL": email_n,
        "FIRST_NAME": first,
        "LAST_NAME": last,
        "DATE_OF_BIRTH": date_of_birth,
        "PHONE": phone_n,
        "CITY": city_n,
        "NEIGHBOURHOOD": hood,
        "DIETARY_NEEDS": dietary,
        "ACTIVITY_PREFERENCES": activities,
        "ACCEPTED_TERMS_AT": terms_at,
        "MARKETING_OPT_IN": bool(marketing_opt_in),
        "PROFILE_COMPLETE": complete,
        "PROFILE_PHOTO_B64": primary_b64,
        "PROFILE_PHOTO_MIME": primary_mime,
        "HAS_PROFILE_PHOTO": has_photo,
        "PHOTO_COUNT": photo_count,
    }
