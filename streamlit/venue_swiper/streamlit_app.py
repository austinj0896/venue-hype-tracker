"""
Après — discover and rate food & drink spots by neighborhood.
Tagline: Find what comes next.

Runs on **Neon Postgres** (Streamlit Community Cloud) or **Snowflake** (SiS / legacy Cloud).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, time, timedelta
from html import escape
from pathlib import Path
from typing import Any

# Streamlit Cloud can resolve sibling imports from site-packages first;
# keep this app directory at the front of sys.path.
_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import streamlit as st

from db import (
    backend,
    clear_db_caches,
    fetch_db_identity,
    places_table as dim_places_table,
    ratings_table,
    run_query,
    upsert_rating,
    venue_hours_table,
    venue_tags_table,
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
from app_log import log_event, show_recent_errors
from brand import brand_mark_html
from greeting import personalized_greeting
from onboarding import onboarding_complete, render_onboarding
from places_data import fetch_community_ratings, fetch_venues_with_coords
from profile_options import preferred_types_from_activities
from profile_setup import render_profile_settings, render_profile_setup
from user_profiles_store import (
    fetch_profile,
    fetch_profile_photo,
    is_profile_complete,
    photo_data_uri,
)
from planned_dates_store import fetch_planned_dates, save_planned_date

DEFAULT_BOROUGH = "Manhattan Beach"
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
DISCOVER_BOROUGH_KEY = "discover_borough"
FEEDBACK_KEY = "apres_action_feedback"
SESSION_RATINGS_KEY = "session_ratings"
SESSION_SKIPS_KEY = "session_skips"
WELCOME_FLAG_KEY = "just_completed_profile"
WELCOME_NAME_KEY = "just_completed_profile_name"


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

FONT_SERIF = "'Cormorant Garamond', Georgia, 'Times New Roman', serif"
FONT_DISPLAY = "'Bodoni Moda', 'Cormorant Garamond', Georgia, serif"
FONT_SANS = "'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
FONT_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Bodoni+Moda:ital,opsz,wght@0,6..96,400;0,6..96,500;0,6..96,600;1,6..96,400;1,6..96,500&"
    "family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&"
    "family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,400&"
    "display=swap"
)

# SiS strips <link> tags and often breaks <style> inside st.markdown — inject via iframe + markdown.
APRES_CSS = f"""
@import url('{FONT_URL}');
:root {{
    --cream: #F8E6D2;
    --cream-deep: #F0D7BC;
    --cream-soft: #FBF1E6;
    --surface: rgba(255, 252, 247, 0.82);
    --surface-solid: #FFFCF7;
    --brown: #704D3B;
    --gold: #D3A345;
    --steel: #7897A3;
    --sage: #B6BEB1;
    --text-dark: #2C1A10;
    --text-mid: #7A5B48;
    --text-light: #B09080;
    --hairline: rgba(112, 77, 59, 0.12);
    --hairline-strong: rgba(112, 77, 59, 0.18);
    --shadow-sm: 0 1px 2px rgba(44, 26, 16, 0.04), 0 4px 12px rgba(44, 26, 16, 0.05);
    --shadow-md: 0 2px 4px rgba(44, 26, 16, 0.04), 0 12px 28px rgba(44, 26, 16, 0.08);
    --shadow-lg: 0 4px 8px rgba(44, 26, 16, 0.05), 0 24px 48px rgba(44, 26, 16, 0.12);
    --radius-sm: 10px;
    --radius-md: 14px;
    --radius-lg: 20px;
    --space-1: 0.25rem;
    --space-2: 0.5rem;
    --space-3: 0.75rem;
    --space-4: 1rem;
    --space-5: 1.25rem;
    --space-6: 1.5rem;
    --space-8: 2rem;
    --ease-out: cubic-bezier(0.22, 1, 0.36, 1);
    --ease-inout: cubic-bezier(0.45, 0, 0.55, 1);
    --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
    --dur-fast: 160ms;
    --dur: 280ms;
    --dur-slow: 520ms;
}}
html, body, [class*="css"] {{
    font-family: {FONT_SANS};
    color: var(--text-dark);
    font-size: 16px;
    line-height: 1.45;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    text-rendering: optimizeLegibility;
    -webkit-tap-highlight-color: rgba(211, 163, 69, 0.18);
}}
.stApp {{
    background:
        radial-gradient(120% 80% at 100% -10%, rgba(211, 163, 69, 0.14) 0%, transparent 52%),
        radial-gradient(90% 60% at -10% 100%, rgba(112, 77, 59, 0.08) 0%, transparent 48%),
        linear-gradient(180deg, var(--cream-soft) 0%, var(--cream) 42%, var(--cream-deep) 100%);
    background-attachment: fixed;
}}
.block-container {{
    padding-top: calc(var(--space-5) + env(safe-area-inset-top, 0px));
    padding-bottom: calc(5.5rem + env(safe-area-inset-bottom, 0px));
    padding-left: calc(1rem + env(safe-area-inset-left, 0px));
    padding-right: calc(1rem + env(safe-area-inset-right, 0px));
    max-width: 480px;
    animation: apres-page-in var(--dur-slow) var(--ease-out) both;
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
    letter-spacing: -0.01em;
}}
.apres-status {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.75rem;
    font-size: 11px;
    font-weight: 500;
    color: var(--brown);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: var(--space-4);
    animation: apres-fade-up var(--dur-slow) var(--ease-out) both;
}}
.apres-status .tagline {{
    font-family: {FONT_SERIF};
    font-size: 14px;
    font-style: italic;
    font-weight: 400;
    letter-spacing: 0.01em;
    text-transform: none;
    color: var(--text-mid);
    flex: 1;
    text-align: right;
    min-width: 0;
}}
.apres-brand-header {{
    height: 34px;
    width: auto;
    max-width: min(46vw, 168px);
    object-fit: contain;
    object-position: left center;
    display: block;
    flex-shrink: 0;
}}
.apres-brand-hero {{
    width: min(88%, 240px);
    height: auto;
    display: block;
    margin: 0 auto 0.9rem;
    transform: translateX(4%);
}}
.apres-brand-text {{
    font-family: {FONT_DISPLAY};
    font-weight: 500;
    font-style: italic;
    letter-spacing: -0.02em;
    background: linear-gradient(
        180deg,
        #F8F0E0 0%,
        #E8D4A8 28%,
        #D3A345 55%,
        #A67C3A 78%,
        #C9A46A 100%
    );
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
    -webkit-text-fill-color: transparent;
    text-shadow: none;
    filter: drop-shadow(0 2px 8px rgba(44, 26, 16, 0.25));
}}
.apres-status .apres-brand-text {{
    font-size: 22px;
    line-height: 1;
}}
.apres-greeting {{
    font-family: {FONT_SERIF};
    font-size: clamp(28px, 7vw, 34px);
    font-weight: 400;
    font-style: italic;
    color: var(--brown);
    line-height: 1.18;
    letter-spacing: -0.015em;
    margin: 0 0 var(--space-1) 0;
    animation: apres-fade-up var(--dur-slow) var(--ease-out) 0.06s both;
}}
.apres-avatar {{
    width: 56px;
    height: 56px;
    border-radius: 50%;
    object-fit: cover;
    border: 1.5px solid rgba(211, 163, 69, 0.55);
    box-shadow: var(--shadow-sm), 0 0 0 4px rgba(248, 230, 210, 0.65);
    flex-shrink: 0;
    transition: transform var(--dur) var(--ease-spring), box-shadow var(--dur) var(--ease-inout);
}}
.apres-avatar:hover {{
    transform: scale(1.04);
    box-shadow: var(--shadow-md), 0 0 0 5px rgba(211, 163, 69, 0.18);
}}
.apres-greeting-row {{
    display: flex;
    align-items: center;
    gap: 0.9rem;
    margin: 0 0 var(--space-1) 0;
    animation: apres-fade-up var(--dur-slow) var(--ease-out) 0.06s both;
}}
.apres-greeting-row .apres-greeting {{
    margin: 0;
    animation: none;
}}
.apres-sub {{
    font-size: 11px;
    color: var(--text-light);
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: var(--space-5);
    animation: apres-fade-up var(--dur-slow) var(--ease-out) 0.1s both;
}}
.section-label {{
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--text-light);
    margin: var(--space-5) 0 var(--space-3);
}}
.date-card {{
    background:
        linear-gradient(165deg, rgba(211,163,69,0.14) 0%, transparent 36%),
        linear-gradient(180deg, #7A5643 0%, var(--brown) 55%, #5E3F31 100%);
    border-radius: var(--radius-lg);
    border: 1px solid rgba(248, 230, 210, 0.08);
    padding: 1.45rem 1.3rem 1.25rem;
    position: relative;
    overflow: hidden;
    margin-bottom: var(--space-3);
    min-height: 280px;
    box-shadow: var(--shadow-lg), inset 0 1px 0 rgba(248, 230, 210, 0.1);
    animation: apres-card-in var(--dur-slow) var(--ease-out) both;
    transform: translateZ(0);
    will-change: transform, opacity;
}}
.date-card::before {{
    content: '';
    position: absolute;
    top: -48px; right: -36px;
    width: 160px; height: 160px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(211,163,69,0.22) 0%, transparent 68%);
    pointer-events: none;
}}
.date-card::after {{
    content: '';
    position: absolute;
    bottom: -28px; left: 28px;
    width: 110px; height: 110px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(248,230,210,0.08) 0%, transparent 70%);
    pointer-events: none;
}}
.date-card-label {{
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--sage);
    margin-bottom: var(--space-2);
    position: relative;
}}
.date-card-title {{
    font-family: {FONT_SERIF};
    font-size: clamp(26px, 6.5vw, 30px);
    font-weight: 500;
    color: var(--cream);
    margin-bottom: 0.35rem;
    line-height: 1.12;
    letter-spacing: -0.01em;
    position: relative;
}}
.date-card-meta {{
    font-size: 12.5px;
    line-height: 1.45;
    color: rgba(248,230,210,0.58);
    margin-bottom: var(--space-4);
    position: relative;
}}
.date-card-pills {{
    position: relative;
    margin-bottom: var(--space-3);
}}
.date-card-pills span {{
    display: inline-block;
    background: rgba(248,230,210,0.1);
    border: 1px solid rgba(248,230,210,0.16);
    border-radius: 999px;
    padding: 0.28rem 0.65rem;
    margin: 0.15rem 0.35rem 0.15rem 0;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--sage);
    transition: background var(--dur-fast) var(--ease-inout), border-color var(--dur-fast) var(--ease-inout);
}}
.vibe-rail {{
    position: relative;
    margin: 0.15rem 0 var(--space-4);
    padding-top: 0.65rem;
}}
.vibe-rail::before {{
    content: '';
    position: absolute;
    left: 0;
    right: 0;
    top: 0;
    height: 1px;
    background: linear-gradient(
        90deg,
        transparent 0%,
        rgba(211,163,69,0.55) 18%,
        rgba(248,230,210,0.35) 52%,
        rgba(211,163,69,0.45) 82%,
        transparent 100%
    );
    pointer-events: none;
}}
.vibe-rail-label {{
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 9px;
    font-weight: 500;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--gold);
    margin-bottom: 0.55rem;
}}
.vibe-rail-label::after {{
    content: '';
    display: inline-block;
    width: 18px;
    height: 1px;
    background: var(--gold);
    opacity: 0.7;
}}
.vibe-tags {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    overflow: visible;
    padding-top: 0.25rem;
}}
.vibe-tag {{
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    position: relative;
    padding: 0.38rem 0.72rem 0.4rem;
    border-radius: 999px 999px 999px 10px;
    font-family: {FONT_SERIF};
    font-style: italic;
    font-size: 13px;
    line-height: 1.1;
    color: var(--cream);
    cursor: default;
    background:
        linear-gradient(145deg, rgba(211,163,69,0.42) 0%, rgba(211,163,69,0.14) 55%, rgba(248,230,210,0.08) 100%);
    border: 1px solid rgba(211,163,69,0.62);
    box-shadow:
        inset 0 1px 0 rgba(248,230,210,0.18),
        0 6px 16px rgba(44,26,16,0.22);
    animation: vibe-rise 0.55s var(--ease-out) both;
    transform-origin: left center;
    transition:
        transform var(--dur) var(--ease-spring),
        box-shadow var(--dur) var(--ease-inout),
        border-color var(--dur) var(--ease-inout),
        background var(--dur) var(--ease-inout),
        color var(--dur) var(--ease-inout);
    z-index: 1;
}}
.vibe-tag::before {{
    content: '';
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--gold);
    box-shadow: 0 0 8px rgba(211,163,69,0.85);
    flex-shrink: 0;
    transition: transform var(--dur) var(--ease-spring), box-shadow var(--dur) var(--ease-inout);
}}
.vibe-tag:hover,
.vibe-tag:focus-visible {{
    transform: translateY(-3px) scale(1.05);
    z-index: 20;
    border-color: rgba(248,230,210,0.75);
    color: #FFF8EE;
    background:
        linear-gradient(145deg, rgba(211,163,69,0.78) 0%, rgba(211,163,69,0.38) 48%, rgba(248,230,210,0.14) 100%);
    box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.22),
        0 10px 28px rgba(44,26,16,0.38),
        0 0 0 1px rgba(211,163,69,0.35),
        0 0 22px rgba(211,163,69,0.45);
}}
.vibe-tag:hover::before,
.vibe-tag:focus-visible::before {{
    transform: scale(1.35);
    box-shadow: 0 0 14px rgba(211,163,69,1);
}}
.vibe-tag-hot {{
    background:
        linear-gradient(145deg, rgba(211,163,69,0.72) 0%, rgba(211,163,69,0.28) 60%, rgba(112,77,59,0.35) 100%);
    border-color: rgba(248,230,210,0.42);
    color: #FFF8EE;
}}
.vibe-tag-hot:hover,
.vibe-tag-hot:focus-visible {{
    background:
        linear-gradient(145deg, rgba(248,230,210,0.35) 0%, rgba(211,163,69,0.72) 42%, rgba(211,163,69,0.38) 100%);
    box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.28),
        0 12px 32px rgba(44,26,16,0.42),
        0 0 0 1px rgba(248,230,210,0.25),
        0 0 28px rgba(211,163,69,0.62);
}}
.vibe-tag:nth-child(1) {{ animation-delay: 0.04s; }}
.vibe-tag:nth-child(2) {{ animation-delay: 0.09s; }}
.vibe-tag:nth-child(3) {{ animation-delay: 0.14s; }}
.vibe-tag:nth-child(4) {{ animation-delay: 0.19s; }}
.vibe-tag:nth-child(5) {{ animation-delay: 0.24s; }}
.vibe-tag:nth-child(6) {{ animation-delay: 0.29s; }}
.vibe-tag:nth-child(7) {{ animation-delay: 0.34s; }}
.vibe-tag:nth-child(8) {{ animation-delay: 0.39s; }}
@keyframes vibe-rise {{
    from {{
        opacity: 0;
        transform: translateY(10px) scale(0.94);
        filter: blur(2px);
    }}
    to {{
        opacity: 1;
        transform: translateY(0) scale(1);
        filter: none;
    }}
}}
@keyframes apres-fade-up {{
    from {{ opacity: 0; transform: translateY(10px); }}
    to {{ opacity: 1; transform: translateY(0); }}
}}
@keyframes apres-page-in {{
    from {{ opacity: 0; transform: translateY(6px); }}
    to {{ opacity: 1; transform: translateY(0); }}
}}
@keyframes apres-card-in {{
    from {{
        opacity: 0;
        transform: translateY(16px) scale(0.985);
        filter: blur(3px);
    }}
    to {{
        opacity: 1;
        transform: translateY(0) scale(1);
        filter: none;
    }}
}}
@keyframes apres-shimmer {{
    0% {{ background-position: 200% 0; }}
    100% {{ background-position: -200% 0; }}
}}
@keyframes apres-bar-fill {{
    from {{ transform: scaleX(0); }}
    to {{ transform: scaleX(1); }}
}}
.vibe-empty {{
    font-family: {FONT_SERIF};
    font-size: 13px;
    font-style: italic;
    color: rgba(248,230,210,0.42);
    letter-spacing: 0.02em;
}}
.hours-rail {{
    position: relative;
    margin: 0 0 0.9rem;
    padding: 0.65rem 0.8rem 0.7rem;
    border-radius: var(--radius-sm);
    background: rgba(248,230,210,0.06);
    border: 1px solid rgba(211,163,69,0.2);
    backdrop-filter: blur(6px);
}}
.hours-rail-label {{
    font-size: 9px;
    font-weight: 500;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--gold);
    margin-bottom: 0.35rem;
}}
.hours-today {{
    font-size: 13px;
    color: var(--cream);
    margin-bottom: 0.35rem;
    letter-spacing: 0.02em;
}}
.hours-today strong {{
    color: var(--gold);
    font-weight: 500;
}}
.hours-week {{
    font-size: 11px;
    line-height: 1.5;
    color: rgba(248,230,210,0.55);
    white-space: pre-line;
}}
.date-card-footer {{
    font-size: 12px;
    color: rgba(248,230,210,0.75);
    border-left: 2px solid var(--gold);
    padding-left: 10px;
    font-style: italic;
    line-height: 1.5;
    position: relative;
    z-index: 3;
}}
.date-card-footer a {{
    color: var(--gold);
    text-decoration: none;
    position: relative;
    z-index: 3;
    cursor: pointer;
    transition: color var(--dur-fast) var(--ease-inout);
}}
.date-card-footer a:hover {{
    color: #F8E6D2;
}}
.swipe-hint {{
    text-align: center;
    color: var(--text-light);
    font-size: 12px;
    letter-spacing: 0.05em;
    line-height: 1.5;
    margin: var(--space-2) 0 var(--space-4);
}}
.progress-track {{
    width: 100%;
    background: rgba(112,77,59,0.1);
    border-radius: 999px;
    height: 4px;
    overflow: hidden;
    margin: 0.25rem 0 var(--space-5);
    box-shadow: inset 0 1px 1px rgba(44, 26, 16, 0.04);
}}
.progress-bar {{
    height: 100%;
    transform-origin: left center;
    background:
        linear-gradient(90deg, #C4923A 0%, var(--gold) 45%, #E0B85C 100%);
    background-size: 200% 100%;
    border-radius: 999px;
    animation:
        apres-bar-fill var(--dur-slow) var(--ease-out) both,
        apres-shimmer 2.8s var(--ease-inout) 0.6s infinite;
}}
.progress-caption {{
    font-size: 11px;
    color: var(--text-light);
    letter-spacing: 0.08em;
    margin-bottom: 0.4rem;
}}
.login-panel,
.empty-state {{
    background: var(--surface);
    backdrop-filter: blur(14px) saturate(1.1);
    -webkit-backdrop-filter: blur(14px) saturate(1.1);
    border-radius: var(--radius-lg);
    border: 1px solid var(--hairline);
    box-shadow: var(--shadow-sm);
    padding: 1.4rem 1.2rem;
    margin: var(--space-3) 0 var(--space-4);
    animation: apres-fade-up var(--dur-slow) var(--ease-out) both;
}}
.login-panel p,
.empty-state p {{
    font-size: 14px;
    color: var(--text-mid);
    line-height: 1.65;
    margin: 0;
}}
.empty-state-eyebrow {{
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--gold);
    margin: 0 0 var(--space-2);
}}
.empty-state-title {{
    font-family: {FONT_SERIF};
    font-size: 24px;
    font-weight: 500;
    font-style: italic;
    color: var(--brown);
    line-height: 1.2;
    margin: 0 0 var(--space-2);
}}
.empty-state-mark {{
    width: 36px;
    height: 3px;
    border-radius: 999px;
    background: linear-gradient(90deg, var(--gold), transparent);
    margin: 0 0 var(--space-3);
}}
.empty-state-action {{
    display: block;
    margin-top: var(--space-4);
    font-size: 13px;
    font-weight: 500;
    letter-spacing: 0.04em;
    color: var(--brown);
}}
.empty-state-action span {{
    color: var(--gold);
}}
.bucket-card {{
    background: var(--surface-solid);
    border-radius: var(--radius-md);
    border: 1px solid var(--hairline);
    box-shadow: var(--shadow-sm);
    padding: 1.05rem 1.15rem;
    margin-bottom: 0.75rem;
    transition:
        transform var(--dur) var(--ease-out),
        box-shadow var(--dur) var(--ease-inout),
        border-color var(--dur) var(--ease-inout);
    animation: apres-fade-up var(--dur-slow) var(--ease-out) both;
}}
.bucket-card:hover {{
    transform: translateY(-2px);
    box-shadow: var(--shadow-md);
    border-color: rgba(211, 163, 69, 0.28);
}}
.bucket-title {{
    font-family: {FONT_SERIF};
    font-size: 21px;
    font-weight: 500;
    color: var(--brown);
    margin-bottom: 0.2rem;
    letter-spacing: -0.01em;
    line-height: 1.2;
}}
.bucket-sub {{
    font-size: 12px;
    line-height: 1.45;
    color: var(--text-light);
    margin-bottom: 0.55rem;
}}
.bucket-score {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(211,163,69,0.12);
    border: 1px solid rgba(211,163,69,0.28);
    border-radius: 999px;
    padding: 0.35rem 0.85rem;
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
    border-radius: var(--radius-sm);
    background: rgba(120,151,163,0.14);
    color: var(--steel);
    font-size: 14px;
    margin-bottom: var(--space-2);
}}
.date-plan-card {{
    background: var(--surface-solid);
    border-radius: var(--radius-md);
    border: 1px solid var(--hairline);
    box-shadow: var(--shadow-sm);
    padding: 1rem 1.1rem;
    margin-bottom: 0.85rem;
    transition: box-shadow var(--dur) var(--ease-inout), transform var(--dur) var(--ease-out);
    animation: apres-fade-up var(--dur-slow) var(--ease-out) both;
}}
.date-plan-card:hover {{
    box-shadow: var(--shadow-md);
    transform: translateY(-1px);
}}
.date-plan-header {{
    font-family: {FONT_SERIF};
    font-size: 19px;
    font-weight: 500;
    color: var(--brown);
    margin-bottom: 0.75rem;
    letter-spacing: -0.01em;
}}
.date-plan-stop {{
    padding: 0.7rem 0;
    border-bottom: 1px solid rgba(112,77,59,0.08);
}}
.date-plan-stop:last-of-type {{
    border-bottom: none;
}}
.date-plan-stop-num {{
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--gold);
    margin-bottom: 0.2rem;
}}
.date-plan-stop-name {{
    font-family: {FONT_SERIF};
    font-size: 17px;
    color: var(--brown);
    line-height: 1.25;
}}
.date-plan-stop-meta {{
    font-size: 11px;
    line-height: 1.45;
    color: var(--text-light);
}}
.date-plan-walk {{
    text-align: center;
    font-size: 12px;
    color: var(--steel);
    padding: 0.65rem 0;
    letter-spacing: 0.04em;
}}
.date-plan-walk-time {{
    font-weight: 600;
    color: var(--brown);
}}
.location-mode-row div[data-testid="stRadio"] > div {{
    flex-direction: row;
    flex-wrap: wrap;
    gap: 0.5rem;
}}
.location-mode-row div[data-testid="stRadio"] label {{
    background: var(--surface-solid);
    border: 1px solid var(--hairline);
    border-radius: 999px;
    min-height: 44px;
    padding: 0.65rem 1.1rem !important;
    font-size: 14px !important;
    letter-spacing: 0.03em;
    text-transform: none !important;
    color: var(--text-mid) !important;
    box-shadow: var(--shadow-sm);
    display: inline-flex !important;
    align-items: center;
    transition:
        background var(--dur) var(--ease-inout),
        color var(--dur) var(--ease-inout),
        border-color var(--dur) var(--ease-inout),
        transform var(--dur-fast) var(--ease-spring);
}}
.location-mode-row div[data-testid="stRadio"] label:hover {{
    border-color: rgba(211, 163, 69, 0.35);
}}
.location-mode-row div[data-testid="stRadio"] label:active {{
    transform: scale(0.98);
}}
.location-mode-row div[data-testid="stRadio"] label[data-checked="true"] {{
    background: var(--brown);
    border-color: var(--brown);
    color: var(--cream) !important;
}}
.location-set-pill {{
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    background: var(--surface);
    backdrop-filter: blur(10px);
    border: 1px solid var(--hairline);
    border-radius: 999px;
    padding: 0.5rem 0.95rem;
    font-size: 12px;
    color: var(--text-mid);
    letter-spacing: 0.03em;
    margin: 0.15rem 0 0.9rem;
    box-shadow: var(--shadow-sm);
}}
.location-set-pill strong {{
    color: var(--brown);
    font-weight: 500;
}}
.location-set-dot {{
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--gold);
    display: inline-block;
    box-shadow: 0 0 0 3px rgba(211, 163, 69, 0.18);
}}
iframe[title="streamlit_folium.streamlit_folium"] {{
    border-radius: var(--radius-md) !important;
    border: 1px solid var(--hairline) !important;
    box-shadow: var(--shadow-md);
}}
iframe[title="apres_geolocation.apres_geolocation"] {{
    min-height: 64px !important;
    height: 64px !important;
    width: 100% !important;
    border-radius: var(--radius-sm) !important;
    border: none !important;
    background: transparent !important;
    display: block !important;
}}
.stars-preview {{
    font-family: {FONT_SERIF};
    font-size: 26px;
    color: var(--gold);
    letter-spacing: 0.1em;
    text-align: center;
    margin: 0.2rem 0 0.85rem;
    transition: transform var(--dur-fast) var(--ease-spring);
}}
div[data-testid="stTabs"] {{
    margin-top: var(--space-2);
}}
div[data-testid="stTabs"] [data-baseweb="tab-list"] {{
    gap: 0.1rem;
    border-bottom: 1px solid var(--hairline);
    padding-bottom: 0;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
}}
div[data-testid="stTabs"] [data-baseweb="tab-list"]::-webkit-scrollbar {{
    display: none;
}}
div[data-testid="stTabs"] button {{
    font-family: {FONT_SANS} !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    letter-spacing: 0.03em !important;
    color: var(--text-light) !important;
    min-height: 44px !important;
    padding: 0.65rem 0.7rem !important;
    transition: color var(--dur) var(--ease-inout) !important;
}}
div[data-testid="stTabs"] button[aria-selected="true"] {{
    color: var(--brown) !important;
}}
div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{
    background-color: var(--gold) !important;
    height: 2px !important;
}}
div[data-testid="stSlider"] label,
div[data-testid="stForm"] label,
div[data-testid="stTextInput"] label,
div[data-testid="stSelectbox"] label,
div[data-testid="stMultiSelect"] label {{
    font-size: 12px !important;
    font-weight: 500 !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
    color: var(--text-light) !important;
}}
div[data-testid="stTextInput"] input,
div[data-testid="stSelectbox"] > div > div,
div[data-testid="stMultiSelect"] > div > div {{
    border-radius: var(--radius-sm) !important;
    border: 1px solid var(--hairline-strong) !important;
    background: var(--surface-solid) !important;
    color: var(--text-dark) !important;
    font-size: 16px !important;
    min-height: 44px !important;
    box-shadow: var(--shadow-sm);
    transition: border-color var(--dur) var(--ease-inout), box-shadow var(--dur) var(--ease-inout) !important;
}}
div[data-testid="stTextInput"] input:focus {{
    border-color: rgba(211, 163, 69, 0.55) !important;
    box-shadow: 0 0 0 3px rgba(211, 163, 69, 0.16) !important;
}}
div[data-testid="stBaseButton-secondary"] button,
div[data-testid="stBaseButton-primary"] button,
div[data-testid="stFormSubmitButton"] button {{
    border-radius: var(--radius-md) !important;
    font-family: {FONT_SANS} !important;
    font-size: 15px !important;
    font-weight: 500 !important;
    letter-spacing: 0.04em !important;
    min-height: 48px !important;
    padding: 0.75rem 1rem !important;
    transition:
        transform var(--dur-fast) var(--ease-spring) !important,
        box-shadow var(--dur) var(--ease-inout) !important,
        background var(--dur) var(--ease-inout) !important,
        border-color var(--dur) var(--ease-inout) !important,
        filter var(--dur-fast) var(--ease-inout) !important;
}}
.apres-action-anchor + div[data-testid="stHorizontalBlock"] {{
    position: sticky;
    bottom: calc(0.5rem + env(safe-area-inset-bottom, 0px));
    z-index: 50;
    gap: 0.65rem !important;
    margin-top: 0.35rem;
    padding: 0.85rem 0.15rem calc(0.35rem + env(safe-area-inset-bottom, 0px));
    background:
        linear-gradient(180deg, rgba(248, 230, 210, 0) 0%, rgba(248, 230, 210, 0.92) 28%, var(--cream) 100%);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
}}
div[data-testid="stBaseButton-secondary"] button {{
    background: rgba(255, 252, 247, 0.55) !important;
    color: var(--text-mid) !important;
    border: 1px solid rgba(112,77,59,0.22) !important;
    backdrop-filter: blur(8px);
    box-shadow: var(--shadow-sm) !important;
}}
div[data-testid="stBaseButton-secondary"] button:hover {{
    border-color: rgba(112,77,59,0.38) !important;
    transform: translateY(-1px) !important;
    box-shadow: var(--shadow-md) !important;
}}
div[data-testid="stBaseButton-secondary"] button:active {{
    transform: translateY(1px) scale(0.985) !important;
}}
div[data-testid="stBaseButton-primary"] button,
div[data-testid="stFormSubmitButton"] button {{
    background: linear-gradient(180deg, #E0B85C 0%, var(--gold) 55%, #C4923A 100%) !important;
    color: var(--brown) !important;
    border: 1px solid rgba(112, 77, 59, 0.08) !important;
    box-shadow: var(--shadow-sm), inset 0 1px 0 rgba(255, 255, 255, 0.28) !important;
}}
div[data-testid="stBaseButton-primary"] button:hover,
div[data-testid="stFormSubmitButton"] button:hover {{
    filter: brightness(1.04);
    transform: translateY(-1px) !important;
    box-shadow: var(--shadow-md), inset 0 1px 0 rgba(255, 255, 255, 0.32) !important;
}}
div[data-testid="stBaseButton-primary"] button:active,
div[data-testid="stFormSubmitButton"] button:active {{
    transform: translateY(1px) scale(0.985) !important;
    filter: brightness(0.98);
}}
div[data-testid="stSlider"] [data-baseweb="slider"] > div > div:nth-child(1) {{
    background: rgba(112,77,59,0.16) !important;
}}
div[data-testid="stSlider"] [data-baseweb="slider"] > div > div:nth-child(2) {{
    background: linear-gradient(90deg, #C4923A, var(--gold)) !important;
}}
div[data-testid="stSlider"] [role="slider"] {{
    background: var(--brown) !important;
    border: 2px solid var(--cream) !important;
    width: 24px !important;
    height: 24px !important;
    box-shadow: 0 2px 8px rgba(44,26,16,0.22) !important;
    transition: transform var(--dur-fast) var(--ease-spring) !important;
}}
div[data-testid="stSlider"] [role="slider"]:active {{
    transform: scale(1.12) !important;
}}
div[data-testid="stSlider"] [data-testid="stThumbValue"] {{
    color: var(--brown) !important;
    font-weight: 600 !important;
}}
.apres-feedback {{
    background: var(--surface);
    backdrop-filter: blur(14px) saturate(1.1);
    -webkit-backdrop-filter: blur(14px) saturate(1.1);
    border-radius: var(--radius-lg);
    border: 1px solid rgba(211, 163, 69, 0.35);
    box-shadow: var(--shadow-md), 0 0 0 1px rgba(211, 163, 69, 0.08);
    padding: 1.05rem 1.15rem 1.1rem;
    margin: 0 0 var(--space-4);
    animation: apres-card-in var(--dur-slow) var(--ease-out) both;
}}
.apres-feedback-eyebrow {{
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--gold);
    margin: 0 0 0.35rem;
}}
.apres-feedback-title {{
    font-family: {FONT_SERIF};
    font-size: 24px;
    font-weight: 500;
    font-style: italic;
    color: var(--brown);
    line-height: 1.2;
    letter-spacing: -0.01em;
    margin: 0 0 0.35rem;
}}
.apres-feedback-body {{
    font-size: 13px;
    line-height: 1.5;
    color: var(--text-mid);
    margin: 0;
}}
.progress-nudge {{
    font-size: 12px;
    color: var(--gold);
    letter-spacing: 0.04em;
    margin: 0.15rem 0 0.55rem;
    font-family: {FONT_SERIF};
    font-style: italic;
}}
.progress-session {{
    font-size: 11px;
    color: var(--text-light);
    letter-spacing: 0.06em;
    margin: 0 0 0.35rem;
}}
.locals-line {{
    position: relative;
    z-index: 2;
    font-size: 12px;
    color: rgba(248, 230, 210, 0.62);
    letter-spacing: 0.03em;
    margin: 0 0 0.85rem;
}}
.locals-line strong {{
    color: var(--gold);
    font-weight: 500;
}}
.apres-welcome {{
    background:
        linear-gradient(165deg, rgba(211,163,69,0.16) 0%, transparent 40%),
        linear-gradient(180deg, #7A5643 0%, var(--brown) 55%, #5E3F31 100%);
    border-radius: var(--radius-lg);
    border: 1px solid rgba(248, 230, 210, 0.08);
    box-shadow: var(--shadow-lg), inset 0 1px 0 rgba(248, 230, 210, 0.1);
    padding: 1.6rem 1.3rem 1.35rem;
    margin: 0.5rem 0 1.25rem;
    animation: apres-card-in var(--dur-slow) var(--ease-out) both;
}}
.apres-welcome-eyebrow {{
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--gold);
    margin: 0 0 0.45rem;
}}
.apres-welcome-title {{
    font-family: {FONT_SERIF};
    font-size: clamp(28px, 7vw, 34px);
    font-weight: 500;
    font-style: italic;
    color: var(--cream);
    line-height: 1.15;
    letter-spacing: -0.015em;
    margin: 0 0 0.45rem;
}}
.apres-welcome-body {{
    font-size: 14px;
    line-height: 1.55;
    color: rgba(248, 230, 210, 0.68);
    margin: 0;
}}
@media (hover: none) {{
    .bucket-card:hover,
    .date-card:hover,
    .date-plan-card:hover {{
        transform: none;
    }}
    div[data-testid="stBaseButton-secondary"] button:hover,
    div[data-testid="stBaseButton-primary"] button:hover,
    div[data-testid="stFormSubmitButton"] button:hover {{
        transform: none !important;
        filter: none;
    }}
}}
@media (min-width: 720px) {{
    .block-container {{
        padding-bottom: calc(var(--space-8) + env(safe-area-inset-bottom, 0px));
    }}
    html, body, [class*="css"] {{
        font-size: 15px;
    }}
}}
@media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
    }}
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
    """Inject Après CSS without st.iframe.

    An empty measuring iframe (height=\"content\") has hung mobile Safari /
    Streamlit Cloud after form submit — keep styles in markdown only.
    """
    st.markdown(
        f'<link rel="stylesheet" href="{FONT_URL}" />'
        f"<style>{APRES_CSS}</style>",
        unsafe_allow_html=True,
    )


