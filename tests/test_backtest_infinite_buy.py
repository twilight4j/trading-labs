from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import pandas as pd
import pytest

from backtest.analytics import (
    format_infinite_buy_fills,
    format_infinite_buy_report,
    infinite_buy_equity_view,
    infinite_buy_fills,
    style_infinite_buy_equity,
    style_infinite_buy_fills,
    summarize_infinite_buy,
)
from backtest.core.types import BacktestResult
from backtest.strategies import get_strategy, run_infinite_buy
from backtest.strategies.infinite_buy import crash_tier_prices, first_half_qtys, p_value, star_price


def _prices(
    closes: list[float],
    *,
    highs: list[float] | None = None,
    opens: list[float] | None = None,
) -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=len(closes), freq="B")
    high = highs if highs is not None else closes
    open_px = opens if opens is not None else closes
    return pd.DataFrame({
        "trade_date": dates,
        "security_id": "KRX:TEST",
        "open": open_px,
        "high": high,
        "low": closes,
        "close": closes,
        "volume": 1_000,
    })


def test_p_value_matches_screenshot_and_doc() -> None:
    assert p_value(0.15, 40, 0.0) == pytest.approx(0.15)
    assert p_value(0.15, 40, 1.0) == pytest.approx(0.1425)
    assert p_value(0.15, 40, 1.5) == pytest.approx(0.13875)
    assert p_value(0.15, 40, 2.0) == pytest.approx(0.135)
    assert p_value(0.15, 40, 2.5) == pytest.approx(0.13125)
    assert p_value(0.15, 40, 1.0, reverse=True) == 0.0

    p = p_value(0.20, 20, 8.6)
    assert p == pytest.approx(0.028)
    assert star_price(38.30, p) == pytest.approx(39.3724)


def test_first_half_qty_formula() -> None:
    assert first_half_qtys(1000.0, 100.0, 80.0) == (5, 7)


def test_crash_tier_prices_cap_at_five_below_large_num() -> None:
    prices = crash_tier_prices(250.0, 2, 110.0)
    assert len(prices) == 5
    assert prices[0] == pytest.approx(250.0 / 3)
    assert all(price < 110.0 for price in prices)


def test_first_buy_fills_on_start_bar() -> None:
    result = run_infinite_buy(
        _prices([11_000.0], opens=[10_000.0]),
        splits=40,
        target_pct=0.15,
        big_buy_pct=0.10,
        tick_size=1.0,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
    )
    assert result.trades.iloc[0]["reason"] == "first_buy"
    assert result.trades.iloc[0]["trade_date"] == result.equity["trade_date"].iloc[0]
    assert float(result.equity["t_value"].iloc[0]) == 1.0
    assert float(result.equity["shares"].iloc[0]) > 0.0
    buys = result.trades.loc[result.trades["reason"] == "first_buy"]
    assert len(buys) == 1
    assert float(buys.iloc[0]["price"]) == 11_000.0


def test_first_buy_fills_on_start_bar_even_if_gap_up() -> None:
    result = run_infinite_buy(
        _prices([15_000.0], opens=[10_000.0]),
        splits=40,
        big_buy_pct=0.10,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
    )
    assert result.trades.iloc[0]["reason"] == "first_buy"
    assert result.trades.iloc[0]["trade_date"] == result.equity["trade_date"].iloc[0]
    assert float(result.equity["t_value"].iloc[0]) == 1.0


def test_first_half_star_only_adds_half_turn() -> None:
    result = run_infinite_buy(
        _prices([11_000.0, 11_500.0], opens=[10_000.0, 11_500.0]),
        splits=40,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
    )
    assert float(result.equity["t_value"].iloc[0]) == 1.0
    assert float(result.equity["avg_price"].iloc[0]) == 11_000.0
    assert float(result.equity["t_value"].iloc[1]) == pytest.approx(1.5)
    reasons = set(result.trades.loc[result.trades["trade_date"] == result.equity["trade_date"].iloc[1], "reason"])
    assert "half_star" in reasons
    assert "half_avg" not in reasons


