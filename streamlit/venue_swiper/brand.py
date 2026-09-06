"""Après brand mark helpers (logo asset + metallic text fallback)."""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent / "assets"
_WORDMARK_LIGHT = _ASSETS / "apres_wordmark_light.png"
_WORDMARK_DARK = _ASSETS / "apres_wordmark_dark.png"
_WORDMARK_LIGHT_SM = _ASSETS / "apres_wordmark_light_sm.png"
_WORDMARK_DARK_SM = _ASSETS / "apres_wordmark_dark_sm.png"


def wordmark_path(*, variant: str = "light") -> Path | None:
    """Filesystem path for st.image (avoids huge base64 in the DOM)."""
    mapping = {
        "light": _WORDMARK_LIGHT,
        "dark": _WORDMARK_DARK,
        "light_sm": _WORDMARK_LIGHT_SM,
        "dark_sm": _WORDMARK_DARK_SM,
    }
    path = mapping.get(variant)
    if path is None or not path.is_file():
        return None
    return path


@lru_cache(maxsize=8)
def _data_uri(path: str, mime: str) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def brand_mark_html(*, size: str = "hero") -> str:
    """HTML for the Après wordmark (prefer small assets in chrome).

    size:
      hero   — gold mark (prefer st.image via wordmark_path in splash)
      header — compact dark mark for status bar
    """
    if size == "hero":
        uri = _data_uri(str(_WORDMARK_LIGHT_SM if _WORDMARK_LIGHT_SM.is_file() else _WORDMARK_LIGHT), "image/png")
        cls = "apres-brand-hero"
    else:
        path = _WORDMARK_DARK_SM if _WORDMARK_DARK_SM.is_file() else _WORDMARK_DARK
        uri = _data_uri(str(path), "image/png") or _data_uri(
            str(_WORDMARK_LIGHT_SM if _WORDMARK_LIGHT_SM.is_file() else _WORDMARK_LIGHT),
            "image/png",
        )
        cls = "apres-brand-header"

    if uri:
        return f'<img class="{cls}" src="{uri}" alt="Après" />'
    return f'<div class="{cls} apres-brand-text">Après</div>'
