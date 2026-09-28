from __future__ import annotations

import pandas as pd

from backtest.core.types import BacktestResult

_REASON_LABELS = {
    "first_buy": "처음매수",
    "crash_tier": "보조계단",
    "half_star": "별지점 절반",
    "half_avg": "평단 절반",
    "second_half": "후반전 매수",
    "reverse_buy": "리버스 매수",
    "reverse_moc": "리버스 MOC",
    "reverse_loc": "리버스 LOC매도",
    "quarter_sell": "쿼터매도",
    "target_limit": "지정가매도",
}

_FILL_COLUMNS = [
    "일자",
    "구분",
    "종류",
    "수량",
    "누적수량",
    "체결가",
    "금액",
    "수수료",
    "세금",
    "투입(누적)",
    "평가손익",
    "cycle_end",
]


def infinite_buy_fills(result: BacktestResult) -> pd.DataFrame:
    """Per-fill ledger: invested cost, marked PnL, cycle-end flags."""
    empty = pd.DataFrame(columns=_FILL_COLUMNS)
    trades = result.trades
    if trades.empty:
        return empty

    close_by_date: dict[object, float] = {}
    if not result.equity.empty and "close" in result.equity.columns:
        frame = result.equity.copy()
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        close_by_date = {
            pd.Timestamp(stamp).normalize(): float(close)
            for stamp, close in zip(
                frame["trade_date"],
                pd.to_numeric(frame["close"], errors="coerce"),
                strict=False,
            )
            if pd.notna(close)
        }

    principal = float(result.initial_cash)
    shares = 0
    avg = 0.0
    rows: list[dict[str, object]] = []

    for _, trade in trades.iterrows():
        side = str(trade.get("side", "")).lower()
        qty = int(float(trade["shares"]))
        price = float(trade["price"])
        fee = float(trade["fee"]) if "fee" in trade.index and pd.notna(trade["fee"]) else 0.0
        tax = float(trade["tax"]) if "tax" in trade.index and pd.notna(trade["tax"]) else 0.0
        cash_after = float(trade["cash_after"]) if "cash_after" in trade.index else 0.0
        stamp = pd.Timestamp(trade["trade_date"])
        reason = str(trade["reason"]) if "reason" in trade.index else ""

        if side == "buy":
            new_cost = shares * avg + qty * price
            shares += qty
            avg = new_cost / shares if shares else 0.0
        else:
            shares = max(0, shares - qty)
            if shares <= 0:
                shares = 0
                avg = 0.0

        close = close_by_date.get(stamp.normalize(), price)
        invested = shares * avg
        marked_pnl = cash_after + shares * close - principal
        cycle_end = side == "sell" and shares <= 0
        rows.append({
            "일자": stamp.strftime("%Y-%m-%d"),
            "구분": "매수" if side == "buy" else "매도",
            "종류": _REASON_LABELS.get(reason, reason),
            "수량": qty,
            "누적수량": shares,
            "체결가": price,
            "금액": qty * price,
            "수수료": fee,
            "세금": tax,
            "투입(누적)": invested,
            "평가손익": marked_pnl,
            "cycle_end": cycle_end,
        })
        if cycle_end:
            principal = cash_after

    return pd.DataFrame(rows, columns=_FILL_COLUMNS)


def format_infinite_buy_fills(fills: pd.DataFrame) -> str:
    """Text table with a separator after each completed cycle."""
    count = int(len(fills))
    header = (
        f"체결 이력 ({count}건 · 투입 = 보유 매입원가(수수료 제외) · "
        "평가손익 = 평가금-원금, 매수는 수수료만 · 매도는 수수료+세금 · 가로선 = 사이클 완료)"
    )
    if fills.empty:
        return header + "\n(없음)"

    lines = [header, ""]
    col_names = ["일자", "구분", "종류", "수량", "누적수량", "체결가", "금액", "수수료", "세금", "투입(누적)", "평가손익"]
    lines.append("  ".join(col_names))
    for _, row in fills.iterrows():
        tax = float(row["세금"]) if "세금" in fills.columns else 0.0
        parts = [
            str(row["일자"]),
            str(row["구분"]),
            str(row["종류"]),
            f"{int(row['수량'])}",
            f"{int(row['누적수량'])}",
            f"{float(row['체결가']):,.0f}",
            f"{float(row['금액']):,.0f}",
            f"{float(row['수수료']):,.2f}",
            f"{tax:,.2f}",
            f"{float(row['투입(누적)']):,.0f}",
            _signed_won(float(row["평가손익"])),
        ]
        lines.append("  ".join(parts))
        if bool(row["cycle_end"]):
            lines.append("-" * 72)
    return "\n".join(lines)


def style_infinite_buy_fills(fills: pd.DataFrame) -> pd.io.formats.style.Styler | pd.DataFrame:
    """Notebook table: buy/sell color, signed PnL, cycle-end row border.

    Falls back to a plain DataFrame if pandas Styler (jinja2) is unavailable.
    """
    show = fills.copy()
    if show.empty:
        return show.drop(columns=["cycle_end"], errors="ignore")

    def side_color(value: object) -> str:
        if value == "매수":
            return "color: #60a5fa"
        if value == "매도":
            return "color: #f87171"
        return ""

    def pnl_color(value: object) -> str:
        number = float(value)
        if number > 0:
            return "color: #4ade80"
        if number < 0:
            return "color: #f87171"
        return ""

    def cycle_border(row: pd.Series) -> list[str]:
        if bool(fills.loc[row.name, "cycle_end"]):
            return ["border-bottom: 2px solid #64748b"] * len(row)
        return [""] * len(row)

    try:
        return (
            show.style.format({
                "체결가": "{:,.0f}",
                "금액": "{:,.0f}",
                "수수료": "{:,.2f}",
                "세금": "{:,.2f}",
                "투입(누적)": "{:,.0f}",
                "평가손익": _signed_won,
            })
            .map(side_color, subset=["구분"])
            .map(pnl_color, subset=["평가손익"])
            .apply(cycle_border, axis=1)
            .hide(["cycle_end"], axis="columns")
        )
    except AttributeError:
        show["경계"] = ["──" if bool(flag) else "" for flag in show["cycle_end"]]
        return show.drop(columns=["cycle_end"])


