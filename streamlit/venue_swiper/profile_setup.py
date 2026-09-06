"""Après profile setup wizard and profile edit UI."""

from __future__ import annotations

from datetime import date, datetime
from html import escape
from typing import Any

import streamlit as st

from profile_options import (
    ACTIVITY_OPTIONS,
    DEFAULT_CITIES,
    DIETARY_OPTIONS,
    OPEN_TO_DATES_LABELS,
    RELATIONSHIP_STATUS_KEYS,
    RELATIONSHIP_STATUS_LABELS,
    RELATIONSHIP_STATUS_PARTNERED,
    RELATIONSHIP_STATUS_SOLO,
    compute_profile_visibility,
    neighbourhoods_for_city,
    relationship_preview_line,
)
from partner_store import (
    can_view_profile,
    cancel_partner_request,
    create_partner_request,
    get_linked_partner,
    list_notifications,
    list_pending_inbound,
    list_pending_outbound,
    mark_notifications_read,
    respond_to_partner_request,
    unlink_partner,
)
from user_profiles_store import (
    MAX_PROFILE_PHOTOS,
    clear_profile_cache,
    fetch_profile,
    is_profile_complete,
    list_profile_photos,
    photo_data_uri,
    prepare_profile_photo,
    save_profile_photos,
    upsert_profile,
)

DRAFT_KEY = "profile_draft"
STEP_KEY = "profile_setup_step"
PREVIEW_OPEN_KEY = "apres_profile_preview_open"
PREVIEW_IDX_KEY = "apres_preview_photo_idx"
PARTNER_PREVIEW_KEY = "apres_partner_preview_open"
PREVIEW_CLOSE_QP = "apres_close"
SETUP_PARTNER_DIALOG_KEY = "apres_setup_partner_dialog"
PROFILE_FLASH_KEY = "apres_profile_flash"


def _empty_draft(email: str, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    if existing:
        dietary = list(existing.get("DIETARY_NEEDS") or [])
        activities = list(existing.get("ACTIVITY_PREFERENCES") or [])
        city = existing.get("CITY") or ""
        known_city = city if city in DEFAULT_CITIES else ""
        dob = existing.get("DATE_OF_BIRTH")
        return {
            "email": email,
            "first_name": existing.get("FIRST_NAME") or "",
            "last_name": existing.get("LAST_NAME") or "",
            "date_of_birth": dob,
            "phone": existing.get("PHONE") or "",
            "city_choice": known_city,
            "neighbourhood": existing.get("NEIGHBOURHOOD") or "",
            "dietary_needs": dietary,
            "activity_preferences": activities,
            "accepted_terms": bool(existing.get("ACCEPTED_TERMS_AT")),
            "marketing_opt_in": bool(existing.get("MARKETING_OPT_IN")),
            "relationship_status": existing.get("RELATIONSHIP_STATUS") or "",
            "open_to_dates": existing.get("OPEN_TO_DATES"),
            "partner_email_draft": "",
            "photos": [],
            "photos_changed": False,
            "photos_loaded": False,
        }
    return {
        "email": email,
        "first_name": "",
        "last_name": "",
        "date_of_birth": None,
        "phone": "",
        "city_choice": "",
        "neighbourhood": "",
        "dietary_needs": [],
        "activity_preferences": [],
        "accepted_terms": False,
        "marketing_opt_in": False,
        "relationship_status": "",
        "open_to_dates": None,
        "partner_email_draft": "",
        "photos": [],
        "photos_changed": False,
        "photos_loaded": False,
    }


def _get_draft(email: str, existing: dict[str, Any] | None) -> dict[str, Any]:
    draft = st.session_state.get(DRAFT_KEY)
    if not isinstance(draft, dict) or draft.get("email") != email:
        draft = _empty_draft(email, existing)
        st.session_state[DRAFT_KEY] = draft
    # Backfill keys for drafts created before relationship fields existed.
    for key, default in (
        ("relationship_status", ""),
        ("open_to_dates", None),
        ("partner_email_draft", ""),
    ):
        if key not in draft:
            draft[key] = default
    return draft


def _save_draft(draft: dict[str, Any]) -> None:
    st.session_state[DRAFT_KEY] = draft


def _resolved_city(draft: dict[str, Any]) -> str:
    return (draft.get("city_choice") or "").strip()


def _neighbourhood_select(
    city: str,
    current: str,
    *,
    label: str,
    key: str,
) -> str | None:
    """Forced neighbourhood select for a city. Returns None if city has no list."""
    hoods = neighbourhoods_for_city(city)
    if not hoods:
        st.caption("Choose a city to pick a neighbourhood.")
        return None
    if current and current not in hoods:
        st.caption(f"Previously saved “{current}” isn’t in the list. Please reselect.")
        current = ""
    index = hoods.index(current) if current in hoods else 0
    return st.selectbox(label, hoods, index=index, key=key)


def _persist_photos_now(email: str, draft: dict[str, Any]) -> bool:
    """Save gallery immediately (upload / reorder / unlink). Returns True on success."""
    email_n = (email or draft.get("email") or "").strip()
    if not email_n:
        st.error("Missing email — can’t save photos.")
        return False
    try:
        save_profile_photos(email_n, list(draft.get("photos") or []))
        rows = list_profile_photos(email_n, include_bytes=True)
        draft["photos"] = [
            {
                "PHOTO_ID": r.get("PHOTO_ID"),
                "PHOTO_B64": r.get("PHOTO_B64"),
                "PHOTO_MIME": r.get("PHOTO_MIME") or "image/jpeg",
            }
            for r in rows
            if r.get("PHOTO_B64")
        ]
        draft["photos_changed"] = False
        draft["photos_loaded"] = True
        _save_draft(draft)
        clear_profile_cache()
        st.toast("Photos saved")
        return True
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not save photos: {exc}")
        return False


def _hydrate_draft_photos(email: str, draft: dict[str, Any], profile: dict[str, Any] | None = None) -> None:
    """Load gallery into draft once (unless the user already edited photos this session)."""
    if draft.get("photos_loaded") or draft.get("photos_changed"):
        return
    try:
        rows = list_profile_photos(email, include_bytes=True)
    except Exception:
        draft["photos_loaded"] = True
        _save_draft(draft)
        return
    draft["photos"] = [
        {
            "PHOTO_ID": r.get("PHOTO_ID"),
            "PHOTO_B64": r.get("PHOTO_B64"),
            "PHOTO_MIME": r.get("PHOTO_MIME") or "image/jpeg",
        }
        for r in rows
        if r.get("PHOTO_B64")
    ]
    draft["photos_loaded"] = True
    _save_draft(draft)


def _render_photo_picker(email: str, draft: dict[str, Any], *, key_prefix: str) -> None:
    """Compact 2×3 photo grid with shared edit controls under it."""
    st.markdown('<div class="photo-editor-label">Photos</div>', unsafe_allow_html=True)
    st.markdown(
        f'<p class="photo-editor-hint">Up to {MAX_PROFILE_PHOTOS}. Main photo shows first.</p>',
        unsafe_allow_html=True,
    )

    photos: list[dict[str, Any]] = list(draft.get("photos") or [])
    sel_key = f"{key_prefix}_photo_sel"

    def _commit(next_photos: list[dict[str, Any]]) -> None:
        draft["photos"] = next_photos
        draft.pop("_photo_upload_marker", None)
        _save_draft(draft)
        _persist_photos_now(email, draft)
        st.rerun()

    # Pure visual grid — no per-tile buttons (keeps mobile compact).
    tiles: list[str] = []
    for i in range(MAX_PROFILE_PHOTOS):
        if i < len(photos):
            photo = photos[i]
            uri = photo_data_uri(photo.get("PHOTO_B64"), photo.get("PHOTO_MIME"))
            badge = (
                '<span class="photo-main-badge">Main</span>'
                if i == 0
                else f'<span class="photo-slot-num">{i + 1}</span>'
            )
            if uri:
                tiles.append(
                    f'<div class="photo-tile">{badge}<img src="{uri}" alt="" /></div>'
                )
            else:
                tiles.append(
                    '<div class="photo-tile photo-tile-empty">'
                    '<span class="photo-plus-label">?</span></div>'
                )
        else:
            tiles.append(
                '<div class="photo-tile photo-tile-empty">'
                '<span class="photo-plus">+</span></div>'
            )

    st.markdown(
        '<div class="photo-grid">'
        + "".join(f'<div class="photo-grid-cell">{t}</div>' for t in tiles)
        + "</div>",
        unsafe_allow_html=True,
    )

    if photos:
        options = [f"Photo {i + 1}" + (" · main" if i == 0 else "") for i in range(len(photos))]
        current = st.session_state.get(sel_key, options[0])
        if current not in options:
            current = options[0]
        picked = st.selectbox(
            "Selected photo",
            options,
            index=options.index(current),
            key=sel_key,
            label_visibility="collapsed",
        )
        idx = options.index(picked)
        a1, a2 = st.columns(2)
        with a1:
            if idx > 0:
                if st.button("Make main", key=f"{key_prefix}_main", use_container_width=True):
                    moved = photos.pop(idx)
                    photos.insert(0, moved)
                    st.session_state[sel_key] = "Photo 1 · main"
                    _commit(photos)
            else:
                st.markdown(
                    '<div class="photo-main-static">Main photo</div>',
                    unsafe_allow_html=True,
                )
        with a2:
            if st.button("Remove", key=f"{key_prefix}_del", use_container_width=True):
                photos.pop(idx)
                st.session_state.pop(sel_key, None)
                _commit(photos)

    remaining = MAX_PROFILE_PHOTOS - len(photos)
    if remaining > 0:
        uploaded = st.file_uploader(
            "Add photos",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            key=f"{key_prefix}_photo_upload",
            help="JPG, PNG, or WebP · under 5 MB each",
        )
        if uploaded:
            marker = "|".join(f"{f.name}:{getattr(f, 'size', 0)}" for f in uploaded)
            if draft.get("_photo_upload_marker") != marker:
                added = 0
                errors: list[str] = []
                for f in uploaded:
                    if len(photos) >= MAX_PROFILE_PHOTOS:
                        break
                    try:
                        b64, mime = prepare_profile_photo(f)
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"{getattr(f, 'name', 'photo')}: {exc}")
                        continue
                    photos.append({"PHOTO_B64": b64, "PHOTO_MIME": mime})
                    added += 1
                draft["photos"] = photos
                draft["_photo_upload_marker"] = marker
                _save_draft(draft)
                for err in errors[:3]:
                    st.error(err)
                if added:
                    _persist_photos_now(email, draft)
                    st.rerun()
    else:
        st.caption("Photo limit reached — remove one to add another.")


