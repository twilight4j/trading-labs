from __future__ import annotations

import pandas as pd

from collector.models import QualityIssue


def validate_prices(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[QualityIssue]]:
    """Return valid rows and row-level quality issues without aborting ingestion."""
    issues: list[QualityIssue] = []
    invalid = pd.Series(False, index=frame.index)
    duplicate = frame.duplicated(["trade_date", "security_id"], keep="first")
    for index in frame.index[duplicate]:
        issues.append(QualityIssue("duplicate_key", "error", "duplicate trade_date/security_id", int(index)))
    invalid |= duplicate
    required = ["open", "high", "low", "close", "volume"]
    missing = frame[required].isna().any(axis=1)
    for index in frame.index[missing]:
        issues.append(QualityIssue("missing_price", "error", "required price field is missing", int(index)))
    invalid |= missing
    negative = (frame[required] < 0).any(axis=1)
    for index in frame.index[negative]:
        issues.append(QualityIssue("negative_value", "error", "price or volume is negative", int(index)))
    invalid |= negative
    ohlc = (frame["low"] > frame[["open", "close"]].min(axis=1)) | (frame["high"] < frame[["open", "close"]].max(axis=1)) | (frame["low"] > frame["high"])
    for index in frame.index[ohlc]:
        issues.append(QualityIssue("ohlc_range", "error", "low/open/close/high relationship is invalid", int(index)))
    invalid |= ohlc
    return frame.loc[~invalid].copy(), issues
