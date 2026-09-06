"""Partner link requests, links, and in-app notifications."""

from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.parse import quote, urlencode

import streamlit as st

from app_log import log_event
from db import (
    backend,
    execute_write,
    partner_link_requests_table,
    partner_links_table,
    run_query,
    user_notifications_table,
    user_profiles_table,
)

_REL_SCHEMA_KEY = "_user_relationship_schema_ok"


def ensure_relationship_schema() -> None:
    """Create partner/notification tables and profile relationship columns."""
    if backend() != "postgres":
        return
    if st.session_state.get(_REL_SCHEMA_KEY):
        return

    profiles = user_profiles_table()
    requests_t = partner_link_requests_table()
    links_t = partner_links_table()
    notif_t = user_notifications_table()

    try:
        execute_write("CREATE EXTENSION IF NOT EXISTS pgcrypto", [])
    except Exception:
        pass

    for col_sql in (
        f"ALTER TABLE {profiles} ADD COLUMN IF NOT EXISTS relationship_status TEXT",
        f"ALTER TABLE {profiles} ADD COLUMN IF NOT EXISTS open_to_dates BOOLEAN",
        (
            f"ALTER TABLE {profiles} ADD COLUMN IF NOT EXISTS profile_visibility "
            f"TEXT NOT NULL DEFAULT 'private'"
        ),
    ):
        try:
            execute_write(col_sql, [])
        except Exception:
            pass

    try:
        execute_write(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{profiles}_visibility
            ON {profiles} (profile_visibility)
            WHERE profile_complete = TRUE
            """,
            [],
        )
    except Exception:
        pass

    execute_write(
        f"""
        CREATE TABLE IF NOT EXISTS {requests_t} (
            request_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            from_email    TEXT NOT NULL,
            to_email      TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'pending',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            responded_at  TIMESTAMPTZ,
            CONSTRAINT {requests_t}_status_chk
                CHECK (status IN ('pending', 'accepted', 'declined', 'cancelled', 'expired')),
            CONSTRAINT {requests_t}_not_self_chk
                CHECK (lower(from_email) <> lower(to_email))
        )
        """,
        [],
    )
    for idx_sql in (
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_{requests_t}_pending
        ON {requests_t} (lower(from_email), lower(to_email))
        WHERE status = 'pending'
        """,
        f"""
        CREATE INDEX IF NOT EXISTS idx_{requests_t}_to
        ON {requests_t} (lower(to_email), status, created_at DESC)
        """,
        f"""
        CREATE INDEX IF NOT EXISTS idx_{requests_t}_from
        ON {requests_t} (lower(from_email), status, created_at DESC)
        """,
    ):
        try:
            execute_write(idx_sql, [])
        except Exception:
            pass

    execute_write(
        f"""
        CREATE TABLE IF NOT EXISTS {links_t} (
            user_email_a       TEXT NOT NULL,
            user_email_b       TEXT NOT NULL,
            linked_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            requested_by_email TEXT NOT NULL,
            PRIMARY KEY (user_email_a, user_email_b),
            CONSTRAINT {links_t}_ordered_chk CHECK (user_email_a < user_email_b)
        )
        """,
        [],
    )
    for idx_sql in (
        f"CREATE INDEX IF NOT EXISTS idx_{links_t}_a ON {links_t} (user_email_a)",
        f"CREATE INDEX IF NOT EXISTS idx_{links_t}_b ON {links_t} (user_email_b)",
    ):
        try:
            execute_write(idx_sql, [])
        except Exception:
            pass

    execute_write(
        f"""
        CREATE TABLE IF NOT EXISTS {notif_t} (
            notification_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_email      TEXT NOT NULL,
            kind            TEXT NOT NULL,
            payload         JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            read_at         TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT {notif_t}_kind_chk
                CHECK (kind IN ('partner_request', 'partner_accepted', 'partner_declined'))
        )
        """,
        [],
    )
    for idx_sql in (
        f"""
        CREATE INDEX IF NOT EXISTS idx_{notif_t}_inbox
        ON {notif_t} (lower(user_email), created_at DESC)
        """,
        f"""
        CREATE INDEX IF NOT EXISTS idx_{notif_t}_unread
        ON {notif_t} (lower(user_email), created_at DESC)
        WHERE read_at IS NULL
        """,
    ):
        try:
            execute_write(idx_sql, [])
        except Exception:
            pass

    st.session_state[_REL_SCHEMA_KEY] = True


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def _ordered_pair(a: str, b: str) -> tuple[str, str]:
    x, y = _norm_email(a), _norm_email(b)
    return (x, y) if x < y else (y, x)