def _age_from_dob(dob: Any) -> int | None:
    if isinstance(dob, datetime):
        dob = dob.date()
    if not isinstance(dob, date):
        return None
    today = date.today()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return years if 18 <= years <= 120 else years


def _chips_html(items: list[str]) -> str:
    bits = []
    for item in items:
        text = escape(str(item).strip())
        if not text:
            continue
        bits.append(f'<span class="preview-chip">{text}</span>')
    return "".join(bits)


def _dismiss_profile_preview() -> None:
    st.session_state[PREVIEW_OPEN_KEY] = False
    st.session_state[PARTNER_PREVIEW_KEY] = False


def _consume_preview_close_query() -> None:
    """Honor ?apres_close=1 from the in-photo ✕ (iframe can't call st.rerun)."""
    try:
        raw = st.query_params.get(PREVIEW_CLOSE_QP)
    except Exception:
        return
    if raw is None:
        return
    _dismiss_profile_preview()
    try:
        del st.query_params[PREVIEW_CLOSE_QP]
    except Exception:
        pass


@st.dialog("Preview", width="small", on_dismiss=_dismiss_profile_preview)
def _open_profile_preview_dialog(
    *,
    first_name: str,
    city: str,
    neighbourhood: str,
    dietary: list[str],
    activities: list[str],
    photos: list[dict[str, Any]],
    date_of_birth: Any = None,
    relationship_status: str | None = None,
    open_to_dates: bool | None = None,
) -> None:
    """Modal profile preview — dismiss via X, Escape, or click outside."""
    if st.button("Close preview", key="preview_dialog_close", use_container_width=True):
        _dismiss_profile_preview()
        st.rerun()
    render_profile_preview_card(
        first_name=first_name,
        city=city,
        neighbourhood=neighbourhood,
        dietary=dietary,
        activities=activities,
        photos=photos,
        date_of_birth=date_of_birth,
        relationship_status=relationship_status,
        open_to_dates=open_to_dates,
    )


