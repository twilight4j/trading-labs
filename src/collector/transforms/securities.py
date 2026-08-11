from __future__ import annotations

import pandas as pd


EXCLUDED_KEYWORDS = ("ETF", "ETN", "REIT", "리츠", "스팩", "SPAC", "우선주", "우B", "우C")


def _pick(frame: pd.DataFrame, *names: str) -> pd.Series:
    for name in names:
        if name in frame.columns:
            return frame[name]
    return pd.Series(pd.NA, index=frame.index)


def normalize_security_master(frame: pd.DataFrame, source: str) -> pd.DataFrame:
    code = _pick(frame, "Code", "Symbol", "종목코드", "단축코드").astype("string").str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
    name = _pick(frame, "Name", "종목명", "한글 종목약명").astype("string")
    market = _pick(frame, "Market", "Market Id", "시장구분").astype("string").str.upper()
    result = pd.DataFrame({
        "security_id": "KRX:" + code,
        "ticker": code,
        "name": name,
        "market": market,
        "dart_corp_code": pd.Series(pd.NA, index=frame.index, dtype="string"),
        "source": source,
    }).dropna(subset=["ticker"])
    text = (result["name"].fillna("") + " " + result["market"].fillna("")).str.upper()
    result["security_type"] = "COMMON"
    result["exclusion_reason"] = pd.NA
    for keyword in EXCLUDED_KEYWORDS:
        mask = text.str.contains(keyword.upper(), regex=False)
        result.loc[mask, "security_type"] = "EXCLUDED"
        result.loc[mask, "exclusion_reason"] = keyword
    result.loc[~result["market"].isin(["KOSPI", "KOSDAQ"]), "exclusion_reason"] = "outside_target_market"
    return result.drop_duplicates("security_id", keep="last")
