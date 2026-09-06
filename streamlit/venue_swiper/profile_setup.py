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
    neighbourhoods_for_city,
)
from user_profiles_store import (
    MAX_PROFILE_PHOTOS,
    clear_profile_cache,
    is_profile_complete,
    list_profile_photos,
    photo_bytes,
    photo_data_uri,
    prepare_profile_photo,
    save_profile_photos,
    upsert_profile,
)

DRAFT_KEY = "profile_draft"
STEP_KEY = "profile_setup_step"
PREVIEW_OPEN_KEY = "apres_profile_preview_open"
PREVIEW_IDX_KEY = "apres_preview_photo_idx"
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
        "photos": [],
        "photos_changed": False,
        "photos_loaded": False,
    }


def _get_draft(email: str, existing: dict[str, Any] | None) -> dict[str, Any]:
    draft = st.session_state.get(DRAFT_KEY)
    if not isinstance(draft, dict) or draft.get("email") != email:
        draft = _empty_draft(email, existing)
        st.session_state[DRAFT_KEY] = draft
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


def render_profile_preview_card(
    *,
    first_name: str,
    city: str,
    neighbourhood: str,
    dietary: list[str],
    activities: list[str],
    photos: list[dict[str, Any]],
    date_of_birth: Any = None,
) -> None:
    """Dating-app style preview: photo stack + concise identity / taste."""
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

    if n:
        photo = photos[idx]
        uri = photo_data_uri(photo.get("PHOTO_B64"), photo.get("PHOTO_MIME"))
        img_html = (
            f'<img class="preview-photo" src="{uri}" alt="" />'
            if uri
            else '<div class="preview-photo preview-photo-empty">No photo</div>'
        )
        segments = "".join(
            f'<span class="preview-seg{" on" if i == idx else ""}"></span>' for i in range(n)
        )
        seg_html = f'<div class="preview-segments" aria-hidden="true">{segments}</div>'
    else:
        img_html = '<div class="preview-photo preview-photo-empty">Add photos to fill this card</div>'
        seg_html = ""

    diet_html = _chips_html([d for d in dietary if d and d != "None"]) or (
        '<span class="preview-chip muted">Open to anything</span>'
        if "None" in dietary or not dietary
        else ""
    )
    act_html = _chips_html(list(activities)) or (
        '<span class="preview-chip muted">Still figuring it out</span>'
    )

    st.markdown(
        f"""
        <div class="preview-card">
          <div class="preview-photo-stage">
            {seg_html}
            {img_html}
          </div>
        """,
        unsafe_allow_html=True,
    )

    if n > 1:
        left, right = st.columns(2, gap="small")
        with left:
            if st.button(
                "\u200b",
                key="preview_tap_left",
                use_container_width=True,
            ):
                st.session_state[PREVIEW_IDX_KEY] = (idx - 1) % n
                st.rerun()
        with right:
            if st.button(
                "\u200b",
                key="preview_tap_right",
                use_container_width=True,
            ):
                st.session_state[PREVIEW_IDX_KEY] = (idx + 1) % n
                st.rerun()

    st.markdown(
        f"""
          <div class="preview-body">
            <div class="preview-eyebrow">How others see you</div>
            <div class="preview-name">{title}</div>
            <div class="preview-place">{place}</div>
            <div class="preview-group-label">Into</div>
            <div class="preview-chips">{act_html}</div>
            <div class="preview-group-label">Dietary</div>
            <div class="preview-chips">{diet_html}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _progress_html(step: int, total: int = 4) -> str:
    parts: list[str] = []
    labels = ["About you", "Where", "Dietary", "Activities"]
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
.preview-card {
    background:
        linear-gradient(165deg, rgba(211,163,69,0.18) 0%, transparent 38%),
        linear-gradient(180deg, #7A5643 0%, #704D3B 55%, #5E3F31 100%);
    border-radius: 22px;
    border: 1px solid rgba(248, 230, 210, 0.1);
    box-shadow: 0 4px 8px rgba(44,26,16,0.05), 0 24px 48px rgba(44,26,16,0.14),
        inset 0 1px 0 rgba(248,230,210,0.1);
    overflow: hidden;
    margin: 0.35rem 0 0.85rem;
    animation: apres-card-in 480ms cubic-bezier(0.22, 1, 0.36, 1) both;
}
.preview-photo-stage {
    position: relative;
    background: #2C1A10;
    min-height: 340px;
}
.preview-photo {
    width: 100%;
    height: min(62vh, 420px);
    object-fit: cover;
    display: block;
    pointer-events: none;
    user-select: none;
}
/* Tap zones: the column row directly under the photo stage markdown */
div[data-testid="stMarkdown"]:has(.preview-photo-stage) + div[data-testid="stHorizontalBlock"] {
    margin-top: calc(-1 * min(62vh, 420px)) !important;
    margin-bottom: 0 !important;
    height: min(62vh, 420px);
    position: relative;
    z-index: 12;
    gap: 0 !important;
}
div[data-testid="stMarkdown"]:has(.preview-photo-stage) + div[data-testid="stHorizontalBlock"] > div {
    padding: 0 !important;
}
div[data-testid="stMarkdown"]:has(.preview-photo-stage) + div[data-testid="stHorizontalBlock"] .stButton {
    height: 100%;
}
div[data-testid="stMarkdown"]:has(.preview-photo-stage) + div[data-testid="stHorizontalBlock"] .stButton > button {
    height: min(62vh, 420px) !important;
    min-height: min(62vh, 420px) !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: transparent !important;
    cursor: pointer;
}
div[data-testid="stMarkdown"]:has(.preview-photo-stage) + div[data-testid="stHorizontalBlock"]
  > div:first-child .stButton > button:hover {
    background: linear-gradient(90deg, rgba(248,230,210,0.14), transparent 72%) !important;
}
div[data-testid="stMarkdown"]:has(.preview-photo-stage) + div[data-testid="stHorizontalBlock"]
  > div:last-child .stButton > button:hover {
    background: linear-gradient(270deg, rgba(248,230,210,0.14), transparent 72%) !important;
}
div[data-testid="stMarkdown"]:has(.preview-photo-stage) + div[data-testid="stHorizontalBlock"]
  .stButton > button:focus {
    outline: none !important;
    box-shadow: none !important;
}
/* Body markdown closes the card visually under the overlay */
div[data-testid="stMarkdown"]:has(.preview-body) {
    position: relative;
    z-index: 2;
}
.preview-photo-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 280px;
    color: rgba(248,230,210,0.55);
    font-size: 15px;
    padding: 1.5rem;
    text-align: center;
}
.preview-segments {
    position: absolute;
    top: 10px;
    left: 10px;
    right: 10px;
    display: flex;
    gap: 4px;
    z-index: 2;
}
.preview-seg {
    flex: 1;
    height: 3px;
    border-radius: 999px;
    background: rgba(248,230,210,0.28);
}
.preview-seg.on {
    background: #F8E6D2;
    box-shadow: 0 0 0 1px rgba(211,163,69,0.35);
}
.preview-count {
    position: absolute;
    right: 12px;
    bottom: 12px;
    z-index: 2;
    font-size: 11px;
    letter-spacing: 0.08em;
    color: #F8E6D2;
    background: rgba(44,26,16,0.45);
    padding: 0.35rem 0.55rem;
    border-radius: 999px;
}
.preview-body {
    padding: 1.15rem 1.2rem 1.35rem;
}
.preview-eyebrow {
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: #D3A345;
    margin: 0 0 0.45rem;
}
.preview-name {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: clamp(28px, 7vw, 34px);
    font-weight: 500;
    font-style: italic;
    color: #F8E6D2;
    line-height: 1.1;
    margin: 0 0 0.35rem;
}
.preview-place {
    font-size: 14px;
    color: rgba(248,230,210,0.72);
    margin: 0 0 1rem;
}
.preview-group-label {
    font-size: 10px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: rgba(248,230,210,0.45);
    margin: 0.65rem 0 0.4rem;
}
.preview-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
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
    step = int(st.session_state.get(STEP_KEY, 1))
    step = max(1, min(4, step))

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
    else:
        _render_step_activities(draft, email)


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


def _render_step_activities(draft: dict[str, Any], email: str) -> None:
    st.markdown('<div class="section-label">Activity profile</div>', unsafe_allow_html=True)
    st.caption("Which of these genuinely appeal to you? Pick at least one.")
    selected = st.multiselect(
        "Activities you enjoy",
        options=ACTIVITY_OPTIONS,
        default=[a for a in (draft.get("activity_preferences") or []) if a in ACTIVITY_OPTIONS],
        key="pf_activities",
    )

    back, nxt = _nav(next_label="Finish & start exploring", next_key="profile_step4")
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
        _persist_complete(email, draft)


def _persist_complete(email: str, draft: dict[str, Any]) -> None:
    city = _resolved_city(draft)
    if not draft.get("accepted_terms"):
        st.error("Terms must be accepted.")
        return
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
            photos=list(draft.get("photos") or []),
            update_photos=True,
            mark_complete=True,
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
    st.markdown('<div class="section-label">Your profile</div>', unsafe_allow_html=True)
    st.caption("Photos save as you go. Use preview to see what others would see.")

    flash = st.session_state.pop(PROFILE_FLASH_KEY, None)
    if flash:
        st.success(flash)

    draft = _get_draft(email, profile)
    _hydrate_draft_photos(email, draft, profile)

    preview_open = bool(st.session_state.get(PREVIEW_OPEN_KEY))
    toggle_cols = st.columns([1, 1])
    with toggle_cols[0]:
        if preview_open:
            if st.button("Close preview", use_container_width=True, key="preview_close"):
                st.session_state[PREVIEW_OPEN_KEY] = False
                st.rerun()
        else:
            if st.button(
                "Preview as others see you",
                type="primary",
                use_container_width=True,
                key="preview_open",
            ):
                st.session_state[PREVIEW_OPEN_KEY] = True
                st.session_state[PREVIEW_IDX_KEY] = 0
                st.rerun()

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

        render_profile_preview_card(
            first_name=first_live,
            city=city_live,
            neighbourhood=hood_live,
            dietary=dietary_live,
            activities=activities_live,
            photos=list(draft.get("photos") or []),
            date_of_birth=dob_live,
        )
        st.markdown("---")

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
        st.session_state.pop(DRAFT_KEY, None)
        clear_profile_cache()
        st.session_state[PROFILE_FLASH_KEY] = (
            f"Saved · {saved.get('CITY')} · {saved.get('NEIGHBOURHOOD')}"
        )
        st.rerun()
