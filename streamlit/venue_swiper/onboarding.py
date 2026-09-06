"""01 · ONBOARDING — splash + three pre-signup slides (Après-branded).

Deck intent: sell the product before account creation. No passwords / platform
connects here — those stay out of scope.
"""

from __future__ import annotations

from html import escape

import streamlit as st

from app_log import log_event

ONBOARDING_DONE_KEY = "apres_onboarding_done"
ONBOARDING_STEP_KEY = "apres_onboarding_step"

# step 0 = splash, 1–3 = marketing slides, then done → email login
_SLIDES = (
    {
        "eyebrow": "Slide 1",
        "title": "Rate what you’ve tried.",
        "body": "Skip what you haven’t. Après learns your taste — then plans around it.",
        "cta": "Next",
    },
    {
        "eyebrow": "Slide 2",
        "title": "Every detail arranged.",
        "body": "Hours, vibes, and walkable stops — so the night feels intentional, not improvised.",
        "cta": "Next",
    },
    {
        "eyebrow": "Slide 3",
        "title": "Your city, your terms.",
        "body": "Neighbourhood, diet, and what you actually enjoy. Built once — used every time you plan.",
        "cta": "Create account",
    },
)


def onboarding_css() -> str:
    return """
.ob-splash {
    min-height: 62vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 2.5rem 1rem 1.5rem;
    animation: apres-fade-up 520ms cubic-bezier(0.22, 1, 0.36, 1) both;
}
.ob-mark {
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: clamp(42px, 12vw, 56px);
    font-weight: 500;
    font-style: italic;
    color: #704D3B;
    letter-spacing: -0.02em;
    margin: 0 0 0.75rem;
}
.ob-tagline {
    font-size: 13px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #B09080;
    margin: 0 0 1.75rem;
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
    min-height: 280px;
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
    font-size: clamp(30px, 8vw, 38px);
    font-weight: 500;
    font-style: italic;
    color: #F8E6D2;
    line-height: 1.12;
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
.ob-principle {
    font-size: 12px;
    line-height: 1.5;
    color: #B09080;
    font-style: italic;
    margin: 0.35rem 0 1rem;
    text-align: center;
}
"""


def onboarding_complete() -> bool:
    return bool(st.session_state.get(ONBOARDING_DONE_KEY))


def render_onboarding() -> None:
    """Splash + 3 slides. Returns only after user finishes (via rerun to login)."""
    st.markdown(f"<style>{onboarding_css()}</style>", unsafe_allow_html=True)
    step = int(st.session_state.get(ONBOARDING_STEP_KEY, 0))

    if step <= 0:
        st.markdown(
            '<div class="ob-splash">'
            '<div class="ob-mark">Après</div>'
            '<div class="ob-tagline">Find what comes next.</div>'
            '<div class="ob-pulse" aria-hidden="true"></div>'
            "</div>",
            unsafe_allow_html=True,
        )
        st.caption("First impressions · then your account")
        if st.button("Get started", type="primary", use_container_width=True, key="ob_splash"):
            st.session_state[ONBOARDING_STEP_KEY] = 1
            log_event("onboarding", "Splash → slide 1")
            st.rerun()
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
    if idx == 0:
        st.markdown(
            '<p class="ob-principle">Both of you bring a taste. Après finds the night.</p>',
            unsafe_allow_html=True,
        )

    cols = st.columns([1, 1] if idx > 0 else [1])
    if idx > 0:
        with cols[0]:
            if st.button("Back", use_container_width=True, key=f"ob_back_{idx}"):
                st.session_state[ONBOARDING_STEP_KEY] = idx  # previous (1-based idx → step)
                log_event("onboarding", f"Back to step {idx}")
                st.rerun()
        with cols[1]:
            if st.button(slide["cta"], type="primary", use_container_width=True, key=f"ob_next_{idx}"):
                _advance(idx)
    else:
        if st.button(slide["cta"], type="primary", use_container_width=True, key=f"ob_next_{idx}"):
            _advance(idx)


def _advance(idx: int) -> None:
    """idx is 0-based slide index (0, 1, 2)."""
    if idx >= 2:
        st.session_state[ONBOARDING_DONE_KEY] = True
        st.session_state.pop(ONBOARDING_STEP_KEY, None)
        log_event("onboarding", "Completed; showing email login")
    else:
        next_step = idx + 2  # slide 0 → step 2, slide 1 → step 3
        st.session_state[ONBOARDING_STEP_KEY] = next_step
        log_event("onboarding", f"Advance to slide {next_step}")
    st.rerun()
