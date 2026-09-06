"""Après profile setup wizard and profile edit UI."""

from __future__ import annotations

from datetime import date, datetime
from html import escape
from typing import Any

import streamlit as st

from profile_options import (
    ACTIVITY_OPTIONS,
    CUSTOM_CITY_SENTINEL,
    DEFAULT_CITIES,
    DIETARY_OPTIONS,
)
from user_profiles_store import (
    clear_profile_cache,
    is_profile_complete,
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
        custom_city = "" if known_city else city
        dob = existing.get("DATE_OF_BIRTH")
        return {
            "email": email,
            "first_name": existing.get("FIRST_NAME") or "",
            "last_name": existing.get("LAST_NAME") or "",
            "date_of_birth": dob,
            "phone": existing.get("PHONE") or "",
            "city_choice": known_city or (CUSTOM_CITY_SENTINEL if custom_city else ""),
            "custom_city": custom_city,
            "neighbourhood": existing.get("NEIGHBOURHOOD") or "",
            "dietary_needs": dietary,
            "activity_preferences": activities,
            "accepted_terms": bool(existing.get("ACCEPTED_TERMS_AT")),
            "marketing_opt_in": bool(existing.get("MARKETING_OPT_IN")),
        }
    return {
        "email": email,
        "first_name": "",
        "last_name": "",
        "date_of_birth": None,
        "phone": "",
        "city_choice": "",
        "custom_city": "",
        "neighbourhood": "",
        "dietary_needs": [],
        "activity_preferences": [],
        "accepted_terms": False,
        "marketing_opt_in": False,
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
    choice = (draft.get("city_choice") or "").strip()
    if choice == CUSTOM_CITY_SENTINEL or choice == "":
        return (draft.get("custom_city") or "").strip()
    return choice


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
    gap: 0.5rem;
    margin: 0.5rem 0 1.25rem;
    flex-wrap: wrap;
}
.profile-step {
    flex: 1;
    min-width: 4.5rem;
    padding: 0.55rem 0.45rem;
    border-radius: 12px;
    background: rgba(112,77,59,0.08);
    border: 0.5px solid rgba(112,77,59,0.12);
    text-align: center;
}
.profile-step.active {
    background: rgba(211,163,69,0.18);
    border-color: rgba(211,163,69,0.55);
}
.profile-step.done {
    background: rgba(112,77,59,0.14);
}
.profile-step-num {
    display: block;
    font-size: 11px;
    letter-spacing: 0.12em;
    color: #D3A345;
    margin-bottom: 0.15rem;
}
.profile-step-label {
    font-size: 11px;
    color: #704D3B;
}
.profile-panel {
    background: #704D3B;
    border-radius: 20px;
    padding: 1.25rem 1.15rem 1.1rem;
    margin-bottom: 1rem;
}
.profile-panel-title {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: 26px;
    color: #F8E6D2;
    margin: 0 0 0.35rem;
}
.profile-panel-sub {
    font-size: 12px;
    color: rgba(248,230,210,0.62);
    margin: 0 0 0.85rem;
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
        "A few questions — once — so every recommendation fits you. "
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
    c1, c2 = st.columns(2)
    with c1:
        first = st.text_input("First name", value=draft.get("first_name") or "", key="pf_first")
    with c2:
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
    city_options = [*DEFAULT_CITIES, CUSTOM_CITY_SENTINEL]
    current = draft.get("city_choice") or ""
    if current and current not in city_options and current != CUSTOM_CITY_SENTINEL:
        current = CUSTOM_CITY_SENTINEL
    index = city_options.index(current) if current in city_options else 0

    choice = st.selectbox("Which city are you based in?", city_options, index=index, key="pf_city")
    custom = ""
    if choice == CUSTOM_CITY_SENTINEL:
        custom = st.text_input(
            "Add your city",
            value=draft.get("custom_city") or "",
            key="pf_city_custom",
        )
    neighbourhood = st.text_input(
        "Which neighbourhood do you live in?",
        value=draft.get("neighbourhood") or "",
        placeholder="Never shared with a partner",
        key="pf_hood",
    )

    back, nxt = _nav(next_key="profile_step2")
    if back:
        draft["city_choice"] = choice
        draft["custom_city"] = custom
        draft["neighbourhood"] = neighbourhood.strip()
        _save_draft(draft)
        st.session_state[STEP_KEY] = 1
        st.rerun()
    if nxt:
        city = custom.strip() if choice == CUSTOM_CITY_SENTINEL else choice.strip()
        if not city:
            st.error("Please choose or enter a city.")
            return
        if not neighbourhood.strip():
            st.error("Neighbourhood is required.")
            return
        draft["city_choice"] = choice
        draft["custom_city"] = custom.strip()
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
            mark_complete=True,
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not save your profile: {exc}")
        return

    st.session_state.pop(DRAFT_KEY, None)
    st.session_state.pop(STEP_KEY, None)
    clear_profile_cache()
    st.toast("Profile saved — welcome to Après.")
    st.rerun()


def render_profile_settings(email: str, profile: dict[str, Any]) -> None:
    """Edit surface for users who already completed basic setup."""
    st.markdown('<div class="section-label">Your profile</div>', unsafe_allow_html=True)
    st.caption("Update your taste profile anytime. Ratings and plans stay as they are.")

    draft = _empty_draft(email, profile)

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

    city_options = [*DEFAULT_CITIES, CUSTOM_CITY_SENTINEL]
    city_choice = draft.get("city_choice") or CUSTOM_CITY_SENTINEL
    if city_choice not in city_options:
        city_choice = CUSTOM_CITY_SENTINEL
    choice = st.selectbox(
        "City",
        city_options,
        index=city_options.index(city_choice),
        key="edit_city",
    )
    custom = ""
    if choice == CUSTOM_CITY_SENTINEL:
        custom = st.text_input("Your city", value=draft.get("custom_city") or "", key="edit_city_custom")
    neighbourhood = st.text_input(
        "Neighbourhood",
        value=draft.get("neighbourhood") or "",
        key="edit_hood",
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
        city = custom.strip() if choice == CUSTOM_CITY_SENTINEL else choice.strip()
        if not first.strip() or not last.strip() or not city or not neighbourhood.strip():
            st.error("Name, city, and neighbourhood are required.")
            return
        if not dietary:
            st.error("Select at least one dietary option (None is fine).")
            return
        if not activities:
            st.error("Select at least one activity.")
            return
        try:
            saved = upsert_profile(
                email=email,
                first_name=first.strip(),
                last_name=last.strip(),
                city=city,
                neighbourhood=neighbourhood.strip(),
                dietary_needs=list(dietary),
                activity_preferences=list(activities),
                accepted_terms_at=profile.get("ACCEPTED_TERMS_AT") or datetime.utcnow(),
                marketing_opt_in=bool(marketing),
                date_of_birth=dob if isinstance(dob, date) else None,
                phone=phone.strip() or None,
                mark_complete=True,
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not save: {exc}")
            return
        if not is_profile_complete(saved):
            st.error("Profile is still incomplete — check required fields.")
            return
        st.toast("Profile updated.")
        st.rerun()
