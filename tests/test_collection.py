import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api_caller import authed, caller
from collector.config import Settings
from collector.ingestion.jobs import CollectionJobs, JobBusy
from collector.storage import Lakehouse
from valuation.api import API_PREFIX, create_app
from wisereport_fakes import seed_market_data

STATUS = f"{API_PREFIX}/collection/status"

pytestmark = pytest.mark.usefixtures("api_token")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    settings = Settings(data_dir=tmp_path / "market-data")
    seed_market_data(Lakehouse(settings))
    return settings


def record(settings: Settings, run_id: str, **fields) -> None:
    Lakehouse(settings).write_metadata("ingestion_runs", run_id, {"run_id": run_id, "rows_written": 0, "message": None, **fields})


class Held:
    """A runner that waits until released — lets a test look at a job while it runs."""

    def __init__(self):
        self.calls: list[str] = []
        self.pending: list = []

    def runners(self, fail: str | None = None) -> dict:
        def runner(job):
            def run(_settings):
                self.calls.append(job)
                if job == fail:
                    raise RuntimeError("WiseReport 응답 없음")
            return run
        return {job: runner(job) for job in ("daily", "consensus", "fundamentals")}

    def spawn(self, work) -> None:
        self.pending.append(work)

    def finish(self) -> None:
        while self.pending:
            self.pending.pop(0)()


def actions(settings: Settings) -> list[dict]:
    """Who did what from the screen, without the time."""
    file = settings.metadata_dir / "collection" / "actions.jsonl"
    lines = file.read_text(encoding="utf-8").splitlines() if file.exists() else []
    return [{key: value for key, value in json.loads(line).items() if key != "at"} for line in lines]


# --- jobs --------------------------------------------------------------------


def test_schedule_switch_defaults_on_and_survives_a_new_process(settings):
    jobs = CollectionJobs(settings)
    assert jobs.schedule_enabled("daily") and jobs.schedule_enabled("consensus")
    assert not jobs.schedule_enabled("fundamentals")  # no schedule at all

    jobs.set_schedule_enabled("consensus", False)

    again = CollectionJobs(settings)
    assert not again.schedule_enabled("consensus")
    assert again.schedule_enabled("daily")
    with pytest.raises(KeyError):
        jobs.set_schedule_enabled("fundamentals", True)


def test_a_running_job_cannot_be_started_again_until_it_ends(settings):
    held = Held()
    jobs = CollectionJobs(settings, held.runners(), held.spawn)

    started = jobs.start("consensus")

    assert jobs.running() == {"consensus": started}
    assert started["source"] == "api"
    with pytest.raises(JobBusy):
        jobs.start("consensus")
    jobs.start("daily")  # another job is free to run
    held.finish()
    assert jobs.running() == {}
    assert held.calls == ["consensus", "daily"]
    with pytest.raises(KeyError):
        jobs.start("adjusted")


def test_the_schedule_skips_a_switched_off_or_running_job(settings):
    held = Held()
    jobs = CollectionJobs(settings, held.runners(), held.spawn)

    jobs.set_schedule_enabled("daily", False)
    jobs.run_scheduled("daily")
    assert held.calls == []

    jobs.set_schedule_enabled("daily", True)
    jobs.start("daily")            # started from the screen, still running
    jobs.run_scheduled("daily")    # 18:30 arrives
    assert held.calls == []
    held.finish()
    jobs.run_scheduled("daily")
    assert held.calls == ["daily", "daily"]


def test_a_failed_job_is_released_and_its_error_kept(settings):
    held = Held()
    jobs = CollectionJobs(settings, held.runners(fail="consensus"), held.spawn)

    jobs.start("consensus")
    held.finish()

    assert jobs.running() == {}
    assert jobs.last_errors()["consensus"]["message"] == "WiseReport 응답 없음"
    jobs.start("consensus")        # can run again, and the old error is cleared while it runs
    assert jobs.last_errors() == {}


# --- API ---------------------------------------------------------------------


