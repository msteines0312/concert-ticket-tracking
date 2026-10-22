"""Run the whole Phase 2 model stage in order.

Each step reads what the previous one saved, so the order matters:
the dataset first, the sellout ladders before the comparison that reads
them, and the robustness checks before the right-sizing score.

Usage
-----
    python -m concert_demand.models
"""

import logging

from concert_demand.ingest import cpi
from concert_demand.models import (
    covid_comparison,
    dataset,
    expected_fill,
    fill_rate,
    right_sizing,
    robustness,
    sellout,
    signal_comparison,
)

STEPS = [dataset, sellout, fill_rate, expected_fill, signal_comparison,
         covid_comparison, robustness, right_sizing]

logger = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not cpi.OUTPUT_PATH.exists():
        raise SystemExit("CPI table missing: run `python -m concert_demand.ingest.cpi` first")
    for step in STEPS:
        logger.info("=== %s ===", step.__name__)
        step.run()


if __name__ == "__main__":
    main()
