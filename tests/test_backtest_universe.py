from __future__ import annotations

from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import pandas as pd
import pytest

from backtest.analytics.cross_section import (
    attach_size_quintile,
    period_hit_rates,
    plot_excess_scatter,
    plot_period_hit_rate,
    stock_axis_summary,
    stock_group_summary,
)
from backtest.analytics.metrics import cagr, is_effective, period_returns
from backtest.api import load_run_panel, run_universe_backtest, save_run_panel
from backtest.core.types import RunPanel
from backtest.data import list_universe, load_price_panel


def _price_row(security_id: str, market: str, cap: float, open_: float, close: float) -> dict[str, object]:
    return {
        "security_id": security_id,
        "market": market,
        "open_raw": open_,
        "high_raw": close,
        "low_raw": open_,
        "close_raw": close,
        "open_adjusted": open_,
        "high_adjusted": close,
        "low_adjusted": open_,
        "close_adjusted": close,
        "volume": 1_000,
        "market_cap": cap,
    }


def _write_partition(root: Path, dataset: str, partition: str, frame: pd.DataFrame) -> None:
    path = root / "curated" / dataset / partition
    path.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path / "part-000.parquet", index=False)


def _lake(tmp_path: Path) -> Path:
    as_of = date(2026, 7, 30)
    day_rows = [
        _price_row("KRX:AAA", "KOSPI", 200_000_000_000, 10.0, 11.0),
        _price_row("KRX:BBB", "KOSPI", 50_000_000_000, 20.0, 21.0),
        _price_row("KRX:CCC", "KOSDAQ", 150_000_000_000, 30.0, 31.0),
        _price_row("KRX:ETF", "KOSPI", 300_000_000_000, 40.0, 41.0),
    ]
    _write_partition(tmp_path, "daily_prices", f"trade_date={as_of.isoformat()}", pd.DataFrame(day_rows))
    hist = []
    for offset, close in enumerate([10.0, 10.0, 12.0, 14.0, 8.0, 7.0]):
        day = date(2020, 1, 2 + offset)
        hist.append({
            **_price_row("KRX:AAA", "KOSPI", 200_000_000_000, close, close),
            "trade_date": pd.Timestamp(day),
        })
        hist.append({
            **_price_row("KRX:CCC", "KOSDAQ", 150_000_000_000, close + 1, close + 1),
            "trade_date": pd.Timestamp(day),
        })
    hist_frame = pd.DataFrame(hist)
    for day, chunk in hist_frame.groupby(hist_frame["trade_date"].dt.strftime("%Y-%m-%d")):
        _write_partition(tmp_path, "daily_prices", f"trade_date={day}", chunk.drop(columns=["trade_date"]))
    snapshot = pd.DataFrame({
        "security_id": ["KRX:AAA", "KRX:BBB", "KRX:CCC", "KRX:ETF"],
        "market": ["KOSPI", "KOSPI", "KOSDAQ", "KOSPI"],
        "security_type": ["COMMON", "COMMON", "COMMON", "EXCLUDED"],
        "exclusion_reason": ["", "", "", "ETF"],
        "as_of_date": pd.Timestamp(as_of),
        "eligible": [True, True, True, False],
    })
    _write_partition(tmp_path, "universe_snapshot", f"as_of_date={as_of.isoformat()}", snapshot)
    master = pd.DataFrame({
        "security_id": ["KRX:AAA", "KRX:BBB", "KRX:CCC", "KRX:ETF"],
        "name": ["Alpha", "Beta", "Gamma", "Fund"],
        "market": ["KOSPI", "KOSPI", "KOSDAQ", "KOSPI"],
    })
    _write_partition(tmp_path, "security_master", "current", master)
    return tmp_path


def test_list_universe_filters_market_cap_and_eligible(tmp_path: Path) -> None:
    data_dir = _lake(tmp_path)
    universe = list_universe(data_dir, as_of=date(2026, 7, 30), min_market_cap=100_000_000_000)
    assert set(universe["security_id"]) == {"KRX:AAA", "KRX:CCC"}
    assert float(universe.loc[universe["security_id"] == "KRX:AAA", "market_cap"].iloc[0]) == 200_000_000_000
    assert universe.loc[universe["security_id"] == "KRX:AAA", "name"].iloc[0] == "Alpha"


