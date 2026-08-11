from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd


class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    def get_daily_prices(self, trade_date: date, market: str) -> pd.DataFrame:
        """Return source-native daily prices for one market."""

    @abstractmethod
    def get_security_master(self) -> pd.DataFrame:
        """Return source-native security master rows."""

    def get_adjusted_ohlcv(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        """Return source-native adjusted OHLCV for one ticker over [start, end]."""
        raise NotImplementedError(f"{type(self).__name__} does not support adjusted OHLCV")

    def get_delistings(self) -> pd.DataFrame:
        return pd.DataFrame()
