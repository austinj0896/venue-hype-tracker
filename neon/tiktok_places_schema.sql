-- TikTok POI mapping: Google place -> TikTok /place/ URL

CREATE TABLE IF NOT EXISTS tiktok_places (
    id                  BIGSERIAL PRIMARY KEY,
    google_place_id     TEXT REFERENCES places (google_place_id) ON DELETE SET NULL,
    venue_name          TEXT,
    discovery_query     TEXT NOT NULL,
    tiktok_place_url    TEXT NOT NULL,
    tiktok_poi_id       TEXT NOT NULL,
    place_slug          TEXT,
    discovery_method    TEXT,
    confidence_score    DOUBLE PRECISION,
    captured_at_utc     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tiktok_places_poi UNIQUE (tiktok_poi_id),
    CONSTRAINT uq_tiktok_places_url UNIQUE (tiktok_place_url)
);

CREATE INDEX IF NOT EXISTS idx_tiktok_places_google ON tiktok_places (google_place_id);

-- Optional columns on videos (safe if tiktok_videos already exists)
ALTER TABLE tiktok_videos ADD COLUMN IF NOT EXISTS tiktok_place_url TEXT;
ALTER TABLE tiktok_videos ADD COLUMN IF NOT EXISTS tiktok_poi_id TEXT;
