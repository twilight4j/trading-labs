from __future__ import annotations

import pandas as pd

from backtest.core.types import BacktestResult


def run_bar_by_bar(
    prices: pd.DataFrame,
    *,
    initial_cash: float = 10_000_000.0,
    fee_rate: float = 0.0015,
) -> BacktestResult:
    """Simulate long-only all-in/all-out fills on next-bar open after signal flags.

    Expects columns: trade_date, open, close, golden_cross, death_cross.
    """
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if fee_rate < 0:
        raise ValueError("fee_rate must be >= 0")

    required = {"trade_date", "open", "close", "golden_cross", "death_cross"}
    missing = required - set(prices.columns)
    if missing:
        raise KeyError(f"missing columns: {sorted(missing)}")

    cash = float(initial_cash)
    shares = 0.0
    pending: str | None = None
    equity_rows: list[dict] = []
    trade_rows: list[dict] = []

    for _, row in prices.iterrows():
        open_price = float(row["open"])
        close_price = float(row["close"])
        trade_date = row["trade_date"]

        if pending == "buy" and shares == 0 and open_price > 0:
            cost_per_share = open_price * (1.0 + fee_rate)
            bought = cash / cost_per_share
            if bought > 0:
                cash -= bought * cost_per_share
                shares = bought
                trade_rows.append({
                    "trade_date": trade_date,
                    "side": "buy",
                    "price": open_price,
                    "shares": shares,
                    "fee": bought * open_price * fee_rate,
                    "cash_after": cash,
                })
        elif pending == "sell" and shares > 0 and open_price > 0:
            proceeds = shares * open_price * (1.0 - fee_rate)
            fee = shares * open_price * fee_rate
            trade_rows.append({
                "trade_date": trade_date,
                "side": "sell",
                "price": open_price,
                "shares": shares,
                "fee": fee,
                "cash_after": cash + proceeds,
            })
            cash += proceeds
            shares = 0.0
        pending = None

        equity = cash + shares * close_price
        equity_rows.append({
            "trade_date": trade_date,
            "cash": cash,
            "shares": shares,
            "close": close_price,
            "equity": equity,
            "position": 1 if shares > 0 else 0,
            "golden_cross": bool(row["golden_cross"]),
            "death_cross": bool(row["death_cross"]),
        })

        if bool(row["golden_cross"]) and shares == 0:
            pending = "buy"
        elif bool(row["death_cross"]) and shares > 0:
            pending = "sell"

    equity = pd.DataFrame(equity_rows)
    trades = pd.DataFrame(trade_rows)
    return BacktestResult(equity=equity, trades=trades, initial_cash=initial_cash, fee_rate=fee_rate)
