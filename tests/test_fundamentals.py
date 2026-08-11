import pandas as pd
import pytest

from collector.config import Settings
from collector.ingestion.fundamentals import FundamentalsService
from collector.providers.dart import DartQuotaExceeded
from collector.storage import Lakehouse
from collector.transforms.fundamentals import (
    attach_dart_corp_codes,
    attach_latest_fundamentals,
    normalize_fundamentals_accounts,
    prefer_cfs_accounts,
)


class FakeDartProvider:
    name = "fake_dart"

    def fetch_corp_codes(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "corp_code": ["00126380", "00164779"],
                "corp_name": ["삼성전자", "NAVER"],
                "stock_code": ["005930", "035420"],
                "modify_date": ["20240101", "20240101"],
            }
        )

    def fetch_accounts_prefer_cfs(self, corp_code: str, bsns_year: int | str, reprt_code: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "corp_code": [corp_code, corp_code],
                "bsns_year": [str(bsns_year), str(bsns_year)],
                "reprt_code": [reprt_code, reprt_code],
                "fs_div": ["CFS", "CFS"],
                "account_id": ["ifrs-full_Revenue", "dart_OperatingIncomeLoss"],
                "account_nm": ["매출액", "영업이익"],
                "thstrm_amount": ["1000", "200"],
                "frmtrm_amount": ["900", "180"],
                "currency": ["KRW", "KRW"],
                "rcept_no": ["20240301000001", "20240301000001"],
            }
        )


class CountingDartProvider(FakeDartProvider):
    def __init__(self) -> None:
        self.calls = 0

    def fetch_accounts_prefer_cfs(self, corp_code: str, bsns_year: int | str, reprt_code: str) -> pd.DataFrame:
        self.calls += 1
        return super().fetch_accounts_prefer_cfs(corp_code, bsns_year, reprt_code)


class QuotaDartProvider(FakeDartProvider):
    """Succeeds for the first N prefer_cfs calls, then raises DartQuotaExceeded."""

    def __init__(self, succeed_calls: int) -> None:
        self.succeed_calls = succeed_calls
        self.calls = 0

    def fetch_accounts_prefer_cfs(self, corp_code: str, bsns_year: int | str, reprt_code: str) -> pd.DataFrame:
        self.calls += 1
        if self.calls > self.succeed_calls:
            raise DartQuotaExceeded("OpenDART fnlttSinglAcntAll failed (020): 사용한도를 초과하였습니다.")
        return super().fetch_accounts_prefer_cfs(corp_code, bsns_year, reprt_code)


def _write_master(lakehouse: Lakehouse, *, with_codes: bool = True) -> None:
    master = pd.DataFrame(
        {
            "security_id": ["KRX:005930", "KRX:035420"],
            "ticker": ["005930", "035420"],
            "name": ["삼성전자", "NAVER"],
            "market": ["KOSPI", "KOSDAQ"],
            "dart_corp_code": ["00126380", "00164779"] if with_codes else [pd.NA, pd.NA],
            "source": ["fake", "fake"],
            "security_type": ["COMMON", "COMMON"],
            "exclusion_reason": [pd.NA, pd.NA],
        }
    )
    lakehouse.replace_curated_partition("security_master", master, "current")


def test_attach_dart_corp_codes() -> None:
    securities = pd.DataFrame(
        {
            "security_id": ["KRX:005930", "KRX:035420"],
            "ticker": ["005930", "035420"],
            "name": ["삼성전자", "NAVER"],
            "dart_corp_code": [pd.NA, pd.NA],
        }
    )
    corp_codes = FakeDartProvider().fetch_corp_codes()
    result = attach_dart_corp_codes(securities, corp_codes)
    assert result.set_index("ticker").loc["005930", "dart_corp_code"] == "00126380"


def test_normalize_and_prefer_cfs() -> None:
    raw = FakeDartProvider().fetch_accounts_prefer_cfs("00126380", 2024, "11011")
    ofs = raw.copy()
    ofs["fs_div"] = "OFS"
    ofs["thstrm_amount"] = ["1", "2"]
    mixed = pd.concat([raw, ofs], ignore_index=True)
    normalized = normalize_fundamentals_accounts(mixed, security_id="KRX:005930")
    preferred = prefer_cfs_accounts(normalized)
    assert len(preferred) == 2
    assert (preferred["fs_div"] == "CFS").all()
    assert preferred.loc[preferred["account_nm"] == "매출액", "thstrm_amount"].iloc[0] == 1000


def test_fundamentals_service_writes_curated(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", dart_reprt_codes=("11011",))
    lakehouse = Lakehouse(settings)
    _write_master(lakehouse, with_codes=False)
    service = FundamentalsService(settings, FakeDartProvider())
    enriched = service.sync_corp_codes()
    assert enriched["dart_corp_code"].notna().all()
    run = service.ingest_year_report(2024, "11011")
    assert run.status == "completed"
    assert run.rows_written == 4
    curated = lakehouse.read_curated("fundamentals_accounts")
    assert set(curated["account_nm"]) == {"매출액", "영업이익"}


def test_fundamentals_update_respects_limit(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", dart_reprt_codes=("11011",))
    lakehouse = Lakehouse(settings)
    _write_master(lakehouse)
    runs = FundamentalsService(settings, FakeDartProvider()).update(2024, reprt_codes=("11011",), limit=1)
    assert len(runs) == 1
    assert runs[0].rows_written == 2
    curated = lakehouse.read_curated("fundamentals_accounts")
    assert curated["security_id"].nunique() == 1


def test_backfill_skips_existing_partitions(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", dart_reprt_codes=("11011", "11012"))
    lakehouse = Lakehouse(settings)
    _write_master(lakehouse)
    provider = CountingDartProvider()
    service = FundamentalsService(settings, provider)
    first = service.backfill(2024, 2024, skip_existing=True)
    assert len(first) == 2
    calls_after_first = provider.calls
    second = service.backfill(2024, 2024, skip_existing=True)
    assert second == []
    assert provider.calls == calls_after_first


def test_backfill_stops_on_quota_and_keeps_completed(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", dart_reprt_codes=("11011", "11012"))
    lakehouse = Lakehouse(settings)
    _write_master(lakehouse)
    # 2 securities × 1 report = 2 calls succeed → first partition completes; next partition hits quota
    provider = QuotaDartProvider(succeed_calls=2)
    service = FundamentalsService(settings, provider)
    with pytest.raises(DartQuotaExceeded) as exc_info:
        service.backfill(2024, 2024, skip_existing=True)
    assert len(exc_info.value.completed_runs) == 1
    assert lakehouse.curated_partition_exists("fundamentals_accounts", "bsns_year=2024/reprt_code=11011")
    assert not lakehouse.curated_partition_exists("fundamentals_accounts", "bsns_year=2024/reprt_code=11012")


def test_attach_latest_fundamentals() -> None:
    prices = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2024-12-31")],
            "security_id": ["KRX:005930"],
            "close_raw": [70000],
        }
    )
    accounts = normalize_fundamentals_accounts(
        FakeDartProvider().fetch_accounts_prefer_cfs("00126380", 2024, "11011"),
        security_id="KRX:005930",
    )
    joined = attach_latest_fundamentals(prices, accounts)
    assert joined.loc[0, "fundamentals_bsns_year"] == "2024"
    assert joined.loc[0, "acct_매출액"] == 1000
