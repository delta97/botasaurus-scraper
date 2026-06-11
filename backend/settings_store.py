"""Read/write app settings (key/value table). The OpenRouter key is stored
obfuscated — see backend.secrets for the caveats."""
import json

from . import config, secrets
from .models import Setting, utcnow

KEY_API_KEY = "openrouter_api_key"
KEY_MODEL = "openrouter_model"
KEY_DEFAULT_CONFIG = "default_botasaurus_config"


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
