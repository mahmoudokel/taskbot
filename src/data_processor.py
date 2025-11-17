"""Data ingestion and transformation routines."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import pandas as pd

from . import config
from .data_validation import DataValidator

logger = logging.getLogger(__name__)


class DataProcessor:
    """Loads and cleans raw data sources for downstream models."""

    def __init__(self, validator: DataValidator | None = None) -> None:
        self.validator = validator or DataValidator()

    def load_sources(self, sources: Iterable[Path]) -> pd.DataFrame:
        """Read multiple CSV sources and concatenate them into a single frame."""
        frames: list[pd.DataFrame] = []
        for source in sources:
            logger.info("Loading data from %s", source)
            frames.append(pd.read_csv(source))
        combined = pd.concat(frames, ignore_index=True)
        validation = self.validator.validate(combined)
        if not validation.is_valid:
            logger.error("Data validation failed: %s", validation.errors)
            raise ValueError("; ".join(validation.errors))
        return combined

    def normalize_channels(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Normalize channel naming to match configured values."""
        mapping = {channel.lower(): channel for channel in config.CHANNELS}
        frame["channel"] = frame["channel"].str.lower().map(mapping).fillna(frame["channel"])
        return frame

    def enrich_with_holidays(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Annotate transactions with holiday and Ramadan flags."""
        frame["date"] = pd.to_datetime(frame["date"])
        frame["is_holiday"] = frame["date"].dt.strftime("%m-%d").isin(
            {f"{month:02d}-{day:02d}" for month, day in config.SAUDI_HOLIDAYS.values()}
        )
        frame["is_ramadan"] = frame["date"].apply(self._is_ramadan)
        return frame

    def _is_ramadan(self, current_date: pd.Timestamp) -> bool:
        for _, start, end in config.RAMADAN_DATES:
            if start <= current_date.date() <= end:
                return True
        return False
