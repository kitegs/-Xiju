from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from .config import DATA_DIR


KEY_FILE = DATA_DIR / ".vault-key"


def _cipher() -> Fernet:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not KEY_FILE.exists():
        KEY_FILE.write_bytes(Fernet.generate_key())
        try:
            KEY_FILE.chmod(0o600)
        except OSError:
            pass
    return Fernet(KEY_FILE.read_bytes().strip())


def encrypt_secret(value: str) -> str:
    return _cipher().encrypt(value.encode("utf-8")).decode("ascii") if value else ""


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _cipher().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("API key vault cannot decrypt this value") from exc


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••••••"
    return f"{value[:3]}••••••{value[-4:]}"
