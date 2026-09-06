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
    clear_profile_cache,
    fetch_profile_photo,
    is_profile_complete,
    photo_bytes,
    prepare_profile_photo,
    upsert_profile,
)

DRAFT_KEY = "profile_draft"
STEP_KEY = "profile_setup_step"


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
            "photo_b64": existing.get("PROFILE_PHOTO_B64"),
            "photo_mime": existing.get("PROFILE_PHOTO_MIME"),
            "photo_changed": False,
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
        "photo_b64": None,
        "photo_mime": None,
        "photo_changed": False,
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


def _hydrate_draft_photo(email: str, draft: dict[str, Any], profile: dict[str, Any]) -> None:
    """Load photo bytes once into the draft when the profile only has a flag."""
    if draft.get("photo_b64") or draft.get("photo_changed"):
        return
    if not profile.get("HAS_PROFILE_PHOTO"):
        return
    try:
        photo = fetch_profile_photo(email)
    except Exception:
        return
    if not photo or not photo.get("PROFILE_PHOTO_B64"):
        return
    draft["photo_b64"] = photo.get("PROFILE_PHOTO_B64")
    draft["photo_mime"] = photo.get("PROFILE_PHOTO_MIME") or "image/jpeg"
    _save_draft(draft)


def _render_photo_picker(draft: dict[str, Any], *, key_prefix: str) -> None:
    """Optional profile photo upload; mutates draft in place when Continue/Save runs.

    Streamlit file_uploader only yields a file on the run it was chosen, so we
    process immediately into draft photo_b64 when a new upload appears.
    """
    st.markdown("Profile photo (optional)")
    current_bytes = photo_bytes(draft.get("photo_b64"))
    if current_bytes:
        left, right = st.columns([1, 3])
        with left:
            st.image(current_bytes, width=96)
        with right:
            st.caption("Current photo")
            if st.button("Remove photo", key=f"{key_prefix}_clear_photo"):
                draft["photo_b64"] = None
                draft["photo_mime"] = None
                draft["photo_changed"] = True
                draft.pop("_photo_upload_marker", None)
                st.session_state.pop(f"{key_prefix}_photo_upload", None)
                _save_draft(draft)
                st.rerun()

    uploaded = st.file_uploader(
        "Upload a photo",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=False,
        key=f"{key_prefix}_photo_upload",
        label_visibility="collapsed",
    )
    if uploaded is not None:
        # Dedupe: same name+size already applied this session.
        marker = f"{uploaded.name}:{getattr(uploaded, 'size', 0)}"
        if draft.get("_photo_upload_marker") != marker:
            try:
                b64, mime = prepare_profile_photo(uploaded)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not use that photo: {exc}")
            else:
                draft["photo_b64"] = b64
                draft["photo_mime"] = mime
                draft["photo_changed"] = True
                draft["_photo_upload_marker"] = marker
                _save_draft(draft)
                st.image(photo_bytes(b64), width=96)
                st.caption("Photo ready. It’ll save with your profile.")
    st.caption("JPG, PNG, or WebP · under 5 MB · resized to fit.")


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
    _render_photo_picker(draft, key_prefix="pf")

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
            profile_photo_b64=draft.get("photo_b64"),
            profile_photo_mime=draft.get("photo_mime"),
            update_photo=bool(draft.get("photo_changed")),
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


PROFILE_FLASH_KEY = "apres_profile_flash"


def render_profile_settings(email: str, profile: dict[str, Any]) -> None:
    """Edit surface for users who already completed basic setup."""
    st.markdown('<div class="section-label">Your profile</div>', unsafe_allow_html=True)
    st.caption("Update your taste profile anytime. Ratings and plans stay as they are.")
    st.markdown(f"<style>{profile_setup_css()}</style>", unsafe_allow_html=True)

    flash = st.session_state.pop(PROFILE_FLASH_KEY, None)
    if flash:
        st.success(flash)

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

    draft = _get_draft(email, profile)
    _hydrate_draft_photo(email, draft, profile)
    _render_photo_picker(draft, key_prefix="edit")

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
            st.error("Name, city, and neighbourhood are required. If you changed city, pick a neighbourhood again.")
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
                    profile_photo_b64=draft.get("photo_b64"),
                    profile_photo_mime=draft.get("photo_mime"),
                    update_photo=bool(draft.get("photo_changed")),
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
