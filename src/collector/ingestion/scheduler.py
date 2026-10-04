from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger

from collector.config import Settings

from .jobs import CONSENSUS, DAILY, CollectionJobs

DAILY_DAYS = "mon-fri"


def schedules(settings: Settings) -> dict[str, dict[str, str | int]]:
    """When each scheduled job fires — the one place both the scheduler and the status API read."""
    return {
        DAILY: {"days": DAILY_DAYS, "hour": settings.schedule_hour, "minute": settings.schedule_minute},
        CONSENSUS: {
            "days": settings.consensus_schedule_day,
            "hour": settings.consensus_schedule_hour,
            "minute": settings.consensus_schedule_minute,
        },
    }


def trigger(settings: Settings, job: str) -> CronTrigger:
    when = schedules(settings)[job]
    return CronTrigger(day_of_week=when["days"], hour=when["hour"], minute=when["minute"], timezone=settings.timezone)


def build_scheduler(
    settings: Settings, jobs: CollectionJobs | None = None, scheduler: BaseScheduler | None = None
) -> BaseScheduler:
    """The scheduler the labs API starts. A switched-off schedule still fires; `run_scheduled` skips it."""
    jobs = jobs or CollectionJobs(settings)
    scheduler = scheduler or BackgroundScheduler(timezone=settings.timezone)
    ids = {DAILY: "daily-update", CONSENSUS: "consensus-weekly"}
    for job, job_id in ids.items():
        scheduler.add_job(jobs.run_scheduled, trigger(settings, job), args=[job], id=job_id, max_instances=1, coalesce=True)
    return scheduler
