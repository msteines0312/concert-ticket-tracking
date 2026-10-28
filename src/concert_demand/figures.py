"""Save the two headline figures as PNGs for the README.

Both charts are the same ones notebooks/02_models.ipynb draws, read from
the tables the model stage saves. They are written to reports/figures/ so
GitHub can show them, since the notebooks are committed without outputs.

1. sellout_auc.png: test AUC as each signal block is added
2. room_upsizing.png: how doubling the room changes the odds of a sellout,
   depending on how full the artist's previous tour was

Usage
-----
    python -m concert_demand.figures
"""

import logging

import matplotlib

matplotlib.use("Agg")  # no window needed, and it keeps the tests headless
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from concert_demand.models.sellout import TABLES_DIR
from concert_demand.paths import PROJECT_ROOT

FIGURES_DIR = PROJECT_ROOT / "reports" / "figures"

# Same palette as the notebook: two categorical slots for the two test sets,
# plus text and grid inks.
BLUE, ORANGE = "#2a78d6", "#eb6834"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
SPLIT_COLOR = {"test_2019": BLUE, "holdout_post": ORANGE}
SPLIT_LABEL = {"test_2019": "2019 test", "holdout_post": "2022-25 holdout"}

STYLE = {"axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED,
         "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID,
         "axes.spines.top": False, "axes.spines.right": False,
         "figure.facecolor": "white", "axes.facecolor": "white"}

logger = logging.getLogger(__name__)


def read_table(tables_dir, name):
    """Read one model table, with a clear message if the models haven't run."""
    path = tables_dir / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path.name} not found: run `python -m concert_demand.models` first")
    return pd.read_csv(path)


def plot_sellout_auc(ladders):
    """Test AUC with 95% tour-resampled intervals at each step of the main ladder.

    Parameters
    ----------
    ladders : pandas.DataFrame
        The sellout_ladders table.

    Returns
    -------
    matplotlib.figure.Figure
    """
    main = ladders[ladders["ladder"] == "charts_first"]
    fig, ax = plt.subplots(figsize=(7, 3.6))
    for offset, (split, rows) in zip([-0.1, 0.1], main.groupby("test_split", sort=False)):
        x = np.arange(len(rows)) + offset
        tours = rows["test_tours"].iloc[0]
        ax.errorbar(x, rows["auc"], yerr=[rows["auc"] - rows["auc_low"], rows["auc_high"] - rows["auc"]],
                    fmt="o", ms=8, lw=2, capsize=0, color=SPLIT_COLOR[split],
                    label=f"{SPLIT_LABEL[split]} ({tours} tours)")
    ax.axhline(0.5, color=MUTED, lw=1, ls="--")
    # Between the first two steps is the only gap where no interval crosses 0.5.
    ax.text(0.5, 0.495, "coin flip", color=MUTED, fontsize=8, ha="center", va="top")
    ax.set_xticks(range(4), ["room and market", "+ charts", "+ pageviews", "+ career charts"])
    ax.set_ylabel("Test AUC")
    ax.set_title("Chart signals add little on top of room size and market", loc="left", color=INK)
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0, -0.12), ncol=2, fontsize=9)
    ax.set_xlim(-0.4, 3.4)
    fig.tight_layout()
    return fig


def plot_room_upsizing(coefficients, leave_one_out):
    """Odds multiplier per doubling of the room, across previous-tour fill rates.

    The shaded band is the range across the leave-one-tour-out refits, so it
    shows how much any single tour moves the curve.

    Parameters
    ----------
    coefficients : pandas.DataFrame
        The sellout_coefficients table.
    leave_one_out : pandas.DataFrame
        The room_leave_one_tour_out table.

    Returns
    -------
    matplotlib.figure.Figure
    """
    room = coefficients[(coefficients["sample"] == "history") & (coefficients["block"] == "room")]
    main_coef, interaction = room.set_index("predictor").loc[["room_up", "room_up_x_prev_unfilled"], "coef"]
    refits = leave_one_out[leave_one_out["dropped_tour"] != "none"].dropna(subset=["room_main"])

    # The model term is unfilled share (1 - fill), so the odds multiplier
    # for one doubling is exp(main + interaction * unfilled).
    fill = np.linspace(0.75, 1.0, 101)
    odds = np.exp(main_coef + interaction * (1 - fill))
    refit_odds = np.exp(refits["room_main"].to_numpy()[:, None]
                        + refits["room_interaction"].to_numpy()[:, None] * (1 - fill))
    break_even = 1 + main_coef / interaction

    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.fill_between(100 * fill, refit_odds.min(axis=0), refit_odds.max(axis=0), color=BLUE, alpha=0.15, lw=0)
    ax.plot(100 * fill, odds, color=BLUE, lw=2)
    ax.axhline(1, color=MUTED, lw=1, ls="--")
    ax.axvline(100 * break_even, color=MUTED, lw=1)
    ax.annotate(f"break-even: {break_even:.1%} full", (100 * break_even, 2.0), xytext=(-8, 0),
                textcoords="offset points", ha="right", color=INK, fontsize=9)
    ax.text(76, 1.04, "no change in odds", color=MUTED, fontsize=8, va="bottom")
    ax.set_xlabel("How full the artist's previous tour was (%)")
    ax.set_ylabel("Odds multiplier per doubling")
    ax.set_title("Upsizing only pays off after a nearly full tour", loc="left", color=INK)
    fig.tight_layout()
    return fig


def run(tables_dir=TABLES_DIR, out_dir=FIGURES_DIR):
    """Draw both figures from the model tables and save them as PNGs."""
    ladders = read_table(tables_dir, "sellout_ladders")
    coefficients = read_table(tables_dir, "sellout_coefficients")
    leave_one_out = read_table(tables_dir, "room_leave_one_tour_out")

    out_dir.mkdir(parents=True, exist_ok=True)
    with plt.rc_context(STYLE):
        figures = {"sellout_auc.png": plot_sellout_auc(ladders),
                   "room_upsizing.png": plot_room_upsizing(coefficients, leave_one_out)}
    for name, fig in figures.items():
        fig.savefig(out_dir / name, dpi=200, bbox_inches="tight")
        plt.close(fig)
        logger.info("saved %s", out_dir / name)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()