def empty_state_html(*, eyebrow: str, title: str, body: str, action: str | None = None) -> str:
    """Designed empty state — single-line HTML for Streamlit markdown safety."""
    action_html = (
        f'<div class="empty-state-action">{action}</div>' if action else ""
    )
    return (
        f'<div class="empty-state">'
        f'<div class="empty-state-eyebrow">{escape(eyebrow)}</div>'
        f'<div class="empty-state-title">{escape(title)}</div>'
        f'<div class="empty-state-mark"></div>'
        f"<p>{body}</p>"
        f"{action_html}"
        f"</div>"
    )


def bump_session_counter(kind: str) -> None:
    key = SESSION_RATINGS_KEY if kind == "rated" else SESSION_SKIPS_KEY
    st.session_state[key] = int(st.session_state.get(key) or 0) + 1


def queue_action_feedback(
    *,
    kind: str,
    place_name: str,
    rating: float | None = None,
) -> None:
    """Persist feedback across the next rerun so the panel is actually visible."""
    name = (place_name or "that spot").strip() or "that spot"
    if kind == "skipped":
        payload = {
            "eyebrow": "Parked for later",
            "title": f"Skipped {name}",
            "body": "Find it again under Skipped when you’ve been.",
        }
    elif kind == "updated":
        stars = f"{rating:.1f}" if rating is not None else ""
        payload = {
            "eyebrow": "Updated",
            "title": f"{stars}★ saved" if stars else "Rating updated",
            "body": f"{name} is on your list.",
        }
    else:
        score = float(rating or 0)
        if score >= 4.5:
            payload = {
                "eyebrow": "A favorite",
                "title": f"{score:.1f}★",
                "body": f"{name} is one of your highs.",
            }
        elif score >= 3.0:
            payload = {
                "eyebrow": "Noted",
                "title": f"{score:.1f}★ saved",
                "body": f"{name} is on your map.",
            }
        else:
            payload = {
                "eyebrow": "Honest take",
                "title": f"{score:.1f}★ logged",
                "body": f"We’ll weigh {name} accordingly.",
            }
    st.session_state[FEEDBACK_KEY] = payload


