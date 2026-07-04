"""Après-themed geolocation button for Streamlit."""

from __future__ import annotations

import os

import streamlit.components.v1 as components

_COMPONENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))

_apres_geolocation = components.declare_component(
    "apres_geolocation",
    path=_COMPONENT_DIR,
)


def apres_geolocation(*, key: str | None = None) -> dict | None:
    """Return {latitude, longitude, accuracy} after the user shares location."""
    result = _apres_geolocation(key=key)
    if isinstance(result, dict):
        return result
    return None
