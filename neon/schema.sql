-- Après on Neon Postgres — run once in Neon SQL Editor or via scripts/seed_neon_places.py

CREATE TABLE IF NOT EXISTS places (
    google_place_id         TEXT PRIMARY KEY,
    place_name              TEXT,
    formatted_address       TEXT,
    short_formatted_address TEXT,
    latitude                DOUBLE PRECISION,
    longitude               DOUBLE PRECISION,
    primary_type            TEXT,
    venue_category          TEXT,
    price_level             TEXT,
    website_uri             TEXT,
    borough                 TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_places_borough ON places (borough);
CREATE INDEX IF NOT EXISTS idx_places_primary_type ON places (primary_type);

CREATE TABLE IF NOT EXISTS venue_ratings (
    rating_id       BIGSERIAL PRIMARY KEY,
    user_email      TEXT NOT NULL,
    google_place_id TEXT NOT NULL,
    place_name      TEXT,
    borough         TEXT NOT NULL DEFAULT 'Manhattan Beach',
    rating          DOUBLE PRECISION,
    status          TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_venue_ratings_user_place UNIQUE (user_email, google_place_id),
    CONSTRAINT chk_venue_ratings_status CHECK (status IN ('rated', 'skipped')),
    CONSTRAINT chk_venue_ratings_value CHECK (
        (status = 'skipped' AND rating IS NULL)
        OR (status = 'rated' AND rating IS NOT NULL AND rating >= 0 AND rating <= 5)
    )
);

CREATE INDEX IF NOT EXISTS idx_venue_ratings_user ON venue_ratings (user_email);
