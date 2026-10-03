import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import requests
from typer.testing import CliRunner

import collector.ingestion.consensus as consensus_module
from collector.cli import app
from collector.config import Settings
from collector.ingestion.consensus import (
    CONSENSUS_DATASET,
    PROFILE_DATASET,
    ConsensusService,
    is_preferred_share,
    latest_published_snapshot,
    read_latest_prices,
    read_snapshot,
)
from collector.ingestion.scheduler import build_scheduler
from collector.providers.wisereport import WiseReportError, WiseReportProvider
from collector.storage import Lakehouse
from collector.transforms.consensus import infer_base_year, parse_company_profile, parse_consensus
from wisereport_fakes import EOK, FakeWiseReport, company_fixture, consensus_fixture, seed_market_data


def _estimates(frame: pd.DataFrame) -> dict[int, float]:
    projected = frame.loc[frame["is_estimate"]]
    return dict(zip(projected["fiscal_year"], projected["net_income_controlling"], strict=True))


# --- parsers -----------------------------------------------------------------


def test_parse_consensus_reads_controlling_net_income_estimates():
    samsung = parse_consensus(consensus_fixture("005930"), security_id="KRX:005930", ticker="005930")
    assert _estimates(samsung) == {2026: 3196571.9, 2027: 4566458.5, 2028: 4744728.4}
    assert not samsung.loc[samsung["fiscal_year"] == 2025, "is_estimate"].item()
    assert set(samsung["fiscal_period"]) >= {"202612", "202712", "202812"}

    ecopro = parse_consensus(consensus_fixture("247540"), security_id="KRX:247540", ticker="247540")
    estimates = _estimates(ecopro)
    assert estimates[2026] == 141.9
    assert estimates[2028] == 1179.4


def test_parse_consensus_keeps_missing_estimates_null_and_tolerates_empty_payload():
    uncovered = parse_consensus(consensus_fixture("000020"), security_id="KRX:000020", ticker="000020")
    projected = uncovered.loc[uncovered["is_estimate"], "net_income_controlling"]
    assert len(projected) == 3
    assert projected.isna().all()
    assert (uncovered.loc[~uncovered["is_estimate"], "net_income_controlling"] != 0).all()

    empty = parse_consensus({"JsonData": []}, security_id="KRX:005935", ticker="005935")
    assert empty.empty
    assert "net_income_controlling" in empty.columns


def test_parse_company_profile_reads_wics_sector_and_dividend_yield():
    assert parse_company_profile(company_fixture("company_005930")) == ("반도체와반도체장비", 0.58)
    assert parse_company_profile(company_fixture("company_247540")) == ("전기제품", 0.10)
    assert parse_company_profile(company_fixture("company_277810_no_dividend")) == ("기계", None)
    assert parse_company_profile(company_fixture("company_invalid")) == (None, None)


def test_infer_base_year_uses_most_common_first_estimate_year():
    def rows(ticker: str, first_estimate: int) -> list[dict]:
        return [
            {"ticker": ticker, "fiscal_year": year, "is_estimate": year >= first_estimate}
            for year in range(first_estimate - 2, first_estimate + 3)
        ]

    current = pd.DataFrame(rows("A", 2026) + rows("B", 2026) + rows("C", 2027))
    assert infer_base_year(current) == 2026
    rolled = pd.DataFrame(rows("A", 2027) + rows("B", 2027) + rows("C", 2026))
    assert infer_base_year(rolled) == 2027
    assert infer_base_year(pd.DataFrame(columns=["ticker", "fiscal_year", "is_estimate"])) is None


# --- provider ----------------------------------------------------------------


class _Response:
    def __init__(self, payload=None, text="", status=200):
        self._payload = payload
        self.text = text
        self.status_code = status
        self.encoding = None

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _FlakySession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_provider_retries_then_returns_consensus_json():
    session = _FlakySession([requests.ConnectionError("boom"), _Response(payload={"JsonData": []})])
    provider = WiseReportProvider(request_interval=0, retry_backoff=0, session=session)
    assert provider.fetch_consensus("005930") == {"JsonData": []}
    assert len(session.calls) == 2
    url, params = session.calls[-1]
    assert url.endswith("/v3/company/ajax/c1050001_data.aspx")
    assert params == {"flag": "2", "cmp_cd": "005930", "finGubun": "MAIN", "frq": "0"}


def test_provider_raises_after_exhausting_retries_or_on_non_json():
    session = _FlakySession([_Response(status=500)] * 2)
    provider = WiseReportProvider(request_interval=0, retry_backoff=0, max_retries=2, session=session)
    with pytest.raises(WiseReportError):
        provider.fetch_consensus("005930")

    provider = WiseReportProvider(request_interval=0, retry_backoff=0, session=_FlakySession([_Response(text="<html>")]))
    with pytest.raises(WiseReportError):
        provider.fetch_consensus("005930")


