from __future__ import annotations

from typing import Any

from app.services.invite_parser import InviteDraft, draft_to_ics


def _fmt_dt(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def draft_to_dict(draft: InviteDraft) -> dict[str, Any]:
    """Параметры встречи для отладки в админке."""
    ics_preview = ""
    if draft.raw_ics:
        ics_preview = draft.raw_ics.decode("utf-8", errors="replace")
    else:
        try:
            ics_preview = draft_to_ics(draft).decode("utf-8", errors="replace")
        except Exception:
            ics_preview = ""

    return {
        "uid": draft.uid,
        "summary": draft.summary,
        "description": draft.description,
        "location": draft.location,
        "dtstart": _fmt_dt(draft.dtstart),
        "dtend": _fmt_dt(draft.dtend),
        "organizer_email": draft.organizer_email,
        "organizer_name": draft.organizer_name,
        "organizer_name": draft.organizer_name,
        "attendees": draft.attendees,
        "source": draft.source,
        "attachments": [
            {"filename": name, "size_bytes": len(data)}
            for name, data in draft.attachments
        ],
        "ics_preview": ics_preview[:12000],
    }


def build_outgoing_email_preview(
    *,
    to_email: str,
    draft: InviteDraft,
    from_email: str,
    from_name: str = "Calendar Bridge",
) -> dict[str, Any]:
    """Что уйдёт участнику по SMTP (текст + .ics)."""
    subject = f"Приглашение: {draft.summary}"
    body_text = (
        f"Приглашение на встречу «{draft.summary}».\n\n"
        f"Файл .ics во вложении — откройте его в календаре.\n\n"
        f"— Calendar Bridge (АБД)"
    )
    ics_bytes = draft_to_ics(draft)
    filename = f"invite-{draft.uid[:32]}.ics"
    return {
        "to": to_email,
        "from": from_email,
        "from_name": from_name,
        "subject": subject,
        "body_text": body_text,
        "attachment_filename": filename,
        "attachment_content_type": "text/calendar; method=REQUEST",
        "ics_preview": ics_bytes.decode("utf-8", errors="replace")[:12000],
        "event": draft_to_dict(draft),
    }
