"""API key obfuscation for at-rest storage.

This is deliberately obfuscation, NOT encryption: a real encryption key would
have to live next to the database anyway. It only protects against casual
exposure of the key in a `sqlite3 .dump` or a copied DB file.
"""
import base64
from itertools import cycle

_PEPPER = b"botasaurus-studio-pepper-v1"
_PREFIX = "obf:"


def obfuscate(value: str) -> str:
    raw = value.encode("utf-8")
    mixed = bytes(b ^ p for b, p in zip(raw, cycle(_PEPPER)))
    return _PREFIX + base64.urlsafe_b64encode(mixed).decode("ascii")


def deobfuscate(value: str) -> str:
    if not value.startswith(_PREFIX):
        return value
    mixed = base64.urlsafe_b64decode(value[len(_PREFIX):].encode("ascii"))
    return bytes(b ^ p for b, p in zip(mixed, cycle(_PEPPER))).decode("utf-8")


def preview(value: str) -> str:
    if len(value) <= 12:
        return value[:2] + "..." + value[-2:]
    return value[:8] + "..." + value[-4:]
