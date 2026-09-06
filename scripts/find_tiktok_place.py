#!/usr/bin/env python3
"""Test TikTok /place/ discovery for a single venue search query."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))

from tiktok_place_discovery import (  # noqa: E402
    build_venue_search_query,
    discover_tiktok_places,
    find_places_via_web_search,
    resolve_canonical_place_url,
)


def web_search_fn(query: str, max_results: int) -> list[str]:
    from tiktok_discover_scraper import duckduckgo_search, google_cse_search

    return google_cse_search(query, max_results=max_results) or duckduckgo_search(
        query, max_results=max_results
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find TikTok /place/ URLs via TikTok search (Playwright)."
    )
    parser.add_argument("--query", help='Search text, e.g. "Tara Rose NYC"')
    parser.add_argument("--place-name", help="Venue name (with --borough builds query)")
    parser.add_argument("--borough", help="City/neighborhood for search query")
    parser.add_argument("--address", help="Fallback if no place name")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show browser window (useful for debugging)",
    )
    parser.add_argument(
        "--web-only",
        action="store_true",
        help="Skip TikTok search; only try site:tiktok.com/place web search",
    )
    parser.add_argument(
        "--user-data-dir",
        help="Persistent Chromium profile (reuse TikTok login cookies)",
    )
    parser.add_argument(
        "--resolve",
        action="store_true",
        help="Open first place URL and confirm canonical from page source",
    )
    args = parser.parse_args()

    query = args.query or build_venue_search_query(
        place_name=args.place_name,
        borough=args.borough,
        address=args.address,
    )
    if not query:
        parser.error("Provide --query or --place-name (+ optional --borough)")

    print(f"Searching for: {query!r}")

    if args.web_only:
        results = find_places_via_web_search(query, web_search_fn=web_search_fn)
    else:
        results = discover_tiktok_places(
            query,
            headless=not args.headed,
            user_data_dir=args.user_data_dir,
            web_search_fn=web_search_fn,
        )

    if not results:
        print("No /place/ links found.")
        print("Tips:")
        print("  --headed              visible browser (TikTok may require login for Places tab)")
        print("  --user-data-dir PATH  reuse a logged-in Chromium profile")
        print("  --web-only            try DuckDuckGo site:tiktok.com/place search")
        return

    print(f"Found {len(results)} place candidate(s):\n")
    for i, row in enumerate(results, start=1):
        print(f"[{i}] {row['tiktok_place_url']}")
        print(f"    slug={row['place_slug']} poi_id={row['tiktok_poi_id']}")
        print(
            f"    method={row.get('discovery_method')} "
            f"confidence={row.get('confidence_score')}"
        )

    if args.resolve and results:
        first = results[0]["tiktok_place_url"]
        print(f"\nResolving canonical for: {first}")
        canonical = resolve_canonical_place_url(first, headless=not args.headed)
        print(json.dumps(canonical, indent=2))


if __name__ == "__main__":
    main()
