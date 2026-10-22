-- SQLite schema for the concert demand database.
--
-- Built by `python -m concert_demand.load_db` from the CSVs in data/interim.
-- Dates are ISO text (YYYY-MM-DD) and booleans are 0/1 integers, the usual
-- SQLite conventions, so date comparisons and SUM(flag) both work.
--
-- Pollstar data is deliberately not loaded. It is copyrighted and used only
-- for validation, and this database feeds the public dashboard.

PRAGMA foreign_keys = ON;

-- Feature tables are written by concert_demand.features.signals. They're
-- dropped here too, so a rebuild never leaves features from old data behind.
DROP TABLE IF EXISTS show_features;
DROP TABLE IF EXISTS show_features_show_date;
DROP VIEW IF EXISTS model_ready_engagements;
DROP TABLE IF EXISTS spotify_credits;
DROP TABLE IF EXISTS pageviews_daily;
DROP TABLE IF EXISTS chart_credits;
DROP TABLE IF EXISTS engagements;
DROP TABLE IF EXISTS tour_sources;
DROP TABLE IF EXISTS artists;

-- One row per artist named on a tour page, as headliner or co-headliner.
-- Co-headliners (Faith Hill, Migos) get chart and pageview data too, since
-- a co-headlined show's demand comes from both acts.
CREATE TABLE artists (
    artist          TEXT PRIMARY KEY,   -- canonical Wikipedia title, e.g. "Drake (musician)"
    headlines_tour  INTEGER NOT NULL CHECK (headlines_tour IN (0, 1)),  -- 0 = only ever co-headlines
    is_package_tour INTEGER NOT NULL CHECK (is_package_tour IN (0, 1))
);

-- Every Wikipedia tour article used, with the exact revision read (CC BY-SA attribution).
CREATE TABLE tour_sources (
    tour         TEXT PRIMARY KEY,
    url          TEXT NOT NULL,
    revid        INTEGER NOT NULL,
    permalink    TEXT NOT NULL,
    retrieved_at TEXT NOT NULL
);

-- One row per engagement: a single show, or a multi-night run at one venue.
CREATE TABLE engagements (
    engagement_id       INTEGER PRIMARY KEY,
    artist              TEXT REFERENCES artists (artist),   -- null for 10 rows with no artist
    tour                TEXT NOT NULL REFERENCES tour_sources (tour),
    venue               TEXT,
    city                TEXT,
    country             TEXT,
    country_raw         TEXT,              -- country as written on the page
    country_source      TEXT,              -- page, city_lookup or tour_neighbors
    first_date          TEXT,
    last_date           TEXT,
    n_shows             INTEGER NOT NULL CHECK (n_shows >= 1),
    tickets_sold        INTEGER NOT NULL,
    capacity            INTEGER NOT NULL,
    capacity_per_show   REAL NOT NULL,
    revenue_usd         REAL,
    fill_rate           REAL NOT NULL CHECK (fill_rate BETWEEN 0 AND 1),  -- capped at 1
    sold_out            INTEGER NOT NULL CHECK (sold_out IN (0, 1)),
    over_capacity       INTEGER NOT NULL CHECK (over_capacity IN (0, 1)),
    co_headliners       TEXT,
    n_headliners        INTEGER NOT NULL,
    in_us_canada        INTEGER NOT NULL CHECK (in_us_canada IN (0, 1)),
    is_puerto_rico      INTEGER NOT NULL CHECK (is_puerto_rico IN (0, 1)),
    is_festival         INTEGER NOT NULL CHECK (is_festival IN (0, 1)),
    is_package_tour     INTEGER NOT NULL CHECK (is_package_tour IN (0, 1)),
    suspect_capacity    INTEGER NOT NULL CHECK (suspect_capacity IN (0, 1)),
    conflicting_sources INTEGER NOT NULL CHECK (conflicting_sources IN (0, 1)),
    covid_era           TEXT CHECK (covid_era IN ('pre', 'during', 'post'))
);
CREATE INDEX idx_engagements_artist_date ON engagements (artist, first_date);

-- Billboard Hot 100 / Billboard 200 entries credited to a tour artist.
CREATE TABLE chart_credits (
    chart        TEXT NOT NULL CHECK (chart IN ('hot100', 'billboard200')),
    chart_week   TEXT NOT NULL,
    rank         INTEGER NOT NULL,
    title        TEXT NOT NULL,
    performer    TEXT NOT NULL,       -- credit as printed by Billboard
    last_week    INTEGER,             -- null for new entries and re-entries
    peak_pos     INTEGER NOT NULL,
    wks_on_chart INTEGER NOT NULL,
    artist       TEXT NOT NULL REFERENCES artists (artist),
    role         TEXT NOT NULL CHECK (role IN ('lead', 'featured'))
);
CREATE INDEX idx_chart_credits_artist_week ON chart_credits (artist, chart_week);

-- Daily Wikipedia pageviews (human readers), one row per artist per day.
CREATE TABLE pageviews_daily (
    artist          TEXT NOT NULL REFERENCES artists (artist),
    date            TEXT NOT NULL,
    views_total     INTEGER NOT NULL,   -- current title + former-name redirects
    views_canonical INTEGER NOT NULL,   -- current title only
    PRIMARY KEY (artist, date)
);

-- Spotify US and Canada Top 200 / Viral 50 entries credited to a tour artist (2017-2021).
CREATE TABLE spotify_credits (
    chart       TEXT NOT NULL CHECK (chart IN ('top200', 'viral50')),
    region      TEXT NOT NULL,
    date        TEXT NOT NULL,
    rank        INTEGER NOT NULL,
    title       TEXT NOT NULL,
    performer   TEXT NOT NULL,          -- credit as printed by Spotify
    streams     INTEGER,                -- null on Viral 50, which has no stream counts
    artist      TEXT NOT NULL REFERENCES artists (artist),
    role        TEXT NOT NULL CHECK (role IN ('lead', 'featured'))
);
CREATE INDEX idx_spotify_credits_artist_date ON spotify_credits (artist, date);

-- The modeling sample: US + Canada (incl. Puerto Rico) shows with a known
-- artist and date and no data-quality flags. Package tours are excluded
-- because their demand can't be credited to one artist.
CREATE VIEW model_ready_engagements AS
SELECT *
FROM engagements
WHERE in_us_canada = 1
  AND artist IS NOT NULL
  AND first_date IS NOT NULL
  AND is_festival = 0
  AND suspect_capacity = 0
  AND conflicting_sources = 0
  AND is_package_tour = 0;
