from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class BacktestResult:
    equity: pd.DataFrame
    trades: pd.DataFrame
    initial_cash: float
    fee_rate: float
    sell_tax_rate: float = 0.0


@dataclass(frozen=True)
class RunPanel:
    summaries: pd.DataFrame
    period_returns: pd.DataFrame
