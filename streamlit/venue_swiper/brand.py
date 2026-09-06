"""Après brand mark helpers (logo asset + metallic text fallback)."""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent / "assets"
_WORDMARK_LIGHT = _ASSETS / "apres_wordmark_light.png"
_WORDMARK_DARK = _ASSETS / "apres_wordmark_dark.png"


@lru_cache(maxsize=8)
def _data_uri(path: str, mime: str) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def brand_mark_html(*, size: str = "hero") -> str:
    """HTML for the Après wordmark.

    size:
      hero   — gold transparent mark (dark splash)
      header — dark metallic transparent mark (cream chrome)
    """
    if size == "hero":
        uri = _data_uri(str(_WORDMARK_LIGHT), "image/png")
        cls = "apres-brand-hero"
    else:
        uri = _data_uri(str(_WORDMARK_DARK), "image/png") or _data_uri(
            str(_WORDMARK_LIGHT), "image/png"
        )
        cls = "apres-brand-header"

    if uri:
        return f'<img class="{cls}" src="{uri}" alt="Après" />'
    return f'<div class="{cls} apres-brand-text">Après</div>'
