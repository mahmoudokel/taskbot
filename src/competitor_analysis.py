"""Competitor price intelligence utilities."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import config

logger = logging.getLogger(__name__)


@dataclass
class CompetitorSnapshot:
    """Captures competitor pricing for a specific date range."""

    data: pd.DataFrame


class CompetitorAnalyzer:
    """Aggregates competitor pricing data for downstream optimization."""

    def __init__(self, source: Path | None = None) -> None:
        self.source = source or config.COMPETITOR_PRICE_FILE

    def load(self) -> CompetitorSnapshot:
        logger.info("Loading competitor pricing from %s", self.source)
        frame = pd.read_csv(self.source)
        return CompetitorSnapshot(data=frame)

    def summarize(self, snapshot: CompetitorSnapshot) -> pd.DataFrame:
        """Generate summary statistics by SKU and channel."""
        summary = snapshot.data.groupby(["sku", "channel"]).agg(
            median_price=("price", "median"),
            min_price=("price", "min"),
            max_price=("price", "max"),
        )
        summary = summary.reset_index()
        logger.debug("Competitor summary created for %s SKUs", summary["sku"].nunique())
        return summary