def render_queued_feedback() -> None:
    payload = st.session_state.pop(FEEDBACK_KEY, None)
    if not isinstance(payload, dict):
        return
    st.markdown(
        f'<div class="apres-feedback">'
        f'<div class="apres-feedback-eyebrow">{escape(str(payload.get("eyebrow") or ""))}</div>'
        f'<div class="apres-feedback-title">{escape(str(payload.get("title") or ""))}</div>'
        f'<p class="apres-feedback-body">{escape(str(payload.get("body") or ""))}</p>'
        f"</div>",
        unsafe_allow_html=True,
    )


def render_profile_welcome() -> bool:
    """One-shot premium welcome after profile setup. Returns True if still showing."""
    if not st.session_state.get(WELCOME_FLAG_KEY):
        return False
    name = (st.session_state.get(WELCOME_NAME_KEY) or "").strip() or "there"
    st.markdown(
        f'<div class="apres-welcome">'
        f'<div class="apres-welcome-eyebrow">Welcome</div>'
        f'<div class="apres-welcome-title">You’re in, {escape(name)}.</div>'
        f'<p class="apres-welcome-body">'
        "Discover is ready. Rate what you’ve tried, skip what you haven’t, "
        "and we’ll shape dates around your taste."
        "</p>"
        f"</div>",
        unsafe_allow_html=True,
    )
    if st.button("Start exploring", type="primary", use_container_width=True, key="welcome_continue"):
        st.session_state.pop(WELCOME_FLAG_KEY, None)
        st.session_state.pop(WELCOME_NAME_KEY, None)
        st.rerun()
    return True


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
        st.success(f"Live probe: **{venue_count}** venues. Access works. Click **Retry**.")
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


