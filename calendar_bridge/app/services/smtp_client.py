from __future__ import annotations

import logging
import smtplib
import ssl
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

from app.services.invite_parser import InviteDraft, draft_to_ics

logger = logging.getLogger(__name__)


class SmtpClient:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        from_email: str,
        from_name: str = "Calendar Bridge",
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.from_email = from_email or user
        self.from_name = from_name

    def send_ics_invite(
        self,
        to_email: str,
        draft: InviteDraft,
        *,
        dry_run: bool = True,
    ) -> str:
        msg_id = make_msgid(domain="rubda-bridge.local")
        subject = f"Приглашение: {draft.summary}"
        plain = (
            f"Приглашение на встречу «{draft.summary}».\n\n"
            f"Файл .ics во вложении — откройте его в календаре.\n\n"
            f"— Calendar Bridge (АБД)"
        )
        ics_bytes = draft_to_ics(draft)
        filename = f"invite-{draft.uid[:32]}.ics"

        if dry_run:
            logger.info("[DRY RUN] SMTP → %s subject=%s", to_email, subject)
            return msg_id

        msg = MIMEMultipart("mixed")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = formataddr((self.from_name, self.from_email))
        msg["To"] = to_email
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = msg_id

        msg.attach(MIMEText(plain, "plain", "utf-8"))
        part = MIMEApplication(ics_bytes, Name=filename)
        part["Content-Disposition"] = f'attachment; filename="{filename}"'
        part["Content-Type"] = f'text/calendar; method=REQUEST; charset=utf-8; name="{filename}"'
        msg.attach(part)

        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(self.host, self.port, context=ctx, timeout=120) as smtp:
            smtp.login(self.user, self.password)
            smtp.sendmail(self.from_email, [to_email], msg.as_string())
        logger.info("Отправлено приглашение → %s", to_email)
        return msg_id
