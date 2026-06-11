"""Pairing-token auth for extension-facing write endpoints.

The studio is a single-user localhost app with open reads, but once the Chrome
extension can POST recipes we gate writes behind a shared secret (the pairing
token shown in Settings) so a stray local process or a malicious web page can't
silently create recipes. Combined with CORS restricted to the extension origin,
this is the security boundary for cross-origin writes.
"""
import hmac

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from . import settings_store
from .db import get_session


def require_pairing_token(
    x_studio_token: str = Header(default=None),
    session: Session = Depends(get_session),
):
    expected = settings_store.get_pairing_token(session, create=False)
    if not expected:
        raise HTTPException(status_code=503,
                            detail="pairing token not initialised; open Settings in the studio first")
    if not x_studio_token or not hmac.compare_digest(x_studio_token, expected):
        raise HTTPException(status_code=401, detail="invalid or missing X-Studio-Token")
    return True