# --- collection service ------------------------------------------------------

@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    settings = Settings(data_dir=tmp_path / "market-data")
    seed_market_data(Lakehouse(settings))
    return settings


def test_select_universe_uses_latest_prices_common_shares_and_market_cap_floor(settings):
    universe = ConsensusService(settings, provider=FakeWiseReport()).select_universe()
    assert universe["ticker"].tolist() == ["005930", "247540", "000020"]
    assert set(universe["market"]) == {"KOSPI", "KOSDAQ"}
    assert universe.loc[universe["ticker"] == "005930", "market_cap"].item() == 16_749_588 * EOK

    names = pd.Series(["삼성전자우", "현대차2우B", "CJ4우(전환)", "CJ제일제당 우", "성우", "이오플로우"])
    known = {"삼성전자", "현대차", "CJ", "CJ제일제당", "이오플"}
    assert is_preferred_share(names, known).tolist() == [True, True, True, True, False, False]

    limited = ConsensusService(settings, provider=FakeWiseReport()).select_universe(limit=1)
    assert limited["ticker"].tolist() == ["005930"]


def test_latest_prices_skip_a_holiday_partition_of_zero_market_caps(settings):
    # pykrx stores market holidays as every stock with a zero market cap (2026-09-24·25 추석 in the real data).
    lakehouse = Lakehouse(settings)
    holiday = lakehouse.read_curated_partition("daily_prices", "trade_date=2026-09-25")
    holiday = holiday.assign(trade_date=pd.Timestamp("2026-09-28"), market_cap=0)
    lakehouse.replace_curated_partition("daily_prices", holiday, "trade_date=2026-09-28")

    trade_date, prices = read_latest_prices(lakehouse)

    assert trade_date == "2026-09-25"
    assert prices["market_cap"].gt(0).all()
    assert ConsensusService(settings, provider=FakeWiseReport()).select_universe()["ticker"].tolist() == [
        "005930", "247540", "000020",
    ]


def test_update_writes_snapshot_raw_and_run_record(settings):
    provider = FakeWiseReport()
    result = ConsensusService(settings, provider=provider).update(date(2026, 9, 26))

    assert result.published is True
    assert result.base_year == 2026
    assert result.universe_size == 3
    assert result.failure_rate == 0.0
    # 동화약품 has no 2028 estimate, so its company page is never requested.
    assert provider.profile_calls == ["005930", "247540"]

    lakehouse = Lakehouse(settings)
    estimates, profiles = read_snapshot(lakehouse, "2026-09-26")
    assert set(estimates["ticker"]) == {"005930", "247540", "000020"}
    assert profiles.set_index("ticker")["sector"].to_dict() == {"005930": "반도체와반도체장비", "247540": "전기제품"}
    assert (profiles["profile_source"] == "crawled").all()
    assert list((settings.raw_dir / CONSENSUS_DATASET / "snapshot_date=2026-09-26").rglob("*.parquet"))
    assert list((settings.raw_dir / PROFILE_DATASET / "snapshot_date=2026-09-26").rglob("*.parquet"))

    record = json.loads((settings.metadata_dir / "ingestion_runs" / f"{result.run_id}.json").read_text(encoding="utf-8"))
    assert record["kind"] == "consensus"
    assert record["status"] == "completed"
    assert record["failure_rate"] == 0.0
    assert record["published"] is True
    assert latest_published_snapshot(lakehouse) == "2026-09-26"


def test_second_snapshot_adds_partition_without_touching_the_first(settings):
    ConsensusService(settings, provider=FakeWiseReport()).update(date(2026, 9, 19))
    lakehouse = Lakehouse(settings)
    first_file = settings.curated_dir / CONSENSUS_DATASET / "snapshot_date=2026-09-19" / "part-000.parquet"
    first_bytes = first_file.read_bytes()

    ConsensusService(settings, provider=FakeWiseReport()).update(date(2026, 9, 26))

    assert lakehouse.list_curated_partitions(CONSENSUS_DATASET) == ["snapshot_date=2026-09-19", "snapshot_date=2026-09-26"]
    assert first_file.read_bytes() == first_bytes
    assert latest_published_snapshot(lakehouse) == "2026-09-26"


