"""Endpoints the Chrome extension talks to."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/extension", tags=["extension"])

EXTENSION_API_VERSION = 1


@router.get("/ping")
def ping():
    """Used by the extension's "Test connection" button. No auth: it only
    confirms reachability; writes are token-gated separately."""
    from ..agent.selectors import SELECTOR_SPEC_VERSION
    return {"ok": True, "api_version": EXTENSION_API_VERSION,
            "selector_spec_version": SELECTOR_SPEC_VERSION}
