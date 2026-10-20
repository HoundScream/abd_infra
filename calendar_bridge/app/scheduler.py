from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.config import get_settings
from app.db.models import JobDefinition
from app.db.session import SessionLocal, init_db
from app.workers.incoming_invites import run_incoming_job
from app.workers.outgoing_invites import run_outgoing_job
from app.workers.sync_audit import run_sync_audit_job

logger = logging.getLogger(__name__)

JOB_HANDLERS = {
    "incoming_invites": run_incoming_job,
    "outgoing_invites": run_outgoing_job,
    "sync_audit": run_sync_audit_job,
}

_running: set[str] = set()
_lock = threading.Lock()


def is_job_running(slug: str) -> bool:
    with _lock:
        return slug in _running


def _run_job(slug: str) -> None:
    settings = get_settings()
    with SessionLocal() as session:
        job = session.scalar(select(JobDefinition).where(JobDefinition.slug == slug))
        if not job or not job.enabled:
            logger.info("Задача %s отключена или не найдена", slug)
            return
        handler = JOB_HANDLERS.get(slug)
        if not handler:
            logger.warning("Нет обработчика для %s", slug)
            return
        logger.info("Запуск задачи %s", slug)
        try:
            handler(session, settings, job)
        except Exception:
            logger.exception("Ошибка задачи %s", slug)


def _run_job_guarded(slug: str) -> None:
    with _lock:
        if slug in _running:
            logger.info("Задача %s уже выполняется, пропуск", slug)
            return
        _running.add(slug)
    try:
        _run_job(slug)
    finally:
        with _lock:
            _running.remove(slug)


def start_scheduler() -> BackgroundScheduler:
    init_db()
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone="UTC")

    with SessionLocal() as session:
        jobs = session.scalars(select(JobDefinition).where(JobDefinition.enabled.is_(True))).all()
        for job in jobs:
            if job.slug not in JOB_HANDLERS:
                continue
            scheduler.add_job(
                _run_job_guarded,
                "interval",
                seconds=job.interval_seconds,
                id=job.slug,
                args=[job.slug],
                replace_existing=True,
                max_instances=1,
            )
            logger.info("Запланировано: %s каждые %ss", job.slug, job.interval_seconds)

    if settings.scheduler_enabled:
        scheduler.start()
        logger.info(
            "Планировщик включён (автозапуск по интервалу). Ручной запуск — кнопкой в админке."
        )
    return scheduler


def run_job_now(slug: str) -> str:
    """Запуск в фоне. Коды: started | already_running | not_implemented | disabled | unknown."""
    with SessionLocal() as session:
        job = session.scalar(select(JobDefinition).where(JobDefinition.slug == slug))
        if not job:
            return "unknown"
        if slug not in JOB_HANDLERS:
            return "not_implemented"
        if not job.enabled:
            return "disabled"
    if is_job_running(slug):
        return "already_running"
    thread = threading.Thread(target=_run_job_guarded, args=[slug], daemon=True)
    thread.start()
    return "started"


def can_run_job(slug: str, enabled: bool = True) -> bool:
    return enabled and slug in JOB_HANDLERS


def last_finished_at(slug: str) -> datetime | None:
    """Время последнего завершённого запуска (для UI)."""
    from app.db.models import JobRun

    with SessionLocal() as session:
        job = session.scalar(select(JobDefinition).where(JobDefinition.slug == slug))
        if not job:
            return None
        from sqlalchemy import desc

        run = session.scalar(
            select(JobRun)
            .where(JobRun.job_id == job.id, JobRun.finished_at.isnot(None))
            .order_by(desc(JobRun.finished_at))
            .limit(1)
        )
        return run.finished_at if run else None
