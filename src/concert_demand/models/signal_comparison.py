"""Chart signal vs. pageview signal: which tells a buyer more?

Reads the Part 1 tables and lines up, for each signal block:
- its AUC gain when it enters right after the controls ("alone"), and
- its gain when it enters after the other signal ("unique"), which is
  what it adds that the other one doesn't (Matt ran both orders for this).
Plus the joint Wald test of each block in the explanatory model, and the
Spotify block from the 2017-21 sub-analysis.

Usage
-----
    python -m concert_demand.models.signal_comparison
"""

import logging

import pandas as pd

from concert_demand.models.sellout import TABLES_DIR

GAIN_COLUMNS = ["auc_gain", "gain_low", "gain_high"]

logger = logging.getLogger(__name__)


def block_gain(ladders, ladder, block):
    """The AUC gain (with interval) where `block` enters `ladder`, per test split."""
    rows = ladders[(ladders["ladder"] == ladder) & (ladders["added_block"] == block)]
    return rows.set_index("test_split")[GAIN_COLUMNS]


def compare(ladders, coefficients):
    """One row per (signal, test split): gain alone, unique gain, and the block's Wald p-value.

    Returns
    -------
    pandas.DataFrame
    """
    wald = (coefficients[coefficients["sample"] == "all"]
            .drop_duplicates("block").set_index("block")["block_wald_p"])
    pieces = []
    for signal, other_first in [("charts", "pageviews_first"), ("pageviews", "charts_first")]:
        alone = block_gain(ladders, "charts_first" if signal == "charts" else "pageviews_first", signal)
        unique = block_gain(ladders, other_first, signal)
        piece = alone.add_suffix("_alone").join(unique.add_suffix("_unique"))
        piece["wald_p_all_years"] = wald.get(signal)
        pieces.append(piece.reset_index().assign(signal=signal))
    spotify = block_gain(ladders, "spotify", "spotify").add_suffix("_unique").reset_index()
    pieces.append(spotify.assign(signal="spotify (2017-21, after charts + pageviews)"))
    out = pd.concat(pieces, ignore_index=True)
    return out[["signal", "test_split"] + [c for c in out.columns if c not in ("signal", "test_split")]]


def run():
    """Build the comparison table from the saved Part 1 results."""
    ladders = pd.read_csv(TABLES_DIR / "sellout_ladders.csv")
    coefficients = pd.read_csv(TABLES_DIR / "sellout_coefficients.csv")
    table = compare(ladders, coefficients)
    table.to_csv(TABLES_DIR / "signal_comparison.csv", index=False)
    logger.info("Signal comparison (AUC gains):\n%s", table.round(3).to_string(index=False))
    return table


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
