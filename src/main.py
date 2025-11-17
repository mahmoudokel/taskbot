"""CLI entrypoint for orchestrating the dynamic pricing workflow."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from . import config
from .competitor_analysis import CompetitorAnalyzer
from .data_processor import DataProcessor
from .demand_forecasting import DemandForecaster
from .excel_generator import ExcelGenerator
from .price_optimizer import PriceOptimizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def run(raw_sources: list[Path] | None = None) -> Path:
    raw_sources = raw_sources or [config.RAW_SALES_FILE]
    processor = DataProcessor()
    forecaster = DemandForecaster()
    optimizer = PriceOptimizer()
    excel_writer = ExcelGenerator()
    competitor_analyzer = CompetitorAnalyzer()

    combined = processor.load_sources(raw_sources)
    combined = processor.normalize_channels(combined)
    combined = processor.enrich_with_holidays(combined)

    competitor_snapshot = competitor_analyzer.load()
    competitor_summary = competitor_analyzer.summarize(competitor_snapshot)
    combined = combined.merge(competitor_summary, on=["sku", "channel"], how="left")

    forecast_result = forecaster.train(combined)
    combined["predicted_units"] = forecast_result.forecast["prediction"].reindex(combined.index, fill_value=0)

    cost_frame = pd.read_csv(config.COST_FILE)
    optimized = optimizer.optimize(combined, cost_frame)

    output_path = excel_writer.generate(optimized.optimized_prices)
    logger.info("Dynamic pricing workflow complete. Output saved to %s", output_path)
    return output_path


def main() -> None:
    run()


if __name__ == "__main__":
    main()
