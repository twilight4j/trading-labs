from __future__ import annotations

from datetime import date

import pandas as pd

from collector.config import load_environment, require_krx_credentials

from .base import MarketDataProvider


class PykrxProvider(MarketDataProvider):
    name = "pykrx"

    @staticmethod
    def _stock():
        # pykrx logs in at import time using KRX_ID / KRX_PW.
        load_environment()
        require_krx_credentials()
        try:
            from pykrx import stock
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("pykrx가 설치되지 않았습니다. `uv sync`를 실행하세요.") from exc
        return stock

    def get_daily_prices(self, trade_date: date, market: str) -> pd.DataFrame:
        stock = self._stock()
        day = trade_date.strftime("%Y%m%d")
        prices = stock.get_market_ohlcv_by_ticker(day, market=market).reset_index()
        if prices.empty or not {"시가", "고가", "저가", "종가"}.issubset(prices.columns):
            raise RuntimeError(
                f"pykrx가 {trade_date.isoformat()} {market} 일봉을 반환하지 않았습니다. "
                "KRX 로그인(.env의 KRX_ID/KRX_PW)과 거래일을 확인하세요."
            )
        caps = stock.get_market_cap_by_ticker(day, market=market).reset_index()
        return prices.merge(caps, on="티커", how="left", suffixes=("", "_시총"))

    def get_adjusted_ohlcv(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        """Fetch split/dividend-adjusted OHLCV for one ticker (pykrx by-date API)."""
        if end < start:
            raise ValueError("end는 start 이후여야 합니다.")
        stock = self._stock()
        frame = stock.get_market_ohlcv_by_date(
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
            ticker,
            adjusted=True,
        )
        if frame is None or frame.empty:
            return pd.DataFrame()
        result = frame.reset_index()
        if "티커" not in result.columns:
            result["티커"] = ticker
        return result

    def get_security_master(self) -> pd.DataFrame:
        stock = self._stock()
        frames = []
        for market in ("KOSPI", "KOSDAQ"):
            tickers = stock.get_market_ticker_list(market=market)
            frames.extend({"Code": ticker, "Name": stock.get_market_ticker_name(ticker), "Market": market} for ticker in tickers)
        return pd.DataFrame(frames)