def build_signup_invite_url(to_email: str, *, from_email: str | None = None) -> str:
    """Deep-link hint for future outbound invite email (no mail send yet)."""
    params: dict[str, str] = {"invite": "partner", "email": _norm_email(to_email)}
    if from_email:
        params["from"] = _norm_email(from_email)
    query = urlencode(params, quote_via=quote)
    try:
        base = str(st.secrets.get("app", {}).get("public_app_url", "")).strip().rstrip("/")
    except Exception:
        base = ""
    if base:
        return f"{base}/?{query}"
    return f"?{query}"


def _insert_notification(
    user_email: str,
    kind: str,
    payload: dict[str, Any],
) -> None:
    notif_t = user_notifications_table()
    execute_write(
        f"""
        insert into {notif_t} (notification_id, user_email, kind, payload, created_at)
        values (%s, %s, %s, %s::jsonb, NOW())
        """,
        [str(uuid.uuid4()), _norm_email(user_email), kind, json.dumps(payload)],
    )


def profile_exists(email: str) -> bool:
    if backend() != "postgres" or not email:
        return False
    ensure_relationship_schema()
    rows = run_query(
        f"""
        select 1 as ok from {user_profiles_table()}
        where lower(user_email) = lower(%s)
        limit 1
        """,
        [_norm_email(email)],
    )
    return bool(rows)


def get_linked_partner(email: str) -> str | None:
    if backend() != "postgres" or not email:
        return None
    ensure_relationship_schema()
    email_n = _norm_email(email)
    links_t = partner_links_table()
    rows = run_query(
        f"""
        select user_email_a, user_email_b
        from {links_t}
        where user_email_a = %s or user_email_b = %s
        limit 1
        """,
        [email_n, email_n],
    )
    if not rows:
        return None
    a = _norm_email(str(rows[0].get("USER_EMAIL_A") or ""))
    b = _norm_email(str(rows[0].get("USER_EMAIL_B") or ""))
    if a == email_n:
        return b or None
    return a or None


def are_linked(email_a: str, email_b: str) -> bool:
    partner = get_linked_partner(email_a)
    return bool(partner and partner == _norm_email(email_b))


def can_view_profile(viewer_email: str, subject_email: str) -> bool:
    """Self, linked partner, or (future) public subject."""
    viewer = _norm_email(viewer_email)
    subject = _norm_email(subject_email)
    if not viewer or not subject:
        return False
    if viewer == subject:
        return True
    if are_linked(viewer, subject):
        return True
    if backend() != "postgres":
        return False
    ensure_relationship_schema()
    rows = run_query(
        f"""
        select profile_visibility
        from {user_profiles_table()}
        where lower(user_email) = lower(%s)
        limit 1
        """,
        [subject],
    )
    if not rows:
        return False
    return str(rows[0].get("PROFILE_VISIBILITY") or "private").strip().lower() == "public"