def test_quarter_sell_uses_p_not_target_and_scales_t() -> None:
    result = run_infinite_buy(
        _prices([11_000.0, 12_600.0], opens=[10_000.0, 12_600.0], highs=[11_000.0, 12_600.0]),
        splits=40,
        target_pct=0.15,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
    )
    day1 = result.equity["trade_date"].iloc[1]
    day_trades = result.trades.loc[result.trades["trade_date"] == day1]
    assert "quarter_sell" in set(day_trades["reason"])
    assert "target_limit" not in set(day_trades["reason"])
    assert float(result.equity["t_value"].iloc[1]) == pytest.approx(0.75)


def test_target_limit_then_same_day_buy_rescales_t() -> None:
    result = run_infinite_buy(
        _prices([11_000.0, 12_000.0], opens=[10_000.0, 12_000.0], highs=[11_000.0, 13_000.0]),
        splits=40,
        target_pct=0.15,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
    )
    day1 = result.equity["trade_date"].iloc[1]
    reasons = set(result.trades.loc[result.trades["trade_date"] == day1, "reason"])
    assert "target_limit" in reasons
    assert "quarter_sell" not in reasons
    assert float(result.equity["t_value"].iloc[1]) == pytest.approx(0.75)


def test_crash_tiers_fill_without_extra_t() -> None:
    result = run_infinite_buy(
        _prices([5_000.0], opens=[10_000.0]),
        splits=40,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
    )
    assert float(result.equity["t_value"].iloc[0]) == 1.0
    crash = result.trades.loc[result.trades["reason"] == "crash_tier"]
    assert len(crash) == 5
    assert float(crash["shares"].sum()) == 5.0
    first = result.trades.loc[result.trades["reason"] == "first_buy"]
    assert float(first.iloc[0]["shares"]) == 45.0
    assert float(result.equity["shares"].iloc[0]) == 50.0


