from __future__ import annotations

import pandas as pd

from .base import MarketDataProvider


class FdrProvider(MarketDataProvider):
    name = "fdr"

    @staticmethod
    def _fdr():
        try:
            import FinanceDataReader as fdr
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("FinanceDataReader가 설치되지 않았습니다. `uv sync`를 실행하세요.") from exc
        return fdr

    def get_daily_prices(self, *args, **kwargs) -> pd.DataFrame:
        raise NotImplementedError("FDR은 이 프로젝트에서 보조 메타데이터 공급자입니다.")

    def get_security_master(self) -> pd.DataFrame:
        return self._fdr().StockListing("KRX")

    def get_delistings(self) -> pd.DataFrame:
        return self._fdr().StockListing("KRX-DELISTING")
