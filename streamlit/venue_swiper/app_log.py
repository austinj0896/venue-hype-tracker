"""Structured client/app event logging for Après (Streamlit Cloud + Neon).

Writes to stdout (Cloud logs) and best-effort to Neon ``app_event_logs``
so we can see where users fail after login.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

import streamlit as st

from db import backend, execute_write, run_query

logger = logging.getLogger("apres")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [apres] %(message)s")
    )
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

_SCHEMA_KEY = "_app_event_logs_schema_ok"
SESSION_ERRORS_KEY = "apres_recent_errors"


def ensure_log_schema() -> None:
    if backend() != "postgres":
        return
    if st.session_state.get(_SCHEMA_KEY):
        return
    try:
        execute_write(
            """
            CREATE TABLE IF NOT EXISTS app_event_logs (
                id          BIGSERIAL PRIMARY KEY,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                user_email  TEXT,
                stage       TEXT NOT NULL,
                level       TEXT NOT NULL DEFAULT 'info',
                message     TEXT NOT NULL,
                detail      TEXT
            )
            """,
            [],
        )
        execute_write(
            """
            CREATE INDEX IF NOT EXISTS idx_app_event_logs_created
            ON app_event_logs (created_at DESC)
            """,
            [],
        )
        execute_write(
            """
            CREATE INDEX IF NOT EXISTS idx_app_event_logs_stage
            ON app_event_logs (stage, created_at DESC)
            """,
            [],
        )
        st.session_state[_SCHEMA_KEY] = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("app_event_logs schema failed: %s", exc)


def log_event(
    stage: str,
    message: str,
    *,
    level: str = "info",
    email: str | None = None,
    detail: str | None = None,
    exc: BaseException | None = None,
) -> None:
    """Log a stage event to Cloud logs + Neon (best effort)."""
    detail_text = detail
    if exc is not None:
        tb = traceback.format_exc()
        detail_text = (detail_text + "\n" if detail_text else "") + f"{exc!r}\n{tb}"

    line = f"stage={stage} email={email or '-'} msg={message}"
    if level == "error":
        logger.error("%s detail=%s", line, (detail_text or "")[:800])
    elif level == "warning":
        logger.warning("%s", line)
    else:
        logger.info("%s", line)

    if level in ("error", "warning"):
        recent = list(st.session_state.get(SESSION_ERRORS_KEY) or [])
        recent.append({"stage": stage, "message": message, "level": level})
        st.session_state[SESSION_ERRORS_KEY] = recent[-8:]

    if backend() != "postgres":
        return
    # Info events stay in Cloud logs only — Neon writes on the auth path
    # have contributed to mobile freezes (schema ensure + insert).
    if level == "info":
        return
    try:
        ensure_log_schema()
        execute_write(
            """
            INSERT INTO app_event_logs (user_email, stage, level, message, detail)
            VALUES (%s, %s, %s, %s, %s)
            """,
            [
                (email or "").strip().lower() or None,
                stage[:120],
                level[:20],
                message[:2000],
                (detail_text or "")[:8000] or None,
            ],
        )
    except Exception as write_exc:  # noqa: BLE001
        logger.warning("failed to persist app_event_logs: %s", write_exc)


def show_recent_errors() -> None:
    """Surface recent session errors in the UI when something failed."""
    recent = list(st.session_state.get(SESSION_ERRORS_KEY) or [])
    if not recent:
        return
    with st.expander("Diagnostics (recent errors)", expanded=True):
        for row in reversed(recent[-5:]):
            st.caption(f"[{row.get('level')}] {row.get('stage')}: {row.get('message')}")


def fetch_recent_logs(limit: int = 40) -> list[dict[str, Any]]:
    if backend() != "postgres":
        return []
    ensure_log_schema()
    try:
        return run_query(
            """
            SELECT created_at, user_email, stage, level, message, detail
            FROM app_event_logs
            ORDER BY created_at DESC
            LIMIT %s
            """,
            [limit],
        )
    except Exception:
        return []
