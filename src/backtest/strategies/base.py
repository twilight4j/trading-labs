from __future__ import annotations

from typing import Protocol

import pandas as pd

from backtest.core.types import BacktestResult


class Strategy(Protocol):
    """Prepare price bars with execution signal columns for the shared engine."""

    name: str

    def prepare(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Return prices plus signal columns (at least golden_cross / death_cross)."""

    def run(
        self,
        prices: pd.DataFrame,
        *,
        initial_cash: float = 10_000_000.0,
        fee_rate: float = 0.0015,
    ) -> BacktestResult:
        """Run this strategy through the shared bar engine."""
