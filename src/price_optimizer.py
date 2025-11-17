"""Price optimization logic leveraging demand forecasts and margin targets."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict

import numpy as np
import pandas as pd

from . import config

logger = logging.getLogger(__name__)


@dataclass
class OptimizationResult:
    """Represents optimized prices for each SKU and channel."""

    optimized_prices: pd.DataFrame


class PriceOptimizer:
    """Applies business rules and optimization heuristics to set prices."""

    def __init__(self, default_margins: Dict[str, float] | None = None) -> None:
        self.default_margins = default_margins or config.DEFAULT_MARGINS

    def optimize(self, forecast: pd.DataFrame, costs: pd.DataFrame) -> OptimizationResult:
        """Combine forecasts with costs to propose optimized prices."""
        merged = forecast.merge(costs, on=["sku", "channel"], how="left")
        merged["target_margin"] = merged["channel"].map(self.default_margins).fillna(0.15)
        merged["base_price"] = merged["unit_cost"] * (1 + merged["target_margin"])

        demand_factor = np.clip(merged["predicted_units"] / merged["predicted_units"].max(), 0.5, 1.5)
        merged["optimized_price"] = merged["base_price"] * demand_factor
        merged["price_with_vat"] = merged["optimized_price"] * (1 + config.VAT_RATE)
        logger.info("Optimized prices for %s records", len(merged))
        return OptimizationResult(optimized_prices=merged[
            ["sku", "channel", "optimized_price", "price_with_vat", "predicted_units"]
        ])
