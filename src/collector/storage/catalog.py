from __future__ import annotations

from pathlib import Path

import duckdb

from collector.config import Settings


class Catalog:
    def __init__(self, settings: Settings):
        self.settings = settings

    def connect(self) -> duckdb.DuckDBPyConnection:
        database = self.settings.data_dir / "market_data.duckdb"
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect(str(database))
        for name in ("daily_prices", "universe_snapshot", "security_master", "fundamentals_accounts"):
            pattern = self.settings.curated_dir / name / "**" / "*.parquet"
            if list((self.settings.curated_dir / name).rglob("*.parquet")) if (self.settings.curated_dir / name).exists() else []:
                connection.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{pattern}', hive_partitioning=true, union_by_name=true)")
        return connection
