"""Tiny localStorage bridge: remember returning Après visitors (skip onboarding slides)."""

from __future__ import annotations

import os

import streamlit.components.v1 as components

_COMPONENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))

_apres_returning = components.declare_component(
    "apres_returning",
    path=_COMPONENT_DIR,
)


def read_returning_flag(*, key: str = "apres_returning_read") -> bool | None:
    """None while loading; True/False once the browser reports."""
    result = _apres_returning(mode="read", key=key, default=None)
    if result is None:
        return None
    if isinstance(result, dict):
        return bool(result.get("returning"))
    return bool(result)


def mark_returning(*, key: str = "apres_returning_write") -> None:
    """Persist that this device has signed in before."""
    _apres_returning(mode="write", key=key, default=None)
