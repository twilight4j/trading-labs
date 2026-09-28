from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PER_CONFIG = Path("config/valuation_per.toml")


def _positive(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} PER은 숫자여야 합니다: {value!r}")
    number = float(value)
    if number <= 0:
        raise ValueError(f"{label} PER은 0보다 커야 합니다: {value}")
    return number


@dataclass(frozen=True)
class PerConfig:
    """기준PER: 종목 오버라이드 → WICS 업종 PER → 기본값."""

    default_per: float = 10.0
    sector_per: dict[str, float] = field(default_factory=dict)
    stock_per: dict[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None) -> PerConfig:
        if path is None or not path.exists():
            return cls()
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for table in ("sector_per", "stock_per"):
            if not isinstance(data.get(table, {}), dict):
                raise ValueError(f"[{table}]는 테이블이어야 합니다.")
        return cls(
            default_per=_positive(data.get("default_per", 10.0), "default_per"),
            sector_per={str(k): _positive(v, str(k)) for k, v in data.get("sector_per", {}).items()},
            stock_per={str(k): _positive(v, str(k)) for k, v in data.get("stock_per", {}).items()},
        )

    def resolve(self, ticker: str, sector: str | None) -> float:
        if ticker in self.stock_per:
            return self.stock_per[ticker]
        if sector and sector in self.sector_per:
            return self.sector_per[sector]
        return self.default_per
