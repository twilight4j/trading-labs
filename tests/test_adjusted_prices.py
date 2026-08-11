from datetime import date

import pandas as pd

from collector.config import Settings
from collector.ingestion.adjusted import AdjustedPricesService
from collector.providers.base import MarketDataProvider
from collector.storage import Lakehouse
from collector.transforms.prices import normalize_adjusted_ohlcv, overlay_adjusted_prices


class FakeAdjustedProvider(MarketDataProvider):
    name = "fake_adjusted"

    def get_daily_prices(self, trade_date: date, market: str) -> pd.DataFrame:
        raise NotImplementedError

    def get_security_master(self) -> pd.DataFrame:
        return pd.DataFrame()

    def get_adjusted_ohlcv(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        assert ticker == "005930"
        return pd.DataFrame(
            {
                "날짜": pd.to_datetime(["2024-01-02", "2024-01-03"]),
                "시가": [100.0, 110.0],
                "고가": [105.0, 115.0],
                "저가": [95.0, 105.0],
                "종가": [102.0, 112.0],
            }
        )


def test_normalize_adjusted_ohlcv_filters_zero_rows() -> None:
    frame = pd.DataFrame(
        {
            "날짜": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "시가": [0.0, 100.0],
            "고가": [0.0, 110.0],
            "저가": [0.0, 90.0],
            "종가": [0.0, 105.0],
        }
    )
    result = normalize_adjusted_ohlcv(frame, "5930", "fake")
    assert len(result) == 1
    assert result.iloc[0]["security_id"] == "KRX:005930"
    assert float(result.iloc[0]["close"]) == 105.0


def test_overlay_adjusted_prices_updates_only_matching_rows() -> None:
    curated = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-02"]),
            "security_id": ["KRX:005930", "KRX:000660"],
            "market": ["KOSPI", "KOSPI"],
            "open_raw": [1000.0, 2000.0],
            "high_raw": [1000.0, 2000.0],
            "low_raw": [1000.0, 2000.0],
            "close_raw": [1000.0, 2000.0],
            "open_adjusted": [pd.NA, 20.0],
            "high_adjusted": [pd.NA, 20.0],
            "low_adjusted": [pd.NA, 20.0],
            "close_adjusted": [pd.NA, 20.0],
            "adjustment_as_of": [pd.NaT, pd.Timestamp("2024-01-01")],
        }
    )
    adjusted = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2024-01-02"]),
            "security_id": ["KRX:005930"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
        }
    )
    merged = overlay_adjusted_prices(curated, adjusted, date(2024, 6, 1))
    samsung = merged.loc[merged["security_id"] == "KRX:005930"].iloc[0]
    other = merged.loc[merged["security_id"] == "KRX:000660"].iloc[0]
    assert float(samsung["close_adjusted"]) == 10.5
    assert pd.Timestamp(samsung["adjustment_as_of"]) == pd.Timestamp("2024-06-01")
    assert float(other["close_adjusted"]) == 20.0


def test_rebuild_adjusted_writes_curated_columns(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    lakehouse = Lakehouse(settings)
    for day, close_raw in (("2024-01-02", 1000.0), ("2024-01-03", 1100.0)):
        frame = pd.DataFrame(
            {
                "trade_date": [pd.Timestamp(day)],
                "security_id": ["KRX:005930"],
                "market": ["KOSPI"],
                "open_raw": [close_raw],
                "high_raw": [close_raw],
                "low_raw": [close_raw],
                "close_raw": [close_raw],
                "volume": [1],
                "trading_value": [close_raw],
                "market_cap": [1],
                "source": ["fake"],
                "open_adjusted": [pd.NA],
                "high_adjusted": [pd.NA],
                "low_adjusted": [pd.NA],
                "close_adjusted": [pd.NA],
                "adjustment_as_of": [pd.NaT],
            }
        )
        lakehouse.replace_curated_partition("daily_prices", frame, f"trade_date={day}")

    run = AdjustedPricesService(settings, FakeAdjustedProvider()).rebuild(
        date(2024, 1, 2),
        date(2024, 1, 3),
        security_ids=["KRX:005930"],
    )
    assert run.status == "completed"
    prices = lakehouse.read_curated("daily_prices").sort_values("trade_date")
    assert list(prices["close_adjusted"].astype(float)) == [102.0, 112.0]
    assert prices["adjustment_as_of"].notna().all()
