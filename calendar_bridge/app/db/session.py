from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base, ExternalOrgDomain, JobDefinition
from app.services.org_domains import normalize_domain

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    with SessionLocal() as session:
        _seed_jobs(session)
        _seed_org_domains(session)
        session.commit()


def _ensure_columns() -> None:
    """Добавляет новые колонки в существующую БД без Alembic."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE outgoing_invites "
                "ADD COLUMN IF NOT EXISTS details_json TEXT NOT NULL DEFAULT '{}'"
            )
        )


def _seed_jobs(session: Session) -> None:
    defaults = [
        (
            "incoming_invites",
            "Входящие приглашения (winmail / no_name)",
            "Сканирует IMAP, разбирает TNEF/ICS и создаёт событие в Яндекс Календаре",
            get_settings().incoming_interval_seconds,
        ),
        (
            "outgoing_invites",
            "Исходящие приглашения (.ics внешним участникам)",
            "Находит встречи с участниками из списка организаций и досылает .ics",
            get_settings().outgoing_interval_seconds,
        ),
        (
            "sync_audit",
            "Аудит синхронизации",
            "Проверяет CalDAV и фиксирует расхождения / ошибки подключения",
            get_settings().audit_interval_seconds,
        ),
        (
            "attachment_links",
            "Вложения во встречах",
            "Добавляет ссылки на файлы в описание события (обход CalDAV без ATTACH)",
            900,
        ),
    ]
    for slug, title, description, interval in defaults:
        existing = session.scalar(select(JobDefinition).where(JobDefinition.slug == slug))
        if existing:
            # обновляем формулировки без «банки»
            if slug == "outgoing_invites" and (
                "банк" in (existing.title or "").lower()
                or "банк" in (existing.description or "").lower()
            ):
                existing.title = title
                existing.description = description
                session.add(existing)
            continue
        session.add(
            JobDefinition(
                slug=slug,
                title=title,
                description=description,
                interval_seconds=interval,
                enabled=slug != "attachment_links",
            )
        )


def _seed_org_domains(session: Session) -> None:
    """Первый запуск: подтянуть домены из EXTERNAL_DOMAIN_ALLOWLIST, дальше — только UI."""
    count = session.scalar(select(ExternalOrgDomain.id).limit(1))
    if count is not None:
        return
    for domain in get_settings().external_domain_allowlist:
        normalized = normalize_domain(domain)
        if not normalized:
            continue
        session.add(
            ExternalOrgDomain(
                domain=normalized,
                org_name="",
                enabled=True,
                notes="импорт из EXTERNAL_DOMAIN_ALLOWLIST",
            )
        )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
