-- App event / error log for Après Streamlit Cloud debugging.
-- Also auto-created by streamlit/venue_swiper/app_log.py ensure_log_schema().

CREATE TABLE IF NOT EXISTS app_event_logs (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_email  TEXT,
    stage       TEXT NOT NULL,
    level       TEXT NOT NULL DEFAULT 'info',
    message     TEXT NOT NULL,
    detail      TEXT
);

CREATE INDEX IF NOT EXISTS idx_app_event_logs_created
    ON app_event_logs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_app_event_logs_stage
    ON app_event_logs (stage, created_at DESC);
