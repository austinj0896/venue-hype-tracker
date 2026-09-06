#!/usr/bin/env python3
"""Tag venues with local Ollama: website first, then web reviews for low confidence.

Pass 1 — classify from Google place fields + multi-page website scrape
          (homepage + About/Menu/Story when linked).
Pass 2 — only when needed: DuckDuckGo/Yelp/TripAdvisor review bodies
          (no Places API) to confirm low-confidence tags and fill gaps.

Examples:
  python scripts/tag_venue_vibes.py
  python scripts/tag_venue_vibes.py --name "North End"
  python scripts/tag_venue_vibes.py --limit 3 --save
  python scripts/tag_venue_vibes.py --apply-schema
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[misc, assignment]

from review_scrape import fetch_web_reviews, needs_review_fallback
from vibe_taxonomy import allowed_tags_for_type, taxonomy_prompt_block, taxonomy_rows

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:7b"
# Website tags at/above this are kept without a review pass.
HIGH_CONFIDENCE = 0.75
# Final tags below this are dropped after merge.
MIN_ACCEPT = 0.65
MAX_WEBSITE_CHARS = 4500
MAX_SECONDARY_PAGES = 3
MAX_SECONDARY_CHARS = 1800
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
# Prefer these paths for vibe/menu signal beyond the homepage.
_SECONDARY_LINK_RE = re.compile(
    r"(?i)\b("
    r"about|our[-_\s]?story|story|menu|food|drink|cocktail|wine|beer|"
    r"private|experience|vibe|philosophy|chef|concept|reservations?"
    r")\b"
)
_SKIP_LINK_RE = re.compile(
    r"(?i)(careers?|jobs?|privacy|terms|login|cart|checkout|instagram|"
    r"facebook|twitter|tiktok|mailto:|tel:|javascript:|#$)"
)


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
    schema_path = ROOT / "neon" / "venue_tags_schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    print(f"Applied schema from {schema_path}")


def sync_taxonomy(conn) -> int:
    """Upsert the canonical tag list into vibe_taxonomy; deactivate removed tags."""
    rows = taxonomy_rows()
    active_tags = [str(row["tag"]) for row in rows]
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO vibe_taxonomy (tag, category, sort_order, is_active, updated_at)
                VALUES (%s, %s, %s, TRUE, NOW())
                ON CONFLICT (tag) DO UPDATE SET
                    category = EXCLUDED.category,
                    sort_order = EXCLUDED.sort_order,
                    is_active = TRUE,
                    updated_at = NOW()
                """,
                (row["tag"], row["category"], row["sort_order"]),
            )
        if active_tags:
            cur.execute(
                """
                UPDATE vibe_taxonomy
                SET is_active = FALSE, updated_at = NOW()
                WHERE tag <> ALL(%s)
                """,
                (active_tags,),
            )
    conn.commit()
    print(f"Synced {len(rows)} active tag(s) into vibe_taxonomy")
    return len(rows)


