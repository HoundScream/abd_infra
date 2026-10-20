from __future__ import annotations

import logging

import caldav
from icalendar import Calendar

from app.services.invite_parser import InviteDraft, draft_to_ics

logger = logging.getLogger(__name__)


class CaldavClient:
    def __init__(self, url: str, login: str, password: str) -> None:
        self.client = caldav.DAVClient(url=url, username=login, password=password)
        self.login = login

    def get_calendar(self, name: str | None) -> caldav.objects.Calendar:
        principal = self.client.principal()
        calendars = principal.calendars()
        if name:
            for cal in calendars:
                if str(cal.name) == name:
                    return cal
        if calendars:
            return calendars[0]
        return principal.make_calendar(name=name or "Calendar Bridge")

    def event_exists(self, calendar: caldav.objects.Calendar, ics_uid: str) -> bool:
        for ev in calendar.events():
            try:
                ical = Calendar.from_ical(ev.data)
                for component in ical.walk("VEVENT"):
                    if str(component.get("UID", "")).strip() == ics_uid:
                        return True
            except Exception:
                continue
        return False

    def save_event(self, calendar_name: str | None, draft: InviteDraft) -> str:
        calendar = self.get_calendar(calendar_name)
        if self.event_exists(calendar, draft.uid):
            logger.info("Событие UID=%s уже есть у %s", draft.uid, self.login)
            return draft.uid
        payload = draft_to_ics(draft).replace(
            b"TZID=Russian Standard Time", b"TZID=Europe/Moscow"
        )
        calendar.save_event(payload)
        logger.info("Создано событие UID=%s у %s", draft.uid, self.login)
        return draft.uid

    def list_events(self, calendar_name: str | None) -> list[dict]:
        calendar = self.get_calendar(calendar_name)
        items: list[dict] = []
        for ev in calendar.events():
            try:
                ical = Calendar.from_ical(ev.data)
                for component in ical.walk("VEVENT"):
                    uid = str(component.get("UID", "")).strip()
                    summary = str(component.get("SUMMARY", ""))
                    attendees = [
                        str(a).replace("mailto:", "").split(":")[-1]
                        for a in component.get("ATTENDEE", [])
                    ]
                    organizer = component.get("ORGANIZER")
                    org = str(organizer).replace("mailto:", "").split(":")[-1] if organizer else ""
                    items.append(
                        {
                            "uid": uid,
                            "summary": summary,
                            "organizer": org,
                            "attendees": attendees,
                            "href": str(getattr(ev, "url", "")),
                        }
                    )
            except Exception as exc:
                logger.warning("Не удалось прочитать событие: %s", exc)
        return items

    def ping(self) -> bool:
        try:
            self.client.principal()
            return True
        except Exception as exc:
            logger.warning("CalDAV ping failed for %s: %s", self.login, exc)
            return False
