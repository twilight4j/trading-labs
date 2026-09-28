from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import pandas as pd
import pytest

from backtest.analytics import plot_backtest, summarize
from backtest.core import run_bar_by_bar
from backtest.strategies import add_sma_cross_signals, get_strategy, run_golden_cross


def _synthetic_trend_prices() -> pd.DataFrame:
    """Build closes that force one golden cross then one death cross for fast=2, slow=3."""
    closes = [
        10,
        10,
        10,
        10,
        12,
        14,
        16,
        18,
        12,
        8,
        7,
        6,
    ]
    opens = [c for c in closes]
    dates = pd.date_range("2020-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({
        "trade_date": dates,
        "security_id": "KRX:TEST",
        "open": opens,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": 1_000,
    })


def test_sma_cross_flags_on_synthetic_series() -> None:
    signaled = add_sma_cross_signals(_synthetic_trend_prices(), fast=2, slow=3)
    assert int(signaled["golden_cross"].sum()) >= 1
    assert int(signaled["death_cross"].sum()) >= 1
    first_golden = signaled.index[signaled["golden_cross"]].tolist()[0]
    first_death = signaled.index[signaled["death_cross"]].tolist()[0]
    assert first_golden < first_death


def test_golden_then_death_produces_two_trades_and_ends_flat() -> None:
    prices = _synthetic_trend_prices()
    result = run_golden_cross(prices, fast=2, slow=3, initial_cash=1_000_000.0, fee_rate=0.0)
    assert len(result.trades) == 2
    assert list(result.trades["side"]) == ["buy", "sell"]
    assert float(result.equity["shares"].iloc[-1]) == 0.0
    assert float(result.equity["cash"].iloc[-1]) > 0.0

    summary = summarize(result)
    assert summary["trade_count"] == 2
    assert summary["bars"] == len(prices)


def test_next_bar_open_execution() -> None:
    frame = pd.DataFrame({
        "trade_date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]),
        "open": [100.0, 110.0, 90.0],
        "close": [100.0, 105.0, 95.0],
        "golden_cross": [True, False, False],
        "death_cross": [False, False, True],
    })
    result = run_bar_by_bar(frame, initial_cash=1_100.0, fee_rate=0.0)
    assert len(result.trades) == 1
    assert result.trades.iloc[0]["side"] == "buy"
    assert float(result.trades.iloc[0]["price"]) == 110.0
    assert float(result.equity["shares"].iloc[-1]) == 10.0


def test_plot_backtest_writes_png(tmp_path: Path) -> None:
    result = run_golden_cross(_synthetic_trend_prices(), fast=2, slow=3, initial_cash=1_000_000.0, fee_rate=0.0)
    output = tmp_path / "golden.png"
    saved = plot_backtest(
        result,
        security_id="KRX:TEST",
        strategy="golden_cross",
        fast=2,
        slow=3,
        output_path=output,
        show=False,
    )
    assert saved == output
    assert output.exists()
    assert output.stat().st_size > 0


def test_strategy_registry_resolves_golden_cross() -> None:
    strat = get_strategy("golden_cross", fast=2, slow=3)
    result = strat.run(_synthetic_trend_prices(), initial_cash=1_000_000.0, fee_rate=0.0)
    assert len(result.trades) == 2


def test_sell_tax_is_charged_only_on_sells() -> None:
    result = run_golden_cross(
        _synthetic_trend_prices(),
        fast=2,
        slow=3,
        initial_cash=1_000_000.0,
        fee_rate=0.01,
        sell_tax_rate=0.02,
    )
    buy = result.trades.iloc[0]
    sell = result.trades.iloc[1]
    buy_notional = float(buy["shares"]) * float(buy["price"])
    sell_notional = float(sell["shares"]) * float(sell["price"])
    assert float(buy["fee"]) == pytest.approx(buy_notional * 0.01)
    assert float(buy["tax"]) == 0.0
    assert float(sell["fee"]) == pytest.approx(sell_notional * 0.01)
    assert float(sell["tax"]) == pytest.approx(sell_notional * 0.02)
    assert result.sell_tax_rate == 0.02
    with pytest.raises(ValueError, match="sell_tax_rate"):
        run_bar_by_bar(
            pd.DataFrame({
                "trade_date": pd.to_datetime(["2020-01-01"]),
                "open": [100.0],
                "close": [100.0],
                "golden_cross": [False],
                "death_cross": [False],
            }),
            sell_tax_rate=-0.01,
        )
