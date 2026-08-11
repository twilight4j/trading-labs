from __future__ import annotations

import pandas as pd

from collector.storage import Lakehouse


def quarantine(lakehouse: Lakehouse, frame: pd.DataFrame, run_id: str, trade_date: str) -> None:
    if not frame.empty:
        lakehouse.write_raw("quarantine", frame, run_id, f"trade_date={trade_date}")
