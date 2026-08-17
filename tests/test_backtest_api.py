from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from typer.testing import CliRunner

from backtest.api import run_backtest
from backtest.cli import app
from backtest.core.types import BacktestResult


def _prices() -> pd.DataFrame:
    closes = [10, 10, 10, 10, 12, 14, 16, 18, 12, 8, 7, 6]
    dates = pd.date_range("2020-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({
        "trade_date": dates,
        "security_id": "KRX:TEST",
        "open": closes,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": 1_000,
    })


def test_run_backtest_loads_prices_and_runs_registered_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    prices = _prices()
    loader = MagicMock(return_value=prices)
    monkeypatch.setattr("backtest.api.load_price_series", loader)

    result = run_backtest(
        "golden_cross",
        "KRX:TEST",
        data_dir=Path("unused"),
        start=date(2020, 1, 1),
        end=date(2020, 6, 1),
        initial_cash=1_000_000.0,
        fee_rate=0.0,
        fast=2,
        slow=3,
    )

    loader.assert_called_once_with(
        Path("unused"),
        "KRX:TEST",
        start=date(2020, 1, 1),
        end=date(2020, 6, 1),
    )
    assert isinstance(result, BacktestResult)
    assert len(result.trades) == 2
    assert list(result.trades["side"]) == ["buy", "sell"]


def test_run_backtest_unknown_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backtest.api.load_price_series", MagicMock(return_value=_prices()))
    with pytest.raises(KeyError, match="unknown strategy"):
        run_backtest("does_not_exist", "KRX:TEST")


def test_cli_run_delegates_to_run_backtest(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    stub = BacktestResult(
        equity=pd.DataFrame({
            "trade_date": pd.to_datetime(["2020-01-01"]),
            "cash": [1_000_000.0],
            "shares": [0.0],
            "close": [10.0],
            "equity": [1_000_000.0],
            "position": [0],
        }),
        trades=pd.DataFrame(),
        initial_cash=1_000_000.0,
        fee_rate=0.0,
    )

    def fake_run_backtest(strategy: str, security_id: str, **kwargs: object) -> BacktestResult:
        captured["strategy"] = strategy
        captured["security_id"] = security_id
        captured.update(kwargs)
        return stub

    monkeypatch.setattr("backtest.cli.run_backtest", fake_run_backtest)
    runner = CliRunner()
    outcome = runner.invoke(
        app,
        [
            "run",
            "--strategy",
            "golden_cross",
            "--security-id",
            "KRX:005930",
            "--fast",
            "50",
            "--slow",
            "200",
            "--start",
            "2015-01-01",
            "--initial-cash",
            "1000000",
            "--fee-rate",
            "0",
        ],
    )
    assert outcome.exit_code == 0, outcome.output
    assert captured["strategy"] == "golden_cross"
    assert captured["security_id"] == "KRX:005930"
    assert captured["fast"] == 50
    assert captured["slow"] == 200
    assert captured["start"] == date(2015, 1, 1)
    assert captured["initial_cash"] == 1_000_000.0
    assert captured["fee_rate"] == 0.0
    assert "total_return=" in outcome.output


def test_resolve_data_dir_uses_repo_when_cwd_is_notebook_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backtest.data.prices import _resolve_data_dir

    repo = tmp_path / "repo"
    curated = repo / "data" / "market-data" / "curated" / "daily_prices"
    curated.mkdir(parents=True)
    notebooks = tmp_path / "notebooks"
    notebooks.mkdir()
    monkeypatch.setattr("backtest.data.prices._repo_root", lambda: repo)
    monkeypatch.chdir(notebooks)
    assert _resolve_data_dir(Path("data/market-data")) == repo / "data" / "market-data"
