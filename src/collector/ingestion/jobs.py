"""Collection jobs — run on a schedule and on demand, inside the one labs API process.

The scheduler lives in the API process (`labs-api serve`), so "is it running" and "don't run it twice" are plain
in-memory state. Two things are files under `metadata/collection/`: the schedule on/off switch (`schedule.json`), so
it survives a restart, and who ran or switched what from the screen (`actions.jsonl`). Restarting the process stops a
job that is running.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from collector.config import Settings
from collector.providers.dart import DartQuotaExceeded

from .consensus import ConsensusService
from .fundamentals import FundamentalsService
from .service import IngestionService

logger = logging.getLogger(__name__)

DAILY = "daily"
CONSENSUS = "consensus"
FUNDAMENTALS = "fundamentals"
RUNNABLE = (DAILY, CONSENSUS, FUNDAMENTALS)
SCHEDULED = (DAILY, CONSENSUS)

Runner = Callable[[Settings], None]


class JobBusy(RuntimeError):
    """The job is already running (started by the schedule or by the screen)."""


def _run_daily(settings: Settings) -> None:
    IngestionService(settings).catch_up()


def _run_consensus(settings: Settings) -> None:
    ConsensusService(settings).update(date.today())


def _run_fundamentals(settings: Settings) -> None:
    try:
        FundamentalsService(settings).update()
    except DartQuotaExceeded as exc:
        # The service already recorded the run as `quota_exceeded`; finished partitions are kept.
        logger.warning("OpenDART 일일 한도 초과로 중단: %s", exc)


DEFAULT_RUNNERS: dict[str, Runner] = {DAILY: _run_daily, CONSENSUS: _run_consensus, FUNDAMENTALS: _run_fundamentals}


def _start_thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, daemon=True, name="collection-job").start()


class CollectionJobs:
    def __init__(
        self,
        settings: Settings,
        runners: dict[str, Runner] | None = None,
        spawn: Callable[[Callable[[], None]], None] = _start_thread,
    ) -> None:
        self.settings = settings
        self._runners = runners or DEFAULT_RUNNERS
        self._spawn = spawn
        self._guard = threading.Lock()
        self._running: dict[str, dict[str, str]] = {}
        self._errors: dict[str, dict[str, str]] = {}

    # --- schedule switch ------------------------------------------------------------------------

    @property
    def _schedule_file(self) -> Path:
        return self.settings.metadata_dir / "collection" / "schedule.json"

    def _schedule_state(self) -> dict[str, bool]:
        try:
            return json.loads(self._schedule_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def schedule_enabled(self, job: str) -> bool:
        """On unless switched off. A job without a schedule is never enabled."""
        return job in SCHEDULED and bool(self._schedule_state().get(job, True))

    def set_schedule_enabled(self, job: str, enabled: bool, by: str | None = None) -> None:
        if job not in SCHEDULED:
            raise KeyError(job)
        state = {**self._schedule_state(), job: bool(enabled)}
        self._schedule_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self._schedule_file.with_suffix(".tmp")
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self._schedule_file)
        self._note(by, "schedule_on" if enabled else "schedule_off", job)

    # --- who did it -----------------------------------------------------------------------------

    @property
    def _actions_file(self) -> Path:
        return self.settings.metadata_dir / "collection" / "actions.jsonl"

    def _note(self, by: str | None, action: str, job: str) -> None:
        """Append who did what from the screen, one JSON line each. Without `by` (the scheduler) nothing is noted.

        Run records cannot carry this: the services write them, one run-now can leave several, and the services do not
        know users (the commands and the scheduler call them too).
        """
        if not by:
            return
        line = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "by": by, "action": action, "job": job}
        try:
            with self._guard:
                self._actions_file.parent.mkdir(parents=True, exist_ok=True)
                with self._actions_file.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError:  # a note that cannot be written must not stop the collection
            logger.exception("수집 작업 %s — %s 를 %s 로 남기지 못함", job, action, self._actions_file)

    # --- running --------------------------------------------------------------------------------

    def running(self) -> dict[str, dict[str, str]]:
        with self._guard:
            return {job: dict(entry) for job, entry in self._running.items()}

    def last_errors(self) -> dict[str, dict[str, str]]:
        """Errors of the latest run of each job that ended without the service recording a run."""
        with self._guard:
            return {job: dict(entry) for job, entry in self._errors.items()}

    def _begin(self, job: str, source: str, by: str | None = None) -> dict[str, str]:
        if job not in self._runners:
            raise KeyError(job)
        with self._guard:
            if job in self._running:
                raise JobBusy(job)
            entry = {"started_at": datetime.now(UTC).isoformat(timespec="seconds"), "source": source}
            if by:
                entry["by"] = by
            self._running[job] = entry
            self._errors.pop(job, None)
            return dict(entry)

    def _work(self, job: str) -> None:
        try:
            self._runners[job](self.settings)
        except Exception as exc:  # the scheduler thread and the request thread must both survive a failed job
            logger.exception("수집 작업 %s 실패", job)
            with self._guard:
                self._errors[job] = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "message": str(exc)}
        finally:
            with self._guard:
                self._running.pop(job, None)

    def start(self, job: str, source: str = "api", by: str | None = None) -> dict[str, str]:
        """Start the job in the background. Raises `JobBusy` when it is already running, `KeyError` when unknown.

        `by` is the signed-in user who asked: shown while the job runs, and noted in the action log.
        """
        entry = self._begin(job, source, by)
        self._note(by, "run", job)
        self._spawn(lambda: self._work(job))
        return entry

    def run_scheduled(self, job: str) -> None:
        """What the scheduler calls: skipped when the schedule is switched off or the job is already running."""
        if not self.schedule_enabled(job):
            logger.info("수집 작업 %s — 스케줄이 꺼져 있어 건너뜀", job)
            return
        try:
            self._begin(job, "schedule")
        except JobBusy:
            logger.warning("수집 작업 %s — 이미 실행 중이라 이번 스케줄은 건너뜀", job)
            return
        self._work(job)
