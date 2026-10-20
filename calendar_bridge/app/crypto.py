from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _fernet(secret_key: str) -> Fernet:
    digest = hashlib.sha256(secret_key.encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt(secret_key: str, plain: str) -> str:
    if not plain:
        return ""
    return _fernet(secret_key).encrypt(plain.encode()).decode()


def decrypt(secret_key: str, token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet(secret_key).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Не удалось расшифровать пароль") from exc
