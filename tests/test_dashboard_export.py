"""Tests for the dashboard export runner."""

import pandas as pd
import pytest

from concert_demand.dashboard.export import chart_test_table, run


def test_missing_model_output_names_the_file(tmp_path):
    with pytest.raises(FileNotFoundError) as error:
        run(tables_dir=tmp_path, out_dir=tmp_path / "out")
    assert "room_effect.csv" in str(error.value)
    assert "python -m concert_demand.models" in str(error.value)


def test_chart_test_keeps_two_steps_per_split():
    rows = [(ladder, split, step, 0.5, 0.4, 0.6, 30)
            for ladder in ["charts_first", "history"]
            for split in ["test_2019", "holdout_post"]
            for step in ["controls", "controls+charts", "controls+charts+pageviews"]]
    ladders = pd.DataFrame(rows, columns=["ladder", "test_split", "step", "auc",
                                          "auc_low", "auc_high", "test_tours"])
    table = chart_test_table(ladders)
    assert len(table) == 4
    assert set(table["step"]) == {"controls", "controls+charts"}
    assert table.columns.tolist() == ["test_split", "step", "auc", "auc_low", "auc_high", "test_tours"]
