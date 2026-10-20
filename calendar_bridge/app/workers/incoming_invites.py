from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.crypto import decrypt
from app.db.models import CalendarEventRecord, JobDefinition, JobRun, ProcessedMessage, User
from app.services.caldav_client import CaldavClient
from app.services.imap_client import ImapClient
from app.debug_serializers import draft_to_dict
from app.services.invite_parser import is_invite_candidate, parse_message

logger = logging.getLogger(__name__)


def _finish_run(
    session: Session,
    run: JobRun,
    status: str,
    summary: str,
    details: dict,
) -> None:
    run.status = status
    run.summary = summary
    run.details_json = json.dumps(details, ensure_ascii=False)
    run.finished_at = datetime.now(timezone.utc)
    session.add(run)
    session.commit()


def run_incoming_for_user(session: Session, settings: Settings, user: User) -> dict:
    imap_pass = decrypt(settings.secret_key, user.imap_password_enc)
    cal_pass = decrypt(settings.secret_key, user.caldav_password_enc) or imap_pass
    cal_name = user.calendar_name or settings.default_calendar_name

    imap = ImapClient(settings.imap_host, settings.imap_port, user.email, imap_pass)
    caldav = CaldavClient(settings.caldav_url, user.email, cal_pass)

    stats = {"scanned": 0, "candidates": 0, "created": 0, "skipped_dup": 0, "failed": 0, "dry_run": settings.dry_run}

    for mail in imap.fetch_since(settings.lookback_days):
        stats["scanned"] += 1
        message_id = mail.message.get("Message-ID", "") or f"uid:{mail.uid}"
        dedupe_key = hashlib.sha256((message_id + user.email).encode()).hexdigest()

        existing = session.scalar(
            select(ProcessedMessage).where(
                ProcessedMessage.user_id == user.id,
                ProcessedMessage.dedupe_key == dedupe_key,
            )
        )
        if existing and existing.status in {"event_created", "skipped_exists"}:
            stats["skipped_dup"] += 1
            continue

        if not is_invite_candidate(mail.message):
            continue

        stats["candidates"] += 1
        draft = parse_message(mail.message)
        record = existing or ProcessedMessage(
            user_id=user.id,
            imap_uid=mail.uid,
            message_id=message_id,
            dedupe_key=dedupe_key,
            subject=str(mail.message.get("Subject", "")),
            sender=str(mail.message.get("From", "")),
        )

        if not draft:
            record.status = "parse_failed"
            record.details_json = json.dumps({"reason": "Не удалось разобрать TNEF/ICS"}, ensure_ascii=False)
            session.add(record)
            stats["failed"] += 1
            continue

        event_exists = session.scalar(
            select(CalendarEventRecord).where(
                CalendarEventRecord.user_id == user.id,
                CalendarEventRecord.ics_uid == draft.uid,
            )
        )
        if event_exists:
            record.status = "skipped_exists"
            record.details_json = json.dumps(draft_to_dict(draft), ensure_ascii=False)
            session.add(record)
            stats["skipped_dup"] += 1
            continue

        event_details = json.dumps(draft_to_dict(draft), ensure_ascii=False)

        if settings.dry_run or not settings.create_events_enabled:
            record.status = "candidate_dry_run"
            record.details_json = event_details
            session.add(record)
            continue

        try:
            with session.begin_nested():
                caldav.save_event(cal_name, draft)
                session.add(
                    CalendarEventRecord(
                        user_id=user.id,
                        ics_uid=draft.uid,
                        source_message_id=message_id,
                        summary=draft.summary,
                    )
                )
                record.status = "event_created"
                record.details_json = event_details
                session.add(record)
                session.flush()
            stats["created"] += 1
        except Exception as exc:
            from sqlalchemy.exc import IntegrityError

            if isinstance(exc, IntegrityError) or "uq_user_ics_uid" in str(exc):
                record.status = "skipped_exists"
                record.details_json = event_details
                session.add(record)
                stats["skipped_dup"] += 1
            else:
                record.status = "write_failed"
                payload = draft_to_dict(draft)
                payload["error"] = str(exc)
                record.details_json = json.dumps(payload, ensure_ascii=False)
                session.add(record)
                stats["failed"] += 1
                logger.exception("CalDAV write failed for %s", user.email)

        session.flush()

    session.commit()
    return stats


def run_incoming_job(session: Session, settings: Settings, job: JobDefinition) -> None:
    run = JobRun(job_id=job.id, status="running")
    session.add(run)
    session.commit()

    users = session.scalars(select(User).where(User.enabled.is_(True))).all()
    totals = {"users": len(users), "created": 0, "candidates": 0, "failed": 0}
    per_user: dict[str, dict] = {}

    for user in users:
        if not user.imap_password_enc:
            continue
        user_run = JobRun(job_id=job.id, user_id=user.id, status="running")
        session.add(user_run)
        session.commit()
        try:
            stats = run_incoming_for_user(session, settings, user)
            per_user[user.email] = stats
            totals["created"] += stats["created"]
            totals["candidates"] += stats["candidates"]
            totals["failed"] += stats["failed"]
            _finish_run(
                session,
                user_run,
                "success",
                f"создано {stats['created']}, кандидатов {stats['candidates']}",
                stats,
            )
        except Exception as exc:
            _finish_run(session, user_run, "failed", str(exc), {"error": str(exc)})
            logger.exception("incoming job failed for %s", user.email)

    _finish_run(
        session,
        run,
        "success",
        f"пользователей {totals['users']}, создано {totals['created']}",
        {"totals": totals, "per_user": per_user},
    )


def reparse_message_record(session: Session, settings: Settings, message_id: int) -> str:
    """Перечитывает письмо из IMAP и обновляет details_json (для отладки)."""
    row = session.get(ProcessedMessage, message_id)
    if not row:
        raise ValueError("Письмо не найдено")
    user = session.get(User, row.user_id)
    if not user or not user.imap_password_enc:
        raise ValueError("Пользователь или пароль IMAP не настроены")
    if not row.imap_uid:
        raise ValueError("Нет IMAP UID — перечитать нельзя")

    imap_pass = decrypt(settings.secret_key, user.imap_password_enc)
    imap = ImapClient(settings.imap_host, settings.imap_port, user.email, imap_pass)
    mail = imap.fetch_uid(row.imap_uid)
    if not mail:
        raise ValueError(f"Письмо UID {row.imap_uid} не найдено в INBOX")

    draft = parse_message(mail.message)
    if not draft:
        row.status = "parse_failed"
        row.details_json = json.dumps({"reason": "Не удалось разобрать TNEF/ICS"}, ensure_ascii=False)
        session.add(row)
        session.commit()
        return "parse_failed"

    row.details_json = json.dumps(draft_to_dict(draft), ensure_ascii=False)
    if row.status == "parse_failed":
        row.status = "candidate_dry_run" if (settings.dry_run or not settings.create_events_enabled) else row.status
    session.add(row)
    session.commit()
    return "ok"
