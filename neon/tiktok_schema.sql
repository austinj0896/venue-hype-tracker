-- TikTok hype videos linked to Après places (optional extension to neon/schema.sql)

CREATE TABLE IF NOT EXISTS tiktok_videos (
    id                  BIGSERIAL PRIMARY KEY,
    google_place_id     TEXT REFERENCES places (google_place_id) ON DELETE SET NULL,
    place_name          TEXT,
    search_address      TEXT,
    discover_url        TEXT,
    discover_slug       TEXT,
    video_id            TEXT NOT NULL,
    video_url           TEXT NOT NULL,
    creator_handle      TEXT,
    creator_nickname    TEXT,
    caption             TEXT,
    create_time_unix    BIGINT,
    created_at_utc      TIMESTAMPTZ,
    duration_seconds    INTEGER,
    like_count          BIGINT,
    share_count         BIGINT,
    comment_count       BIGINT,
    play_count          BIGINT,
    collect_count       BIGINT,
    parse_status        TEXT NOT NULL DEFAULT 'ok',
    captured_at_utc     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tiktok_videos_video_id UNIQUE (video_id)
);

CREATE INDEX IF NOT EXISTS idx_tiktok_videos_place ON tiktok_videos (google_place_id);
CREATE INDEX IF NOT EXISTS idx_tiktok_videos_discover ON tiktok_videos (discover_slug);
CREATE INDEX IF NOT EXISTS idx_tiktok_videos_captured ON tiktok_videos (captured_at_utc DESC);
