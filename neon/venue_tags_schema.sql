-- Après vibe tags — run once in Neon SQL Editor or via:
--   python scripts/tag_venue_vibes.py --apply-schema

CREATE TABLE IF NOT EXISTS venue_scrapes (
    google_place_id TEXT PRIMARY KEY,
    website_uri     TEXT,
    content_hash    TEXT,
    extracted_text  TEXT,
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scrape_status   TEXT NOT NULL,
    scrape_error    TEXT,
    reviews_text    TEXT,
    reviews_source  TEXT,
    reviews_status  TEXT,
    reviews_fetched_at TIMESTAMPTZ,
    CONSTRAINT chk_venue_scrapes_status CHECK (
        scrape_status IN ('ok', 'blocked', 'no_website', 'empty', 'error')
    )
);

-- Safe to re-run if venue_scrapes already existed without review columns.
ALTER TABLE venue_scrapes ADD COLUMN IF NOT EXISTS reviews_text TEXT;
ALTER TABLE venue_scrapes ADD COLUMN IF NOT EXISTS reviews_source TEXT;
ALTER TABLE venue_scrapes ADD COLUMN IF NOT EXISTS reviews_status TEXT;
ALTER TABLE venue_scrapes ADD COLUMN IF NOT EXISTS reviews_fetched_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS venue_tags (
    google_place_id TEXT NOT NULL,
    tag             TEXT NOT NULL,
    confidence      DOUBLE PRECISION,
    evidence        TEXT,
    source          TEXT NOT NULL DEFAULT 'llm_v1',
    model_version   TEXT,
    tagged_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (google_place_id, tag)
);

-- Tags considered but not applied (accuracy-first: low confidence / unconfirmed).
CREATE TABLE IF NOT EXISTS venue_tag_rejects (
    google_place_id TEXT NOT NULL,
    tag             TEXT NOT NULL,
    confidence      DOUBLE PRECISION,
    evidence        TEXT,
    reason          TEXT NOT NULL,
    source          TEXT,
    model_version   TEXT,
    rejected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (google_place_id, tag, reason)
);

-- Full canonical vibe taxonomy (synced from scripts/vibe_taxonomy.py).
CREATE TABLE IF NOT EXISTS vibe_taxonomy (
    tag          TEXT PRIMARY KEY,
    category     TEXT NOT NULL,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_vibe_taxonomy_category CHECK (
        category IN ('restaurant_bar_vibes', 'bar_specific', 'general')
    )
);

CREATE INDEX IF NOT EXISTS idx_venue_tags_tag ON venue_tags (tag);
CREATE INDEX IF NOT EXISTS idx_venue_tags_tagged_at ON venue_tags (tagged_at);
CREATE INDEX IF NOT EXISTS idx_venue_tag_rejects_place ON venue_tag_rejects (google_place_id);
CREATE INDEX IF NOT EXISTS idx_vibe_taxonomy_category ON vibe_taxonomy (category);
