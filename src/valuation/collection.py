"""labs API — collection status, run-now and the schedule switch for trading-ui's 데이터 수집 screen.

Reads what the collector already records (`metadata/ingestion_runs`, consensus manifests, price partitions) and drives
`CollectionJobs`, which shares this process with the scheduler. Rules: docs/collection.md.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from pydantic import BaseModel

from collector.config import Settings
from collector.ingestion.consensus import latest_published_snapshot, read_latest_prices
from collector.ingestion.jobs import RUNNABLE, SCHEDULED, CollectionJobs, JobBusy
from collector.ingestion.scheduler import schedules, trigger
from collector.storage import Lakehouse
from valuation.errors import CONFLICT, NOT_FOUND, VALIDATION, ApiError

# Screen job id → the `kind` its runs are recorded under. 수정주가 has records but is not run from the screen.
JOB_KINDS = {"daily": "daily", "consensus": "consensus", "fundamentals": "fundamentals", "adjusted": "adjusted_prices"}
RECENT_RUNS = 30


class ScheduleUpdate(BaseModel):
    enabled: bool


class RunIndex:
    """Run records, newest first. Re-read only when the directory changes (4,400 small files and growing)."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._stamp: int | None = None
        self._runs: list[dict] = []

    def load(self) -> list[dict]:
        try:
            stamp = self._directory.stat().st_mtime_ns
        except FileNotFoundError:
            return []
        if stamp != self._stamp:
            runs = []
            for file in self._directory.glob("*.json"):
                try:
                    run = json.loads(file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                run.pop("issues", None)
                runs.append(run)
            runs.sort(key=lambda run: run.get("started_at") or "", reverse=True)
            self._runs, self._stamp = runs, stamp
        return self._runs


def build_router(settings: Settings, jobs: CollectionJobs, scheduler_running: Callable[[], bool]) -> APIRouter:
    router = APIRouter(prefix="/collection")
    lakehouse = Lakehouse(settings)
    index = RunIndex(settings.metadata_dir / "ingestion_runs")

    def known(job: str) -> str:
        if job not in JOB_KINDS:
            raise ApiError(404, NOT_FOUND, f"수집 작업이 없습니다: {job}")
        return job

    @router.get("/status")
    def status() -> dict:
        now = datetime.now(ZoneInfo(settings.timezone))
        runs = index.load()
        last: dict[str, dict] = {}
        for run in runs:
            last.setdefault(run.get("kind"), run)
        running, errors, plan, alive = jobs.running(), jobs.last_errors(), schedules(settings), scheduler_running()
        items = []
        for job, kind in JOB_KINDS.items():
            schedule = None
            if job in plan:
                enabled = jobs.schedule_enabled(job)
                upcoming = trigger(settings, job).get_next_fire_time(None, now) if enabled and alive else None
                schedule = {
                    "days": plan[job]["days"],
                    "time": f"{plan[job]['hour']:02d}:{plan[job]['minute']:02d}",
                    "enabled": enabled,
                    "next_run_at": upcoming.isoformat(timespec="seconds") if upcoming else None,
                }
            items.append({
                "id": job,
                "runnable": job in RUNNABLE,
                "schedule": schedule,
                "running": running.get(job),
                "last_run": last.get(kind),
                "last_error": errors.get(job),
            })
        trade_date, _ = read_latest_prices(lakehouse)
        return {
            "now": now.isoformat(timespec="seconds"),
            "timezone": settings.timezone,
            "scheduler": {"running": alive},
            "jobs": items,
            "summary": {"daily_trade_date": trade_date, "consensus_snapshot_date": latest_published_snapshot(lakehouse)},
            "runs": runs[:RECENT_RUNS],
        }

    @router.post("/jobs/{job}/run", status_code=202)
    def run(job: str) -> dict:
        if known(job) not in RUNNABLE:
            raise ApiError(400, VALIDATION, f"{job} 은 화면에서 실행하지 않습니다 — 명령으로 실행하세요.")
        try:
            return {"job": job, **jobs.start(job, source="api")}
        except JobBusy:
            raise ApiError(409, CONFLICT, "이미 실행 중입니다 — 끝난 뒤 다시 실행하세요.") from None

    @router.put("/jobs/{job}/schedule")
    def set_schedule(job: str, body: ScheduleUpdate) -> dict:
        if known(job) not in SCHEDULED:
            raise ApiError(400, VALIDATION, f"{job} 은 스케줄이 없는 작업입니다.")
        jobs.set_schedule_enabled(job, body.enabled)
        return {"job": job, "enabled": jobs.schedule_enabled(job)}

    return router
