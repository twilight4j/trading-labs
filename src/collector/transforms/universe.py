from __future__ import annotations

from datetime import date

import pandas as pd


def build_universe(prices: pd.DataFrame, securities: pd.DataFrame, as_of_date: date, delisted: pd.DataFrame | None = None) -> pd.DataFrame:
    keys = ["security_id", "market"]
    master = securities[keys + ["security_type", "exclusion_reason"]].drop_duplicates(keys)
    universe = prices[keys].drop_duplicates().merge(master, on=keys, how="left")
    universe["as_of_date"] = pd.Timestamp(as_of_date)
    universe["eligible"] = (universe["security_type"] == "COMMON") & universe["exclusion_reason"].isna()
    universe["exclusion_reason"] = universe["exclusion_reason"].fillna("")
    if delisted is not None and not delisted.empty and "security_id" in delisted:
        delisted_after = delisted.set_index("security_id").get("last_trade_date")
        if delisted_after is not None:
            last_dates = universe["security_id"].map(delisted_after)
            mask = last_dates.notna() & (pd.Timestamp(as_of_date) > pd.to_datetime(last_dates))
            universe.loc[mask, "eligible"] = False
            universe.loc[mask, "exclusion_reason"] = "delisted"
    return universe
