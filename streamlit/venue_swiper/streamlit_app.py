"""
Après — discover and rate food & drink spots by neighborhood.
Tagline: Find what comes next.

Runs on **Neon Postgres** (Streamlit Community Cloud) or **Snowflake** (SiS / legacy Cloud).
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from html import escape
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from db import (
    backend,
    clear_db_caches,
    fetch_db_identity,
    places_table as dim_places_table,
    ratings_table,
    run_query,
    upsert_rating,
)
from date_planner import (
    DATE_COMBOS,
    DatePlan,
    RatingLookup,
    combo_by_id,
    find_date_plans,
    pick_random_plan,
    rating_badge_label,
    rebuild_plan,
    venues_for_stop,
)
from geo import filter_by_radius, miles_to_meters
from location_ui import render_location_picker
from places_data import fetch_community_ratings, fetch_venues_with_coords
from planned_dates_store import fetch_planned_dates, save_planned_date

DEFAULT_BOROUGH = "Manhattan Beach"
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
DISCOVER_BOROUGH_KEY = "discover_borough"


def discover_venue_key(borough: str) -> str:
    return f"discover_venue_{borough}"

# Food, drink, bars, clubs — excludes hotels, orgs, courts, schools, etc.
ALLOWED_PRIMARY_TYPES = (
    "american_restaurant",
    "bagel_shop",
    "bakery",
    "bar",
    "breakfast_restaurant",
    "brunch_restaurant",
    "cafe",
    "chinese_restaurant",
    "coffee_shop",
    "diner",
    "event_venue",
    "fast_food_restaurant",
    "french_restaurant",
    "greek_restaurant",
    "irish_pub",
    "italian_restaurant",
    "japanese_restaurant",
    "juice_shop",
    "mexican_restaurant",
    "night_club",
    "pizza_restaurant",
    "pub",
    "restaurant",
    "sandwich_shop",
    "seafood_restaurant",
    "sports_bar",
    "steak_house",
    "sushi_restaurant",
    "thai_restaurant",
)

FONT_SERIF = "Georgia, 'Times New Roman', serif"
FONT_SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"

# SiS strips <link> tags and often breaks <style> inside st.markdown — inject via components.html.
APRES_CSS = f"""
:root {{
    --cream: #F8E6D2;
    --brown: #704D3B;
    --gold: #D3A345;
    --steel: #7897A3;
    --sage: #B6BEB1;
    --text-dark: #2C1A10;
    --text-mid: #7A5B48;
    --text-light: #B09080;
}}
html, body, [class*="css"] {{
    font-family: {FONT_SANS};
    color: var(--text-dark);
}}
.stApp {{
    background: var(--cream);
}}
.block-container {{
    padding-top: 1.25rem;
    padding-bottom: 2rem;
    max-width: 480px;
}}
header[data-testid="stHeader"] {{
    background: transparent;
}}
#MainMenu, footer, header[data-testid="stHeader"] {{
    visibility: hidden;
}}
h1, h2, h3 {{
    font-family: {FONT_SERIF} !important;
    font-weight: 400 !important;
    color: var(--brown) !important;
}}
.apres-status {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 11px;
    font-weight: 500;
    color: var(--brown);
    letter-spacing: 0.05em;
    margin-bottom: 1rem;
}}
.apres-status .tagline {{
    font-family: {FONT_SERIF};
    font-size: 13px;
    font-style: italic;
    letter-spacing: 0;
}}
.apres-greeting {{
    font-family: {FONT_SERIF};
    font-size: 30px;
    font-weight: 300;
    font-style: italic;
    color: var(--brown);
    line-height: 1.2;
    margin: 0 0 0.25rem 0;
}}
.apres-sub {{
    font-size: 11px;
    color: var(--text-light);
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-bottom: 1.25rem;
}}
.section-label {{
    font-size: 10px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--text-light);
    margin: 0.5rem 0 0.75rem;
}}
.date-card {{
    background: var(--brown);
    border-radius: 20px;
    padding: 1.35rem 1.25rem 1.15rem;
    position: relative;
    overflow: hidden;
    margin-bottom: 0.75rem;
    min-height: 240px;
}}
.date-card::before {{
    content: '';
    position: absolute;
    top: -40px; right: -40px;
    width: 140px; height: 140px;
    border-radius: 50%;
    background: rgba(211,163,69,0.12);
}}
.date-card::after {{
    content: '';
    position: absolute;
    bottom: -20px; left: 40px;
    width: 80px; height: 80px;
    border-radius: 50%;
    background: rgba(248,230,210,0.05);
}}
.date-card-label {{
    font-size: 10px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--sage);
    margin-bottom: 8px;
    position: relative;
}}
.date-card-title {{
    font-family: {FONT_SERIF};
    font-size: 28px;
    font-weight: 400;
    color: var(--cream);
    margin-bottom: 4px;
    line-height: 1.15;
    position: relative;
}}
.date-card-meta {{
    font-size: 12px;
    color: rgba(248,230,210,0.55);
    margin-bottom: 14px;
    position: relative;
}}
.date-card-pills {{
    position: relative;
    margin-bottom: 12px;
}}
.date-card-pills span {{
    display: inline-block;
    background: rgba(248,230,210,0.12);
    border: 0.5px solid rgba(248,230,210,0.18);
    border-radius: 999px;
    padding: 0.2rem 0.55rem;
    margin: 0.15rem 0.35rem 0.15rem 0;
    font-size: 10px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--sage);
}}
.date-card-footer {{
    font-size: 12px;
    color: rgba(248,230,210,0.75);
    border-left: 2px solid var(--gold);
    padding-left: 10px;
    font-style: italic;
    line-height: 1.5;
    position: relative;
}}
.date-card-footer a {{
    color: var(--gold);
    text-decoration: none;
}}
.swipe-hint {{
    text-align: center;
    color: var(--text-light);
    font-size: 12px;
    letter-spacing: 0.04em;
    margin: 0.35rem 0 0.85rem;
}}
.progress-track {{
    width: 100%;
    background: rgba(112,77,59,0.12);
    border-radius: 4px;
    height: 3px;
    overflow: hidden;
    margin: 0.25rem 0 1.25rem;
}}
.progress-bar {{
    height: 100%;
    background: var(--gold);
    border-radius: 4px;
}}
.progress-caption {{
    font-size: 11px;
    color: var(--text-light);
    letter-spacing: 0.06em;
    margin-bottom: 0.35rem;
}}
.login-panel {{
    background: white;
    border-radius: 16px;
    border: 0.5px solid rgba(112,77,59,0.12);
    padding: 1.25rem 1.1rem;
    margin: 0.75rem 0 1rem;
}}
.login-panel p {{
    font-size: 13px;
    color: var(--text-mid);
    line-height: 1.55;
    margin: 0;
}}
.bucket-card {{
    background: white;
    border-radius: 16px;
    border: 0.5px solid rgba(112,77,59,0.12);
    padding: 16px 18px;
    margin-bottom: 10px;
}}
.bucket-title {{
    font-family: {FONT_SERIF};
    font-size: 20px;
    color: var(--brown);
    margin-bottom: 2px;
}}
.bucket-sub {{
    font-size: 12px;
    color: var(--text-light);
    margin-bottom: 6px;
}}
.bucket-score {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(211,163,69,0.14);
    border: 0.5px solid rgba(211,163,69,0.35);
    border-radius: 20px;
    padding: 5px 14px;
    font-size: 13px;
    color: var(--brown);
    font-weight: 500;
}}
.bucket-score-num {{
    font-family: {FONT_SERIF};
    font-size: 18px;
}}
.bucket-icon-skip {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px; height: 36px;
    border-radius: 10px;
    background: rgba(120,151,163,0.14);
    color: var(--steel);
    font-size: 14px;
    margin-bottom: 8px;
}}
.date-plan-card {{
    background: white;
    border-radius: 16px;
    border: 0.5px solid rgba(112,77,59,0.12);
    padding: 14px 16px;
    margin-bottom: 12px;
}}
.date-plan-header {{
    font-family: {FONT_SERIF};
    font-size: 18px;
    color: var(--brown);
    margin-bottom: 10px;
}}
.date-plan-stop {{
    padding: 10px 0;
    border-bottom: 0.5px solid rgba(112,77,59,0.08);
}}
.date-plan-stop:last-of-type {{
    border-bottom: none;
}}
.date-plan-stop-num {{
    font-size: 10px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--gold);
    margin-bottom: 2px;
}}
.date-plan-stop-name {{
    font-family: {FONT_SERIF};
    font-size: 17px;
    color: var(--brown);
}}
.date-plan-stop-meta {{
    font-size: 11px;
    color: var(--text-light);
}}
.date-plan-walk {{
    text-align: center;
    font-size: 12px;
    color: var(--steel);
    padding: 8px 0;
    letter-spacing: 0.04em;
}}
.date-plan-walk-time {{
    font-weight: 600;
    color: var(--brown);
}}
.stars-preview {{
    font-family: {FONT_SERIF};
    font-size: 22px;
    color: var(--gold);
    letter-spacing: 0.08em;
    text-align: center;
    margin: 0.15rem 0 0.5rem;
}}
div[data-testid="stTabs"] button {{
    font-family: {FONT_SANS};
    font-size: 12px;
    letter-spacing: 0.06em;
    color: var(--text-light);
}}
div[data-testid="stTabs"] button[aria-selected="true"] {{
    color: var(--brown);
}}
div[data-testid="stSlider"] label,
div[data-testid="stForm"] label {{
    font-size: 10px !important;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--text-light) !important;
}}
div[data-testid="stTextInput"] input {{
    border-radius: 12px;
    border: 0.5px solid rgba(112,77,59,0.18);
    background: white;
    color: var(--text-dark);
}}
div[data-testid="stBaseButton-secondary"] button {{
    background: transparent !important;
    color: var(--text-mid) !important;
    border: 0.5px solid rgba(112,77,59,0.25) !important;
    border-radius: 14px !important;
    font-family: {FONT_SANS} !important;
    font-weight: 500 !important;
    letter-spacing: 0.04em !important;
}}
div[data-testid="stBaseButton-primary"] button,
div[data-testid="stFormSubmitButton"] button {{
    background: var(--gold) !important;
    color: var(--brown) !important;
    border: none !important;
    border-radius: 14px !important;
    font-family: {FONT_SANS} !important;
    font-weight: 500 !important;
    letter-spacing: 0.04em !important;
}}
div[data-testid="stSlider"] [data-baseweb="slider"] > div > div:nth-child(1) {{
    background: rgba(112,77,59,0.18) !important;
}}
div[data-testid="stSlider"] [data-baseweb="slider"] > div > div:nth-child(2) {{
    background: var(--gold) !important;
}}
div[data-testid="stSlider"] [role="slider"] {{
    background: var(--brown) !important;
    border: 2px solid var(--cream) !important;
    box-shadow: 0 1px 4px rgba(44,26,16,0.25) !important;
}}
div[data-testid="stSlider"] [data-testid="stThumbValue"] {{
    color: var(--brown) !important;
    font-weight: 600 !important;
}}
"""

st.set_page_config(
    page_title="Après",
    page_icon="*",
    layout="centered",
    initial_sidebar_state="collapsed",
)


def format_price_level(raw: str | None) -> str:
    if not raw:
        return ""
    text = raw.replace("_", " ").strip().lower()
    if text.startswith("price level "):
        text = text[len("price level ") :]
    return text.title()


def inject_styles() -> None:
    # st.html() on Streamlit Cloud does not run parent-document scripts — use components.html.
    css_literal = json.dumps(APRES_CSS)
    script = f"""<script>
    (function() {{
        const doc = window.parent.document;
        if (doc.getElementById("apres-styles")) return;
        const el = doc.createElement("style");
        el.id = "apres-styles";
        el.textContent = {css_literal};
        doc.head.appendChild(el);
    }})();
    </script>"""
    components.html(script, height=0, width=0)
    # Fallback: styles widgets inside the app iframe when parent injection is blocked.
    st.markdown(f"<style>{APRES_CSS}</style>", unsafe_allow_html=True)


def show_data_error(exc: Exception) -> None:
    db_label = "Neon Postgres" if backend() == "postgres" else "Snowflake"
    st.error(f"Cannot read venue data from {db_label}.")
    st.markdown(f"**Error:** `{exc}`")
    st.markdown(f"**Places table:** `{dim_places_table()}`")

    identity = fetch_db_identity()
    if identity:
        st.markdown("**Database session:**")
        st.code(
            "\n".join(f"{key}: {value}" for key, value in identity.items()),
            language="text",
        )

    try:
        count_row = run_query(
            f"""
            select count(*) as venue_count
            from {dim_places_table()}
            where borough = ?
            """,
            [DEFAULT_BOROUGH],
        )[0]
        venue_count = count_row.get("VENUE_COUNT") or count_row.get("venue_count")
        st.success(f"Live probe: **{venue_count}** venues — access works. Click **Retry**.")
    except Exception as probe_exc:
        st.markdown(f"**Live probe:** `{probe_exc}`")

    if st.button("Retry database connection", type="primary"):
        clear_db_caches()
        fetch_stats.clear()
        fetch_boroughs.clear()
        fetch_next_venue.clear()
        fetch_user_ratings.clear()
        st.rerun()

    if backend() == "postgres":
        st.markdown(
            """
            **Neon checklist**

            1. Streamlit secrets include `[connections.postgresql]` with your **pooled** Neon URL.
            2. Ran `neon/schema.sql` and seeded places:
               `python scripts/seed_neon_places.py --from-snowflake`
            3. **Reboot app** after changing secrets.
            """
        )
    else:
        st.markdown(
            f"""
            **Snowflake checklist**

            1. Grants on `{dim_places_table()}` and `{ratings_table()}` for the service role.
            2. snowsql as `VENUE_SWIPER_SVC` returns a row count for places.
            3. **Reboot app** after changing secrets.
            """
        )


def render_apres_header(subtitle: str = "Manhattan Beach") -> None:
    st.markdown(
        """
        <div class="apres-status">
            <span>Apr&egrave;s</span>
            <span class="tagline">Find what comes next.</span>
            <span>&middot;</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f'<p class="apres-greeting">{subtitle}</p>', unsafe_allow_html=True)


