"""Label each show as before, during or after the COVID-19 touring shutdown.

The analysis compares how well chart and pageview signals predict demand
in each era. Fans returned to live music with pent-up demand and changed
habits, so the same signal may not mean the same thing before and after.

The boundaries are judgment calls, kept as constants so they're easy to
change or test in a robustness check:

- Start: March 12, 2020, when Live Nation and AEG suspended all tours.
- End: August 1, 2021, when large arena and stadium tours were broadly
  back on the road in the US. The few shows between these dates were
  drive-ins, test events or early restarts, not normal touring.
"""

import pandas as pd

SHUTDOWN_START = pd.Timestamp("2020-03-12")
SHUTDOWN_END = pd.Timestamp("2021-08-01")


def assign_covid_era(show_dates):
    """Label show dates "pre", "during" or "post" relative to the shutdown.

    Parameters
    ----------
    show_dates : pandas.Series
        Datetime show dates. Missing dates get no label.

    Returns
    -------
    pandas.Series
        "pre", "during", "post" or None, aligned with `show_dates`.
    """
    era = pd.Series("post", index=show_dates.index, dtype=object)
    era[show_dates < SHUTDOWN_END] = "during"
    era[show_dates < SHUTDOWN_START] = "pre"
    era[show_dates.isna()] = None
    return era
