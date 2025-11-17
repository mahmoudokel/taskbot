"""Demand forecasting components for dynamic pricing."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error
from sklearn.ensemble import RandomForestRegressor

from . import config

logger = logging.getLogger(__name__)


@dataclass
class ForecastResult:
    """Holds forecast outputs and evaluation metrics."""

    forecast: pd.DataFrame
    mae: Optional[float] = None


class DemandForecaster:
    """Trains and persists demand forecasting models."""

    def __init__(self, model_path: Path | None = None) -> None:
        self.model_path = model_path or (config.MODEL_DIR / "demand_forecast.pkl")
        self.model: RandomForestRegressor | None = None

    def train(self, frame: pd.DataFrame, target: str = "units_sold") -> ForecastResult:
        """Train a baseline model and report MAE."""
        features = frame.drop(columns=[target])
        X_train, X_test, y_train, y_test = train_test_split(features, frame[target], test_size=0.2, random_state=42)
        self.model = RandomForestRegressor(n_estimators=200, random_state=42)
        self.model.fit(X_train, y_train)
        predictions = self.model.predict(X_test)
        mae = mean_absolute_error(y_test, predictions)
        logger.info("Trained demand forecaster with MAE=%s", mae)
        return ForecastResult(forecast=pd.DataFrame({"prediction": predictions}), mae=mae)

    def predict(self, frame: pd.DataFrame) -> pd.Series:
        """Generate demand forecasts using the trained model."""
        if self.model is None:
            raise RuntimeError("Model has not been trained")
        return pd.Series(self.model.predict(frame), index=frame.index, name="predicted_units")
