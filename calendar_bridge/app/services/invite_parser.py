from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from email.message import Message
from typing import Any

from tnefparse import TNEF
from icalendar import Calendar, Event

logger = logging.getLogger(__name__)

SUSPICIOUS_NAMES = {"winmail.dat", "winmail", "no_name", "noname"}
SUSPICIOUS_TYPES = {
    "application/ms-tnef",
    "application/vnd.ms-tnef",
    "text/calendar",
}


@dataclass
class InviteDraft:
    uid: str
    summary: str
    description: str
    dtstart: datetime | None
    dtend: datetime | None
    organizer_email: str = ""
    organizer_name: str = ""
    location: str = ""
    attendees: list[str] = field(default_factory=list)
    attachments: list[tuple[str, bytes]] = field(default_factory=list)
    source: str = "unknown"
    raw_ics: bytes | None = None


def is_invite_candidate(message: Message) -> bool:
    for part in message.walk():
        if part.is_multipart():
            continue
        name = (part.get_filename() or "").strip().lower()
        ctype = part.get_content_type().lower()
        if ctype in SUSPICIOUS_TYPES:
            return True
        if name in SUSPICIOUS_NAMES or name.endswith((".ics", ".dat")):
            return True
    subj = (message.get("Subject") or "").lower()
    if any(k in subj for k in ("приглашение", "invitation", "встреча", "meeting")):
        for part in message.walk():
            if not part.is_multipart() and part.get_payload(decode=True):
                return True
    return False


def extract_parts(message: Message) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        name = (part.get_filename() or "").strip()
        ctype = part.get_content_type().lower()
        payload = part.get_payload(decode=True) or b""
        normalized = name.lower()
        if (
            ctype in SUSPICIOUS_TYPES
            or normalized in SUSPICIOUS_NAMES
            or normalized.endswith((".ics", ".dat"))
        ):
            found.append(
                {
                    "filename": name or "(без имени)",
                    "content_type": ctype,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "payload": payload,
                }
            )
    return found


def parse_message(message: Message) -> InviteDraft | None:
    """Разбирает все вложения и выбирает наиболее полный вариант встречи.

    Exchange часто кладёт «пустой» text/calendar в тело и полный ICS/TNEF в winmail.dat —
    раньше брался первый попавшийся кусок без DTSTART/участников.
    """
    drafts: list[InviteDraft] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        name = (part.get_filename() or "").lower()
        ctype = part.get_content_type().lower()
        payload = part.get_payload(decode=True) or b""
        if not payload:
            continue
        if ctype == "text/calendar" or name.endswith(".ics"):
            draft = parse_ics(payload)
            if draft:
                drafts.append(draft)
        if ctype in SUSPICIOUS_TYPES or name in SUSPICIOUS_NAMES or name.endswith(".dat"):
            draft = parse_tnef(payload)
            if draft:
                drafts.append(draft)
    if not drafts:
        return None
    if len(drafts) == 1:
        return drafts[0]
    return _merge_drafts(drafts)


