from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from collector.config import Settings
from collector.ingestion.consensus import ConsensusService
from collector.storage import Lakehouse
from valuation.api import create_app
from valuation.cli import app as labs_cli
from valuation.per import PerConfig
from valuation.screener import EOK, FairValueTable, build_fair_value_rows, fair_value
from wisereport_fakes import FakeWiseReport, seed_market_data

# --- formula -----------------------------------------------------------------


def test_fair_value_reproduces_samsung_example():
    fair_cap, upside = fair_value(4_744_728, 16_749_588, 10)
    assert fair_cap == 47_447_280
    assert upside == pytest.approx(183.27, abs=0.01)

    fair_cap, upside = fair_value(3_196_572, 16_749_588, 10)
    assert fair_cap == 31_965_720
    assert upside == pytest.approx(90.84, abs=0.01)


def test_fair_value_reproduces_ecoprobm_example_and_handles_missing_or_negative_e():
    fair_cap, upside = fair_value(142, 103_211, 10)
    assert fair_cap == 1_420
    assert upside == pytest.approx(-98.62, abs=0.01)

    fair_cap, upside = fair_value(1_179, 103_211, 10)
    assert fair_cap == 11_790
    assert upside == pytest.approx(-88.58, abs=0.01)

    assert fair_value(None, 103_211, 10) == (None, None)
    assert fair_value(float("nan"), 103_211, 10) == (None, None)
    fair_cap, upside = fair_value(-500, 1_000, 10)
    assert fair_cap == -5_000
    assert upside == pytest.approx(-600.0)


# --- PER config --------------------------------------------------------------


def test_per_config_precedence_stock_then_sector_then_default(tmp_path: Path):
    path = tmp_path / "per.toml"
    path.write_text(
        'default_per = 8\n[sector_per]\n"반도체와반도체장비" = 12\n[stock_per]\n"005930" = 15\n',
        encoding="utf-8",
    )
    config = PerConfig.load(path)
    assert config.resolve("005930", "반도체와반도체장비") == 15
    assert config.resolve("000660", "반도체와반도체장비") == 12
    assert config.resolve("247540", "전기제품") == 8
    assert config.resolve("247540", None) == 8


def test_per_config_defaults_to_ten_and_rejects_non_positive(tmp_path: Path):
    assert PerConfig.load(None).resolve("005930", "x") == 10
    assert PerConfig.load(tmp_path / "missing.toml").resolve("005930", "x") == 10
    bad = tmp_path / "bad.toml"
    for content in ('[stock_per]\n"005930" = 0\n', "sector_per = 12\n", "default_per = [1]\n", 'default_per = "10"\n'):
        bad.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError):
            PerConfig.load(bad)


def test_repo_per_config_file_is_valid():
    config = PerConfig.load(Path(__file__).parents[1] / "config" / "valuation_per.toml")
    assert config.default_per == 10


# --- table building ----------------------------------------------------------


def _estimate_rows(ticker: str, values: dict[int, float | None], first_estimate: int) -> list[dict]:
    return [
        {
            "security_id": f"KRX:{ticker}",
            "ticker": ticker,
            "fiscal_period": f"{year}12",
            "fiscal_year": year,
            "is_estimate": year >= first_estimate,
            "net_income_controlling": value,
        }
        for year, value in values.items()
    ]


def _inputs(estimate_rows: list[dict], caps_eok: dict[str, float]):
    estimates = pd.DataFrame(estimate_rows)
    estimates["net_income_controlling"] = estimates["net_income_controlling"].astype("float64")
    tickers = list(caps_eok)
    prices = pd.DataFrame(
        {
            "security_id": [f"KRX:{t}" for t in tickers],
            "market": ["KOSPI"] * len(tickers),
            "market_cap": [caps_eok[t] * EOK for t in tickers],
        }
    )
    master = pd.DataFrame({"security_id": [f"KRX:{t}" for t in tickers], "name": [f"종목{t}" for t in tickers]})
    profiles = pd.DataFrame({"ticker": tickers, "sector": ["업종A"] * len(tickers), "dividend_yield": [1.0] * len(tickers)})
    return estimates, profiles, prices, master