def fetch_places(
    conn,
    *,
    name: str | None,
    place_id: str | None,
    borough: str | None,
    limit: int,
    require_website: bool,
    skip_tagged: bool,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if place_id:
        clauses.append("google_place_id = %s")
        params.append(place_id)
    if name:
        clauses.append("place_name ILIKE %s")
        params.append(f"%{name}%")
    if borough:
        clauses.append("borough ILIKE %s")
        params.append(borough)
    if require_website:
        clauses.append("website_uri IS NOT NULL AND trim(website_uri) <> ''")
    if skip_tagged:
        clauses.append(
            """
            NOT EXISTS (
                SELECT 1 FROM venue_tags t
                WHERE t.google_place_id = places.google_place_id
            )
            """
        )

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT google_place_id, place_name, primary_type, venue_category,
               price_level, website_uri, borough, formatted_address,
               short_formatted_address
        FROM places
        {where}
        ORDER BY place_name
        LIMIT %s
    """
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def clean_html_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def _same_site(base_url: str, candidate: str) -> bool:
    from urllib.parse import urlparse

    try:
        b = urlparse(base_url)
        c = urlparse(candidate)
    except Exception:  # noqa: BLE001
        return False
    if not c.scheme.startswith("http"):
        return False
    return (c.netloc or "").lower() == (b.netloc or "").lower()


def _score_secondary_link(href: str, anchor: str) -> float:
    blob = f"{href} {anchor}".lower()
    if _SKIP_LINK_RE.search(blob):
        return -1.0
    if not _SECONDARY_LINK_RE.search(blob):
        return -1.0
    score = 1.0
    for token, weight in (
        ("about", 3.0),
        ("story", 3.0),
        ("menu", 2.5),
        ("cocktail", 2.0),
        ("wine", 2.0),
        ("beer", 1.5),
        ("private", 1.5),
        ("experience", 1.5),
        ("chef", 1.2),
        ("concept", 1.2),
    ):
        if token in blob:
            score += weight
    return score


def discover_secondary_urls(html: str, base_url: str) -> list[str]:
    """Find About / Menu / Story pages on the same site."""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin, urldefrag

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
        score = _score_secondary_link(absolute, anchor)
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
        return {"ok": False, "error": str(exc), "html": "", "final_url": url, "status_code": None}

    if resp.status_code in (401, 403, 429):
        return {
            "ok": False,
            "error": f"HTTP {resp.status_code}",
            "html": "",
            "final_url": resp.url,
            "status_code": resp.status_code,
            "blocked": True,
        }
    if resp.status_code >= 400:
        return {
            "ok": False,
            "error": f"HTTP {resp.status_code}",
            "html": "",
            "final_url": resp.url,
            "status_code": resp.status_code,
        }

    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "html" not in ctype and "text" not in ctype and ctype:
        return {
            "ok": False,
            "error": f"Unsupported content-type: {ctype}",
            "html": "",
            "final_url": resp.url,
            "status_code": resp.status_code,
        }
    return {
        "ok": True,
        "error": None,
        "html": resp.text,
        "final_url": resp.url,
        "status_code": resp.status_code,
    }


def _prefer_vibe_excerpt(text: str, limit: int) -> str:
    """Keep vibe-relevant lines when truncating long pages."""
    if len(text) <= limit:
        return text
    lines = text.splitlines()
    keywords = (
        "atmosphere",
        "vibe",
        "ambiance",
        "about",
        "story",
        "menu",
        "cocktail",
        "wine",
        "beer",
        "date",
        "romantic",
        "outdoor",
        "patio",
        "rooftop",
        "private",
        "experience",
        "farm",
        "chef",
        "music",
        "sports",
        "dive",
        "casual",
        "intimate",
    )
    scored: list[tuple[float, int, str]] = []
    for idx, line in enumerate(lines):
        low = line.lower()
        hits = sum(1 for k in keywords if k in low)
        if not hits:
            continue
        score = float(hits) * 2.0 + min(len(line) / 400.0, 1.0)
        scored.append((score, idx, line))
    if not scored:
        return text[:limit]

    scored.sort(key=lambda x: (-x[0], x[1]))
    chosen_idx: set[int] = set()
    size = 0
    for _, idx, line in scored:
        if size + len(line) + 1 > limit:
            continue
        chosen_idx.add(idx)
        size += len(line) + 1
        if size >= limit:
            break
    ordered = [lines[i] for i in sorted(chosen_idx)]
    out = "\n".join(ordered)
    # Pad with page lead-in when vibe lines are sparse (after the signal).
    if len(out) < max(limit // 3, 200):
        remaining = limit - len(out) - 10
        head = text[: max(remaining, 0)]
        out = f"{out}\n...\n{head}" if head else out
    return out[:limit]


def scrape_website(url: str, timeout: float = 20.0) -> dict[str, Any]:
    if not url or not url.strip():
        return {
            "status": "no_website",
            "text": "",
            "error": None,
            "final_url": None,
            "content_hash": None,
            "pages_fetched": [],
        }

    home = _fetch_html(url, timeout=timeout)
    if not home.get("ok"):
        status = "blocked" if home.get("blocked") else "error"
        return {
            "status": status,
            "text": "",
            "error": home.get("error"),
            "final_url": home.get("final_url") or url,
            "content_hash": None,
            "pages_fetched": [],
        }

    final_url = home["final_url"] or url
    home_text = clean_html_text(home["html"])
    if len(home_text) < 40:
        return {
            "status": "empty",
            "text": home_text,
            "error": "Extracted text too short",
            "final_url": final_url,
            "content_hash": hashlib.sha256(home_text.encode("utf-8")).hexdigest()
            if home_text
            else None,
            "pages_fetched": [final_url],
        }

    parts = [f"[Homepage]\n{_prefer_vibe_excerpt(home_text, MAX_WEBSITE_CHARS)}"]
    pages_fetched = [final_url]
    secondary_urls = discover_secondary_urls(home["html"], final_url)
    for sec_url in secondary_urls:
        page = _fetch_html(sec_url, timeout=timeout)
        if not page.get("ok"):
            continue
        page_text = clean_html_text(page["html"])
        if len(page_text) < 60:
            continue
        label = sec_url.rstrip("/").rsplit("/", 1)[-1] or "page"
        excerpt = _prefer_vibe_excerpt(page_text, MAX_SECONDARY_CHARS)
        parts.append(f"[{label}]\n{excerpt}")
        pages_fetched.append(page.get("final_url") or sec_url)
        time.sleep(0.4)

    combined = "\n\n".join(parts)
    truncated = combined[: MAX_WEBSITE_CHARS + MAX_SECONDARY_CHARS * MAX_SECONDARY_PAGES]
    return {
        "status": "ok",
        "text": truncated,
        "error": None,
        "final_url": final_url,
        "content_hash": hashlib.sha256(truncated.encode("utf-8")).hexdigest(),
        "pages_fetched": pages_fetched,
    }


def build_google_facts(place: dict[str, Any]) -> dict[str, Any]:
    """Structured place fields the LLM can treat as soft, non-review signals."""
    primary = (place.get("primary_type") or "").strip()
    category = (place.get("venue_category") or "").strip()
    price = place.get("price_level")
    inferred: list[str] = []
    low_type = primary.lower()
    if low_type in {"sports_bar"} or "sport" in low_type:
        inferred.append("Google type suggests sports-oriented bar")
    if low_type in {"wine_bar"} or "wine" in low_type:
        inferred.append("Google type suggests wine-focused venue")
    if low_type in {"cocktail_bar"} or "cocktail" in low_type:
        inferred.append("Google type suggests cocktail-focused bar")
    if low_type in {"night_club", "nightclub"} or "club" in low_type:
        inferred.append("Google type suggests nightlife / dancing potential")
    if low_type in {"cafe", "coffee_shop", "bakery"}:
        inferred.append("Google type suggests cafe/bakery (often quieter / daytime)")
    if category:
        inferred.append(f"Venue category: {category}")
    if price:
        inferred.append(f"Price level: {price}")

    return {
        "primary_type": primary or None,
        "venue_category": category or None,
        "price_level": price,
        "borough": place.get("borough"),
        "address": place.get("short_formatted_address") or place.get("formatted_address"),
        "inferred_signals": inferred,
    }


def build_base_context(place: dict[str, Any], scrape: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": place.get("place_name"),
        "website_uri": place.get("website_uri"),
        "scrape_status": scrape.get("status"),
        "pages_fetched": scrape.get("pages_fetched") or [],
        "google_facts": build_google_facts(place),
        "website_excerpt": scrape.get("text") or "",
    }


def build_website_prompt(context: dict[str, Any], allowed: list[str]) -> str:
    return f"""You classify restaurants, bars, and cafes into vibe tags for a date-planning app called Après.

This is PASS 1 — use ONLY the venue metadata and website excerpt below.
Do NOT invent details that are not supported by that text.

Rules:
- Use ONLY tags from the Allowed tags list. Do not invent new tags.
- Multi-select is allowed. Prefer precision over recall.
- Put a honest confidence 0.0–1.0 on every tag you include.
- If evidence is weak, still include the tag with LOW confidence (e.g. 0.4–0.7) rather than omitting it — we will confirm weak tags later with reviews.
- Never invent Michelin / BYOB / Cigs inside / Cash only / Dress code without clear evidence.
- Treat google_facts.inferred_signals as soft hints only; still require website language for high confidence.
- Evidence must quote or paraphrase website/menu/about text — never use the venue name alone.
- Also list tags you considered but could not support in "unsure".
- Return valid JSON only:
{{
  "tags": [{{"tag": "...", "confidence": 0.0}}],
  "evidence": {{"Tag Name": "short quote or reason"}},
  "unsure": ["optional tag names"]
}}

Allowed tags:
{taxonomy_prompt_block(allowed)}

Venue data:
{json.dumps(context, indent=2)}
"""


def build_review_prompt(
    context: dict[str, Any],
    allowed: list[str],
    *,
    locked_tags: list[dict[str, Any]],
    candidate_tags: list[str],
    reviews_text: str,
) -> str:
    locked_names = [t["tag"] for t in locked_tags]
    return f"""You refine vibe tags for Après using customer review text from the web (Yelp/TripAdvisor/Google).

This is PASS 2 — website-only tagging already finished.
LOCKED tags (already high-confidence from the website; do not remove them):
{json.dumps(locked_names)}

CANDIDATE tags to confirm, raise, lower, or drop using reviews:
{json.dumps(candidate_tags)}

You may also ADD new tags from the Allowed list when reviews clearly support them.

Rules:
- Use ONLY Allowed tags.
- Prefer quotes from "Customer review excerpts" over search snippets.
- NEVER use page titles, star ratings alone, or the venue name as evidence.
- If reviews do not clearly support a candidate, OMIT it — accuracy over coverage.
- Do not keep a weak website guess just because it was a candidate.
- Do not contradict locked tags unless reviews overwhelmingly disagree — if so, put them in "contradicted".
- google_facts are context only; reviews must still support subjective vibes.
- Return valid JSON only:
{{
  "tags": [{{"tag": "...", "confidence": 0.0}}],
  "evidence": {{"Tag Name": "short review quote or reason"}},
  "contradicted": ["locked tags reviews strongly disagree with"],
  "unsure": ["still unclear"]
}}

Allowed tags:
{taxonomy_prompt_block(allowed)}

Venue metadata + website (context only):
{json.dumps({k: v for k, v in context.items() if k != "website_excerpt"}, indent=2)}

Web review text:
{reviews_text}
"""


def call_ollama(
    prompt: str,
    *,
    model: str,
    base_url: str,
    timeout: float = 180.0,
) -> dict[str, Any]:
    import requests

    url = urljoin(base_url.rstrip("/") + "/", "api/chat")
    resp = requests.post(
        url,
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a careful venue classifier. Output JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.2},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    content = payload.get("message", {}).get("content", "")
    if isinstance(content, dict):
        return content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise RuntimeError(f"Ollama returned non-JSON content: {content[:500]}")


def normalize_tags(
    raw: dict[str, Any],
    allowed: list[str],
    *,
    min_confidence: float = 0.0,
    pass_name: str | None = None,
) -> list[dict[str, Any]]:
    allowed_set = set(allowed)
    allowed_lower = {t.lower(): t for t in allowed}
    evidence = raw.get("evidence") or {}
    if not isinstance(evidence, dict):
        evidence = {}

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw.get("tags") or []:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("tag") or "").strip()
        if not tag:
            continue
        if tag not in allowed_set:
            tag = allowed_lower.get(tag.lower(), "")
        if not tag or tag in seen:
            continue
        try:
            conf = float(item.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0.0
        if conf < min_confidence:
            continue
        seen.add(tag)
        reason = evidence.get(tag) or evidence.get(tag.lower())
        row: dict[str, Any] = {
            "tag": tag,
            "confidence": round(conf, 3),
            "evidence": str(reason).strip() if reason else None,
        }
        if pass_name:
            row["pass"] = pass_name
        out.append(row)
    out.sort(key=lambda row: (-row["confidence"], row["tag"]))
    return out


def resolve_unsure(raw: dict[str, Any], allowed: list[str]) -> list[str]:
    allowed_lower = {t.lower(): t for t in allowed}
    out: list[str] = []
    for item in raw.get("unsure") or []:
        name = str(item).strip()
        if not name:
            continue
        canon = name if name in allowed_lower.values() else allowed_lower.get(name.lower())
        if canon and canon not in out:
            out.append(canon)
    return out


def split_by_confidence(
    tags: list[dict[str, Any]],
    *,
    high_threshold: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    high = [t for t in tags if t["confidence"] >= high_threshold]
    low = [t for t in tags if t["confidence"] < high_threshold]
    return high, low


def merge_passes(
    locked: list[dict[str, Any]],
    review_tags: list[dict[str, Any]],
    *,
    high_threshold: float,
    min_accept: float,
    candidates: list[str],
    contradicted: list[str],
    unsure: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (accepted_tags, rejected_tags). Accuracy-first: omit if still weak."""
    contradicted_set = set(contradicted)
    by_tag: dict[str, dict[str, Any]] = {}
    rejects: list[dict[str, Any]] = []

    for row in locked:
        if row["tag"] in contradicted_set:
            rejects.append(
                {
                    **row,
                    "source": "website",
                    "reason": "contradicted_by_reviews",
                }
            )
            continue
        if row["confidence"] < min_accept:
            rejects.append({**row, "source": "website", "reason": "below_accept_threshold"})
            continue
        item = dict(row)
        item.setdefault("pass", "website")
        item["source"] = "website"
        by_tag[item["tag"]] = item

    review_by_tag = {t["tag"]: t for t in review_tags}
    for row in review_tags:
        tag = row["tag"]
        if tag in contradicted_set and tag in {t["tag"] for t in locked}:
            continue
        if row["confidence"] < min_accept:
            rejects.append({**row, "source": "reviews", "reason": "below_accept_threshold"})
            continue
        existing = by_tag.get(tag)
        if (
            existing
            and existing.get("source") == "website"
            and existing["confidence"] >= high_threshold
            and row["confidence"] <= existing["confidence"]
        ):
            continue
        item = dict(row)
        item["pass"] = "reviews"
        item["source"] = "website+reviews" if existing else "reviews"
        if existing and existing.get("source") == "website":
            item["confidence"] = max(existing["confidence"], row["confidence"])
            if not item.get("evidence") and existing.get("evidence"):
                item["evidence"] = existing["evidence"]
        by_tag[tag] = item

    # Candidates never confirmed by reviews → reject (do not keep weak website guesses).
    for name in candidates:
        if name in by_tag:
            continue
        if name in contradicted_set:
            continue
        if any(r["tag"] == name and r.get("reason") == "below_accept_threshold" for r in rejects):
            continue
        weak = review_by_tag.get(name)
        if weak:
            continue  # already recorded as below_accept_threshold
        # Fall back to original low website row if present in rejects? add explicit reason
        rejects.append(
            {
                "tag": name,
                "confidence": (weak or {}).get("confidence"),
                "evidence": (weak or {}).get("evidence"),
                "source": "reviews" if weak else "website",
                "reason": "unconfirmed_after_reviews",
            }
        )

    for name in unsure:
        if name in by_tag or any(r["tag"] == name for r in rejects):
            continue
        rejects.append(
            {
                "tag": name,
                "confidence": None,
                "evidence": None,
                "source": "website",
                "reason": "unsure_unconfirmed",
            }
        )

    accepted = [t for t in by_tag.values() if t["confidence"] >= min_accept]
    accepted.sort(key=lambda row: (-row["confidence"], row["tag"]))

    # Dedupe rejects by tag+reason
    seen_rej: set[tuple[str, str]] = set()
    uniq_rejects: list[dict[str, Any]] = []
    for row in rejects:
        key = (row["tag"], row.get("reason") or "")
        if key in seen_rej:
            continue
        seen_rej.add(key)
        uniq_rejects.append(row)
    uniq_rejects.sort(key=lambda r: (r.get("reason") or "", r["tag"]))
    return accepted, uniq_rejects


def upsert_scrape(
    conn,
    place: dict[str, Any],
    scrape: dict[str, Any],
    reviews: dict[str, Any] | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO venue_scrapes (
                google_place_id, website_uri, content_hash, extracted_text,
                scraped_at, scrape_status, scrape_error,
                reviews_text, reviews_source, reviews_status, reviews_fetched_at
            ) VALUES (
                %s, %s, %s, %s, NOW(), %s, %s,
                %s, %s, %s, CASE WHEN %s THEN NOW() ELSE NULL END
            )
            ON CONFLICT (google_place_id) DO UPDATE SET
                website_uri = EXCLUDED.website_uri,
                content_hash = EXCLUDED.content_hash,
                extracted_text = EXCLUDED.extracted_text,
                scraped_at = EXCLUDED.scraped_at,
                scrape_status = EXCLUDED.scrape_status,
                scrape_error = EXCLUDED.scrape_error,
                reviews_text = EXCLUDED.reviews_text,
                reviews_source = EXCLUDED.reviews_source,
                reviews_status = EXCLUDED.reviews_status,
                reviews_fetched_at = EXCLUDED.reviews_fetched_at
            """,
            (
                place["google_place_id"],
                scrape.get("final_url") or place.get("website_uri"),
                scrape.get("content_hash"),
                scrape.get("text") or None,
                scrape.get("status"),
                scrape.get("error"),
                (reviews or {}).get("text"),
                ",".join((reviews or {}).get("sources") or []) or None,
                (reviews or {}).get("status"),
                bool(reviews),
            ),
        )
    conn.commit()


def upsert_tags(
    conn,
    place_id: str,
    tags: list[dict[str, Any]],
    rejects: list[dict[str, Any]],
    *,
    model: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM venue_tags WHERE google_place_id = %s", (place_id,))
        cur.execute("DELETE FROM venue_tag_rejects WHERE google_place_id = %s", (place_id,))
        for row in tags:
            source = row.get("source") or row.get("pass") or "llm_v1"
            cur.execute(
                """
                INSERT INTO venue_tags (
                    google_place_id, tag, confidence, evidence, source, model_version, tagged_at
                ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (google_place_id, tag) DO UPDATE SET
                    confidence = EXCLUDED.confidence,
                    evidence = EXCLUDED.evidence,
                    source = EXCLUDED.source,
                    model_version = EXCLUDED.model_version,
                    tagged_at = EXCLUDED.tagged_at
                """,
                (
                    place_id,
                    row["tag"],
                    row["confidence"],
                    row.get("evidence"),
                    source,
                    model,
                ),
            )
        for row in rejects:
            cur.execute(
                """
                INSERT INTO venue_tag_rejects (
                    google_place_id, tag, confidence, evidence, reason,
                    source, model_version, rejected_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (google_place_id, tag, reason) DO UPDATE SET
                    confidence = EXCLUDED.confidence,
                    evidence = EXCLUDED.evidence,
                    source = EXCLUDED.source,
                    model_version = EXCLUDED.model_version,
                    rejected_at = EXCLUDED.rejected_at
                """,
                (
                    place_id,
                    row["tag"],
                    row.get("confidence"),
                    row.get("evidence"),
                    row.get("reason") or "unconfirmed",
                    row.get("source"),
                    model,
                ),
            )
    conn.commit()


def print_pass(title: str, tags: list[dict[str, Any]], unsure: list[str] | None = None) -> None:
    print(f"\n{title}")
    if not tags:
        print("  (none)")
    else:
        for row in tags:
            evid = f"  — {row['evidence']}" if row.get("evidence") else ""
            print(f"  {row['confidence']:.2f}  {row['tag']}{evid}")
    if unsure:
        print(f"  unsure: {', '.join(unsure)}")


def print_result(
    place: dict[str, Any],
    scrape: dict[str, Any],
    *,
    high_threshold: float,
    min_accept: float,
    high: list[dict[str, Any]],
    low: list[dict[str, Any]],
    unsure: list[str],
    reviews: dict[str, Any] | None,
    final_tags: list[dict[str, Any]],
    rejects: list[dict[str, Any]],
    review_ran: bool,
) -> None:
    print()
    print("=" * 72)
    print(f"{place.get('place_name')}  ({place.get('borough')})")
    print(f"type: {place.get('primary_type')}  |  price: {place.get('price_level')}")
    print(f"website: {place.get('website_uri')}")
    print(
        f"website scrape: {scrape.get('status')}"
        + (f" ({scrape.get('error')})" if scrape.get("error") else "")
    )
    pages = scrape.get("pages_fetched") or []
    if pages:
        print(f"pages fetched ({len(pages)}): {', '.join(pages[:4])}" + (" ..." if len(pages) > 4 else ""))
    if scrape.get("text"):
        preview = scrape["text"][:200].replace("\n", " ")
        print(f"website excerpt: {preview}...")

    print_pass(f"Pass 1 — high confidence (≥{high_threshold:.2f}, kept if not contradicted)", high)
    print_pass(f"Pass 1 — low confidence (<{high_threshold:.2f}, needs reviews)", low, unsure)

    if review_ran:
        status = (reviews or {}).get("status")
        sources = ",".join((reviews or {}).get("sources") or []) or "none"
        n_reviews = (reviews or {}).get("review_excerpt_count")
        n_snips = (reviews or {}).get("snippet_count")
        counts = ""
        if n_reviews is not None or n_snips is not None:
            counts = f"  review_bodies={n_reviews or 0} snippets={n_snips or 0}"
        print(f"\nPass 2 — web reviews: {status}  sources={sources}{counts}")
        if (reviews or {}).get("text"):
            preview = (reviews or {})["text"][:220].replace("\n", " ")
            print(f"reviews excerpt: {preview}...")
    else:
        print("\nPass 2 — skipped (website confidence was enough)")

    print_pass(f"Accepted tags (≥{min_accept:.2f})", final_tags)
    print("\nNot tagged (kept for review — accuracy first)")
    if not rejects:
        print("  (none)")
    else:
        for row in rejects:
            conf = row.get("confidence")
            conf_s = f"{conf:.2f}" if isinstance(conf, (int, float)) else "—"
            evid = f"  — {row['evidence']}" if row.get("evidence") else ""
            print(f"  {conf_s}  {row['tag']}  [{row.get('reason')}]{evid}")
    print("=" * 72)


def check_ollama(base_url: str, model: str) -> None:
    import requests

    try:
        root = requests.get(base_url.rstrip("/") + "/", timeout=5)
        if root.status_code >= 400:
            raise SystemExit(f"Ollama not reachable at {base_url} (HTTP {root.status_code})")
    except requests.RequestException as exc:
        raise SystemExit(
            f"Ollama not reachable at {base_url}. Open the Ollama app, then retry.\n{exc}"
        ) from exc

    try:
        tags = requests.get(base_url.rstrip("/") + "/api/tags", timeout=10)
        tags.raise_for_status()
        exact = {m.get("name") for m in tags.json().get("models", [])}
        if model not in exact and not any(
            (m or "").startswith(model.split(":")[0]) for m in exact
        ):
            print(f"Warning: model '{model}' not found in `ollama list`. Installed: {sorted(exact)}")
    except requests.RequestException:
        pass


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Tag Après venues with Ollama (website first, reviews for low confidence)"
    )
    p.add_argument("--database-url", default=None, help="Neon connection string override")
    p.add_argument("--apply-schema", action="store_true", help="Create/update venue_scrapes / venue_tags / vibe_taxonomy")
    p.add_argument(
        "--sync-taxonomy",
        action="store_true",
        help="Upsert the full tag list from vibe_taxonomy.py into Neon vibe_taxonomy",
    )
    p.add_argument("--name", default=None, help="Substring match on place_name")
    p.add_argument("--place-id", default=None, help="Exact google_place_id")
    p.add_argument("--borough", default=None, help="Filter by borough")
    p.add_argument("--limit", type=int, default=1, help="How many venues to tag (default 1)")
    p.add_argument("--allow-no-website", action="store_true", help="Tag even without website_uri")
    p.add_argument(
        "--skip-tagged",
        action="store_true",
        help="Skip venues that already have at least one row in venue_tags (resume-friendly)",
    )
    p.add_argument("--save", action="store_true", help="Write scrape + tags to Neon")
    p.add_argument("--model", default=os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL))
    p.add_argument("--ollama-url", default=os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_URL))
    p.add_argument(
        "--high-confidence",
        type=float,
        default=HIGH_CONFIDENCE,
        help=f"Website tags at/above this skip review confirmation (default {HIGH_CONFIDENCE})",
    )
    p.add_argument(
        "--min-confidence",
        type=float,
        default=MIN_ACCEPT,
        help=f"Final accept threshold after merge (default {MIN_ACCEPT})",
    )
    p.add_argument(
        "--force-reviews",
        action="store_true",
        help="Always run web-review pass even if website tags are all high-confidence",
    )
    p.add_argument(
        "--no-reviews",
        action="store_true",
        help="Never fetch web reviews (website pass only)",
    )
    p.add_argument("--dry-run-prompt", action="store_true", help="Print pass-1 prompt and exit")
    return p.parse_args()


def tag_one_venue(
    place: dict[str, Any],
    *,
    model: str,
    ollama_url: str,
    high_threshold: float,
    min_accept: float,
    force_reviews: bool,
    no_reviews: bool,
    dry_run_prompt: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any] | None]:
    scrape = scrape_website(place.get("website_uri") or "")
    context = build_base_context(place, scrape)
    allowed = allowed_tags_for_type(place.get("primary_type"))
    prompt1 = build_website_prompt(context, allowed)

    if dry_run_prompt:
        print(prompt1)
        return [], [], scrape, None

    raw1 = call_ollama(prompt1, model=model, base_url=ollama_url)
    pass1 = normalize_tags(raw1, allowed, min_confidence=0.0, pass_name="website")
    unsure = resolve_unsure(raw1, allowed)
    high, low = split_by_confidence(pass1, high_threshold=high_threshold)

    candidates = [t["tag"] for t in low]
    for name in unsure:
        if name not in candidates and name not in {t["tag"] for t in high}:
            candidates.append(name)

    thin_site = needs_review_fallback(scrape)
    need_reviews = (not no_reviews) and (
        force_reviews or bool(candidates) or thin_site or not high
    )

    reviews: dict[str, Any] | None = None
    review_tags: list[dict[str, Any]] = []
    contradicted: list[str] = []
    raw2: dict[str, Any] = {}
    if need_reviews:
        print(
            f"  → fetching web reviews for {len(candidates)} low/unsure tag(s)"
            + (" (thin website)" if thin_site else "")
            + (" (forced)" if force_reviews else "")
        )
        try:
            reviews = fetch_web_reviews(place)
        except Exception as exc:  # noqa: BLE001
            reviews = {"status": "error", "text": "", "sources": [], "error": str(exc)}
            print(f"  → review fetch failed: {exc}")

        if reviews.get("text"):
            prompt2 = build_review_prompt(
                context,
                allowed,
                locked_tags=high,
                candidate_tags=candidates,
                reviews_text=reviews["text"],
            )
            raw2 = call_ollama(prompt2, model=model, base_url=ollama_url)
            review_tags = normalize_tags(
                raw2, allowed, min_confidence=0.0, pass_name="reviews"
            )
            contradicted = resolve_unsure(
                {"unsure": raw2.get("contradicted") or []}, allowed
            )
        else:
            print("  → no review text found; keeping only high-confidence website tags")

    if need_reviews and (reviews or {}).get("text"):
        final_tags, rejects = merge_passes(
            high,
            review_tags,
            high_threshold=high_threshold,
            min_accept=min_accept,
            candidates=candidates,
            contradicted=contradicted,
            unsure=unsure,
        )
    elif need_reviews:
        # No usable review text → accuracy first: keep only strong website tags.
        final_tags = [
            {**t, "source": "website", "pass": "website"}
            for t in high
            if t["confidence"] >= min_accept
        ]
        rejects = [
            {**t, "source": "website", "reason": "unconfirmed_no_review_text"}
            for t in low
        ]
        for name in unsure:
            if name in {t["tag"] for t in final_tags} or any(r["tag"] == name for r in rejects):
                continue
            rejects.append(
                {
                    "tag": name,
                    "confidence": None,
                    "evidence": None,
                    "source": "website",
                    "reason": "unconfirmed_no_review_text",
                }
            )
    else:
        final_tags = [
            {**t, "source": "website", "pass": "website"}
            for t in pass1
            if t["confidence"] >= min_accept
        ]
        rejects = [
            {**t, "source": "website", "reason": "below_accept_threshold"}
            for t in pass1
            if t["confidence"] < min_accept
        ]
        for name in unsure:
            if name in {t["tag"] for t in final_tags} or any(r["tag"] == name for r in rejects):
                continue
            rejects.append(
                {
                    "tag": name,
                    "confidence": None,
                    "evidence": None,
                    "source": "website",
                    "reason": "unsure_unconfirmed",
                }
            )

    print_result(
        place,
        scrape,
        high_threshold=high_threshold,
        min_accept=min_accept,
        high=high,
        low=low,
        unsure=unsure,
        reviews=reviews,
        final_tags=final_tags,
        rejects=rejects,
        review_ran=need_reviews,
    )
    return final_tags, rejects, scrape, reviews


def reconnect(db_url: str, old_conn=None):
    """Open a fresh Neon connection; close the old one if it died mid-batch."""
    if old_conn is not None:
        try:
            old_conn.close()
        except Exception:  # noqa: BLE001
            pass
    return connect(db_url)


def main() -> None:
    args = parse_args()
    db_url = load_database_url(args.database_url)
    conn = connect(db_url)

    try:
        if args.apply_schema:
            apply_schema(conn)
            sync_taxonomy(conn)
        elif args.sync_taxonomy:
            sync_taxonomy(conn)

        # Schema/taxonomy maintenance only — skip tagging unless a venue filter/save was requested.
        if (args.apply_schema or args.sync_taxonomy) and not (
            args.name
            or args.place_id
            or args.borough
            or args.skip_tagged
            or args.save
            or args.dry_run_prompt
            or args.allow_no_website
        ):
            return

        check_ollama(args.ollama_url, args.model)

        places = fetch_places(
            conn,
            name=args.name,
            place_id=args.place_id,
            borough=args.borough,
            limit=max(1, args.limit),
            require_website=not args.allow_no_website,
            skip_tagged=args.skip_tagged,
        )
        if not places:
            raise SystemExit(
                "No matching places found "
                "(try --allow-no-website, drop --skip-tagged, or a different --name)."
            )

        print(
            f"Tagging {len(places)} venue(s) with model={args.model} "
            f"(high≥{args.high_confidence}, accept≥{args.min_confidence}"
            f"{', skip-tagged' if args.skip_tagged else ''})"
        )
        for i, place in enumerate(places):
            if i:
                time.sleep(1.0)
            print(f"\n[{i + 1}/{len(places)}] {place.get('place_name')}")
            try:
                tags, rejects, scrape, reviews = tag_one_venue(
                    place,
                    model=args.model,
                    ollama_url=args.ollama_url,
                    high_threshold=args.high_confidence,
                    min_accept=args.min_confidence,
                    force_reviews=args.force_reviews,
                    no_reviews=args.no_reviews,
                    dry_run_prompt=args.dry_run_prompt,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  ! tagging failed, skipping: {exc}")
                continue
            if args.dry_run_prompt:
                continue
            if args.save:
                try:
                    upsert_scrape(conn, place, scrape, reviews)
                    upsert_tags(
                        conn,
                        place["google_place_id"],
                        tags,
                        rejects,
                        model=args.model,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! DB write failed ({exc}); reconnecting and retrying once…")
                    conn = reconnect(db_url, conn)
                    upsert_scrape(conn, place, scrape, reviews)
                    upsert_tags(
                        conn,
                        place["google_place_id"],
                        tags,
                        rejects,
                        model=args.model,
                    )
                print(
                    f"Saved {len(tags)} accepted tag(s), "
                    f"{len(rejects)} rejected candidate(s) for {place['place_name']}"
                )
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
