-- Analysis views on top of the concert demand database.
--
-- Applied by `python -m concert_demand.analysis_views`, after the feature
-- build (several views read show_features). Three groups, chosen by Matt:
--
--   Right-sizing       artist_venue_fit, extra_nights, demand_per_seat
--   Booking history    tour_summary, engagement_history, city_revisits
--   Signal diagnostics sellout_by_signal_decile, within_artist_pageviews,
--                      one_hit_case_study (reads the one_hit_shows table)

DROP VIEW IF EXISTS era_venue_comparison;   -- removed: COVID is covered in Phase 2 instead
DROP VIEW IF EXISTS artist_venue_fit;
DROP VIEW IF EXISTS extra_nights;
DROP VIEW IF EXISTS demand_per_seat;
DROP VIEW IF EXISTS tour_summary;
DROP VIEW IF EXISTS engagement_history;
DROP VIEW IF EXISTS city_revisits;
DROP VIEW IF EXISTS sellout_by_signal_decile;
DROP VIEW IF EXISTS within_artist_pageviews;
DROP VIEW IF EXISTS one_hit_case_study;
DROP VIEW IF EXISTS model_sample;


-- The modeling sample with its features: model-ready shows whose 52-week
-- pageview window is fully covered. Most views below start here.
CREATE VIEW model_sample AS
SELECT
    m.*,
    f.signal_artist,
    f.pageviews_mean_52w,
    f.pageviews_en_mean_52w,
    f.hot100_lead_points_52w,
    f.hot100_lead_top10_52w,
    f.hot100_lead_entries_career,
    f.billboard200_lead_points_52w,
    f.billboard200_lead_entries_career,
    f.hot100_lead_momentum,
    f.pageviews_momentum,
    CASE
        WHEN m.capacity_per_show < 5000   THEN '1. Under 5K (clubs, theaters)'
        WHEN m.capacity_per_show <= 20000 THEN '2. 5K-20K (arenas, amphitheaters)'
        ELSE                                   '3. Over 20K (stadiums)'
    END AS venue_size
FROM model_ready_engagements AS m
JOIN show_features AS f USING (engagement_id)
WHERE f.in_model_window = 1;


-- ===========================================================================
-- Right-sizing
-- ===========================================================================

-- How does each artist do in each size of room? An artist who sells out
-- every arena date may be booked too small; one who rarely fills stadiums
-- may be booked too big. Descriptive only: the right-sizing score itself is
-- a Phase 2 model output.
CREATE VIEW artist_venue_fit AS
SELECT
    artist,
    venue_size,
    COUNT(*)                        AS engagements,
    AVG(sold_out)                   AS sellout_rate,
    1.0 * SUM(tickets_sold) / SUM(capacity) AS fill_rate,
    AVG(capacity_per_show)          AS mean_capacity,
    MIN(fill_rate)                  AS worst_fill_rate
FROM model_sample
GROUP BY artist, venue_size;


-- Do multi-night runs sell better? Buyers add nights when they expect
-- demand, so the number of nights is itself a signal of what the buyer knew.
CREATE VIEW extra_nights AS
SELECT
    venue_size,
    CASE WHEN n_shows >= 3 THEN '3+' ELSE CAST(n_shows AS TEXT) END AS nights,
    COUNT(*)        AS engagements,
    AVG(sold_out)   AS sellout_rate,
    AVG(fill_rate)  AS mean_fill_rate
FROM model_sample
GROUP BY venue_size, nights;


-- Popularity per seat: pageviews divided by room size, in deciles. If
-- buyers already size rooms to popularity, this ratio (how much attention
-- each seat has behind it) should predict sellouts better than raw
-- pageviews do.
CREATE VIEW demand_per_seat AS
WITH ratio AS (
    SELECT
        engagement_id,
        sold_out,
        fill_rate,
        pageviews_mean_52w / capacity_per_show AS views_per_seat
    FROM model_sample
),
bucketed AS (
    SELECT *, NTILE(10) OVER (ORDER BY views_per_seat, engagement_id) AS decile
    FROM ratio
)
SELECT
    decile,
    COUNT(*)            AS engagements,
    MIN(views_per_seat) AS views_per_seat_min,
    MAX(views_per_seat) AS views_per_seat_max,
    AVG(sold_out)       AS sellout_rate,
    AVG(fill_rate)      AS mean_fill_rate