def render_apres_header(subtitle: str = "Manhattan Beach", photo_uri: str | None = None) -> None:
    mark = brand_mark_html(size="header")
    st.markdown(
        f"""
        <div class="apres-status">
            {mark}
            <span class="tagline">Find what comes next.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if photo_uri:
        st.markdown(
            f'<div class="apres-greeting-row">'
            f'<img class="apres-avatar" src="{photo_uri}" alt="" />'
            f'<p class="apres-greeting">{subtitle}</p>'
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(f'<p class="apres-greeting">{subtitle}</p>', unsafe_allow_html=True)


def render_progress(stats: dict[str, int], *, borough: str | None = None) -> None:
    pct = (stats["reviewed"] / stats["total"] * 100) if stats["total"] else 0
    remaining = int(stats.get("remaining") or 0)
    session_rated = int(st.session_state.get(SESSION_RATINGS_KEY) or 0)
    session_skipped = int(st.session_state.get(SESSION_SKIPS_KEY) or 0)

    session_bits: list[str] = []
    if session_rated:
        session_bits.append(f"{session_rated} rated this session")
    if session_skipped:
        session_bits.append(f"{session_skipped} skipped")
    session_html = (
        f'<div class="progress-session">{escape(" · ".join(session_bits))}</div>'
        if session_bits
        else ""
    )

    nudge_html = ""
    if remaining == 0 and borough:
        nudge_html = (
            f'<div class="progress-nudge">You cleared {escape(borough)}.</div>'
        )
    elif 0 < remaining <= 3:
        nudge_html = (
            '<div class="progress-nudge">Almost there. A few spots left.</div>'
        )

    st.markdown(
        f'<div class="progress-caption">'
        f'{stats["remaining"]} left &middot; {stats["rated"]} rated &middot; {stats["skipped"]} skipped'
        f"</div>"
        f"{session_html}"
        f"{nudge_html}"
        f'<div class="progress-track">'
        f'<div class="progress-bar" style="width: {pct:.1f}%;"></div>'
        f"</div>",
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
    preferred: tuple[str, ...] = ()
    try:
        profile = fetch_profile(email)
        preferred = tuple(
            preferred_types_from_activities(
                list((profile or {}).get("ACTIVITY_PREFERENCES") or [])
            )
        )
    except Exception:
        preferred = ()
    venue = fetch_next_venue(email, borough, preferred)
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
def fetch_next_venue(
    email: str,
    borough: str,
    preferred_types: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    type_filter, type_params = venue_type_filter_sql("d")
    preferred = [t for t in preferred_types if t]

    order_sql = "order by random()"
    order_params: list[Any] = []
    if preferred:
        placeholders = ", ".join("?" for _ in preferred)
        order_sql = (
            f"order by case when d.primary_type in ({placeholders}) then 0 else 1 end, random()"
        )
        order_params = list(preferred)

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
        {order_sql}
        limit 1
    """
    rows = run_query(sql, [borough, *type_params, email, *order_params])
    return rows[0] if rows else None


@st.cache_data(show_spinner=False)
def fetch_venue_tags(google_place_id: str) -> list[dict[str, Any]]:
    """Accepted vibe tags for a Discover card. Empty if table missing / untagged."""
    if not google_place_id:
        return []
    sql = f"""
        select tag, confidence, evidence, source
        from {venue_tags_table()}
        where google_place_id = ?
        order by confidence desc nulls last, tag
        limit 8
    """
    try:
        return run_query(sql, [google_place_id])
    except Exception:
        return []


def vibe_tags_html(tags: list[dict[str, Any]]) -> str:
    if not tags:
        return (
            '<div class="vibe-rail">'
            '<div class="vibe-rail-label">Vibes</div>'
            '<div class="vibe-empty">Vibes still brewing for this spot</div>'
            "</div>"
        )

    chips: list[str] = []
    for row in tags:
        label = escape(str(row.get("TAG") or "").strip())
        if not label:
            continue
        try:
            conf = float(row.get("CONFIDENCE") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        hot = " vibe-tag-hot" if conf >= 0.85 else ""
        chips.append(f'<span class="vibe-tag{hot}">{label}</span>')

    if not chips:
        return (
            '<div class="vibe-rail">'
            '<div class="vibe-rail-label">Vibes</div>'
            '<div class="vibe-empty">Vibes still brewing for this spot</div>'
            "</div>"
        )

    return (
        '<div class="vibe-rail">'
        '<div class="vibe-rail-label">Vibes</div>'
        f'<div class="vibe-tags">{"".join(chips)}</div>'
        "</div>"
    )


@st.cache_data(show_spinner=False, ttl=300)
def fetch_venue_hours(google_place_id: str) -> dict[str, Any] | None:
    """Hours of operation when available (ok/partial). None if missing/empty."""
    if not google_place_id:
        return None
    sql = f"""
        select hours_text, hours_json, status, confidence, source, timezone
        from {venue_hours_table()}
        where google_place_id = ?
          and status in ('ok', 'partial')
          and hours_text is not null
          and trim(hours_text) <> ''
        limit 1
    """
    try:
        rows = run_query(sql, [google_place_id])
    except Exception:
        return None
    return rows[0] if rows else None


def _parse_hours_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _fmt_clock_24(hhmm: str) -> str:
    try:
        h, m = map(int, hhmm.split(":"))
    except (TypeError, ValueError):
        return hhmm
    ampm = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {ampm}"


def today_hours_summary(hours_row: dict[str, Any]) -> str:
    """e.g. 'Open · 7:00 AM – 1:00 PM' or 'Closed today'."""
    hours_json = _parse_hours_json(hours_row.get("HOURS_JSON"))
    day_key = date.today().strftime("%A").lower()
    periods = hours_json.get(day_key)
    if periods is None and hours_json:
        # Explicit null / missing → try text line for today
        text = str(hours_row.get("HOURS_TEXT") or "")
        for line in text.splitlines():
            if line.lower().startswith(day_key[:3]) or line.lower().startswith(day_key):
                body = line.split(":", 1)[-1].strip() if ":" in line else line
                if re.search(r"(?i)closed", body):
                    return "Closed today"
                if body:
                    return f"Today · {body}"
        return "Hours on file"
    if periods == [] or periods is None:
        # Check text for Closed
        text = str(hours_row.get("HOURS_TEXT") or "")
        for line in text.splitlines():
            if day_key in line.lower() and re.search(r"(?i)closed", line):
                return "Closed today"
        if periods is None:
            return "Hours on file"
        return "Closed today"
    if isinstance(periods, list) and periods:
        parts: list[str] = []
        for p in periods:
            if not isinstance(p, dict):
                continue
            o = _fmt_clock_24(str(p.get("open") or ""))
            c = _fmt_clock_24(str(p.get("close") or ""))
            if o and c:
                parts.append(f"{o} – {c}")
        if parts:
            return f"Open · {' · '.join(parts)}"
    return "Hours on file"


def hours_html(hours_row: dict[str, Any] | None) -> str:
    """Render hours block only when we have usable data."""
    if not hours_row:
        return ""
    week = escape(str(hours_row.get("HOURS_TEXT") or "").strip()).replace("\n", "<br>")
    if not week:
        return ""
    today = escape(today_hours_summary(hours_row))
    return (
        '<div class="hours-rail">'
        '<div class="hours-rail-label">Hours</div>'
        f'<div class="hours-today"><strong>{today}</strong></div>'
        f'<div class="hours-week">{week}</div>'
        "</div>"
    )


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
            empty_state_html(
                eyebrow="Your calendar",
                title="No dates planned yet",
                body="Build one above. We’ll keep it here when you’re ready.",
            ),
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
        sched_hour = st.selectbox(
            "Hour",
            options=list(range(1, 13)),
            index=6,
            format_func=lambda h: f"{h}:00",
        )
        sched_minute = st.selectbox(
            "Minute",
            options=[0, 15, 30, 45],
            index=0,
            format_func=lambda m: f":{m:02d}",
        )
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
        '<p class="swipe-hint">Build a two-stop plan. Re-roll, swap stops, then save a time.</p>',
        unsafe_allow_html=True,
    )

    if "plan_borough" not in st.session_state:
        st.session_state["plan_borough"] = (
            DEFAULT_BOROUGH if DEFAULT_BOROUGH in boroughs else boroughs[0]
        )
    borough = st.selectbox("Area", boroughs, key="plan_borough")

    location = render_location_picker(borough=borough)
    if not location:
        st.info("Choose **Near me** or drop a pin on the map to get started.")
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

    radius_mi = st.slider(
        "Within this distance of you",
        min_value=0.25,
        max_value=2.0,
        value=1.0,
        step=0.25,
        format="%.2f mi",
        key="plan_radius_mi",
    )
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
    from onboarding import LOGIN_MODE_KEY
    from brand import wordmark_path

    returning = st.session_state.get(LOGIN_MODE_KEY) == "returning"
    if returning:
        title = "Welcome back."
        hint = "Same email as before. We’ll pick up your ratings and profile."
    else:
        title = "Create your account."
        hint = "A few taste questions come next, so Discover and dates fit you sooner."

    mark = wordmark_path(variant="dark_sm")
    brand_col, tag_col = st.columns([1.15, 2])
    with brand_col:
        if mark is not None:
            st.image(str(mark), use_container_width=True)
        else:
            st.markdown(
                '<div class="apres-brand-text" style="font-size:22px;line-height:1;">Après</div>',
                unsafe_allow_html=True,
            )
    with tag_col:
        st.markdown(
            '<p class="tagline" style="text-align:right;margin:0.55rem 0 0;'
            'font-family:Cormorant Garamond,Georgia,serif;font-style:italic;'
            'color:#7A5B48;font-size:14px;">Find what comes next.</p>',
            unsafe_allow_html=True,
        )

    st.markdown(
        f"""
        <p class="apres-greeting">{title}</p>
        <p class="apres-sub">email only · no password</p>
        <p class="swipe-hint">{hint}</p>
        """,
        unsafe_allow_html=True,
    )

    with st.form("login_form", clear_on_submit=False):
        email_raw = st.text_input("Email", placeholder="you@example.com")
        submitted = st.form_submit_button("Continue", type="primary", use_container_width=True)

    if submitted:
        email = normalize_email(email_raw)
        if not is_valid_email(email):
            st.error("Enter a valid email address.")
            return
        st.session_state["user_email"] = email
        clear_discover_venue()
        st.rerun()


def render_venue_card(
    venue: dict[str, Any],
    tags: list[dict[str, Any]] | None = None,
    hours: dict[str, Any] | None = None,
    community_line: str | None = None,
) -> None:
    name = escape(str(venue.get("PLACE_NAME") or "Unknown venue"))
    address = venue.get("SHORT_FORMATTED_ADDRESS") or venue.get("FORMATTED_ADDRESS") or ""
    category = escape(
        (venue.get("VENUE_CATEGORY") or venue.get("PRIMARY_TYPE") or "venue").replace("_", " ").title()
    )
    primary = escape((venue.get("PRIMARY_TYPE") or "").replace("_", " "))
    price = format_price_level(venue.get("PRICE_LEVEL"))
    website = venue.get("WEBSITE_URI") or ""
    place_id = str(venue.get("GOOGLE_PLACE_ID") or "")
    if tags is None:
        tags = fetch_venue_tags(place_id)
    if hours is None:
        hours = fetch_venue_hours(place_id)

    meta_parts = [p for p in [primary, escape(address.split(",")[0]) if address else ""] if p]
    meta_line = " &middot; ".join(meta_parts[:2]) if meta_parts else escape(str(address))

    pills = f"<span>{category}</span>"
    if price:
        pills += f"<span>{escape(price)}</span>"

    locals_html = ""
    if community_line:
        locals_html = f'<div class="locals-line">{community_line}</div>'

    footer_html = ""
    if website:
        safe_url = escape(str(website), quote=True)
        footer_html = (
            f'<div class="date-card-footer">'
            f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">Website</a></div>'
        )

    # Single-line HTML — indented lines inside st.markdown become code blocks
    # (which is why vibe/hours markup was showing as raw text on Cloud).
    html = (
        f'<div class="date-card">'
        f'<div class="date-card-label">Up next</div>'
        f'<div class="date-card-title">{name}</div>'
        f'<div class="date-card-meta">{meta_line}</div>'
        f'<div class="date-card-pills">{pills}</div>'
        f"{locals_html}"
        f"{hours_html(hours)}"
        f"{vibe_tags_html(tags)}"
        f"{footer_html}"
        f"</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


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
    render_queued_feedback()
    render_progress(stats, borough=borough)

    venue = get_discover_venue(email, borough)
    if not venue:
        st.markdown(
            empty_state_html(
                eyebrow="All caught up",
                title=f"{borough} is clear",
                body=(
                    f"You cleared this area. Try another location, "
                    f"or revisit <strong>Rated</strong> and <strong>Skipped</strong>."
                ),
                action='Open <span>Plan</span> when you’re ready for what’s next.',
            ),
            unsafe_allow_html=True,
        )
        return

    community_line = None
    try:
        community = fetch_community_ratings(borough)
        stats_row = community.get(str(venue.get("GOOGLE_PLACE_ID") or ""))
        if stats_row and stats_row.rating_count >= 2:
            community_line = (
                f"Locals · <strong>{stats_row.avg_rating:.1f}★</strong> · "
                f"{stats_row.rating_count} ratings"
            )
    except Exception:
        community_line = None

    render_venue_card(venue, community_line=community_line)
    st.markdown(
        '<p class="swipe-hint">Skip if you haven\'t been · Rate when you have</p>',
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

    st.markdown('<div class="apres-action-anchor" aria-hidden="true"></div>', unsafe_allow_html=True)
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
            bump_session_counter("skipped")
            queue_action_feedback(kind="skipped", place_name=place_name)
            st.toast("Skipped. Find it again under Skipped.")
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
            bump_session_counter("rated")
            queue_action_feedback(
                kind="rated",
                place_name=place_name,
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
    render_queued_feedback()
    if not rows:
        st.markdown(
            empty_state_html(
                eyebrow="My ratings",
                title="Nothing rated yet",
                body="Head to <strong>Discover</strong> and save your first score.",
                action='Start in <span>Discover</span> — one place at a time.',
            ),
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
            bump_session_counter("rated")
            queue_action_feedback(
                kind="updated",
                place_name=row["PLACE_NAME"] or "Unknown venue",
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
    render_queued_feedback()
    if not rows:
        st.markdown(
            empty_state_html(
                eyebrow="Skipped",
                title="A clean slate",
                body="Nothing parked here yet. Skip from <strong>Discover</strong> when you haven’t been.",
                action='Use <span>Skip</span> on Discover when you haven’t visited yet.',
            ),
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
            bump_session_counter("rated")
            queue_action_feedback(
                kind="rated",
                place_name=row["PLACE_NAME"] or "Unknown venue",
                rating=float(score),
            )
            st.toast("Rating saved!")
            st.rerun()


def main() -> None:
    try:
        inject_styles()
    except Exception as exc:  # noqa: BLE001
        log_event("inject_styles", "Style injection failed", level="error", exc=exc)

    if "user_email" not in st.session_state:
        if not onboarding_complete():
            render_onboarding()
            return
        render_login()
        return

    email = st.session_state["user_email"]

    try:
        with st.spinner("Loading your profile…"):
            profile = fetch_profile(email, include_photo=False)
    except Exception as exc:  # noqa: BLE001
        log_event("fetch_profile", "Profile fetch failed", level="error", email=email, exc=exc)
        st.error("Couldn’t load your profile. Pull to refresh, or try again in a moment.")
        show_recent_errors()
        if st.button("Sign out", type="secondary", key="profile_fail_sign_out"):
            del st.session_state["user_email"]
            st.rerun()
        return

    try:
        complete = is_profile_complete(profile)
    except Exception as exc:  # noqa: BLE001
        log_event("profile_complete_check", "Completeness check failed", level="error", email=email, exc=exc)
        complete = False

    if not complete:
        if st.button("Sign out", type="secondary", use_container_width=True, key="setup_sign_out"):
            clear_discover_venue()
            st.session_state.pop("profile_draft", None)
            st.session_state.pop("profile_setup_step", None)
            del st.session_state["user_email"]
            st.rerun()
        try:
            render_profile_setup(email, profile)
        except Exception as exc:  # noqa: BLE001
            log_event("profile_setup_render", "Setup UI crashed", level="error", email=email, exc=exc)
            st.error("Something went wrong loading profile setup.")
            show_recent_errors()
        return

    first = (profile or {}).get("FIRST_NAME") or ""
    city = (profile or {}).get("CITY") or ""
    display_name = first or email.split("@")[0].replace(".", " ").title()
    photo_uri = None
    try:
        if (profile or {}).get("HAS_PROFILE_PHOTO"):
            photo_row = fetch_profile_photo(email)
            if photo_row:
                photo_uri = photo_data_uri(
                    photo_row.get("PROFILE_PHOTO_B64"),
                    photo_row.get("PROFILE_PHOTO_MIME"),
                )
    except Exception as exc:  # noqa: BLE001
        log_event("fetch_photo", "Avatar load failed", level="warning", email=email, exc=exc)

    render_apres_header(personalized_greeting(display_name, city), photo_uri=photo_uri)
    st.markdown(
        f'<p class="apres-sub">signed in as {email}</p>',
        unsafe_allow_html=True,
    )

    if st.button("Sign out", type="secondary", use_container_width=True, key="main_sign_out"):
        clear_discover_venue()
        st.session_state.pop("profile_draft", None)
        st.session_state.pop("profile_setup_step", None)
        st.session_state.pop(WELCOME_FLAG_KEY, None)
        st.session_state.pop(WELCOME_NAME_KEY, None)
        del st.session_state["user_email"]
        st.rerun()

    if render_profile_welcome():
        return

    tab_discover, tab_plan, tab_rated, tab_skipped, tab_profile = st.tabs(
        ["Discover", "Plan", "Rated", "Skipped", "Profile"]
    )

    with tab_discover:
        try:
            render_discover(email)
        except Exception as exc:  # noqa: BLE001
            log_event("discover", "Discover crashed", level="error", email=email, exc=exc)
            st.error("Discover hit an error.")
            show_recent_errors()

    with tab_plan:
        try:
            render_plan_date(email)
        except Exception as exc:  # noqa: BLE001
            log_event("plan", "Plan crashed", level="error", email=email, exc=exc)
            st.error("Plan a date hit an error.")
            show_recent_errors()

    with tab_rated:
        try:
            render_rated_list(email)
        except Exception as exc:  # noqa: BLE001
            log_event("rated", "Ratings list crashed", level="error", email=email, exc=exc)
            st.error("My ratings hit an error.")
            show_recent_errors()

    with tab_skipped:
        try:
            render_skipped_list(email)
        except Exception as exc:  # noqa: BLE001
            log_event("skipped", "Skipped list crashed", level="error", email=email, exc=exc)
            st.error("Skipped hit an error.")
            show_recent_errors()

    with tab_profile:
        try:
            # Load photo only on Profile tab (heavy base64).
            profile_full = fetch_profile(email, include_photo=True) or profile or {}
            render_profile_settings(email, profile_full)
        except Exception as exc:  # noqa: BLE001
            log_event("profile_tab", "Profile tab crashed", level="error", email=email, exc=exc)
            st.error("Profile hit an error.")
            show_recent_errors()


if __name__ == "__main__":
    main()
