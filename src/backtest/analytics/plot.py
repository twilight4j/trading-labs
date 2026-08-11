from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from backtest.core.types import BacktestResult


def plot_backtest(
    result: BacktestResult,
    *,
    security_id: str,
    strategy: str = "golden_cross",
    fast: int | None = 50,
    slow: int | None = 200,
    output_path: Path | None = None,
    show: bool = False,
) -> Path | None:
    """Plot price (optional SMA) with trade markers and equity vs buy&hold."""
    equity = result.equity.copy()
    if equity.empty:
        raise ValueError("equity is empty")

    equity["trade_date"] = pd.to_datetime(equity["trade_date"])
    close = pd.to_numeric(equity["close"], errors="coerce")
    equity["buy_hold"] = result.initial_cash * (close / close.iloc[0])

    fig, (ax_price, ax_equity) = plt.subplots(
        2,
        1,
        figsize=(11, 7),
        sharex=True,
        gridspec_kw={"height_ratios": [1.2, 1]},
    )

    ax_price.plot(equity["trade_date"], close, color="#1f2937", linewidth=1.0, label="close")
    title = f"{security_id}  {strategy}"
    if fast is not None and slow is not None:
        equity["sma_fast"] = close.rolling(window=fast, min_periods=fast).mean()
        equity["sma_slow"] = close.rolling(window=slow, min_periods=slow).mean()
        ax_price.plot(equity["trade_date"], equity["sma_fast"], color="#2563eb", linewidth=1.0, label=f"SMA {fast}")
        ax_price.plot(equity["trade_date"], equity["sma_slow"], color="#dc2626", linewidth=1.0, label=f"SMA {slow}")
        title = f"{security_id}  {strategy}  ({fast}/{slow})"

    trades = result.trades
    if not trades.empty:
        buys = trades.loc[trades["side"] == "buy"]
        sells = trades.loc[trades["side"] == "sell"]
        if not buys.empty:
            ax_price.scatter(
                pd.to_datetime(buys["trade_date"]),
                buys["price"],
                marker="^",
                color="#16a34a",
                s=48,
                zorder=5,
                label="buy",
            )
        if not sells.empty:
            ax_price.scatter(
                pd.to_datetime(sells["trade_date"]),
                sells["price"],
                marker="v",
                color="#dc2626",
                s=48,
                zorder=5,
                label="sell",
            )

    ax_price.set_ylabel("price")
    ax_price.set_title(title)
    ax_price.legend(loc="upper left", fontsize=8)
    ax_price.grid(True, alpha=0.25)

    ax_equity.plot(equity["trade_date"], equity["equity"], color="#7c3aed", linewidth=1.2, label="strategy")
    ax_equity.plot(equity["trade_date"], equity["buy_hold"], color="#9ca3af", linewidth=1.0, label="buy&hold")
    ax_equity.set_ylabel("equity")
    ax_equity.set_xlabel("trade_date")
    ax_equity.legend(loc="upper left", fontsize=8)
    ax_equity.grid(True, alpha=0.25)

    fig.autofmt_xdate()
    fig.tight_layout()

    saved: Path | None = None
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=140)
        saved = output_path

    if show:
        plt.show()
    else:
        plt.close(fig)

    return saved