def _signed_won(value: float) -> str:
    if value > 0:
        return f"+{value:,.2f}"
    if value < 0:
        return f"{value:,.2f}"
    return "0.00"


def _mode_label(value: object) -> str:
    text = str(value).upper()
    if text == "REVERSE":
        return "리버스"
    if text == "NORMAL":
        return "일반"
    if text == "WAIT":
        return "대기"
    return str(value)


_EQUITY_COLUMNS = [
    "일자",
    "모드",
    "T",
    "보유수량",
    "평단",
    "별지점",
    "별%",
    "시가",
    "고가",
    "저가",
    "종가",
    "잔금",
    "원금",
    "투입",
    "평가금",
    "평가손익",
    "cycle_end",
]


def infinite_buy_equity_view(equity: pd.DataFrame) -> pd.DataFrame:
    """Daily ledger with Korean column names. Pass a slice of ``result.equity``."""
    empty = pd.DataFrame(columns=_EQUITY_COLUMNS)
    if equity.empty:
        return empty

    frame = equity.copy()

    def _col(name: str) -> pd.Series:
        if name not in frame.columns:
            return pd.Series(float("nan"), index=frame.index, dtype=float)
        return pd.to_numeric(frame[name], errors="coerce")

    shares = _col("shares").fillna(0.0)
    avg = _col("avg_price").fillna(0.0)
    principal = _col("principal")
    marked = _col("equity")
    if "regime" in frame.columns:
        mode = frame["regime"]
    elif "mode" in frame.columns:
        mode = frame["mode"]
    else:
        mode = pd.Series("NORMAL", index=frame.index)
    dates = (
        pd.to_datetime(frame["trade_date"]).dt.strftime("%Y-%m-%d")
        if "trade_date" in frame.columns
        else pd.Series("", index=frame.index)
    )
    prev_shares = shares.shift(1)
    cycle_end = (shares <= 0) & prev_shares.fillna(0.0).gt(0)

    view = pd.DataFrame({
        "일자": dates,
        "모드": [_mode_label(value) for value in mode],
        "T": _col("t_value"),
        "보유수량": shares.astype(int),
        "평단": avg,
        "별지점": _col("star"),
        "별%": _col("p_value"),
        "시가": _col("open"),
        "고가": _col("high"),
        "저가": _col("low"),
        "종가": _col("close"),
        "잔금": _col("cash"),
        "원금": principal,
        "투입": shares * avg,
        "평가금": marked,
        "평가손익": marked - principal,
        "cycle_end": cycle_end,
    }, index=frame.index)
    return view.reindex(columns=_EQUITY_COLUMNS)


def style_infinite_buy_equity(equity: pd.DataFrame) -> pd.io.formats.style.Styler | pd.DataFrame:
    """Notebook daily table: Korean columns, reverse/PnL/underwater colors.

    Accepts ``result.equity`` or a slice. Falls back to a plain DataFrame without jinja2.
    """
    view = infinite_buy_equity_view(equity)
    if view.empty:
        return view.drop(columns=["cycle_end"], errors="ignore")

    def mode_color(value: object) -> str:
        if value == "리버스":
            return "color: #f87171"
        if value == "일반":
            return "color: #60a5fa"
        if value == "대기":
            return "color: #fbbf24"
        return ""

    def pnl_color(value: object) -> str:
        if pd.isna(value):
            return ""
        number = float(value)
        if number > 0:
            return "color: #4ade80"
        if number < 0:
            return "color: #f87171"
        return ""

    def close_color(row: pd.Series) -> str:
        if pd.isna(row["종가"]) or pd.isna(row["평단"]):
            return ""
        shares = float(row["보유수량"])
        close = float(row["종가"])
        avg = float(row["평단"])
        if shares > 0 and avg > 0 and close < avg:
            return "color: #f87171"
        return ""

    def cycle_border(row: pd.Series) -> list[str]:
        if bool(view.loc[row.name, "cycle_end"]):
            return ["border-bottom: 2px solid #64748b"] * len(row)
        return [""] * len(row)

    def close_column(series: pd.Series) -> list[str]:
        return [close_color(view.loc[idx]) for idx in series.index]

    try:
        return (
            view.style.format({
                "T": "{:.4f}",
                "평단": "{:,.0f}",
                "별지점": "{:,.0f}",
                "별%": "{:.2%}",
                "시가": "{:,.0f}",
                "고가": "{:,.0f}",
                "저가": "{:,.0f}",
                "종가": "{:,.0f}",
                "잔금": "{:,.0f}",
                "원금": "{:,.0f}",
                "투입": "{:,.0f}",
                "평가금": "{:,.0f}",
                "평가손익": _signed_won,
            })
            .map(mode_color, subset=["모드"])
            .map(pnl_color, subset=["평가손익"])
            .apply(close_column, subset=["종가"])
            .apply(cycle_border, axis=1)
            .hide(["cycle_end"], axis="columns")
        )
    except AttributeError:
        show = view.drop(columns=["cycle_end"])
        return show
