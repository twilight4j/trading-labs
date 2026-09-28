from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from backtest.core.types import BacktestResult


def cycle_boundary_dates(equity: pd.DataFrame) -> pd.DatetimeIndex:
    """Dates where holdings go from positive to zero (cycle complete)."""
    if equity.empty or "shares" not in equity.columns:
        return pd.DatetimeIndex([])
    frame = equity.copy().reset_index(drop=True)
    shares = pd.to_numeric(frame["shares"], errors="coerce").fillna(0.0)
    prev = shares.shift(fill_value=0.0)
    ended = (prev > 0) & (shares <= 0)
    dates = pd.to_datetime(frame.loc[ended, "trade_date"])
    return pd.DatetimeIndex(dates)


def reverse_spans(equity: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Inclusive reverse-mode runs as [start, end) timestamps for axvspan."""
    if equity.empty or "mode" not in equity.columns:
        return []
    frame = equity.copy().reset_index(drop=True)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    mask = frame["mode"].astype(str).str.upper() == "REVERSE"
    if not bool(mask.any()):
        return []
    groups = (mask != mask.shift(fill_value=False)).cumsum()
    dates = frame["trade_date"]
    spans: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for _, chunk in mask.groupby(groups, sort=False):
        if not bool(chunk.iloc[0]):
            continue
        start_i = int(chunk.index[0])
        end_i = int(chunk.index[-1])
        start = pd.Timestamp(dates.iloc[start_i])
        if end_i + 1 < len(dates):
            end = pd.Timestamp(dates.iloc[end_i + 1])
        else:
            end = pd.Timestamp(dates.iloc[end_i]) + pd.Timedelta(1, unit="D")
        spans.append((start, end))
    return spans


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
    infinite = strategy == "infinite_buy"

    fig, (ax_price, ax_equity) = plt.subplots(
        2,
        1,
        figsize=(11, 7),
        sharex=True,
        gridspec_kw={"height_ratios": [1.2, 1]},
    )

    ax_price.plot(equity["trade_date"], close, color="#1f2937", linewidth=1.0, label="close")
    title = f"{security_id}  {strategy}"
    if not infinite and fast is not None and slow is not None:
        equity["sma_fast"] = close.rolling(window=fast, min_periods=fast).mean()
        equity["sma_slow"] = close.rolling(window=slow, min_periods=slow).mean()
        ax_price.plot(equity["trade_date"], equity["sma_fast"], color="#2563eb", linewidth=1.0, label=f"SMA {fast}")
        ax_price.plot(equity["trade_date"], equity["sma_slow"], color="#dc2626", linewidth=1.0, label=f"SMA {slow}")
        title = f"{security_id}  {strategy}  ({fast}/{slow})"

    if infinite:
        _overlay_infinite_buy(ax_price, ax_equity, equity, result.trades)
    else:
        _scatter_trades(ax_price, result.trades, buys=True)

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


def _scatter_trades(ax: plt.Axes, trades: pd.DataFrame, *, buys: bool) -> None:
    if trades.empty:
        return
    if buys:
        buy_rows = trades.loc[trades["side"] == "buy"]
        if not buy_rows.empty:
            ax.scatter(
                pd.to_datetime(buy_rows["trade_date"]),
                buy_rows["price"],
                marker="^",
                color="#16a34a",
                s=48,
                zorder=5,
                label="buy",
            )
    sell_rows = trades.loc[trades["side"] == "sell"]
    if not sell_rows.empty:
        ax.scatter(
            pd.to_datetime(sell_rows["trade_date"]),
            sell_rows["price"],
            marker="s",
            color="#dc2626",
            s=36,
            zorder=5,
            label="sell",
        )


def _overlay_infinite_buy(
    ax_price: plt.Axes,
    ax_equity: plt.Axes,
    equity: pd.DataFrame,
    trades: pd.DataFrame,
) -> None:
    dates = equity["trade_date"]
    if "avg_price" in equity.columns:
        shares = pd.to_numeric(equity["shares"], errors="coerce").fillna(0.0)
        avg = pd.to_numeric(equity["avg_price"], errors="coerce").where(shares > 0)
        ax_price.plot(
            dates,
            avg,
            color="#2563eb",
            linewidth=1.2,
            drawstyle="steps-post",
            label="avg",
            zorder=4,
        )
    first_close = float(pd.to_numeric(equity["close"], errors="coerce").iloc[0])
    if first_close > 0:
        ax_price.axhline(
            first_close,
            color="#c026d3",
            linestyle="--",
            linewidth=1.0,
            label="hodl",
            zorder=3,
        )

    reverse_label = "reverse"
    for start, end in reverse_spans(equity):
        ax_price.axvspan(start, end, color="#fecaca", alpha=0.35, zorder=0, label=reverse_label)
        ax_equity.axvspan(start, end, color="#fecaca", alpha=0.35, zorder=0, label=reverse_label)
        reverse_label = "_nolegend_"

    cycle_label = "cycle"
    for index, stamp in enumerate(cycle_boundary_dates(equity), start=1):
        ax_price.axvline(stamp, color="#2563eb", linestyle=":", linewidth=1.1, zorder=3, label=cycle_label)
        ax_equity.axvline(stamp, color="#2563eb", linestyle=":", linewidth=1.1, zorder=3, label=cycle_label)
        ax_price.text(
            stamp,
            1.02,
            str(index),
            transform=ax_price.get_xaxis_transform(),
            color="#2563eb",
            ha="center",
            va="bottom",
            fontsize=8,
            fontweight="bold",
        )
        cycle_label = "_nolegend_"

    _scatter_trades(ax_price, trades, buys=False)
