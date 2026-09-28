"""Offline WiseReport fakes and a seeded market-data lakehouse shared by consensus/valuation tests."""

import json
from pathlib import Path

import pandas as pd

from collector.providers.wisereport import WiseReportError
from collector.storage import Lakehouse

FIXTURES = Path(__file__).parent / "fixtures" / "wisereport"


def consensus_fixture(ticker: str) -> dict:
    return json.loads((FIXTURES / f"consensus_{ticker}.json").read_text(encoding="utf-8"))


def company_fixture(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


EOK = 100_000_000


def seed_market_data(lakehouse: Lakehouse) -> None:
    master = pd.DataFrame(
        {
            "security_id": ["KRX:005930", "KRX:247540", "KRX:000020", "KRX:005935", "KRX:111110", "KRX:222220"],
            "ticker": ["005930", "247540", "000020", "005935", "111110", "222220"],
            "name": ["삼성전자", "에코프로비엠", "동화약품", "삼성전자우", "소형주", "제외종목"],
            # Mirrors the real master: 에코프로비엠 sits in KOSDAQ GLOBAL (flagged outside_target_market)
            # while daily_prices says KOSDAQ, and 삼성전자우 is tagged COMMON.
            "market": ["KOSPI", "KOSDAQ GLOBAL", "KOSPI", "KOSPI", "KOSDAQ", "KOSPI"],
            "source": ["fake"] * 6,
            "security_type": ["COMMON", "COMMON", "COMMON", "COMMON", "COMMON", "EXCLUDED"],
            "exclusion_reason": [None, "outside_target_market", None, None, None, "SPAC"],
            "dart_corp_code": [None] * 6,
        }
    )
    lakehouse.replace_curated_partition("security_master", master, "current")

    def prices(trade_date: str, caps: list[int]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trade_date": pd.Timestamp(trade_date),
                "security_id": master["security_id"],
                "market": ["KOSPI", "KOSDAQ", "KOSPI", "KOSPI", "KOSDAQ", "KOSPI"],
                "close_raw": 1000,
                "market_cap": caps,
                "source": "fake",
            }
        )

    # Older partition: 동화약품 was below the floor; the latest partition must win.
    lakehouse.replace_curated_partition(
        "daily_prices",
        prices("2026-09-24", [16_000_000 * EOK, 100_000 * EOK, 1_000 * EOK, 1_000_000 * EOK, 500 * EOK, 5_000 * EOK]),
        "trade_date=2026-09-24",
    )
    lakehouse.replace_curated_partition(
        "daily_prices",
        prices("2026-09-25", [16_749_588 * EOK, 103_211 * EOK, 2_500 * EOK, 1_000_000 * EOK, 1_199 * EOK, 5_000 * EOK]),
        "trade_date=2026-09-25",
    )


class FakeWiseReport:
    name = "fake_wisereport"

    def __init__(self, *, fail_consensus=(), fail_profile=(), period_suffix=None, **_kwargs):
        self.fail_consensus = set(fail_consensus)
        self.period_suffix = period_suffix
        self.fail_profile = set(fail_profile)
        self.consensus_calls: list[str] = []
        self.profile_calls: list[str] = []

    def fetch_consensus(self, ticker: str) -> dict:
        self.consensus_calls.append(ticker)
        if ticker in self.fail_consensus:
            raise WiseReportError(f"timeout {ticker}")
        payload = consensus_fixture(ticker)
        if self.period_suffix is not None:
            # Simulates a WiseReport format change the parser cannot read (e.g. "2026.12(E)" -> "2026.12E").
            for item in payload["JsonData"]:
                item["YYMM"] = item["YYMM"].replace("(A)", self.period_suffix).replace("(E)", self.period_suffix)
        return payload

    def fetch_company_page(self, ticker: str) -> str:
        self.profile_calls.append(ticker)
        if ticker in self.fail_profile:
            raise WiseReportError(f"blocked {ticker}")
        return company_fixture(f"company_{ticker}")
