"""
Manhattan Beach Venue Swiper

Runs in Streamlit in Snowflake (SiS) or Streamlit Community Cloud.
- SiS: Snowflake login + in-app email for personal ratings.
- Community Cloud: share app URL; friends enter email only (service account in secrets).
"""

from __future__ import annotations

import json
import re
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

DEFAULT_BOROUGH = "Manhattan Beach"
DEFAULT_DIM_PLACES = "VENUE_HYPE.STAGING_MARTS.DIM_PLACES"
DEFAULT_RATINGS_TABLE = "VENUE_HYPE.APP.VENUE_RATINGS"
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SESSION_VENUE_KEY = "discover_venue"


def dim_places_table() -> str:
    try:
        return st.secrets.get("app", {}).get("dim_places", DEFAULT_DIM_PLACES)
    except Exception:
        return DEFAULT_DIM_PLACES


def ratings_table() -> str:
    try:
        return st.secrets.get("app", {}).get("ratings_table", DEFAULT_RATINGS_TABLE)
    except Exception:
        return DEFAULT_RATINGS_TABLE

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
VESPER_CSS = f"""
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
.vesper-status {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 11px;
    font-weight: 500;
    color: var(--brown);
    letter-spacing: 0.05em;
    margin-bottom: 1rem;
}}
.vesper-status .tagline {{
    font-family: {FONT_SERIF};
    font-size: 13px;
    font-style: italic;
    letter-spacing: 0;
}}
.vesper-greeting {{
    font-family: {FONT_SERIF};
    font-size: 30px;
    font-weight: 300;
    font-style: italic;
    color: var(--brown);
    line-height: 1.2;
    margin: 0 0 0.25rem 0;
}}
.vesper-sub {{
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
"""

st.set_page_config(
    page_title="Vesper - Manhattan Beach",
    page_icon="*",
    layout="centered",
    initial_sidebar_state="collapsed",
)


def inject_styles() -> None:
    css_literal = json.dumps(VESPER_CSS)
    script = f"""<script>
    (function() {{
        const doc = window.parent.document;
        if (doc.getElementById("vesper-styles")) return;
        const el = doc.createElement("style");
        el.id = "vesper-styles";
        el.textContent = {css_literal};
        doc.head.appendChild(el);
    }})();
    </script>"""
    if hasattr(st, "html"):
        st.html(script, height=0)
    else:
        components.html(script, height=0, width=0)


def fetch_snowflake_identity() -> dict[str, str] | None:
    """What user/role the app session is actually using (not your Snowsight worksheet)."""
    try:
        row = run_query(
            """
            select
                current_user() as snowflake_user,
                current_role() as snowflake_role,
                current_database() as snowflake_database,
                current_warehouse() as snowflake_warehouse
            """
        )[0]
        return {k.lower(): str(v) for k, v in row.items()}
    except Exception:
        return None


