from __future__ import annotations

import email
import imaplib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import Message

logger = logging.getLogger(__name__)


@dataclass
class MailMessage:
    uid: str
    raw: bytes
    message: Message


class ImapClient:
    def __init__(self, host: str, port: int, login: str, password: str) -> None:
        self.host = host
        self.port = port
        self.login = login
        self.password = password

    def fetch_since(self, lookback_days: int) -> list[MailMessage]:
        since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
        results: list[MailMessage] = []
        with imaplib.IMAP4_SSL(self.host, self.port) as client:
            client.login(self.login, self.password)
            status, _ = client.select("INBOX", readonly=True)
            if status != "OK":
                raise RuntimeError(f"INBOX недоступен для {self.login}")
            status, data = client.uid("search", None, "SINCE", since)
            if status != "OK":
                raise RuntimeError("IMAP search failed")
            uids = data[0].split() if data and data[0] else []
            logger.info("%s: писем за %d дн. — %d", self.login, lookback_days, len(uids))
            for raw_uid in uids:
                uid = raw_uid.decode("ascii")
                status, payload = client.uid("fetch", raw_uid, "(RFC822)")
                if status != "OK" or not payload or not isinstance(payload[0], tuple):
                    continue
                raw = payload[0][1]
                results.append(MailMessage(uid=uid, raw=raw, message=email.message_from_bytes(raw)))
        return results

    def fetch_uid(self, uid: str) -> MailMessage | None:
        with imaplib.IMAP4_SSL(self.host, self.port) as client:
            client.login(self.login, self.password)
            status, _ = client.select("INBOX", readonly=True)
            if status != "OK":
                raise RuntimeError(f"INBOX недоступен для {self.login}")
            status, payload = client.uid("fetch", uid.encode("ascii"), "(RFC822)")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                return None
            raw = payload[0][1]
            return MailMessage(uid=uid, raw=raw, message=email.message_from_bytes(raw))