def create_partner_request(from_email: str, to_email: str) -> dict[str, Any]:
    """Create a pending partner request. In-app notify if recipient has an account."""
    if backend() != "postgres":
        raise RuntimeError("Partner linking requires Neon Postgres.")
    ensure_relationship_schema()
    from_n = _norm_email(from_email)
    to_n = _norm_email(to_email)
    if not from_n or not to_n:
        raise ValueError("Both emails are required.")
    if from_n == to_n:
        raise ValueError("You can’t link yourself.")
    if get_linked_partner(from_n):
        raise ValueError("You already have a linked partner. Unlink first.")
    if get_linked_partner(to_n):
        raise ValueError("That person already has a linked partner.")

    requests_t = partner_link_requests_table()
    existing = run_query(
        f"""
        select request_id, status
        from {requests_t}
        where lower(from_email) = %s and lower(to_email) = %s and status = 'pending'
        limit 1
        """,
        [from_n, to_n],
    )
    if existing:
        return {
            "REQUEST_ID": str(existing[0].get("REQUEST_ID")),
            "FROM_EMAIL": from_n,
            "TO_EMAIL": to_n,
            "STATUS": "pending",
            "RECIPIENT_HAS_ACCOUNT": profile_exists(to_n),
            "ALREADY_PENDING": True,
        }

    request_id = str(uuid.uuid4())
    execute_write(
        f"""
        insert into {requests_t} (request_id, from_email, to_email, status, created_at)
        values (%s, %s, %s, 'pending', NOW())
        """,
        [request_id, from_n, to_n],
    )

    recipient_has_account = profile_exists(to_n)
    signup_url = build_signup_invite_url(to_n, from_email=from_n)
    payload = {
        "request_id": request_id,
        "from_email": from_n,
        "to_email": to_n,
        "signup_url": signup_url,
        "recipient_has_account": recipient_has_account,
    }

    if recipient_has_account:
        _insert_notification(to_n, "partner_request", payload)
    else:
        log_event(
            "partner_invite_email",
            "Outbound partner invite email skipped (mail provider not configured)",
            level="info",
            email=from_n,
            detail=json.dumps(payload),
        )

    return {
        "REQUEST_ID": request_id,
        "FROM_EMAIL": from_n,
        "TO_EMAIL": to_n,
        "STATUS": "pending",
        "RECIPIENT_HAS_ACCOUNT": recipient_has_account,
        "SIGNUP_URL": signup_url,
        "ALREADY_PENDING": False,
    }


def cancel_partner_request(from_email: str, request_id: str) -> None:
    if backend() != "postgres":
        return
    ensure_relationship_schema()
    execute_write(
        f"""
        update {partner_link_requests_table()}
        set status = 'cancelled', responded_at = NOW()
        where request_id = %s
          and lower(from_email) = %s
          and status = 'pending'
        """,
        [str(request_id), _norm_email(from_email)],
    )


def list_pending_outbound(email: str) -> list[dict[str, Any]]:
    if backend() != "postgres" or not email:
        return []
    ensure_relationship_schema()
    rows = run_query(
        f"""
        select request_id, from_email, to_email, status, created_at
        from {partner_link_requests_table()}
        where lower(from_email) = %s and status = 'pending'
        order by created_at desc
        """,
        [_norm_email(email)],
    )
    return [
        {
            "REQUEST_ID": str(r.get("REQUEST_ID")),
            "FROM_EMAIL": r.get("FROM_EMAIL"),
            "TO_EMAIL": r.get("TO_EMAIL"),
            "STATUS": r.get("STATUS"),
            "CREATED_AT": r.get("CREATED_AT"),
        }
        for r in rows
    ]


def list_pending_inbound(email: str) -> list[dict[str, Any]]:
    if backend() != "postgres" or not email:
        return []
    ensure_relationship_schema()
    rows = run_query(
        f"""
        select request_id, from_email, to_email, status, created_at
        from {partner_link_requests_table()}
        where lower(to_email) = %s and status = 'pending'
        order by created_at desc
        """,
        [_norm_email(email)],
    )
    return [
        {
            "REQUEST_ID": str(r.get("REQUEST_ID")),
            "FROM_EMAIL": r.get("FROM_EMAIL"),
            "TO_EMAIL": r.get("TO_EMAIL"),
            "STATUS": r.get("STATUS"),
            "CREATED_AT": r.get("CREATED_AT"),
        }
        for r in rows
    ]


