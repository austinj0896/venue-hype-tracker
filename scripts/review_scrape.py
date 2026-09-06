"""Free web review enrichment (no Google Places API).

Finds Yelp / TripAdvisor / Google review pages via DuckDuckGo for a venue
name + location, then prefers real review bodies over search titles/snippets.
Preferred signal is still the venue website; this is a fallback / supplement.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urlparse

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
MAX_REVIEW_CHARS = 4500
MIN_WEBSITE_CHARS_FOR_SKIP = 500
MIN_SNIPPET_CHARS = 50
MIN_REVIEW_CHARS = 40

# Titles/snippets that are SEO chrome, not customer voice.
_TITLE_NOISE = re.compile(
    r"(?i)^("
    r"yelp|tripadvisor|google|maps|photos?|menu|about|website|official|"
    r"best \d+|top \d+|hours|directions|reservations?|"
    r".+\s[-–|]\s*(yelp|tripadvisor|google|opentable)"
    r").*$"
)
_SNIPPET_NOISE = re.compile(
    r"(?i)("
    r"see \d+ photos|\d+\s*photos?|"
    r"view menu|order online|make a reservation|"
    r"claim this business|write a review|people also searched|"
    r"opening hours|get directions|try our new menu|"
    r"\b(mon|tue|wed|thu|fri|sat|sun)\b.{0,20}\d{1,2}:\d{2}\s*(am|pm)|"
    r"\(\d{3}\)\s*\d{3}[-.\s]?\d{4}|\d{3}[-.\s]\d{3}[-.\s]\d{4}"
    r")"
)
_VIBE_HINTS = (
    "atmosphere",
    "vibe",
    "ambiance",
    "ambience",
    "romantic",
    "date",
    "intimate",
    "loud",
    "quiet",
    "crowded",
    "cozy",
    "trendy",
    "dive",
    "casual",
    "fancy",
    "swanky",
    "sports",
    "cocktail",
    "wine",
    "beer",
    "outdoor",
    "patio",
    "rooftop",
    "service",
    "music",
    "dance",
    "karaoke",
    "group",
    "busy",
    "chill",
    "rustic",
    "modern",
    "vintage",
    "kitschy",
    "funky",
)


def needs_review_fallback(website_scrape: dict[str, Any]) -> bool:
    status = website_scrape.get("status")
    text = website_scrape.get("text") or ""
    if status != "ok":
        return True
    return len(text) < MIN_WEBSITE_CHARS_FOR_SKIP


def _location_query(place: dict[str, Any]) -> str:
    parts = [
        place.get("borough") or "",
        place.get("short_formatted_address") or place.get("formatted_address") or "",
    ]
    loc = " ".join(p for p in parts if p).strip()
    return re.sub(r"\s+", " ", loc)


def _ddg_text(query: str, *, max_results: int = 8) -> list[dict[str, str]]:
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "ddgs is required for web reviews. "
                "pip install -r scripts/requirements-tagging.txt"
            ) from exc

    rows: list[dict[str, str]] = []
    with DDGS() as ddgs:
        for item in ddgs.text(query, max_results=max_results):
            href = (item.get("href") or item.get("link") or "").strip()
            title = (item.get("title") or "").strip()
            body = (item.get("body") or item.get("snippet") or "").strip()
            if not (title or body or href):
                continue
            rows.append({"title": title, "url": href, "snippet": body})
    return rows


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        return ""


def search_review_sources(place: dict[str, Any]) -> dict[str, Any]:
    name = (place.get("place_name") or "").strip()
    loc = _location_query(place)
    if not name:
        return {
            "queries": [],
            "results": [],
            "yelp_urls": [],
            "tripadvisor_urls": [],
            "maps_urls": [],
        }

    queries = [
        f'"{name}" {loc} site:yelp.com',
        f'"{name}" {loc} yelp reviews',
        f'"{name}" {loc} site:tripadvisor.com',
        f'"{name}" {loc} tripadvisor reviews',
        f'"{name}" {loc} google reviews',
    ]
    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for q in queries:
        try:
            batch = _ddg_text(q, max_results=6)
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "title": f"[search error] {q}",
                    "url": "",
                    "snippet": str(exc),
                }
            )
            continue
        for row in batch:
            key = row["url"] or f"{row['title']}|{row['snippet'][:80]}"
            if key in seen_urls:
                continue
            seen_urls.add(key)
            results.append(row)
        time.sleep(0.5)

    yelp_urls = [
        r["url"]
        for r in results
        if r.get("url") and "yelp.com" in _host(r["url"]) and "/biz/" in r["url"]
    ]
    # Fall back to any yelp URL if /biz/ filter was too strict.
    if not yelp_urls:
        yelp_urls = [
            r["url"]
            for r in results
            if r.get("url") and "yelp.com" in _host(r["url"])
        ]
    tripadvisor_urls = [
        r["url"]
        for r in results
        if r.get("url")
        and "tripadvisor." in _host(r["url"])
        and any(x in r["url"].lower() for x in ("restaurant", "attraction", "review"))
    ]
    maps_urls = [
        r["url"]
        for r in results
        if r.get("url")
        and any(
            h in _host(r["url"])
            for h in ("google.com", "maps.google.", "goo.gl")
        )
        and ("maps" in r["url"].lower() or "place" in r["url"].lower())
    ]
    return {
        "queries": queries,
        "results": results,
        "yelp_urls": yelp_urls,
        "tripadvisor_urls": tripadvisor_urls,
        "maps_urls": maps_urls,
    }


def _clean_html_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "nav", "footer", "header"]):
        # Keep application/ld+json — parsed separately.
        if tag.name == "script" and tag.get("type") == "application/ld+json":
            continue
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _extract_json_ld_reviews(html: str) -> list[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        review = node.get("review")
        if isinstance(review, list):
            for r in review:
                walk(r)
        elif isinstance(review, dict):
            walk(review)
        types = node.get("@type")
        type_list = types if isinstance(types, list) else [types]
        if any(t and "Review" in str(t) for t in type_list):
            body = node.get("reviewBody") or node.get("description")
            if body:
                out.append(str(body).strip())
        for val in node.values():
            if isinstance(val, (dict, list)):
                walk(val)

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        walk(data)
    return out


def _looks_like_review_line(line: str) -> bool:
    if not (MIN_REVIEW_CHARS <= len(line) <= 500):
        return False
    low = line.lower()
    if _SNIPPET_NOISE.search(line):
        return False
    if any(k in low for k in _VIBE_HINTS):
        return True
    # First-person / opinion cues common in reviews.
    return bool(
        re.search(
            r"(?i)\b(i |we |my |our |was |were |felt |seemed |loved |hated |"
            r"recommend|would go|came here|went here)\b",
            line,
        )
    )


def _fetch_page(url: str, timeout: float = 20.0) -> dict[str, Any]:
    import requests

    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc), "text": "", "reviews": []}

    if resp.status_code in (401, 403, 429) or resp.status_code >= 400:
        return {
            "ok": False,
            "error": f"HTTP {resp.status_code}",
            "text": "",
            "reviews": [],
        }

    html = resp.text
    reviews = _extract_json_ld_reviews(html)
    text = _clean_html_text(html)
    reviewish = [line for line in text.splitlines() if _looks_like_review_line(line)]
    return {
        "ok": True,
        "error": None,
        "text": text[:MAX_REVIEW_CHARS],
        "reviews": reviews[:25],
        "reviewish_lines": reviewish[:40],
        "final_url": resp.url,
    }


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _is_usable_snippet(snippet: str, *, place_name: str = "") -> bool:
    s = _normalize_text(snippet)
    if len(s) < MIN_SNIPPET_CHARS:
        return False
    if _TITLE_NOISE.match(s) or _SNIPPET_NOISE.search(s):
        return False
    # Drop snippets that are basically just the venue name + rating chrome.
    name = _normalize_text(place_name).lower()
    if name and s.lower().startswith(name) and len(s) < len(name) + 30:
        return False
    return True


def _quality_score(text: str) -> float:
    """Prefer longer, vibe-rich review bodies over thin SEO snippets."""
    t = _normalize_text(text)
    if not t:
        return -1.0
    score = min(len(t) / 200.0, 3.0)
    low = t.lower()
    score += sum(0.35 for h in _VIBE_HINTS if h in low)
    if re.search(r'(?i)\b(i |we |my |our )\b', t):
        score += 0.8
    if _TITLE_NOISE.match(t) or _SNIPPET_NOISE.search(t):
        score -= 2.0
    return score


def _dedupe_rank(texts: list[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    scored: list[tuple[float, str]] = []
    for raw in texts:
        t = _normalize_text(raw)
        key = t.lower()
        if len(t) < MIN_REVIEW_CHARS or key in seen:
            continue
        seen.add(key)
        scored.append((_quality_score(t), t))
    scored.sort(key=lambda x: (-x[0], -len(x[1])))
    return [t for _, t in scored[:limit]]


def _snippet_bodies_only(
    results: list[dict[str, str]], *, place_name: str
) -> list[str]:
    """Use DuckDuckGo body text only — never titles as evidence."""
    bodies: list[str] = []
    for row in results:
        snippet = _normalize_text(row.get("snippet") or "")
        if not _is_usable_snippet(snippet, place_name=place_name):
            continue
        bodies.append(snippet)
    ranked = _dedupe_rank(bodies, limit=12)
    # Drop pure SEO/contact chrome even if it passed length checks.
    return [t for t in ranked if _quality_score(t) >= 1.0][:10]


def fetch_web_reviews(place: dict[str, Any]) -> dict[str, Any]:
    """Search + optional page scrape for review signal. No paid APIs."""
    place_name = (place.get("place_name") or "").strip()
    search = search_review_sources(place)
    snippets = _snippet_bodies_only(search["results"], place_name=place_name)

    page_reviews: list[str] = []
    page_notes: list[str] = []
    sources_used: list[str] = []

    if snippets:
        sources_used.append("duckduckgo_snippets")

    def ingest_page(url: str, source_label: str) -> None:
        nonlocal page_reviews, page_notes, sources_used
        page = _fetch_page(url)
        if page.get("ok"):
            bodies = list(page.get("reviews") or []) + list(page.get("reviewish_lines") or [])
            if bodies:
                sources_used.append(source_label)
                page_reviews.extend(bodies)
            elif page.get("text"):
                # Keep a short, quality-filtered slice only — never raw homepage chrome.
                filtered = [
                    line
                    for line in str(page["text"]).splitlines()
                    if _looks_like_review_line(line)
                ]
                if filtered:
                    sources_used.append(source_label)
                    page_reviews.extend(filtered)
                else:
                    page_notes.append(f"{source_label} had little review text: {url}")
        else:
            page_notes.append(f"{source_label} blocked/error ({page.get('error')}): {url}")
        time.sleep(0.7)

    for url in search["yelp_urls"][:3]:
        ingest_page(url, "yelp_page")
    for url in search["tripadvisor_urls"][:2]:
        ingest_page(url, "tripadvisor_page")
    for url in search["maps_urls"][:1]:
        ingest_page(url, "google_maps_page")

    clean_reviews = _dedupe_rank(page_reviews, limit=18)
    clean_snippets = _dedupe_rank(snippets, limit=10)

    combined_parts: list[str] = []
    # Prefer real review bodies first so truncation keeps the best signal.
    if clean_reviews:
        combined_parts.append(
            "Customer review excerpts (prefer these as evidence):\n"
            + "\n".join(f"- {r}" for r in clean_reviews)
        )
    if clean_snippets:
        combined_parts.append(
            "Search result snippets (body text only; do not treat titles as evidence):\n"
            + "\n".join(f"- {s}" for s in clean_snippets)
        )
    if not combined_parts and page_notes:
        combined_parts.append("Fetch notes:\n" + "\n".join(page_notes)[:1200])

    text = "\n\n".join(combined_parts)[:MAX_REVIEW_CHARS]
    status = "ok" if text.strip() else "empty"
    return {
        "status": status,
        "text": text,
        "sources": sorted(set(sources_used)),
        "yelp_urls": search["yelp_urls"][:3],
        "tripadvisor_urls": search["tripadvisor_urls"][:2],
        "maps_urls": search["maps_urls"][:2],
        "result_count": len(search["results"]),
        "review_excerpt_count": len(clean_reviews),
        "snippet_count": len(clean_snippets),
        "error": None if text.strip() else "No review snippets found",
    }
