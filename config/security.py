"""Модуль безопасности: маскирование и шифрование чувствительных данных (Этап P1)."""

import base64
import hashlib
import logging
from typing import Optional
from cryptography.fernet import Fernet

logger = logging.getLogger("security")


def mask_secret(secret: Optional[str], show_first: int = 4, show_last: int = 2) -> str:
    """Безопасное маскирование секретных ключей, паролей и токенов для логов.
    
    Пример: 'xpl_b30f5afa...' -> 'xpl_****...*'
    """
    if not secret:
        return "<empty>"
    if len(secret) <= (show_first + show_last):
        return "*" * len(secret)
    return f"{secret[:show_first]}{'*' * (len(secret) - show_first - show_last)}{secret[-show_last:]}"


def derive_key(secret_phrase: str) -> bytes:
    """Генерация 32-байтового ключа Fernet из секретной фразы."""
    digest = hashlib.sha256(secret_phrase.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class SecretVault:
    """Шифрование и расшифрование конфиденциальных строк."""

    def __init__(self, master_key: Optional[str] = None):
        key_bytes = derive_key(master_key or "krons_trading_bot_default_salt")
        self._fernet = Fernet(key_bytes)

    def encrypt(self, plain_text: str) -> str:
        """Зашифровать строку."""
        if not plain_text:
            return ""
        encrypted = self._fernet.encrypt(plain_text.encode("utf-8"))
        return encrypted.decode("utf-8")

    def decrypt(self, encrypted_token: str) -> str:
        """Расшифровать строку."""
        if not encrypted_token:
            return ""
        try:
            decrypted = self._fernet.decrypt(encrypted_token.encode("utf-8"))
            return decrypted.decode("utf-8")
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return ""
