"""Demand forecasting module with Prophet and XGBoost models."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import joblib
import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from prophet import Prophet
from prophet.serialize import model_from_json, model_to_json
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, mean_squared_error
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBRegressor

from . import config

logger = logging.getLogger(__name__)


@dataclass
class ForecastMetrics:
    """Captured evaluation metrics."""

    mape: float
    rmse: float
    mae: float


@dataclass
class ForecastResult:
    """Holds forecast outputs and evaluation metrics."""

    forecast: pd.DataFrame
    metrics: Optional[ForecastMetrics] = None
    plots: List[Path] = field(default_factory=list)


class DemandForecaster:
    """Demand forecaster using Prophet and XGBoost for a SKU-channel pair."""

    def __init__(
        self, sku: str, channel: str, historical_data: pd.DataFrame, product_category: Optional[str] = None
    ) -> None:
        self.sku = sku
        self.channel = channel
        self.product_category = product_category or "Unknown"
        self.historical_data = historical_data.copy()
        self.prophet_model: Optional[Prophet] = None
        self.xgb_model: Optional[XGBRegressor] = None
        self.feature_columns: List[str] = []
        self.model_dir = config.MODEL_DIR
        self.model_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("Initialized DemandForecaster for SKU=%s channel=%s", sku, channel)

    @staticmethod
    def _holiday_frame() -> pd.DataFrame:
        """Build Prophet-compatible holiday dataframe for Saudi holidays and Ramadan."""
        records: List[Dict[str, object]] = []
        for name, (month, day) in config.SAUDI_HOLIDAYS.items():
            for year in range(datetime.now().year - 2, datetime.now().year + 3):
                try:
                    records.append({"holiday": name, "ds": datetime(year, month, day)})
                except ValueError:
                    logger.debug("Skipping invalid holiday date for %s in %s", name, year)
        for year, start_date, end_date in config.RAMADAN_DATES:
            current = start_date
            while current <= end_date:
                records.append({"holiday": "Ramadan", "ds": datetime.combine(current, datetime.min.time())})
                current += timedelta(days=1)
        return pd.DataFrame(records)

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create lagged, rolling, seasonal, and contextual features."""
        frame = df.copy()
        frame = frame.sort_values("date")
        frame["date"] = pd.to_datetime(frame["date"])
        frame["sales"] = frame["sales"].astype(float)
        frame["price"] = frame["price"].astype(float)

        frame["sales_lag_7d"] = frame["sales"].shift(7)
        frame["sales_lag_14d"] = frame["sales"].shift(14)
        frame["sales_lag_30d"] = frame["sales"].shift(30)

        frame["rolling_mean_7d"] = frame["sales"].rolling(window=7, min_periods=3).mean()
        frame["rolling_mean_30d"] = frame["sales"].rolling(window=30, min_periods=7).mean()

        frame["month"] = frame["date"].dt.month
        frame["quarter"] = frame["date"].dt.quarter
        frame["day_of_week"] = frame["date"].dt.dayofweek
        frame["is_weekend"] = frame["day_of_week"].isin([4, 5]).astype(int)

        ramadan_days = []
        hajj_months = []
        for year, start_date, end_date in config.RAMADAN_DATES:
            ramadan_days.extend(pd.date_range(start=start_date, end=end_date).to_pydatetime().tolist())
            hajj_months.append((year, 12))
        frame["is_ramadan"] = frame["date"].dt.normalize().isin(ramadan_days).astype(int)
        frame["is_hajj"] = frame["date"].apply(lambda d: int((d.year, d.month) in hajj_months))

        saudi_holidays = [datetime(d.year, month, day) for d in frame["date"] for _, (month, day) in config.SAUDI_HOLIDAYS.items() if d.month == month and d.day == day]
        frame["is_holiday"] = frame["date"].dt.normalize().isin(saudi_holidays).astype(int)

        def _days_to_ramadan(day: pd.Timestamp) -> int:
            deltas = []
            for _, start_date, _ in config.RAMADAN_DATES:
                deltas.append((start_date - day.date()).days)
            deltas = [d for d in deltas if d >= 0]
            return min(deltas) if deltas else -1

        frame["days_to_ramadan"] = frame["date"].apply(_days_to_ramadan)

        frame["price_change_pct"] = frame["price"].pct_change() * 100
        if "competitor_price" in frame.columns:
            frame["competitor_price_gap"] = ((frame["price"] - frame["competitor_price"]) / frame["competitor_price"]) * 100
        else:
            frame["competitor_price_gap"] = np.nan
        frame["competitor_price_gap"] = frame["competitor_price_gap"].replace([np.inf, -np.inf], np.nan)

        if "temperature" not in frame.columns:
            frame["temperature"] = np.nan
        if "promotion_flag" not in frame.columns:
            frame["promotion_flag"] = 0

        frame = frame.fillna(method="ffill").fillna(method="bfill")
        frame = frame.dropna()

        self.feature_columns = [
            "sales_lag_7d",
            "sales_lag_14d",
            "sales_lag_30d",
            "rolling_mean_7d",
            "rolling_mean_30d",
            "month",
            "quarter",
            "day_of_week",
            "is_weekend",
            "is_ramadan",
            "is_hajj",
            "is_holiday",
            "days_to_ramadan",
            "price",
            "price_change_pct",
            "competitor_price_gap",
            "temperature",
            "promotion_flag",
        ]
        logger.debug("Prepared features with columns: %s", self.feature_columns)
        return frame

    def train_prophet_model(self) -> Prophet:
        """Train a Prophet model with Saudi holidays and price regressor."""
        frame = self.historical_data.copy()
        frame = frame.rename(columns={"date": "ds", "sales": "y"})
        frame["ds"] = pd.to_datetime(frame["ds"])

        model = Prophet(
            yearly_seasonality=True,
            weekly_seasonality=True,
            daily_seasonality=False,
            holidays=self._holiday_frame(),
        )
        if "price" in frame.columns:
            model.add_regressor("price")
        logger.info("Training Prophet model for SKU=%s channel=%s", self.sku, self.channel)
        model.fit(frame[["ds", "y", "price"]] if "price" in frame.columns else frame[["ds", "y"]])
        self.prophet_model = model
        return model

    def train_xgboost_model(self) -> XGBRegressor:
        """Train an XGBoost model using engineered features with time-series CV."""
        feature_frame = self.prepare_features(self.historical_data)
        target = feature_frame["sales"]
        features = feature_frame[self.feature_columns]

        tscv = TimeSeriesSplit(n_splits=3)
        model = XGBRegressor(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.1,
            objective="reg:squarederror",
            subsample=0.9,
            colsample_bytree=0.8,
            random_state=42,
        )

        for fold, (train_idx, val_idx) in enumerate(tscv.split(features), start=1):
            X_train, X_val = features.iloc[train_idx], features.iloc[val_idx]
            y_train, y_val = target.iloc[train_idx], target.iloc[val_idx]
            model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
            logger.debug("Fold %s validation RMSE: %.4f", fold, float(np.sqrt(mean_squared_error(y_val, model.predict(X_val)))))

        model.fit(features, target)
        self.xgb_model = model
        logger.info("Trained XGBoost model for SKU=%s channel=%s", self.sku, self.channel)
        return model

    def _build_future_frame(self, horizon_days: int, price_scenario: Optional[Iterable[float]]) -> pd.DataFrame:
        """Extend historical data with future dates and price scenario."""
        last_date = pd.to_datetime(self.historical_data["date"].max())
        future_dates = pd.date_range(start=last_date + timedelta(days=1), periods=horizon_days, freq="D")
        base_price = self.historical_data["price"].iloc[-1]
        scenario_prices = list(price_scenario) if price_scenario is not None else [base_price] * horizon_days
        if len(scenario_prices) < horizon_days:
            scenario_prices.extend([scenario_prices[-1]] * (horizon_days - len(scenario_prices)))
        future = pd.DataFrame({"date": future_dates, "price": scenario_prices})

        base_columns = ["date", "sales", "price"]
        optional_columns = [col for col in ["competitor_price", "temperature", "promotion_flag"] if col in self.historical_data.columns]
        combined = pd.concat(
            [self.historical_data[base_columns + optional_columns], future], ignore_index=True, sort=False
        )
        return combined

    def forecast_demand(self, horizon_days: int = 28, price_scenario: Optional[Iterable[float]] = None) -> pd.DataFrame:
        """Generate Prophet and XGBoost forecasts and blend them."""
        if self.prophet_model is None:
            self.train_prophet_model()
        if self.xgb_model is None:
            self.train_xgboost_model()

        combined = self._build_future_frame(horizon_days, price_scenario)
        feature_frame = self.prepare_features(combined)

        prophet_future = pd.DataFrame({"ds": feature_frame["date"]})
        if "price" in self.historical_data.columns:
            prophet_future["price"] = feature_frame["price"].values
        prophet_pred = self.prophet_model.predict(prophet_future)
        prophet_values = prophet_pred["yhat"].tail(horizon_days).values

        xgb_features = feature_frame[self.feature_columns].tail(horizon_days)
        xgb_pred = self.xgb_model.predict(xgb_features)

        blended = 0.6 * prophet_values + 0.4 * xgb_pred
        lower = blended * 0.9
        upper = blended * 1.1

        forecast_dates = feature_frame["date"].tail(horizon_days).reset_index(drop=True)
        forecast_df = pd.DataFrame(
            {
                "date": forecast_dates,
                "predicted_demand": blended,
                "lower_bound": lower,
                "upper_bound": upper,
                "prophet_pred": prophet_values,
                "xgb_pred": xgb_pred,
            }
        )
        logger.info("Generated forecast for SKU=%s channel=%s for %s days", self.sku, self.channel, horizon_days)
        return forecast_df

    def evaluate_model(self, test_data: pd.DataFrame) -> Dict[str, float]:
        """Evaluate blended model on held-out data and return metrics."""
        if self.xgb_model is None:
            raise RuntimeError("XGBoost model must be trained before evaluation")

        test_features = self.prepare_features(test_data)
        actuals = test_features["sales"]
        predicted = self.xgb_model.predict(test_features[self.feature_columns])
        mape = mean_absolute_percentage_error(actuals, predicted)
        rmse = float(np.sqrt(mean_squared_error(actuals, predicted)))
        mae = mean_absolute_error(actuals, predicted)

        plot_path = self._plot_forecast(test_features["date"], actuals, predicted)
        logger.info("Evaluation for SKU=%s channel=%s -> MAPE=%.3f RMSE=%.3f MAE=%.3f", self.sku, self.channel, mape, rmse, mae)
        return {"mape": mape, "rmse": rmse, "mae": mae, "plot_path": str(plot_path)}

    def _plot_forecast(self, dates: pd.Series, actuals: pd.Series, predicted: Iterable[float]) -> Path:
        """Generate and save a forecast comparison plot."""
        plots_dir = config.OUTPUT_DIR / "plots"
        plots_dir.mkdir(parents=True, exist_ok=True)
        plt.figure(figsize=(10, 5))
        plt.plot(dates, actuals, label="Actual", marker="o")
        plt.plot(dates, predicted, label="Predicted", marker="x")
        plt.title(f"Demand Forecast: {self.sku} - {self.channel}")
        plt.xlabel("Date")
        plt.ylabel("Units")
        plt.legend()
        plt.tight_layout()
        file_path = plots_dir / f"forecast_{self.sku}_{self.channel}.png"
        plt.savefig(file_path)
        plt.close()
        logger.debug("Saved forecast plot to %s", file_path)
        return file_path

    def save_models(self) -> None:
        """Persist trained models to disk."""
        if self.prophet_model:
            prophet_path = self.model_dir / f"prophet_{self.sku}_{self.channel}.json"
            prophet_path.write_text(model_to_json(self.prophet_model))
            logger.debug("Saved Prophet model to %s", prophet_path)
        if self.xgb_model:
            xgb_path = self.model_dir / f"xgb_{self.sku}_{self.channel}.pkl"
            joblib.dump(self.xgb_model, xgb_path)
            logger.debug("Saved XGBoost model to %s", xgb_path)

    def load_models(self) -> None:
        """Load persisted models if available."""
        prophet_path = self.model_dir / f"prophet_{self.sku}_{self.channel}.json"
        xgb_path = self.model_dir / f"xgb_{self.sku}_{self.channel}.pkl"
        if prophet_path.exists():
            self.prophet_model = model_from_json(prophet_path.read_text())
            logger.info("Loaded Prophet model from %s", prophet_path)
        if xgb_path.exists():
            self.xgb_model = joblib.load(xgb_path)
            logger.info("Loaded XGBoost model from %s", xgb_path)


