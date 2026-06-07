-- Venue / place inventory (Google Places seed for Manhattan pilot)

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS places (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  google_place_id TEXT NOT NULL UNIQUE,
  name TEXT,
  formatted_address TEXT,
  short_formatted_address TEXT,
  latitude REAL,
  longitude REAL,
  primary_type TEXT,
  types_json TEXT,
  business_status TEXT,
  rating REAL,
  user_rating_count INTEGER,
  price_level TEXT,
  website_uri TEXT,
  borough TEXT DEFAULT 'Manhattan',
  source TEXT DEFAULT 'google_places_nearby',
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_places_borough ON places(borough);
CREATE INDEX IF NOT EXISTS idx_places_primary_type ON places(primary_type);
CREATE INDEX IF NOT EXISTS idx_places_last_seen ON places(last_seen_at);

-- One row per ETL run (auditing, debugging quota)
CREATE TABLE IF NOT EXISTS fetch_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  source TEXT NOT NULL,
  grid_rows INTEGER,
  grid_cols INTEGER,
  search_radius_m REAL,
  types_requested TEXT,
  api_calls INTEGER,
  places_upserted INTEGER,
  error_message TEXT
);
