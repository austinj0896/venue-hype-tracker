"""Load environment and paths for venue_hype_tracker."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")


def project_root() -> Path:
    return _PROJECT_ROOT


def sqlite_path() -> Path:
    raw = os.environ.get("SQLITE_PATH", "data/venue_hype.db")
    p = Path(raw)
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    return p


def google_places_api_key() -> str:
    key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "GOOGLE_PLACES_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return key


def snowflake_settings() -> dict[str, str]:
    account = os.environ.get("SNOWFLAKE_ACCOUNT", "").strip()
    user = os.environ.get("SNOWFLAKE_USER", "").strip()
    password = os.environ.get("SNOWFLAKE_PASSWORD", "").strip()
    warehouse = os.environ.get("SNOWFLAKE_WAREHOUSE", "").strip()
    if not account or not user or not warehouse:
        raise RuntimeError(
            "Set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, and SNOWFLAKE_WAREHOUSE in .env"
        )
    if not password and not os.environ.get("SNOWFLAKE_AUTHENTICATOR", "").strip():
        raise RuntimeError(
            "Set SNOWFLAKE_PASSWORD or SNOWFLAKE_AUTHENTICATOR (e.g. externalbrowser) in .env"
        )
    return {
        "account": account,
        "user": user,
        "password": password,
        "role": os.environ.get("SNOWFLAKE_ROLE", "").strip(),
        "warehouse": warehouse,
        "database": os.environ.get("SNOWFLAKE_DATABASE", "VENUE_HYPE").strip(),
        "schema": os.environ.get("SNOWFLAKE_SCHEMA", "RAW").strip(),
        "authenticator": os.environ.get("SNOWFLAKE_AUTHENTICATOR", "").strip(),
        "snowsql_connection": os.environ.get("SNOWSQL_CONNECTION", "venue_hype").strip(),
    }