FROM bucketed
GROUP BY decile;


-- ===========================================================================
-- Booking history
-- ===========================================================================

-- Which tours sold best, and how did they rank against the same year's tours?
-- One row per tour in the model-ready sample, ranked by tickets sold within
-- the year the tour started.
CREATE VIEW tour_summary AS
WITH tour_totals AS (
    SELECT
        artist,
        tour,
        MIN(first_date)                     AS tour_start,
        COUNT(*)                            AS engagements,
        SUM(n_shows)                        AS shows,
        SUM(tickets_sold)                   AS tickets_sold,
        SUM(revenue_usd)                    AS revenue_usd,
        AVG(sold_out)                       AS sellout_rate,
        -- Ticket-weighted fill rate: big rooms count more than small ones
        1.0 * SUM(tickets_sold) / SUM(capacity) AS fill_rate
    FROM model_ready_engagements
    GROUP BY artist, tour
)
SELECT
    *,
    CAST(strftime('%Y', tour_start) AS INTEGER) AS start_year,
    RANK() OVER (
        PARTITION BY strftime('%Y', tour_start)
        ORDER BY tickets_sold DESC
    ) AS tickets_rank_in_year
FROM tour_totals;


-- Where does each show sit in its artist's touring history?
--
-- prior_sellout_rate uses only shows at least 182 days before this one, the
-- same cutoff as the features: a talent buyer booking this show would know
-- how those earlier shows sold, but not the ones in the months just before.
-- The RANGE frame works on day numbers (julianday), so the 182-day gap is
-- exact regardless of how many shows fall inside it.
CREATE VIEW engagement_history AS
WITH dated AS (
    SELECT
        *,
        julianday(first_date) AS show_day
    FROM model_ready_engagements
)
SELECT
    engagement_id,
    artist,
    tour,
    city,
    first_date,
    sold_out,
    fill_rate,
    ROW_NUMBER() OVER (
        PARTITION BY artist, tour ORDER BY first_date, engagement_id
    ) AS stop_number,
    -- Days since this artist last played the same city (null on a first visit)
    show_day - LAG(show_day) OVER (
        PARTITION BY artist, city ORDER BY first_date, engagement_id
    ) AS days_since_last_city_visit,
    COUNT(*) OVER prior_shows        AS prior_shows_known,
    AVG(sold_out) OVER prior_shows   AS prior_sellout_rate
FROM dated
WINDOW prior_shows AS (
    PARTITION BY artist
    ORDER BY show_day
    RANGE BETWEEN UNBOUNDED PRECEDING AND 182 PRECEDING
);


-- Does coming back to a city help or hurt? Sellout rate by time since the
-- artist's previous show in the same city.
CREATE VIEW city_revisits AS
SELECT
    CASE
        WHEN days_since_last_city_visit IS NULL THEN '0. First visit'
        WHEN days_since_last_city_visit <= 365  THEN '1. Within a year'
        WHEN days_since_last_city_visit <= 730  THEN '2. One to two years'
        ELSE                                         '3. Over two years'
    END AS since_last_visit,
    COUNT(*)        AS engagements,
    AVG(sold_out)   AS sellout_rate,
    AVG(fill_rate)  AS mean_fill_rate
FROM engagement_history
GROUP BY since_last_visit;


-- ===========================================================================
-- Signal diagnostics
-- ===========================================================================

