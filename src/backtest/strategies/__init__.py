from __future__ import annotations

from backtest.strategies.base import Strategy
from backtest.strategies.golden_cross import GoldenCrossStrategy, add_sma_cross_signals, run_golden_cross
from backtest.strategies.infinite_buy import InfiniteBuyStrategy, run_infinite_buy

STRATEGIES: dict[str, type] = {
    "golden_cross": GoldenCrossStrategy,
    "infinite_buy": InfiniteBuyStrategy,
}


def get_strategy(name: str, **params: object) -> Strategy:
    try:
        strategy_cls = STRATEGIES[name]
    except KeyError as exc:
        known = ", ".join(sorted(STRATEGIES))
        raise KeyError(f"unknown strategy {name!r}; known: {known}") from exc
    return strategy_cls(**params)


def available_strategies() -> list[str]:
    return sorted(STRATEGIES)


__all__ = [
    "STRATEGIES",
    "Strategy",
    "GoldenCrossStrategy",
    "InfiniteBuyStrategy",
    "add_sma_cross_signals",
    "available_strategies",
    "get_strategy",
    "run_golden_cross",
    "run_infinite_buy",
]
