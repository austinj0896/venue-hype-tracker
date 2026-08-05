#!/usr/bin/env python3
"""Fetch venue hours of operation with local Ollama (no Places API).

Pass 1 — scrape venue website (homepage + hours/contact pages).
Pass 2 — DuckDuckGo Google/web search for hours when the site is thin
          or confidence is low (searching \"{name} hours\" usually helps).

Stores current hours in venue_hours and archives changes to
venue_hours_history so you can re-run periodically.

Examples:
  python scripts/fetch_venue_hours.py --apply-schema
  python scripts/fetch_venue_hours.py --name "North End" --save
  python scripts/fetch_venue_hours.py --borough "Manhattan Beach" --limit 200 --save
  python scripts/fetch_venue_hours.py --borough "Manhattan Beach" --stale-days 14 --limit 500 --save
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[misc, assignment]

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:7b"
MIN_ACCEPT = 0.65
MAX_PAGE_CHARS = 3500
MAX_SECONDARY_PAGES = 3
MAX_SEARCH_CHARS = 3500
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_HOURS_LINK_RE = re.compile(
    r"(?i)\b("
    r"hours|hour|open|opening|schedule|location|locations|"
    r"contact|visit|find[-_\s]?us|directions|about"
    r")\b"
)
_SKIP_LINK_RE = re.compile(
    r"(?i)(careers?|jobs?|privacy|terms|login|cart|checkout|instagram|"
    r"facebook|twitter|tiktok|mailto:|tel:|javascript:|#$|menu|order)"
)
_HOURS_LINE_RE = re.compile(
    r"(?i)\b("
    r"hours|open|closed|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|mon|tue|wed|thu|fri|sat|sun|"
    r"am\b|pm\b|\d{1,2}:\d{2}"
    r")\b"
)
# Real weekly schedule: weekday + (clock range or Closed) — not "48 hours notice".
_SCHEDULE_SIGNAL_RE = re.compile(
    r"(?i)\b("
    r"mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|"
    r"fri(?:day)?|sat(?:urday)?|sun(?:day)?"
    r")\b"
    r".{0,20}"
    r"(?:"
    r"closed"
    r"|"
    r"\d{1,2}(?::\d{2})?\s*(?:am|pm)"
    r"|"
    r"\d{1,2}:\d{2}"
    r")"
)
_FALSE_HOURS_RE = re.compile(
    r"(?i)("
    r"\d+\s*hours?\s+notice|"
    r"after\s+hours|"
    r"happy\s+hour|"
    r"24\s*hours?\s+notice|"
    r"within\s+\d+\s+hours|"
    r"business\s+hours\s+only"
    r")"
)
_DAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
_DAY_ALIASES = {
    "mon": "monday",
    "monday": "monday",
    "tue": "tuesday",
    "tues": "tuesday",
    "tuesday": "tuesday",
    "wed": "wednesday",
    "wednesday": "wednesday",
    "thu": "thursday",
    "thur": "thursday",
    "thurs": "thursday",
    "thursday": "thursday",
    "fri": "friday",
    "friday": "friday",
    "sat": "saturday",
    "saturday": "saturday",
    "sun": "sunday",
    "sunday": "sunday",
}


def looks_like_weekly_schedule(text: str) -> bool:
    """True only for weekday+time / Closed schedules — not '48 hours notice'."""
    if not text:
        return False
    # Strip common false positives before matching.
    cleaned = _FALSE_HOURS_RE.sub(" ", text)
    hits = _SCHEDULE_SIGNAL_RE.findall(cleaned)
    # Need at least 2 weekday schedule hits to trust it.
    return len(hits) >= 2


def _to_24h(token: str) -> str | None:
    token = re.sub(r"\s+", " ", (token or "").strip().lower())
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", token)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = m.group(3)
    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if not ampm and hour > 23:
        return None
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def parse_schedule_from_text(text: str) -> dict[str, Any] | None:
    """Heuristic parse for Yelp/Google-style schedule snippets.

    Examples:
      Mon - 7:00 am - 1:00 pm, Tue - Closed, Wed - 7:00 am - 1:00 pm
      Monday: 11:00 AM – 10:00 PM
    """
    if not text:
        return None
    pattern = re.compile(
        r"(?i)\b(?P<day>mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|"
        r"thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b"
        r"\s*[-–:|]\s*"
        r"(?:"
        r"(?P<closed>closed)"
        r"|"
        r"(?P<open>\d{1,2}(?::\d{2})?\s*(?:am|pm)?)"
        r"\s*[-–to]+\s*"
        r"(?P<close>\d{1,2}(?::\d{2})?\s*(?:am|pm)?)"
        r")"
    )
    hours: dict[str, Any] = {d: None for d in _DAYS}
    found = 0
    for m in pattern.finditer(text):
        day = _DAY_ALIASES.get(m.group("day").lower())
        if not day:
            continue
        if m.group("closed"):
            hours[day] = []  # empty list = explicitly closed
            found += 1
            continue
        open_t = _to_24h(m.group("open") or "")
        close_t = _to_24h(m.group("close") or "")
        if open_t and close_t:
            hours[day] = [{"open": open_t, "close": close_t}]
            found += 1
    if found < 3:
        return None

    lines: list[str] = []
    for day in _DAYS:
        label = day.capitalize()
        val = hours[day]
        if val is None:
            lines.append(f"{label}: (unknown)")
        elif val == []:
            hours[day] = None  # store null for closed in JSON; text says Closed
            lines.append(f"{label}: Closed")
        else:
            o, c = val[0]["open"], val[0]["close"]

            def fmt(t: str) -> str:
                h, m = map(int, t.split(":"))
                ampm = "AM" if h < 12 else "PM"
                h12 = h % 12 or 12
                return f"{h12}:{m:02d} {ampm}"

            lines.append(f"{label}: {fmt(o)} – {fmt(c)}")

    return {
        "status": "ok",
        "confidence": 0.9,
        "timezone": "America/Los_Angeles",
        "notes": "Parsed from search/website schedule snippet",
        "source_preference": "google_search",
        "evidence": text[:280],
        "hours": hours,
        "hours_text": "\n".join(lines),
    }


def snippet_schedule_score(text: str) -> float:
    if not text:
        return -1.0
    if "RuntimeError" in text or "search error" in text.lower():
        return -5.0
    score = 0.0
    if looks_like_weekly_schedule(text):
        score += 5.0
    score += min(len(_SCHEDULE_SIGNAL_RE.findall(text)), 7) * 0.8
    if re.search(r"(?i)mon\s*[-–].*tue\s*[-–]", text):
        score += 3.0
    if re.search(r"(?i)\d{1,2}:\d{2}\s*(am|pm)", text):
        score += 1.5
    if _FALSE_HOURS_RE.search(text) and not looks_like_weekly_schedule(text):
        score -= 3.0
    return score
    if explicit:
        return explicit
    if load_dotenv:
        load_dotenv(ROOT / ".env")
    url = os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")
    if not url:
        raise SystemExit(
            "Set DATABASE_URL (Neon pooled connection string) or pass --database-url"
        )
    return url


def load_database_url(explicit: str | None) -> str:
    if explicit:
        return explicit
    if load_dotenv:
        load_dotenv(ROOT / ".env")
    url = os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")
    if not url:
        raise SystemExit(
            "Set DATABASE_URL (Neon pooled connection string) or pass --database-url"
        )
    return url


def connect(url: str):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    return psycopg2.connect(url, cursor_factory=RealDictCursor)


def apply_schema(conn) -> None:
    schema_path = ROOT / "neon" / "venue_hours_schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    print(f"Applied schema from {schema_path}")


def reconnect(db_url: str, old_conn=None):
    if old_conn is not None:
        try:
            old_conn.close()
        except Exception:  # noqa: BLE001
            pass
    return connect(db_url)


def fetch_places(
    conn,
    *,
    name: str | None,
    place_id: str | None,
    borough: str | None,
    limit: int,
    require_website: bool,
    stale_days: int | None,
    force: bool,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if place_id:
        clauses.append("p.google_place_id = %s")
        params.append(place_id)
    if name:
        clauses.append("p.place_name ILIKE %s")
        params.append(f"%{name}%")
    if borough:
        clauses.append("p.borough ILIKE %s")
        params.append(borough)
    if require_website:
        clauses.append("p.website_uri IS NOT NULL AND trim(p.website_uri) <> ''")
    if stale_days is not None and not force:
        # Missing hours OR last fetch older than N days OR previous run failed/empty.
        clauses.append(
            """
            (
              h.google_place_id IS NULL
              OR h.fetched_at < NOW() - (%s || ' days')::interval
              OR h.status IN ('empty', 'error')
            )
            """
        )
        params.append(str(int(stale_days)))

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT p.google_place_id, p.place_name, p.primary_type, p.venue_category,
               p.price_level, p.website_uri, p.borough, p.formatted_address,
               p.short_formatted_address,
               h.fetched_at AS hours_fetched_at,
               h.status AS hours_status
        FROM places p
        LEFT JOIN venue_hours h ON h.google_place_id = p.google_place_id
        {where}
        ORDER BY p.place_name
        LIMIT %s
    """
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def clean_html_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    # Keep header/footer — venues often put hours there.
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _same_site(base_url: str, candidate: str) -> bool:
    try:
        b = urlparse(base_url)
        c = urlparse(candidate)
    except Exception:  # noqa: BLE001
        return False
    if not c.scheme.startswith("http"):
        return False
    return (c.netloc or "").lower() == (b.netloc or "").lower()


