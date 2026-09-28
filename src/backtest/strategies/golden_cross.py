from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backtest.core.engine import run_bar_by_bar
from backtest.core.types import BacktestResult


def add_sma_cross_signals(prices: pd.DataFrame, *, fast: int = 50, slow: int = 200) -> pd.DataFrame:
    """Attach SMA columns and golden/death cross flags on close.

    Cross is confirmed on day t using closes through t. Execution should use t+1.
    """
    if fast < 1 or slow < 1:
        raise ValueError("fast and slow must be >= 1")
    if fast >= slow:
        raise ValueError("fast must be < slow")
    if "close" not in prices.columns:
        raise KeyError("prices must include a close column")

    frame = prices.copy()
    close = pd.to_numeric(frame["close"], errors="coerce")
    frame["sma_fast"] = close.rolling(window=fast, min_periods=fast).mean()
    frame["sma_slow"] = close.rolling(window=slow, min_periods=slow).mean()

    prev_fast = frame["sma_fast"].shift(1)
    prev_slow = frame["sma_slow"].shift(1)
    ready = frame["sma_fast"].notna() & frame["sma_slow"].notna() & prev_fast.notna() & prev_slow.notna()

    frame["golden_cross"] = ready & (prev_fast <= prev_slow) & (frame["sma_fast"] > frame["sma_slow"])
    frame["death_cross"] = ready & (prev_fast >= prev_slow) & (frame["sma_fast"] < frame["sma_slow"])
    return frame


@dataclass(frozen=True)
class GoldenCrossStrategy:
    name: str = "golden_cross"
    fast: int = 50
    slow: int = 200

    def prepare(self, prices: pd.DataFrame) -> pd.DataFrame:
        return add_sma_cross_signals(prices, fast=self.fast, slow=self.slow)

    def run(
        self,
        prices: pd.DataFrame,
        *,
        initial_cash: float = 10_000_000.0,
        fee_rate: float = 0.0015,
        sell_tax_rate: float = 0.0,
    ) -> BacktestResult:
        return run_bar_by_bar(
            self.prepare(prices),
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            sell_tax_rate=sell_tax_rate,
        )


def run_golden_cross(
    prices: pd.DataFrame,
    *,
    fast: int = 50,
    slow: int = 200,
    initial_cash: float = 10_000_000.0,
    fee_rate: float = 0.0015,
    sell_tax_rate: float = 0.0,
) -> BacktestResult:
    return GoldenCrossStrategy(fast=fast, slow=slow).run(
        prices,
        initial_cash=initial_cash,
        fee_rate=fee_rate,
        sell_tax_rate=sell_tax_rate,
    )
