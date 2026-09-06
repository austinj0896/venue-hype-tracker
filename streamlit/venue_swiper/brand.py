"""Après brand mark helpers (logo asset + metallic text fallback)."""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent / "assets"
_WORDMARK = _ASSETS / "apres_wordmark_dark.png"
_WORDMARK_SM = _ASSETS / "apres_wordmark_dark_sm.png"
# Kept as fallback if dark assets are missing.
_WORDMARK_LIGHT = _ASSETS / "apres_wordmark_light.png"
_WORDMARK_LIGHT_SM = _ASSETS / "apres_wordmark_light_sm.png"


def wordmark_path(*, variant: str = "dark") -> Path | None:
    """Filesystem path for st.image (avoids huge base64 in the DOM).

    Prefer the dark metallic mark everywhere on cream UI.
    """
    mapping = {
        "dark": _WORDMARK,
        "dark_sm": _WORDMARK_SM,
        "hero": _WORDMARK,
        "header": _WORDMARK_SM,
        "light": _WORDMARK_LIGHT,
        "light_sm": _WORDMARK_LIGHT_SM,
    }
    path = mapping.get(variant, _WORDMARK)
    if path is not None and path.is_file():
        return path
    for fallback in (_WORDMARK, _WORDMARK_SM, _WORDMARK_LIGHT, _WORDMARK_LIGHT_SM):
        if fallback.is_file():
            return fallback
    return None


@lru_cache(maxsize=8)
def _data_uri(path: str, mime: str) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def brand_mark_html(*, size: str = "header") -> str:
    """HTML for the Après wordmark — dark metallic on cream."""
    if size == "hero":
        path = wordmark_path(variant="dark")
        cls = "apres-brand-hero"
    else:
        path = wordmark_path(variant="dark_sm")
        cls = "apres-brand-header"

    uri = _data_uri(str(path), "image/png") if path else None
    if uri:
        return f'<img class="{cls}" src="{uri}" alt="Après" />'
    return f'<div class="{cls} apres-brand-text">Après</div>'