def test_status_reports_jobs_summary_and_recent_runs(settings):
    record(settings, "a1", kind="daily", started_at="2026-10-02T09:30:10+00:00", status="completed", rows_written=2659, trade_date="2026-10-02")
    record(settings, "a2", kind="consensus", started_at="2026-10-01T14:37:26+00:00", status="completed", snapshot_date="2026-10-01", issues=["x"])
    record(settings, "a3", kind="fundamentals", started_at="2026-08-09T14:09:50+00:00", status="quota_exceeded", message="bsns_year=2025 reprt_code=11014: 사용한도")
    record(settings, "a4", kind="adjusted_prices", started_at="2026-08-09T07:57:50+00:00", status="completed", securities=["KRX:000660"])
    record(settings, "a5", kind="daily", started_at="2026-10-01T09:30:10+00:00", status="completed", trade_date="2026-10-01")

    payload = authed(create_app(settings)).get(STATUS).json()

    assert payload["timezone"] == "Asia/Seoul"
    assert payload["scheduler"] == {"running": False}          # no lifespan in this test
    assert payload["summary"] == {"daily_trade_date": "2026-09-25", "consensus_snapshot_date": None}
    jobs = {job["id"]: job for job in payload["jobs"]}
    assert list(jobs) == ["daily", "consensus", "fundamentals", "adjusted"]
    assert jobs["daily"]["schedule"] == {"days": "mon-fri", "time": "18:30", "enabled": True, "next_run_at": None}
    assert jobs["consensus"]["schedule"]["days"] == "sat"
    assert jobs["fundamentals"]["schedule"] is None and jobs["adjusted"]["schedule"] is None
    assert [jobs[name]["runnable"] for name in jobs] == [True, True, True, False]
    assert jobs["daily"]["last_run"]["run_id"] == "a1"         # the newest of its kind
    assert jobs["fundamentals"]["last_run"]["status"] == "quota_exceeded"
    assert jobs["adjusted"]["last_run"]["securities"] == ["KRX:000660"]
    assert all(job["running"] is None and job["last_error"] is None for job in payload["jobs"])
    assert [run["run_id"] for run in payload["runs"]] == ["a1", "a2", "a5", "a3", "a4"]   # newest first
    assert "issues" not in payload["runs"][1]


def test_status_sees_a_new_run_without_restarting(settings):
    client = authed(create_app(settings))
    assert client.get(STATUS).json()["runs"] == []
    record(settings, "b1", kind="daily", started_at="2026-10-06T09:30:10+00:00", status="completed")
    assert [run["run_id"] for run in client.get(STATUS).json()["runs"]] == ["b1"]


def test_run_starts_the_job_and_reports_it_running_until_it_ends(settings):
    held = Held()
    client = authed(create_app(settings, jobs=CollectionJobs(settings, held.runners(), held.spawn)))

    response = client.post(f"{API_PREFIX}/collection/jobs/consensus/run")

    assert response.status_code == 202
    assert response.json()["job"] == "consensus" and response.json()["source"] == "api"
    running = {job["id"]: job["running"] for job in client.get(STATUS).json()["jobs"]}
    assert running["consensus"]["started_at"] == response.json()["started_at"]
    assert running["daily"] is None

    busy = client.post(f"{API_PREFIX}/collection/jobs/consensus/run")
    assert busy.status_code == 409 and busy.json()["code"] == "conflict"

    held.finish()
    assert held.calls == ["consensus"]
    assert all(job["running"] is None for job in client.get(STATUS).json()["jobs"])


def test_run_refuses_adjusted_prices_and_unknown_jobs(settings):
    held = Held()
    client = authed(create_app(settings, jobs=CollectionJobs(settings, held.runners(), held.spawn)))

    adjusted = client.post(f"{API_PREFIX}/collection/jobs/adjusted/run")
    assert adjusted.status_code == 400 and adjusted.json()["code"] == "validation"
    unknown = client.post(f"{API_PREFIX}/collection/jobs/nope/run")
    assert unknown.status_code == 404 and unknown.json()["code"] == "not_found"
    assert held.calls == [] and held.pending == []


