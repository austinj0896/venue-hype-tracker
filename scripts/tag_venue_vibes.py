#!/usr/bin/env python3
"""Tag venues with local Ollama: website first, then web reviews for low confidence.

Pass 1 — classify from Google place fields + website scrape.
Pass 2 — only when needed: DuckDuckGo/Yelp/Maps review text (no Places API)
          to confirm low-confidence tags and fill gaps.

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
from vibe_taxonomy import allowed_tags_for_type, taxonomy_prompt_block

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:7b"
# Website tags at/above this are kept without a review pass.
HIGH_CONFIDENCE = 0.75
# Final tags below this are dropped after merge.
MIN_ACCEPT = 0.65
MAX_WEBSITE_CHARS = 3500
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
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


def fetch_places(
    conn,
    *,
    name: str | None,
    place_id: str | None,
    borough: str | None,
    limit: int,
    require_website: bool,
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

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT google_place_id, place_name, primary_type, venue_category,
               price_level, website_uri, borough, formatted_address,
               short_formatted_address
        FROM places
        {where}
        ORDER BY random()
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


def scrape_website(url: str, timeout: float = 20.0) -> dict[str, Any]:
    import requests

    if not url or not url.strip():
        return {
            "status": "no_website",
            "text": "",
            "error": None,
            "final_url": None,
            "content_hash": None,
        }

    try:
        resp = requests.get(
            url.strip(),
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        return {
            "status": "error",
            "text": "",
            "error": str(exc),
            "final_url": url,
            "content_hash": None,
        }

    if resp.status_code in (401, 403, 429):
        return {
            "status": "blocked",
            "text": "",
            "error": f"HTTP {resp.status_code}",
            "final_url": resp.url,
            "content_hash": None,
        }
    if resp.status_code >= 400:
        return {
            "status": "error",
            "text": "",
            "error": f"HTTP {resp.status_code}",
            "final_url": resp.url,
            "content_hash": None,
        }

    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "html" not in ctype and "text" not in ctype and ctype:
        return {
            "status": "empty",
            "text": "",
            "error": f"Unsupported content-type: {ctype}",
            "final_url": resp.url,
            "content_hash": None,
        }

    text = clean_html_text(resp.text)
    if len(text) < 40:
        return {
            "status": "empty",
            "text": text,
            "error": "Extracted text too short",
            "final_url": resp.url,
            "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
        }

    truncated = text[:MAX_WEBSITE_CHARS]
    return {
        "status": "ok",
        "text": truncated,
        "error": None,
        "final_url": resp.url,
        "content_hash": hashlib.sha256(truncated.encode("utf-8")).hexdigest(),
    }


def build_base_context(place: dict[str, Any], scrape: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": place.get("place_name"),
        "primary_type": place.get("primary_type"),
        "venue_category": place.get("venue_category"),
        "price_level": place.get("price_level"),
        "borough": place.get("borough"),
        "address": place.get("short_formatted_address") or place.get("formatted_address"),
        "website_uri": place.get("website_uri"),
        "scrape_status": scrape.get("status"),
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
    return f"""You refine vibe tags for Après using customer review text from the web (Yelp/Google search snippets and pages).

This is PASS 2 — website-only tagging already finished.
LOCKED tags (already high-confidence from the website; do not remove them):
{json.dumps(locked_names)}

CANDIDATE tags to confirm, raise, lower, or drop using reviews:
{json.dumps(candidate_tags)}

You may also ADD new tags from the Allowed list when reviews clearly support them.

Rules:
- Use ONLY Allowed tags.
- Prefer quotes from the review text as evidence.
- If reviews do not clearly support a candidate, OMIT it — accuracy over coverage.
- Do not keep a weak website guess just because it was a candidate.
- Do not contradict locked tags unless reviews overwhelmingly disagree — if so, put them in "contradicted".
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
{json.dumps(context, indent=2)}

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
    if scrape.get("text"):
        preview = scrape["text"][:200].replace("\n", " ")
        print(f"website excerpt: {preview}...")

    print_pass(f"Pass 1 — high confidence (≥{high_threshold:.2f}, kept if not contradicted)", high)
    print_pass(f"Pass 1 — low confidence (<{high_threshold:.2f}, needs reviews)", low, unsure)

    if review_ran:
        status = (reviews or {}).get("status")
        sources = ",".join((reviews or {}).get("sources") or []) or "none"
        print(f"\nPass 2 — web reviews: {status}  sources={sources}")
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
    p.add_argument("--apply-schema", action="store_true", help="Create/update venue_scrapes / venue_tags")
    p.add_argument("--name", default=None, help="Substring match on place_name")
    p.add_argument("--place-id", default=None, help="Exact google_place_id")
    p.add_argument("--borough", default=None, help="Filter by borough")
    p.add_argument("--limit", type=int, default=1, help="How many venues to tag (default 1)")
    p.add_argument("--allow-no-website", action="store_true", help="Tag even without website_uri")
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


def main() -> None:
    args = parse_args()
    db_url = load_database_url(args.database_url)
    conn = connect(db_url)

    try:
        if args.apply_schema:
            apply_schema(conn)
            if args.limit <= 0 and not args.name and not args.place_id:
                return

        check_ollama(args.ollama_url, args.model)

        places = fetch_places(
            conn,
            name=args.name,
            place_id=args.place_id,
            borough=args.borough,
            limit=max(1, args.limit),
            require_website=not args.allow_no_website,
        )
        if not places:
            raise SystemExit(
                "No matching places found (try --allow-no-website or a different --name)."
            )

        print(
            f"Tagging {len(places)} venue(s) with model={args.model} "
            f"(high≥{args.high_confidence}, accept≥{args.min_confidence})"
        )
        for i, place in enumerate(places):
            if i:
                time.sleep(1.0)
            print(f"\n[{i + 1}/{len(places)}] {place.get('place_name')}")
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
            if args.dry_run_prompt:
                continue
            if args.save:
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
        conn.close()


if __name__ == "__main__":
    main()
