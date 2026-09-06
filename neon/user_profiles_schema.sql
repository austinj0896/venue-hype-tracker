-- Après user profiles — separate from venue tags/hours/ratings.
-- Apply via app ensure_schema or Neon SQL Editor:
--   streamlit: user_profiles_store.ensure_schema()

CREATE TABLE IF NOT EXISTS user_profiles (
    user_email            TEXT PRIMARY KEY,
    first_name            TEXT NOT NULL,
    last_name             TEXT NOT NULL,
    date_of_birth         DATE,
    phone                 TEXT,
    city                  TEXT NOT NULL,
    neighbourhood         TEXT NOT NULL,
    dietary_needs         TEXT[] NOT NULL DEFAULT '{}',
    activity_preferences  TEXT[] NOT NULL DEFAULT '{}',
    accepted_terms_at     TIMESTAMPTZ NOT NULL,
    marketing_opt_in      BOOLEAN NOT NULL DEFAULT FALSE,
    profile_complete      BOOLEAN NOT NULL DEFAULT FALSE,
    relationship_status   TEXT,
    open_to_dates         BOOLEAN,
    profile_visibility    TEXT NOT NULL DEFAULT 'private',
    profile_photo_b64     TEXT,
    profile_photo_mime    TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_profiles_complete
    ON user_profiles (profile_complete);

CREATE INDEX IF NOT EXISTS idx_user_profiles_updated
    ON user_profiles (updated_at DESC);
