"""Подписи задач и расшифровка итогов для админки."""

from __future__ import annotations

import json
from email.header import decode_header, make_header
from email.utils import parseaddr

JOB_LABELS: dict[str, str] = {
    "incoming_invites": "Входящие приглашения (winmail → календарь)",
    "outgoing_invites": "Исходящие приглашения (.ics внешним участникам)",
    "sync_audit": "Проверка почты и календаря (IMAP + CalDAV)",
    "attachment_links": "Вложения во встречах (заготовка)",
}

JOB_HELP: dict[str, str] = {
    "incoming_invites": "Сканирует IMAP, ищет winmail/no_name, при находке — создаёт встречу в Яндекс Календаре.",
    "outgoing_invites": "Смотрит CalDAV: встречи с участниками из списка организаций → досылает .ics.",
    "sync_audit": "Проверяет, что у каждого пользователя открываются почта (IMAP) и календарь (CalDAV).",
    "attachment_links": "Пока не реализовано.",
}


def explain_run_summary(slug: str, summary: str, details_json: str = "") -> str:
    """Человекочитаемая расшифровка строки итога."""
    s = (summary or "").strip()
    if not s:
        return "—"

    if slug == "incoming_invites":
        if "пользователей" in s and "создано" in s:
            return s.replace("пользователей", "ящиков обработано").replace(
                "создано", "встреч добавлено в календарь"
            )
        if "кандидатов" in s:
            return s.replace("создано", "встреч создано").replace(
                "кандидатов", "писем-приглашений найдено"
            )
        return s

    if slug == "outgoing_invites":
        return s.replace("отправлено", "писем .ics отправлено").replace(
            "пропущено дублей", "уже отправляли раньше (пропуск)"
        )

    if slug == "sync_audit":
        if "проблем" in s:
            n_users = "?"
            try:
                data = json.loads(details_json or "{}")
                n_users = str(data.get("per_user", {}) and len(data.get("per_user", {})))
            except json.JSONDecodeError:
                pass
            base = s.replace("проверено", "пользователей проверено").replace(
                "проблем", "ошибок подключения"
            )
            return f"{base}. Для каждого: доступна ли почта (IMAP) и календарь (CalDAV)."
        return s

    return s


def decode_mime_header(value: str) -> str:
    """Декодирует =?utf-8?B?...?= в читаемый текст."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeError, ValueError):
        return value


def format_email_address(raw: str) -> str:
    """Из «Иван <ivan@mail.ru>» → ivan@mail.ru или как есть."""
    name, addr = parseaddr(raw or "")
    if addr:
        return addr
    return decode_mime_header(raw)


def explain_message_status(
    status: str,
    details_json: str = "",
    *,
    dry_run: bool = True,
    create_events_enabled: bool = False,
) -> dict[str, str]:
    """Человекочитаемый результат обработки одного письма."""
    details: dict = {}
    try:
        details = json.loads(details_json or "{}")
    except json.JSONDecodeError:
        pass

    event_title = (details.get("summary") or "").strip()
    source = (details.get("source") or "").strip()
    reason = (details.get("reason") or details.get("error") or "").strip()

    source_hint = ""
    if source:
        source_hint = f" Источник: {source}."

    if status == "candidate_dry_run":
        why = []
        if dry_run:
            why.append("включён DRY RUN")
        if not create_events_enabled:
            why.append("CREATE_EVENTS_ENABLED=false")
        mode = ", ".join(why) if why else "запись отключена"
        detail = (
            f"Найдено приглашение во вложении.{source_hint} "
            f"Встреча «{event_title or 'без названия'}» должна попасть в Яндекс Календарь, "
            f"но сейчас не создана ({mode})."
        )
        return {"label": "Распознано, не создано", "detail": detail, "css": "warn"}

    if status == "event_created":
        return {
            "label": "Встреча создана",
            "detail": f"Добавлено в календарь: «{event_title or 'без названия'}».{source_hint}",
            "css": "ok",
        }

    if status == "parse_failed":
        return {
            "label": "Не разобрать",
            "detail": reason or f"Письмо похоже на приглашение, но TNEF/ICS не удалось прочитать.{source_hint}",
            "css": "error",
        }

    if status == "skipped_exists":
        return {
            "label": "Уже в календаре",
            "detail": f"Такая встреча уже есть — повторно не добавляли.{source_hint}",
            "css": "muted",
        }

    if status == "write_failed":
        return {
            "label": "Ошибка CalDAV",
            "detail": reason or "Не удалось записать встречу в Яндекс Календарь.",
            "css": "error",
        }

    if status == "detected":
        return {
            "label": "Обнаружено",
            "detail": "Письмо отмечено как кандидат, дальнейшая обработка не завершена.",
            "css": "muted",
        }

    return {"label": status, "detail": reason or "—", "css": "muted"}


def parse_details_json(raw: str) -> dict:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


def explain_outgoing_status(
    status: str,
    details_json: str = "",
    *,
    dry_run: bool = True,
    outgoing_send_enabled: bool = False,
) -> dict[str, str]:
    details = parse_details_json(details_json)
    subject = (details.get("subject") or "").strip()
    to = (details.get("to") or "").strip()
    reason = (details.get("error") or "").strip()
    event_title = (details.get("event") or {}).get("summary") or ""

    if status == "dry_run":
        why = []
        if dry_run:
            why.append("DRY RUN")
        if not outgoing_send_enabled:
            why.append("OUTGOING_SEND_ENABLED=false")
        mode = ", ".join(why) if why else "отправка отключена"
        return {
            "label": "Запланировано, не отправлено",
            "detail": (
                f"Письмо «{subject or 'Приглашение'}» → {to or '?'}. "
                f"Встреча «{event_title or '—'}». Не отправлено ({mode})."
            ),
            "css": "warn",
        }

    if status == "sent":
        return {
            "label": "Отправлено",
            "detail": f"«{subject}» → {to}. Встреча «{event_title or '—'}».",
            "css": "ok",
        }

    if status == "failed":
        return {
            "label": "Ошибка отправки",
            "detail": reason or f"Не удалось отправить → {to}.",
            "css": "error",
        }

    return {"label": status, "detail": reason or "—", "css": "muted"}