def test_build_rows_only_keeps_y2_estimates_and_leaves_missing_y0_null():
    rows = (
        _estimate_rows("000001", {2025: 50.0, 2026: 100.0, 2027: 150.0, 2028: 200.0}, 2026)
        + _estimate_rows("000002", {2025: 50.0, 2026: None, 2027: None, 2028: 300.0}, 2026)
        + _estimate_rows("000003", {2025: 50.0, 2026: 100.0, 2027: 120.0, 2028: None}, 2026)
    )
    base_year, table = build_fair_value_rows(*_inputs(rows, {"000001": 1_500, "000002": 1_500, "000003": 1_500}), PerConfig(), 0)
    assert base_year == 2026
    assert set(table["ticker"]) == {"000001", "000002"}
    no_y0 = table.set_index("ticker").loc["000002"]
    assert pd.isna(no_y0["net_income_y0"]) and pd.isna(no_y0["fair_cap_y0"]) and pd.isna(no_y0["upside_y0"])
    assert no_y0["fair_cap_y2"] == 3_000
    assert no_y0["upside_y2"] == pytest.approx(100.0)
    # Default order: upside_y2 descending.
    assert table["ticker"].tolist() == ["000002", "000001"]


def test_build_rows_rolls_base_year_with_the_data():
    rows = (
        _estimate_rows("000001", {2026: 90.0, 2027: 100.0, 2028: 150.0, 2029: 200.0}, 2027)
        + _estimate_rows("000002", {2026: 90.0, 2027: 100.0, 2028: 150.0, 2029: 250.0}, 2027)
        + _estimate_rows("000003", {2025: 90.0, 2026: 100.0, 2027: 150.0, 2028: 999.0}, 2026)
    )
    base_year, table = build_fair_value_rows(*_inputs(rows, {"000001": 1_000, "000002": 1_000, "000003": 1_000}), PerConfig(), 0)
    assert base_year == 2027
    by_ticker = table.set_index("ticker")
    assert by_ticker.loc["000001", "net_income_y0"] == 100.0
    assert by_ticker.loc["000001", "net_income_y2"] == 200.0
    # 000003's latest estimate year is 2028, so it has no 2029 (Y2) value and drops out.
    assert "000003" not in by_ticker.index


def test_build_rows_applies_market_cap_floor_and_per_precedence():
    rows = _estimate_rows("000001", {2026: 100.0, 2028: 200.0}, 2026) + _estimate_rows("000002", {2026: 100.0, 2028: 200.0}, 2026)
    config = PerConfig(default_per=10, sector_per={"업종A": 12}, stock_per={"000001": 20})
    _, table = build_fair_value_rows(*_inputs(rows, {"000001": 2_000, "000002": 1_000}), config, 1_200 * EOK)
    assert table["ticker"].tolist() == ["000001"]
    assert table.loc[0, "base_per"] == 20
    assert table.loc[0, "fair_cap_y2"] == 4_000


# --- API ---------------------------------------------------------------------


@pytest.fixture
def seeded_settings(tmp_path: Path) -> Settings:
    settings = Settings(data_dir=tmp_path / "market-data")
    seed_market_data(Lakehouse(settings))
    return settings


