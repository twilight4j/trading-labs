from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.core.types import BacktestResult

_TRADING_DAYS_PER_YEAR = 252.0


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    return float(drawdown.min())


def cagr(total_return: float, bars: int, *, trading_days_per_year: float = _TRADING_DAYS_PER_YEAR) -> float:
    if bars <= 0 or trading_days_per_year <= 0:
        return 0.0
    years = bars / trading_days_per_year
    if years <= 0:
        return 0.0
    return float((1.0 + total_return) ** (1.0 / years) - 1.0)


def is_effective(
    excess_return: float,
    max_drawdown_value: float,
    *,
    mdd_limit: float = -0.30,
) -> bool:
    return excess_return > 0.0 and max_drawdown_value >= mdd_limit


def realized_vol(close: pd.Series) -> float:
    prices = pd.to_numeric(close, errors="coerce").replace(0, np.nan).dropna()
    if len(prices) < 2:
        return 0.0
    log_ret = np.log(prices).diff().dropna()
    if log_ret.empty:
        return 0.0
    return float(log_ret.std(ddof=1)) if len(log_ret) > 1 else 0.0


def period_returns(equity: pd.DataFrame, *, freq: str) -> pd.DataFrame:
    """Per-period strategy / buy-hold / excess returns from an equity curve.

    freq: ``YE`` (calendar year) or ``ME`` (calendar month).
    """
    if freq not in {"YE", "ME"}:
        raise ValueError("freq must be 'YE' or 'ME'")
    columns = ["period", "freq", "strategy_return", "buy_hold_return", "excess_return"]
    if equity.empty or "equity" not in equity.columns or "close" not in equity.columns:
        return pd.DataFrame(columns=columns)

    frame = equity.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame.sort_values("trade_date")
    code = "Y" if freq == "YE" else "M"
    grouped = frame.groupby(frame["trade_date"].dt.to_period(code), sort=True)

    rows: list[dict[str, object]] = []
    for period, chunk in grouped:
        first_equity = float(chunk["equity"].iloc[0])
        last_equity = float(chunk["equity"].iloc[-1])
        first_close = float(chunk["close"].iloc[0])
        last_close = float(chunk["close"].iloc[-1])
        strategy_return = last_equity / first_equity - 1.0 if first_equity > 0 else 0.0
        buy_hold_return = last_close / first_close - 1.0 if first_close > 0 else 0.0
        label = f"{period.year:04d}" if freq == "YE" else f"{period.year:04d}-{period.month:02d}"
        rows.append({
            "period": label,
            "freq": freq,
            "strategy_return": float(strategy_return),
            "buy_hold_return": float(buy_hold_return),
            "excess_return": float(strategy_return - buy_hold_return),
        })
    return pd.DataFrame(rows, columns=columns)


def summarize(result: BacktestResult) -> dict[str, float | int]:
    equity = result.equity
    if equity.empty:
        return {
            "initial_cash": result.initial_cash,
            "final_equity": result.initial_cash,
            "total_return": 0.0,
            "buy_hold_return": 0.0,
            "max_drawdown": 0.0,
            "trade_count": 0,
            "bars": 0,
        }

    final_equity = float(equity["equity"].iloc[-1])
    total_return = final_equity / result.initial_cash - 1.0

    first_close = float(equity["close"].iloc[0])
    last_close = float(equity["close"].iloc[-1])
    buy_hold_final = result.initial_cash * (last_close / first_close) if first_close > 0 else result.initial_cash
    buy_hold_return = buy_hold_final / result.initial_cash - 1.0

    return {
        "initial_cash": float(result.initial_cash),
        "final_equity": final_equity,
        "total_return": float(total_return),
        "buy_hold_return": float(buy_hold_return),
        "max_drawdown": max_drawdown(equity["equity"]),
        "trade_count": int(len(result.trades)),
        "bars": int(len(equity)),
    }


def summarize_run(result: BacktestResult) -> dict[str, float | int | bool]:
    """summarize() plus excess, CAGR, buy-hold MDD, and realized vol."""
    base = summarize(result)
    excess = float(base["total_return"]) - float(base["buy_hold_return"])
    close = result.equity["close"] if not result.equity.empty else pd.Series(dtype=float)
    if result.equity.empty:
        buy_hold_mdd = 0.0
    else:
        first_close = float(result.equity["close"].iloc[0])
        if first_close > 0:
            buy_hold_equity = result.initial_cash * (pd.to_numeric(close, errors="coerce") / first_close)
            buy_hold_mdd = max_drawdown(buy_hold_equity)
        else:
            buy_hold_mdd = 0.0
    return {
        **base,
        "excess_return": excess,
        "cagr": cagr(float(base["total_return"]), int(base["bars"])),
        "buy_hold_mdd": buy_hold_mdd,
        "realized_vol": realized_vol(close),
    }


