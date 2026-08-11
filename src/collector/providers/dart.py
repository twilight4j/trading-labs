from __future__ import annotations

import io
import time
import zipfile
from datetime import date
from xml.etree import ElementTree

import pandas as pd
import requests

from collector.config import require_dart_api_key


class DartQuotaExceeded(RuntimeError):
    """OpenDART daily request quota exceeded (status 020)."""

    def __init__(self, message: str, *, completed_runs: list | None = None):
        super().__init__(message)
        self.completed_runs = completed_runs or []


class DartProvider:
    """OpenDART client for corp codes and single-company major accounts."""

    name = "dart"
    base_url = "https://opendart.fss.or.kr/api"

    def __init__(self, api_key: str | None = None, request_interval: float = 0.15):
        self.api_key = api_key or require_dart_api_key()
        self.request_interval = request_interval
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.request_interval:
            time.sleep(self.request_interval - elapsed)
        self._last_request_at = time.monotonic()

    @staticmethod
    def _raise_for_status(path: str, status: str, message: str) -> None:
        if status == "020":
            raise DartQuotaExceeded(f"OpenDART {path} failed ({status}): {message}")
        raise RuntimeError(f"OpenDART {path} failed ({status}): {message}")

    def _get(self, path: str, params: dict | None = None, *, expect_json: bool = True) -> requests.Response:
        self._throttle()
        query = {"crtfc_key": self.api_key, **(params or {})}
        response = requests.get(f"{self.base_url}/{path}", params=query, timeout=60)
        response.raise_for_status()
        if expect_json:
            payload = response.json()
            status = str(payload.get("status", ""))
            if status and status != "000":
                message = payload.get("message", "unknown OpenDART error")
                self._raise_for_status(path, status, message)
        return response

    def fetch_corp_codes(self) -> pd.DataFrame:
        response = self._get("corpCode.xml", expect_json=False)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            xml_name = next(name for name in archive.namelist() if name.lower().endswith(".xml"))
            root = ElementTree.fromstring(archive.read(xml_name))
        rows = []
        for node in root.findall("list"):
            stock_code = (node.findtext("stock_code") or "").strip()
            rows.append(
                {
                    "corp_code": (node.findtext("corp_code") or "").strip(),
                    "corp_name": (node.findtext("corp_name") or "").strip(),
                    "stock_code": stock_code.zfill(6) if stock_code.isdigit() else stock_code,
                    "modify_date": (node.findtext("modify_date") or "").strip(),
                }
            )
        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame
        listed = frame["stock_code"].astype("string").str.fullmatch(r"\d{6}", na=False)
        return frame.loc[listed].drop_duplicates("stock_code", keep="last").reset_index(drop=True)

    def fetch_accounts(self, corp_code: str, bsns_year: int | str, reprt_code: str, *, fs_div: str = "CFS") -> pd.DataFrame:
        """Return major accounts for one company/year/report. Empty if no data (status 013)."""
        self._throttle()
        query = {
            "crtfc_key": self.api_key,
            "corp_code": corp_code,
            "bsns_year": str(bsns_year),
            "reprt_code": reprt_code,
            "fs_div": fs_div,
        }
        response = requests.get(f"{self.base_url}/fnlttSinglAcntAll.json", params=query, timeout=60)
        response.raise_for_status()
        payload = response.json()
        status = str(payload.get("status", ""))
        if status == "013":
            return pd.DataFrame()
        if status != "000":
            message = payload.get("message", "unknown OpenDART error")
            self._raise_for_status("fnlttSinglAcntAll", status, message)
        rows = payload.get("list") or []
        if not rows:
            return pd.DataFrame()
        frame = pd.DataFrame(rows)
        frame["requested_fs_div"] = fs_div
        frame["bsns_year"] = str(bsns_year)
        frame["reprt_code"] = reprt_code
        frame["corp_code"] = corp_code
        return frame

    def fetch_accounts_prefer_cfs(self, corp_code: str, bsns_year: int | str, reprt_code: str) -> pd.DataFrame:
        frame = self.fetch_accounts(corp_code, bsns_year, reprt_code, fs_div="CFS")
        if not frame.empty:
            return frame
        return self.fetch_accounts(corp_code, bsns_year, reprt_code, fs_div="OFS")

    def get_daily_prices(self, trade_date: date, market: str) -> pd.DataFrame:  # pragma: no cover - not a price provider
        raise NotImplementedError("DartProvider does not supply daily prices.")

    def get_security_master(self) -> pd.DataFrame:  # pragma: no cover
        return self.fetch_corp_codes().rename(columns={"stock_code": "Code", "corp_name": "Name"})