def render_profile_preview_card(
    *,
    first_name: str,
    city: str,
    neighbourhood: str,
    dietary: list[str],
    activities: list[str],
    photos: list[dict[str, Any]],
    date_of_birth: Any = None,
    relationship_status: str | None = None,
    open_to_dates: bool | None = None,
) -> None:
    """Phone-sized dating card; photo taps flip in-place; dialog scrolls the body."""
    import json

    import streamlit.components.v1 as components

    n = len(photos)
    idx = int(st.session_state.get(PREVIEW_IDX_KEY, 0) or 0)
    if n:
        idx = max(0, min(n - 1, idx))
    else:
        idx = 0
    st.session_state[PREVIEW_IDX_KEY] = idx

    age = _age_from_dob(date_of_birth)
    name = (first_name or "Member").strip() or "Member"
    title = escape(name)
    if age is not None:
        title = f"{title}, {age}"

    place_bits = [b for b in [(neighbourhood or "").strip(), (city or "").strip()] if b]
    place = escape(" · ".join(place_bits)) if place_bits else "Somewhere great"
    status_line = escape(relationship_preview_line(relationship_status, open_to_dates))
    status_html = (
        f'<div class="preview-status">{status_line}</div>' if status_line else ""
    )

    diet_items = [d for d in dietary if d and d != "None"]
    diet_html = _chips_html(diet_items) or (
        '<span class="preview-chip muted">Open to anything</span>'
        if "None" in dietary or not dietary
        else ""
    )
    act_html = _chips_html(list(activities)) or (
        '<span class="preview-chip muted">Still figuring it out</span>'
    )

    uris: list[str] = []
    for photo in photos:
        uris.append(photo_data_uri(photo.get("PHOTO_B64"), photo.get("PHOTO_MIME")) or "")
    uris_json = json.dumps(uris)

    # Photo-only iframe (no inner scroll) — dialog scrolls the text/chips smoothly.
    photo_h = 340
    if n:
        uri0 = uris[idx] if uris[idx] else ""
        img_html = (
            f'<img id="photo" src="{uri0}" alt=""/>'
            if uri0
            else '<div class="empty">No photo</div>'
        )
        segments = "".join(
            f'<span class="seg{" on" if i == idx else ""}"></span>' for i in range(n)
        )
        taps = (
            '<div class="tap left" id="tapL" role="button" aria-label="Previous photo"></div>'
            '<div class="tap right" id="tapR" role="button" aria-label="Next photo"></div>'
            if n > 1
            else ""
        )
        close_btn = (
            '<button type="button" class="close-x" id="closeX" aria-label="Close preview">×</button>'
        )
        nav_script = f"""
<script>
(function() {{
  var URIS = {uris_json};
  var idx = {idx};
  var img = document.getElementById("photo");
  function show(next) {{
    if (!URIS.length) return;
    idx = (next % URIS.length + URIS.length) % URIS.length;
    if (img && URIS[idx]) img.setAttribute("src", URIS[idx]);
    var segs = document.querySelectorAll("#segs .seg");
    for (var i = 0; i < segs.length; i++) {{
      if (i === idx) segs[i].classList.add("on");
      else segs[i].classList.remove("on");
    }}
  }}
  function bind(el, delta) {{
    if (!el) return;
    var startY = 0, startX = 0;
    el.addEventListener("touchstart", function(e) {{
      if (!e.touches || !e.touches.length) return;
      startY = e.touches[0].clientY;
      startX = e.touches[0].clientX;
    }}, {{passive: true}});
    el.addEventListener("click", function(e) {{
      e.preventDefault();
      show(idx + delta);
    }});
    el.addEventListener("touchend", function(e) {{
      if (!e.changedTouches || !e.changedTouches.length) return;
      var dy = Math.abs(e.changedTouches[0].clientY - startY);
      var dx = Math.abs(e.changedTouches[0].clientX - startX);
      if (dy > 12 || dx > 12) return;
      e.preventDefault();
      show(idx + delta);
    }}, {{passive: false}});
  }}
  bind(document.getElementById("tapL"), -1);
  bind(document.getElementById("tapR"), 1);
  function closePreview() {{
    try {{
      var root = window.parent.document;
      var nodes = root.querySelectorAll(
        '[data-testid="stDialog"] button[aria-label="Close"],' +
        '[data-testid="stModal"] button[aria-label="Close"],' +
        '[data-testid="stDialog"] button[kind="header"],' +
        '[data-testid="stDialog"] [data-testid="stBaseButton-header"] button,' +
        '[data-testid="stDialog"] [data-testid="stBaseButton-headerNoPadding"] button'
      );
      for (var i = 0; i < nodes.length; i++) {{
        nodes[i].click();
        return;
      }}
    }} catch (e) {{}}
    try {{
      var u = new URL(window.parent.location.href);
      u.searchParams.set("{PREVIEW_CLOSE_QP}", "1");
      window.parent.location.href = u.toString();
    }} catch (e2) {{}}
  }}
  var cx = document.getElementById("closeX");
  if (cx) {{
    cx.addEventListener("click", function(e) {{
      e.preventDefault();
      e.stopPropagation();
      closePreview();
    }});
  }}
}})();
</script>
"""
        components.html(
            f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
  html, body {{ margin:0; padding:0; background:#2C1A10; }}
  .stage {{
    position:relative; width:100%; height:{photo_h}px;
    background:#2C1A10; overflow:hidden;
    border-radius:18px 18px 0 0;
  }}
  .stage img {{
    width:100%; height:100%; object-fit:cover; object-position:center 18%;
    display:block; pointer-events:none; user-select:none; -webkit-user-drag:none;
  }}
  .empty {{
    display:flex; align-items:center; justify-content:center; height:100%;
    color:rgba(248,230,210,.55); font:15px/1.4 system-ui,sans-serif; padding:1.5rem; text-align:center;
  }}
  .segs {{
    position:absolute; top:12px; left:12px; right:56px; display:flex; gap:4px;
    z-index:3; pointer-events:none;
  }}
  .seg {{ flex:1; height:3px; border-radius:99px; background:rgba(248,230,210,.28); }}
  .seg.on {{ background:#F8E6D2; }}
  .close-x {{
    position:absolute; top:8px; right:8px; z-index:8;
    width:40px; height:40px; border:none; border-radius:999px;
    background:rgba(44,26,16,0.55); color:#F8E6D2;
    font-size:26px; line-height:1; cursor:pointer;
    display:flex; align-items:center; justify-content:center;
    -webkit-tap-highlight-color:transparent;
    backdrop-filter: blur(6px);
  }}
  .close-x:active {{ background:rgba(44,26,16,0.75); }}
  .tap {{
    position:absolute; top:48px; bottom:0; width:50%; z-index:4; cursor:pointer;
    -webkit-tap-highlight-color:transparent; touch-action:pan-y;
  }}
  .tap.left {{ left:0; }}
  .tap.right {{ right:0; }}
  .tap:active {{ background:rgba(248,230,210,.1); }}
</style></head><body>
<div class="stage">
  {close_btn}
  <div class="segs" id="segs">{segments}</div>
  {img_html}
  {taps}
</div>
{nav_script}
</body></html>""",
            height=photo_h,
            scrolling=False,
        )
    else:
        components.html(
            f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
  html,body{{margin:0;background:#2C1A10}}
  .wrap{{position:relative;height:{photo_h}px}}
  .empty{{height:100%;display:flex;align-items:center;justify-content:center;
    color:rgba(248,230,210,.55);font:15px/1.4 system-ui,sans-serif;padding:1.5rem;text-align:center;
    border-radius:18px 18px 0 0}}
  .close-x{{position:absolute;top:8px;right:8px;z-index:8;width:40px;height:40px;border:none;
    border-radius:999px;background:rgba(44,26,16,.55);color:#F8E6D2;font-size:26px;line-height:1;
    cursor:pointer;display:flex;align-items:center;justify-content:center}}
</style></head><body>
<div class="wrap">
  <button type="button" class="close-x" id="closeX" aria-label="Close preview">×</button>
  <div class="empty">Add photos to fill this card</div>
</div>
<script>
(function(){{
  function closePreview(){{
    try {{
      var root = window.parent.document;
      var nodes = root.querySelectorAll(
        '[data-testid="stDialog"] button[aria-label="Close"],' +
        '[data-testid="stDialog"] button[kind="header"]'
      );
      for (var i=0;i<nodes.length;i++){{ nodes[i].click(); return; }}
    }} catch(e){{}}
    try {{
      var u = new URL(window.parent.location.href);
      u.searchParams.set("{PREVIEW_CLOSE_QP}", "1");
      window.parent.location.href = u.toString();
    }} catch(e2){{}}
  }}
  var cx = document.getElementById("closeX");
  if (cx) cx.addEventListener("click", function(e){{ e.preventDefault(); closePreview(); }});
}})();
</script>
</body></html>""",
            height=photo_h,
            scrolling=False,
        )

    st.markdown(
        f"""
        <div class="preview-body-card">
          <div class="preview-name">{title}</div>
          <div class="preview-place">{place}</div>
          {status_html}
          <div class="preview-group-label">Into</div>
          <div class="preview-chips">{act_html}</div>
          <div class="preview-group-label">Dietary</div>
          <div class="preview-chips">{diet_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _progress_html(step: int, total: int = 5) -> str:
    parts: list[str] = []
    labels = ["About you", "Where", "Dietary", "Activities", "Connection"]
    for i in range(1, total + 1):
        cls = "profile-step done" if i < step else ("profile-step active" if i == step else "profile-step")
        parts.append(
            f'<div class="{cls}"><span class="profile-step-num">{i}</span>'
            f'<span class="profile-step-label">{escape(labels[i - 1])}</span></div>'
        )
    return (
        '<div class="profile-progress">'
        + "".join(parts)
        + "</div>"
    )


def profile_setup_css() -> str:
    return """
.profile-progress {
    display: flex;
    gap: 0.45rem;
    margin: 0.5rem 0 1.35rem;
    flex-wrap: nowrap;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    padding-bottom: 0.15rem;
    scrollbar-width: none;
}
.profile-progress::-webkit-scrollbar {
    display: none;
}
.profile-step {
    flex: 1 0 auto;
    min-width: 5.25rem;
    min-height: 44px;
    padding: 0.7rem 0.55rem;
    border-radius: 12px;
    background: rgba(112,77,59,0.07);
    border: 1px solid rgba(112,77,59,0.1);
    text-align: center;
    transition:
        background 280ms cubic-bezier(0.45, 0, 0.55, 1),
        border-color 280ms cubic-bezier(0.45, 0, 0.55, 1),
        transform 220ms cubic-bezier(0.34, 1.56, 0.64, 1),
        box-shadow 280ms cubic-bezier(0.45, 0, 0.55, 1);
}
.profile-step.active {
    background: rgba(211,163,69,0.16);
    border-color: rgba(211,163,69,0.5);
    box-shadow: 0 6px 18px rgba(44,26,16,0.06);
    transform: translateY(-1px);
}
.profile-step.done {
    background: rgba(112,77,59,0.12);
}
.profile-step-num {
    display: block;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.14em;
    color: #D3A345;
    margin-bottom: 0.2rem;
}
.profile-step-label {
    font-size: 12px;
    color: #704D3B;
    letter-spacing: 0.02em;
}
.profile-panel {
    background:
        linear-gradient(165deg, rgba(211,163,69,0.16) 0%, transparent 40%),
        linear-gradient(180deg, #7A5643 0%, #704D3B 55%, #5E3F31 100%);
    border-radius: 20px;
    border: 1px solid rgba(248,230,210,0.08);
    box-shadow: 0 4px 8px rgba(44,26,16,0.05), 0 24px 48px rgba(44,26,16,0.12),
        inset 0 1px 0 rgba(248,230,210,0.1);
    padding: 1.4rem 1.25rem 1.2rem;
    margin-bottom: 1.1rem;
    animation: apres-card-in 520ms cubic-bezier(0.22, 1, 0.36, 1) both;
}
.profile-panel-title {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: 28px;
    font-weight: 500;
    font-style: italic;
    color: #F8E6D2;
    letter-spacing: -0.01em;
    line-height: 1.15;
    margin: 0 0 0.4rem;
}
.profile-panel-sub {
    font-size: 13px;
    line-height: 1.55;
    color: rgba(248,230,210,0.62);
    margin: 0;
}
.apres-avatar {
    width: 56px;
    height: 56px;
    border-radius: 50%;
    object-fit: cover;
    border: 1.5px solid rgba(211,163,69,0.55);
    box-shadow: 0 1px 2px rgba(44,26,16,0.04), 0 4px 12px rgba(44,26,16,0.05),
        0 0 0 4px rgba(248,230,210,0.65);
    display: block;
}
.apres-avatar-row {
    display: flex;
    align-items: center;
    gap: 0.85rem;
    margin: 0 0 0.25rem 0;
}
/* Preview card lives in components.html; keep chip helper styles for markdown fallbacks. */
div[data-testid="stCustomComponentV1"] {
    margin: 0.15rem 0 0.35rem;
}
div[data-testid="stCustomComponentV1"] iframe {
    border: none !important;
    background: transparent !important;
}
/* Preview dialog: visible close affordance + smooth single-axis scroll. */
div[data-testid="stDialog"],
div[data-testid="stModal"] {
    background: #2C1A10 !important;
    color: #F8E6D2 !important;
    border: 1px solid rgba(248, 230, 210, 0.12) !important;
}
div[data-testid="stDialog"] [data-testid="stMarkdownContainer"] p,
div[data-testid="stDialog"] h2,
div[data-testid="stDialog"] [data-testid="stWidgetLabel"] {
    color: #F8E6D2 !important;
}
/* Native Streamlit dialog X */
div[data-testid="stDialog"] button[kind="header"],
div[data-testid="stDialog"] button[aria-label="Close"],
div[data-testid="stDialog"] [data-testid="stBaseButton-header"],
div[data-testid="stDialog"] [data-testid="stBaseButton-headerNoPadding"] button {
    color: #F8E6D2 !important;
    opacity: 1 !important;
    font-size: 1.35rem !important;
    min-width: 44px !important;
    min-height: 44px !important;
}
/* Explicit ✕ button in the dialog body */
div[data-testid="stDialog"] button[kind="secondary"] p,
div[data-testid="stDialog"] button[data-testid="baseButton-secondary"] {
    color: #F8E6D2 !important;
}
div[data-testid="stDialog"] div[data-testid="stHorizontalBlock"]:first-of-type button {
    background: rgba(248, 230, 210, 0.1) !important;
    border: 1px solid rgba(248, 230, 210, 0.22) !important;
    color: #F8E6D2 !important;
    border-radius: 999px !important;
    font-size: 1.15rem !important;
    font-weight: 500 !important;
    min-height: 40px !important;
}
/* One smooth scroll surface — no nested iframe scrolling. */
div[data-testid="stDialog"] [data-testid="stVerticalBlock"] {
    max-height: min(88vh, 900px) !important;
    overflow-y: auto !important;
    overflow-x: hidden !important;
    -webkit-overflow-scrolling: touch !important;
    overscroll-behavior: contain;
    scroll-behavior: smooth;
}
div[data-testid="stDialog"] div[data-testid="stCustomComponentV1"] {
    margin: 0 !important;
}
div[data-testid="stDialog"] div[data-testid="stCustomComponentV1"] iframe {
    display: block !important;
    width: 100% !important;
    max-width: 100% !important;
    border: none !important;
    background: #2C1A10 !important;
    /* Prevent the iframe from becoming a second scroll trap */
    pointer-events: auto;
}
.preview-body-card {
    background:
        linear-gradient(180deg, #704D3B 0%, #5E3F31 100%);
    border-radius: 0 0 18px 18px;
    padding: 1rem 1.05rem 1.25rem;
    margin: 0 0 0.35rem;
    color: #F8E6D2;
}
.preview-body-card .preview-name {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: 28px;
    font-weight: 500;
    font-style: italic;
    color: #F8E6D2;
    line-height: 1.1;
    margin: 0 0 0.25rem;
}
.preview-body-card .preview-place {
    font-size: 13px;
    color: rgba(248,230,210,0.72);
    margin: 0 0 0.3rem;
}
.preview-body-card .preview-status {
    font-size: 12px;
    color: rgba(211,163,69,0.95);
    margin: 0 0 0.65rem;
}
.preview-body-card .preview-group-label {
    font-size: 10px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: rgba(248,230,210,0.45);
    margin: 0.45rem 0 0.28rem;
}
.preview-body-card .preview-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem;
}
.preview-chip {
    display: inline-flex;
    align-items: center;
    min-height: 32px;
    padding: 0.3rem 0.7rem;
    border-radius: 999px;
    background: rgba(248,230,210,0.1);
    border: 1px solid rgba(248,230,210,0.14);
    color: #F8E6D2;
    font-size: 13px;
}
.preview-chip.muted {
    color: rgba(248,230,210,0.55);
    font-style: italic;
}
.partner-banner {
    background:
        linear-gradient(165deg, rgba(211,163,69,0.16) 0%, transparent 42%),
        linear-gradient(180deg, #7A5643 0%, #5E3F31 100%);
    border: 1px solid rgba(248, 230, 210, 0.12);
    border-radius: 16px;
    padding: 1rem 1.1rem 1.05rem;
    margin: 0.35rem 0 0.85rem;
    color: #F8E6D2;
}
.partner-banner-eyebrow {
    font-size: 10px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: rgba(211,163,69,0.95);
    margin: 0 0 0.3rem;
}
.partner-banner-name {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: 26px;
    font-weight: 500;
    font-style: italic;
    line-height: 1.1;
    margin: 0 0 0.25rem;
    color: #F8E6D2;
}
.partner-banner-meta {
    font-size: 13px;
    color: rgba(248,230,210,0.7);
}
.photo-editor-label {
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #7A5B48;
    margin: 0.15rem 0 0.35rem;
}
.photo-editor-hint {
    font-size: 13px;
    color: #7A5B48;
    margin: 0 0 0.65rem;
    line-height: 1.45;
}
.photo-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.4rem;
    margin: 0 0 0.7rem;
}
.photo-grid-cell {
    min-width: 0;
}
.photo-tile {
    position: relative;
    aspect-ratio: 1 / 1;
    width: 100%;
    border-radius: 10px;
    overflow: hidden;
    background:
        linear-gradient(160deg, rgba(211,163,69,0.12), transparent 55%),
        #E8D9C8;
    border: 1px solid rgba(112,77,59,0.12);
}
.photo-tile img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
}
.photo-tile-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    border: 1.5px dashed rgba(112,77,59,0.28);
    background: rgba(112,77,59,0.04);
    color: #7A5B48;
}
.photo-tile-empty .photo-plus {
    font-size: 18px;
    line-height: 1;
    color: #D3A345;
    font-weight: 300;
}
.photo-tile-empty .photo-plus-label {
    font-size: 11px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.photo-main-badge,
.photo-slot-num {
    position: absolute;
    top: 4px;
    left: 4px;
    z-index: 2;
    font-size: 8px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 0.12rem 0.32rem;
    border-radius: 999px;
    backdrop-filter: blur(8px);
}
.photo-main-badge {
    color: #2C1A10;
    background: rgba(211,163,69,0.92);
}
.photo-slot-num {
    color: #F8E6D2;
    background: rgba(44,26,16,0.45);
}
.photo-main-static {
    min-height: 38px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #7A5B48;
    background: rgba(211,163,69,0.14);
    border: 1px solid rgba(211,163,69,0.35);
    border-radius: 8px;
}
div[data-testid="stFileUploader"] section {
    border: 1.5px dashed rgba(112,77,59,0.28) !important;
    background: rgba(112,77,59,0.04) !important;
    border-radius: 14px !important;
    padding: 0.85rem 0.9rem !important;
    transition: border-color 200ms ease, background 200ms ease;
}
div[data-testid="stFileUploader"] section:hover {
    border-color: rgba(211,163,69,0.55) !important;
    background: rgba(211,163,69,0.08) !important;
}
div[data-testid="stFileUploader"] label {
    font-size: 14px !important;
    color: #704D3B !important;
}
div[data-testid="stFileUploader"] small,
div[data-testid="stFileUploader"] [data-testid="stMarkdownContainer"] p {
    color: #7A5B48 !important;
}
@media (max-width: 640px) {
    .photo-editor-hint {
        font-size: 12px;
        margin: 0 0 0.4rem;
    }
    .photo-grid {
        gap: 0.3rem;
        margin-bottom: 0.5rem;
    }
    .photo-tile {
        border-radius: 8px;
    }
}
"""


def render_profile_setup(email: str, existing: dict[str, Any] | None = None) -> None:
    """Full-screen wizard until profile is complete. No main tabs."""
    st.markdown(f"<style>{profile_setup_css()}</style>", unsafe_allow_html=True)

    draft = _get_draft(email, existing)
    if STEP_KEY not in st.session_state and existing:
        # Returning users who only need Connection land on step 5.
        core_ok = bool(
            (existing.get("FIRST_NAME") or "").strip()
            and (existing.get("LAST_NAME") or "").strip()
            and (existing.get("CITY") or "").strip()
            and (existing.get("NEIGHBOURHOOD") or "").strip()
            and (existing.get("DIETARY_NEEDS") or [])
            and (existing.get("ACTIVITY_PREFERENCES") or [])
            and existing.get("ACCEPTED_TERMS_AT")
        )
        if core_ok and not (existing.get("RELATIONSHIP_STATUS") or "").strip():
            st.session_state[STEP_KEY] = 5
    step = int(st.session_state.get(STEP_KEY, 1))
    step = max(1, min(5, step))

    st.markdown(
        '<div class="section-label">Welcome to Après</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="profile-panel">'
        '<div class="profile-panel-title">Build your taste profile</div>'
        '<div class="profile-panel-sub">'
        "A few questions, once, so recommendations fit you. "
        f"Signed in as {escape(email)}."
        "</div></div>",
        unsafe_allow_html=True,
    )
    st.markdown(_progress_html(step), unsafe_allow_html=True)

    if step == 1:
        _render_step_about(draft)
    elif step == 2:
        _render_step_location(draft)
    elif step == 3:
        _render_step_dietary(draft)
    elif step == 4:
        _render_step_activities(draft)
    else:
        _render_step_connection(draft, email)


def _nav(back: bool = True, next_label: str = "Continue", next_key: str = "profile_next") -> tuple[bool, bool]:
    cols = st.columns([1, 1])
    went_back = False
    went_next = False
    with cols[0]:
        if back and st.button("Back", key=f"{next_key}_back", use_container_width=True):
            went_back = True
    with cols[1]:
        if st.button(next_label, key=next_key, type="primary", use_container_width=True):
            went_next = True
    return went_back, went_next


def _render_step_about(draft: dict[str, Any]) -> None:
    st.markdown('<div class="section-label">About you</div>', unsafe_allow_html=True)
    email = str(draft.get("email") or "")
    _hydrate_draft_photos(email, draft, None)
    _render_photo_picker(email, draft, key_prefix="pf")

    first = st.text_input("First name", value=draft.get("first_name") or "", key="pf_first")
    last = st.text_input("Last name", value=draft.get("last_name") or "", key="pf_last")

    dob_val = draft.get("date_of_birth")
    if isinstance(dob_val, datetime):
        dob_val = dob_val.date()
    phone = st.text_input(
        "Phone (optional)",
        value=draft.get("phone") or "",
        placeholder="+1 …",
        key="pf_phone",
    )
    add_dob = st.checkbox(
        "Add date of birth (optional)",
        value=isinstance(dob_val, date),
        key="pf_add_dob",
    )
    dob: date | None = None
    if add_dob:
        dob = st.date_input(
            "Date of birth",
            value=dob_val if isinstance(dob_val, date) else date(1995, 1, 1),
            min_value=date(1920, 1, 1),
            max_value=date.today(),
            format="MM/DD/YYYY",
            key="pf_dob",
        )

    terms = st.checkbox(
        "I agree to the Terms of Service & Privacy Policy",
        value=bool(draft.get("accepted_terms")),
        key="pf_terms",
    )
    marketing = st.checkbox(
        "Send me occasional Après updates (optional)",
        value=bool(draft.get("marketing_opt_in")),
        key="pf_marketing",
    )

    _, nxt = _nav(back=False, next_label="Continue", next_key="profile_step1")
    if nxt:
        if not first.strip() or not last.strip():
            st.error("First and last name are required.")
            return
        if not terms:
            st.error("Please accept the Terms to continue.")
            return
        draft["first_name"] = first.strip()
        draft["last_name"] = last.strip()
        draft["phone"] = phone.strip()
        draft["date_of_birth"] = dob if isinstance(dob, date) else None
        draft["accepted_terms"] = True
        draft["marketing_opt_in"] = bool(marketing)
        _save_draft(draft)
        st.session_state[STEP_KEY] = 2
        st.rerun()


def _render_step_location(draft: dict[str, Any]) -> None:
    st.markdown('<div class="section-label">Where you are</div>', unsafe_allow_html=True)
    city_options = list(DEFAULT_CITIES)
    current_city = draft.get("city_choice") or ""
    if current_city and current_city not in city_options:
        current_city = ""
    city_index = city_options.index(current_city) if current_city in city_options else 0

    choice = st.selectbox(
        "Which city are you based in?",
        city_options,
        index=city_index,
        key="pf_city",
    )
    neighbourhood = _neighbourhood_select(
        choice,
        draft.get("neighbourhood") or "",
        label="Which neighbourhood do you live in?",
        key=f"pf_hood_{choice}",
    )
    st.caption("Never shared with a partner.")

    back, nxt = _nav(next_key="profile_step2")
    if back:
        draft["city_choice"] = choice
        draft["neighbourhood"] = (neighbourhood or "").strip()
        _save_draft(draft)
        st.session_state[STEP_KEY] = 1
        st.rerun()
    if nxt:
        if not choice.strip():
            st.error("Please choose a city.")
            return
        if not neighbourhood:
            st.error("Please choose a neighbourhood.")
            return
        draft["city_choice"] = choice
        draft["neighbourhood"] = neighbourhood.strip()
        _save_draft(draft)
        st.session_state[STEP_KEY] = 3
        st.rerun()


def _render_step_dietary(draft: dict[str, Any]) -> None:
    st.markdown('<div class="section-label">Dietary needs</div>', unsafe_allow_html=True)
    st.caption("Applied to recommendations going forward. Choose all that apply.")
    selected = st.multiselect(
        "Any dietary requirements?",
        options=DIETARY_OPTIONS,
        default=[d for d in (draft.get("dietary_needs") or []) if d in DIETARY_OPTIONS],
        key="pf_dietary",
    )

    back, nxt = _nav(next_key="profile_step3")
    if back:
        draft["dietary_needs"] = list(selected)
        _save_draft(draft)
        st.session_state[STEP_KEY] = 2
        st.rerun()
    if nxt:
        if not selected:
            st.error("Select at least one option (use None if you have no restrictions).")
            return
        # If None + others, keep both — user may mean "mostly none but…"
        draft["dietary_needs"] = list(selected)
        _save_draft(draft)
        st.session_state[STEP_KEY] = 4
        st.rerun()


def _render_step_activities(draft: dict[str, Any]) -> None:
    st.markdown('<div class="section-label">Activity profile</div>', unsafe_allow_html=True)
    st.caption("Which of these genuinely appeal to you? Pick at least one.")
    selected = st.multiselect(
        "Activities you enjoy",
        options=ACTIVITY_OPTIONS,
        default=[a for a in (draft.get("activity_preferences") or []) if a in ACTIVITY_OPTIONS],
        key="pf_activities",
    )

    back, nxt = _nav(next_label="Continue", next_key="profile_step4")
    if back:
        draft["activity_preferences"] = list(selected)
        _save_draft(draft)
        st.session_state[STEP_KEY] = 3
        st.rerun()
    if nxt:
        if not selected:
            st.error("Select at least one activity.")
            return
        draft["activity_preferences"] = list(selected)
        _save_draft(draft)
        st.session_state.pop(SETUP_PARTNER_DIALOG_KEY, None)
        st.session_state[STEP_KEY] = 5
        st.rerun()


def _render_connection_controls(
    draft: dict[str, Any],
    *,
    key_prefix: str,
    hide_partner_invite: bool = False,
) -> tuple[str, bool | None, str]:
    """Shared relationship UI. Returns (status_key, open_to_dates, partner_email)."""
    status_keys = list(RELATIONSHIP_STATUS_KEYS)
    labels = [RELATIONSHIP_STATUS_LABELS[k] for k in status_keys]
    current = (draft.get("relationship_status") or "").strip()
    index = status_keys.index(current) if current in status_keys else 0
    picked_label = st.radio(
        "Where are you at?",
        labels,
        index=index,
        key=f"{key_prefix}_rel_status",
    )
    status = status_keys[labels.index(picked_label)]

    open_to: bool | None = None
    partner_email = ""
    if status in RELATIONSHIP_STATUS_SOLO:
        open_labels = [OPEN_TO_DATES_LABELS[True], OPEN_TO_DATES_LABELS[False]]
        prior = draft.get("open_to_dates")
        open_index = 0 if prior is True else (1 if prior is False else 0)
        open_pick = st.radio(
            "Open to dates?",
            open_labels,
            index=open_index,
            key=f"{key_prefix}_open_dates",
            help="Open to dates makes your profile public for future discovery. "
            "Not right now keeps it private.",
        )
        open_to = open_pick == OPEN_TO_DATES_LABELS[True]
        vis = compute_profile_visibility(status, open_to)
        st.caption(
            "Your profile will be public."
            if vis == "public"
            else "Your profile stays private."
        )
    else:
        st.caption("Coupled profiles stay private — only a linked partner can see yours.")
        if not hide_partner_invite:
            partner_email = st.text_input(
                "Partner email (optional)",
                value=str(draft.get("partner_email_draft") or ""),
                key=f"{key_prefix}_partner_email",
                placeholder="their@email.com",
                help="We’ll send them an in-app request if they already have Après. "
                "Email invites for new accounts come later.",
            ).strip()
        open_to = False

    return status, open_to, partner_email


def _dismiss_setup_partner_dialog() -> None:
    st.session_state[SETUP_PARTNER_DIALOG_KEY] = False


@st.dialog("Partner request", width="small", on_dismiss=_dismiss_setup_partner_dialog)
def _open_setup_partner_request_dialog(
    email: str,
    draft: dict[str, Any],
    request: dict[str, Any],
) -> None:
    """Popup on setup step 5 when someone already invited this email."""
    from_email = str(request.get("FROM_EMAIL") or "")
    rid = str(request.get("REQUEST_ID") or "")
    other = fetch_profile(from_email, include_photo=False) or {}
    name = (other.get("FIRST_NAME") or "").strip() or from_email
    their_status = str(other.get("RELATIONSHIP_STATUS") or "").strip()
    status_label = RELATIONSHIP_STATUS_LABELS.get(their_status, "Coupled up")
    if their_status in RELATIONSHIP_STATUS_SOLO or their_status not in RELATIONSHIP_STATUS_KEYS:
        status_label = RELATIONSHIP_STATUS_LABELS["coupled_up"]

    st.markdown(f"**{escape(name)}** wants to link with you on Après.")
    st.caption(f"{escape(from_email)}")
    st.info(
        f"Accepting links your accounts and sets your status to “{status_label}” "
        "to match theirs."
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Accept", type="primary", use_container_width=True, key="setup_accept_partner"):
            try:
                result = respond_to_partner_request(email, rid, accept=True)
                draft["relationship_status"] = result.get("RELATIONSHIP_STATUS") or "coupled_up"
                draft["open_to_dates"] = False
                draft["partner_email_draft"] = ""
                draft["linked_during_setup"] = True
                draft["linked_partner_email"] = result.get("FROM_EMAIL") or from_email
                _save_draft(draft)
                mark_notifications_read(email)
                st.session_state[SETUP_PARTNER_DIALOG_KEY] = False
                st.session_state[PROFILE_FLASH_KEY] = (
                    f"Linked with {result.get('FROM_NAME') or from_email}. "
                    f"Status set to {RELATIONSHIP_STATUS_LABELS.get(str(result.get('RELATIONSHIP_STATUS')), 'Coupled up')}."
                )
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
    with c2:
        if st.button("Decline", use_container_width=True, key="setup_decline_partner"):
            try:
                respond_to_partner_request(email, rid, accept=False)
                mark_notifications_read(email)
                st.session_state[SETUP_PARTNER_DIALOG_KEY] = False
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))


def _render_step_connection(draft: dict[str, Any], email: str) -> None:
    st.markdown('<div class="section-label">Connection</div>', unsafe_allow_html=True)
    st.caption("How you show up — and who you’re with.")

    flash = st.session_state.pop(PROFILE_FLASH_KEY, None)
    if flash:
        st.success(flash)

    inbound = list_pending_inbound(email)
    # Auto-open popup once per visit to step 5 when a request is waiting.
    if inbound and SETUP_PARTNER_DIALOG_KEY not in st.session_state:
        st.session_state[SETUP_PARTNER_DIALOG_KEY] = True
    if inbound and st.session_state.get(SETUP_PARTNER_DIALOG_KEY):
        _open_setup_partner_request_dialog(email, draft, inbound[0])
    elif inbound:
        from_email = str(inbound[0].get("FROM_EMAIL") or "")
        st.warning(f"You have a partner request from {from_email}.")
        if st.button("Review partner request", key="setup_reopen_partner_req"):
            st.session_state[SETUP_PARTNER_DIALOG_KEY] = True
            st.rerun()

    partner = get_linked_partner(email)
    if partner or draft.get("linked_during_setup"):
        partner = partner or str(draft.get("linked_partner_email") or "")
        status = str(draft.get("relationship_status") or "").strip() or "coupled_up"
        label = RELATIONSHIP_STATUS_LABELS.get(status, status)
        st.success(
            f"Linked with **{partner}**. Your status is **{label}** "
            "(matched to your partner)."
        )
        st.caption("You can finish setup now — or change status later in Profile.")
        back, nxt = _nav(next_label="Finish & start exploring", next_key="profile_step5_linked")
        if back:
            _save_draft(draft)
            st.session_state[STEP_KEY] = 4
            st.rerun()
        if nxt:
            draft["relationship_status"] = status
            draft["open_to_dates"] = False
            draft["partner_email_draft"] = ""
            _save_draft(draft)
            _persist_complete(email, draft)
        return

    status, open_to, partner_email = _render_connection_controls(draft, key_prefix="pf")

    back, nxt = _nav(next_label="Finish & start exploring", next_key="profile_step5")
    if back:
        draft["relationship_status"] = status
        draft["open_to_dates"] = open_to
        draft["partner_email_draft"] = partner_email
        _save_draft(draft)
        st.session_state[STEP_KEY] = 4
        st.rerun()
    if nxt:
        if status not in RELATIONSHIP_STATUS_KEYS:
            st.error("Choose a relationship status.")
            return
        if status in RELATIONSHIP_STATUS_SOLO and open_to is None:
            st.error("Say whether you’re open to dates.")
            return
        draft["relationship_status"] = status
        draft["open_to_dates"] = open_to
        draft["partner_email_draft"] = partner_email
        _save_draft(draft)
        _persist_complete(email, draft)


def _persist_complete(email: str, draft: dict[str, Any]) -> None:
    city = _resolved_city(draft)
    if not draft.get("accepted_terms"):
        st.error("Terms must be accepted.")
        return
    status = str(draft.get("relationship_status") or "").strip()
    open_to = draft.get("open_to_dates")
    # Photos auto-save on edit. Never sync an empty draft gallery here — that
    # wiped links when returning users finished Connection without hydrating photos.
    update_photos = bool(draft.get("photos_changed")) and bool(draft.get("photos"))
    try:
        upsert_profile(
            email=email,
            first_name=str(draft.get("first_name") or ""),
            last_name=str(draft.get("last_name") or ""),
            city=city,
            neighbourhood=str(draft.get("neighbourhood") or ""),
            dietary_needs=list(draft.get("dietary_needs") or []),
            activity_preferences=list(draft.get("activity_preferences") or []),
            accepted_terms_at=datetime.utcnow(),
            marketing_opt_in=bool(draft.get("marketing_opt_in")),
            date_of_birth=draft.get("date_of_birth")
            if isinstance(draft.get("date_of_birth"), date)
            else None,
            phone=str(draft.get("phone") or "") or None,
            relationship_status=status or None,
            open_to_dates=open_to if isinstance(open_to, bool) else None,
            photos=list(draft.get("photos") or []) if update_photos else None,
            update_photos=update_photos,
            mark_complete=True,
        )
        partner_email = str(draft.get("partner_email_draft") or "").strip()
        if status in RELATIONSHIP_STATUS_PARTNERED and partner_email:
            try:
                result = create_partner_request(email, partner_email)
                if result.get("RECIPIENT_HAS_ACCOUNT"):
                    st.session_state[PROFILE_FLASH_KEY] = (
                        f"Partner request sent to {partner_email}."
                    )
                else:
                    st.session_state[PROFILE_FLASH_KEY] = (
                        f"Invite saved for {partner_email}. "
                        "Email delivery comes later — share Après with them for now."
                    )
            except Exception as invite_exc:  # noqa: BLE001
                st.session_state[PROFILE_FLASH_KEY] = (
                    f"Profile saved, but partner invite failed: {invite_exc}"
                )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not save your profile: {exc}")
        return

    st.session_state.pop(DRAFT_KEY, None)
    st.session_state.pop(STEP_KEY, None)
    clear_profile_cache()
    st.session_state["just_completed_profile"] = True
    st.session_state["just_completed_profile_name"] = str(draft.get("first_name") or "").strip()
    st.toast("Profile saved. Welcome to Après.")
    st.rerun()


def render_profile_settings(email: str, profile: dict[str, Any]) -> None:
    """Edit surface for users who already completed basic setup."""
    st.markdown(f"<style>{profile_setup_css()}</style>", unsafe_allow_html=True)
    _consume_preview_close_query()
    st.markdown('<div class="section-label">Your profile</div>', unsafe_allow_html=True)
    st.caption("Photos save as you go. Use preview to see what others would see.")

    flash = st.session_state.pop(PROFILE_FLASH_KEY, None)
    if flash:
        st.success(flash)

    draft = _get_draft(email, profile)
    _hydrate_draft_photos(email, draft, profile)

    _render_partner_banner(email)

    preview_open = bool(st.session_state.get(PREVIEW_OPEN_KEY))
    if st.button(
        "Preview as others see you",
        type="primary",
        use_container_width=True,
        key="preview_open",
    ):
        st.session_state[PREVIEW_OPEN_KEY] = True
        st.session_state[PREVIEW_IDX_KEY] = 0
        preview_open = True

    if preview_open:
        # Prefer live form values when present (from prior run / current widgets).
        first_live = str(st.session_state.get("edit_first") or draft.get("first_name") or profile.get("FIRST_NAME") or "")
        city_live = str(
            st.session_state.get("edit_city")
            or draft.get("city_choice")
            or profile.get("CITY")
            or ""
        )
        hood_key = f"edit_hood_{city_live}" if city_live else None
        hood_live = str(
            (st.session_state.get(hood_key) if hood_key else None)
            or draft.get("neighbourhood")
            or profile.get("NEIGHBOURHOOD")
            or ""
        )
        dietary_live = list(
            st.session_state.get("edit_dietary")
            or draft.get("dietary_needs")
            or profile.get("DIETARY_NEEDS")
            or []
        )
        activities_live = list(
            st.session_state.get("edit_activities")
            or draft.get("activity_preferences")
            or profile.get("ACTIVITY_PREFERENCES")
            or []
        )
        dob_live = draft.get("date_of_birth") or profile.get("DATE_OF_BIRTH")
        if st.session_state.get("edit_add_dob") and st.session_state.get("edit_dob"):
            dob_live = st.session_state.get("edit_dob")
        status_live = str(
            st.session_state.get("edit_rel_status_key")
            or draft.get("relationship_status")
            or profile.get("RELATIONSHIP_STATUS")
            or ""
        )
        # Radio stores label; map back if needed
        if status_live not in RELATIONSHIP_STATUS_KEYS:
            rev = {v: k for k, v in RELATIONSHIP_STATUS_LABELS.items()}
            status_live = rev.get(status_live, status_live)
        open_live = draft.get("open_to_dates")
        if "edit_open_dates" in st.session_state:
            open_pick = st.session_state.get("edit_open_dates")
            if open_pick == OPEN_TO_DATES_LABELS[True]:
                open_live = True
            elif open_pick == OPEN_TO_DATES_LABELS[False]:
                open_live = False

        _open_profile_preview_dialog(
            first_name=first_live,
            city=city_live,
            neighbourhood=hood_live,
            dietary=dietary_live,
            activities=activities_live,
            photos=list(draft.get("photos") or []),
            date_of_birth=dob_live,
            relationship_status=status_live or None,
            open_to_dates=open_live if isinstance(open_live, bool) else None,
        )

    _render_partner_inbox(email)
    _render_connection_settings(email, draft, profile)

    st.markdown('<div class="section-label">Go deeper</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="empty-state" style="margin-top:0;">'
        '<div class="empty-state-eyebrow">Extended profile</div>'
        '<div class="empty-state-title">Food & drink · Activities</div>'
        '<div class="empty-state-mark"></div>'
        "<p>Core setup is done. Deeper buckets (cuisines, adventure level, deal-breakers) "
        "will live here so recommendations can get sharper over time.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    _render_photo_picker(email, draft, key_prefix="edit")

    c1, c2 = st.columns(2)
    with c1:
        first = st.text_input("First name", value=draft["first_name"], key="edit_first")
    with c2:
        last = st.text_input("Last name", value=draft["last_name"], key="edit_last")

    phone = st.text_input("Phone (optional)", value=draft.get("phone") or "", key="edit_phone")
    dob_val = draft.get("date_of_birth")
    if isinstance(dob_val, datetime):
        dob_val = dob_val.date()
    add_dob = st.checkbox(
        "Include date of birth",
        value=isinstance(dob_val, date),
        key="edit_add_dob",
    )
    dob: date | None = None
    if add_dob:
        dob = st.date_input(
            "Date of birth",
            value=dob_val if isinstance(dob_val, date) else date(1995, 1, 1),
            min_value=date(1920, 1, 1),
            max_value=date.today(),
            format="MM/DD/YYYY",
            key="edit_dob",
        )

    city_options = list(DEFAULT_CITIES)
    city_choice = draft.get("city_choice") or ""
    if city_choice not in city_options:
        city_choice = city_options[0]
    choice = st.selectbox(
        "City",
        city_options,
        index=city_options.index(city_choice),
        key="edit_city",
    )
    neighbourhood = _neighbourhood_select(
        choice,
        draft.get("neighbourhood") or "",
        label="Neighbourhood",
        key=f"edit_hood_{choice}",
    )
    dietary = st.multiselect(
        "Dietary needs",
        DIETARY_OPTIONS,
        default=[d for d in draft.get("dietary_needs") or [] if d in DIETARY_OPTIONS],
        key="edit_dietary",
    )
    activities = st.multiselect(
        "Activities",
        ACTIVITY_OPTIONS,
        default=[a for a in draft.get("activity_preferences") or [] if a in ACTIVITY_OPTIONS],
        key="edit_activities",
    )
    marketing = st.checkbox(
        "Marketing emails",
        value=bool(draft.get("marketing_opt_in")),
        key="edit_marketing",
    )

    if st.button("Save profile", type="primary", use_container_width=True, key="edit_save"):
        if not first.strip() or not last.strip() or not choice or not neighbourhood:
            st.error(
                "Name, city, and neighbourhood are required. "
                "If you changed city, pick a neighbourhood again."
            )
            return
        if not dietary:
            st.error("Select at least one dietary option (None is fine).")
            return
        if not activities:
            st.error("Select at least one activity.")
            return
        status = str(draft.get("relationship_status") or profile.get("RELATIONSHIP_STATUS") or "").strip()
        open_to = draft.get("open_to_dates")
        if "edit_rel_status" in st.session_state:
            # Values written by _render_connection_settings into draft on interaction;
            # re-read from draft which Connection section updates before save via widgets.
            pass
        # Prefer live Connection widgets if present this run
        status_label = st.session_state.get("edit_rel_status")
        if status_label in RELATIONSHIP_STATUS_LABELS.values():
            status = {v: k for k, v in RELATIONSHIP_STATUS_LABELS.items()}[status_label]
        open_pick = st.session_state.get("edit_open_dates")
        if status in RELATIONSHIP_STATUS_SOLO:
            if open_pick == OPEN_TO_DATES_LABELS[True]:
                open_to = True
            elif open_pick == OPEN_TO_DATES_LABELS[False]:
                open_to = False
        elif status in RELATIONSHIP_STATUS_PARTNERED:
            open_to = False
        if status not in RELATIONSHIP_STATUS_KEYS:
            st.error("Choose a relationship status in Connection.")
            return
        if status in RELATIONSHIP_STATUS_SOLO and open_to is None:
            st.error("Say whether you’re open to dates.")
            return
        try:
            with st.spinner("Saving…"):
                saved = upsert_profile(
                    email=email,
                    first_name=first.strip(),
                    last_name=last.strip(),
                    city=choice.strip(),
                    neighbourhood=str(neighbourhood).strip(),
                    dietary_needs=list(dietary),
                    activity_preferences=list(activities),
                    accepted_terms_at=profile.get("ACCEPTED_TERMS_AT") or datetime.utcnow(),
                    marketing_opt_in=bool(marketing),
                    date_of_birth=dob if isinstance(dob, date) else None,
                    phone=phone.strip() or None,
                    relationship_status=status,
                    open_to_dates=open_to if isinstance(open_to, bool) else None,
                    photos=list(draft.get("photos") or []),
                    update_photos=bool(draft.get("photos_changed")),
                    mark_complete=True,
                    existing=profile,
                )
        except Exception as exc:  # noqa: BLE001
            st.session_state[PROFILE_FLASH_KEY] = None
            st.error(f"Could not save: {exc}")
            return
        if not is_profile_complete(saved):
            st.error("Profile is still incomplete. Check required fields.")
            return
        partner_email = str(st.session_state.get("edit_partner_email") or "").strip()
        if status in RELATIONSHIP_STATUS_PARTNERED and partner_email and not get_linked_partner(email):
            try:
                result = create_partner_request(email, partner_email)
                if result.get("ALREADY_PENDING"):
                    flash_extra = f" · partner request already pending for {partner_email}"
                elif result.get("RECIPIENT_HAS_ACCOUNT"):
                    flash_extra = f" · partner request sent to {partner_email}"
                else:
                    flash_extra = (
                        f" · invite saved for {partner_email} "
                        "(email delivery later)"
                    )
            except Exception as invite_exc:  # noqa: BLE001
                flash_extra = f" · partner invite failed: {invite_exc}"
        else:
            flash_extra = ""
        st.session_state.pop(DRAFT_KEY, None)
        clear_profile_cache()
        st.session_state[PROFILE_FLASH_KEY] = (
            f"Saved · {saved.get('CITY')} · {saved.get('NEIGHBOURHOOD')}{flash_extra}"
        )
        st.rerun()


def _partner_display_name(partner_email: str) -> tuple[str, dict[str, Any]]:
    """Return (display_name, profile_row) for a linked partner."""
    other = fetch_profile(partner_email, include_photo=False) or {}
    first = (other.get("FIRST_NAME") or "").strip()
    last = (other.get("LAST_NAME") or "").strip()
    if first and last:
        name = f"{first} {last}"
    elif first:
        name = first
    else:
        name = partner_email
    return name, other


def _render_partner_banner(email: str) -> None:
    """Top-of-profile callout when a partner is linked."""
    partner = get_linked_partner(email)
    if not partner:
        return
    name, other = _partner_display_name(partner)
    status = relationship_preview_line(
        other.get("RELATIONSHIP_STATUS"),
        other.get("OPEN_TO_DATES"),
    )
    status_bit = f" · {escape(status)}" if status else ""
    st.markdown(
        f"""
        <div class="partner-banner">
          <div class="partner-banner-eyebrow">Your partner</div>
          <div class="partner-banner-name">{escape(name)}</div>
          <div class="partner-banner-meta">{escape(partner)}{status_bit}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    b1, b2 = st.columns(2)
    with b1:
        if st.button("View their profile", use_container_width=True, key="banner_view_partner"):
            st.session_state[PARTNER_PREVIEW_KEY] = True
            st.session_state[PREVIEW_IDX_KEY] = 0
            st.rerun()
    with b2:
        if st.button("Unlink", use_container_width=True, key="banner_unlink_partner"):
            unlink_partner(email)
            st.session_state[PARTNER_PREVIEW_KEY] = False
            st.session_state[PROFILE_FLASH_KEY] = f"Unlinked from {name}."
            st.rerun()

    if st.session_state.get(PARTNER_PREVIEW_KEY):
        if can_view_profile(email, partner):
            photos = list_profile_photos(partner, include_bytes=True)
            _open_profile_preview_dialog(
                first_name=str(other.get("FIRST_NAME") or name),
                city=str(other.get("CITY") or ""),
                neighbourhood=str(other.get("NEIGHBOURHOOD") or ""),
                dietary=list(other.get("DIETARY_NEEDS") or []),
                activities=list(other.get("ACTIVITY_PREFERENCES") or []),
                photos=[
                    {
                        "PHOTO_ID": p.get("PHOTO_ID"),
                        "PHOTO_B64": p.get("PHOTO_B64"),
                        "PHOTO_MIME": p.get("PHOTO_MIME"),
                    }
                    for p in photos
                    if p.get("PHOTO_B64")
                ],
                date_of_birth=other.get("DATE_OF_BIRTH"),
                relationship_status=other.get("RELATIONSHIP_STATUS"),
                open_to_dates=other.get("OPEN_TO_DATES"),
            )
        else:
            st.warning("You can’t view that profile.")
            st.session_state[PARTNER_PREVIEW_KEY] = False


def _render_partner_inbox(email: str) -> None:
    inbound = list_pending_inbound(email)
    notifs = list_notifications(email, limit=20)
    if not inbound and not notifs:
        return
    st.markdown('<div class="section-label">Inbox</div>', unsafe_allow_html=True)
    unread = [n for n in notifs if not n.get("READ_AT")]
    if unread:
        st.caption(f"{len(unread)} unread notification{'s' if len(unread) != 1 else ''}.")
        if st.button("Mark all read", key="notif_mark_all"):
            mark_notifications_read(email)
            st.rerun()

    for req in inbound:
        from_email = str(req.get("FROM_EMAIL") or "")
        rid = str(req.get("REQUEST_ID") or "")
        st.info(f"Partner request from **{from_email}**")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Accept", key=f"accept_{rid}", use_container_width=True, type="primary"):
                try:
                    respond_to_partner_request(email, rid, accept=True)
                    mark_notifications_read(email)
                    st.session_state[PROFILE_FLASH_KEY] = f"You’re linked with {from_email}."
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
        with c2:
            if st.button("Decline", key=f"decline_{rid}", use_container_width=True):
                try:
                    respond_to_partner_request(email, rid, accept=False)
                    mark_notifications_read(email)
                    st.session_state[PROFILE_FLASH_KEY] = "Partner request declined."
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))

    for n in notifs[:8]:
        kind = str(n.get("KIND") or "")
        payload = n.get("PAYLOAD") or {}
        if kind == "partner_accepted":
            st.caption(f"Accepted — linked with {payload.get('to_email') or payload.get('from_email')}")
        elif kind == "partner_declined":
            st.caption(f"Declined — {payload.get('to_email') or 'partner'} said not now.")
        elif kind == "partner_request" and not inbound:
            st.caption(f"Request from {payload.get('from_email')}")


def _render_connection_settings(
    email: str,
    draft: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    st.markdown('<div class="section-label">Connection</div>', unsafe_allow_html=True)
    partner = get_linked_partner(email)
    if partner:
        name, _other = _partner_display_name(partner)
        st.caption(f"Linked with {name} ({partner}). Change status below if needed.")
        # Skip partner-email invite while already linked.
        status, open_to, _ = _render_connection_controls(
            draft, key_prefix="edit", hide_partner_invite=True
        )
        draft["relationship_status"] = status
        draft["open_to_dates"] = open_to
        draft["partner_email_draft"] = ""
        _save_draft(draft)
    else:
        status, open_to, partner_email = _render_connection_controls(draft, key_prefix="edit")
        draft["relationship_status"] = status
        draft["open_to_dates"] = open_to
        draft["partner_email_draft"] = partner_email
        _save_draft(draft)

    outbound = list_pending_outbound(email)
    for req in outbound:
        to_email = str(req.get("TO_EMAIL") or "")
        rid = str(req.get("REQUEST_ID") or "")
        st.caption(f"Pending invite → {to_email}")
        if st.button("Cancel request", key=f"cancel_{rid}"):
            cancel_partner_request(email, rid)
            st.session_state[PROFILE_FLASH_KEY] = "Partner request cancelled."
            st.rerun()
