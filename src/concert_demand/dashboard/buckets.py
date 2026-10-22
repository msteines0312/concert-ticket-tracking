"""Grid buckets and the flagged-tour rule shown on the dashboard.

Matt's decisions (2026-10-22, dashboard design):
- A tour is flagged when at least half of its shows were upsized past the
  break-even rule. The looser "any flagged show" rule also caught tours that
  mostly moved into smaller rooms (Noel Gallagher, Linkin Park).
- Room change buckets treat anything within 10% of the previous tour's
  room as the same size, since only 7 shows have a ratio of exactly 1.0.
- The "100%" fill bucket means exactly full, matching the sellout definition.
"""

import numpy as np
import pandas as pd

FLAG_THRESHOLD = 0.5

ROOM_ORDER = ["Smaller", "Same", "Up to 2x", "2x+"]
FILL_ORDER = ["Under 90%", "90-95%", "95-99.9%", "100%"]


def _bucket(values, conditions, labels):
    """Label each value by the first condition it meets; missing values stay missing."""
    labeled = np.select(conditions, labels, default="")
    return pd.Series(labeled, index=values.index).replace("", np.nan).where(values.notna())


def room_change_bucket(ratio):
    """Bucket the room size relative to the previous tour's median room.

    Parameters
    ----------
    ratio : pandas.Series
        Room size divided by the previous tour's room (2.0 = twice as big).

    Returns
    -------
    pandas.Series
        One of ROOM_ORDER, or NaN when there is no previous tour.
    """
    conditions = [ratio < 0.9, ratio <= 1.1, ratio <= 2.0, ratio > 2.0]
    return _bucket(ratio, conditions, ROOM_ORDER)


def prev_fill_bucket(fill):
    """Bucket how full the previous tour was (0 to 1).

    Parameters
    ----------
    fill : pandas.Series
        Previous tour fill rate, capped at 1.0 upstream.

    Returns
    -------
    pandas.Series
        One of FILL_ORDER, or NaN when there is no previous tour.
    """
    conditions = [fill < 0.90, fill < 0.95, fill < 1.0, fill >= 1.0]
    return _bucket(fill, conditions, FILL_ORDER)


def is_flagged_tour(share_upsized, threshold=FLAG_THRESHOLD):
    """True when at least `threshold` of a tour's shows were upsized past the rule."""
    return share_upsized >= threshold
