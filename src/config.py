"""Global configuration constants for the Dynamic Pricing System."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Dict, List, Tuple

BASE_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = BASE_DIR / "poultry_pricing" / "data"
MODEL_DIR: Path = BASE_DIR / "poultry_pricing" / "models"
OUTPUT_DIR: Path = BASE_DIR / "poultry_pricing" / "output"
LOG_DIR: Path = BASE_DIR / "poultry_pricing" / "logs"

CHANNELS: Tuple[str, ...] = (
    "VSM",
    "Pre-sales",
    "K/A",
    "Food Service",
    "Distributors",
    "Frozen",
    "Resaleable",
)

PRODUCT_CATEGORIES: Tuple[str, ...] = (
    "Fresh-A",
    "Frozen-A",
    "Cutups Fresh",
    "Cutups Frozen",
    "Marinated",
    "Giblets",
)

DEFAULT_MARGINS: Dict[str, float] = {
    "VSM": 0.18,
    "Pre-sales": 0.16,
    "K/A": 0.17,
    "Food Service": 0.15,
    "Distributors": 0.14,
    "Frozen": 0.12,
    "Resaleable": 0.15,
}

VAT_RATE: float = 0.15
CURRENCY: str = "SAR"

AGING_THRESHOLDS: Dict[str, Tuple[int, int]] = {
    "fresh": (7, 14),
    "frozen": (30, 60),
}

SAUDI_HOLIDAYS: Dict[str, Tuple[int, int]] = {
    "Founding Day": (2, 22),
    "Saudi National Day": (9, 23),
}

RAMADAN_DATES: List[Tuple[int, date, date]] = [
    (2024, date(2024, 3, 10), date(2024, 4, 9)),
    (2025, date(2025, 2, 28), date(2025, 3, 30)),
]

# File paths
RAW_SALES_FILE: Path = DATA_DIR / "raw_sales.csv"
INVENTORY_FILE: Path = DATA_DIR / "inventory.csv"
COMPETITOR_PRICE_FILE: Path = DATA_DIR / "competitor_prices.csv"
COST_FILE: Path = DATA_DIR / "product_costs.csv"
HOLIDAY_FILE: Path = DATA_DIR / "holiday_overrides.csv"
DEMAND_FORECAST_FILE: Path = OUTPUT_DIR / "demand_forecast.csv"
OPTIMIZED_PRICE_FILE: Path = OUTPUT_DIR / "optimized_prices.xlsx"
LOG_FILE: Path = LOG_DIR / "system.log"

__all__ = [
    "BASE_DIR",
    "DATA_DIR",
    "MODEL_DIR",
    "OUTPUT_DIR",
    "LOG_DIR",
    "CHANNELS",
    "PRODUCT_CATEGORIES",
    "DEFAULT_MARGINS",
    "VAT_RATE",
    "CURRENCY",
    "AGING_THRESHOLDS",
    "SAUDI_HOLIDAYS",
    "RAMADAN_DATES",
    "RAW_SALES_FILE",
    "INVENTORY_FILE",
    "COMPETITOR_PRICE_FILE",
    "COST_FILE",
    "HOLIDAY_FILE",
    "DEMAND_FORECAST_FILE",
    "OPTIMIZED_PRICE_FILE",
    "LOG_FILE",
]
