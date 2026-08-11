from __future__ import annotations

import pandas as pd


REPRT_PERIOD_END_MONTH = {
    "11013": 3,  # Q1
    "11012": 6,  # half-year
    "11014": 9,  # Q3
    "11011": 12,  # annual
}


def _to_numeric_amount(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.replace(",", "", regex=False)
    return pd.to_numeric(cleaned, errors="coerce")


def attach_dart_corp_codes(securities: pd.DataFrame, corp_codes: pd.DataFrame) -> pd.DataFrame:
    """Map ticker (6-digit) to OpenDART corp_code via stock_code."""
    if securities.empty:
        return securities.copy()
    mapping = corp_codes[["stock_code", "corp_code"]].drop_duplicates("stock_code", keep="last")
    mapping = mapping.rename(columns={"stock_code": "ticker", "corp_code": "dart_corp_code"})
    mapping["ticker"] = mapping["ticker"].astype("string").str.zfill(6)
    result = securities.copy()
    result["ticker"] = result["ticker"].astype("string").str.zfill(6)
    if "dart_corp_code" in result.columns:
        result = result.drop(columns=["dart_corp_code"])
    return result.merge(mapping, on="ticker", how="left")


def normalize_fundamentals_accounts(frame: pd.DataFrame, *, security_id: str, source: str = "dart") -> pd.DataFrame:
    """Map OpenDART major-account rows into the curated long schema."""
    columns = [
        "security_id",
        "dart_corp_code",
        "bsns_year",
        "reprt_code",
        "fs_div",
        "account_id",
        "account_nm",
        "thstrm_amount",
        "frmtrm_amount",
        "currency",
        "rcept_no",
        "source",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    def pick(*names: str) -> pd.Series:
        for name in names:
            if name in frame.columns:
                return frame[name]
        return pd.Series(pd.NA, index=frame.index)

    result = pd.DataFrame(
        {
            "security_id": security_id,
            "dart_corp_code": pick("corp_code").astype("string"),
            "bsns_year": pick("bsns_year").astype("string"),
            "reprt_code": pick("reprt_code").astype("string"),
            "fs_div": pick("fs_div", "requested_fs_div").astype("string"),
            "account_id": pick("account_id").astype("string"),
            "account_nm": pick("account_nm").astype("string"),
            "thstrm_amount": _to_numeric_amount(pick("thstrm_amount")),
            "frmtrm_amount": _to_numeric_amount(pick("frmtrm_amount")),
            "currency": pick("currency").astype("string").fillna("KRW"),
            "rcept_no": pick("rcept_no").astype("string"),
            "source": source,
        }
    )
    return result.dropna(subset=["account_nm"]).reset_index(drop=True)


def prefer_cfs_accounts(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep CFS rows when both CFS and OFS exist for the same keys."""
    if frame.empty or "fs_div" not in frame.columns:
        return frame
    keys = ["security_id", "bsns_year", "reprt_code", "account_nm"]
    ranked = frame.copy()
    ranked["_rank"] = ranked["fs_div"].map({"CFS": 0, "OFS": 1}).fillna(2)
    ranked = ranked.sort_values(keys + ["_rank"])
    return ranked.drop_duplicates(keys, keep="first").drop(columns=["_rank"]).reset_index(drop=True)


def attach_latest_fundamentals(
    prices: pd.DataFrame,
    accounts: pd.DataFrame,
    *,
    as_of_col: str = "trade_date",
) -> pd.DataFrame:
    """Approximate as-of join using fiscal year + report period end (no rcept date yet)."""
    if prices.empty:
        return prices.copy()

    price = prices.copy()
    price["_as_of"] = pd.to_datetime(price[as_of_col])
    if accounts.empty:
        out = price.drop(columns=["_as_of"])
        out["fundamentals_bsns_year"] = pd.NA
        out["fundamentals_reprt_code"] = pd.NA
        return out

    working = accounts.copy()
    working["bsns_year_int"] = pd.to_numeric(working["bsns_year"], errors="coerce")
    working["period_end_month"] = working["reprt_code"].map(REPRT_PERIOD_END_MONTH)
    working = working.dropna(subset=["bsns_year_int", "period_end_month", "security_id", "account_nm"])
    working["period_end"] = pd.to_datetime(
        dict(
            year=working["bsns_year_int"].astype(int),
            month=working["period_end_month"].astype(int),
            day=1,
        )
    ) + pd.offsets.MonthEnd(0)

    report_keys = (
        working[["security_id", "bsns_year", "reprt_code", "period_end"]]
        .drop_duplicates()
        .sort_values(["security_id", "period_end"])
    )
    attached = price[["security_id", as_of_col, "_as_of"]].merge(report_keys, on="security_id", how="left")
    attached = attached.loc[attached["period_end"].isna() | (attached["period_end"] <= attached["_as_of"])]
    latest = (
        attached.sort_values(["security_id", as_of_col, "period_end"])
        .drop_duplicates(["security_id", as_of_col], keep="last")
        .rename(columns={"bsns_year": "fundamentals_bsns_year", "reprt_code": "fundamentals_reprt_code"})
    )[["security_id", as_of_col, "fundamentals_bsns_year", "fundamentals_reprt_code"]]

    out = price.drop(columns=["_as_of"]).merge(latest, on=["security_id", as_of_col], how="left")
    keyed = working.merge(
        latest.rename(columns={"fundamentals_bsns_year": "bsns_year", "fundamentals_reprt_code": "reprt_code"}),
        on=["security_id", "bsns_year", "reprt_code"],
        how="inner",
    )
    if keyed.empty:
        return out

    pivot = keyed.pivot_table(
        index=["security_id", as_of_col],
        columns="account_nm",
        values="thstrm_amount",
        aggfunc="last",
    )
    pivot.columns = [f"acct_{col}" for col in pivot.columns]
    pivot = pivot.reset_index()
    return out.merge(pivot, on=["security_id", as_of_col], how="left")
