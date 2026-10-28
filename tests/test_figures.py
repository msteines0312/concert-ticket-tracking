"""Tests for the README figure export."""

import pandas as pd
import pytest

from concert_demand.figures import run


def write_fake_tables(tables_dir):
    """Small made-up versions of the three tables the figures read."""
    steps = ["controls", "controls+charts", "controls+charts+pageviews", "controls+charts+pageviews+career"]
    ladder_rows = [("charts_first", split, step, block, 0.55, 0.45, 0.65, tours)
                   for split, tours in [("test_2019", 36), ("holdout_post", 93)]
                   for step, block in zip(steps, ["controls", "charts", "pageviews", "career"])]
    pd.DataFrame(ladder_rows, columns=["ladder", "test_split", "step", "added_block", "auc",
                                       "auc_low", "auc_high", "test_tours"]
                 ).to_csv(tables_dir / "sellout_ladders.csv", index=False)
    pd.DataFrame({"sample": ["history", "history"], "block": ["room", "room"],
                  "predictor": ["room_up", "room_up_x_prev_unfilled"], "coef": [0.88, -12.3]}
                 ).to_csv(tables_dir / "sellout_coefficients.csv", index=False)
    pd.DataFrame({"dropped_tour": ["none", "Tour A", "Tour B"], "room_main": [0.88, 0.8, 0.95],
                  "room_interaction": [-12.3, -11.0, -13.0]}
                 ).to_csv(tables_dir / "room_leave_one_tour_out.csv", index=False)


def test_run_saves_both_figures(tmp_path):
    write_fake_tables(tmp_path)
    run(tables_dir=tmp_path, out_dir=tmp_path / "figures")
    for name in ["sellout_auc.png", "room_upsizing.png"]:
        path = tmp_path / "figures" / name
        assert path.exists() and path.stat().st_size > 0


def test_missing_model_output_names_the_file(tmp_path):
    with pytest.raises(FileNotFoundError) as error:
        run(tables_dir=tmp_path, out_dir=tmp_path / "figures")
    assert "sellout_ladders.csv" in str(error.value)
    assert "python -m concert_demand.models" in str(error.value)