def test_list_universe_missing_as_of_is_empty(tmp_path: Path) -> None:
    data_dir = _lake(tmp_path)
    universe = list_universe(data_dir, as_of=date(2020, 1, 1), min_market_cap=1.0)
    assert universe.empty


def test_list_universe_snaps_to_prior_session(tmp_path: Path) -> None:
    data_dir = _lake(tmp_path)
    universe = list_universe(data_dir, as_of=date(2026, 8, 1), min_market_cap=100_000_000_000)
    assert not universe.empty
    assert universe["as_of"].dt.date.iloc[0] == date(2026, 7, 30)
    assert set(universe["security_id"]) == {"KRX:AAA", "KRX:CCC"}


def test_list_universe_skips_a_stored_holiday_of_zero_market_caps(tmp_path: Path) -> None:
    # Holidays used to be stored with every stock at zero (2026-09-24·25 추석 in the real data).
    data_dir = _lake(tmp_path)
    holiday = pd.DataFrame([
        {**_price_row("KRX:AAA", "KOSPI", 0, 0.0, 0.0), "volume": 0},
        {**_price_row("KRX:CCC", "KOSDAQ", 0, 0.0, 0.0), "volume": 0},
    ])
    _write_partition(tmp_path, "daily_prices", "trade_date=2026-07-31", holiday)

    for as_of in (date(2026, 7, 31), date(2026, 8, 1)):
        universe = list_universe(data_dir, as_of=as_of, min_market_cap=100_000_000_000)
        assert universe["as_of"].dt.date.iloc[0] == date(2026, 7, 30)
        assert set(universe["security_id"]) == {"KRX:AAA", "KRX:CCC"}


def test_load_price_panel_multiple_ids(tmp_path: Path) -> None:
    data_dir = _lake(tmp_path)
    panel = load_price_panel(data_dir, ["KRX:AAA", "KRX:CCC"], start=date(2020, 1, 1), end=date(2020, 1, 31))
    assert set(panel) == {"KRX:AAA", "KRX:CCC"}
    assert not panel["KRX:AAA"].empty
    assert {"trade_date", "open", "close"} <= set(panel["KRX:AAA"].columns)


def test_is_effective_and_cagr() -> None:
    assert is_effective(0.1, -0.2, mdd_limit=-0.30) is True
    assert is_effective(0.1, -0.4, mdd_limit=-0.30) is False
    assert is_effective(-0.01, -0.1, mdd_limit=-0.30) is False
    assert cagr(1.0, 252) == pytest.approx(1.0)


def test_period_returns_year_and_month() -> None:
    equity = pd.DataFrame({
        "trade_date": pd.to_datetime(["2020-01-02", "2020-06-01", "2021-01-04", "2021-12-01"]),
        "equity": [100.0, 110.0, 120.0, 150.0],
        "close": [10.0, 11.0, 12.0, 15.0],
    })
    yearly = period_returns(equity, freq="YE")
    assert list(yearly["period"]) == ["2020", "2021"]
    assert yearly.loc[yearly["period"] == "2020", "strategy_return"].iloc[0] == pytest.approx(0.10)
    monthly = period_returns(equity, freq="ME")
    assert "2020-01" in set(monthly["period"])
    assert (monthly["excess_return"] == monthly["strategy_return"] - monthly["buy_hold_return"]).all()


def _synthetic_prices() -> pd.DataFrame:
    closes = [10, 10, 10, 10, 12, 14, 16, 18, 12, 8, 7, 6]
    dates = pd.date_range("2020-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({
        "trade_date": dates,
        "security_id": "KRX:WIN",
        "open": closes,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": 1_000,
    })


def test_run_universe_backtest_keeps_error_row(monkeypatch: pytest.MonkeyPatch) -> None:
    win = _synthetic_prices()
    miss_id = "KRX:MISS"
    universe = pd.DataFrame({
        "security_id": ["KRX:WIN", miss_id],
        "name": ["Winner", "Missing"],
        "market": ["KOSPI", "KOSPI"],
        "market_cap": [200_000_000_000, 150_000_000_000],
    })

    def fake_panel(_data_dir, security_ids, **_kwargs):
        out = {}
        if "KRX:WIN" in security_ids:
            out["KRX:WIN"] = win
        return out

    monkeypatch.setattr("backtest.api.load_price_panel", fake_panel)
    panel = run_universe_backtest("golden_cross", universe, fast=2, slow=3, fee_rate=0.0, mdd_limit=-0.99)
    assert set(panel.summaries["security_id"]) == {"KRX:WIN", miss_id}
    miss = panel.summaries.loc[panel.summaries["security_id"] == miss_id].iloc[0]
    assert miss["error"] == "no prices"
    assert bool(miss["effective"]) is False
    win_row = panel.summaries.loc[panel.summaries["security_id"] == "KRX:WIN"].iloc[0]
    assert win_row["error"] == ""
    assert "excess_return" in win_row
    assert not panel.period_returns.empty
    assert set(panel.period_returns["freq"]) <= {"YE", "ME"}


