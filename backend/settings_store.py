"""Read/write app settings (key/value table). The OpenRouter key is stored
obfuscated — see backend.secrets for the caveats."""
import json

from . import config, secrets
from .models import Setting, utcnow

import secrets as _pysecrets

KEY_API_KEY = "openrouter_api_key"
KEY_MODEL = "openrouter_model"
KEY_DEFAULT_CONFIG = "default_botasaurus_config"
KEY_PAIRING_TOKEN = "extension_pairing_token"
KEY_WEBHOOK_URL = "notify_webhook_url"


def get_setting(session, key, default=None):
    row = session.get(Setting, key)
    return row.value if row else default


def set_setting(session, key, value):
    row = session.get(Setting, key)
    if row:
        row.value = value
        row.updated_at = utcnow()
    else:
        session.add(Setting(key=key, value=value))


def get_api_key(session):
    stored = get_setting(session, KEY_API_KEY)
    return secrets.deobfuscate(stored) if stored else None


def set_api_key(session, api_key):
    set_setting(session, KEY_API_KEY, secrets.obfuscate(api_key))


def get_model(session):
    return get_setting(session, KEY_MODEL, config.DEFAULT_MODEL)


def get_default_botasaurus_config(session):
    stored = get_setting(session, KEY_DEFAULT_CONFIG)
    merged = dict(config.DEFAULT_BOTASAURUS_CONFIG)
    if stored:
        merged.update(json.loads(stored))
    return merged


def get_pairing_token(session, create=True):
    """The shared secret the Chrome extension sends as X-Studio-Token.
    Stored obfuscated like the API key. Generated on first access."""
    stored = get_setting(session, KEY_PAIRING_TOKEN)
    if stored:
        return secrets.deobfuscate(stored)
    if not create:
        return None
    token = _pysecrets.token_urlsafe(24)
    set_setting(session, KEY_PAIRING_TOKEN, secrets.obfuscate(token))
    session.commit()
    return token


def regenerate_pairing_token(session):
    token = _pysecrets.token_urlsafe(24)
    set_setting(session, KEY_PAIRING_TOKEN, secrets.obfuscate(token))
    session.commit()
    return token


def get_webhook_url(session):
    return get_setting(session, KEY_WEBHOOK_URL)
