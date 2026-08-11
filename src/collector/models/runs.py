from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class IngestionRun:
    run_id: str
    kind: str
    started_at: str
    status: str = "running"
    rows_written: int = 0
    message: str | None = None

    @classmethod
    def start(cls, kind: str) -> "IngestionRun":
        return cls(uuid4().hex, kind, datetime.now(UTC).isoformat(timespec="seconds"))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QualityIssue:
    check: str
    severity: str
    message: str
    row_index: int | None = None