def test_failure_rate_above_threshold_withholds_snapshot(settings):
    ConsensusService(settings, provider=FakeWiseReport()).update(date(2026, 9, 19))
    result = ConsensusService(settings, provider=FakeWiseReport(fail_consensus={"247540"})).update(date(2026, 9, 26))

    assert result.consensus_failed == 1
    assert result.failure_rate > settings.consensus_max_failure_rate
    assert result.published is False
    lakehouse = Lakehouse(settings)
    assert lakehouse.curated_partition_exists(CONSENSUS_DATASET, "snapshot_date=2026-09-26")
    assert latest_published_snapshot(lakehouse) == "2026-09-19"
    record = json.loads((settings.metadata_dir / "ingestion_runs" / f"{result.run_id}.json").read_text(encoding="utf-8"))
    assert record["published"] is False
    assert any(issue["check"] == "consensus_fetch" for issue in record["issues"])


def test_failed_rerun_on_same_date_keeps_the_published_snapshot(settings):
    ConsensusService(settings, provider=FakeWiseReport()).update(date(2026, 9, 26))
    partition_file = settings.curated_dir / CONSENSUS_DATASET / "snapshot_date=2026-09-26" / "part-000.parquet"
    published_bytes = partition_file.read_bytes()

    result = ConsensusService(settings, provider=FakeWiseReport(fail_consensus={"247540"})).update(date(2026, 9, 26))

    assert result.published is False
    assert partition_file.read_bytes() == published_bytes
    lakehouse = Lakehouse(settings)
    assert latest_published_snapshot(lakehouse) == "2026-09-26"
    record = json.loads((settings.metadata_dir / "ingestion_runs" / f"{result.run_id}.json").read_text(encoding="utf-8"))
    assert record["status"] == "withheld"
    assert record["rows_written"] == 0
    assert list((settings.raw_dir / CONSENSUS_DATASET / "snapshot_date=2026-09-26").glob(f"run_id={result.run_id}"))


def test_snapshot_without_parsable_estimates_is_not_published(settings):
    ConsensusService(settings, provider=FakeWiseReport()).update(date(2026, 9, 19))
    result = ConsensusService(settings, provider=FakeWiseReport(period_suffix="E")).update(date(2026, 9, 26))

    assert result.failure_rate == 0.0
    assert result.base_year is None
    assert result.published is False
    assert latest_published_snapshot(Lakehouse(settings)) == "2026-09-19"


def test_profile_failure_carries_forward_previous_sector_and_dividend(settings):
    ConsensusService(settings, provider=FakeWiseReport()).update(date(2026, 9, 19))
    result = ConsensusService(settings, provider=FakeWiseReport(fail_profile={"005930"})).update(date(2026, 9, 26))

    assert result.published is True
    assert result.profile_failed == 1
    _, profiles = read_snapshot(Lakehouse(settings), "2026-09-26")
    samsung = profiles.set_index("ticker").loc["005930"]
    assert samsung["sector"] == "반도체와반도체장비"
    assert samsung["dividend_yield"] == 0.58
    assert samsung["profile_source"] == "carried_forward"
    assert samsung["profile_as_of"] == "2026-09-19"
    assert profiles.set_index("ticker").loc["247540", "profile_source"] == "crawled"


def test_profile_failure_without_history_is_recorded_as_missing(settings):
    ConsensusService(settings, provider=FakeWiseReport(fail_profile={"247540"})).update(date(2026, 9, 26))
    _, profiles = read_snapshot(Lakehouse(settings), "2026-09-26")
    ecopro = profiles.set_index("ticker").loc["247540"]
    assert pd.isna(ecopro["sector"])
    assert ecopro["profile_source"] == "missing"


def test_cli_consensus_update_writes_snapshot(settings, monkeypatch):
    monkeypatch.setattr(consensus_module, "WiseReportProvider", FakeWiseReport)
    result = CliRunner().invoke(
        app,
        ["consensus", "update", "--limit", "3", "--snapshot-date", "2026-09-26", "--data-dir", str(settings.data_dir)],
    )
    assert result.exit_code == 0, result.output
    assert "게시" in result.output
    assert Lakehouse(settings).curated_partition_exists(CONSENSUS_DATASET, "snapshot_date=2026-09-26")
    manifest = json.loads((settings.metadata_dir / "consensus_snapshots" / "2026-09-26.json").read_text(encoding="utf-8"))
    assert manifest["published"] is True
    assert "failure_rate" in manifest


# --- scheduler ---------------------------------------------------------------


def test_scheduler_registers_weekly_consensus_job(tmp_path):
    settings = Settings(data_dir=tmp_path, consensus_schedule_day="sun", consensus_schedule_hour=7)
    scheduler = build_scheduler(settings)
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"daily-update", "consensus-weekly"}
    fields = {field.name: str(field) for field in jobs["consensus-weekly"].trigger.fields}
    assert fields["day_of_week"] == "sun"
    assert fields["hour"] == "7"
    assert fields["minute"] == "0"
