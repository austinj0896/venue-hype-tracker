"""Find TikTok /place/ POI URLs via in-app search (Playwright)."""

from __future__ import annotations

import re
from html import unescape
from typing import Any, Callable
from urllib.parse import quote_plus, unquote

BASE_URL = "https://www.tiktok.com"

PLACE_URL_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/place/([A-Za-z0-9\-]+)-(\d+)",
    re.IGNORECASE,
)
PLACE_PATH_RE = re.compile(
    r"/place/([A-Za-z0-9\-]+)-(\d+)",
    re.IGNORECASE,
)
CANONICAL_PLACE_RE = re.compile(
    r'"canonical"\s*:\s*"(https://(?:www\.)?tiktok\.com/place/[^"]+)"',
    re.IGNORECASE,
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

SEARCH_URLS = (
    "https://www.tiktok.com/search?q={query}",
    "https://www.tiktok.com/search/places?q={query}",
)


def normalize_tiktok_html(html: str) -> str:
    """Decode HTML entities and TikTok JSON unicode escapes (\\u002F -> /)."""
    text = unescape(html)
    return text.replace("\\u002F", "/").replace("\\u002f", "/")


def parse_place_url(url: str) -> dict[str, str] | None:
    clean = unquote(url.split("?")[0].split("#")[0].strip())
    match = PLACE_URL_RE.search(clean) or PLACE_PATH_RE.search(clean)
    if not match:
        return None
    slug, poi_id = match.group(1), match.group(2)
    canonical = f"{BASE_URL}/place/{slug}-{poi_id}"
    return {
        "tiktok_place_url": canonical,
        "place_slug": slug,
        "tiktok_poi_id": poi_id,
    }


def build_venue_search_query(
    *,
    place_name: str | None,
    borough: str | None = None,
    address: str | None = None,
) -> str:
    """Prefer name + city over full street address for TikTok search."""
    name = (place_name or "").strip()
    city = (borough or "").strip()
    if name and city:
        return f"{name} {city}"
    if name:
        return name
    if address:
        # Drop country suffix for shorter queries
        parts = address.split(",")
        if len(parts) >= 2:
            return ",".join(parts[:2]).strip()
        return address.strip()
    return ""


def extract_place_urls_from_html(html: str) -> list[dict[str, str]]:
    text = normalize_tiktok_html(html)
    found: dict[str, dict[str, str]] = {}

    for match in CANONICAL_PLACE_RE.finditer(text):
        parsed = parse_place_url(match.group(1))
        if parsed:
            found[parsed["tiktok_place_url"]] = parsed

    for match in PLACE_URL_RE.finditer(text):
        parsed = parse_place_url(match.group(0))
        if parsed:
            found[parsed["tiktok_place_url"]] = parsed

    for match in PLACE_PATH_RE.finditer(text):
        parsed = parse_place_url(match.group(0))
        if parsed:
            found[parsed["tiktok_place_url"]] = parsed

    return list(found.values())


def _collect_places_from_page(page: Any, *, query: str, html: str) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}

    try:
        hrefs = page.eval_on_selector_all("a[href]", "els => els.map(a => a.href)")
    except Exception:
        hrefs = []

    for href in hrefs:
        if "/place/" not in href:
            continue
        parsed = parse_place_url(href)
        if parsed:
            found[parsed["tiktok_place_url"]] = {
                **parsed,
                "discovery_query": query,
                "discovery_method": "tiktok_search_link",
                "confidence_score": 0.9,
            }

    for parsed in extract_place_urls_from_html(html):
        url = parsed["tiktok_place_url"]
        if url not in found:
            found[url] = {
                **parsed,
                "discovery_query": query,
                "discovery_method": "tiktok_search_html",
                "confidence_score": 0.75,
            }

    return found


def _scroll_search_page(page: Any, *, rounds: int = 4) -> None:
    for _ in range(rounds):
        page.mouse.wheel(0, 1800)
        page.wait_for_timeout(1200)


def _click_places_tab(page: Any) -> None:
    selectors = (
        'a[href*="/search/places"]',
        '[data-e2e="search-places-tab"]',
        'text=Places',
    )
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible():
                locator.click()
                page.wait_for_timeout(2500)
                return
        except Exception:
            continue


def find_tiktok_places_via_search(
    query: str,
    *,
    headless: bool = True,
    wait_ms: int = 8000,
    user_data_dir: str | None = None,
) -> list[dict[str, Any]]:
    """
    Open TikTok search and collect /place/ links from the rendered page.
    Returns de-duplicated place records with discovery_query attached.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright required. Run: pip install playwright "
            "&& python -m playwright install chromium"
        ) from exc

    search_url = SEARCH_URLS[0].format(query=quote_plus(query))
    found: dict[str, dict[str, Any]] = {}

    with sync_playwright() as playwright:
        launch_kwargs: dict[str, Any] = {
            "headless": headless,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if user_data_dir:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir,
                headless=headless,
                user_agent=USER_AGENT,
                locale="en-US",
                viewport={"width": 1280, "height": 900},
                args=launch_kwargs["args"],
            )
            page = context.new_page()
            browser = None
        else:
            browser = playwright.chromium.launch(**launch_kwargs)
            page = browser.new_page(
                user_agent=USER_AGENT,
                locale="en-US",
                viewport={"width": 1280, "height": 900},
            )

        for template in SEARCH_URLS:
            url = template.format(query=quote_plus(query))
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_selector('a[href*="/place/"]', timeout=wait_ms)
            except Exception:
                page.wait_for_timeout(wait_ms)

            _click_places_tab(page)
            _scroll_search_page(page)
            html = page.content()
            found.update(_collect_places_from_page(page, query=query, html=html))
            if found:
                break

        if browser:
            browser.close()
        else:
            context.close()

    return list(found.values())


def find_places_via_web_search(
    query: str,
    *,
    web_search_fn: Callable[[str, int], list[str]] | None = None,
    max_results: int = 8,
) -> list[dict[str, Any]]:
    """Fallback: site:tiktok.com/place via DuckDuckGo / Google CSE."""
    if web_search_fn is None:
        return []

    search_queries = [
        f'site:tiktok.com/place "{query}"',
        f"site:tiktok.com/place {query}",
    ]
    found: dict[str, dict[str, Any]] = {}
    for search_query in search_queries:
        for url in web_search_fn(search_query, max_results):
            parsed = parse_place_url(url)
            if parsed:
                found[parsed["tiktok_place_url"]] = {
                    **parsed,
                    "discovery_query": query,
                    "discovery_method": "web_search",
                    "confidence_score": 0.6,
                }
        if found:
            break
    return list(found.values())


def discover_tiktok_places(
    query: str,
    *,
    headless: bool = True,
    wait_ms: int = 8000,
    user_data_dir: str | None = None,
    web_search_fn: Callable[[str, int], list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Try TikTok search first, then web search fallback."""
    results = find_tiktok_places_via_search(
        query,
        headless=headless,
        wait_ms=wait_ms,
        user_data_dir=user_data_dir,
    )
    if results:
        return results
    return find_places_via_web_search(query, web_search_fn=web_search_fn)


def resolve_canonical_place_url(
    place_url: str,
    *,
    headless: bool = True,
    wait_ms: int = 6000,
) -> dict[str, str] | None:
    """Load a /place/ page and return canonical URL from embedded SEO JSON if present."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return parse_place_url(place_url)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = browser.new_page(user_agent=USER_AGENT, locale="en-US")
        page.goto(place_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(wait_ms)
        html = page.content()
        browser.close()

    places = extract_place_urls_from_html(html)
    if places:
        return places[0]
    return parse_place_url(place_url)
