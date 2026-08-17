"""Backtests on curated market data."""

from backtest.analytics import plot_backtest, summarize
from backtest.api import load_run_panel, run_backtest, run_universe_backtest, save_run_panel
from backtest.core import BacktestResult, RunPanel, run_bar_by_bar
from backtest.data import list_universe, load_price_panel, load_price_series
from backtest.strategies import available_strategies, get_strategy, run_golden_cross

__all__ = [
    "BacktestResult",
    "RunPanel",
    "available_strategies",
    "get_strategy",
    "list_universe",
    "load_price_panel",
    "load_price_series",
    "load_run_panel",
    "plot_backtest",
    "run_backtest",
    "run_bar_by_bar",
    "run_golden_cross",
    "run_universe_backtest",
    "save_run_panel",
    "summarize",
]