def test_reverse_first_day_moc_and_t_multiplier() -> None:
    result = run_infinite_buy(
        _prices([10_000.0, 8_000.0, 8_000.0]),
        splits=40,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
        start_shares=962,
        start_avg=10_000.0,
    )
    start_t = (962 * 10_000.0 / 10_000_000.0) * 40
    assert start_t == pytest.approx(38.48)
    assert result.equity["mode"].iloc[0] == "NORMAL"
    assert float(result.equity["t_value"].iloc[1]) > 39.0
    assert result.equity["mode"].iloc[1] == "REVERSE"
    moc = result.trades.loc[result.trades["reason"] == "reverse_moc"]
    assert len(moc) == 1
    assert moc.iloc[0]["trade_date"] == result.equity["trade_date"].iloc[2]
    sold = float(moc.iloc[0]["shares"])
    shares_before = float(result.equity["shares"].iloc[1])
    assert sold == int(shares_before // 20)
    assert float(result.equity["t_value"].iloc[2]) == pytest.approx(float(result.equity["t_value"].iloc[1]) * 0.95)


def test_reverse_recovery_switches_next_orders_to_normal() -> None:
    result = run_infinite_buy(
        _prices([8_000.0, 9_000.0]),
        splits=40,
        target_pct=0.15,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
        start_shares=980,
        start_avg=10_000.0,
    )
    assert result.equity["mode"].iloc[0] == "REVERSE"
    assert result.equity["mode"].iloc[1] == "NORMAL"


def test_cycle_end_compounds_principal_into_next_first_buy() -> None:
    result = run_infinite_buy(
        _prices(
            [11_000.0, 20_000.0, 11_000.0],
            opens=[10_000.0, 20_000.0, 11_000.0],
            highs=[11_000.0, 20_000.0, 11_000.0],
        ),
        splits=40,
        target_pct=0.15,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
    )
    assert float(result.equity["shares"].iloc[1]) == 0.0
    assert float(result.equity["t_value"].iloc[1]) == 0.0
    cash_after_exit = float(result.equity["cash"].iloc[1])
    assert cash_after_exit > 10_000_000.0
    next_buy = result.trades.loc[result.trades["reason"] == "first_buy"]
    assert len(next_buy) == 2
    second = next_buy.iloc[1]
    assert second["trade_date"] == result.equity["trade_date"].iloc[2]
    expected_qty = int((cash_after_exit / 40) // (20_000.0 * 1.10))
    assert float(second["shares"]) == expected_qty
    assert "principal" in result.equity.columns
    assert float(result.equity["principal"].iloc[1]) == pytest.approx(cash_after_exit)
    assert float(result.equity["principal"].iloc[2]) == pytest.approx(cash_after_exit)
    summary = summarize_infinite_buy(result)
    assert summary["completed_cycles"] == 1
    assert summary["final_cycle_principal"] == pytest.approx(cash_after_exit)
    assert summary["realized_cycle_profit"] == pytest.approx(cash_after_exit - 10_000_000.0)
    assert str(summary["status"]).startswith("진행 중")


def test_registry_resolves_infinite_buy() -> None:
    strat = get_strategy("infinite_buy", splits=20, target_pct=0.20)
    result = strat.run(_prices([10_000.0, 11_000.0]), initial_cash=10_000_000.0, fee_rate=0.0)
    assert not result.equity.empty
    assert "t_value" in result.equity.columns
    assert "principal" in result.equity.columns
    assert {"open", "high", "low", "close"}.issubset(result.equity.columns)


def test_cli_run_passes_infinite_buy_params(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from backtest.cli import app
    from backtest.core.types import BacktestResult

    captured: dict[str, object] = {}
    stub = BacktestResult(
        equity=pd.DataFrame({
            "trade_date": pd.to_datetime(["2020-01-01"]),
            "cash": [10_000_000.0],
            "shares": [0.0],
            "close": [10.0],
            "equity": [10_000_000.0],
            "position": [0],
        }),
        trades=pd.DataFrame(),
        initial_cash=10_000_000.0,
        fee_rate=0.0,
    )

    def fake_run_backtest(strategy: str, security_id: str, **kwargs: object) -> BacktestResult:
        captured["strategy"] = strategy
        captured["security_id"] = security_id
        captured.update(kwargs)
        return stub

    monkeypatch.setattr("backtest.cli.run_backtest", fake_run_backtest)
    outcome = CliRunner().invoke(
        app,
        [
            "run",
            "--strategy",
            "infinite_buy",
            "--security-id",
            "KRX:005930",
            "--splits",
            "20",
            "--target-pct",
            "0.2",
            "--big-buy-pct",
            "0.12",
            "--initial-cash",
            "1000000",
            "--fee-rate",
            "0",
        ],
    )
    assert outcome.exit_code == 0, outcome.output
    assert captured["strategy"] == "infinite_buy"
    assert captured["splits"] == 20
    assert captured["target_pct"] == 0.2
    assert captured["big_buy_pct"] == 0.12
    assert captured["wait_extended"] is False
    assert captured["entry_lookback"] == 20
    assert captured["entry_pullback_pct"] == 0.10
    assert "splits=20" in outcome.output
    assert "wait_extended=False" in outcome.output
    assert "상태:" in outcome.output
    assert "평가 수익률" in outcome.output


def test_infinite_buy_report_fees_and_side_counts() -> None:
    result = run_infinite_buy(
        _prices([11_000.0, 12_600.0], opens=[10_000.0, 12_600.0], highs=[11_000.0, 12_600.0]),
        splits=40,
        target_pct=0.15,
        initial_cash=10_000_000.0,
        fee_rate=0.0015,
    )
    summary = summarize_infinite_buy(result)
    assert summary["total_fees"] == pytest.approx(float(result.trades["fee"].sum()))
    assert summary["buy_count"] == int((result.trades["side"] == "buy").sum())
    assert summary["sell_count"] == int((result.trades["side"] == "sell").sum())
    assert summary["buy_count"] > 0
    assert summary["sell_count"] > 0
    assert summary["total_fees"] > 0
    assert summary["total_tax"] == 0.0


def test_infinite_buy_sell_pays_fee_and_tax() -> None:
    result = run_infinite_buy(
        _prices(
            [11_000.0, 20_000.0],
            opens=[10_000.0, 20_000.0],
            highs=[11_000.0, 20_000.0],
        ),
        splits=40,
        target_pct=0.15,
        initial_cash=10_000_000.0,
        fee_rate=0.001,
        sell_tax_rate=0.002,
    )
    buys = result.trades.loc[result.trades["side"] == "buy"]
    sells = result.trades.loc[result.trades["side"] == "sell"]
    assert not buys.empty
    assert not sells.empty
    assert (buys["tax"] == 0).all()
    for _, row in buys.iterrows():
        assert float(row["fee"]) == pytest.approx(float(row["shares"]) * float(row["price"]) * 0.001)
    for _, row in sells.iterrows():
        notional = float(row["shares"]) * float(row["price"])
        assert float(row["fee"]) == pytest.approx(notional * 0.001)
        assert float(row["tax"]) == pytest.approx(notional * 0.002)
    summary = summarize_infinite_buy(result)
    assert summary["total_tax"] == pytest.approx(float(result.trades["tax"].sum()))
    assert summary["total_tax"] > 0
    fills = infinite_buy_fills(result)
    sell_fills = fills.loc[fills["구분"] == "매도"]
    assert float(sell_fills["세금"].sum()) == pytest.approx(float(sells["tax"].sum()))


def test_infinite_buy_report_underwater_mdd_and_alpha() -> None:
    dates = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"])
    result = BacktestResult(
        equity=pd.DataFrame({
            "trade_date": dates,
            "cash": [5_000_000.0, 5_000_000.0, 5_000_000.0, 5_000_000.0, 12_000_000.0],
            "shares": [100.0, 100.0, 100.0, 100.0, 0.0],
            "close": [100.0, 110.0, 90.0, 80.0, 90.0],
            "equity": [15_000_000.0, 16_000_000.0, 14_000_000.0, 13_000_000.0, 12_000_000.0],
            "position": [1, 1, 1, 1, 0],
            "principal": [10_000_000.0, 10_000_000.0, 10_000_000.0, 10_000_000.0, 12_000_000.0],
            "avg_price": [100.0, 100.0, 100.0, 100.0, 0.0],
        }),
        trades=pd.DataFrame({
            "trade_date": [dates[0], dates[4]],
            "side": ["buy", "sell"],
            "price": [100.0, 120.0],
            "shares": [100.0, 100.0],
            "fee": [10.0, 12.0],
        }),
        initial_cash=10_000_000.0,
        fee_rate=0.0,
    )
    summary = summarize_infinite_buy(result)
    assert summary["underwater_days"] == 2
    assert summary["avg_recovery_days"] == 2
    assert summary["longest_underwater_start"] == "2020-01-03"
    assert summary["longest_underwater_end"] == "2020-01-06"
    assert summary["max_drawdown"] == pytest.approx(-0.25)
    assert summary["mdd_start"] == "2020-01-02"
    assert summary["mdd_end"] == "2020-01-07"
    assert summary["completed_cycles"] == 1
    assert summary["status"] == "종료 · 1사이클 완료"
    assert summary["final_cycle_principal"] == pytest.approx(12_000_000.0)
    assert summary["realized_cycle_profit"] == pytest.approx(2_000_000.0)
    assert summary["max_invested"] == pytest.approx(10_000.0)
    assert summary["pnl"] == pytest.approx(2_000_000.0)
    assert summary["buy_hold_price"] == pytest.approx(100.0)
    assert summary["buy_hold_final"] == pytest.approx(9_000_000.0)
    assert summary["buy_hold_pnl"] == pytest.approx(-1_000_000.0)
    assert summary["buy_hold_return"] == pytest.approx(-0.10)
    assert summary["alpha"] == pytest.approx(3_000_000.0)
    assert summary["total_fees"] == pytest.approx(22.0)
    assert summary["total_tax"] == 0.0
    assert summary["buy_count"] == 1
    assert summary["sell_count"] == 1
    assert summary["calendar_days"] == 6
    assert summary["trading_days"] == 5
    text = format_infinite_buy_report(summary)
    assert "평가 수익률" in text
    assert "알파 +3,000,000" in text
    assert "MDD 구간: 2020-01-02 ~ 2020-01-07" in text
    assert "가장 긴 물밀: 2020-01-03 ~ 2020-01-06" in text


def test_infinite_buy_report_empty() -> None:
    result = BacktestResult(
        equity=pd.DataFrame(),
        trades=pd.DataFrame(),
        initial_cash=1_000.0,
        fee_rate=0.0,
    )
    summary = summarize_infinite_buy(result)
    assert summary["completed_cycles"] == 0
    assert summary["final_equity"] == 1_000.0
    assert "0사이클" in format_infinite_buy_report(summary)


def test_cycle_boundary_dates_match_flatten() -> None:
    from backtest.analytics.plot import cycle_boundary_dates

    result = run_infinite_buy(
        _prices(
            [11_000.0, 20_000.0, 11_000.0],
            opens=[10_000.0, 20_000.0, 11_000.0],
            highs=[11_000.0, 20_000.0, 11_000.0],
        ),
        splits=40,
        target_pct=0.15,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
    )
    bounds = cycle_boundary_dates(result.equity)
    assert len(bounds) == 1
    assert bounds[0] == pd.Timestamp(result.equity["trade_date"].iloc[1])


def test_reverse_spans_cover_reverse_bars() -> None:
    from backtest.analytics.plot import reverse_spans

    dates = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"])
    equity = pd.DataFrame({
        "trade_date": dates,
        "shares": [10.0, 10.0, 10.0, 10.0, 10.0],
        "mode": ["NORMAL", "REVERSE", "REVERSE", "NORMAL", "REVERSE"],
    })
    spans = reverse_spans(equity)
    assert len(spans) == 2
    assert spans[0] == (pd.Timestamp("2020-01-02"), pd.Timestamp("2020-01-06"))
    assert spans[1] == (pd.Timestamp("2020-01-07"), pd.Timestamp("2020-01-08"))


def test_plot_infinite_buy_writes_png(tmp_path: Path) -> None:
    from backtest.analytics.plot import plot_backtest

    result = run_infinite_buy(
        _prices(
            [11_000.0, 20_000.0, 11_000.0],
            opens=[10_000.0, 20_000.0, 11_000.0],
            highs=[11_000.0, 20_000.0, 11_000.0],
        ),
        splits=40,
        target_pct=0.15,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
    )
    output = tmp_path / "infinite.png"
    saved = plot_backtest(
        result,
        security_id="KRX:TEST",
        strategy="infinite_buy",
        fast=None,
        slow=None,
        output_path=output,
        show=False,
    )
    assert saved == output
    assert output.exists()
    assert output.stat().st_size > 0


def test_infinite_buy_fills_first_buy_pnl_is_fee_only() -> None:
    result = run_infinite_buy(
        _prices([11_000.0], opens=[10_000.0]),
        splits=40,
        initial_cash=10_000_000.0,
        fee_rate=0.0015,
    )
    fills = infinite_buy_fills(result)
    first = fills.iloc[0]
    assert first["구분"] == "매수"
    assert first["종류"] == "처음매수"
    qty = int(first["수량"])
    price = float(first["체결가"])
    assert price == 11_000.0
    assert float(first["금액"]) == pytest.approx(qty * price)
    assert float(first["투입(누적)"]) == pytest.approx(qty * price)
    assert int(first["누적수량"]) == qty
    assert float(first["수수료"]) == pytest.approx(qty * price * 0.0015)
    assert float(first["세금"]) == 0.0
    assert float(first["평가손익"]) == pytest.approx(-float(first["수수료"]))
    crash = fills.loc[fills["종류"] == "보조계단"]
    assert not crash.empty
    assert int(fills.iloc[-1]["누적수량"]) == int(result.equity["shares"].iloc[0])


def test_infinite_buy_fills_marks_cycle_end_and_formats() -> None:
    result = run_infinite_buy(
        _prices(
            [11_000.0, 20_000.0, 11_000.0],
            opens=[10_000.0, 20_000.0, 11_000.0],
            highs=[11_000.0, 20_000.0, 11_000.0],
        ),
        splits=40,
        target_pct=0.15,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
    )
    fills = infinite_buy_fills(result)
    ends = fills.loc[fills["cycle_end"]]
    assert len(ends) == 1
    assert int(ends.iloc[0]["누적수량"]) == 0
    assert ends.iloc[0]["구분"] == "매도"
    text = format_infinite_buy_fills(fills)
    assert "처음매수" in text
    assert "체결 이력" in text
    assert "-" * 72 in text
    styled = style_infinite_buy_fills(fills)
    if isinstance(styled, pd.DataFrame):
        assert "경계" in styled.columns
        assert "cycle_end" not in styled.columns
    else:
        html = styled.to_html()
        assert "cycle_end" not in html
        assert "평가손익" in html


def test_style_infinite_buy_equity_korean_columns() -> None:
    result = run_infinite_buy(
        _prices([11_000.0], opens=[10_000.0]),
        splits=40,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
    )
    raw_columns = list(result.equity.columns)
    view = infinite_buy_equity_view(result.equity)
    assert list(result.equity.columns) == raw_columns
    assert view["모드"].iloc[0] == "일반"
    assert "일자" in view.columns
    assert "평가손익" in view.columns
    shares = float(result.equity["shares"].iloc[0])
    avg = float(result.equity["avg_price"].iloc[0])
    assert float(view["투입"].iloc[0]) == pytest.approx(shares * avg)
    assert float(view["평가손익"].iloc[0]) == pytest.approx(
        float(result.equity["equity"].iloc[0]) - float(result.equity["principal"].iloc[0])
    )
    styled = style_infinite_buy_equity(result.equity.head(1))
    if isinstance(styled, pd.DataFrame):
        assert "cycle_end" not in styled.columns
        assert "평가손익" in styled.columns
    else:
        html = styled.to_html()
        assert "cycle_end" not in html
        assert "평가손익" in html
        assert "일반" in html


def test_infinite_buy_equity_view_reverse_and_cycle_end() -> None:
    reverse = run_infinite_buy(
        _prices([10_000.0, 8_000.0, 8_000.0]),
        splits=40,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
        start_shares=962,
        start_avg=10_000.0,
    )
    reverse_view = infinite_buy_equity_view(reverse.equity)
    assert reverse_view["모드"].iloc[1] == "리버스"
    assert float(reverse.equity["close"].iloc[1]) < float(reverse.equity["avg_price"].iloc[1])
    reverse_styled = style_infinite_buy_equity(reverse.equity)
    if not isinstance(reverse_styled, pd.DataFrame):
        reverse_html = reverse_styled.to_html()
        assert "리버스" in reverse_html
        assert "f87171" in reverse_html

    exited = run_infinite_buy(
        _prices(
            [11_000.0, 20_000.0, 11_000.0],
            opens=[10_000.0, 20_000.0, 11_000.0],
            highs=[11_000.0, 20_000.0, 11_000.0],
        ),
        splits=40,
        target_pct=0.15,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
    )
    exited_view = infinite_buy_equity_view(exited.equity)
    assert int(exited_view["보유수량"].iloc[1]) == 0
    assert bool(exited_view["cycle_end"].iloc[1]) is True
    styled = style_infinite_buy_equity(exited.equity)
    if not isinstance(styled, pd.DataFrame):
        assert "border-bottom" in styled.to_html()


def _wait_prices(closes: list[float]) -> pd.DataFrame:
    return _prices(closes, opens=closes, highs=closes)


def test_wait_extended_off_has_no_regime_and_buys_after_cycle() -> None:
    prices = _wait_prices([10_000.0, 12_000.0, 12_000.0])
    result = run_infinite_buy(
        prices,
        splits=40,
        target_pct=0.15,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
        wait_extended=False,
    )
    assert "regime" not in result.equity.columns
    first_buys = result.trades.loc[result.trades["reason"] == "first_buy"]
    assert len(first_buys) == 2
    assert first_buys["trade_date"].iloc[1] == result.equity["trade_date"].iloc[2]


def test_wait_extended_does_not_wait_when_history_short() -> None:
    result = run_infinite_buy(
        _wait_prices([11_000.0]),
        splits=40,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
        wait_extended=True,
        entry_lookback=20,
    )
    assert result.trades.iloc[0]["reason"] == "first_buy"
    assert result.equity["regime"].iloc[0] == "NORMAL"
    assert float(result.equity["shares"].iloc[0]) > 0.0


def test_wait_extended_skips_first_buy_near_high() -> None:
    result = run_infinite_buy(
        _wait_prices([10_000.0, 12_000.0, 12_000.0]),
        splits=40,
        target_pct=0.15,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
        wait_extended=True,
        entry_lookback=2,
        entry_pullback_pct=0.10,
    )
    first_buys = result.trades.loc[result.trades["reason"] == "first_buy"]
    assert len(first_buys) == 1
    assert result.equity["regime"].iloc[0] == "NORMAL"
    assert result.equity["regime"].iloc[1] == "WAIT"
    assert result.equity["regime"].iloc[2] == "WAIT"
    assert float(result.equity["shares"].iloc[2]) == 0.0
    assert result.equity["mode"].iloc[2] == "NORMAL"


def test_wait_extended_resumes_after_pullback_with_compounded_principal() -> None:
    result = run_infinite_buy(
        _wait_prices([10_000.0, 12_000.0, 12_000.0, 10_000.0, 10_000.0]),
        splits=40,
        target_pct=0.15,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
        wait_extended=True,
        entry_lookback=2,
        entry_pullback_pct=0.10,
    )
    first_buys = result.trades.loc[result.trades["reason"] == "first_buy"]
    assert len(first_buys) == 2
    assert first_buys["trade_date"].iloc[1] == result.equity["trade_date"].iloc[4]
    assert result.equity["regime"].iloc[2] == "WAIT"
    assert result.equity["regime"].iloc[3] == "NORMAL"
    assert float(result.equity["shares"].iloc[3]) == 0.0
    assert float(result.equity["shares"].iloc[4]) > 0.0
    cash_after_exit = float(result.equity["cash"].iloc[1])
    assert float(result.equity["principal"].iloc[3]) == pytest.approx(cash_after_exit)
    assert float(result.equity["principal"].iloc[4]) == pytest.approx(cash_after_exit)
    assert cash_after_exit > 10_000_000.0


def test_style_infinite_buy_equity_shows_wait() -> None:
    result = run_infinite_buy(
        _wait_prices([10_000.0, 12_000.0, 12_000.0]),
        splits=40,
        target_pct=0.15,
        initial_cash=10_000_000.0,
        fee_rate=0.0,
        wait_extended=True,
        entry_lookback=2,
        entry_pullback_pct=0.10,
    )
    view = infinite_buy_equity_view(result.equity)
    assert view["모드"].iloc[1] == "대기"
    assert view["모드"].iloc[2] == "대기"
    assert bool(view["cycle_end"].iloc[1]) is True
    assert bool(view["cycle_end"].iloc[2]) is False
    styled = style_infinite_buy_equity(result.equity)
    if not isinstance(styled, pd.DataFrame):
        html = styled.to_html()
        assert "대기" in html
        assert "fbbf24" in html
