"""Build the dashboard's star schema from pipeline tables.

Four tables, joined in Power BI:
- artists: one row per artist with a tour in the model sample
- tours: every tour by those artists worldwide, so the career timeline can
  show previous tours played outside the US + Canada sample
- shows: one row per model-sample show, with the grid buckets
- chart_quarters: lead chart points per artist per calendar quarter

Tours are built from the same usable worldwide history the model uses for
previous tours (models/dataset.py), with fill as an unweighted mean of
shows, so a previous tour's timeline bar agrees with the page 2 tiles
(Matt, after the final review). The tiles can still differ slightly when
the previous tour was running at booking time, because the model only
counts shows finished by then; the page labels them "at booking time".

Billboard chart data is copyrighted, so only quarterly point totals are
exported, never weekly ranks or titles. All functions are pure: they take
DataFrames and return DataFrames, and export.py handles reading and writing.
"""

import pandas as pd

from concert_demand.dashboard.buckets import (
    is_flagged_tour,
    prev_fill_bucket,
    room_change_bucket,
)
from concert_demand.features.signals import CHART_SIZES

# Per-tour "hype going in": dashboard column -> model_dataset column.
HYPE_COLUMNS = {
    "hot100_points_52w": "hot100_lead_points_52w",
    "hot100_top10_52w": "hot100_lead_top10_52w",
    "billboard200_points_52w": "billboard200_lead_points_52w",
    "pageviews_52w": "pageviews_mean_52w",
}


def tour_key(frame):
    """Key that identifies a tour across tables.

    Parameters
    ----------
    frame : pandas.DataFrame
        Has artist and tour columns.

    Returns
    -------
    pandas.Series
        "Artist | Tour" strings.
    """
    return frame["artist"] + " | " + frame["tour"]


def display_name(artist):
    """Drop Wikipedia's trailing disambiguator, e.g. "Halsey (singer)" -> "Halsey".

    Parameters
    ----------
    artist : pandas.Series
        Canonical Wikipedia titles, which stay the join key.

    Returns
    -------
    pandas.Series
        Names for slicers and tables.
    """
    return artist.str.replace(r"\s*\([^)]*\)$", "", regex=True)


def build_shows(model_dataset, right_sizing_shows):
    """One row per model-sample show, with room buckets where a previous tour exists.

    Parameters
    ----------
    model_dataset : pandas.DataFrame
        Model-sample shows (engagement_id, artist, tour, first_date, capacity_per_show,
        sold_out, fill_rate).
    right_sizing_shows : pandas.DataFrame
        Scored shows (engagement_id, room_ratio, prev_tour_fill_rate, upsized_past_rule).

    Returns
    -------
    pandas.DataFrame
    """
    # Take only the show columns needed: model_dataset also has prev_tour_fill_rate,
    # and merging two copies would rename both (_x, _y).
    show_columns = ["engagement_id", "artist", "tour", "first_date", "capacity_per_show",
                    "sold_out", "fill_rate"]
    shows = model_dataset[show_columns].merge(
        right_sizing_shows[["engagement_id", "room_ratio", "prev_tour_fill_rate", "upsized_past_rule"]],
        on="engagement_id", how="left")
    shows["tour_key"] = tour_key(shows)
    shows["room_change_bucket"] = room_change_bucket(shows["room_ratio"])
    shows["prev_fill_bucket"] = prev_fill_bucket(shows["prev_tour_fill_rate"])
    return shows[["engagement_id", "tour_key", "first_date", "capacity_per_show", "sold_out",
                  "fill_rate", "room_ratio", "room_change_bucket", "prev_fill_bucket",
                  "upsized_past_rule"]]


def _tour_outcomes(history):
    """Start date, room and outcome per tour, worldwide, using the model's previous-tour rules."""
    return (history.groupby(["artist", "tour"])
            .agg(tour_start=("first_date", "min"), shows=("first_date", "size"),
                 median_room=("capacity_per_show", "median"),
                 sellout_rate=("sold_out", "mean"), fill_rate=("fill_rate", "mean"))
            .reset_index())


def _sample_tour_signals(model_dataset):
    """Per sample tour: outcome over its sample shows, median hype, and career entries at the first show."""
    shows = model_dataset.sort_values("first_date")
    grouped = shows.groupby(["artist", "tour"])
    signals = grouped[list(HYPE_COLUMNS.values())].median().rename(
        columns={source: name for name, source in HYPE_COLUMNS.items()})
    signals["sample_shows"] = grouped.size()
    signals["sample_sellout_rate"] = grouped["sold_out"].mean()
    signals["sample_fill_rate"] = grouped["fill_rate"].mean()
    first_show = grouped.first()
    signals["career_entries"] = (first_show["hot100_lead_entries_career"]
                                 + first_show["billboard200_lead_entries_career"])
    return signals.reset_index()


