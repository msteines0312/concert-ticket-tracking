"""Merge shows that appear on two tour pages into one row.

When two acts share a bill, both artists' tour pages can list the same
show. Left alone, one sellout would count twice, credited to two artists.
Each known case was checked by hand against the tour pages:

- Kenny Chesney and Jason Aldean merged their 2015 tours for ten stadium
  shows. That's a true co-headline, so one row is kept with both artists.
- The Smashing Pumpkins and Marilyn Manson co-headlined The End Times Tour.
- ZZ Top opened for Guns N' Roses, and Lali opened for Katy Perry. An
  opener doesn't drive ticket sales, so only the headliner's row is kept.

Any other pair of tours opening at the same venue on the same night is
either an unchecked shared bill or a page error, so both rows are flagged
`conflicting_sources` and logged. The same flag marks a merged show whose two pages report
different numbers, since there's no way to know which page is right.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# Tour whose duplicate rows are dropped -> (tour that keeps the show, billing)
SHARED_BILLS = {
    "Burn It Down Tour": ("The Big Revival Tour", "co-headline"),
    "The Hell Not Hallelujah Tour": ("The End Times Tour", "co-headline"),
    "Tonnage Tour": ("Not in This Lifetime... Tour", "opener"),
    "A Bailar Tour": ("Prismatic World Tour", "opener"),
}


def _add_co_headliner(cell, artist):
    """Append `artist` to a "; "-separated co-headliner cell if it's missing."""
    names = [] if pd.isna(cell) else [name.strip() for name in cell.split(";") if name.strip()]
    if artist not in names:
        names.append(artist)
    return "; ".join(names)


def _merge_listed_bills(out, shared_bills):
    """Drop the second listing of each hand-checked shared show.

    Shows are matched on city and first date, not venue, because the two
    pages can spell the venue differently ("Hipódromo de Palermo" vs
    "Hipódromo Argentino de Palermo").
    """
    drop_index = []
    for drop_tour, (keep_tour, billing) in shared_bills.items():
        keep = out[(out["tour"] == keep_tour) & out["first_date"].notna()]
        drop = out[(out["tour"] == drop_tour) & out["first_date"].notna()]
        pairs = keep.reset_index().merge(drop.reset_index(), on=["city", "first_date"],
                                         suffixes=("_keep", "_drop"))
        for _, pair in pairs.iterrows():
            drop_index.append(pair["index_drop"])
            if billing == "co-headline":
                cell = _add_co_headliner(out.at[pair["index_keep"], "co_headliners"],
                                         pair["artist_drop"])
                out.at[pair["index_keep"], "co_headliners"] = cell
                out.at[pair["index_keep"], "n_headliners"] = 1 + len(cell.split("; "))
            if (pair["tickets_sold_keep"], pair["capacity_keep"]) != (
                    pair["tickets_sold_drop"], pair["capacity_drop"]):
                out.at[pair["index_keep"], "conflicting_sources"] = True
                logger.warning("%s and %s disagree on %s, %s: flagged",
                               keep_tour, drop_tour, pair["venue_keep"],
                               pair["first_date"].date())
    return out.drop(index=drop_index)


def _flag_unlisted_overlaps(out):
    """Flag rows from different tours at one venue on the same opening night.

    Only first dates are compared, not whole date ranges. A multi-night run
    isn't always on consecutive nights: Harry Styles' 15 Madison Square
    Garden shows ran Aug 20 to Sep 21, 2022, with other acts on the open
    nights in between. The first date is the one night a run certainly
    includes.
    """
    dated = out[out["first_date"].notna() & out["venue"].notna()].reset_index()
    pairs = dated.merge(dated, on=["city", "venue", "first_date"], suffixes=("", "_other"))
    overlaps = pairs[pairs["tour"] < pairs["tour_other"]]
    for _, pair in overlaps.iterrows():
        logger.warning("%s and %s both list %s on %s: flagged as conflicting",
                       pair["tour"], pair["tour_other"], pair["venue"],
                       pair["first_date"].date())
    out.loc[overlaps["index"].tolist() + overlaps["index_other"].tolist(),
            "conflicting_sources"] = True
    return out


def merge_shared_shows(engagements, shared_bills=SHARED_BILLS):
    """Keep one row per shared show and flag shows the sources disagree on.

    Parameters
    ----------
    engagements : pandas.DataFrame
        All engagements, with datetime first_date and last_date.
    shared_bills : dict, optional
        Tour to drop -> (tour to keep, "co-headline" or "opener").

    Returns
    -------
    pandas.DataFrame
        Engagements without duplicate listings, plus `conflicting_sources`.
    """
    out = engagements.copy()
    out["conflicting_sources"] = False
    before = len(out)
    out = _merge_listed_bills(out, shared_bills)
    out = _flag_unlisted_overlaps(out)
    logger.info("Merged %d shared shows, %d rows flagged as conflicting",
                before - len(out), out["conflicting_sources"].sum())
    return out.reset_index(drop=True)
