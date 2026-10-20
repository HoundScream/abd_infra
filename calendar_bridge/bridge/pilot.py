from __future__ import annotations

import email
import hashlib
import imaplib
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path

import caldav
from icalendar import Calendar
from dotenv import load_dotenv


DATA_DIR = Path("/app/data")
SUSPICIOUS_NAMES = {"winmail.dat", "winmail", "no_name", "noname"}
SUSPICIOUS_TYPES = {"application/ms-tnef", "application/vnd.ms-tnef", "text/calendar"}


def env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Не заполнена переменная {name}")
    return value


def connect_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA_DIR / "bridge.sqlite3")
    db.execute(
        """CREATE TABLE IF NOT EXISTS messages (
        mailbox TEXT NOT NULL, uid TEXT NOT NULL, digest TEXT NOT NULL,
        status TEXT NOT NULL, details TEXT, processed_at TEXT NOT NULL,
        PRIMARY KEY (mailbox, uid)
        )"""
    )
    return db


def interesting_parts(message: Message) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        name = (part.get_filename() or "").strip()
        content_type = part.get_content_type().lower()
        normalized_name = name.lower()
        suspicious = (
            content_type in SUSPICIOUS_TYPES
            or normalized_name in SUSPICIOUS_NAMES
            or normalized_name.endswith((".ics", ".dat"))
        )
        if suspicious:
            payload = part.get_payload(decode=True) or b""
            found.append(
                {
                    "filename": name or "(без имени)",
                    "content_type": content_type,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
    return found


def calendar_payload(message: Message) -> bytes | None:
    """Return the first standards-based iCalendar payload from a message."""
    for part in message.walk():
        if part.is_multipart():
            continue
        name = (part.get_filename() or "").lower()
        if part.get_content_type().lower() == "text/calendar" or name.endswith(".ics"):
            payload = part.get_payload(decode=True) or b""
            if payload:
                return payload
    return None


def normalized_ics(payload: bytes) -> tuple[bytes, str]:
    """Validate an invite and return normalized bytes plus VEVENT UID."""
    parsed = Calendar.from_ical(payload)
    events = parsed.walk("VEVENT")
    if not events:
        raise ValueError("В iCalendar нет VEVENT")
    uid = str(events[0].get("UID", "")).strip()
    if not uid:
        raise ValueError("В VEVENT нет UID")
    # METHOD belongs to iTIP email transport. A CalDAV collection stores the
    # resulting calendar object without METHOD; Yandex otherwise returns 409.
    if "METHOD" in parsed:
        del parsed["METHOD"]
    result = parsed.to_ical().replace(
        b"TZID=Russian Standard Time", b"TZID=Europe/Moscow"
    )
    return result, uid


def test_calendar(login: str, password: str):
    client = caldav.DAVClient(
        url=os.getenv("CALDAV_URL", "https://caldav.yandex.ru"),
        username=login,
        password=password,
    )
    principal = client.principal()
    wanted = os.getenv("TEST_CALENDAR_NAME", "Calendar Bridge Test")
    for existing in principal.calendars():
        if str(existing.name) == wanted:
            return existing
    logging.info("Создаётся отдельный тестовый календарь: %s", wanted)
    return principal.make_calendar(name=wanted)


def write_test_event(login: str, password: str, payload: bytes) -> str:
    prepared, event_uid = normalized_ics(payload)
    calendar = test_calendar(login, password)
    calendar.save_event(prepared)
    return event_uid


def scan_once() -> None:
    if os.getenv("AUTH_MODE", "app_password") != "app_password":
        raise RuntimeError("Пилот пока запускается в AUTH_MODE=app_password; service_app подключается следующим этапом")

    login = required("YANDEX_LOGIN")
    password = required("YANDEX_APP_PASSWORD")
    calendar_password = os.getenv("YANDEX_CALENDAR_APP_PASSWORD", password).strip() or password
    host = os.getenv("IMAP_HOST", "imap.yandex.ru")
    port = int(os.getenv("IMAP_PORT", "993"))
    lookback = int(os.getenv("LOOKBACK_DAYS", "14"))
    since = (datetime.now(timezone.utc) - timedelta(days=lookback)).strftime("%d-%b-%Y")
    dry_run = env_bool("DRY_RUN", True)
    create_events = env_bool("CREATE_EVENTS_ENABLED", False)
    db = connect_db()

    logging.info("Подключение к IMAP %s:%s, ящик %s", host, port, login)
    with imaplib.IMAP4_SSL(host, port) as client:
        client.login(login, password)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("Не удалось открыть INBOX")
        status, data = client.uid("search", None, "SINCE", since)
        if status != "OK":
            raise RuntimeError("Не удалось выполнить поиск в IMAP")
        uids = data[0].split()
        logging.info("Писем за период: %d", len(uids))

        detected = 0
        for raw_uid in uids:
            uid = raw_uid.decode("ascii")
            previous = db.execute(
                "SELECT status FROM messages WHERE mailbox=? AND uid=?", (login, uid)
            ).fetchone()
            if previous and not (
                previous[0] == "candidate" and create_events and not dry_run
            ):
                continue
            status, payload = client.uid("fetch", raw_uid, "(RFC822)")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            raw_message = payload[0][1]
            message = email.message_from_bytes(raw_message)
            parts = interesting_parts(message)
            digest = hashlib.sha256(raw_message).hexdigest()
            state = "candidate" if parts else "ignored"
            details = {
                "message_id": message.get("Message-ID", ""),
                "subject": message.get("Subject", ""),
                "from": message.get("From", ""),
                "parts": parts,
                "dry_run": dry_run,
            }
            if parts and create_events and not dry_run:
                ics = calendar_payload(message)
                if ics:
                    try:
                        details["event_uid"] = write_test_event(
                            login, calendar_password, ics
                        )
                        state = "event_created"
                        logging.info(
                            "Создано событие UID=%s из письма UID=%s",
                            details["event_uid"],
                            uid,
                        )
                    except Exception as exc:
                        state = "write_failed"
                        details["write_error"] = str(exc)
                        logging.exception(
                            "Не удалось создать событие из письма UID=%s", uid
                        )
                else:
                    state = "parser_pending"
            db.execute(
                "INSERT OR REPLACE INTO messages VALUES (?, ?, ?, ?, ?, ?)",
                (login, uid, digest, state, json.dumps(details, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
            )
            db.commit()
            if parts:
                detected += 1
                logging.info("Найден кандидат UID=%s: %s", uid, json.dumps(details, ensure_ascii=False))
        logging.info(
            "Новых кандидатов: %d; DRY_RUN=%s; CREATE_EVENTS_ENABLED=%s",
            detected,
            dry_run,
            create_events,
        )


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    interval = int(os.getenv("SCAN_INTERVAL_SECONDS", "60"))
    while True:
        try:
            scan_once()
        except Exception:
            logging.exception("Ошибка прохода; повтор через %d сек.", interval)
        time.sleep(interval)