def _empty_infinite_buy_summary(initial_cash: float) -> dict[str, float | int | str | None]:
    return {
        "status": "종료 · 0사이클 완료",
        "completed_cycles": 0,
        "marked_return": 0.0,
        "invested_return": 0.0,
        "pnl": 0.0,
        "initial_cash": float(initial_cash),
        "final_equity": float(initial_cash),
        "realized_cycle_profit": 0.0,
        "final_cycle_principal": float(initial_cash),
        "max_invested": 0.0,
        "utilization": 0.0,
        "total_fees": 0.0,
        "total_tax": 0.0,
        "start_date": None,
        "end_date": None,
        "calendar_days": 0,
        "trading_days": 0,
        "max_drawdown": 0.0,
        "avg_recovery_days": 0,
        "underwater_days": 0,
        "buy_count": 0,
        "sell_count": 0,
        "mdd_start": None,
        "mdd_end": None,
        "longest_underwater_start": None,
        "longest_underwater_end": None,
        "buy_hold_price": 0.0,
        "buy_hold_final": float(initial_cash),
        "buy_hold_pnl": 0.0,
        "buy_hold_return": 0.0,
        "alpha": 0.0,
    }


def _as_date(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        return None
    return stamp.strftime("%Y-%m-%d")


def _mdd_period(equity: pd.Series, dates: pd.Series) -> tuple[float, str | None, str | None]:
    if equity.empty:
        return 0.0, None, None
    values = pd.to_numeric(equity, errors="coerce")
    peak = values.cummax()
    drawdown = values / peak - 1.0
    trough_i = int(drawdown.to_numpy().argmin())
    mdd = float(drawdown.iloc[trough_i]) if pd.notna(drawdown.iloc[trough_i]) else 0.0
    peak_value = float(peak.iloc[trough_i])
    prefix = values.iloc[: trough_i + 1]
    matches = (prefix - peak_value).abs() < 1e-9
    peak_i = int(matches.to_numpy().argmax()) if matches.any() else 0
    return mdd, _as_date(dates.iloc[peak_i]), _as_date(dates.iloc[trough_i])


def _longest_true_run(mask: pd.Series, dates: pd.Series) -> tuple[int, str | None, str | None]:
    if mask.empty or not bool(mask.any()):
        return 0, None, None
    groups = (mask != mask.shift(fill_value=False)).cumsum()
    best_len = 0
    best_start: str | None = None
    best_end: str | None = None
    for _, chunk in mask.groupby(groups, sort=False):
        if not bool(chunk.iloc[0]):
            continue
        length = int(len(chunk))
        if length > best_len:
            best_len = length
            first_i = int(chunk.index[0])
            last_i = int(chunk.index[-1])
            best_start = _as_date(dates.iloc[first_i])
            best_end = _as_date(dates.iloc[last_i])
    return best_len, best_start, best_end


def summarize_infinite_buy(result: BacktestResult) -> dict[str, float | int | str | None]:
    """Cycle, invested-capital, underwater, and buy-hold alpha metrics."""
    equity = result.equity
    if equity.empty:
        return _empty_infinite_buy_summary(result.initial_cash)

    frame = equity.copy().reset_index(drop=True)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    shares = pd.to_numeric(frame["shares"], errors="coerce").fillna(0.0)
    close = pd.to_numeric(frame["close"], errors="coerce")
    avg = pd.to_numeric(frame["avg_price"], errors="coerce") if "avg_price" in frame.columns else pd.Series(0.0, index=frame.index)
    equity_value = pd.to_numeric(frame["equity"], errors="coerce")
    if "principal" in frame.columns:
        principal = pd.to_numeric(frame["principal"], errors="coerce")
    else:
        principal = pd.Series(result.initial_cash, index=frame.index)

    final_equity = float(equity_value.iloc[-1])
    pnl = final_equity - result.initial_cash
    marked_return = pnl / result.initial_cash if result.initial_cash else 0.0
    invested = shares * avg.fillna(0.0)
    max_invested = float(invested.max()) if not invested.empty else 0.0
    invested_return = pnl / max_invested if max_invested > 0 else 0.0
    utilization = max_invested / result.initial_cash if result.initial_cash else 0.0

    prev_shares = shares.shift(fill_value=0.0)
    completed_cycles = int(((prev_shares > 0) & (shares <= 0)).sum())
    last_shares = float(shares.iloc[-1])
    if last_shares > 0:
        status = f"진행 중 (기간 끝) · {completed_cycles}사이클 완료"
    else:
        status = f"종료 · {completed_cycles}사이클 완료"

    final_cycle_principal = float(principal.iloc[-1]) if pd.notna(principal.iloc[-1]) else float(result.initial_cash)
    realized_cycle_profit = final_cycle_principal - result.initial_cash

    trades = result.trades
    if trades.empty or "fee" not in trades.columns:
        total_fees = 0.0
        total_tax = 0.0
        buy_count = 0
        sell_count = 0
    else:
        total_fees = float(pd.to_numeric(trades["fee"], errors="coerce").fillna(0.0).sum())
        if "tax" in trades.columns:
            total_tax = float(pd.to_numeric(trades["tax"], errors="coerce").fillna(0.0).sum())
        else:
            total_tax = 0.0
        side = trades["side"].astype(str).str.lower() if "side" in trades.columns else pd.Series(dtype=str)
        buy_count = int((side == "buy").sum())
        sell_count = int((side == "sell").sum())

    start_date = _as_date(frame["trade_date"].iloc[0])
    end_date = _as_date(frame["trade_date"].iloc[-1])
    calendar_days = int((frame["trade_date"].iloc[-1] - frame["trade_date"].iloc[0]).days)
    trading_days = int(len(frame))

    mdd, mdd_start, mdd_end = _mdd_period(equity_value, frame["trade_date"])
    holding = shares > 0
    underwater = holding & close.notna() & avg.notna() & (avg > 0) & (close < avg)
    underwater_days = int(underwater.sum())
    avg_recovery_days, uw_start, uw_end = _longest_true_run(underwater, frame["trade_date"])

    first_close = float(close.iloc[0]) if pd.notna(close.iloc[0]) else 0.0
    last_close = float(close.iloc[-1]) if pd.notna(close.iloc[-1]) else 0.0
    buy_hold_final = result.initial_cash * (last_close / first_close) if first_close > 0 else result.initial_cash
    buy_hold_pnl = buy_hold_final - result.initial_cash
    buy_hold_return = buy_hold_pnl / result.initial_cash if result.initial_cash else 0.0

    return {
        "status": status,
        "completed_cycles": completed_cycles,
        "marked_return": float(marked_return),
        "invested_return": float(invested_return),
        "pnl": float(pnl),
        "initial_cash": float(result.initial_cash),
        "final_equity": final_equity,
        "realized_cycle_profit": float(realized_cycle_profit),
        "final_cycle_principal": final_cycle_principal,
        "max_invested": max_invested,
        "utilization": float(utilization),
        "total_fees": total_fees,
        "total_tax": total_tax,
        "start_date": start_date,
        "end_date": end_date,
        "calendar_days": calendar_days,
        "trading_days": trading_days,
        "max_drawdown": mdd,
        "avg_recovery_days": avg_recovery_days,
        "underwater_days": underwater_days,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "mdd_start": mdd_start,
        "mdd_end": mdd_end,
        "longest_underwater_start": uw_start,
        "longest_underwater_end": uw_end,
        "buy_hold_price": first_close,
        "buy_hold_final": float(buy_hold_final),
        "buy_hold_pnl": float(buy_hold_pnl),
        "buy_hold_return": float(buy_hold_return),
        "alpha": float(pnl - buy_hold_pnl),
    }


def _signed_pct(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value * 100:.2f}%"


def _signed_money(value: float) -> str:
    if value > 0:
        return f"+{value:,.0f}"
    return f"{value:,.0f}"


def _date_range(start: object, end: object) -> str:
    if not start or not end:
        return "—"
    return f"{start} ~ {end}"


def format_infinite_buy_report(summary: dict[str, float | int | str | None]) -> str:
    """Grouped text report for notebook and CLI."""
    utilization_pct = float(summary["utilization"]) * 100.0
    lines = [
        f"상태: {summary['status']}",
        f"평가 수익률 {_signed_pct(float(summary['marked_return']))}   투입액 대비 {_signed_pct(float(summary['invested_return']))}",
        f"손익 {_signed_money(float(summary['pnl']))}",
        f"{float(summary['initial_cash']):,.0f} → {float(summary['final_equity']):,.0f}",
        f"재투자 {_signed_money(float(summary['realized_cycle_profit']))}   최종 사이클 원금 {float(summary['final_cycle_principal']):,.0f}",
        f"최대 투입액 {float(summary['max_invested']):,.0f} ({utilization_pct:.0f}%)",
        f"수수료 {_signed_money(-abs(float(summary['total_fees'])))}   세금 {_signed_money(-abs(float(summary.get('total_tax', 0.0))))}",
        "",
        f"사이클 {int(summary['completed_cycles'])}   {_date_range(summary['start_date'], summary['end_date'])}",
        f"경과 {int(summary['calendar_days'])}일 / 거래일 {int(summary['trading_days'])}일",
        (
            f"MDD {_signed_pct(float(summary['max_drawdown']))}   "
            f"평단 회복 {int(summary['avg_recovery_days'])}거래일   "
            f"물밀 합계 {int(summary['underwater_days'])}거래일"
        ),
        f"매수 {int(summary['buy_count'])} / 매도 {int(summary['sell_count'])}",
        f"MDD 구간: {_date_range(summary['mdd_start'], summary['mdd_end'])}",
        f"가장 긴 물밀: {_date_range(summary['longest_underwater_start'], summary['longest_underwater_end'])}",
        "",
        (
            f"단순보유 {float(summary['buy_hold_price']):,.0f} → {float(summary['buy_hold_final']):,.0f}  "
            f"({_signed_pct(float(summary['buy_hold_return']))})"
        ),
        f"알파 {_signed_money(float(summary['alpha']))}",
    ]
    return "\n".join(lines)
