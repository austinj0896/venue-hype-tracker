-- Saved two-stop date plans per user (run after neon/schema.sql)

CREATE TABLE IF NOT EXISTS planned_dates (
    planned_date_id     BIGSERIAL PRIMARY KEY,
    user_email          TEXT NOT NULL,
    borough             TEXT NOT NULL,
    combo_id            TEXT NOT NULL,
    combo_label         TEXT NOT NULL,
    stop1_google_place_id TEXT NOT NULL,
    stop1_place_name    TEXT,
    stop1_primary_type  TEXT,
    stop2_google_place_id TEXT NOT NULL,
    stop2_place_name    TEXT,
    stop2_primary_type  TEXT,
    walk_distance_m     DOUBLE PRECISION,
    walk_duration_min   DOUBLE PRECISION,
    scheduled_at        TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_planned_dates_user ON planned_dates (user_email);
CREATE INDEX IF NOT EXISTS idx_planned_dates_scheduled ON planned_dates (user_email, scheduled_at);
