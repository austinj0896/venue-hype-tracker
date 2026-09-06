#!/usr/bin/env python3
"""
Scrape TikTok Discover + video metadata for Après venue hype research.

Typical flow:
  1. Google/DuckDuckGo: site:tiktok.com/discover "<address>"
  2. Open discover hub (e.g. /discover/tara-rose-nyc)
  3. Collect /video/ links from that page
  4. Parse each video page for stats + caption

Examples:
  python scripts/tiktok_discover_scraper.py \\
    --address "384 3rd Ave, New York, NY 10016" \\
    --neon --limit-videos 15

  python scripts/tiktok_discover_scraper.py \\
    --discover-url "https://www.tiktok.com/discover/tara-rose-nyc" \\
    --place-name "Tara Rose" --output data/tiktok_sample.csv

  python scripts/tiktok_discover_scraper.py \\
    --from-neon --borough "Manhattan Beach" --limit-places 3 --neon
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from tiktok_place_discovery import (  # noqa: E402
    build_venue_search_query,
    discover_tiktok_places,
    find_tiktok_places_via_search,
    parse_place_url,
    resolve_canonical_place_url,
)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[misc, assignment]

BASE_URL = "https://www.tiktok.com"
DISCOVER_PATH_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/discover/([a-zA-Z0-9\-_]+)/?",
    re.IGNORECASE,
)
REL_VIDEO_HREF_RE = re.compile(
    r'href=(["\'])(?P<path>/@[^"\']+/video/\d+)\1',
    re.IGNORECASE,
)
VIDEO_ID_HANDLE_RE = re.compile(
    r'/@(?P<handle>[A-Za-z0-9._]+)/video/(?P<vid>\d+)',
    re.IGNORECASE,
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def load_env() -> None:
    if load_dotenv:
        load_dotenv(ROOT / ".env")


def get_html(url: str, *, session: requests.Session) -> str:
    response = session.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def duckduckgo_search(query: str, *, max_results: int = 8) -> list[str]:
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # type: ignore[no-redef]
        except ImportError as exc:
            raise RuntimeError(
                "Install ddgs: pip install ddgs"
            ) from exc

    urls: list[str] = []
    with DDGS() as ddgs:
        for row in ddgs.text(query, max_results=max_results):
            href = row.get("href") or row.get("link") or ""
            if href:
                urls.append(href)
    return urls


def google_cse_search(query: str, *, max_results: int = 5) -> list[str]:
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    cse_id = os.environ.get("GOOGLE_CSE_ID")
    if not api_key or not cse_id:
        return []

    resp = requests.get(
        "https://www.googleapis.com/customsearch/v1",
        params={
            "key": api_key,
            "cx": cse_id,
            "q": query,
            "num": min(max_results, 10),
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    return [item["link"] for item in payload.get("items", []) if item.get("link")]


def find_discover_url(
    address: str,
    *,
    place_name: str | None = None,
    session: requests.Session,
) -> tuple[str, str]:
    """Return (discover_url, search_query_used)."""
    queries = [
        f"site:tiktok.com/discover {address}",
    ]
    if place_name:
        queries.insert(0, f"site:tiktok.com/discover {place_name} {address}")

    candidate_urls: list[str] = []
    for query in queries:
        candidate_urls.extend(google_cse_search(query))
        if not candidate_urls:
            try:
                candidate_urls.extend(duckduckgo_search(query))
            except Exception as exc:
                print(f"  Search warning ({query}): {exc}")
        for url in candidate_urls:
            match = DISCOVER_PATH_RE.search(url)
            if match:
                slug = match.group(1)
                discover_url = f"{BASE_URL}/discover/{slug}"
                print(f"  Found discover hub: {discover_url} (query: {query})")
                return discover_url, query
        candidate_urls = []

    raise RuntimeError(
        f"No TikTok discover URL found for address={address!r}. "
        "Try --discover-url directly or set GOOGLE_CSE_ID for Google search."
    )


VIDEO_PATH_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@([^/]+)/video/(\d+)",
    re.IGNORECASE,
)


def video_url_from_parts(handle: str, video_id: str) -> str:
    return f"{BASE_URL}/@{handle.lstrip('@')}/video/{video_id}"


def _add_video_link(links: set[str], handle: str | None, video_id: str | None) -> None:
    if handle and video_id:
        links.add(video_url_from_parts(handle, str(video_id)))


def extract_from_sigi_state(html: str) -> set[str]:
    """TikTok discover pages often hydrate video cards via SIGI_STATE ItemModule."""
    links: set[str] = set()
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="SIGI_STATE")
    if not tag or not tag.string:
        return links

    try:
        data = json.loads(tag.string)
    except json.JSONDecodeError:
        return links

    item_module = data.get("ItemModule") or {}
    authors = data.get("AuthorModule") or {}
    if not isinstance(item_module, dict):
        return links
    if not isinstance(authors, dict):
        authors = {}

    for _key, item in item_module.items():
        if not isinstance(item, dict):
            continue
        video_id = item.get("id")
        author_id = item.get("author")
        handle = None
        if isinstance(author_id, str) and author_id in authors:
            author_row = authors.get(author_id) or {}
            if isinstance(author_row, dict):
                handle = author_row.get("uniqueId")
        if not handle:
            handle = item.get("authorUniqueId") or item.get("uniqueId")
        _add_video_link(links, handle, video_id)

    return links


def extract_video_links_from_html(html: str, *, debug: bool = False) -> list[str]:
    text = unescape(html)
    soup = BeautifulSoup(text, "html.parser")
    links: set[str] = set()
    counts: dict[str, int] = {}

    for a in soup.select('a[href*="/video/"]'):
        href = a.get("href")
        if not href:
            continue
        full_url = urljoin(BASE_URL, href.split("?")[0])
        match = VIDEO_ID_HANDLE_RE.search(full_url)
        if match:
            links.add(video_url_from_parts(match.group("handle"), match.group("vid")))
    counts["anchor_tags"] = len(links)

    for match in REL_VIDEO_HREF_RE.finditer(text):
        path = match.group("path").split("?")[0]
        vm = VIDEO_ID_HANDLE_RE.search(path)
        if vm:
            links.add(video_url_from_parts(vm.group("handle"), vm.group("vid")))
    counts["relative_href"] = len(links) - counts.get("anchor_tags", 0)

    for match in VIDEO_ID_HANDLE_RE.finditer(text):
        links.add(video_url_from_parts(match.group("handle"), match.group("vid")))
    counts["regex_scan"] = len(links)

    sigi_links = extract_from_sigi_state(text)
    before = len(links)
    links.update(sigi_links)
    counts["sigi_state"] = len(links) - before

    if debug:
        print(f"  Link extraction: {counts} (total unique={len(links)})")

    return sorted(links)


def fetch_with_playwright(url: str, *, wait_ms: int = 8000) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright not installed. Run: pip install playwright "
            "&& python -m playwright install chromium"
        ) from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(user_agent=HEADERS["User-Agent"], locale="en-US")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector('a[href*="/video/"]', timeout=wait_ms)
        except Exception:
            page.wait_for_timeout(wait_ms)
        html = page.content()
        browser.close()
    return html


def fetch_discover_html(
    discover_url: str,
    *,
    session: requests.Session,
    use_browser: bool,
    html_file: Path | None,
    save_html: Path | None,
) -> str:
    if html_file:
        print(f"Loading discover HTML from {html_file}")
        return html_file.read_text(encoding="utf-8")

    if use_browser:
        print("  Using Playwright browser fetch...")
        html = fetch_with_playwright(discover_url)
    else:
        session.get(BASE_URL, headers=HEADERS, timeout=30)
        html = get_html(discover_url, session=session)

    if save_html:
        save_html.parent.mkdir(parents=True, exist_ok=True)
        save_html.write_text(html, encoding="utf-8")
        print(f"  Saved discover HTML to {save_html}")

    return html


def _dig_item_struct(node: Any) -> dict | None:
    if isinstance(node, dict):
        if "itemStruct" in node and isinstance(node["itemStruct"], dict):
            if node["itemStruct"].get("id"):
                return node["itemStruct"]
        for value in node.values():
            found = _dig_item_struct(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _dig_item_struct(item)
            if found:
                return found
    return None


def find_item_struct(html: str) -> dict:
    text = unescape(html)
    soup = BeautifulSoup(text, "html.parser")

    script_ids = (
        "__UNIVERSAL_DATA_FOR_REHYDRATION__",
        "SIGI_STATE",
    )
    for script_id in script_ids:
        tag = soup.find("script", id=script_id)
        if tag and tag.string:
            try:
                data = json.loads(tag.string)
                item = _dig_item_struct(data)
                if item:
                    return item
                scoped = (
                    data.get("__DEFAULT_SCOPE__", {})
                    .get("webapp.video-detail", {})
                    .get("itemInfo", {})
                    .get("itemStruct", {})
                )
                if scoped:
                    return scoped
            except json.JSONDecodeError:
                pass

    for script in soup.find_all("script"):
        script_text = script.string or script.get_text()
        if not script_text or "webapp.video-detail" not in script_text:
            continue
        try:
            data = json.loads(script_text)
            item = (
                data.get("__DEFAULT_SCOPE__", {})
                .get("webapp.video-detail", {})
                .get("itemInfo", {})
                .get("itemStruct", {})
            )
            if item:
                return item
        except json.JSONDecodeError:
            pass

        match = re.search(
            r'"itemStruct"\s*:\s*(\{.*?\})\s*,\s*"shareMeta"',
            script_text,
            flags=re.DOTALL,
        )
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue

    return {}


def unix_to_iso(ts: Any) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def parse_video_page(
    video_url: str,
    *,
    session: requests.Session,
    context: dict[str, Any],
) -> dict[str, Any]:
    html = get_html(video_url, session=session)
    item = find_item_struct(html)

    row = {
        **context,
        "video_url": video_url.split("?")[0],
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    if not item:
        row["parse_status"] = "failed_no_item_struct"
        vid_match = VIDEO_PATH_RE.search(video_url)
        row["video_id"] = vid_match.group(2) if vid_match else None
        return row

    stats = item.get("stats") or {}
    author = item.get("author") or {}
    video = item.get("video") or {}

    row.update(
        {
            "parse_status": "ok",
            "video_id": str(item.get("id") or ""),
            "creator_handle": author.get("uniqueId"),
            "creator_nickname": author.get("nickname"),
            "caption": item.get("desc"),
            "create_time_unix": item.get("createTime"),
            "created_at_utc": unix_to_iso(item.get("createTime")),
            "duration_seconds": video.get("duration"),
            "like_count": stats.get("diggCount"),
            "share_count": stats.get("shareCount"),
            "comment_count": stats.get("commentCount"),
            "play_count": stats.get("playCount"),
            "collect_count": stats.get("collectCount"),
        }
    )
    return row


def discover_slug_from_url(discover_url: str) -> str | None:
    match = DISCOVER_PATH_RE.search(discover_url)
    return match.group(1) if match else None


def scrape_place_page(
    place_url: str,
    *,
    session: requests.Session,
    context: dict[str, Any],
    limit_videos: int | None,
    sleep_seconds: float,
    use_browser: bool = False,
    html_file: Path | None = None,
    save_html: Path | None = None,
    debug_links: bool = False,
    headed: bool = False,
) -> list[dict[str, Any]]:
    """Scrape videos from a TikTok /place/ POI page."""
    parsed = parse_place_url(place_url)
    print(f"Fetching place page: {place_url}")

    if html_file:
        place_html = html_file.read_text(encoding="utf-8")
    elif use_browser or headed:
        print("  Using Playwright browser fetch...")
        place_html = fetch_with_playwright(place_url, wait_ms=10000)
    else:
        session.get(BASE_URL, headers=HEADERS, timeout=30)
        place_html = get_html(place_url, session=session)

    if save_html:
        save_html.parent.mkdir(parents=True, exist_ok=True)
        save_html.write_text(place_html, encoding="utf-8")
        print(f"  Saved place HTML to {save_html}")

    video_links = extract_video_links_from_html(place_html, debug=debug_links)

    if not video_links and not use_browser and not html_file and not headed:
        print("  No links via HTTP — retrying with Playwright...")
        try:
            place_html = fetch_with_playwright(place_url, wait_ms=10000)
            video_links = extract_video_links_from_html(place_html, debug=debug_links)
        except Exception as exc:
            print(f"  Playwright retry failed: {exc}")

    if limit_videos:
        video_links = video_links[:limit_videos]

    print(f"Found {len(video_links)} video link(s) on place page")

    ctx = {
        **context,
        "discover_url": place_url,
        "discover_slug": parsed.get("place_slug") if parsed else None,
        "tiktok_place_url": parsed.get("tiktok_place_url") if parsed else place_url,
        "tiktok_poi_id": parsed.get("tiktok_poi_id") if parsed else None,
    }

    rows: list[dict[str, Any]] = []
    for idx, video_url in enumerate(video_links, start=1):
        print(f"  [{idx}/{len(video_links)}] {video_url}")
        try:
            row = parse_video_page(video_url, session=session, context=ctx)
        except Exception as exc:
            row = {
                **ctx,
                "video_url": video_url,
                "video_id": VIDEO_PATH_RE.search(video_url).group(2)
                if VIDEO_PATH_RE.search(video_url)
                else None,
                "parse_status": f"error: {exc}",
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        rows.append(row)
        if idx < len(video_links):
            time.sleep(sleep_seconds)

    return rows


def scrape_discover(
    discover_url: str,
    *,
    session: requests.Session,
    context: dict[str, Any],
    limit_videos: int | None,
    sleep_seconds: float,
    use_browser: bool = False,
    html_file: Path | None = None,
    save_html: Path | None = None,
    debug_links: bool = False,
) -> list[dict[str, Any]]:
    print(f"Fetching discover page: {discover_url}")
    discover_html = fetch_discover_html(
        discover_url,
        session=session,
        use_browser=use_browser,
        html_file=html_file,
        save_html=save_html,
    )
    video_links = extract_video_links_from_html(discover_html, debug=debug_links)

    if not video_links and not use_browser and not html_file:
        print("  No links via HTTP — retrying with Playwright (--browser)...")
        try:
            discover_html = fetch_discover_html(
                discover_url,
                session=session,
                use_browser=True,
                html_file=None,
                save_html=save_html,
            )
            video_links = extract_video_links_from_html(discover_html, debug=debug_links)
        except Exception as exc:
            print(f"  Playwright retry failed: {exc}")

    if limit_videos:
        video_links = video_links[:limit_videos]

    print(f"Found {len(video_links)} video link(s) on discover page")
    if not video_links:
        print(
            "  Warning: no /video/ links found. Try:\n"
            "    --browser          (Playwright; python -m playwright install chromium)\n"
            "    --save-html data/discover.html  then inspect / re-run with --html-file\n"
            "    Save page source from your browser and pass --html-file"
        )

    rows: list[dict[str, Any]] = []
    ctx = {
        **context,
        "discover_url": discover_url,
        "discover_slug": discover_slug_from_url(discover_url),
    }

    for idx, video_url in enumerate(video_links, start=1):
        print(f"  [{idx}/{len(video_links)}] {video_url}")
        try:
            row = parse_video_page(video_url, session=session, context=ctx)
        except Exception as exc:
            row = {
                **ctx,
                "video_url": video_url,
                "video_id": VIDEO_PATH_RE.search(video_url).group(2)
                if VIDEO_PATH_RE.search(video_url)
                else None,
                "parse_status": f"error: {exc}",
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        rows.append(row)
        if idx < len(video_links):
            time.sleep(sleep_seconds)

    return rows


def scrape_place(
    *,
    session: requests.Session,
    address: str,
    place_name: str | None = None,
    google_place_id: str | None = None,
    borough: str | None = None,
    discover_url: str | None = None,
    place_url: str | None = None,
    limit_videos: int | None,
    sleep_seconds: float,
    use_browser: bool = False,
    use_place_search: bool = True,
    html_file: Path | None = None,
    save_html: Path | None = None,
    debug_links: bool = False,
    headed: bool = False,
    user_data_dir: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """
    Resolve a venue to TikTok content and scrape videos.
    Returns (video_rows, tiktok_place_mapping_or_none).
    """
    search_query: str | None = None
    place_mapping: dict[str, Any] | None = None

    context: dict[str, Any] = {
        "google_place_id": google_place_id,
        "place_name": place_name,
        "search_address": address,
    }

    if place_url:
        parsed = parse_place_url(place_url)
        if parsed:
            place_mapping = {
                **parsed,
                "discovery_query": place_url,
                "discovery_method": "cli_place_url",
                "confidence_score": 1.0,
            }
        rows = scrape_place_page(
            place_url,
            session=session,
            context={**context, "search_query": place_url},
            limit_videos=limit_videos,
            sleep_seconds=sleep_seconds,
            use_browser=use_browser,
            html_file=html_file,
            save_html=save_html,
            debug_links=debug_links,
            headed=headed,
        )
        return rows, place_mapping

    if discover_url:
        rows = scrape_discover(
            discover_url,
            session=session,
            context={**context, "search_query": None},
            limit_videos=limit_videos,
            sleep_seconds=sleep_seconds,
            use_browser=use_browser,
            html_file=html_file,
            save_html=save_html,
            debug_links=debug_links,
        )
        return rows, None

    if use_place_search:
        search_query = build_venue_search_query(
            place_name=place_name,
            borough=borough,
            address=address,
        )
        print(f"  TikTok place search: {search_query!r}")
        candidates = discover_tiktok_places(
            search_query,
            headless=not headed,
            user_data_dir=user_data_dir,
            web_search_fn=lambda q, n: (
                google_cse_search(q, max_results=n) or duckduckgo_search(q, max_results=n)
            ),
        )
        if candidates:
            place_mapping = {
                **candidates[0],
                "google_place_id": google_place_id,
                "venue_name": place_name,
            }
            print(f"  Found place: {place_mapping['tiktok_place_url']}")
            rows = scrape_place_page(
                place_mapping["tiktok_place_url"],
                session=session,
                context={**context, "search_query": search_query},
                limit_videos=limit_videos,
                sleep_seconds=sleep_seconds,
                use_browser=use_browser,
                html_file=html_file,
                save_html=save_html,
                debug_links=debug_links,
                headed=headed,
            )
            return rows, place_mapping

        print("  No /place/ links from TikTok search — trying discover search...")

    discover_url, search_query = find_discover_url(
        address, place_name=place_name, session=session
    )
    rows = scrape_discover(
        discover_url,
        session=session,
        context={**context, "search_query": search_query},
        limit_videos=limit_videos,
        sleep_seconds=sleep_seconds,
        use_browser=use_browser,
        html_file=html_file,
        save_html=save_html,
        debug_links=debug_links,
    )
    return rows, None


def load_places_from_neon(
    *,
    database_url: str,
    borough: str | None,
    limit: int | None,
) -> list[dict[str, str]]:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    sql = """
        select google_place_id, place_name, borough,
               coalesce(formatted_address, short_formatted_address) as address
        from places
        where coalesce(formatted_address, short_formatted_address) is not null
    """
    params: list[Any] = []
    if borough:
        sql += " and borough = %s"
        params.append(borough)
    sql += " order by place_name"
    if limit:
        sql += " limit %s"
        params.append(limit)

    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def apply_tiktok_schema(database_url: str) -> None:
    import psycopg2

    schema_files = [
        ROOT / "neon" / "tiktok_schema.sql",
        ROOT / "neon" / "tiktok_places_schema.sql",
    ]
    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            for schema_path in schema_files:
                if schema_path.exists():
                    cur.execute(schema_path.read_text(encoding="utf-8"))
                    print(f"Applied {schema_path}")
        conn.commit()
    finally:
        conn.close()


def upsert_tiktok_place_neon(database_url: str, mapping: dict[str, Any]) -> None:
    import psycopg2

    sql = """
        insert into tiktok_places (
            google_place_id, venue_name, discovery_query,
            tiktok_place_url, tiktok_poi_id, place_slug,
            discovery_method, confidence_score, captured_at_utc
        ) values (
            %(google_place_id)s, %(venue_name)s, %(discovery_query)s,
            %(tiktok_place_url)s, %(tiktok_poi_id)s, %(place_slug)s,
            %(discovery_method)s, %(confidence_score)s, %(captured_at_utc)s
        )
        on conflict (tiktok_poi_id) do update set
            google_place_id = excluded.google_place_id,
            venue_name = excluded.venue_name,
            discovery_query = excluded.discovery_query,
            tiktok_place_url = excluded.tiktok_place_url,
            place_slug = excluded.place_slug,
            discovery_method = excluded.discovery_method,
            confidence_score = excluded.confidence_score,
            captured_at_utc = excluded.captured_at_utc
    """
    payload = {
        "google_place_id": mapping.get("google_place_id"),
        "venue_name": mapping.get("venue_name"),
        "discovery_query": mapping.get("discovery_query") or "",
        "tiktok_place_url": mapping["tiktok_place_url"],
        "tiktok_poi_id": mapping["tiktok_poi_id"],
        "place_slug": mapping.get("place_slug"),
        "discovery_method": mapping.get("discovery_method"),
        "confidence_score": mapping.get("confidence_score"),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, payload)
        conn.commit()
    finally:
        conn.close()


def upsert_rows_neon(database_url: str, rows: list[dict[str, Any]]) -> int:
    import psycopg2

    if not rows:
        return 0

    sql = """
        insert into tiktok_videos (
            google_place_id, place_name, search_address, discover_url, discover_slug,
            tiktok_place_url, tiktok_poi_id,
            video_id, video_url, creator_handle, creator_nickname, caption,
            create_time_unix, created_at_utc, duration_seconds,
            like_count, share_count, comment_count, play_count, collect_count,
            parse_status, captured_at_utc
        ) values (
            %(google_place_id)s, %(place_name)s, %(search_address)s,
            %(discover_url)s, %(discover_slug)s,
            %(tiktok_place_url)s, %(tiktok_poi_id)s,
            %(video_id)s, %(video_url)s, %(creator_handle)s, %(creator_nickname)s,
            %(caption)s, %(create_time_unix)s, %(created_at_utc)s, %(duration_seconds)s,
            %(like_count)s, %(share_count)s, %(comment_count)s, %(play_count)s,
            %(collect_count)s, %(parse_status)s, %(captured_at_utc)s
        )
        on conflict (video_id) do update set
            google_place_id = excluded.google_place_id,
            place_name = excluded.place_name,
            search_address = excluded.search_address,
            discover_url = excluded.discover_url,
            discover_slug = excluded.discover_slug,
            tiktok_place_url = excluded.tiktok_place_url,
            tiktok_poi_id = excluded.tiktok_poi_id,
            video_url = excluded.video_url,
            creator_handle = excluded.creator_handle,
            creator_nickname = excluded.creator_nickname,
            caption = excluded.caption,
            create_time_unix = excluded.create_time_unix,
            created_at_utc = excluded.created_at_utc,
            duration_seconds = excluded.duration_seconds,
            like_count = excluded.like_count,
            share_count = excluded.share_count,
            comment_count = excluded.comment_count,
            play_count = excluded.play_count,
            collect_count = excluded.collect_count,
            parse_status = excluded.parse_status,
            captured_at_utc = excluded.captured_at_utc
    """

    written = 0
    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            for row in rows:
                video_id = row.get("video_id")
                if not video_id:
                    print(f"  Skip row without video_id: {row.get('video_url')}")
                    continue
                payload = {
                    "google_place_id": row.get("google_place_id"),
                    "place_name": row.get("place_name"),
                    "search_address": row.get("search_address"),
                    "discover_url": row.get("discover_url"),
                    "discover_slug": row.get("discover_slug"),
                    "tiktok_place_url": row.get("tiktok_place_url"),
                    "tiktok_poi_id": row.get("tiktok_poi_id"),
                    "video_id": str(video_id),
                    "video_url": row.get("video_url"),
                    "creator_handle": row.get("creator_handle"),
                    "creator_nickname": row.get("creator_nickname"),
                    "caption": row.get("caption"),
                    "create_time_unix": row.get("create_time_unix"),
                    "created_at_utc": row.get("created_at_utc"),
                    "duration_seconds": row.get("duration_seconds"),
                    "like_count": row.get("like_count"),
                    "share_count": row.get("share_count"),
                    "comment_count": row.get("comment_count"),
                    "play_count": row.get("play_count"),
                    "collect_count": row.get("collect_count"),
                    "parse_status": row.get("parse_status") or "ok",
                    "captured_at_utc": row.get("captured_at_utc")
                    or datetime.now(timezone.utc).isoformat(),
                }
                cur.execute(sql, payload)
                written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def write_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    if not rows:
        print("No rows to write.")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(fieldnames=fieldnames, f=handle)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {output_path}")


def database_url_from_env(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    return os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")


def main() -> None:
    load_env()

    parser = argparse.ArgumentParser(
        description="Scrape TikTok discover + video metadata for venue hype.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--address", help="Street address for Google discover search")
    parser.add_argument("--place-name", help="Venue name (optional, improves search)")
    parser.add_argument("--google-place-id", help="Link row to Après places.google_place_id")
    parser.add_argument(
        "--discover-url",
        help="Skip search and use this TikTok discover hub URL directly",
    )
    parser.add_argument(
        "--place-url",
        help="Skip search and use this TikTok /place/ URL directly",
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Skip TikTok /place/ search; use Google/DuckDuckGo discover search only",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show browser window for TikTok search / place fetch",
    )
    parser.add_argument(
        "--user-data-dir",
        help="Persistent Chromium profile dir (reuse TikTok login cookies)",
    )
    parser.add_argument(
        "--from-neon",
        action="store_true",
        help="Loop places from Neon Postgres (requires DATABASE_URL)",
    )
    parser.add_argument("--borough", help="Filter Neon places by borough")
    parser.add_argument("--limit-places", type=int, help="Max places when using --from-neon")
    parser.add_argument("--limit-videos", type=int, default=10, help="Max videos per discover page")
    parser.add_argument("--sleep", type=float, default=1.5, help="Delay between video page fetches")
    parser.add_argument("--output", type=Path, default=Path("data/tiktok_videos.csv"))
    parser.add_argument("--neon", action="store_true", help="Upsert results into Neon tiktok_videos")
    parser.add_argument("--database-url", help="Neon URL (or set DATABASE_URL in .env)")
    parser.add_argument("--apply-schema", action="store_true", help="Run neon/tiktok_schema.sql first")
    parser.add_argument("--no-csv", action="store_true", help="Skip CSV export")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Fetch discover page with Playwright (needed when TikTok omits links from HTTP)",
    )
    parser.add_argument(
        "--html-file",
        type=Path,
        help="Use saved discover page HTML instead of fetching (debug / browser save-as)",
    )
    parser.add_argument(
        "--save-html",
        type=Path,
        help="Write discover page HTML to this path for inspection",
    )
    parser.add_argument(
        "--debug-links",
        action="store_true",
        help="Print link extraction counts by method",
    )
    args = parser.parse_args()

    if not args.from_neon and not args.discover_url and not args.place_url and not args.address:
        parser.error("Provide --address, --discover-url, --place-url, or --from-neon")

    db_url = database_url_from_env(args.database_url)
    if args.neon and not db_url:
        parser.error("--neon requires DATABASE_URL or --database-url")

    if args.apply_schema and db_url:
        apply_tiktok_schema(db_url)

    session = requests.Session()
    all_rows: list[dict[str, Any]] = []
    place_mappings: list[dict[str, Any]] = []

    if args.from_neon:
        if not db_url:
            parser.error("--from-neon requires DATABASE_URL")
        places = load_places_from_neon(
            database_url=db_url,
            borough=args.borough,
            limit=args.limit_places,
        )
        print(f"Loaded {len(places)} place(s) from Neon")
        for i, place in enumerate(places, start=1):
            name = place.get("place_name") or ""
            address = place.get("address") or ""
            borough = place.get("borough")
            pid = place.get("google_place_id")
            print(f"\n[{i}/{len(places)}] {name} — {address}")
            try:
                rows, mapping = scrape_place(
                    session=session,
                    address=address,
                    place_name=name,
                    google_place_id=pid,
                    borough=borough,
                    discover_url=None,
                    place_url=None,
                    limit_videos=args.limit_videos,
                    sleep_seconds=args.sleep,
                    use_browser=args.browser,
                    use_place_search=not args.discover_only,
                    html_file=args.html_file,
                    save_html=args.save_html,
                    debug_links=args.debug_links,
                    headed=args.headed,
                    user_data_dir=args.user_data_dir,
                )
                all_rows.extend(rows)
                if mapping:
                    place_mappings.append(mapping)
                    if args.neon and db_url:
                        upsert_tiktok_place_neon(db_url, mapping)
            except Exception as exc:
                print(f"  Failed: {exc}")
            time.sleep(args.sleep)
    else:
        rows, mapping = scrape_place(
            session=session,
            address=args.address or "",
            place_name=args.place_name,
            google_place_id=args.google_place_id,
            borough=args.borough,
            discover_url=args.discover_url,
            place_url=args.place_url,
            limit_videos=args.limit_videos,
            sleep_seconds=args.sleep,
            use_browser=args.browser,
            use_place_search=not args.discover_only,
            html_file=args.html_file,
            save_html=args.save_html,
            debug_links=args.debug_links,
            headed=args.headed,
            user_data_dir=args.user_data_dir,
        )
        all_rows.extend(rows)
        if mapping:
            place_mappings.append(mapping)
            if args.neon and db_url:
                upsert_tiktok_place_neon(db_url, mapping)

    if not args.no_csv:
        write_csv(all_rows, args.output)

    if args.neon and db_url:
        count = upsert_rows_neon(db_url, all_rows)
        print(f"Upserted {count} row(s) into tiktok_videos")

    ok = sum(1 for r in all_rows if r.get("parse_status") == "ok")
    print(f"Done. {ok}/{len(all_rows)} videos parsed successfully.")
    if place_mappings:
        print(f"Resolved {len(place_mappings)} TikTok place mapping(s).")


if __name__ == "__main__":
    main()