def test_schedule_switch_through_the_api(settings):
    client = authed(create_app(settings))

    off = client.put(f"{API_PREFIX}/collection/jobs/consensus/schedule", json={"enabled": False})

    assert off.status_code == 200 and off.json() == {"job": "consensus", "enabled": False}
    jobs = {job["id"]: job for job in client.get(STATUS).json()["jobs"]}
    assert jobs["consensus"]["schedule"]["enabled"] is False
    assert jobs["daily"]["schedule"]["enabled"] is True
    state = json.loads((settings.metadata_dir / "collection" / "schedule.json").read_text(encoding="utf-8"))
    assert state == {"consensus": False}

    no_schedule = client.put(f"{API_PREFIX}/collection/jobs/fundamentals/schedule", json={"enabled": True})
    assert no_schedule.status_code == 400 and no_schedule.json()["code"] == "validation"
    malformed = client.put(f"{API_PREFIX}/collection/jobs/daily/schedule", json={"enabled": "maybe"})
    assert malformed.status_code == 400
    assert malformed.json()["errors"][0]["field"] == "enabled"


def test_the_screen_user_who_ran_or_switched_a_job_is_noted(settings):
    held = Held()
    app = create_app(settings, jobs=CollectionJobs(settings, held.runners(), held.spawn))
    minsu = authed(app, caller("collection", email="minsu@example.com"))

    started = minsu.post(f"{API_PREFIX}/collection/jobs/daily/run")

    assert started.json()["by"] == "minsu@example.com"
    running = {job["id"]: job["running"] for job in minsu.get(STATUS).json()["jobs"]}
    assert running["daily"]["by"] == "minsu@example.com"                     # shown while it runs
    assert minsu.post(f"{API_PREFIX}/collection/jobs/daily/run").status_code == 409   # refused — nothing to note

    authed(app).put(f"{API_PREFIX}/collection/jobs/consensus/schedule", json={"enabled": False})
    minsu.put(f"{API_PREFIX}/collection/jobs/consensus/schedule", json={"enabled": True})

    assert actions(settings) == [
        {"by": "minsu@example.com", "action": "run", "job": "daily"},
        {"by": "admin@example.com", "action": "schedule_off", "job": "consensus"},
        {"by": "minsu@example.com", "action": "schedule_on", "job": "consensus"},
    ]


def test_the_scheduler_and_a_refused_request_leave_no_note(settings):
    held = Held()
    jobs = CollectionJobs(settings, held.runners(), held.spawn)
    client = authed(create_app(settings, jobs=jobs))

    jobs.run_scheduled("daily")                                              # the scheduler is nobody
    client.post(f"{API_PREFIX}/collection/jobs/adjusted/run")                # 400
    client.put(f"{API_PREFIX}/collection/jobs/fundamentals/schedule", json={"enabled": True})   # 400
    viewer = caller("fair", email="viewer@example.com")
    assert client.post(f"{API_PREFIX}/collection/jobs/consensus/run", headers=viewer).status_code == 403

    assert held.calls == ["daily"] and held.pending == []
    assert actions(settings) == []


def test_a_note_that_cannot_be_written_does_not_stop_the_job(settings):
    held = Held()
    jobs = CollectionJobs(settings, held.runners(), held.spawn)
    (settings.metadata_dir / "collection").mkdir(parents=True, exist_ok=True)
    (settings.metadata_dir / "collection" / "actions.jsonl").mkdir()         # a directory where the file should be

    jobs.start("daily", by="minsu@example.com")
    held.finish()

    assert held.calls == ["daily"] and jobs.running() == {}


def test_collection_routes_need_the_token(settings):
    client = TestClient(create_app(settings))
    assert client.get(STATUS).status_code == 401
    assert client.post(f"{API_PREFIX}/collection/jobs/daily/run").status_code == 401
    assert client.put(f"{API_PREFIX}/collection/jobs/daily/schedule", json={"enabled": False}).status_code == 401


def test_the_api_process_runs_the_scheduler_and_reports_the_next_run(settings):
    held = Held()
    app = create_app(settings, jobs=CollectionJobs(settings, held.runners(), held.spawn))

    with authed(app) as client:      # the lifespan starts the scheduler
        payload = client.get(STATUS).json()
        assert payload["scheduler"] == {"running": True}
        jobs = {job["id"]: job for job in payload["jobs"]}
        assert jobs["daily"]["schedule"]["next_run_at"][11:16] == "18:30"
        assert jobs["consensus"]["schedule"]["next_run_at"][11:16] == "09:00"

        client.put(f"{API_PREFIX}/collection/jobs/daily/schedule", json={"enabled": False})
        assert client.get(STATUS).json()["jobs"][0]["schedule"]["next_run_at"] is None

    assert app.state.scheduler is None  # stopped with the app