def _draft_completeness_score(draft: InviteDraft) -> int:
    score = 0
    if draft.dtstart:
        score += 20
    if draft.dtend:
        score += 10
    score += min(len(draft.attendees), 10) * 3
    if draft.organizer_email:
        score += 5
    if draft.location:
        score += 3
    if draft.description and len(draft.description) > 20:
        score += 2
    if draft.raw_ics:
        score += min(len(draft.raw_ics) // 200, 15)
    if draft.source in {"tnef-ics-attachment", "tnef-mapi"}:
        score += 8
    return score


def _merge_drafts(drafts: list[InviteDraft]) -> InviteDraft:
    ordered = sorted(drafts, key=_draft_completeness_score, reverse=True)
    base = ordered[0]
    for other in ordered[1:]:
        if not base.dtstart and other.dtstart:
            base.dtstart = other.dtstart
        if not base.dtend and other.dtend:
            base.dtend = other.dtend
        if not base.location and other.location:
            base.location = other.location
        if not base.organizer_email and other.organizer_email:
            base.organizer_email = other.organizer_email
            base.organizer_name = other.organizer_name or base.organizer_name
        if not base.description and other.description:
            base.description = other.description
        for email in other.attendees:
            if email not in base.attendees:
                base.attendees.append(email)
        if (not base.raw_ics or len(base.raw_ics) < len(other.raw_ics or b"")) and other.raw_ics:
            base.raw_ics = other.raw_ics
        if other.source.startswith("tnef") and base.source == "ics" and not base.dtstart:
            base.source = other.source
    return base


def parse_ics(payload: bytes) -> InviteDraft | None:
    try:
        cal = Calendar.from_ical(payload)
    except Exception:
        return None
    events = list(cal.walk("VEVENT"))
    if not events:
        return None
    ev = events[0]
    return _event_to_draft(ev, source="ics", raw_ics=payload)


def parse_tnef(payload: bytes) -> InviteDraft | None:
    try:
        tnef = TNEF(payload)
    except Exception as exc:
        logger.warning("TNEF parse failed: %s", exc)
        return None

    for attachment in tnef.attachments:
        data = getattr(attachment, "data", None) or b""
        name = (getattr(attachment, "name", "") or "").lower()
        if data and (name.endswith(".ics") or data.startswith(b"BEGIN:VCALENDAR")):
            draft = parse_ics(data)
            if draft:
                draft.source = "tnef-ics-attachment"
                return draft

    summary = _tnef_prop(tnef, "subject") or _tnef_prop(tnef, "messageclass") or "Встреча"
    dtstart = _tnef_date(tnef, "date_start") or _tnef_date(tnef, "date_sent")
    dtend = _tnef_date(tnef, "date_end") or dtstart
    uid_seed = f"{summary}|{dtstart}|{hashlib.sha256(payload).hexdigest()[:16]}"
    uid = f"bridge-tnef-{hashlib.sha256(uid_seed.encode()).hexdigest()[:24]}@rubda-bridge"

    attachments: list[tuple[str, bytes]] = []
    for att in tnef.attachments:
        data = getattr(att, "data", None) or b""
        name = getattr(att, "name", None) or "attachment.bin"
        if data and not name.lower().endswith(".ics"):
            attachments.append((name, data))

    if not dtstart and not attachments:
        return None

    return InviteDraft(
        uid=uid,
        summary=str(summary),
        description="Импортировано из winmail/TNEF (Calendar Bridge)",
        dtstart=dtstart,
        dtend=dtend,
        attachments=attachments,
        source="tnef-mapi",
    )


def _tnef_prop(tnef: TNEF, attr: str) -> str | None:
    val = getattr(tnef, attr, None)
    if val is None:
        return None
    text = str(val).strip()
    return text or None


def _tnef_date(tnef: TNEF, attr: str) -> datetime | None:
    val = getattr(tnef, attr, None)
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    return None


def _parse_cal_address(prop) -> str:
    if prop is None:
        return ""
    params = getattr(prop, "params", {}) or {}
    if params.get("EMAIL"):
        return str(params.get("EMAIL")).strip()
    text = str(prop)
    lower = text.lower()
    if "mailto:" in lower:
        idx = lower.index("mailto:") + 7
        addr = text[idx:].split(";", 1)[0].split("?", 1)[0].strip()
        if addr:
            return addr
    if ":" in text:
        return text.split(":", 1)[-1].split(";", 1)[0].strip()
    return text.strip()


def _attendees_from_event(ev: Event) -> list[str]:
    raw = ev.get("ATTENDEE")
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        email = _parse_cal_address(item)
        if email and email not in seen:
            seen.add(email)
            out.append(email)
    return out


def _dt_from_component(prop) -> datetime | None:
    if not prop:
        return None
    value = prop.dt
    if isinstance(value, datetime):
        return value
    if hasattr(value, "year"):  # date
        from datetime import time

        return datetime.combine(value, time.min)
    return None


def _event_to_draft(ev: Event, *, source: str, raw_ics: bytes | None = None) -> InviteDraft:
    uid = str(ev.get("UID", "")).strip() or hashlib.sha256(raw_ics or b"").hexdigest()
    summary = str(ev.get("SUMMARY", "Встреча"))
    description = str(ev.get("DESCRIPTION", "") or "")
    location = str(ev.get("LOCATION", "") or "")
    start = _dt_from_component(ev.get("DTSTART"))
    end = _dt_from_component(ev.get("DTEND"))
    organizer = ev.get("ORGANIZER")
    org_email = _parse_cal_address(organizer)
    org_name = ""
    if organizer is not None:
        params = getattr(organizer, "params", {}) or {}
        org_name = str(params.get("CN", "") or "")

    return InviteDraft(
        uid=uid,
        summary=summary,
        description=description,
        dtstart=start,
        dtend=end,
        organizer_email=org_email,
        organizer_name=org_name,
        location=location,
        attendees=_attendees_from_event(ev),
        source=source,
        raw_ics=raw_ics,
    )


def draft_to_ics(draft: InviteDraft) -> bytes:
    if draft.raw_ics:
        cal = Calendar.from_ical(draft.raw_ics)
        if "METHOD" in cal:
            del cal["METHOD"]
        return cal.to_ical()

    cal = Calendar()
    cal.add("prodid", "-//ABD//Calendar Bridge//RU")
    cal.add("version", "2.0")
    ev = Event()
    ev.add("uid", draft.uid)
    ev.add("summary", draft.summary)
    if draft.description:
        ev.add("description", draft.description)
    if draft.location:
        ev.add("location", draft.location)
    if draft.dtstart:
        ev.add("dtstart", draft.dtstart)
    if draft.dtend:
        ev.add("dtend", draft.dtend)
    if draft.organizer_email:
        ev.add("organizer", f"mailto:{draft.organizer_email}")
    for email in draft.attendees:
        ev.add("attendee", f"mailto:{email}")
    cal.add_component(ev)
    return cal.to_ical()
