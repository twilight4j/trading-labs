"""Backtests on curated market data."""

from backtest.analytics import (
    format_infinite_buy_fills,
    format_infinite_buy_report,
    infinite_buy_equity_view,
    infinite_buy_fills,
    plot_backtest,
    style_infinite_buy_equity,
    style_infinite_buy_fills,
    summarize,
    summarize_infinite_buy,
)
from backtest.api import load_run_panel, run_backtest, run_universe_backtest, save_run_panel
from backtest.core import BacktestResult, RunPanel, run_bar_by_bar
from backtest.data import list_universe, load_price_panel, load_price_series
from backtest.strategies import available_strategies, get_strategy, run_golden_cross, run_infinite_buy

__all__ = [
    "BacktestResult",
    "RunPanel",
    "available_strategies",
    "get_strategy",
    "list_universe",
    "load_price_panel",
    "load_price_series",
    "load_run_panel",
    "format_infinite_buy_fills",
    "format_infinite_buy_report",
    "infinite_buy_equity_view",
    "infinite_buy_fills",
    "plot_backtest",
    "run_backtest",
    "run_bar_by_bar",
    "run_golden_cross",
    "run_infinite_buy",
    "run_universe_backtest",
    "save_run_panel",
    "style_infinite_buy_equity",
    "style_infinite_buy_fills",
    "summarize",
    "summarize_infinite_buy",
]