class DemandForecasterMulti:
    """Coordinator for training and forecasting across all SKU-channel combinations."""

    def __init__(self) -> None:
        self.registry: Dict[str, DemandForecaster] = {}

    def _registry_key(self, sku: str, channel: str) -> str:
        return f"{sku}__{channel}"

    def train_all_models(self, sales_data: pd.DataFrame) -> Dict[str, DemandForecaster]:
        """Train individual models for each SKU-channel combination."""
        required_cols = {"sku", "channel", "date", "sales", "price"}
        if not required_cols.issubset(sales_data.columns):
            missing = required_cols - set(sales_data.columns)
            raise ValueError(f"Missing required columns: {missing}")

        sales_data["date"] = pd.to_datetime(sales_data["date"])
        for (sku, channel), group in sales_data.groupby(["sku", "channel"]):
            logger.info("Training models for SKU=%s channel=%s", sku, channel)
            category = group["category"].iloc[0] if "category" in group.columns else None
            forecaster = DemandForecaster(sku, channel, group, product_category=category)
            forecaster.train_prophet_model()
            forecaster.train_xgboost_model()
            forecaster.save_models()
            self.registry[self._registry_key(sku, channel)] = forecaster
        return self.registry

    def forecast_all(self, horizon_days: int = 28) -> pd.DataFrame:
        """Forecast demand for all registered models and export aggregated results."""
        forecasts: List[pd.DataFrame] = []
        for key, forecaster in self.registry.items():
            forecast_df = forecaster.forecast_demand(horizon_days=horizon_days)
            forecast_df["sku"] = forecaster.sku
            forecast_df["channel"] = forecaster.channel
            forecast_df["category"] = forecaster.product_category
            forecasts.append(forecast_df)
        if not forecasts:
            logger.warning("No models registered for forecasting.")
            return pd.DataFrame()

        combined = pd.concat(forecasts, ignore_index=True)
        aggregated_channel = combined.groupby(["date", "channel"]).agg({"predicted_demand": "sum"}).reset_index()
        aggregated_category = combined.groupby(["date", "category", "channel"]).agg({"predicted_demand": "sum"}).reset_index()

        output_file = config.OUTPUT_DIR / "demand_forecasts.xlsx"
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(output_file, engine="xlsxwriter") as writer:
            combined.to_excel(writer, sheet_name="SKU_Channel", index=False)
            aggregated_channel.to_excel(writer, sheet_name="Channel_Aggregate", index=False)
            aggregated_category.to_excel(writer, sheet_name="Category_Channel", index=False)
        logger.info("Exported consolidated forecasts to %s", output_file)
        return combined


__all__ = [
    "DemandForecaster",
    "DemandForecasterMulti",
    "ForecastResult",
    "ForecastMetrics",
]
