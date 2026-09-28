from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from collector.config import Settings
from .consensus import ConsensusService
from .service import IngestionService


def build_scheduler(settings: Settings) -> BlockingScheduler:
    service = IngestionService(settings)
    consensus = ConsensusService(settings)
    scheduler = BlockingScheduler(timezone=settings.timezone)
    scheduler.add_job(service.update, CronTrigger(day_of_week="mon-fri", hour=settings.schedule_hour, minute=settings.schedule_minute), id="daily-update", max_instances=1, coalesce=True)
    scheduler.add_job(
        consensus.update,
        CronTrigger(
            day_of_week=settings.consensus_schedule_day,
            hour=settings.consensus_schedule_hour,
            minute=settings.consensus_schedule_minute,
        ),
        id="consensus-weekly",
        max_instances=1,
        coalesce=True,
    )
    return scheduler


def serve(settings: Settings) -> None:
    build_scheduler(settings).start()
