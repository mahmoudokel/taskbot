"""Data cleaning, feature engineering, and dataset preparation utilities."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from pandas import DataFrame, Series
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LinearRegression

from . import config

logger = logging.getLogger(__name__)


@dataclass
class ProcessedDataPaths:
    """Container for persisted data artifact paths."""

    costs: Path
    inventory: Path
    sales: Path
    competitor: Path
    master: Path


class DataProcessor:
    """Cleans, transforms, and prepares data for downstream pricing models."""

    def __init__(self) -> None:
        self.config = config
        self.data_dir = self.config.DATA_DIR
        self.output_dir = self.config.OUTPUT_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.paths = ProcessedDataPaths(
            costs=self.data_dir / "processed_costs.pkl",
            inventory=self.data_dir / "processed_inventory.pkl",
            sales=self.data_dir / "processed_sales.pkl",
            competitor=self.data_dir / "processed_competitor.pkl",
            master=self.data_dir / "master_dataset.pkl",
        )

        self.costs: DataFrame | None = None
        self.inventory: DataFrame | None = None
        self.sales: DataFrame | None = None
        self.competitor: DataFrame | None = None
        self.master: DataFrame | None = None

    # ------------------------------------------------------------------
    # Data Loading
    # ------------------------------------------------------------------
    def load_data(self, file_path: Path, sheet_name: str | int | None = None) -> DataFrame:
        """Read an Excel sheet and perform basic cleaning.

        Args:
            file_path: Path to an Excel file.
            sheet_name: Sheet to load (defaults to first sheet).

        Returns:
            Cleaned DataFrame with normalized dtypes and missing values handled.
        """

        logger.info("Loading data from %s (sheet=%s)", file_path, sheet_name)
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        df = df.rename(columns=lambda c: str(c).strip())

        # Handle missing values based on inferred column types
        for column in df.columns:
            if pd.api.types.is_numeric_dtype(df[column]):
                df[column] = pd.to_numeric(df[column], errors="coerce")
                df[column] = df[column].fillna(0)
            elif pd.api.types.is_datetime64_any_dtype(df[column]):
                df[column] = pd.to_datetime(df[column], errors="coerce")
            else:
                df[column] = df[column].fillna("").astype(str).str.strip()

        return df

    # ------------------------------------------------------------------
    # Feature Engineering
    # ------------------------------------------------------------------
    def create_derived_features(self, df: DataFrame) -> DataFrame:
        """Add domain-specific derived features to the provided dataframe."""

        logger.info("Creating derived features")
        today = pd.Timestamp(date.today())

        if "expiry_date" in df.columns:
            df["expiry_date"] = pd.to_datetime(df["expiry_date"], errors="coerce")
        if "production_date" in df.columns:
            df["production_date"] = pd.to_datetime(df["production_date"], errors="coerce")

        if "expiry_date" in df.columns:
            df["days_to_expiry"] = (df["expiry_date"] - today).dt.days
        else:
            df["days_to_expiry"] = np.nan

        fresh_threshold, frozen_threshold = self.config.AGING_THRESHOLDS["fresh"], self.config.AGING_THRESHOLDS["frozen"]

        def categorize_aging(row: Series) -> str:
            days = row.get("days_to_expiry")
            category = str(row.get("category", "")).lower()
            if pd.isna(days):
                return "Unknown"
            if "fresh" in category:
                if days < fresh_threshold[0]:
                    return "OK"
                if fresh_threshold[0] <= days <= fresh_threshold[1]:
                    return "Warning"
                return "Critical"
            if "frozen" in category:
                if days < frozen_threshold[0]:
                    return "OK"
                if frozen_threshold[0] <= days <= frozen_threshold[1]:
                    return "Warning"
                return "Critical"
            return "Unknown"

        df["aging_category"] = df.apply(categorize_aging, axis=1)

        if {"sales_velocity", "stock_on_hand"}.issubset(df.columns):
            df["inventory_turnover_rate"] = df.apply(
                lambda r: (r["sales_velocity"] / r["stock_on_hand"])
                if r.get("stock_on_hand", 0) > 0
                else np.nan,
                axis=1,
            )

        if {"price", "cost"}.issubset(df.columns):
            df["margin_percentage"] = np.where(
                df["price"] != 0,
                (df["price"] - df["cost"]) / df["price"] * 100,
                np.nan,
            )

        if {"our_price", "competitor_avg"}.issubset(df.columns):
            df["price_vs_competitor_gap"] = np.where(
                df["competitor_avg"] != 0,
                (df["our_price"] - df["competitor_avg"]) / df["competitor_avg"] * 100,
                np.nan,
            )

        if {"sales", "sku"}.issubset(df.columns):
            df["demand_velocity"] = (
                df.sort_values("date")
                .groupby("sku")["sales"]
                .transform(lambda s: s.rolling(window=30, min_periods=1).mean())
            )

        def seasonality_flag(d: datetime) -> float:
            if pd.isna(d):
                return 1.0
            d_date = d.date() if isinstance(d, pd.Timestamp) else d
            for _, start, end in self.config.RAMADAN_DATES:
                if start <= d_date <= end:
                    return 1.25
            if d_date.month in {6, 7, 8}:  # placeholder for Hajj seasonal uplift
                return 1.15
            return 1.0

        if "date" in df.columns:
            df["seasonality_index"] = pd.to_datetime(df["date"], errors="coerce").apply(seasonality_flag)
            df["day_of_week_factor"] = pd.to_datetime(df["date"], errors="coerce").dt.dayofweek.map(
                lambda dow: 1.3 if dow in {3, 4} else 1.0
            )

        return df

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------
    def aggregate_sales_data(self, sales_df: DataFrame) -> Dict[str, DataFrame]:
        """Aggregate sales history into multiple grains and compute volatility metrics."""

        logger.info("Aggregating sales data")
        sales_df = sales_df.copy()
        sales_df["date"] = pd.to_datetime(sales_df["date"], errors="coerce")
        sales_df = sales_df.sort_values(["sku", "date"]).dropna(subset=["date"])

        sales_df.set_index("date", inplace=True)
        weekly = sales_df.groupby("sku").resample("W").sum(numeric_only=True).reset_index()
        monthly = sales_df.groupby("sku").resample("M").sum(numeric_only=True).reset_index()

        for frame in (weekly, monthly):
            frame["rolling_7d_avg"] = frame.groupby("sku")["qty"].transform(lambda s: s.rolling(7, min_periods=1).mean())
            frame["rolling_30d_avg"] = frame.groupby("sku")["qty"].transform(lambda s: s.rolling(30, min_periods=1).mean())
            frame["rolling_90d_avg"] = frame.groupby("sku")["qty"].transform(lambda s: s.rolling(90, min_periods=1).mean())

            def _cv(series: Series) -> float:
                mean = series.mean()
                if mean == 0 or pd.isna(mean):
                    return np.nan
                return series.std(ddof=0) / mean

            frame["cv"] = frame.groupby("sku")["qty"].transform(_cv)
            frame["week"] = frame["date"].dt.isocalendar().week
            frame["month"] = frame["date"].dt.month
            frame["quarter"] = frame["date"].dt.quarter
            frame["year"] = frame["date"].dt.year

        sales_df.reset_index(inplace=True)
        return {"weekly": weekly, "monthly": monthly, "daily": sales_df}

    # ------------------------------------------------------------------
    # Merging
    # ------------------------------------------------------------------
    def merge_all_datasets(
        self,
        costs_df: DataFrame,
        inventory_df: DataFrame,
        sales_df: DataFrame,
        competitor_df: DataFrame,
    ) -> DataFrame:
        """Join costs, inventory, sales, and competitor datasets by SKU."""

        logger.info("Merging datasets into master frame")
        for name, frame in {
            "costs": costs_df,
            "inventory": inventory_df,
            "sales": sales_df,
            "competitor": competitor_df,
        }.items():
            if "sku" not in frame.columns:
                raise ValueError(f"Missing 'sku' column in {name} dataset")

        master = costs_df.copy()
        master = master.merge(inventory_df, on="sku", how="left", suffixes=("_cost", "_inventory"))
        master = master.merge(sales_df, on="sku", how="left")
        master = master.merge(competitor_df, on="sku", how="left", suffixes=("", "_competitor"))

        # Fill missing values with business defaults
        numeric_cols = master.select_dtypes(include=["number"]).columns
        master[numeric_cols] = master[numeric_cols].fillna(0)
        categorical_cols = master.select_dtypes(include=["object", "category"]).columns
        master[categorical_cols] = master[categorical_cols].fillna("Unknown")

        master = self.create_derived_features(master)
        self.master = master
        master.to_pickle(self.paths.master)
        logger.info("Master dataset saved to %s", self.paths.master)
        return master

    # ------------------------------------------------------------------
    # Elasticity
    # ------------------------------------------------------------------
    def calculate_price_elasticity(self, sales_df: DataFrame) -> DataFrame:
        """Estimate price elasticity per SKU using log-log regression."""

        logger.info("Calculating price elasticity")
        elasticity_records = []
        grouped = sales_df.groupby("sku")

        for sku, frame in grouped:
            frame = frame.copy()
            frame["price"] = pd.to_numeric(frame.get("price"), errors="coerce")
            frame["qty"] = pd.to_numeric(frame.get("qty"), errors="coerce")
            frame = frame.dropna(subset=["price", "qty"])
            frame = frame[(frame["price"] > 0) & (frame["qty"] > 0)]

            if len(frame) < 3:
                elasticity_records.append({"sku": sku, "elasticity": np.nan, "classification": "insufficient_data"})
                continue

            log_price = np.log(frame["price"])
            log_qty = np.log(frame["qty"])
            model = LinearRegression()
            model.fit(log_price.values.reshape(-1, 1), log_qty.values)
            elasticity = model.coef_[0]
            classification = "elastic" if elasticity < -1 else "inelastic"
            elasticity_records.append({"sku": sku, "elasticity": float(elasticity), "classification": classification})

        elasticity_df = pd.DataFrame(elasticity_records)
        return elasticity_df

    # ------------------------------------------------------------------
    # Training Data Prep
    # ------------------------------------------------------------------
    def prepare_training_data(self, df: DataFrame, target_variable: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, Pipeline]:
        """Split data, encode categoricals, scale numerics, and return train/test sets."""

        if target_variable not in df.columns:
            raise ValueError(f"Target variable '{target_variable}' not found in dataframe")

        logger.info("Preparing training data with target '%s'", target_variable)
        X = df.drop(columns=[target_variable])
        y = df[target_variable]

        categorical_cols = X.select_dtypes(include=["object", "category"]).columns.tolist()
        numeric_cols = X.select_dtypes(exclude=["object", "category"]).columns.tolist()

        categorical_transformer = Pipeline(steps=[
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ])

        numeric_transformer = Pipeline(steps=[
            ("scaler", StandardScaler()),
        ])

        preprocessor = ColumnTransformer(
            transformers=[
                ("categorical", categorical_transformer, categorical_cols),
                ("numeric", numeric_transformer, numeric_cols),
            ]
        )

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        model_pipeline = Pipeline(steps=[("preprocessor", preprocessor)])
        return X_train, X_test, y_train, y_test, model_pipeline

    # ------------------------------------------------------------------
    # Persistence Helpers
    # ------------------------------------------------------------------
    def save_processed_frames(self) -> None:
        """Persist processed datasets for reuse."""

        mapping = {
            self.paths.costs: self.costs,
            self.paths.inventory: self.inventory,
            self.paths.sales: self.sales,
            self.paths.competitor: self.competitor,
            self.paths.master: self.master,
        }
        for path, frame in mapping.items():
            if frame is not None:
                frame.to_pickle(path)
                logger.info("Saved dataset to %s", path)

    # ------------------------------------------------------------------
    # Convenience methods to load and process standard datasets
    # ------------------------------------------------------------------
    def load_standard_datasets(self) -> None:
        """Load configured datasets into memory and persist cleaned versions."""

        self.costs = self.load_data(self.config.COST_FILE)
        self.inventory = self.load_data(self.config.INVENTORY_FILE)
        self.sales = self.load_data(self.config.RAW_SALES_FILE)
        self.competitor = self.load_data(self.config.COMPETITOR_PRICE_FILE)

        self.costs.to_pickle(self.paths.costs)
        self.inventory.to_pickle(self.paths.inventory)
        self.sales.to_pickle(self.paths.sales)
        self.competitor.to_pickle(self.paths.competitor)
        logger.info("Standard datasets loaded and saved to pickle")

    def merge_standard_datasets(self) -> DataFrame:
        """Merge standard datasets and persist master frame."""

        if not all([self.costs is not None, self.inventory is not None, self.sales is not None, self.competitor is not None]):
            raise ValueError("Standard datasets not loaded. Call load_standard_datasets first.")

        return self.merge_all_datasets(self.costs, self.inventory, self.sales, self.competitor)


__all__ = ["DataProcessor", "ProcessedDataPaths"]