def _mark_latest_sample_tour(tours):
    """Flag each artist's most recent in-sample tour (the page 2 default)."""
    sample = tours[tours["in_sample"]]
    latest = sample.loc[sample.groupby("artist")["tour_start"].idxmax(), "tour_key"]
    return tours["tour_key"].isin(latest)


def build_tours(history, right_sizing_tours, model_dataset):
    """Every tour by an artist in the model sample, with room history and outcomes.

    Parameters
    ----------
    history : pandas.DataFrame
        Usable engagements worldwide (artist, tour, first_date, capacity_per_show,
        fill_rate, sold_out), as filtered by models.dataset.usable_history.
    right_sizing_tours : pandas.DataFrame
        Tours with a previous tour (prev_tour, median_room_ratio, prev_tour_fill_rate,
        share_upsized_past_rule).
    model_dataset : pandas.DataFrame
        Model-sample shows, for in_sample, the sample outcome and the hype columns.

    Returns
    -------
    pandas.DataFrame
        shows / sellout_rate / fill_rate cover the whole tour worldwide (timeline);
        sample_* cover only its US + Canada model-sample shows ("what happened").
        prev_tour is a plain label: a few previous tours have no row of their own.
    """
    sample_artists = model_dataset["artist"].unique()
    tours = _tour_outcomes(history[history["artist"].isin(sample_artists)])
    history_columns = right_sizing_tours[["artist", "tour", "prev_tour", "median_room_ratio",
                                          "prev_tour_fill_rate", "share_upsized_past_rule"]]
    tours = (tours.merge(history_columns, on=["artist", "tour"], how="left")
             .merge(_sample_tour_signals(model_dataset), on=["artist", "tour"], how="left"))

    sample_tours = model_dataset[["artist", "tour"]].drop_duplicates()
    tours["tour_key"] = tour_key(tours)
    tours["in_sample"] = tours["tour_key"].isin(tour_key(sample_tours))
    tours["has_prev_tour"] = tours["prev_tour"].notna()
    tours["is_flagged"] = is_flagged_tour(tours["share_upsized_past_rule"]).fillna(False).astype(bool)
    tours["is_latest_in_sample"] = _mark_latest_sample_tour(tours)

    return tours[["tour_key", "artist", "tour", "tour_start", "shows", "median_room",
                  "sellout_rate", "fill_rate", "in_sample", "sample_shows", "sample_sellout_rate",
                  "sample_fill_rate", "has_prev_tour", "prev_tour", "median_room_ratio",
                  "prev_tour_fill_rate", "share_upsized_past_rule", "is_flagged",
                  "is_latest_in_sample", *HYPE_COLUMNS, "career_entries"]]


def build_artists(tours, artists_table):
    """One row per artist with an in-sample tour.

    Parameters
    ----------
    tours : pandas.DataFrame
        Output of build_tours.
    artists_table : pandas.DataFrame
        The database artists table (artist, genre_group).

    Returns
    -------
    pandas.DataFrame
        artist (join key), display_name, genre_group, and latest_tour_key (the page 2 default).
    """
    latest = (tours[tours["is_latest_in_sample"]][["artist", "tour_key"]]
              .rename(columns={"tour_key": "latest_tour_key"}))
    artists = latest.merge(artists_table[["artist", "genre_group"]], on="artist", how="left")
    artists["display_name"] = display_name(artists["artist"])
    return artists[["artist", "display_name", "genre_group", "latest_tour_key"]]


def build_chart_quarters(chart_credits, artists):
    """Lead chart points per artist, chart and calendar quarter.

    Points follow features/signals.py: a #1 earns the chart size, the last
    position earns 1. Featured credits are left out, as in the main signals.

    Parameters
    ----------
    chart_credits : pandas.DataFrame
        Weekly credits (chart, chart_week, rank, artist, role).
    artists : pandas.DataFrame
        Output of build_artists; only these artists are kept.

    Returns
    -------
    pandas.DataFrame
        artist, quarter_start, chart, lead_points. No ranks or titles.
    """
    credits = chart_credits[(chart_credits["role"] == "lead")
                            & chart_credits["artist"].isin(artists["artist"])].copy()
    credits["lead_points"] = credits["chart"].map(CHART_SIZES) + 1 - credits["rank"]
    credits["quarter_start"] = (pd.to_datetime(credits["chart_week"])
                                .dt.to_period("Q").dt.start_time.dt.date)
    return (credits.groupby(["artist", "chart", "quarter_start"], as_index=False)["lead_points"].sum()
            [["artist", "quarter_start", "chart", "lead_points"]])