def test_mdd_limit_is_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    prices = _synthetic_prices()
    universe = pd.DataFrame({
        "security_id": ["KRX:WIN"],
        "name": ["Winner"],
        "market": ["KOSPI"],
        "market_cap": [200_000_000_000],
    })
    seen: list[float] = []

    def fake_effective(_excess: float, _mdd: float, *, mdd_limit: float = -0.30) -> bool:
        seen.append(mdd_limit)
        return True

    monkeypatch.setattr("backtest.api.load_price_panel", lambda *_args, **_kwargs: {"KRX:WIN": prices})
    monkeypatch.setattr("backtest.api.is_effective", fake_effective)
    run_universe_backtest("golden_cross", universe, fast=2, slow=3, fee_rate=0.0, mdd_limit=-0.99)
    run_universe_backtest("golden_cross", universe, fast=2, slow=3, fee_rate=0.0, mdd_limit=0.0)
    assert seen == [-0.99, 0.0]


def test_save_and_load_run_panel(tmp_path: Path) -> None:
    summaries = pd.DataFrame({
        "security_id": ["KRX:AAA"],
        "excess_return": [0.1],
        "effective": [True],
        "error": [""],
    })
    periods = pd.DataFrame({
        "security_id": ["KRX:AAA"],
        "period": ["2020"],
        "freq": ["YE"],
        "strategy_return": [0.2],
        "buy_hold_return": [0.1],
        "excess_return": [0.1],
    })
    saved = save_run_panel(RunPanel(summaries=summaries, period_returns=periods), tmp_path / "run")
    loaded = load_run_panel(saved)
    assert list(loaded.summaries["security_id"]) == ["KRX:AAA"]
    assert list(loaded.period_returns["period"]) == ["2020"]


def test_cross_section_groups_and_hit_rate(tmp_path: Path) -> None:
    summaries = pd.DataFrame({
        "security_id": ["KRX:A", "KRX:B", "KRX:C"],
        "market": ["KOSPI", "KOSPI", "KOSDAQ"],
        "market_cap": [3e11, 2e11, 1.5e11],
        "excess_return": [0.2, -0.1, 0.05],
        "max_drawdown": [-0.1, -0.2, -0.15],
        "trade_count": [4, 2, 3],
        "realized_vol": [0.02, 0.03, 0.01],
        "buy_hold_return": [0.1, 0.4, 0.0],
        "effective": [True, False, True],
        "error": ["", "", ""],
    })
    groups = stock_group_summary(summaries)
    assert int(groups.loc[groups["effective"] == True, "n"].iloc[0]) == 2
    sized = attach_size_quintile(summaries)
    assert "size_quintile" in sized.columns
    by_market = stock_axis_summary(summaries, by="market")
    assert set(by_market["market"]) <= {"KOSPI", "KOSDAQ"}
    periods = pd.DataFrame({
        "security_id": ["KRX:A", "KRX:B", "KRX:A", "KRX:B"],
        "period": ["2020", "2020", "2021", "2021"],
        "freq": ["YE", "YE", "YE", "YE"],
        "strategy_return": [0.2, 0.0, -0.1, 0.1],
        "buy_hold_return": [0.1, 0.2, 0.0, -0.2],
        "excess_return": [0.1, -0.2, -0.1, 0.3],
    })
    hits = period_hit_rates(periods, freq="YE")
    assert hits.loc[hits["period"] == "2020", "hit_rate"].iloc[0] == pytest.approx(0.5)
    plot_period_hit_rate(hits, output_path=tmp_path / "hit.png", show=False)
    plot_excess_scatter(summaries, output_path=tmp_path / "scatter.png", show=False)
    assert (tmp_path / "hit.png").exists()
    assert (tmp_path / "scatter.png").exists()
