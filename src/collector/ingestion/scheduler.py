from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from collector.config import Settings
from .service import IngestionService


def serve(settings: Settings) -> None:
    service = IngestionService(settings)
    scheduler = BlockingScheduler(timezone=settings.timezone)
    scheduler.add_job(service.update, CronTrigger(day_of_week="mon-fri", hour=settings.schedule_hour, minute=settings.schedule_minute), id="daily-update", max_instances=1, coalesce=True)
    scheduler.start()
