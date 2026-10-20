from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.crypto import decrypt
from app.db.models import CalendarEventRecord, JobDefinition, JobRun, ProcessedMessage, User
from app.services.caldav_client import CaldavClient
from app.services.imap_client import ImapClient

logger = logging.getLogger(__name__)


def run_sync_audit_for_user(session: Session, settings: Settings, user: User) -> dict:
    cal_pass = decrypt(settings.secret_key, user.caldav_password_enc) or decrypt(
        settings.secret_key, user.imap_password_enc
    )
    imap_pass = decrypt(settings.secret_key, user.imap_password_enc)

    result = {
        "imap_ok": False,
        "caldav_ok": False,
        "events_in_caldav": 0,
        "events_in_bridge_db": 0,
        "recent_candidates": 0,
    }

    if imap_pass:
        try:
            ImapClient(settings.imap_host, settings.imap_port, user.email, imap_pass).fetch_since(1)
            result["imap_ok"] = True
        except Exception as exc:
            result["imap_error"] = str(exc)

    if cal_pass:
        caldav = CaldavClient(settings.caldav_url, user.email, cal_pass)
        result["caldav_ok"] = caldav.ping()
        if result["caldav_ok"]:
            events = caldav.list_events(user.calendar_name or settings.default_calendar_name)
            result["events_in_caldav"] = len(events)

    result["events_in_bridge_db"] = session.scalar(
        select(func.count())
        .select_from(CalendarEventRecord)
        .where(CalendarEventRecord.user_id == user.id)
    ) or 0

    result["recent_candidates"] = session.scalar(
        select(func.count())
        .select_from(ProcessedMessage)
        .where(
            ProcessedMessage.user_id == user.id,
            ProcessedMessage.status.in_(["candidate_dry_run", "event_created", "parse_failed"]),
        )
    ) or 0

    return result


def run_sync_audit_job(session: Session, settings: Settings, job: JobDefinition) -> None:
    run = JobRun(job_id=job.id, status="running")
    session.add(run)
    session.commit()

    users = session.scalars(select(User).where(User.enabled.is_(True))).all()
    per_user: dict[str, dict] = {}
    problems = 0

    for user in users:
        try:
            stats = run_sync_audit_for_user(session, settings, user)
            per_user[user.email] = stats
            if not stats.get("caldav_ok") or not stats.get("imap_ok"):
                problems += 1
        except Exception as exc:
            per_user[user.email] = {"error": str(exc)}
            problems += 1

    run.status = "success" if problems == 0 else "failed"
    run.summary = f"проверено {len(users)}, проблем {problems}"
    run.details_json = json.dumps({"per_user": per_user, "problems": problems}, ensure_ascii=False)
    run.finished_at = datetime.now(timezone.utc)
    session.add(run)
    session.commit()
