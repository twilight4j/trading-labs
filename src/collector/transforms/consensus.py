from __future__ import annotations

import html
import re

import pandas as pd

CONSENSUS_COLUMNS = [
    "security_id",
    "ticker",
    "fiscal_period",
    "fiscal_year",
    "is_estimate",
    "net_income_controlling",
    "fs_basis",
]

_PERIOD = re.compile(r"^(\d{4})\.(\d{2})\((A|E)\)$")
_WICS = re.compile(r"WICS\s*:\s*(.+?)\s+(?:EPS|BPS|PER)\b")
_DIVIDEND = re.compile(r"현금배당수익률\s+(-?\d+(?:\.\d+)?)\s*%")


def _parse_amount(value: object) -> float | None:
    text = str(value if value is not None else "").replace(",", "").strip()
    if text in {"", "-", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_consensus(payload: dict, *, security_id: str, ticker: str) -> pd.DataFrame:
    """Annual consensus rows from WiseReport v3 `c1050001_data.aspx?flag=2`.

    `NP` is controlling-interest net income in 억원; an empty string means no estimate.
    """
    rows = []
    for item in payload.get("JsonData") or []:
        match = _PERIOD.match(str(item.get("YYMM", "")).strip())
        if not match:
            continue
        year, month, kind = match.groups()
        rows.append(
            {
                "security_id": security_id,
                "ticker": ticker,
                "fiscal_period": f"{year}{month}",
                "fiscal_year": int(year),
                "is_estimate": kind == "E",
                "net_income_controlling": _parse_amount(item.get("NP")),
                "fs_basis": item.get("MAIN"),
            }
        )
    frame = pd.DataFrame(rows, columns=CONSENSUS_COLUMNS)
    frame["net_income_controlling"] = frame["net_income_controlling"].astype("float64")
    return frame


def _page_text(page: str) -> str:
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body)))


def extract_profile_header(page: str) -> str | None:
    """Header line of WiseReport v2 `c1010001.aspx`, e.g. `WICS : 반도체와반도체장비 … 현금배당수익률 0.58%`."""
    text = _page_text(page)
    start = text.find("WICS :")
    if start < 0:
        return None
    return text[start : start + 300].split("결산")[0].strip()


def parse_company_profile(page: str) -> tuple[str | None, float | None]:
    """Return (WICS sector, cash dividend yield %) from the v2 company page header."""
    header = extract_profile_header(page)
    if header is None:
        return None, None
    sector = _WICS.search(header)
    dividend = _DIVIDEND.search(header)
    return (
        sector.group(1).strip() if sector else None,
        float(dividend.group(1)) if dividend else None,
    )


def infer_base_year(estimates: pd.DataFrame) -> int | None:
    """Most common first-(E) fiscal year across tickers; ties resolve to the earlier year."""
    if estimates.empty:
        return None
    projected = estimates.loc[estimates["is_estimate"].astype(bool)]
    if projected.empty:
        return None
    counts = projected.groupby("ticker")["fiscal_year"].min().value_counts()
    return int(min(counts[counts == counts.max()].index))
