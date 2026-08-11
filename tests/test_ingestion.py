from datetime import date

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
