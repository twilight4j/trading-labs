from __future__ import annotations

from typing import Protocol

import pandas as pd

from backtest.core.types import BacktestResult


class Strategy(Protocol):
    """Strategy plugin: custom run(), or prepare() plus the shared bar engine."""

    name: str

    def prepare(self, prices: pd.DataFrame) -> pd.DataFrame:
        """When using the shared engine, return prices plus golden_cross / death_cross."""

    def run(
        self,
        prices: pd.DataFrame,
        *,
        initial_cash: float = 10_000_000.0,
        fee_rate: float = 0.0015,
    ) -> BacktestResult:
        """Run this strategy; may use run_bar_by_bar or a custom loop."""
