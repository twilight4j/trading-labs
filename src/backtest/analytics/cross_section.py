from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def attach_size_quintile(summaries: pd.DataFrame) -> pd.DataFrame:
    """Add universe size quintiles (Q1=smallest). Rows without market_cap stay NA."""
    frame = summaries.copy()
    cap = pd.to_numeric(frame.get("market_cap"), errors="coerce")
    ranked = cap.dropna()
    if ranked.nunique() >= 5:
        frame["size_quintile"] = pd.qcut(cap, 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
    elif ranked.nunique() >= 2:
        n = int(ranked.nunique())
        labels = [f"Q{i}" for i in range(1, n + 1)]
        frame["size_quintile"] = pd.qcut(cap, n, labels=labels, duplicates="drop")
    else:
        frame["size_quintile"] = pd.Series(pd.NA, index=frame.index, dtype="string")
    return frame


def stock_group_summary(summaries: pd.DataFrame) -> pd.DataFrame:
    """Median metrics for effective vs not. Error rows are dropped."""
    frame = _ok(summaries)
    if frame.empty:
        return pd.DataFrame(columns=[
            "effective", "n", "excess_median", "mdd_median", "market_cap_median",
            "trade_count_median", "realized_vol_median", "buy_hold_median",
        ])
    grouped = frame.groupby("effective", dropna=False)
    return grouped.agg(
        n=("security_id", "count"),
        excess_median=("excess_return", "median"),
        mdd_median=("max_drawdown", "median"),
        market_cap_median=("market_cap", "median"),
        trade_count_median=("trade_count", "median"),
        realized_vol_median=("realized_vol", "median"),
        buy_hold_median=("buy_hold_return", "median"),
    ).reset_index()


def stock_axis_summary(summaries: pd.DataFrame, *, by: str) -> pd.DataFrame:
    """Counts and median excess by an axis (market, size_quintile) x effective."""
    frame = _ok(summaries)
    if by not in frame.columns:
        raise KeyError(f"summaries missing column {by!r}")
    if frame.empty:
        return pd.DataFrame(columns=[by, "effective", "n", "excess_median"])
    return (
        frame.groupby([by, "effective"], dropna=False)
        .agg(n=("security_id", "count"), excess_median=("excess_return", "median"))
        .reset_index()
    )


def period_hit_rates(period_returns: pd.DataFrame, *, freq: str = "YE") -> pd.DataFrame:
    """Per-period hit rate (excess > 0), median excess, median universe buy&hold."""
    if freq not in {"YE", "ME"}:
        raise ValueError("freq must be 'YE' or 'ME'")
    columns = ["period", "freq", "n", "hit_rate", "excess_median", "universe_bh_median"]
    if period_returns.empty:
        return pd.DataFrame(columns=columns)
    frame = period_returns.loc[period_returns["freq"] == freq].copy()
    if frame.empty:
        return pd.DataFrame(columns=columns)
    frame["excess_return"] = pd.to_numeric(frame["excess_return"], errors="coerce")
    frame["buy_hold_return"] = pd.to_numeric(frame["buy_hold_return"], errors="coerce")
    grouped = frame.groupby("period", sort=True)
    return grouped.agg(
        n=("security_id", "count"),
        hit_rate=("excess_return", lambda s: float((s > 0).mean())),
        excess_median=("excess_return", "median"),
        universe_bh_median=("buy_hold_return", "median"),
    ).reset_index().assign(freq=freq)[columns]


def plot_period_hit_rate(
    stats: pd.DataFrame,
    *,
    title: str = "period hit rate vs universe buy&hold",
    output_path: Path | None = None,
    show: bool = False,
) -> Path | None:
    if stats.empty:
        raise ValueError("period stats are empty")
    frame = stats.copy()
    fig, ax = plt.subplots(figsize=(11, 4.5))
    x = range(len(frame))
    ax.bar(x, frame["hit_rate"], color="#7c3aed", alpha=0.85, label="hit rate (excess>0)")
    ax.set_ylabel("hit rate")
    ax.set_ylim(0, 1)
    ax.set_xticks(list(x))
    ax.set_xticklabels(frame["period"].astype(str), rotation=45, ha="right")
    ax2 = ax.twinx()
    ax2.plot(list(x), frame["universe_bh_median"], color="#6b7280", marker="o", linewidth=1.2, label="universe BH median")
    ax2.set_ylabel("universe BH median")
    ax.set_title(title)
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    return _finish_fig(fig, output_path, show)


def plot_excess_scatter(
    summaries: pd.DataFrame,
    *,
    x: str = "market_cap",
    output_path: Path | None = None,
    show: bool = False,
) -> Path | None:
    frame = _ok(summaries)
    if frame.empty:
        raise ValueError(
            "no successful summaries to plot "
            "(universe was empty or every name failed). "
            "If as_of is a holiday, list_universe now uses the prior session — re-run from the universe cell."
        )
    fig, ax = plt.subplots(figsize=(8, 5))
    effective = frame["effective"].astype(bool)
    ax.scatter(
        pd.to_numeric(frame.loc[~effective, x], errors="coerce"),
        pd.to_numeric(frame.loc[~effective, "excess_return"], errors="coerce"),
        color="#9ca3af",
        s=28,
        label="not effective",
        alpha=0.8,
    )
    ax.scatter(
        pd.to_numeric(frame.loc[effective, x], errors="coerce"),
        pd.to_numeric(frame.loc[effective, "excess_return"], errors="coerce"),
        color="#16a34a",
        s=28,
        label="effective",
        alpha=0.8,
    )
    ax.axhline(0.0, color="#6b7280", linewidth=0.8)
    ax.set_xlabel(x)
    ax.set_ylabel("excess_return")
    if x == "market_cap":
        ax.set_xscale("log")
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    return _finish_fig(fig, output_path, show)


def _ok(summaries: pd.DataFrame) -> pd.DataFrame:
    if summaries.empty:
        return summaries
    error = summaries["error"] if "error" in summaries.columns else ""
    mask = error.fillna("").astype(str).eq("")
    return summaries.loc[mask].copy()


def _finish_fig(fig, output_path: Path | None, show: bool) -> Path | None:
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