def test_api_returns_fair_value_rows_from_latest_published_snapshot(seeded_settings):
    ConsensusService(seeded_settings, provider=FakeWiseReport()).update(date(2026, 9, 26))
    client = TestClient(create_app(seeded_settings))

    response = client.get("/api/v1/valuation/fair-value")

    assert response.status_code == 200
    payload = response.json()
    assert payload["base_year"] == 2026
    assert payload["snapshot_date"] == "2026-09-26"
    assert payload["price_date"] == "2026-09-25"
    # 동화약품 has no 2028 estimate and is excluded; ordered by 28 upside descending.
    assert [row["ticker"] for row in payload["rows"]] == ["005930", "247540"]
    samsung = payload["rows"][0]
    assert set(samsung) == {
        "stock_name", "market", "ticker", "market_cap_eok", "net_income_y0", "fair_cap_y0", "upside_y0",
        "net_income_y2", "fair_cap_y2", "upside_y2", "dividend_yield", "sector", "base_per",
    }
    assert samsung["stock_name"] == "삼성전자"
    assert samsung["market"] == "KOSPI"
    assert samsung["market_cap_eok"] == 16_749_588
    assert samsung["net_income_y2"] == 4_744_728.4
    assert samsung["upside_y2"] == pytest.approx(183.27, abs=0.01)
    assert samsung["upside_y0"] == pytest.approx(90.84, abs=0.01)
    assert samsung["sector"] == "반도체와반도체장비"
    assert samsung["dividend_yield"] == 0.58
    assert samsung["base_per"] == 10
    ecopro = payload["rows"][1]
    assert ecopro["market"] == "KOSDAQ"
    assert ecopro["upside_y0"] == pytest.approx(-98.62, abs=0.01)
    assert ecopro["upside_y2"] == pytest.approx(-88.57, abs=0.01)


def test_api_reads_per_config_on_each_request(seeded_settings, tmp_path):
    ConsensusService(seeded_settings, provider=FakeWiseReport()).update(date(2026, 9, 26))
    per_path = tmp_path / "per.toml"
    client = TestClient(create_app(seeded_settings, per_path))
    assert client.get("/api/v1/valuation/fair-value").json()["rows"][0]["base_per"] == 10

    per_path.write_text('[stock_per]\n"005930" = 20\n', encoding="utf-8")
    samsung = client.get("/api/v1/valuation/fair-value").json()["rows"][0]
    assert samsung["base_per"] == 20
    assert samsung["fair_cap_y2"] == pytest.approx(4_744_728.4 * 20)


def test_api_returns_503_on_malformed_per_config(seeded_settings, tmp_path):
    ConsensusService(seeded_settings, provider=FakeWiseReport()).update(date(2026, 9, 26))
    per_path = tmp_path / "per.toml"
    per_path.write_text("default_per = [broken", encoding="utf-8")
    response = TestClient(create_app(seeded_settings, per_path)).get("/api/v1/valuation/fair-value")
    assert response.status_code == 503
    assert "기준PER 설정 오류" in response.json()["detail"]


def test_payload_turns_pandas_missing_values_into_null():
    rows = pd.DataFrame({"stock_name": pd.array([pd.NA, "삼성전자"], dtype="string"), "upside_y0": [float("nan"), 1.5]})
    payload = FairValueTable(base_year=2026, snapshot_date="2026-09-26", price_date="2026-09-25", rows=rows).as_payload()
    assert payload["rows"] == [{"stock_name": None, "upside_y0": None}, {"stock_name": "삼성전자", "upside_y0": 1.5}]


def test_api_returns_503_without_published_snapshot(seeded_settings):
    client = TestClient(create_app(seeded_settings))
    response = client.get("/api/v1/valuation/fair-value")
    assert response.status_code == 503
    assert "consensus update" in response.json()["detail"]

    ConsensusService(seeded_settings, provider=FakeWiseReport(fail_consensus={"247540", "000020"})).update(date(2026, 9, 26))
    assert client.get("/api/v1/valuation/fair-value").status_code == 503


def test_labs_api_serve_defaults_to_port_8100(monkeypatch):
    calls = {}
    monkeypatch.setattr("valuation.cli.uvicorn.run", lambda app, host, port: calls.update(host=host, port=port))
    result = CliRunner().invoke(labs_cli, ["serve"])
    assert result.exit_code == 0, result.output
    assert calls == {"host": "127.0.0.1", "port": 8100}
