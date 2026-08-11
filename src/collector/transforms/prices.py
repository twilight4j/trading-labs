from __future__ import annotations

from datetime import date

import pandas as pd


def _column(frame: pd.DataFrame, *names: str, default: object = pd.NA) -> pd.Series:
    for name in names:
        if name in frame.columns:
            return frame[name]
    return pd.Series(default, index=frame.index)


def normalize_prices(frame: pd.DataFrame, trade_date: date, market: str, source: str, *, adjusted: bool) -> pd.DataFrame:
    """Map source-native KRX columns into the stable daily price schema."""
    ticker = _column(frame, "티커", "Code", "Symbol", "code").astype("string").str.zfill(6)
    result = pd.DataFrame({
        "trade_date": pd.Timestamp(trade_date),
        "security_id": "KRX:" + ticker,
        "market": market,
        "open": pd.to_numeric(_column(frame, "시가", "Open", "open"), errors="coerce"),
        "high": pd.to_numeric(_column(frame, "고가", "High", "high"), errors="coerce"),
        "low": pd.to_numeric(_column(frame, "저가", "Low", "low"), errors="coerce"),
        "close": pd.to_numeric(_column(frame, "종가", "Close", "close"), errors="coerce"),
        "volume": pd.to_numeric(_column(frame, "거래량", "Volume", "volume"), errors="coerce"),
        "trading_value": pd.to_numeric(_column(frame, "거래대금", "TradingValue", "trading_value"), errors="coerce"),
        "market_cap": pd.to_numeric(_column(frame, "시가총액", "시가총액_시총", "MarketCap", "market_cap"), errors="coerce"),
        "source": source,
        "adjusted": adjusted,
    })
    return result


def combine_raw_and_adjusted(raw: pd.DataFrame, adjusted: pd.DataFrame | None, adjustment_as_of: date) -> pd.DataFrame:
    keys = ["trade_date", "security_id", "market"]
    raw = raw.rename(columns={column: f"{column}_raw" for column in ["open", "high", "low", "close"]})
    if adjusted is None or adjusted.empty:
        result = raw.copy()
        for column in ("open", "high", "low", "close"):
            result[f"{column}_adjusted"] = pd.Series(pd.NA, index=result.index, dtype="Float64")
        result["adjustment_as_of"] = pd.Series(pd.NaT, index=result.index, dtype="datetime64[ns]")
        return result.drop(columns=["adjusted"])
    adjusted = adjusted[keys + ["open", "high", "low", "close"]].rename(
        columns={column: f"{column}_adjusted" for column in ["open", "high", "low", "close"]}
    )
    result = raw.merge(adjusted, on=keys, how="left")
    result["adjustment_as_of"] = pd.Timestamp(adjustment_as_of)
    return result.drop(columns=["adjusted"])


def normalize_adjusted_ohlcv(frame: pd.DataFrame, ticker: str, source: str) -> pd.DataFrame:
    """Map pykrx by-ticker adjusted OHLCV into open/high/low/close rows."""
    ticker = str(ticker).zfill(6)
    dated = frame.copy()
    if not isinstance(dated, pd.DataFrame):
        raise TypeError("adjusted OHLCV must be a DataFrame")
    if isinstance(dated.index, pd.DatetimeIndex) and "날짜" not in dated.columns and "date" not in dated.columns:
        dated = dated.reset_index()
    if "날짜" in dated.columns:
        trade_date = pd.to_datetime(dated["날짜"])
    elif "date" in dated.columns:
        trade_date = pd.to_datetime(dated["date"])
    elif "index" in dated.columns:
        trade_date = pd.to_datetime(dated["index"])
    else:
        raise KeyError("adjusted OHLCV frame must include a date column or DatetimeIndex")

    result = pd.DataFrame({
        "trade_date": pd.to_datetime(trade_date).dt.normalize(),
        "security_id": f"KRX:{ticker}",
        "open": pd.to_numeric(_column(dated, "시가", "Open", "open"), errors="coerce"),
        "high": pd.to_numeric(_column(dated, "고가", "High", "high"), errors="coerce"),
        "low": pd.to_numeric(_column(dated, "저가", "Low", "low"), errors="coerce"),
        "close": pd.to_numeric(_column(dated, "종가", "Close", "close"), errors="coerce"),
        "source": source,
    })
    return result.loc[(result["open"] > 0) & (result["close"] > 0)].reset_index(drop=True)


def overlay_adjusted_prices(curated: pd.DataFrame, adjusted: pd.DataFrame, adjustment_as_of: date) -> pd.DataFrame:
    """Fill/replace *_adjusted columns for matching security_id(+trade_date) rows."""
    if curated.empty or adjusted.empty:
        return curated.copy()

    result = curated.copy()
    for column in ("open_adjusted", "high_adjusted", "low_adjusted", "close_adjusted", "adjustment_as_of"):
        if column not in result.columns:
            result[column] = pd.NA

    day = adjusted.copy()
    day["security_id"] = day["security_id"].astype("string")
    result["security_id"] = result["security_id"].astype("string")
    keys = ["security_id"]
    if "trade_date" in day.columns and "trade_date" in result.columns:
        day["trade_date"] = pd.to_datetime(day["trade_date"]).dt.normalize()
        result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.normalize()
        keys = ["trade_date", "security_id"]

    patch = (
        day[keys + ["open", "high", "low", "close"]]
        .drop_duplicates(keys, keep="last")
        .rename(columns={column: f"{column}_new" for column in ["open", "high", "low", "close"]})
    )
    merged = result.merge(patch, on=keys, how="left")
    touched = merged["open_new"].notna()
    for column in ("open", "high", "low", "close"):
        adjusted_col = f"{column}_adjusted"
        new_col = f"{column}_new"
        merged.loc[touched, adjusted_col] = merged.loc[touched, new_col]
        merged = merged.drop(columns=[new_col])
    merged.loc[touched, "adjustment_as_of"] = pd.Timestamp(adjustment_as_of)
    return merged