def _score_hours_link(href: str, anchor: str) -> float:
    blob = f"{href} {anchor}".lower()
    if _SKIP_LINK_RE.search(blob):
        return -1.0
    if not _HOURS_LINK_RE.search(blob):
        return -1.0
    score = 1.0
    for token, weight in (
        ("hours", 4.0),
        ("hour", 3.5),
        ("open", 2.5),
        ("schedule", 2.5),
        ("location", 2.0),
        ("contact", 2.0),
        ("visit", 1.5),
        ("about", 1.0),
    ):
        if token in blob:
            score += weight
    return score


def discover_hours_urls(html: str, base_url: str) -> list[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    scored: list[tuple[float, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        absolute = urljoin(base_url, href)
        absolute, _ = urldefrag(absolute)
        if absolute in seen or not _same_site(base_url, absolute):
            continue
        if absolute.rstrip("/") == base_url.rstrip("/"):
            continue
        anchor = a.get_text(" ", strip=True) or ""
        score = _score_hours_link(absolute, anchor)
        if score < 0:
            continue
        seen.add(absolute)
        scored.append((score, absolute))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [url for _, url in scored[:MAX_SECONDARY_PAGES]]


def _fetch_html(url: str, timeout: float = 20.0) -> dict[str, Any]:
    import requests

    try:
        resp = requests.get(
            url.strip(),
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc), "html": "", "final_url": url}

    if resp.status_code in (401, 403, 429) or resp.status_code >= 400:
        return {
            "ok": False,
            "error": f"HTTP {resp.status_code}",
            "html": "",
            "final_url": resp.url,
            "blocked": resp.status_code in (401, 403, 429),
        }
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "html" not in ctype and "text" not in ctype and ctype:
        return {
            "ok": False,
            "error": f"Unsupported content-type: {ctype}",
            "html": "",
            "final_url": resp.url,
        }
    return {"ok": True, "error": None, "html": resp.text, "final_url": resp.url}


def prefer_hours_excerpt(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    lines = text.splitlines()
    scored: list[tuple[float, int, str]] = []
    for idx, line in enumerate(lines):
        if not _HOURS_LINE_RE.search(line):
            continue
        hits = len(_HOURS_LINE_RE.findall(line))
        scored.append((float(hits) + min(len(line) / 200.0, 1.0), idx, line))
    if not scored:
        return text[:limit]
    scored.sort(key=lambda x: (-x[0], x[1]))
    chosen: set[int] = set()
    size = 0
    for _, idx, line in scored:
        if size + len(line) + 1 > limit:
            continue
        chosen.add(idx)
        size += len(line) + 1
        if size >= limit:
            break
    ordered = [lines[i] for i in sorted(chosen)]
    out = "\n".join(ordered)
    if len(out) < max(limit // 3, 200):
        remaining = limit - len(out) - 10
        head = text[: max(remaining, 0)]
        out = f"{out}\n...\n{head}" if head else out
    return out[:limit]


def scrape_website_hours(url: str) -> dict[str, Any]:
    if not url or not str(url).strip():
        return {
            "status": "no_website",
            "text": "",
            "error": None,
            "final_url": None,
            "pages_fetched": [],
            "has_hours_signal": False,
        }

    home = _fetch_html(url)
    if not home.get("ok"):
        return {
            "status": "blocked" if home.get("blocked") else "error",
            "text": "",
            "error": home.get("error"),
            "final_url": home.get("final_url") or url,
            "pages_fetched": [],
            "has_hours_signal": False,
        }

    final_url = home["final_url"] or url
    home_text = clean_html_text(home["html"])
    parts = [f"[Homepage]\n{prefer_hours_excerpt(home_text, MAX_PAGE_CHARS)}"]
    pages = [final_url]

    for sec in discover_hours_urls(home["html"], final_url):
        page = _fetch_html(sec)
        if not page.get("ok"):
            continue
        page_text = clean_html_text(page["html"])
        if len(page_text) < 40:
            continue
        label = sec.rstrip("/").rsplit("/", 1)[-1] or "page"
        parts.append(f"[{label}]\n{prefer_hours_excerpt(page_text, 2000)}")
        pages.append(page.get("final_url") or sec)
        time.sleep(0.35)

    combined = "\n\n".join(parts)
    has_signal = looks_like_weekly_schedule(combined)
    return {
        "status": "ok" if combined.strip() else "empty",
        "text": combined[: MAX_PAGE_CHARS + 6000],
        "error": None,
        "final_url": final_url,
        "pages_fetched": pages,
        "has_hours_signal": has_signal,
    }


def _location_query(place: dict[str, Any]) -> str:
    parts = [
        place.get("borough") or "",
        place.get("short_formatted_address") or place.get("formatted_address") or "",
    ]
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p).strip())


def _ddg_text(query: str, *, max_results: int = 8) -> list[dict[str, str]]:
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "ddgs is required. pip install -r scripts/requirements-tagging.txt"
            ) from exc

    out: list[dict[str, str]] = []
    with DDGS() as ddgs:
        for item in ddgs.text(query, max_results=max_results):
            href = (item.get("href") or item.get("link") or "").strip()
            title = (item.get("title") or "").strip()
            body = (item.get("body") or item.get("snippet") or "").strip()
            if not (title or body or href):
                continue
            out.append({"title": title, "url": href, "snippet": body})
    return out


def search_google_hours(place: dict[str, Any]) -> dict[str, Any]:
    """Search the open web (incl. Google result snippets) for hours."""
    name = (place.get("place_name") or "").strip()
    loc = _location_query(place)
    if not name:
        return {"status": "empty", "text": "", "sources": [], "urls": [], "queries": []}

    queries = [
        f'"{name}" {loc} hours',
        f'"{name}" {loc} opening hours',
        f'"{name}" {loc} open today',
        f'"{name}" {loc} site:google.com hours',
    ]
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for q in queries:
        try:
            batch = _ddg_text(q, max_results=6)
        except Exception as exc:  # noqa: BLE001
            results.append({"title": "[search error]", "url": "", "snippet": str(exc)})
            continue
        for row in batch:
            key = row.get("url") or f"{row.get('title')}|{(row.get('snippet') or '')[:80]}"
            if key in seen:
                continue
            seen.add(key)
            results.append(row)
        time.sleep(0.45)

    # Prefer snippets that look like hours schedules; rank best first.
    scored: list[tuple[float, str, str]] = []
    for row in results:
        snippet = re.sub(r"\s+", " ", (row.get("snippet") or "").strip())
        title = re.sub(r"\s+", " ", (row.get("title") or "").strip())
        url = (row.get("url") or "").strip()
        if snippet.startswith("[search error]") or "RuntimeError" in snippet:
            continue
        candidates = [c for c in (snippet, title) if c]
        for cand in candidates:
            if not _HOURS_LINE_RE.search(cand):
                continue
            # Body first — titles alone are weak unless they contain times.
            if cand is title and not re.search(r"(?i)\d{1,2}(:\d{2})?\s*(am|pm)", title):
                continue
            if len(cand) < 25 and not looks_like_weekly_schedule(cand):
                continue
            scored.append((snippet_schedule_score(cand), cand, url))

    scored.sort(key=lambda x: (-x[0], -len(x[1])))
    deduped: list[str] = []
    urls: list[str] = []
    seen_l: set[str] = set()
    seen_u: set[str] = set()
    for score, line, url in scored:
        key = line.lower()
        if key in seen_l:
            continue
        seen_l.add(key)
        prefix = "SCHEDULE: " if score >= 5 else ""
        deduped.append(prefix + line)
        if url and url not in seen_u:
            seen_u.add(url)
            urls.append(url)
        if len(deduped) >= 14:
            break

    text = ""
    if deduped:
        text = (
            "Search snippets (hours-related; lines marked SCHEDULE are strongest):\n"
            + "\n".join(f"- {s}" for s in deduped)
        )
    text = text[:MAX_SEARCH_CHARS]
    return {
        "status": "ok" if text.strip() else "empty",
        "text": text,
        "sources": ["duckduckgo_google_hours"] if text else [],
        "urls": urls[:8],
        "queries": queries,
        "result_count": len(results),
        "best_schedule_snippet": next(
            (s[len("SCHEDULE: ") :] for s in deduped if s.startswith("SCHEDULE: ")),
            None,
        ),
    }


def check_ollama(base_url: str, model: str) -> None:
    import requests

    try:
        resp = requests.get(urljoin(base_url.rstrip("/") + "/", "api/tags"), timeout=5)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"Ollama not reachable at {base_url}: {exc}") from exc
    names = {m.get("name") for m in (resp.json().get("models") or [])}
    if model not in names and f"{model}:latest" not in names:
        if not any(str(n).startswith(model.split(":")[0]) for n in names):
            print(f"Warning: model {model!r} not listed in Ollama tags: {sorted(names)[:8]}")


