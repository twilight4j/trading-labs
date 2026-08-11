from datetime import date

import pandas as pd

from collector.quality import validate_prices
from collector.transforms import build_universe, normalize_prices, normalize_security_master


def test_normalizes_korean_price_columns() -> None:
    source = pd.DataFrame({"티커": ["5930"], "시가": [70000], "고가": [71000], "저가": [69000], "종가": [70500], "거래량": [100], "거래대금": [7_000_000], "시가총액": [420]})
    result = normalize_prices(source, date(2024, 1, 2), "KOSPI", "pykrx", adjusted=False)
    assert result.loc[0, "security_id"] == "KRX:005930"
    assert result.loc[0, "close"] == 70500


def test_quality_quarantines_invalid_ohlc() -> None:
    prices = pd.DataFrame({"trade_date": ["2024-01-02"], "security_id": ["KRX:005930"], "open": [100], "high": [90], "low": [95], "close": [100], "volume": [1]})
    valid, issues = validate_prices(prices)
    assert valid.empty
    assert issues[0].check == "ohlc_range"


def test_universe_excludes_etf() -> None:
    source = pd.DataFrame({"Code": ["005930", "069500"], "Name": ["삼성전자", "KODEX 200 ETF"], "Market": ["KOSPI", "KOSPI"]})
    master = normalize_security_master(source, "fdr")
    prices = pd.DataFrame({"security_id": ["KRX:005930", "KRX:069500"], "market": ["KOSPI", "KOSPI"]})
    universe = build_universe(prices, master, date(2024, 1, 2))
    assert universe.loc[universe.security_id == "KRX:005930", "eligible"].item()
    assert not universe.loc[universe.security_id == "KRX:069500", "eligible"].item()
