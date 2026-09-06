"""Après brand mark helpers (logo asset + metallic text fallback)."""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent / "assets"
_WORDMARK = _ASSETS / "apres_wordmark.png"
_WORDMARK_SM = _ASSETS / "apres_wordmark_sm.png"


def wordmark_path(*, variant: str = "default") -> Path | None:
    """Filesystem path for st.image — dark metallic mark only."""
    if variant in ("sm", "header", "dark_sm"):
        path = _WORDMARK_SM if _WORDMARK_SM.is_file() else _WORDMARK
    else:
        path = _WORDMARK if _WORDMARK.is_file() else _WORDMARK_SM
    return path if path is not None and path.is_file() else None


@lru_cache(maxsize=4)
def _data_uri(path: str, mime: str) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def brand_mark_html(*, size: str = "header") -> str:
    """HTML for the Après wordmark — dark metallic on cream."""
    path = wordmark_path(variant="sm" if size != "hero" else "default")
    cls = "apres-brand-hero" if size == "hero" else "apres-brand-header"
    uri = _data_uri(str(path), "image/png") if path else None
    if uri:
        return f'<img class="{cls}" src="{uri}" alt="Après" />'
    return f'<div class="{cls} apres-brand-text">Après</div>'
