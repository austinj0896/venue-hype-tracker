"""User location: browser geolocation, map pick, or manual coords."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

try:
    from streamlit_folium import st_folium
    import folium
    from folium.plugins import LocateControl

    HAS_FOLIUM = True
except ImportError:
    HAS_FOLIUM = False

# Default map centers for pilot boroughs
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


@dataclass
class UserLocation:
    lat: float
    lon: float
    source: str  # geolocation | map | manual


_GEOLOCATION_HTML = """
<div id="geo-status" style="font-size:12px;color:#7A5B48;margin-bottom:4px;">
  Tap the button to share your location (browser permission required).
</div>
<button id="geo-btn" style="
  background:#704D3B;color:#F8E6D2;border:none;border-radius:8px;
  padding:8px 16px;font-size:13px;cursor:pointer;width:100%;
">Use my location</button>
<script>
(function() {
  const btn = document.getElementById("geo-btn");
  const status = document.getElementById("geo-status");
  btn.onclick = function() {
    status.textContent = "Requesting location…";
    if (!navigator.geolocation) {
      status.textContent = "Geolocation not supported in this browser.";
      return;
    }
    navigator.geolocation.getCurrentPosition(
      function(pos) {
        const payload = {
          lat: pos.coords.latitude,
          lon: pos.coords.longitude,
          source: "geolocation"
        };
        status.textContent = "Location received ✓";
        window.parent.postMessage({
          isStreamlitMessage: true,
          type: "streamlit:setComponentValue",
          value: payload
        }, "*");
      },
      function(err) {
        status.textContent = "Location denied or unavailable: " + err.message;
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 }
    );
  };
})();
</script>
"""


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
        source=str(st.session_state.get(SESSION_SOURCE, "manual")),
    )


def save_location(lat: float, lon: float, source: str) -> None:
    st.session_state[SESSION_LAT] = float(lat)
    st.session_state[SESSION_LON] = float(lon)
    st.session_state[SESSION_SOURCE] = source


def render_location_picker(*, borough: str) -> UserLocation | None:
    """
    Returns the active user location, or None if not set yet.
    """
    center_lat, center_lon = borough_center(borough)
    saved = get_saved_location()

    st.markdown(
        '<p class="swipe-hint">Set where you\'ll start — we\'ll find spots near you.</p>',
        unsafe_allow_html=True,
    )

    mode = st.radio(
        "Starting point",
        options=["Use my location", "Pick on map", "Enter coordinates"],
        horizontal=False,
        label_visibility="collapsed",
    )

    if mode == "Use my location":
        geo_result = components.html(_GEOLOCATION_HTML, height=90)
        if isinstance(geo_result, dict) and geo_result.get("lat") is not None:
            save_location(
                geo_result["lat"],
                geo_result["lon"],
                geo_result.get("source", "geolocation"),
            )
            saved = get_saved_location()

    elif mode == "Pick on map":
        if not HAS_FOLIUM:
            st.info("Install streamlit-folium for map picking: pip install streamlit-folium")
            lat = st.number_input("Latitude", value=center_lat, format="%.6f")
            lon = st.number_input("Longitude", value=center_lon, format="%.6f")
            if st.button("Set location", use_container_width=True):
                save_location(lat, lon, "manual")
                saved = get_saved_location()
        else:
            init_lat = saved.lat if saved else center_lat
            init_lon = saved.lon if saved else center_lon
            m = folium.Map(location=[init_lat, init_lon], zoom_start=15, tiles="OpenStreetMap")
            folium.Marker([init_lat, init_lon], popup="Start here").add_to(m)
            LocateControl(auto_start=False).add_to(m)
            map_data = st_folium(
                m,
                width=None,
                height=320,
                returned_objects=["last_clicked"],
            )
            clicked = (map_data or {}).get("last_clicked")
            if clicked and clicked.get("lat") is not None:
                save_location(clicked["lat"], clicked["lng"], "map")
                saved = get_saved_location()
                st.caption(f"Pinned: {clicked['lat']:.5f}, {clicked['lng']:.5f}")

    else:
        col_a, col_b = st.columns(2)
        with col_a:
            lat = st.number_input(
                "Latitude",
                value=saved.lat if saved else center_lat,
                format="%.6f",
                key="manual_lat",
            )
        with col_b:
            lon = st.number_input(
                "Longitude",
                value=saved.lon if saved else center_lon,
                format="%.6f",
                key="manual_lon",
            )
        if st.button("Set location", use_container_width=True, key="set_manual_loc"):
            save_location(lat, lon, "manual")
            saved = get_saved_location()

    if saved:
        src_label = {"geolocation": "GPS", "map": "Map", "manual": "Manual"}.get(
            saved.source, saved.source
        )
        st.markdown(
            f'<p class="swipe-hint">Start: {saved.lat:.5f}, {saved.lon:.5f} ({src_label})</p>',
            unsafe_allow_html=True,
        )
        return saved

    return None
