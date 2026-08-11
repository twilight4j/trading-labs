from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

_ENV_LOADED = False


def load_environment() -> None:
    """Load `.env` once for KRX_ID/KRX_PW and DART_API_KEY."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path, override=False)
    else:
        load_dotenv(override=False)
    _ENV_LOADED = True


def require_krx_credentials() -> None:
    load_environment()
    if not os.getenv("KRX_ID") or not os.getenv("KRX_PW"):
        raise RuntimeError(
            "KRX 로그인이 필요합니다. `.env`에 KRX_ID/KRX_PW를 설정하거나 "
            "환경변수로 제공하세요. 예시는 `.env.example`을 참고하세요."
        )


def require_dart_api_key() -> str:
    load_environment()
    key = os.getenv("DART_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "DART API 키가 필요합니다. `.env`에 DART_API_KEY를 설정하거나 "
            "환경변수로 제공하세요. 예시는 `.env.example`을 참고하세요."
        )
    return key


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data/market-data")
    markets: tuple[str, ...] = ("KOSPI", "KOSDAQ")
    schedule_hour: int = 18
    schedule_minute: int = 30
    timezone: str = "Asia/Seoul"
    dart_request_interval: float = 0.15
    dart_reprt_codes: tuple[str, ...] = ("11011", "11012", "11013", "11014")

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def curated_dir(self) -> Path:
        return self.data_dir / "curated"

    @property
    def metadata_dir(self) -> Path:
        return self.data_dir / "metadata"
