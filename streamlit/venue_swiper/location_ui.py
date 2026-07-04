"""User location: browser geolocation or refined map pick."""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

try:
    from streamlit_geolocation import streamlit_geolocation

    HAS_GEOLOCATION = True
except ImportError:
    HAS_GEOLOCATION = False

try:
    from streamlit_folium import st_folium
    import folium
    from folium.plugins import LocateControl

    HAS_FOLIUM = True
except ImportError:
    HAS_FOLIUM = False

BOROUGH_CENTERS: dict[str, tuple[float, float]] = {
    "Manhattan Beach": (33.8847, -118.4109),
    "Murray Hill": (40.751, -73.975),
    "Kips Bay": (40.742, -73.978),
    "Manhattan": (40.758, -73.985),
}

DEFAULT_CENTER = BOROUGH_CENTERS["Manhattan Beach"]

SESSION_LAT = "date_origin_lat"
SESSION_LON = "date_origin_lon"
SESSION_SOURCE = "date_origin_source"

MODE_NEAR_ME = "Near me"
MODE_ON_MAP = "On the map"

# Minimal, modern basemap (Carto Voyager).
MAP_TILES = "CartoDB voyager"

APRES_PIN_HTML = """
<div style="
  width: 16px;
  height: 16px;
  margin: -8px 0 0 -8px;
  background: #D3A345;
  border: 2.5px solid #704D3B;
  border-radius: 50%;
  box-shadow: 0 2px 10px rgba(44,26,16,0.22);
"></div>
"""


@dataclass
class UserLocation:
    lat: float
    lon: float
    source: str  # geolocation | map


def borough_center(borough: str) -> tuple[float, float]:
    return BOROUGH_CENTERS.get(borough, DEFAULT_CENTER)


def get_saved_location() -> UserLocation | None:
    lat = st.session_state.get(SESSION_LAT)
    lon = st.session_state.get(SESSION_LON)
    if lat is None or lon is None:
        return None
    return UserLocation(
        lat=float(lat),
        lon=float(lon),
        source=str(st.session_state.get(SESSION_SOURCE, "map")),
    )


def save_location(lat: float, lon: float, source: str) -> None:
    st.session_state[SESSION_LAT] = float(lat)
    st.session_state[SESSION_LON] = float(lon)
    st.session_state[SESSION_SOURCE] = source


def location_status_html(*, borough: str, source: str) -> str:
    if source == "geolocation":
        detail = "Using your location"
    else:
        detail = "Pin set on map"
    return (
        f'<div class="location-set-pill">'
        f'<span class="location-set-dot"></span>'
        f"<strong>{detail}</strong> · {borough}"
        f"</div>"
    )


def make_apres_map(lat: float, lon: float) -> folium.Map:
    m = folium.Map(
        location=[lat, lon],
        zoom_start=15,
        tiles=MAP_TILES,
        zoom_control=False,
        attributionControl=False,
    )
    folium.Marker(
        location=[lat, lon],
        icon=folium.DivIcon(
            html=APRES_PIN_HTML,
            icon_size=(16, 16),
            icon_anchor=(8, 8),
            class_name="apres-map-pin",
        ),
    ).add_to(m)
    LocateControl(
        auto_start=False,
        position="bottomright",
        strings={"title": "Find me"},
    ).add_to(m)
    return m


def render_location_picker(*, borough: str) -> UserLocation | None:
    """Returns the active user location, or None if not set yet."""
    center_lat, center_lon = borough_center(borough)
    saved = get_saved_location()

    st.markdown(
        '<p class="swipe-hint">Where will you start the evening?</p>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="location-mode-row">', unsafe_allow_html=True)
    mode = st.radio(
        "Starting point",
        options=[MODE_NEAR_ME, MODE_ON_MAP],
        horizontal=True,
        label_visibility="collapsed",
        key="date_location_mode",
    )
    st.markdown("</div>", unsafe_allow_html=True)

    if mode == MODE_NEAR_ME:
        if not HAS_GEOLOCATION:
            st.caption("Location sharing isn’t available here — use the map instead.")
        else:
            st.caption("Allow location access when prompted.")
            loc = None
            try:
                loc = streamlit_geolocation()
            except Exception:
                st.caption("Use **On the map** to drop a pin instead.")
            if (
                isinstance(loc, dict)
                and loc.get("latitude") is not None
                and loc.get("longitude") is not None
            ):
                save_location(
                    float(loc["latitude"]),
                    float(loc["longitude"]),
                    "geolocation",
                )
                saved = get_saved_location()

    elif mode == MODE_ON_MAP:
        if not HAS_FOLIUM:
            st.caption("Map unavailable — switch to **Near me**.")
        else:
            st.caption("Tap anywhere to set your starting point.")
            init_lat = saved.lat if saved else center_lat
            init_lon = saved.lon if saved else center_lon
            map_data = st_folium(
                make_apres_map(init_lat, init_lon),
                width=None,
                height=300,
                returned_objects=["last_clicked"],
            )
            clicked = (map_data or {}).get("last_clicked")
            if clicked and clicked.get("lat") is not None:
                save_location(clicked["lat"], clicked["lng"], "map")
                saved = get_saved_location()

    if saved:
        st.markdown(
            location_status_html(borough=borough, source=saved.source),
            unsafe_allow_html=True,
        )
        return saved

    return None
