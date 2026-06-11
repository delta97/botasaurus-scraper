import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import secrets, settings_store
from ..db import get_session
from ..schemas import SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_settings(session: Session = Depends(get_session)):
    stored_key = settings_store.get_setting(session, settings_store.KEY_API_KEY)
    plain = secrets.deobfuscate(stored_key) if stored_key else None
    return {
        "openrouter_api_key_set": bool(plain),
        "openrouter_api_key_preview": secrets.preview(plain) if plain else None,
        "openrouter_model": settings_store.get_model(session),
        "default_botasaurus_config": settings_store.get_default_botasaurus_config(session),
    }


@router.put("")
def update_settings(payload: SettingsUpdate, session: Session = Depends(get_session)):
    if payload.openrouter_api_key is not None:
        if payload.openrouter_api_key == "":
            settings_store.set_setting(session, settings_store.KEY_API_KEY, "")
        else:
            settings_store.set_api_key(session, payload.openrouter_api_key)
    if payload.openrouter_model is not None:
        settings_store.set_setting(session, settings_store.KEY_MODEL, payload.openrouter_model)
    if payload.default_botasaurus_config is not None:
        settings_store.set_setting(session, settings_store.KEY_DEFAULT_CONFIG,
                                   json.dumps(payload.default_botasaurus_config))
    session.commit()
    return get_settings(session)
