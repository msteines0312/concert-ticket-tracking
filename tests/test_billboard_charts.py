"""Tests for loading and validating the Billboard chart archive (no network calls)."""

import pandas as pd
import pytest

from concert_demand.ingest.billboard_charts import check_chart, load_chart

CSV_TEXT = """chart_week,current_week,title,performer,last_week,peak_pos,wks_on_chart,wks_at_no1
2021-01-02,1,Evermore,Taylor Swift,1,1,2,NA
2021-01-02,2,McCartney III,Paul McCartney,0,2,1,NA
2021-01-02,3,Folklore,Taylor Swift,NA,1,23,8
2021-01-09,1,Evermore,Taylor Swift,1,1,3,NA
2021-01-09,2,Folklore,Taylor Swift,3,1,24,8
2021-01-09,3,Dangerous,Morgan Wallen,NA,3,1,NA
"""


@pytest.fixture
def chart_csv(tmp_path):
    path = tmp_path / "billboard-200-current.csv"
    path.write_text(CSV_TEXT, encoding="utf-8")
    return path


def test_load_chart_standardizes_columns_and_types(chart_csv):
    chart = load_chart(chart_csv, "billboard200")
    assert list(chart.columns) == ["chart", "chart_week", "rank", "title", "performer",
                                   "last_week", "peak_pos", "wks_on_chart"]
    assert set(chart["chart"]) == {"billboard200"}
    assert chart["chart_week"].dtype == "datetime64[ns]"
    assert chart["rank"].tolist() == [1, 2, 3, 1, 2, 3]


def test_load_chart_treats_zero_and_na_last_week_as_new_entry(chart_csv):
    chart = load_chart(chart_csv, "billboard200")
    # 0 and NA both mean the title wasn't on last week's chart
    assert chart["last_week"].isna().tolist() == [False, True, True, False, False, True]


def test_load_chart_drops_exact_duplicate_rows(tmp_path):
    # The archive repeats a few rows verbatim (Eurythmics, 1984-09-29)
    path = tmp_path / "chart.csv"
    path.write_text(CSV_TEXT + "2021-01-09,3,Dangerous,Morgan Wallen,NA,3,1,NA\n", encoding="utf-8")
    assert len(load_chart(path, "billboard200")) == 6


def _weeks(*week_specs):
    """Build a chart from (date, n_entries) pairs with ranks 1..n."""
    rows = [{"chart": "hot100", "chart_week": pd.Timestamp(date), "rank": r,
             "title": f"Song {r}", "performer": "X", "last_week": pd.NA,
             "peak_pos": r, "wks_on_chart": 1}
            for date, n in week_specs for r in range(1, n + 1)]
    return pd.DataFrame(rows)


def test_check_chart_clean_data_has_no_issues():
    report = check_chart(_weeks(("2024-01-06", 3), ("2024-01-13", 3)), chart_size=3)
    assert report == {"missing_weeks": [], "incomplete_weeks": [], "duplicate_ranks": 0}


def test_check_chart_finds_missing_week():
    report = check_chart(_weeks(("2024-01-06", 3), ("2024-01-20", 3)), chart_size=3)
    assert report["missing_weeks"] == [pd.Timestamp("2024-01-13")]


def test_check_chart_allows_chart_date_weekday_change():
    # Early Hot 100 charts are dated Mondays, later ones Saturdays. A 5-day
    # gap at the switch is a convention change, not a missing week.
    report = check_chart(_weeks(("1961-12-25", 3), ("1961-12-30", 3), ("1962-01-06", 3)),
                         chart_size=3)
    assert report["missing_weeks"] == []


def test_check_chart_estimates_dates_of_a_multi_week_gap():
    report = check_chart(_weeks(("2024-01-06", 3), ("2024-01-27", 3)), chart_size=3)
    assert report["missing_weeks"] == [pd.Timestamp("2024-01-13"), pd.Timestamp("2024-01-20")]


def test_check_chart_finds_incomplete_week():
    report = check_chart(_weeks(("2024-01-06", 3), ("2024-01-13", 2)), chart_size=3)
    assert report["incomplete_weeks"] == [pd.Timestamp("2024-01-13")]


def test_check_chart_counts_duplicate_ranks():
    chart = _weeks(("2024-01-06", 3))
    chart = pd.concat([chart, chart.iloc[[0]]], ignore_index=True)
    assert check_chart(chart, chart_size=3)["duplicate_ranks"] == 1
