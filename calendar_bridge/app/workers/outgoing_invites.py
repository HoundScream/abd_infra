from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.crypto import decrypt
from app.db.models import JobDefinition, JobRun, OutgoingInviteRecord, User
from app.services.caldav_client import CaldavClient
from app.debug_serializers import build_outgoing_email_preview
from app.services.invite_parser import InviteDraft
from app.services.org_domains import domain_matches, list_enabled_domains
from app.services.smtp_client import SmtpClient

logger = logging.getLogger(__name__)


def _domain(email: str) -> str:
    return email.split("@")[-1].lower().strip()


def run_outgoing_for_user(session: Session, settings: Settings, user: User) -> dict:
    cal_pass = decrypt(settings.secret_key, user.caldav_password_enc) or decrypt(
        settings.secret_key, user.imap_password_enc
    )
    cal_name = user.calendar_name or settings.default_calendar_name
    caldav = CaldavClient(settings.caldav_url, user.email, cal_pass)
    own_domain = _domain(user.email)
    allowlist = list_enabled_domains(session)

    smtp: SmtpClient | None = None
    if settings.smtp_user and settings.smtp_password:
        smtp = SmtpClient(
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_user,
            settings.smtp_password,
            settings.smtp_from,
        )

    stats = {
        "events": 0,
        "sent": 0,
        "skipped_dup": 0,
        "skipped_internal": 0,
        "dry_run": settings.dry_run,
        "org_domains": allowlist,
    }
    if not allowlist:
        stats["skipped_no_domains"] = True
        return stats

    events = caldav.list_events(cal_name)

    for ev in events:
        stats["events"] += 1
        external_attendees = [
            a
            for a in ev.get("attendees", [])
            if _domain(a) != own_domain and domain_matches(a, allowlist)
        ]
        if not external_attendees:
            stats["skipped_internal"] += 1
            continue

        draft = InviteDraft(
            uid=ev["uid"],
            summary=ev.get("summary") or "Встреча",
            description="Приглашение отправлено через Calendar Bridge (АБД)",
            dtstart=None,
            dtend=None,
            organizer_email=user.email,
            attendees=external_attendees,
            source="caldav-export",
        )

        for recipient in external_attendees:
            dedupe_key = hashlib.sha256(
                f"{user.id}|{ev['uid']}|{recipient}".encode()
            ).hexdigest()
            exists = session.scalar(
                select(OutgoingInviteRecord).where(
                    OutgoingInviteRecord.user_id == user.id,
                    OutgoingInviteRecord.dedupe_key == dedupe_key,
                )
            )
            if exists:
                stats["skipped_dup"] += 1
                continue

            if not smtp:
                stats["skipped_dup"] += 1
                continue

            dry = settings.dry_run or not settings.outgoing_send_enabled
            preview = build_outgoing_email_preview(
                to_email=recipient,
                draft=draft,
                from_email=settings.smtp_from or settings.smtp_user,
            )
            try:
                msg_id = smtp.send_ics_invite(recipient, draft, dry_run=dry)
                status = "dry_run" if dry else "sent"
                session.add(
                    OutgoingInviteRecord(
                        user_id=user.id,
                        event_uid=ev["uid"],
                        recipient_email=recipient,
                        dedupe_key=dedupe_key,
                        status=status,
                        message_id=msg_id if not dry else "",
                        details_json=json.dumps(preview, ensure_ascii=False),
                    )
                )
                stats["sent"] += 1
            except Exception as exc:
                logger.exception("outgoing invite failed %s → %s", user.email, recipient)
                preview["error"] = str(exc)
                session.add(
                    OutgoingInviteRecord(
                        user_id=user.id,
                        event_uid=ev["uid"],
                        recipient_email=recipient,
                        dedupe_key=dedupe_key,
                        status="failed",
                        message_id=str(exc),
                        details_json=json.dumps(preview, ensure_ascii=False),
                    )
                )

    session.commit()
    return stats


def run_outgoing_job(session: Session, settings: Settings, job: JobDefinition) -> None:
    run = JobRun(job_id=job.id, status="running")
    session.add(run)
    session.commit()

    users = session.scalars(select(User).where(User.enabled.is_(True))).all()
    per_user: dict[str, dict] = {}
    totals = {"sent": 0, "skipped_dup": 0}

    for user in users:
        if not user.caldav_password_enc and not user.imap_password_enc:
            continue
        try:
            stats = run_outgoing_for_user(session, settings, user)
            per_user[user.email] = stats
            totals["sent"] += stats["sent"]
            totals["skipped_dup"] += stats["skipped_dup"]
        except Exception as exc:
            per_user[user.email] = {"error": str(exc)}
            logger.exception("outgoing job failed for %s", user.email)

    run.status = "success"
    run.summary = f"отправлено {totals['sent']}, пропущено дублей {totals['skipped_dup']}"
    run.details_json = json.dumps({"totals": totals, "per_user": per_user}, ensure_ascii=False)
    run.finished_at = datetime.now(timezone.utc)
    session.add(run)
    session.commit()
