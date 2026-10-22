"""Tests for the chart vs. pageview comparison table."""

import pandas as pd
import pytest

from concert_demand.models.signal_comparison import compare


def _ladder_row(ladder, block, gain):
    return {"ladder": ladder, "test_split": "test_2019", "added_block": block,
            "auc_gain": gain, "gain_low": gain - 0.1, "gain_high": gain + 0.1}


def test_alone_and_unique_gains_come_from_opposite_orders():
    ladders = pd.DataFrame([_ladder_row("charts_first", "charts", 0.05),
                            _ladder_row("charts_first", "pageviews", 0.01),
                            _ladder_row("pageviews_first", "pageviews", 0.04),
                            _ladder_row("pageviews_first", "charts", 0.02),
                            _ladder_row("spotify", "spotify", 0.0)])
    coefficients = pd.DataFrame({"sample": "all", "block": ["charts", "pageviews"],
                                 "block_wald_p": [0.3, 0.4]})
    table = compare(ladders, coefficients).set_index("signal")
    assert table.loc["charts", "auc_gain_alone"] == pytest.approx(0.05)
    assert table.loc["charts", "auc_gain_unique"] == pytest.approx(0.02)   # entered after pageviews
    assert table.loc["pageviews", "auc_gain_unique"] == pytest.approx(0.01)
    assert table.loc["pageviews", "wald_p_all_years"] == pytest.approx(0.4)
