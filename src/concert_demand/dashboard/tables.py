"""Build the dashboard's star schema from pipeline tables.

Four tables, joined in Power BI:
- artists: one row per artist with a tour in the model sample
- tours: every worldwide tour by those artists, so the career timeline can
  show previous tours that fall outside the US + Canada sample
- shows: one row per model-sample show, with the grid buckets
- chart_quarters: lead chart points per artist per calendar quarter

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
    """Key that identifies a tour across tables ("Artist | Tour")."""
    return frame["artist"] + " | " + frame["tour"]


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
    shows = model_dataset.merge(
        right_sizing_shows[["engagement_id", "room_ratio", "prev_tour_fill_rate", "upsized_past_rule"]],
        on="engagement_id", how="left")
    shows["tour_key"] = tour_key(shows)
    shows["room_change_bucket"] = room_change_bucket(shows["room_ratio"])
    shows["prev_fill_bucket"] = prev_fill_bucket(shows["prev_tour_fill_rate"])
    return shows[["engagement_id", "tour_key", "first_date", "capacity_per_show", "sold_out",
                  "fill_rate", "room_ratio", "room_change_bucket", "prev_fill_bucket",
                  "upsized_past_rule"]]


def _sample_tour_signals(model_dataset):
    """Median hype per sample tour, plus career chart entries as of the tour's first show."""
    shows = model_dataset.sort_values("first_date")
    grouped = shows.groupby(["artist", "tour"])
    hype = grouped[list(HYPE_COLUMNS.values())].median().rename(
        columns={source: name for name, source in HYPE_COLUMNS.items()})
    first_show = grouped.first()
    hype["career_entries"] = (first_show["hot100_lead_entries_career"]
                              + first_show["billboard200_lead_entries_career"])
    return hype.reset_index()


def _mark_latest_sample_tour(tours):
    """Flag each artist's most recent in-sample tour (the page 2 default)."""
    sample = tours[tours["in_sample"]]
    latest = sample.loc[sample.groupby("artist")["tour_start"].idxmax(), "tour_key"]
    return tours["tour_key"].isin(latest)


def build_tours(tour_summary, engagements, right_sizing_tours, model_dataset):
    """Every tour by an artist in the model sample, with room history and outcomes.

    Parameters
    ----------
    tour_summary : pandas.DataFrame
        One row per tour (artist, tour, tour_start, sellout_rate, fill_rate).
    engagements : pandas.DataFrame
        Show-level rooms (artist, tour, capacity_per_show), the same rows tour_summary uses.
    right_sizing_tours : pandas.DataFrame
        Tours with a previous tour (prev_tour, median_room_ratio, prev_tour_fill_rate,
        share_upsized_past_rule).
    model_dataset : pandas.DataFrame
        Model-sample shows, for in_sample and the hype columns.

    Returns
    -------
    pandas.DataFrame
        prev_tour is a plain label: some previous tours have no row of their own.
    """
    sample_artists = model_dataset["artist"].unique()
    tours = tour_summary[tour_summary["artist"].isin(sample_artists)][
        ["artist", "tour", "tour_start", "sellout_rate", "fill_rate"]]

    rooms = (engagements.groupby(["artist", "tour"])["capacity_per_show"].median()
             .rename("median_room").reset_index())
    history = right_sizing_tours[["artist", "tour", "prev_tour", "median_room_ratio",
                                  "prev_tour_fill_rate", "share_upsized_past_rule"]]
    tours = (tours.merge(rooms, on=["artist", "tour"], how="left")
             .merge(history, on=["artist", "tour"], how="left")
             .merge(_sample_tour_signals(model_dataset), on=["artist", "tour"], how="left"))

    sample_tours = model_dataset[["artist", "tour"]].drop_duplicates()
    tours["tour_key"] = tour_key(tours)
    tours["in_sample"] = tours["tour_key"].isin(tour_key(sample_tours))
    tours["has_prev_tour"] = tours["prev_tour"].notna()
    tours["is_flagged"] = is_flagged_tour(tours["share_upsized_past_rule"]).fillna(False).astype(bool)
    tours["is_latest_in_sample"] = _mark_latest_sample_tour(tours)

    return tours[["tour_key", "artist", "tour", "tour_start", "median_room", "sellout_rate",
                  "fill_rate", "in_sample", "has_prev_tour", "prev_tour", "median_room_ratio",
                  "prev_tour_fill_rate", "share_upsized_past_rule", "is_flagged",
                  "is_latest_in_sample", *HYPE_COLUMNS, "career_entries"]]


def build_artists(tours, artists_table):
    """One row per artist with an in-sample tour: genre and the page 2 default tour."""
    latest = (tours[tours["is_latest_in_sample"]][["artist", "tour_key"]]
              .rename(columns={"tour_key": "latest_tour_key"}))
    return latest.merge(artists_table[["artist", "genre_group"]], on="artist", how="left")[
        ["artist", "genre_group", "latest_tour_key"]]


def build_chart_quarters(chart_credits, artists):
    """Lead chart points per artist, chart and calendar quarter.

    Points follow features/signals.py: a #1 earns the chart size, the last
    position earns 1. Featured credits are left out, as in the main signals.
    """
    credits = chart_credits[(chart_credits["role"] == "lead")
                            & chart_credits["artist"].isin(artists["artist"])].copy()
    credits["lead_points"] = credits["chart"].map(CHART_SIZES) + 1 - credits["rank"]
    credits["quarter_start"] = (pd.to_datetime(credits["chart_week"])
                                .dt.to_period("Q").dt.start_time.dt.date)
    return (credits.groupby(["artist", "chart", "quarter_start"], as_index=False)["lead_points"].sum()
            [["artist", "quarter_start", "chart", "lead_points"]])