def respond_to_partner_request(to_email: str, request_id: str, *, accept: bool) -> None:
    if backend() != "postgres":
        raise RuntimeError("Partner linking requires Neon Postgres.")
    ensure_relationship_schema()
    to_n = _norm_email(to_email)
    requests_t = partner_link_requests_table()
    rows = run_query(
        f"""
        select request_id, from_email, to_email, status
        from {requests_t}
        where request_id = %s and lower(to_email) = %s
        limit 1
        """,
        [str(request_id), to_n],
    )
    if not rows:
        raise ValueError("Request not found.")
    row = rows[0]
    if str(row.get("STATUS") or "") != "pending":
        raise ValueError("Request is no longer pending.")
    from_n = _norm_email(str(row.get("FROM_EMAIL") or ""))

    new_status = "accepted" if accept else "declined"
    execute_write(
        f"""
        update {requests_t}
        set status = %s, responded_at = NOW()
        where request_id = %s
        """,
        [new_status, str(request_id)],
    )

    if accept:
        if get_linked_partner(to_n) or get_linked_partner(from_n):
            raise ValueError("One of you already has a linked partner.")
        a, b = _ordered_pair(from_n, to_n)
        execute_write(
            f"""
            insert into {partner_links_table()} (
                user_email_a, user_email_b, linked_at, requested_by_email
            ) values (%s, %s, NOW(), %s)
            on conflict do nothing
            """,
            [a, b, from_n],
        )
        _insert_notification(
            from_n,
            "partner_accepted",
            {"request_id": str(request_id), "from_email": from_n, "to_email": to_n},
        )
    else:
        _insert_notification(
            from_n,
            "partner_declined",
            {"request_id": str(request_id), "from_email": from_n, "to_email": to_n},
        )


def unlink_partner(email: str) -> None:
    if backend() != "postgres" or not email:
        return
    ensure_relationship_schema()
    email_n = _norm_email(email)
    execute_write(
        f"""
        delete from {partner_links_table()}
        where user_email_a = %s or user_email_b = %s
        """,
        [email_n, email_n],
    )


def list_notifications(email: str, *, unread_only: bool = False, limit: int = 30) -> list[dict[str, Any]]:
    if backend() != "postgres" or not email:
        return []
    ensure_relationship_schema()
    unread_sql = "and read_at is null" if unread_only else ""
    rows = run_query(
        f"""
        select notification_id, user_email, kind, payload, read_at, created_at
        from {user_notifications_table()}
        where lower(user_email) = %s
        {unread_sql}
        order by created_at desc
        limit %s
        """,
        [_norm_email(email), int(limit)],
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        payload = r.get("PAYLOAD") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        out.append(
            {
                "NOTIFICATION_ID": str(r.get("NOTIFICATION_ID")),
                "USER_EMAIL": r.get("USER_EMAIL"),
                "KIND": r.get("KIND"),
                "PAYLOAD": payload if isinstance(payload, dict) else {},
                "READ_AT": r.get("READ_AT"),
                "CREATED_AT": r.get("CREATED_AT"),
            }
        )
    return out


def count_unread_notifications(email: str) -> int:
    if backend() != "postgres" or not email:
        return 0
    ensure_relationship_schema()
    rows = run_query(
        f"""
        select count(*)::int as n
        from {user_notifications_table()}
        where lower(user_email) = %s and read_at is null
        """,
        [_norm_email(email)],
    )
    if not rows:
        return 0
    return int(rows[0].get("N") or 0)


def mark_notifications_read(email: str, notification_ids: list[str] | None = None) -> None:
    if backend() != "postgres" or not email:
        return
    ensure_relationship_schema()
    email_n = _norm_email(email)
    notif_t = user_notifications_table()
    if notification_ids:
        for nid in notification_ids:
            execute_write(
                f"""
                update {notif_t}
                set read_at = NOW()
                where notification_id = %s and lower(user_email) = %s and read_at is null
                """,
                [str(nid), email_n],
            )
    else:
        execute_write(
            f"""
            update {notif_t}
            set read_at = NOW()
            where lower(user_email) = %s and read_at is null
            """,
            [email_n],
        )
