from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

from collector.config import Settings


class Lakehouse:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _dataset_dir(self, layer: str, dataset: str, partition: str | None = None) -> Path:
        base = self.settings.raw_dir if layer == "raw" else self.settings.curated_dir
        path = base / dataset
        return path / partition if partition else path

    def write_raw(self, dataset: str, frame: pd.DataFrame, run_id: str, partition: str) -> Path:
        path = self._dataset_dir("raw", dataset, f"{partition}/run_id={run_id}")
        path.mkdir(parents=True, exist_ok=True)
        file = path / "source.parquet"
        frame.to_parquet(file, index=False)
        return file

    def replace_curated_partition(self, dataset: str, frame: pd.DataFrame, partition: str) -> Path:
        path = self._dataset_dir("curated", dataset, partition)
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
        file = path / "part-000.parquet"
        frame.to_parquet(file, index=False)
        return file

    def curated_partition_exists(self, dataset: str, partition: str) -> bool:
        path = self._dataset_dir("curated", dataset, partition)
        return path.exists() and any(path.rglob("*.parquet"))

    def list_curated_partitions(self, dataset: str, prefix: str | None = None) -> list[str]:
        path = self._dataset_dir("curated", dataset)
        if not path.exists():
            return []
        names = sorted(entry.name for entry in path.iterdir() if entry.is_dir())
        if prefix:
            names = [name for name in names if name.startswith(prefix)]
        return names

    def read_curated_partition(self, dataset: str, partition: str) -> pd.DataFrame:
        path = self._dataset_dir("curated", dataset, partition)
        files = list(path.rglob("*.parquet")) if path.exists() else []
        return pd.concat([pd.read_parquet(file) for file in files], ignore_index=True) if files else pd.DataFrame()

    def read_curated(self, dataset: str) -> pd.DataFrame:
        path = self._dataset_dir("curated", dataset)
        files = list(path.rglob("*.parquet")) if path.exists() else []
        return pd.concat([pd.read_parquet(file) for file in files], ignore_index=True) if files else pd.DataFrame()

    def write_metadata(self, dataset: str, key: str, payload: dict) -> Path:
        path = self.settings.metadata_dir / dataset
        path.mkdir(parents=True, exist_ok=True)
        file = path / f"{key}.json"
        file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return file
