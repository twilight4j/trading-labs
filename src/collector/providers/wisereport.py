from __future__ import annotations

import time

import requests


class WiseReportError(RuntimeError):
    """WiseReport request failed after retries or returned an unusable body."""


class WiseReportProvider:
    """Client for the WiseReport pages embedded in Naver Securities (stock.naver.com).

    - Consensus: v3 `c1050001_data.aspx?flag=2` (the 컨센서스 tab's annual JSON).
    - Company header (WICS sector, 현금배당수익률): legacy v2 `c1010001.aspx`.
    """

    name = "wisereport"
    base_url = "https://navercomp.wisereport.co.kr"
    user_agent = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    )

    def __init__(
        self,
        request_interval: float = 0.3,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        timeout: float = 15.0,
        session: requests.Session | None = None,
    ):
        self.request_interval = request_interval
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.request_interval:
            time.sleep(self.request_interval - elapsed)
        self._last_request_at = time.monotonic()

    def _get(self, path: str, params: dict) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                response = self.session.get(f"{self.base_url}/{path}", params=params, timeout=self.timeout)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff * attempt)
        raise WiseReportError(f"WiseReport {path} {params} failed after {self.max_retries} attempts: {last_error}")

    def fetch_consensus(self, ticker: str) -> dict:
        response = self._get(
            "v3/company/ajax/c1050001_data.aspx",
            {"flag": "2", "cmp_cd": ticker, "finGubun": "MAIN", "frq": "0"},
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise WiseReportError(f"WiseReport consensus for {ticker} is not JSON") from exc
        if not isinstance(payload, dict) or "JsonData" not in payload:
            raise WiseReportError(f"WiseReport consensus for {ticker} has no JsonData")
        return payload

    def fetch_company_page(self, ticker: str) -> str:
        response = self._get("v2/company/c1010001.aspx", {"cmp_cd": ticker})
        response.encoding = "utf-8"
        return response.text
