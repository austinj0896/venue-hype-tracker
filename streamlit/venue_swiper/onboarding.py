"""01 · ONBOARDING — splash + three pre-signup slides (Après-branded).

Deck intent: sell the product before account creation. Splash always shows;
Sign in is opt-in from splash or the last slide. Soft email auth only (no OTP yet).
"""

from __future__ import annotations

from html import escape

import streamlit as st

from app_log import log_event
from brand import brand_mark_html

ONBOARDING_DONE_KEY = "apres_onboarding_done"
ONBOARDING_STEP_KEY = "apres_onboarding_step"
LOGIN_MODE_KEY = "apres_login_mode"  # "new" | "returning"

_SLIDES = (
    {
        "eyebrow": "01",
        "title": "Your taste, remembered.",
        "body": "Rate a few places. We’ll never forget what you love.",
        "cta": "Next",
    },
    {
        "eyebrow": "02",
        "title": "Your city, your terms.",
        "body": "Where you are, what you’re into, what you’d rather skip.",
        "cta": "Next",
    },
    {
        "eyebrow": "03",
        "title": "We handle the rest.",
        "body": "Great nights out, without the planning.",
        "cta": "Create account",
    },
)


def onboarding_css() -> str:
    return """
.ob-splash {
    min-height: min(72dvh, 620px);
    min-height: 72vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 2rem 1rem 1.5rem;
    margin: 0.25rem 0 1rem;
    border-radius: 20px;
    background:
        radial-gradient(120% 80% at 50% 20%, rgba(211,163,69,0.18) 0%, transparent 55%),
        linear-gradient(180deg, #2A1A12 0%, #1A100C 55%, #120C09 100%);
    border: 1px solid rgba(211, 163, 69, 0.18);
    box-shadow: 0 18px 40px rgba(44, 26, 16, 0.18);
    animation: apres-fade-up 520ms cubic-bezier(0.22, 1, 0.36, 1) both;
}
@supports (height: 1dvh) {
    .ob-splash {
        min-height: min(72dvh, 620px);
    }
}
.ob-mark,
.apres-brand-hero {
    width: min(100%, 260px);
    height: auto;
    display: block;
    margin: 0 auto 1.1rem;
}
.ob-tagline {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: 16px;
    font-style: italic;
    font-weight: 400;
    letter-spacing: 0.02em;
    color: rgba(248, 230, 210, 0.78);
    margin: 0 0 1.5rem;
    max-width: 18rem;
}
.ob-pulse {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #D3A345;
    box-shadow: 0 0 0 0 rgba(211, 163, 69, 0.55);
    animation: ob-pulse 1.6s cubic-bezier(0.45, 0, 0.55, 1) infinite;
}
@keyframes ob-pulse {
    0% { transform: scale(0.9); box-shadow: 0 0 0 0 rgba(211, 163, 69, 0.55); }
    70% { transform: scale(1); box-shadow: 0 0 0 14px rgba(211, 163, 69, 0); }
    100% { transform: scale(0.9); box-shadow: 0 0 0 0 rgba(211, 163, 69, 0); }
}
.ob-slide {
    background:
        linear-gradient(165deg, rgba(211,163,69,0.16) 0%, transparent 42%),
        linear-gradient(180deg, #7A5643 0%, #704D3B 55%, #5E3F31 100%);
    border-radius: 20px;
    border: 1px solid rgba(248, 230, 210, 0.08);
    box-shadow: 0 4px 8px rgba(44,26,16,0.05), 0 24px 48px rgba(44,26,16,0.12),
        inset 0 1px 0 rgba(248,230,210,0.1);
    padding: 1.75rem 1.35rem 1.45rem;
    margin: 0.75rem 0 1rem;
    min-height: 260px;
    animation: apres-card-in 520ms cubic-bezier(0.22, 1, 0.36, 1) both;
}
.ob-eyebrow {
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: #D3A345;
    margin: 0 0 0.85rem;
}
.ob-title {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: clamp(28px, 7.5vw, 36px);
    font-weight: 500;
    font-style: italic;
    color: #F8E6D2;
    line-height: 1.15;
    letter-spacing: -0.015em;
    margin: 0 0 0.85rem;
}
.ob-body {
    font-size: 15px;
    line-height: 1.55;
    color: rgba(248, 230, 210, 0.68);
    margin: 0 0 1.25rem;
}
.ob-dots {
    display: flex;
    gap: 0.45rem;
    margin: 0 0 0.25rem;
}
.ob-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: rgba(248, 230, 210, 0.22);
}
.ob-dot.active {
    background: #D3A345;
    box-shadow: 0 0 0 3px rgba(211, 163, 69, 0.22);
}
.ob-signin-hint {
    text-align: center;
    font-size: 13px;
    color: #7A5B48;
    margin: 0.75rem 0 0;
}
"""