def show_snowflake_data_error(exc: Exception) -> None:
    st.error("Cannot read venue data from Snowflake.")
    st.markdown(f"**Details:** `{exc}`")

    identity = fetch_snowflake_identity()
    if identity:
        st.markdown("**App session (from Streamlit Cloud secrets):**")
        st.code(
            "\n".join(f"{key}: {value}" for key, value in identity.items()),
            language="text",
        )
        expected_user = "VENUE_SWIPER_SVC"
        expected_role = "VENUE_SWIPER_APP"
        if identity.get("snowflake_user", "").upper() != expected_user:
            st.warning(
                f"Secrets `user` should be `{expected_user}`, not your personal login. "
                "Update App Settings → Secrets, then **Reboot app** (⋮ menu)."
            )
        if identity.get("snowflake_role", "").upper() != expected_role:
            st.warning(
                f"Secrets `role` should be `{expected_role}`. "
                "Worksheets with `USE ROLE` as your admin user do not prove the service account is configured."
            )

    st.markdown(
        f"""
        **Why Step C can pass but the app fails**

        Snowsight Step C runs as **your personal user** after `USE ROLE VENUE_SWIPER_APP`.
        Streamlit Cloud connects as **`VENUE_SWIPER_SVC`** using App Secrets. Those are different logins.

        **Test the service user (not `USE ROLE` from admin):**

        ```sql
        -- snowsql -a YOUR_ACCOUNT -u VENUE_SWIPER_SVC -r VENUE_SWIPER_APP -w VENUE_HYPE_WH
        SELECT CURRENT_USER(), CURRENT_ROLE();
        SELECT COUNT(*) FROM {dim_places_table()} WHERE borough = 'Manhattan Beach';
        ```

        **Secrets must look like this (Settings → Secrets):**

        ```toml
        [connections.snowflake]
        user = "VENUE_SWIPER_SVC"
        role = "VENUE_SWIPER_APP"
        database = "VENUE_HYPE"
        schema = "APP"
        ```

        After changing secrets: **Reboot app** in Streamlit Cloud (cached Snowflake session).

        **If identity above is correct but count still fails — grants (ACCOUNTADMIN):**

        ```sql
        GRANT USAGE ON DATABASE VENUE_HYPE TO ROLE VENUE_SWIPER_APP;
        GRANT USAGE ON SCHEMA VENUE_HYPE.STAGING_MARTS TO ROLE VENUE_SWIPER_APP;
        GRANT SELECT ON TABLE {dim_places_table()} TO ROLE VENUE_SWIPER_APP;
        GRANT USAGE ON SCHEMA VENUE_HYPE.APP TO ROLE VENUE_SWIPER_APP;
        GRANT SELECT, INSERT, UPDATE ON TABLE {ratings_table()} TO ROLE VENUE_SWIPER_APP;
        ```
        """
    )


