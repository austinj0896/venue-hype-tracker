-- Après multi-photo gallery (dating-app style). Primary = sort_order 0.
-- Apply in Neon SQL Editor, or the app creates this on first photo save.

CREATE TABLE IF NOT EXISTS user_profile_photos (
    photo_id       BIGSERIAL PRIMARY KEY,
    user_email     TEXT NOT NULL,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    photo_b64      TEXT NOT NULL,
    photo_mime     TEXT NOT NULL DEFAULT 'image/jpeg',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_profile_photos_order UNIQUE (user_email, sort_order),
    CONSTRAINT chk_user_profile_photos_order CHECK (sort_order >= 0 AND sort_order < 12)
);

CREATE INDEX IF NOT EXISTS idx_user_profile_photos_user
    ON user_profile_photos (user_email, sort_order);
