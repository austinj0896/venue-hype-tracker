-- Après venue hours — run once via:
--   python scripts/fetch_venue_hours.py --apply-schema
--
-- Designed for periodic refresh: upsert current row; archive prior
-- snapshot to history when hours text/json change.

CREATE TABLE IF NOT EXISTS venue_hours (
    google_place_id TEXT PRIMARY KEY,
    hours_json      JSONB,
    hours_text      TEXT,
    timezone        TEXT,
    notes           TEXT,
    source          TEXT NOT NULL,
    source_urls     TEXT[],
    confidence      DOUBLE PRECISION,
    evidence        TEXT,
    status          TEXT NOT NULL,
    model_version   TEXT,
    content_hash    TEXT,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_venue_hours_status CHECK (
        status IN ('ok', 'partial', 'empty', 'error')
    ),
    CONSTRAINT chk_venue_hours_source CHECK (
        source IN (
            'website',
            'google_search',
            'yelp',
            'website+google_search',
            'heuristic',
            'none'
        )
    )
);

CREATE TABLE IF NOT EXISTS venue_hours_history (
    history_id      BIGSERIAL PRIMARY KEY,
    google_place_id TEXT NOT NULL,
    hours_json      JSONB,
    hours_text      TEXT,
    source          TEXT,
    confidence      DOUBLE PRECISION,
    status          TEXT,
    model_version   TEXT,
    content_hash    TEXT,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    change_kind     TEXT NOT NULL DEFAULT 'refresh',
    CONSTRAINT chk_venue_hours_history_change CHECK (
        change_kind IN ('first', 'changed', 'refresh', 'cleared')
    )
);

CREATE INDEX IF NOT EXISTS idx_venue_hours_fetched_at ON venue_hours (fetched_at);
CREATE INDEX IF NOT EXISTS idx_venue_hours_status ON venue_hours (status);
CREATE INDEX IF NOT EXISTS idx_venue_hours_history_place
    ON venue_hours_history (google_place_id, fetched_at DESC);

-- Allow re-running schema after source enum expands.
ALTER TABLE venue_hours DROP CONSTRAINT IF EXISTS chk_venue_hours_source;
ALTER TABLE venue_hours ADD CONSTRAINT chk_venue_hours_source CHECK (
    source IN (
        'website',
        'google_search',
        'yelp',
        'website+google_search',
        'heuristic',
        'none'
    )
);