def render_vesper_header(subtitle: str = "Manhattan Beach") -> None:
    st.markdown(
        """
        <div class="vesper-status">
            <span>VESPER</span>
            <span class="tagline">the evening hour</span>
            <span>&middot;</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f'<p class="vesper-greeting">{subtitle}</p>', unsafe_allow_html=True)


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


def _snowflake_connection_params() -> dict[str, str]:
    if "connections" not in st.secrets or "snowflake" not in st.secrets.connections:
        missing = (
            "Missing `[connections.snowflake]` in Streamlit App Secrets. "
            "Open app Settings -> Secrets and paste the block from "
            "`.streamlit/secrets.toml.example`."
        )
        raise RuntimeError(missing)

    raw = dict(st.secrets.connections.snowflake)
    required = ("account", "user", "password", "role", "warehouse", "database", "schema")
    missing_keys = [key for key in required if not str(raw.get(key, "")).strip()]
    if missing_keys:
        raise RuntimeError(
            "Secrets are missing or empty: "
            + ", ".join(missing_keys)
            + ". Check App Settings -> Secrets."
        )

    params = {key: str(raw[key]).strip() for key in required}
    if "host" in raw and str(raw["host"]).strip():
        params["host"] = str(raw["host"]).strip()
    return params


def _activate_snowflake_role(session, role: str) -> None:
    """Ensure the session uses the role from secrets (st.connection can leave a stale default)."""
    safe_role = role.replace('"', '""')
    session.sql(f'USE ROLE "{safe_role}"').collect()


@st.cache_resource
def get_session():
    try:
        from snowflake.snowpark.context import get_active_session

        return get_active_session()
    except Exception:
        pass

    errors: list[str] = []

    # Prefer explicit Session.builder on Community Cloud — role from secrets is applied reliably.
    try:
        if "connections" in st.secrets and "snowflake" in st.secrets.connections:
            from snowflake.snowpark import Session

            params = _snowflake_connection_params()
            session = Session.builder.configs(params).create()
            _activate_snowflake_role(session, params["role"])
            return session
    except Exception as exc:
        errors.append(f"Session.builder: {exc}")

    try:
        session = st.connection("snowflake").session()
        if "connections" in st.secrets and "snowflake" in st.secrets.connections:
            role = str(st.secrets.connections.snowflake.get("role", "")).strip()
            if role:
                _activate_snowflake_role(session, role)
        return session
    except Exception as exc:
        errors.append(f"st.connection: {exc}")

    try:
        from snowflake.snowpark import Session

        params = _snowflake_connection_params()
        session = Session.builder.configs(params).create()
        _activate_snowflake_role(session, params["role"])
        return session
    except Exception as exc:
        errors.append(f"Session.builder (retry): {exc}")

    st.error("Could not connect to Snowflake.")
    with st.expander("Connection details (for troubleshooting)"):
        st.markdown(
            """
            **Check App Secrets (Settings -> Secrets):**

            ```toml
            [connections.snowflake]
            account = "YOUR_ACCOUNT"
            user = "VENUE_SWIPER_SVC"
            password = "YOUR_PASSWORD"
            role = "VENUE_SWIPER_APP"
            warehouse = "VENUE_HYPE_WH"
            database = "VENUE_HYPE"
            schema = "APP"
            ```

            **Account value:** use the same identifier as `SNOWFLAKE_ACCOUNT` in your
            local `.env` (e.g. `xy12345.us-east-1`). If that fails, try the
            org-account form from Snowsight -> Account -> Account identifier
            (e.g. `MYORG-MYACCOUNT`).

            **Password:** use the `VENUE_SWIPER_SVC` password, not your personal login.
            Wrap passwords with special characters in double quotes in Secrets.
            """
        )
        for message in errors:
            st.code(message)
    st.stop()


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


def run_query(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    session = get_session()
    try:
        rows = session.sql(sql, params=params or []).collect()
    except Exception as exc:
        raise RuntimeError(f"Snowflake query failed: {exc}") from exc
    return [row.as_dict() for row in rows]


def venue_type_filter_sql(alias: str = "d") -> tuple[str, list[str]]:
    placeholders = ", ".join("?" for _ in ALLOWED_PRIMARY_TYPES)
    return f"and {alias}.primary_type in ({placeholders})", list(ALLOWED_PRIMARY_TYPES)


def clear_discover_venue() -> None:
    st.session_state.pop(SESSION_VENUE_KEY, None)
    fetch_next_venue.clear()


def get_discover_venue(email: str, borough: str) -> dict[str, Any] | None:
    """Pin the current card in session so slider moves don't re-roll random()."""
    if SESSION_VENUE_KEY in st.session_state:
        return st.session_state[SESSION_VENUE_KEY]
    venue = fetch_next_venue(email, borough)
    if venue:
        st.session_state[SESSION_VENUE_KEY] = venue
    return venue


@st.cache_data(show_spinner=False)
def fetch_stats(email: str, borough: str) -> dict[str, int]:
    type_filter, type_params = venue_type_filter_sql("d")
    sql = f"""
        select
            count(*) as total_venues,
            count(r.rating_id) as reviewed,
            count_if(r.status = 'rated') as rated,
            count_if(r.status = 'skipped') as skipped
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
def fetch_user_ratings(email: str, borough: str, status: str | None = None) -> list[dict[str, Any]]:
    status_filter = ""
    params: list[Any] = [email, borough]
    if status:
        status_filter = "and r.status = ?"
        params.append(status)

    sql = f"""
        select
            r.place_name,
            r.google_place_id,
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
          and r.borough = ?
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
    session = get_session()
    if status == "skipped":
        sql = f"""
            merge into {ratings_table()} as target
            using (
                select
                    ? as user_email,
                    ? as google_place_id,
                    ? as place_name,
                    ? as borough,
                    ? as status
            ) as source
            on target.user_email = source.user_email
               and target.google_place_id = source.google_place_id
            when matched then update set
                place_name = source.place_name,
                borough = source.borough,
                rating = null,
                status = source.status,
                updated_at = current_timestamp()
            when not matched then insert (
                user_email,
                google_place_id,
                place_name,
                borough,
                rating,
                status
            ) values (
                source.user_email,
                source.google_place_id,
                source.place_name,
                source.borough,
                null,
                source.status
            )
        """
        params = [email, google_place_id, place_name, borough, status]
    else:
        if rating is None:
            raise ValueError("Rated rows require a numeric rating.")
        sql = f"""
            merge into {ratings_table()} as target
            using (
                select
                    ? as user_email,
                    ? as google_place_id,
                    ? as place_name,
                    ? as borough,
                    ?::float as rating,
                    ? as status
            ) as source
            on target.user_email = source.user_email
               and target.google_place_id = source.google_place_id
            when matched then update set
                place_name = source.place_name,
                borough = source.borough,
                rating = source.rating,
                status = source.status,
                updated_at = current_timestamp()
            when not matched then insert (
                user_email,
                google_place_id,
                place_name,
                borough,
                rating,
                status
            ) values (
                source.user_email,
                source.google_place_id,
                source.place_name,
                source.borough,
                source.rating,
                source.status
            )
        """
        params = [email, google_place_id, place_name, borough, float(rating), status]

    session.sql(sql, params=params).collect()
    fetch_stats.clear()
    fetch_next_venue.clear()
    fetch_user_ratings.clear()
    clear_discover_venue()


def render_login() -> None:
    render_vesper_header("Rate the coast.")
    st.markdown(
        '<p class="vesper-sub">Manhattan Beach &middot; venue ratings</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="login-panel">
            <p>Swipe through local spots you've tried. Skip anything you haven't visited yet -
            you can always come back and rate it later.</p>
            <p style="margin-top:0.75rem;font-size:12px;color:var(--text-light);">
            Your email saves your personal ratings. No Snowflake account needed on this hosted app.</p>
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
    category = (venue.get("VENUE_CATEGORY") or venue.get("PRIMARY_TYPE") or "venue").replace("_", " ")
    primary = (venue.get("PRIMARY_TYPE") or "").replace("_", " ")
    price = (venue.get("PRICE_LEVEL") or "").replace("_", " ").title()
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


def render_discover(email: str, borough: str) -> None:
    try:
        stats = fetch_stats(email, borough)
    except Exception as exc:
        show_snowflake_data_error(exc)
        return

    st.markdown('<div class="section-label">Discover</div>', unsafe_allow_html=True)
    render_progress(stats)

    venue = get_discover_venue(email, borough)
    if not venue:
        st.markdown(
            """
            <div class="login-panel">
                <p>You're caught up - no unrated venues left in Manhattan Beach.
                Check <strong>My ratings</strong> or revisit <strong>Skipped</strong>
                when you've visited somewhere new.</p>
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


def render_rated_list(email: str, borough: str) -> None:
    rows = fetch_user_ratings(email, borough, status="rated")
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
        place_id = row["GOOGLE_PLACE_ID"]
        rating_key = f"edit_rate_{place_id}"
        current_rating = float(row["RATING"])
        if rating_key not in st.session_state:
            st.session_state[rating_key] = current_rating

        st.markdown(
            f"""
            <div class="bucket-card">
                <div class="bucket-title">{row['PLACE_NAME']}</div>
                <div class="bucket-sub">{category} &middot; {address}</div>
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
                borough=borough,
                google_place_id=place_id,
                place_name=row["PLACE_NAME"] or "Unknown venue",
                status="rated",
                rating=updated,
            )
            st.toast(f"Updated to {updated:.1f}★")
            st.rerun()


def render_skipped_list(email: str, borough: str) -> None:
    rows = fetch_user_ratings(email, borough, status="skipped")
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
        place_id = row["GOOGLE_PLACE_ID"]
        rating_key = f"skip_rate_{place_id}"
        if rating_key not in st.session_state:
            st.session_state[rating_key] = 3.0

        st.markdown(
            f"""
            <div class="bucket-card">
                <div class="bucket-icon-skip">&rarr;</div>
                <div class="bucket-title">{row['PLACE_NAME']}</div>
                <div class="bucket-sub">{address}</div>
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
                borough=borough,
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
    borough = DEFAULT_BOROUGH
    display_name = email.split("@")[0].replace(".", " ").title()

    render_vesper_header(f"Good evening, {display_name}.")
    st.markdown(
        f'<p class="vesper-sub">{borough} &middot; signed in as {email}</p>',
        unsafe_allow_html=True,
    )

    _, sign_out_col = st.columns([4, 1])
    with sign_out_col:
        if st.button("Sign out", type="secondary", use_container_width=True):
            clear_discover_venue()
            del st.session_state["user_email"]
            st.rerun()

    tab_discover, tab_rated, tab_skipped = st.tabs(["Discover", "My ratings", "Skipped"])

    with tab_discover:
        render_discover(email, borough)

    with tab_rated:
        render_rated_list(email, borough)

    with tab_skipped:
        render_skipped_list(email, borough)


if __name__ == "__main__":
    main()
