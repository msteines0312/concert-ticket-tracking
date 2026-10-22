"""Tests for the CPI-U download and constant-dollar conversion."""

import pandas as pd
import pytest

from concert_demand.ingest.cpi import annual_averages, parse_monthly, to_constant_dollars, year_chunks


def test_year_chunks_respect_the_ten_year_api_limit():
    assert year_chunks(2009, 2025) == [(2009, 2018), (2019, 2025)]
    assert year_chunks(2020, 2024) == [(2020, 2024)]


def test_unpublished_months_are_dropped_not_read_as_zero():
    records = [{"year": "2025", "period": "M09", "value": "324.8"},
               {"year": "2025", "period": "M10", "value": "-"},     # 2025 funding lapse
               {"year": "2025", "period": "M11", "value": "324.2"},
               {"year": "2025", "period": "M13", "value": "999.0"}]  # annual row: skipped
    annual = annual_averages(parse_monthly(records))
    assert annual.loc[0, "months"] == 2
    assert annual.loc[0, "cpi_u"] == pytest.approx(324.5)


def test_constant_dollars_scale_by_the_base_year_index():
    annual = pd.DataFrame({"year": [2014, 2024], "cpi_u": [200.0, 300.0]})
    converted = to_constant_dollars(pd.Series([100.0, 100.0]), pd.Series([2014, 2024]),
                                    annual, base_year=2024)
    assert converted.tolist() == pytest.approx([150.0, 100.0])


def test_years_without_cpi_come_back_null():
    annual = pd.DataFrame({"year": [2024], "cpi_u": [300.0]})
    converted = to_constant_dollars(pd.Series([100.0]), pd.Series([2008]), annual, base_year=2024)
    assert converted.isna().all()
