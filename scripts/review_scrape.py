"""Free web review enrichment (no Google Places API).

Finds Yelp / Google review pages via DuckDuckGo for a venue name + location,
then uses search snippets and (when allowed) page HTML. Preferred signal is
still the venue website; this is a fallback / supplement for vibe tagging.
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
MAX_REVIEW_CHARS = 4000
MIN_WEBSITE_CHARS_FOR_SKIP = 500


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
    # Prefer borough + city-ish short address without full street noise when possible.
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


def search_review_sources(place: dict[str, Any]) -> dict[str, Any]:
    name = (place.get("place_name") or "").strip()
    loc = _location_query(place)
    if not name:
        return {"queries": [], "results": [], "yelp_urls": [], "maps_urls": []}

    queries = [
        f'"{name}" {loc} site:yelp.com',
        f'"{name}" {loc} yelp reviews',
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
        time.sleep(0.6)

    yelp_urls = [
        r["url"]
        for r in results
        if r.get("url") and "yelp.com" in urlparse(r["url"]).netloc.lower()
    ]
    maps_urls = [
        r["url"]
        for r in results
        if r.get("url")
        and any(
            host in urlparse(r["url"]).netloc.lower()
            for host in ("google.com", "maps.google.", "goo.gl")
        )
        and ("maps" in r["url"].lower() or "place" in r["url"].lower())
    ]
    return {
        "queries": queries,
        "results": results,
        "yelp_urls": yelp_urls,
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
    # Keep review-ish lines when full page is noisy.
    reviewish = []
    for line in text.splitlines():
        low = line.lower()
        if any(
            key in low
            for key in (
                "review",
                "stars",
                "rated",
                "atmosphere",
                "vibe",
                "service",
                "food was",
                "drinks",
                "crowded",
                "romantic",
                "date",
                "loud",
                "quiet",
                "sports",
                "dive",
            )
        ):
            if 40 <= len(line) <= 400:
                reviewish.append(line)
    return {
        "ok": True,
        "error": None,
        "text": text[:MAX_REVIEW_CHARS],
        "reviews": reviews[:20],
        "reviewish_lines": reviewish[:30],
        "final_url": resp.url,
    }


def fetch_web_reviews(place: dict[str, Any]) -> dict[str, Any]:
    """Search + optional page scrape for review signal. No paid APIs."""
    search = search_review_sources(place)
    snippets: list[str] = []
    for row in search["results"]:
        bit = " — ".join(p for p in (row.get("title"), row.get("snippet")) if p)
        if bit:
            snippets.append(bit)

    page_reviews: list[str] = []
    page_notes: list[str] = []
    sources_used: list[str] = []

    if snippets:
        sources_used.append("duckduckgo_snippets")

    # Prefer Yelp pages; Maps HTML is often blocked for bots.
    for url in search["yelp_urls"][:2]:
        page = _fetch_page(url)
        if page.get("ok"):
            sources_used.append("yelp_page")
            page_reviews.extend(page.get("reviews") or [])
            page_reviews.extend(page.get("reviewish_lines") or [])
            if page.get("text") and not page_reviews:
                page_notes.append(page["text"][:1500])
        else:
            page_notes.append(f"yelp blocked/error ({page.get('error')}): {url}")
        time.sleep(0.8)

    for url in search["maps_urls"][:1]:
        page = _fetch_page(url)
        if page.get("ok") and (page.get("reviews") or page.get("reviewish_lines")):
            sources_used.append("google_maps_page")
            page_reviews.extend(page.get("reviews") or [])
            page_reviews.extend(page.get("reviewish_lines") or [])
        else:
            page_notes.append(
                f"maps page skipped/blocked ({(page or {}).get('error')}): {url}"
            )
        time.sleep(0.8)

    # Dedupe while preserving order.
    seen: set[str] = set()
    clean_reviews: list[str] = []
    for r in page_reviews:
        r = re.sub(r"\s+", " ", r).strip()
        if len(r) < 20 or r.lower() in seen:
            continue
        seen.add(r.lower())
        clean_reviews.append(r)

    combined_parts = []
    if snippets:
        combined_parts.append("Search snippets:\n" + "\n".join(f"- {s}" for s in snippets[:12]))
    if clean_reviews:
        combined_parts.append(
            "Review excerpts:\n" + "\n".join(f"- {r}" for r in clean_reviews[:15])
        )
    elif page_notes:
        # Last-resort page text if we couldn't isolate reviews.
        combined_parts.append("Page text (noisy):\n" + "\n".join(page_notes)[:2000])

    text = "\n\n".join(combined_parts)[:MAX_REVIEW_CHARS]
    status = "ok" if text.strip() else "empty"
    return {
        "status": status,
        "text": text,
        "sources": sorted(set(sources_used)),
        "yelp_urls": search["yelp_urls"][:3],
        "maps_urls": search["maps_urls"][:2],
        "result_count": len(search["results"]),
        "error": None if text.strip() else "No review snippets found",
    }
