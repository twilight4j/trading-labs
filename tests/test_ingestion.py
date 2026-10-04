import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from collector.config import Settings
from collector.ingestion import IngestionService
from collector.providers.base import MarketDataProvider
from collector.storage import Lakehouse


class FakePriceProvider(MarketDataProvider):
    name = "fake"

    def get_daily_prices(self, trade_date: date, market: str) -> pd.DataFrame:
        ticker = "005930" if market == "KOSPI" else "035420"
        return pd.DataFrame({"티커": [ticker], "시가": [100], "고가": [110], "저가": [90], "종가": [105], "거래량": [1000], "거래대금": [105000], "시가총액": [1_000_000]})

    def get_security_master(self) -> pd.DataFrame:
        return pd.DataFrame()


class FakeMetadataProvider(MarketDataProvider):
    name = "fake_metadata"

    def get_daily_prices(self, *args, **kwargs) -> pd.DataFrame:
        raise NotImplementedError

    def get_security_master(self) -> pd.DataFrame:
        return pd.DataFrame({"Code": ["005930", "035420"], "Name": ["삼성전자", "NAVER"], "Market": ["KOSPI", "KOSDAQ"]})


def test_ingestion_writes_curated_prices_and_universe(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    service = IngestionService(settings, FakePriceProvider(), FakeMetadataProvider())
    run = service.ingest_day(date(2024, 1, 2))
    lakehouse = Lakehouse(settings)
    assert run.status == "completed"
    assert len(lakehouse.read_curated("daily_prices")) == 2
    assert lakehouse.read_curated("universe_snapshot")["eligible"].all()


class HolidayAwareProvider(FakePriceProvider):
    """pykrx answers a market holiday with every stock at zero volume and market cap."""

    def __init__(self, holidays: set[date]):
        self.holidays = holidays
        self.asked: list[date] = []

    def get_daily_prices(self, trade_date: date, market: str) -> pd.DataFrame:
        if market == "KOSPI":
            self.asked.append(trade_date)
        frame = super().get_daily_prices(trade_date, market)
        if trade_date in self.holidays:
            frame[["시가", "고가", "저가", "종가", "거래량", "거래대금", "시가총액"]] = 0
        return frame


def _service(tmp_path, holidays=()) -> tuple[IngestionService, Lakehouse, HolidayAwareProvider]:
    settings = Settings(data_dir=tmp_path / "data")
    provider = HolidayAwareProvider(set(holidays))
    return IngestionService(settings, provider, FakeMetadataProvider()), Lakehouse(settings), provider


def _runs(lakehouse: Lakehouse) -> list[dict]:
    directory = lakehouse.settings.metadata_dir / "ingestion_runs"
    return [json.loads(file.read_text(encoding="utf-8")) for file in directory.glob("*.json")] if directory.exists() else []


def test_a_market_holiday_is_not_stored(tmp_path) -> None:
    service, lakehouse, _ = _service(tmp_path, holidays=[date(2026, 9, 24)])

    run = service.ingest_day(date(2026, 9, 24))

    assert run.status == "skipped"
    assert "2026-09-24" in run.message
    assert lakehouse.list_curated_partitions("daily_prices") == []
    assert not (lakehouse.settings.raw_dir / "daily_prices").exists()


def test_catch_up_fills_every_missing_weekday_and_skips_holidays(tmp_path) -> None:
    service, lakehouse, provider = _service(tmp_path, holidays=[date(2026, 10, 5)])
    service.ingest_day(date(2026, 10, 2))  # Friday
    provider.asked.clear()

    runs = service.catch_up(date(2026, 10, 7))  # Wednesday; Monday 10-05 is a substitute holiday

    assert provider.asked == [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)]  # the weekend is not asked
    assert [run.status for run in runs] == ["completed", "completed"]
    assert lakehouse.list_curated_partitions("daily_prices") == [
        "trade_date=2026-10-02", "trade_date=2026-10-06", "trade_date=2026-10-07",
    ]
    assert sorted(run["trade_date"] for run in _runs(lakehouse)) == ["2026-10-02", "2026-10-06", "2026-10-07"]
    assert service.catch_up(date(2026, 10, 7)) == []  # up to date


def test_catch_up_records_one_skipped_run_when_holidays_were_all_there_was(tmp_path) -> None:
    service, lakehouse, _ = _service(tmp_path, holidays=[date(2026, 9, 24), date(2026, 9, 25)])
    service.ingest_day(date(2026, 9, 23))

    assert service.catch_up(date(2026, 9, 25)) == []

    skipped = [run for run in _runs(lakehouse) if run["status"] == "skipped"]
    assert len(skipped) == 1
    assert skipped[0]["message"] == "휴장일(거래 없음): 2026-09-24, 2026-09-25"
    assert lakehouse.list_curated_partitions("daily_prices") == ["trade_date=2026-09-23"]


def test_update_returns_the_last_stored_day(tmp_path) -> None:
    service, _, _ = _service(tmp_path)
    service.ingest_day(date(2026, 10, 1))
    assert service.update(date(2026, 10, 2)).status == "completed"
    assert service.update(date(2026, 10, 2)) is None


def test_today_counts_only_after_the_daily_schedule_time(tmp_path) -> None:
    service, _, _ = _service(tmp_path)
    kst = ZoneInfo("Asia/Seoul")
    assert service.settled_date(datetime(2026, 10, 6, 11, 0, tzinfo=kst)) == date(2026, 10, 5)   # intraday values
    assert service.settled_date(datetime(2026, 10, 6, 18, 30, tzinfo=kst)) == date(2026, 10, 6)
