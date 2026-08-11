"""Backtests on curated market data."""

from backtest.core import BacktestResult, run_bar_by_bar
from backtest.analytics import summarize
from backtest.strategies import run_golden_cross

__all__ = ["BacktestResult", "run_bar_by_bar", "run_golden_cross", "summarize"]
