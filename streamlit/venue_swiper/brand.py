"""Après brand mark helpers (logo asset + metallic text fallback)."""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent / "assets"
_WORDMARK_PNG = _ASSETS / "apres_wordmark.png"
_WORDMARK_SPLASH = _ASSETS / "apres_wordmark_splash.jpg"


@lru_cache(maxsize=4)
def _data_uri(path: str, mime: str) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def brand_mark_html(*, size: str = "hero") -> str:
    """HTML for the Après wordmark. size: hero | header."""
    if size == "hero":
        uri = _data_uri(str(_WORDMARK_SPLASH), "image/jpeg") or _data_uri(
            str(_WORDMARK_PNG), "image/png"
        )
        cls = "apres-brand-hero"
    else:
        uri = _data_uri(str(_WORDMARK_PNG), "image/png")
        cls = "apres-brand-header"

    if uri:
        return f'<img class="{cls}" src="{uri}" alt="Après" />'
    return f'<div class="{cls} apres-brand-text">Après</div>'