def render_progress(stats: dict[str, int]) -> None:
    pct = (stats["reviewed"] / stats["total"] * 100) if stats["total"] else 0
    st.markdown(
        f"""
        <div class="progress-caption">
            {stats['remaining']} left &middot; {stats['rated']} rated &middot; {stats['skipped']} skipped
        </div>
        <div class="progress-track">
            <div class="progress-bar" style="width: {pct:.1f}%;"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def normalize_email(raw: str) -> str:
    return raw.strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_PATTERN.match(email))


def stars_text(value: float | None) -> str:
    if value is None:
        return "-"
    full = int(value)
    half = 1 if value - full >= 0.5 else 0
    empty = 5 - full - half
    return "★" * full + ("½" if half else "") + "☆" * empty


def venue_type_filter_sql(alias: str = "d") -> tuple[str, list[str]]:
    placeholders = ", ".join("?" for _ in ALLOWED_PRIMARY_TYPES)
    return f"and {alias}.primary_type in ({placeholders})", list(ALLOWED_PRIMARY_TYPES)


def clear_discover_venue(borough: str | None = None) -> None:
    if borough:
        st.session_state.pop(discover_venue_key(borough), None)
    else:
        for key in list(st.session_state.keys()):
            if isinstance(key, str) and key.startswith("discover_venue_"):
                st.session_state.pop(key, None)
    fetch_next_venue.clear()


def get_discover_venue(email: str, borough: str) -> dict[str, Any] | None:
    """Pin the current card in session so slider moves don't re-roll random()."""
    key = discover_venue_key(borough)
    if key in st.session_state:
        return st.session_state[key]
    venue = fetch_next_venue(email, borough)
    if venue:
        st.session_state[key] = venue
    return venue


@st.cache_data(show_spinner=False)
def fetch_boroughs() -> list[str]:
    type_filter, type_params = venue_type_filter_sql("d")
    sql = f"""
        select distinct d.borough as borough
        from {dim_places_table()} d
        where d.borough is not null
          and trim(d.borough) != ''
          {type_filter}
        order by d.borough
    """
    rows = run_query(sql, type_params)
    return [str(row["BOROUGH"]) for row in rows if row.get("BOROUGH")]


@st.cache_data(show_spinner=False)
def fetch_stats(email: str, borough: str) -> dict[str, int]:
    type_filter, type_params = venue_type_filter_sql("d")
    sql = f"""
        select
            count(*) as total_venues,
            count(r.rating_id) as reviewed,
            count(*) filter (where r.status = 'rated') as rated,
            count(*) filter (where r.status = 'skipped') as skipped
        from {dim_places_table()} d
        left join {ratings_table()} r
            on r.google_place_id = d.google_place_id
            and r.user_email = ?
            and r.borough = ?
        where d.borough = ?
          {type_filter}
    """
    row = run_query(sql, [email, borough, borough, *type_params])[0]
    total = int(row["TOTAL_VENUES"] or 0)
    reviewed = int(row["REVIEWED"] or 0)
    return {
        "total": total,
        "reviewed": reviewed,
        "rated": int(row["RATED"] or 0),
        "skipped": int(row["SKIPPED"] or 0),
        "remaining": max(total - reviewed, 0),
    }


@st.cache_data(show_spinner=False)
def fetch_next_venue(email: str, borough: str) -> dict[str, Any] | None:
    type_filter, type_params = venue_type_filter_sql("d")
    sql = f"""
        select
            d.google_place_id,
            d.place_name,
            d.formatted_address,
            d.short_formatted_address,
            d.primary_type,
            d.venue_category,
            d.price_level,
            d.website_uri
        from {dim_places_table()} d
        where d.borough = ?
          {type_filter}
          and not exists (
              select 1
              from {ratings_table()} r
              where r.user_email = ?
                and r.google_place_id = d.google_place_id
          )
        order by random()
        limit 1
    """
    rows = run_query(sql, [borough, *type_params, email])
    return rows[0] if rows else None


@st.cache_data(show_spinner=False)
def fetch_user_ratings(email: str, status: str | None = None) -> list[dict[str, Any]]:
    status_filter = ""
    params: list[Any] = [email]
    if status:
        status_filter = "and r.status = ?"
        params.append(status)

    sql = f"""
        select
            r.place_name,
            r.google_place_id,
            r.borough,
            r.rating,
            r.status,
            r.updated_at,
            d.formatted_address,
            d.primary_type,
            d.venue_category
        from {ratings_table()} r
        left join {dim_places_table()} d
            on d.google_place_id = r.google_place_id
        where r.user_email = ?
          {status_filter}
        order by r.updated_at desc
    """
    return run_query(sql, params)


def save_rating(
    *,
    email: str,
    borough: str,
    google_place_id: str,
    place_name: str,
    status: str,
    rating: float | None,
) -> None:
    upsert_rating(
        email=email,
        borough=borough,
        google_place_id=google_place_id,
        place_name=place_name,
        status=status,
        rating=rating,
    )
    fetch_stats.clear()
    fetch_next_venue.clear()
    fetch_user_ratings.clear()
    fetch_community_ratings.clear()
    clear_discover_venue()


def get_ors_api_key() -> str | None:
    try:
        key = st.secrets.get("app", {}).get("ors_api_key", "")
        if key and str(key).strip():
            return str(key).strip()
    except Exception:
        pass
    import os

    return os.environ.get("ORS_API_KEY") or None


def format_scheduled_at(when: Any) -> str:
    """12-hour display e.g. Fri Jul 4 at 7:00 PM."""
    if when is None:
        return "TBD"
    if isinstance(when, str):
        when = datetime.fromisoformat(when.replace("Z", "+00:00"))
    if isinstance(when, datetime):
        hour = when.strftime("%I").lstrip("0") or "12"
        return f"{when.strftime('%a %b %d')} at {hour}:{when.strftime('%M %p')}"
    return str(when)


def hour_12_to_24(hour: int, ampm: str) -> int:
    if ampm == "AM":
        return 0 if hour == 12 else hour
    return 12 if hour == 12 else hour + 12


def render_date_stop(label: str, venue: dict, rating_stats: RatingLookup) -> str:
    name = escape(venue.get("PLACE_NAME") or "Unknown")
    pt = escape((venue.get("PRIMARY_TYPE") or "").replace("_", " "))
    addr = escape(venue.get("SHORT_FORMATTED_ADDRESS") or venue.get("FORMATTED_ADDRESS") or "")
    pid = str(venue.get("GOOGLE_PLACE_ID") or "")
    badge = escape(rating_badge_label(rating_stats.get(pid)))
    label_safe = escape(label)
    # Single-line HTML — indented lines inside st.markdown become code blocks.
    return (
        f'<div class="date-plan-stop">'
        f'<div class="date-plan-stop-num">{label_safe}</div>'
        f'<div class="date-plan-stop-name">{name}</div>'
        f'<div class="date-plan-stop-meta">{pt} &middot; {addr}</div>'
        f'<div class="date-plan-stop-meta" style="color:var(--gold);margin-top:2px;">{badge}</div>'
        f"</div>"
    )


def render_date_plan_card(plan: DatePlan, rating_stats: RatingLookup) -> None:
    walk_mins = f"{plan.walk.duration_min:.0f}"
    mi = plan.walk.distance_m / 1609.344
    src = "walk" if plan.walk.source == "ors" else "est."
    header = escape(plan.combo.label)
    stop1 = render_date_stop(f"1 · {plan.combo.first_label}", plan.first_stop, rating_stats)
    stop2 = render_date_stop(f"2 · {plan.combo.second_label}", plan.second_stop, rating_stats)
    html = (
        f'<div class="date-plan-card">'
        f'<div class="date-plan-header">{header}</div>'
        f"{stop1}"
        f'<div class="date-plan-walk">'
        f'<span class="date-plan-walk-time">{walk_mins} min</span> walk ({mi:.2f} mi, {src})'
        f"</div>"
        f"{stop2}"
        f"</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def _build_nearby_venue_pool(
    *,
    borough: str,
    combo,
    location,
    radius_mi: float,
) -> list[dict]:
    all_types = tuple(sorted(set(combo.first_types) | set(combo.second_types)))
    venues = fetch_venues_with_coords(borough, all_types)
    if not venues:
        return []
    return filter_by_radius(
        venues,
        origin_lat=location.lat,
        origin_lon=location.lon,
        radius_m=miles_to_meters(radius_mi),
    )


def render_planned_dates_list(email: str) -> None:
    try:
        rows = fetch_planned_dates(email, upcoming_only=True)
    except Exception as exc:
        st.caption(f"Could not load saved dates: {exc}")
        return

    st.markdown('<div class="section-label">Your planned dates</div>', unsafe_allow_html=True)
    if not rows:
        st.markdown(
            '<div class="login-panel"><p>No upcoming dates saved yet.</p></div>',
            unsafe_allow_html=True,
        )
        return

    for row in rows:
        when_label = format_scheduled_at(row.get("SCHEDULED_AT"))
        stop1 = escape(row.get("STOP1_PLACE_NAME") or "Stop 1")
        stop2 = escape(row.get("STOP2_PLACE_NAME") or "Stop 2")
        combo = escape(row.get("COMBO_LABEL") or "Date")
        walk = row.get("WALK_DURATION_MIN")
        walk_txt = f"{float(walk):.0f} min walk" if walk is not None else ""
        borough = escape(row.get("BOROUGH") or "")
        meta = " · ".join(p for p in [when_label, borough, walk_txt] if p)
        st.markdown(
            f'<div class="bucket-card">'
            f'<div class="bucket-title">{combo}</div>'
            f'<div class="bucket-sub">{stop1} → {stop2}</div>'
            f'<div class="bucket-sub">{meta}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )


def render_date_draft_editor(
    *,
    email: str,
    borough: str,
    combo,
    rating_stats: RatingLookup,
    ors_key: str | None,
) -> None:
    draft: DatePlan | None = st.session_state.get("date_draft")
    if draft is None:
        return

    nearby: list[dict] = st.session_state.get("date_nearby_venues") or []
    pool: list[DatePlan] = st.session_state.get("date_plans_pool") or []

    st.markdown('<div class="section-label">Your date</div>', unsafe_allow_html=True)
    render_date_plan_card(draft, rating_stats)

    col_reroll, col_spacer = st.columns([1, 2])
    with col_reroll:
        if st.button("Re-roll date", use_container_width=True, type="secondary"):
            nxt = pick_random_plan(pool, rating_stats, exclude=draft)
            if nxt:
                st.session_state["date_draft"] = nxt
            st.rerun()

    stop1_venues = venues_for_stop(nearby, combo, stop_index=0)
    stop2_venues = venues_for_stop(nearby, combo, stop_index=1)

    def venue_options(venues: list[dict]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for v in venues:
            pid = str(v.get("GOOGLE_PLACE_ID") or "")
            ptype = str(v.get("PRIMARY_TYPE") or "").replace("_", " ")
            name = v.get("PLACE_NAME") or "Unknown"
            label = f"{name} ({ptype})"
            if label in out:
                label = f"{label} · {pid[-6:]}"
            out[label] = v
        return out

    opts1 = venue_options(stop1_venues)
    opts2 = venue_options(stop2_venues)
    cur1_key = next(
        (k for k, v in opts1.items() if v.get("GOOGLE_PLACE_ID") == draft.first_stop.get("GOOGLE_PLACE_ID")),
        list(opts1.keys())[0] if opts1 else None,
    )
    cur2_key = next(
        (k for k, v in opts2.items() if v.get("GOOGLE_PLACE_ID") == draft.second_stop.get("GOOGLE_PLACE_ID")),
        list(opts2.keys())[0] if opts2 else None,
    )

    if opts1:
        pick1 = st.selectbox(
            f"Change {combo.first_label.lower()}",
            options=list(opts1.keys()),
            index=list(opts1.keys()).index(cur1_key) if cur1_key in opts1 else 0,
            key="draft_pick_stop1",
        )
        new_stop1 = opts1[pick1]
        if new_stop1.get("GOOGLE_PLACE_ID") != draft.first_stop.get("GOOGLE_PLACE_ID"):
            st.session_state["date_draft"] = rebuild_plan(
                combo, new_stop1, draft.second_stop, ors_api_key=ors_key
            )
            st.rerun()

    if opts2:
        pick2 = st.selectbox(
            f"Change {combo.second_label.lower()}",
            options=list(opts2.keys()),
            index=list(opts2.keys()).index(cur2_key) if cur2_key in opts2 else 0,
            key="draft_pick_stop2",
        )
        new_stop2 = opts2[pick2]
        if new_stop2.get("GOOGLE_PLACE_ID") != draft.second_stop.get("GOOGLE_PLACE_ID"):
            st.session_state["date_draft"] = rebuild_plan(
                combo, draft.first_stop, new_stop2, ors_api_key=ors_key
            )
            st.rerun()

    st.markdown('<div class="section-label">Schedule it</div>', unsafe_allow_html=True)
    default_day = date.today() + timedelta(days=1)

    with st.form("plan_date_form", clear_on_submit=False):
        sched_date = st.date_input("Date", value=default_day)
        col_h, col_m, col_ampm = st.columns(3)
        with col_h:
            sched_hour = st.selectbox(
                "Hour",
                options=list(range(1, 13)),
                index=6,
                format_func=lambda h: f"{h}:00",
            )
        with col_m:
            sched_minute = st.selectbox(
                "Minute",
                options=[0, 15, 30, 45],
                index=0,
                format_func=lambda m: f":{m:02d}",
            )
        with col_ampm:
            sched_ampm = st.selectbox("AM / PM", options=["AM", "PM"], index=1)
        preview = datetime.combine(
            sched_date,
            time(hour_12_to_24(sched_hour, sched_ampm), sched_minute),
        )
        st.caption(f"Scheduled for {format_scheduled_at(preview)}")
        submitted = st.form_submit_button("Plan date", type="primary", use_container_width=True)

    if submitted:
        scheduled_at = datetime.combine(
            sched_date,
            time(hour_12_to_24(sched_hour, sched_ampm), sched_minute),
        )
        try:
            save_planned_date(
                email=email,
                borough=borough,
                combo_id=combo.id,
                combo_label=combo.label,
                stop1=draft.first_stop,
                stop2=draft.second_stop,
                walk_distance_m=draft.walk.distance_m,
                walk_duration_min=draft.walk.duration_min,
                scheduled_at=scheduled_at,
            )
            fetch_planned_dates.clear()
            st.session_state.pop("date_draft", None)
            st.toast(f"Saved for {format_scheduled_at(scheduled_at)}")
            st.rerun()
        except Exception as exc:
            st.error(
                f"Could not save date: {exc}\n\n"
                "If the table is missing, run `neon/planned_dates_schema.sql` on your database."
            )


def render_plan_date(email: str) -> None:
    try:
        boroughs = fetch_boroughs()
    except Exception as exc:
        show_data_error(exc)
        return

    if not boroughs:
        st.warning("No locations in the venue catalog yet.")
        return

    st.markdown('<div class="section-label">Plan a date</div>', unsafe_allow_html=True)
    st.markdown(
        '<p class="swipe-hint">Build a two-stop evening — re-roll, swap stops, then save with a date & time.</p>',
        unsafe_allow_html=True,
    )

    if "plan_borough" not in st.session_state:
        st.session_state["plan_borough"] = (
            DEFAULT_BOROUGH if DEFAULT_BOROUGH in boroughs else boroughs[0]
        )
    borough = st.selectbox("Area", boroughs, key="plan_borough")

    location = render_location_picker(borough=borough)
    if not location:
        st.info("Set a starting point above to find a date.")
        render_planned_dates_list(email)
        return

    combo_labels = {c.id: c.label for c in DATE_COMBOS}
    combo_id = st.selectbox(
        "Date type",
        options=list(combo_labels.keys()),
        format_func=lambda cid: combo_labels[cid],
        key="plan_combo",
    )
    combo = next(c for c in DATE_COMBOS if c.id == combo_id)

    col_a, col_b = st.columns(2)
    with col_a:
        radius_mi = st.slider(
            "Within this distance of you",
            min_value=0.25,
            max_value=2.0,
            value=1.0,
            step=0.25,
            format="%.2f mi",
            key="plan_radius_mi",
        )
    with col_b:
        max_walk = st.slider(
            "Max walk between stops",
            min_value=5,
            max_value=25,
            value=15,
            step=5,
            format="%d min",
            key="plan_max_walk",
        )

    ors_key = get_ors_api_key()
    if ors_key:
        st.caption("Walk times via OpenRouteService when available.")
    else:
        st.caption("Walk times estimated. Add `ors_api_key` to secrets for ORS routing.")

    try:
        rating_stats = fetch_community_ratings(borough)
    except Exception as exc:
        show_data_error(exc)
        return

    if st.button("Find a date", type="primary", use_container_width=True):
        with st.spinner("Finding a date near you…"):
            try:
                nearby = _build_nearby_venue_pool(
                    borough=borough,
                    combo=combo,
                    location=location,
                    radius_mi=radius_mi,
                )
                if not nearby:
                    st.warning(
                        f"No venues within {radius_mi:.2f} mi. "
                        "Try a larger radius or move your pin."
                    )
                    st.session_state.pop("date_draft", None)
                    return

                pool = find_date_plans(
                    nearby,
                    combo,
                    max_walk_minutes=float(max_walk),
                    ors_api_key=ors_key,
                    rating_stats=rating_stats,
                    max_results=30,
                )
                if not pool:
                    st.warning(
                        "No walkable pairs found. Widen radius or allow a longer walk."
                    )
                    st.session_state.pop("date_draft", None)
                    return

                draft = pick_random_plan(pool, rating_stats)
                st.session_state["date_plans_pool"] = pool
                st.session_state["date_nearby_venues"] = nearby
                st.session_state["date_plan_rating_stats"] = rating_stats
                st.session_state["date_draft"] = draft
                st.session_state["date_draft_borough"] = borough
                st.session_state["date_draft_combo_id"] = combo.id
            except Exception as exc:
                st.error(f"Could not build date: {exc}")
                return

    draft: DatePlan | None = st.session_state.get("date_draft")
    if draft:
        draft_combo = combo_by_id(st.session_state.get("date_draft_combo_id", combo_id)) or combo
        draft_borough = st.session_state.get("date_draft_borough", borough)
        stats: RatingLookup = st.session_state.get("date_plan_rating_stats") or rating_stats
        render_date_draft_editor(
            email=email,
            borough=draft_borough,
            combo=draft_combo,
            rating_stats=stats,
            ors_key=ors_key,
        )
    elif "date_plans_pool" in st.session_state:
        st.warning("No date in your pool matched those filters.")

    render_planned_dates_list(email)


def render_login() -> None:
    render_apres_header("Rate the coast.")
    st.markdown(
        '<p class="apres-sub">venue ratings &middot; pick a neighborhood in Discover</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="login-panel">
            <p>Swipe through local spots you've tried. Skip anything you haven't visited yet -
            you can always come back and rate it later.</p>
            <p style="margin-top:0.75rem;font-size:12px;color:var(--text-light);">
            Your email saves your personal ratings. No account needed beyond this screen.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("login_form", clear_on_submit=False):
        email_raw = st.text_input("Email", placeholder="you@example.com")
        submitted = st.form_submit_button("Continue", use_container_width=True)

    if submitted:
        email = normalize_email(email_raw)
        if not is_valid_email(email):
            st.error("Enter a valid email address.")
            return
        st.session_state["user_email"] = email
        clear_discover_venue()
        st.rerun()


def render_venue_card(venue: dict[str, Any]) -> None:
    name = venue.get("PLACE_NAME") or "Unknown venue"
    address = venue.get("SHORT_FORMATTED_ADDRESS") or venue.get("FORMATTED_ADDRESS") or ""
    category = (venue.get("VENUE_CATEGORY") or venue.get("PRIMARY_TYPE") or "venue").replace("_", " ").title()
    primary = (venue.get("PRIMARY_TYPE") or "").replace("_", " ")
    price = format_price_level(venue.get("PRICE_LEVEL"))
    website = venue.get("WEBSITE_URI") or ""

    meta_parts = [p for p in [primary, address.split(",")[0] if address else ""] if p]
    meta_line = " &middot; ".join(meta_parts[:2]) if meta_parts else address

    pills = f"<span>{category}</span>"
    if price:
        pills += f"<span>{price}</span>"

    footer_html = ""
    if website:
        footer_html = (
            f'<div class="date-card-footer">'
            f'<a href="{website}" target="_blank">Website</a></div>'
        )

    st.markdown(
        f"""
        <div class="date-card">
            <div class="date-card-label">Up next</div>
            <div class="date-card-title">{name}</div>
            <div class="date-card-meta">{meta_line}</div>
            <div class="date-card-pills">{pills}</div>
            {footer_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_discover(email: str) -> None:
    try:
        boroughs = fetch_boroughs()
    except Exception as exc:
        show_data_error(exc)
        return

    if not boroughs:
        st.warning("No discoverable locations in the venue catalog yet.")
        return

    if DISCOVER_BOROUGH_KEY not in st.session_state:
        st.session_state[DISCOVER_BOROUGH_KEY] = (
            DEFAULT_BOROUGH if DEFAULT_BOROUGH in boroughs else boroughs[0]
        )
    if st.session_state[DISCOVER_BOROUGH_KEY] not in boroughs:
        st.session_state[DISCOVER_BOROUGH_KEY] = boroughs[0]

    borough = st.selectbox("Location", boroughs, key=DISCOVER_BOROUGH_KEY)

    try:
        stats = fetch_stats(email, borough)
    except Exception as exc:
        show_data_error(exc)
        return

    st.markdown('<div class="section-label">Discover</div>', unsafe_allow_html=True)
    render_progress(stats)

    venue = get_discover_venue(email, borough)
    if not venue:
        st.markdown(
            f"""
            <div class="login-panel">
                <p>You're caught up - no unrated venues left in <strong>{borough}</strong>.
                Pick another location above, or check <strong>My ratings</strong> /
                <strong>Skipped</strong> for places you've already seen.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    render_venue_card(venue)
    st.markdown(
        '<p class="swipe-hint">Skip if you haven\'t been &middot; Rate with half-stars if you have</p>',
        unsafe_allow_html=True,
    )

    place_id = venue["GOOGLE_PLACE_ID"]
    place_name = venue["PLACE_NAME"] or "Unknown venue"
    rating_key = f"rating_{place_id}"
    if rating_key not in st.session_state:
        st.session_state[rating_key] = 3.0

    st.slider(
        "Your rating",
        min_value=0.0,
        max_value=5.0,
        step=0.5,
        format="%.1f ★",
        key=rating_key,
    )
    st.markdown(
        f'<div class="stars-preview">{stars_text(st.session_state[rating_key])}</div>',
        unsafe_allow_html=True,
    )

    col_skip, col_rate = st.columns(2)
    with col_skip:
        if st.button("Skip", use_container_width=True, type="secondary"):
            save_rating(
                email=email,
                borough=borough,
                google_place_id=place_id,
                place_name=place_name,
                status="skipped",
                rating=None,
            )
            st.toast("Skipped - find it again under Skipped.")
            st.rerun()

    with col_rate:
        if st.button("Save rating", use_container_width=True, type="primary"):
            saved_rating = float(st.session_state[rating_key])
            save_rating(
                email=email,
                borough=borough,
                google_place_id=place_id,
                place_name=place_name,
                status="rated",
                rating=saved_rating,
            )
            st.toast(f"Saved {saved_rating:.1f}★ for {place_name}")
            st.rerun()


def verify_data_access() -> bool:
    """One lightweight read before rendering tabs."""
    try:
        run_query(f"select 1 from {dim_places_table()} limit 1")
        return True
    except Exception as exc:
        show_data_error(exc)
        return False


def render_rated_list(email: str) -> None:
    try:
        rows = fetch_user_ratings(email, status="rated")
    except Exception as exc:
        show_data_error(exc)
        return
    st.markdown('<div class="section-label">Your ratings</div>', unsafe_allow_html=True)
    if not rows:
        st.markdown(
            '<div class="login-panel"><p>No ratings yet. Head to <strong>Discover</strong> to rate your first spot.</p></div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        '<p class="swipe-hint">Adjust a score below and tap Update rating to save changes.</p>',
        unsafe_allow_html=True,
    )

    for row in rows:
        category = (row.get("VENUE_CATEGORY") or row.get("PRIMARY_TYPE") or "").replace("_", " ")
        address = row.get("FORMATTED_ADDRESS") or ""
        location = row.get("BOROUGH") or ""
        place_id = row["GOOGLE_PLACE_ID"]
        rating_key = f"edit_rate_{place_id}"
        current_rating = float(row["RATING"])
        if rating_key not in st.session_state:
            st.session_state[rating_key] = current_rating

        meta = " &middot; ".join(p for p in [location, category, address] if p)

        st.markdown(
            f"""
            <div class="bucket-card">
                <div class="bucket-title">{row['PLACE_NAME']}</div>
                <div class="bucket-sub">{meta}</div>
                <div class="bucket-score">
                    <span class="bucket-score-num">{current_rating:.1f}</span>
                    <span>{stars_text(current_rating)} saved</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.slider(
            "Your rating",
            min_value=0.0,
            max_value=5.0,
            step=0.5,
            format="%.1f ★",
            key=rating_key,
        )
        st.markdown(
            f'<div class="stars-preview">{stars_text(float(st.session_state[rating_key]))}</div>',
            unsafe_allow_html=True,
        )
        if st.button("Update rating", key=f"update_{place_id}", type="primary", use_container_width=True):
            updated = float(st.session_state[rating_key])
            save_rating(
                email=email,
                borough=row.get("BOROUGH") or DEFAULT_BOROUGH,
                google_place_id=place_id,
                place_name=row["PLACE_NAME"] or "Unknown venue",
                status="rated",
                rating=updated,
            )
            st.toast(f"Updated to {updated:.1f}★")
            st.rerun()


def render_skipped_list(email: str) -> None:
    try:
        rows = fetch_user_ratings(email, status="skipped")
    except Exception as exc:
        show_data_error(exc)
        return
    st.markdown('<div class="section-label">Skipped &middot; not visited yet</div>', unsafe_allow_html=True)
    if not rows:
        st.markdown(
            '<div class="login-panel"><p>No skipped venues. Use <strong>Discover</strong> to browse new places.</p></div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        '<p class="swipe-hint">Been somewhere you skipped? Rate it when you\'re ready.</p>',
        unsafe_allow_html=True,
    )

    for row in rows:
        address = row.get("FORMATTED_ADDRESS") or ""
        location = row.get("BOROUGH") or ""
        place_id = row["GOOGLE_PLACE_ID"]
        rating_key = f"skip_rate_{place_id}"
        if rating_key not in st.session_state:
            st.session_state[rating_key] = 3.0

        meta = " &middot; ".join(p for p in [location, address] if p)

        st.markdown(
            f"""
            <div class="bucket-card">
                <div class="bucket-icon-skip">&rarr;</div>
                <div class="bucket-title">{row['PLACE_NAME']}</div>
                <div class="bucket-sub">{meta}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        score = st.slider(
            "Your rating",
            min_value=0.0,
            max_value=5.0,
            step=0.5,
            format="%.1f ★",
            key=rating_key,
        )
        st.markdown(
            f'<div class="stars-preview">{stars_text(float(score))}</div>',
            unsafe_allow_html=True,
        )
        if st.button("Save rating", key=f"save_{place_id}", type="primary", use_container_width=True):
            save_rating(
                email=email,
                borough=row.get("BOROUGH") or DEFAULT_BOROUGH,
                google_place_id=place_id,
                place_name=row["PLACE_NAME"] or "Unknown venue",
                status="rated",
                rating=float(score),
            )
            st.toast("Rating saved!")
            st.rerun()


def main() -> None:
    inject_styles()

    if "user_email" not in st.session_state:
        render_login()
        return

    email = st.session_state["user_email"]
    display_name = email.split("@")[0].replace(".", " ").title()

    render_apres_header(f"Good evening, {display_name}.")
    st.markdown(
        f'<p class="apres-sub">signed in as {email}</p>',
        unsafe_allow_html=True,
    )

    _, sign_out_col = st.columns([4, 1])
    with sign_out_col:
        if st.button("Sign out", type="secondary", use_container_width=True):
            clear_discover_venue()
            del st.session_state["user_email"]
            st.rerun()

    if not verify_data_access():
        return

    tab_discover, tab_plan, tab_rated, tab_skipped = st.tabs(
        ["Discover", "Plan a date", "My ratings", "Skipped"]
    )

    with tab_discover:
        render_discover(email)

    with tab_plan:
        render_plan_date(email)

    with tab_rated:
        render_rated_list(email)

    with tab_skipped:
        render_skipped_list(email)


if __name__ == "__main__":
    main()
