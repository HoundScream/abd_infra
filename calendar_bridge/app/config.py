from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    secret_key: str
    admin_password: str

    imap_host: str
    imap_port: int
    caldav_url: str

    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str

    dry_run: bool
    create_events_enabled: bool
    outgoing_send_enabled: bool
    lookback_days: int
    default_calendar_name: str
    external_domain_allowlist: tuple[str, ...]

    scheduler_enabled: bool
    incoming_interval_seconds: int
    outgoing_interval_seconds: int
    audit_interval_seconds: int


@lru_cache
def get_settings() -> Settings:
    domains = os.getenv(
        "EXTERNAL_DOMAIN_ALLOWLIST",
        "sberbank.ru,vtb.ru,mail.ru,raiffeisen.ru",
    )
    return Settings(
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg2://bridge:bridge@postgres:5432/bridge",
        ),
        secret_key=os.getenv("SECRET_KEY", "change-me-in-production"),
        admin_password=os.getenv("ADMIN_PASSWORD", "admin"),
        imap_host=os.getenv("IMAP_HOST", "imap.yandex.ru"),
        imap_port=int(os.getenv("IMAP_PORT", "993")),
        caldav_url=os.getenv("CALDAV_URL", "https://caldav.yandex.ru"),
        smtp_host=os.getenv("SMTP_HOST", "smtp.yandex.ru"),
        smtp_port=int(os.getenv("SMTP_PORT", "465")),
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "")),
        dry_run=_bool("DRY_RUN", True),
        create_events_enabled=_bool("CREATE_EVENTS_ENABLED", False),
        outgoing_send_enabled=_bool("OUTGOING_SEND_ENABLED", False),
        lookback_days=int(os.getenv("LOOKBACK_DAYS", "14")),
        default_calendar_name=os.getenv("CALENDAR_NAME", "Основной"),
        external_domain_allowlist=tuple(
            d.strip().lower() for d in domains.split(",") if d.strip()
        ),
        scheduler_enabled=_bool("SCHEDULER_ENABLED", True),
        incoming_interval_seconds=int(os.getenv("INCOMING_INTERVAL_SECONDS", "120")),
        outgoing_interval_seconds=int(os.getenv("OUTGOING_INTERVAL_SECONDS", "300")),
        audit_interval_seconds=int(os.getenv("AUDIT_INTERVAL_SECONDS", "600")),
    )
