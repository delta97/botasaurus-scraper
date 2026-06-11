"""Proxy for OpenRouter's public model list, cached in memory for an hour."""
import time

from fastapi import APIRouter, HTTPException

from ..llm.openrouter import fetch_models

router = APIRouter(prefix="/api/models", tags=["models"])

_cache = {"at": 0.0, "models": None}
CACHE_TTL = 3600


@router.get("")
def list_models(q: str = ""):
    now = time.time()
    if _cache["models"] is None or now - _cache["at"] > CACHE_TTL:
        try:
            _cache["models"] = fetch_models()
            _cache["at"] = now
        except Exception as exc:
            if _cache["models"] is None:
                raise HTTPException(status_code=502, detail=f"could not reach OpenRouter: {exc}")
    models = _cache["models"]
    if q:
        ql = q.lower()
        models = [m for m in models
                  if ql in (m["id"] or "").lower() or ql in (m["name"] or "").lower()]
    return {"models": models[:200]}
