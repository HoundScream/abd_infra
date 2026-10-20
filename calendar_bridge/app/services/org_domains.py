"""Домены внешних организаций для исходящих .ics."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExternalOrgDomain


def normalize_domain(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value.startswith("@"):
        value = value[1:]
    if value.startswith("*."):
        value = value[2:]
    if value.startswith("."):
        value = value[1:]
    if value.startswith("www."):
        value = value[4:]
    # на случай, если вставили email
    if "@" in value:
        value = value.split("@")[-1]
    return value.strip(".")


def domain_matches(email_or_domain: str, patterns: list[str]) -> bool:
    """email@sub.corp.ru совпадает с corp.ru и sub.corp.ru."""
    text = (email_or_domain or "").strip().lower()
    if "@" in text:
        text = text.split("@")[-1]
    text = text.strip(".")
    if not text or not patterns:
        return False
    for pattern in patterns:
        p = pattern.strip(".").lower()
        if not p:
            continue
        if text == p or text.endswith("." + p):
            return True
    return False


def list_enabled_domains(session: Session) -> list[str]:
    rows = session.scalars(
        select(ExternalOrgDomain).where(ExternalOrgDomain.enabled.is_(True)).order_by(ExternalOrgDomain.domain)
    ).all()
    return [r.domain for r in rows]