def call_ollama(prompt: str, *, model: str, base_url: str, timeout: float = 180.0) -> dict[str, Any]:
    import requests

    url = urljoin(base_url.rstrip("/") + "/", "api/chat")
    resp = requests.post(
        url,
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You extract restaurant/bar hours of operation. "
                        "Output JSON only. Prefer explicit schedules over guesses."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    content = payload.get("message", {}).get("content", "")
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        return json.loads(content)
    raise ValueError(f"Unexpected Ollama content type: {type(content)}")


def build_hours_prompt(
    place: dict[str, Any],
    *,
    website_text: str,
    search_text: str,
) -> str:
    return f"""Extract weekly hours of operation for this venue from EACH source separately.

Rules:
- Score WEBSITE and SEARCH independently. Do NOT prefer website by default.
- Pick the source with the clearest weekday schedule (Mon–Sun with open/close or Closed).
- Lines marked SCHEDULE in SEARCH are highest-quality (often Yelp).
- Do NOT invent hours. If a source has no schedule, that candidate status is "empty".
- Never mark every day Closed unless the source explicitly says the business is closed all week.
- "48 hours notice" / "happy hour" are NOT weekly hours.
- Times must be 24-hour "HH:MM" in open/close fields.
- Return JSON only:
{{
  "candidates": [
    {{
      "source": "website" | "search",
      "status": "ok" | "partial" | "empty",
      "confidence": 0.0,
      "evidence": "short quote from that source only",
      "hours": {{
        "monday": [{{"open": "07:00", "close": "13:00"}}] or null,
        "tuesday": null,
        "wednesday": null,
        "thursday": null,
        "friday": null,
        "saturday": null,
        "sunday": null
      }},
      "hours_text": [
        "Monday: 7:00 AM – 1:00 PM",
        "Tuesday: Closed",
        "Wednesday: ...",
        "Thursday: ...",
        "Friday: ...",
        "Saturday: ...",
        "Sunday: ..."
      ]
    }}
  ],
  "best_source": "website" | "search" | "none",
  "notes": "optional"
}}

Venue:
{json.dumps({
    "name": place.get("place_name"),
    "borough": place.get("borough"),
    "address": place.get("short_formatted_address") or place.get("formatted_address"),
    "primary_type": place.get("primary_type"),
    "website_uri": place.get("website_uri"),
}, indent=2)}

WEBSITE text:
{website_text or "(none)"}

SEARCH text:
{search_text or "(none)"}
"""


def _normalize_hours_dict(hours_in: Any) -> tuple[dict[str, Any], bool]:
    hours_out: dict[str, Any] = {}
    any_open = False
    if not isinstance(hours_in, dict):
        hours_in = {}
    for day in _DAYS:
        val = hours_in.get(day)
        if val is None:
            hours_out[day] = None
            continue
        periods: list[dict[str, str]] = []
        if isinstance(val, list):
            for item in val:
                if not isinstance(item, dict):
                    continue
                open_t = str(item.get("open") or "").strip()
                close_t = str(item.get("close") or "").strip()
                if re.match(r"^\d{1,2}:\d{2}$", open_t) and re.match(r"^\d{1,2}:\d{2}$", close_t):
                    if len(open_t) == 4:
                        open_t = open_t.zfill(5)
                    if len(close_t) == 4:
                        close_t = close_t.zfill(5)
                    periods.append({"open": open_t, "close": close_t})
        hours_out[day] = periods or None
        if periods:
            any_open = True
    return hours_out, any_open


def _hours_text_from_value(hours_text: Any) -> str | None:
    if isinstance(hours_text, list):
        out = "\n".join(str(x).strip() for x in hours_text if str(x).strip())
        return out or None
    text = str(hours_text or "").strip()
    return text or None


def normalize_candidate(raw: dict[str, Any], *, default_source: str) -> dict[str, Any]:
    status = str(raw.get("status") or "empty").lower().strip()
    if status not in {"ok", "partial", "empty"}:
        status = "empty"
    try:
        confidence = float(raw.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    hours_out, any_open = _normalize_hours_dict(raw.get("hours"))
    hours_text = _hours_text_from_value(raw.get("hours_text"))
    closed_only = (not any_open) and bool(
        hours_text and re.search(r"(?i)closed", hours_text)
    ) and not re.search(r"(?i)\d{1,2}(:\d{2})?\s*(am|pm)", hours_text or "")

    if not any_open and not hours_text:
        status = "empty"
        confidence = min(confidence, 0.2)
    elif closed_only:
        # All-closed with no open times is usually a bad guess unless evidence is strong.
        status = "partial"
        confidence = min(confidence, 0.35)

    source = str(raw.get("source") or default_source).lower().strip()
    if source in {"google_search", "search"}:
        source = "search"
    if source not in {"website", "search", "yelp", "heuristic"}:
        source = default_source

    return {
        "status": status,
        "confidence": round(confidence, 3),
        "timezone": (str(raw.get("timezone")).strip() if raw.get("timezone") else None),
        "notes": (str(raw.get("notes")).strip() if raw.get("notes") else None),
        "evidence": (str(raw.get("evidence")).strip() if raw.get("evidence") else None),
        "source": source,
        "hours_json": hours_out,
        "hours_text": hours_text,
        "any_open": any_open,
    }


def normalize_hours_result(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize Ollama output into a list of scored candidates."""
    candidates_raw = raw.get("candidates")
    out: list[dict[str, Any]] = []
    if isinstance(candidates_raw, list) and candidates_raw:
        for item in candidates_raw:
            if isinstance(item, dict):
                out.append(normalize_candidate(item, default_source="search"))
        return out

    # Backward-compatible single-object response.
    single = normalize_candidate(raw, default_source="search")
    pref = str(raw.get("source_preference") or raw.get("best_source") or "none").lower()
    if pref in {"website", "search", "yelp"}:
        single["source"] = pref
    elif pref == "google_search":
        single["source"] = "search"
    out.append(single)
    return out


def label_search_source(urls: list[str]) -> str:
    for u in urls:
        host = urlparse(u).netloc.lower()
        if "yelp.com" in host:
            return "yelp"
        if "google." in host or "maps." in host:
            return "google_search"
    return "google_search"


def candidate_rank_key(c: dict[str, Any]) -> tuple:
    """Higher is better."""
    status_bonus = {"ok": 2, "partial": 1, "empty": 0}.get(c.get("status") or "", 0)
    open_bonus = 1 if c.get("any_open") else 0
    return (status_bonus, open_bonus, float(c.get("confidence") or 0.0))


def pick_best_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    usable = [c for c in candidates if c.get("status") in {"ok", "partial"} and c.get("hours_text")]
    if not usable:
        usable = [c for c in candidates if c.get("status") in {"ok", "partial"}]
    if not usable:
        return None
    usable.sort(key=candidate_rank_key, reverse=True)
    return usable[0]


def resolve_stored_source(candidate: dict[str, Any], search_urls: list[str]) -> str:
    src = candidate.get("source") or "none"
    if src == "search":
        return label_search_source(search_urls)
    if src == "heuristic":
        # Prefer yelp/google label when heuristic came from search URLs.
        if search_urls:
            return label_search_source(search_urls)
        return "heuristic"
    if src in {"website", "yelp", "google_search", "website+google_search", "none"}:
        return src
    return "none"


def content_hash(*parts: str) -> str:
    blob = "\n".join(p or "" for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def upsert_hours(
    conn,
    place: dict[str, Any],
    result: dict[str, Any],
    *,
    source: str,
    source_urls: list[str],
    model: str,
    evidence_hash: str,
) -> str:
    """Upsert current hours; archive prior row when content changes. Returns change_kind."""
    place_id = place["google_place_id"]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT hours_json, hours_text, content_hash, status, source, confidence, model_version
            FROM venue_hours
            WHERE google_place_id = %s
            """,
            (place_id,),
        )
        prev = cur.fetchone()

        change_kind = "first"
        if prev:
            prev_hash = prev.get("content_hash")
            prev_text = prev.get("hours_text") or ""
            new_text = result.get("hours_text") or ""
            if prev_hash == evidence_hash and prev_text == new_text:
                change_kind = "refresh"
            elif not new_text and prev_text:
                change_kind = "cleared"
            else:
                change_kind = "changed"

            cur.execute(
                """
                INSERT INTO venue_hours_history (
                    google_place_id, hours_json, hours_text, source, confidence,
                    status, model_version, content_hash, fetched_at, change_kind
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, NOW(), %s
                )
                """,
                (
                    place_id,
                    json.dumps(prev.get("hours_json")) if prev.get("hours_json") is not None else None,
                    prev.get("hours_text"),
                    prev.get("source"),
                    prev.get("confidence"),
                    prev.get("status"),
                    prev.get("model_version"),
                    prev.get("content_hash"),
                    change_kind,
                ),
            )

        status = result["status"]
        if status == "empty" and result.get("confidence", 0) <= 0:
            # keep empty but mark cleanly
            pass

        cur.execute(
            """
            INSERT INTO venue_hours (
                google_place_id, hours_json, hours_text, timezone, notes,
                source, source_urls, confidence, evidence, status,
                model_version, content_hash, fetched_at, updated_at
            ) VALUES (
                %s, %s::jsonb, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, NOW(), NOW()
            )
            ON CONFLICT (google_place_id) DO UPDATE SET
                hours_json = EXCLUDED.hours_json,
                hours_text = EXCLUDED.hours_text,
                timezone = EXCLUDED.timezone,
                notes = EXCLUDED.notes,
                source = EXCLUDED.source,
                source_urls = EXCLUDED.source_urls,
                confidence = EXCLUDED.confidence,
                evidence = EXCLUDED.evidence,
                status = EXCLUDED.status,
                model_version = EXCLUDED.model_version,
                content_hash = EXCLUDED.content_hash,
                fetched_at = NOW(),
                updated_at = NOW()
            """,
            (
                place_id,
                json.dumps(result.get("hours_json") or {}),
                result.get("hours_text"),
                result.get("timezone"),
                result.get("notes"),
                source,
                source_urls or None,
                result.get("confidence"),
                result.get("evidence"),
                status if status in {"ok", "partial", "empty", "error"} else "empty",
                model,
                evidence_hash,
            ),
        )
    conn.commit()
    return change_kind


def fetch_one(
    place: dict[str, Any],
    *,
    model: str,
    ollama_url: str,
    force_search: bool,
    no_search: bool,
    dry_run_prompt: bool,
) -> dict[str, Any]:
    # Always gather website; search unless disabled. Run both in parallel.
    website: dict[str, Any] = {
        "status": "no_website",
        "text": "",
        "error": None,
        "final_url": None,
        "pages_fetched": [],
        "has_hours_signal": False,
    }
    search: dict[str, Any] = {
        "status": "skipped",
        "text": "",
        "sources": [],
        "urls": [],
        "best_schedule_snippet": None,
    }

    need_search = not no_search  # default: always search; confidence pick decides winner
    if not force_search and no_search:
        need_search = False

    def do_website() -> dict[str, Any]:
        return scrape_website_hours(place.get("website_uri") or "")

    def do_search() -> dict[str, Any]:
        return search_google_hours(place)

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_web = pool.submit(do_website)
        fut_search = pool.submit(do_search) if need_search else None
        website = fut_web.result()
        if fut_search is not None:
            try:
                search = fut_search.result()
            except Exception as exc:  # noqa: BLE001
                search = {
                    "status": "error",
                    "text": "",
                    "sources": [],
                    "urls": [],
                    "error": str(exc),
                    "best_schedule_snippet": None,
                }

    candidates: list[dict[str, Any]] = []

    # Deterministic parsers — usually beat the LLM on Yelp-style snippets.
    web_parsed = parse_schedule_from_text(website.get("text") or "")
    if web_parsed:
        c = normalize_candidate(
            {
                **web_parsed,
                "source": "website",
                "confidence": max(float(web_parsed.get("confidence") or 0.85), 0.85),
            },
            default_source="website",
        )
        c["source"] = "website"
        candidates.append(c)

    best_snip = search.get("best_schedule_snippet") or ""
    search_parsed = parse_schedule_from_text(best_snip) or parse_schedule_from_text(
        search.get("text") or ""
    )
    if search_parsed:
        search_label = label_search_source(list(search.get("urls") or []))
        c = normalize_candidate(
            {
                **search_parsed,
                "source": search_label,
                "confidence": max(float(search_parsed.get("confidence") or 0.9), 0.9),
            },
            default_source=search_label,
        )
        c["source"] = search_label
        candidates.append(c)

    prompt = build_hours_prompt(
        place,
        website_text=website.get("text") or "",
        search_text=search.get("text") or "",
    )
    if dry_run_prompt:
        print(prompt)
        return {
            "result": {
                "status": "empty",
                "confidence": 0,
                "hours_json": {},
                "hours_text": None,
                "evidence": None,
                "timezone": None,
                "notes": None,
            },
            "website": website,
            "search": search,
            "source": "none",
            "source_urls": [],
            "candidates": candidates,
            "evidence_hash": content_hash(website.get("text") or "", search.get("text") or ""),
        }

    try:
        raw = call_ollama(prompt, model=model, base_url=ollama_url)
        llm_candidates = normalize_hours_result(raw)
        for c in llm_candidates:
            if c.get("source") == "search":
                c["source"] = label_search_source(list(search.get("urls") or []))
            candidates.append(c)
    except Exception as exc:  # noqa: BLE001
        print(f"  → ollama failed ({exc}); using heuristic candidates if any")

    best = pick_best_candidate(candidates)
    if best is None:
        best = {
            "status": "empty",
            "confidence": 0.0,
            "hours_json": {d: None for d in _DAYS},
            "hours_text": None,
            "timezone": None,
            "notes": "No usable hours found in website or search",
            "evidence": None,
            "source": "none",
            "any_open": False,
        }

    source = resolve_stored_source(best, list(search.get("urls") or []))
    urls = list(website.get("pages_fetched") or []) + list(search.get("urls") or [])
    seen_u: set[str] = set()
    source_urls: list[str] = []
    for u in urls:
        if u and u not in seen_u:
            seen_u.add(u)
            source_urls.append(u)

    return {
        "result": best,
        "website": website,
        "search": search,
        "source": source,
        "source_urls": source_urls,
        "candidates": candidates,
        "evidence_hash": content_hash(website.get("text") or "", search.get("text") or ""),
    }


def print_result(place: dict[str, Any], payload: dict[str, Any]) -> None:
    website = payload["website"]
    search = payload["search"]
    result = payload["result"]
    print()
    print("=" * 72)
    print(f"{place.get('place_name')}  ({place.get('borough')})")
    print(f"website: {place.get('website_uri')}")
    print(
        f"website scrape: {website.get('status')}"
        + (f" ({website.get('error')})" if website.get("error") else "")
        + f"  hours_signal={website.get('has_hours_signal')}"
    )
    pages = website.get("pages_fetched") or []
    if pages:
        print(f"pages: {', '.join(pages[:4])}" + (" ..." if len(pages) > 4 else ""))
    print(
        f"search: {search.get('status')}  "
        f"sources={','.join(search.get('sources') or []) or 'none'}"
    )
    cands = payload.get("candidates") or []
    if cands:
        print("candidates:")
        for c in sorted(cands, key=candidate_rank_key, reverse=True):
            print(
                f"  {c.get('confidence', 0):.2f}  {c.get('source')}  "
                f"status={c.get('status')}  open_days={1 if c.get('any_open') else 0}"
            )
    print(f"source used: {payload.get('source')}  confidence={result.get('confidence')}")
    print(f"status: {result.get('status')}")
    if result.get("hours_text"):
        print("hours:")
        for line in str(result["hours_text"]).splitlines():
            print(f"  {line}")
    else:
        print("hours: (none)")
    if result.get("notes"):
        print(f"notes: {result['notes']}")
    if result.get("evidence"):
        evid = str(result["evidence"]).replace("\n", " ")
        print(f"evidence: {evid[:240]}")
    print("=" * 72)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch venue hours via website + Google search + Ollama")
    p.add_argument("--database-url", default=None)
    p.add_argument("--apply-schema", action="store_true", help="Create venue_hours tables")
    p.add_argument("--name", default=None)
    p.add_argument("--place-id", default=None)
    p.add_argument("--borough", default=None)
    p.add_argument("--limit", type=int, default=1)
    p.add_argument("--allow-no-website", action="store_true")
    p.add_argument(
        "--stale-days",
        type=int,
        default=None,
        help="Only venues missing hours or fetched_at older than N days (or empty/error)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Ignore --stale-days freshness filter (still respects name/borough/limit)",
    )
    p.add_argument("--save", action="store_true", help="Write to venue_hours (+ history on change)")
    p.add_argument("--model", default=os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL))
    p.add_argument("--ollama-url", default=os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_URL))
    p.add_argument(
        "--force-search",
        action="store_true",
        help="Kept for compatibility; search already runs by default unless --no-search",
    )
    p.add_argument("--no-search", action="store_true", help="Website only")
    p.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Parallel venues (default 4). I/O bound; Ollama may still serialize on GPU",
    )
    p.add_argument("--dry-run-prompt", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    db_url = load_database_url(args.database_url)
    conn = connect(db_url)
    db_lock = threading.Lock()
    print_lock = threading.Lock()

    try:
        if args.apply_schema:
            apply_schema(conn)
            if not (
                args.name
                or args.place_id
                or args.borough
                or args.save
                or args.stale_days is not None
                or args.allow_no_website
                or args.dry_run_prompt
            ):
                return

        check_ollama(args.ollama_url, args.model)

        if args.stale_days is not None or args.save:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema='public' AND table_name='venue_hours'
                    """
                )
                if not cur.fetchone():
                    apply_schema(conn)

        places = fetch_places(
            conn,
            name=args.name,
            place_id=args.place_id,
            borough=args.borough,
            limit=max(1, args.limit),
            require_website=not args.allow_no_website,
            stale_days=args.stale_days,
            force=args.force,
        )
        if not places:
            raise SystemExit(
                "No matching places found "
                "(try --allow-no-website, --force, or drop --stale-days)."
            )

        workers = max(1, min(int(args.workers), len(places)))
        print(
            f"Fetching hours for {len(places)} venue(s) with model={args.model}"
            f", workers={workers}"
            + (f", stale-days={args.stale_days}" if args.stale_days is not None else "")
            + (", force" if args.force else "")
        )

        def process_one(idx: int, place: dict[str, Any]) -> None:
            nonlocal conn
            with print_lock:
                print(f"\n[{idx}/{len(places)}] {place.get('place_name')}")
            try:
                payload = fetch_one(
                    place,
                    model=args.model,
                    ollama_url=args.ollama_url,
                    force_search=args.force_search,
                    no_search=args.no_search,
                    dry_run_prompt=args.dry_run_prompt,
                )
            except Exception as exc:  # noqa: BLE001
                with print_lock:
                    print(f"  ! hours fetch failed, skipping: {exc}")
                if args.save:
                    with db_lock:
                        try:
                            upsert_hours(
                                conn,
                                place,
                                {
                                    "status": "error",
                                    "confidence": 0.0,
                                    "hours_json": {},
                                    "hours_text": None,
                                    "timezone": None,
                                    "notes": str(exc),
                                    "evidence": None,
                                },
                                source="none",
                                source_urls=[],
                                model=args.model,
                                evidence_hash=content_hash(str(exc)),
                            )
                        except Exception:  # noqa: BLE001
                            pass
                return

            if args.dry_run_prompt:
                return

            with print_lock:
                print_result(place, payload)

            if not args.save:
                return

            with db_lock:
                try:
                    kind = upsert_hours(
                        conn,
                        place,
                        payload["result"],
                        source=payload["source"],
                        source_urls=payload["source_urls"],
                        model=args.model,
                        evidence_hash=payload["evidence_hash"],
                    )
                    with print_lock:
                        print(f"  → saved ({kind})")
                except Exception as exc:  # noqa: BLE001
                    with print_lock:
                        print(f"  ! DB write failed ({exc}); reconnecting and retrying once…")
                    try:
                        conn = reconnect(db_url, conn)
                        kind = upsert_hours(
                            conn,
                            place,
                            payload["result"],
                            source=payload["source"],
                            source_urls=payload["source_urls"],
                            model=args.model,
                            evidence_hash=payload["evidence_hash"],
                        )
                        with print_lock:
                            print(f"  → saved after reconnect ({kind})")
                    except Exception as exc2:  # noqa: BLE001
                        with print_lock:
                            print(f"  ! DB retry failed: {exc2}")

        if workers == 1:
            for i, place in enumerate(places, start=1):
                process_one(i, place)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [
                    pool.submit(process_one, i, place)
                    for i, place in enumerate(places, start=1)
                ]
                for fut in as_completed(futs):
                    exc = fut.exception()
                    if exc:
                        with print_lock:
                            print(f"  ! worker crashed: {exc}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