def onboarding_complete() -> bool:
    return bool(st.session_state.get(ONBOARDING_DONE_KEY))


def go_to_sign_in(*, returning: bool = True) -> None:
    st.session_state[ONBOARDING_DONE_KEY] = True
    st.session_state.pop(ONBOARDING_STEP_KEY, None)
    st.session_state[LOGIN_MODE_KEY] = "returning" if returning else "new"
    log_event("onboarding", "Sign in path (skip slides)" if returning else "Create account path")
    st.rerun()


def render_onboarding() -> None:
    st.markdown(f"<style>{onboarding_css()}</style>", unsafe_allow_html=True)

    step = int(st.session_state.get(ONBOARDING_STEP_KEY, 0))

    if step <= 0:
        st.markdown(
            '<div class="ob-splash">'
            f"{brand_mark_html(size='hero')}"
            '<div class="ob-tagline">Find what comes next.</div>'
            '<div class="ob-pulse" aria-hidden="true"></div>'
            "</div>",
            unsafe_allow_html=True,
        )
        if st.button("Get started", type="primary", use_container_width=True, key="ob_splash"):
            st.session_state[ONBOARDING_STEP_KEY] = 1
            st.session_state[LOGIN_MODE_KEY] = "new"
            log_event("onboarding", "Splash → slide 1")
            st.rerun()
        st.markdown('<p class="ob-signin-hint">Already have an account?</p>', unsafe_allow_html=True)
        if st.button("Sign in", use_container_width=True, key="ob_splash_signin"):
            go_to_sign_in(returning=True)
        return

    idx = max(1, min(3, step)) - 1
    slide = _SLIDES[idx]
    dots = "".join(
        f'<span class="ob-dot{" active" if i == idx else ""}"></span>' for i in range(3)
    )
    st.markdown(
        f'<div class="ob-slide">'
        f'<div class="ob-eyebrow">{escape(slide["eyebrow"])}</div>'
        f'<div class="ob-title">{escape(slide["title"])}</div>'
        f'<p class="ob-body">{escape(slide["body"])}</p>'
        f'<div class="ob-dots">{dots}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )

    cols = st.columns([1, 1] if idx > 0 else [1])
    if idx > 0:
        with cols[0]:
            if st.button("Back", use_container_width=True, key=f"ob_back_{idx}"):
                st.session_state[ONBOARDING_STEP_KEY] = idx
                st.rerun()
        with cols[1]:
            if st.button(slide["cta"], type="primary", use_container_width=True, key=f"ob_next_{idx}"):
                _advance(idx)
    else:
        if st.button(slide["cta"], type="primary", use_container_width=True, key=f"ob_next_{idx}"):
            _advance(idx)

    if idx == 2:
        st.markdown('<p class="ob-signin-hint">Already with Après?</p>', unsafe_allow_html=True)
        if st.button("Sign in instead", use_container_width=True, key="ob_slide3_signin"):
            go_to_sign_in(returning=True)


def _advance(idx: int) -> None:
    if idx >= 2:
        st.session_state[ONBOARDING_DONE_KEY] = True
        st.session_state.pop(ONBOARDING_STEP_KEY, None)
        st.session_state[LOGIN_MODE_KEY] = "new"
        log_event("onboarding", "Completed slides; create account")
    else:
        st.session_state[ONBOARDING_STEP_KEY] = idx + 2
        log_event("onboarding", f"Advance to slide {idx + 2}")
    st.rerun()