-- Do the signals line up with demand at all? Sellout rate by decile of the
-- main signals, on the modeling sample.
--
-- Chart signals are zero for about 40% of shows (no charting song that
-- year). NTILE splits tied values across buckets by the ORDER BY tiebreaker,
-- so a first version put zeros in deciles 1 to 4 and their sellout rates
-- differed by 30 points purely because of row order. Zeros now get their own
-- bucket, decile 0 ("didn't chart"), and only positive values are split into
-- deciles 1-10.
CREATE VIEW sellout_by_signal_decile AS
WITH long_signals AS (
    SELECT 'pageviews_mean_52w' AS signal, engagement_id, pageviews_mean_52w AS value, sold_out, fill_rate FROM model_sample
    UNION ALL
    SELECT 'pageviews_en_mean_52w', engagement_id, pageviews_en_mean_52w, sold_out, fill_rate FROM model_sample
    UNION ALL
    SELECT 'hot100_lead_points_52w', engagement_id, hot100_lead_points_52w, sold_out, fill_rate FROM model_sample
    UNION ALL
    SELECT 'hot100_lead_top10_52w', engagement_id, hot100_lead_top10_52w, sold_out, fill_rate FROM model_sample
    UNION ALL
    SELECT 'hot100_lead_entries_career', engagement_id, hot100_lead_entries_career, sold_out, fill_rate FROM model_sample
    UNION ALL
    SELECT 'billboard200_lead_points_52w', engagement_id, billboard200_lead_points_52w, sold_out, fill_rate FROM model_sample
    UNION ALL
    SELECT 'billboard200_lead_entries_career', engagement_id, billboard200_lead_entries_career, sold_out, fill_rate FROM model_sample
),
bucketed AS (
    SELECT *, NTILE(10) OVER (PARTITION BY signal ORDER BY value, engagement_id) AS decile
    FROM long_signals
    WHERE value > 0
    UNION ALL
    SELECT *, 0 AS decile
    FROM long_signals
    WHERE value = 0
)
SELECT
    signal,
    decile,
    COUNT(*)        AS shows,
    MIN(value)      AS signal_min,
    MAX(value)      AS signal_max,
    AVG(sold_out)   AS sellout_rate,
    AVG(fill_rate)  AS mean_fill_rate
FROM bucketed
GROUP BY signal, decile;


-- Do pageviews tell us WHEN an artist is hot, or only WHO is popular?
-- Each show's pageviews are compared to that artist's own average across
-- their shows in the sample. If sellouts rise with this ratio, a buyer
-- learns something from an artist's attention going up; if they don't, the
-- signal only separates big artists from small ones.
--
-- Note: the artist average uses all of the artist's shows, including later
-- ones, so this is a diagnostic, not a model feature.
CREATE VIEW within_artist_pageviews AS
WITH relative AS (
    SELECT
        engagement_id,
        artist,
        sold_out,
        fill_rate,
        pageviews_mean_52w / AVG(pageviews_mean_52w) OVER (PARTITION BY artist) AS vs_own_average,
        COUNT(*) OVER (PARTITION BY artist) AS artist_shows
    FROM model_sample
),
bucketed AS (
    SELECT *, NTILE(5) OVER (ORDER BY vs_own_average, engagement_id) AS quintile
    FROM relative
    WHERE artist_shows >= 10   -- need enough shows for an artist average to mean something
)
SELECT
    quintile,
    COUNT(*)              AS shows,
    COUNT(DISTINCT artist) AS artists,
    MIN(vs_own_average)   AS ratio_min,
    MAX(vs_own_average)   AS ratio_max,
    AVG(sold_out)         AS sellout_rate,
    AVG(fill_rate)        AS mean_fill_rate
FROM bucketed
GROUP BY quintile;


-- Matt's one-hit question: are acts riding one viral song booked into rooms
-- their fan base can't fill? one_hit_shows is built in Python
-- (features/one_hit.py) because it needs song-level chart history.
CREATE VIEW one_hit_case_study AS
SELECT
    CASE WHEN o.is_one_hit = 1 THEN 'One-hit act' ELSE 'Other charting act' END AS act_type,
    COUNT(*)                         AS engagements,
    COUNT(DISTINCT s.artist)         AS artists,
    AVG(s.sold_out)                  AS sellout_rate,
    AVG(s.fill_rate)                 AS mean_fill_rate,
    AVG(s.capacity_per_show)         AS mean_capacity
FROM model_sample AS s
JOIN one_hit_shows AS o USING (engagement_id)
GROUP BY act_type;
