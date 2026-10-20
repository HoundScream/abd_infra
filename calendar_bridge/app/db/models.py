from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    imap_password_enc: Mapped[str] = mapped_column(Text, default="")
    caldav_password_enc: Mapped[str] = mapped_column(Text, default="")
    calendar_name: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    job_runs: Mapped[list["JobRun"]] = relationship(back_populates="user")
    processed_messages: Mapped[list["ProcessedMessage"]] = relationship(back_populates="user")
    calendar_events: Mapped[list["CalendarEventRecord"]] = relationship(back_populates="user")


class JobDefinition(Base):
    __tablename__ = "job_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    runs: Mapped[list["JobRun"]] = relationship(back_populates="job")


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_definitions.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="running")  # running|success|failed|skipped
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    details_json: Mapped[str] = mapped_column(Text, default="{}")

    job: Mapped["JobDefinition"] = relationship(back_populates="runs")
    user: Mapped["User | None"] = relationship(back_populates="job_runs")


class ProcessedMessage(Base):
    __tablename__ = "processed_messages"
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_user_dedupe"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    imap_uid: Mapped[str] = mapped_column(String(64), default="")
    message_id: Mapped[str] = mapped_column(String(512), default="")
    dedupe_key: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="detected")
    subject: Mapped[str] = mapped_column(String(512), default="")
    sender: Mapped[str] = mapped_column(String(512), default="")
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="processed_messages")


class CalendarEventRecord(Base):
    __tablename__ = "calendar_events"
    __table_args__ = (UniqueConstraint("user_id", "ics_uid", name="uq_user_ics_uid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    ics_uid: Mapped[str] = mapped_column(String(512))
    source_message_id: Mapped[str] = mapped_column(String(512), default="")
    caldav_href: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="calendar_events")


class OutgoingInviteRecord(Base):
    __tablename__ = "outgoing_invites"
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_outgoing_dedupe"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_uid: Mapped[str] = mapped_column(String(512))
    recipient_email: Mapped[str] = mapped_column(String(255))
    dedupe_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="sent")
    message_id: Mapped[str] = mapped_column(String(512), default="")
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExternalOrgDomain(Base):
    """Домены внешних организаций: на встречи с ними досылаем .ics."""

    __tablename__ = "external_org_domains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    org_name: Mapped[str] = mapped_column(String(255), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
