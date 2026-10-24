"""Authentication and authorization for ContentMind.

Provides JWT-like access tokens for FastAPI endpoints. Uses a simple
HMAC-signature approach for compatibility with Python 3.14 and the
installed package set.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import User

# ---------------------------------------------------------------------------
# Token constants
# ---------------------------------------------------------------------------

ACCESS_TOKEN_EXPIRE_DAYS = 1440  # 1 year

# ---------------------------------------------------------------------------
# Pydantic models for token payload
# ---------------------------------------------------------------------------

class TokenData(BaseModel):
    sub: Optional[str] = None


# ---------------------------------------------------------------------------
# OAuth2 scheme
# ---------------------------------------------------------------------------

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")


# ---------------------------------------------------------------------------
# Helper: simple signed token encoding/decoding
# ---------------------------------------------------------------------------

def _encode_token(data: dict, secret_key: str, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed, base64url-encoded token string."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS))
    to_encode.pop("exp", None)
    to_encode["exp"] = expire
    # JSON-encode with datetime support via default=str
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(to_encode, default=str).encode()
    ).rstrip(b"=").decode()
    # Sign the payload with HMAC-HS256
    hmac_sig = base64.urlsafe_b64encode(
        hmac.new(secret_key.encode(), payload_b64.encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return f"{payload_b64}.{hmac_sig}"


def _decode_token(token: str, secret_key: str) -> dict:
    """Verify and decode a signed token, returning the payload dict."""
    parts = token.split(".")
    if len(parts) != 2:
        raise ValueError("Invalid token format")
    payload_b64, sig_b64 = parts
    # Recover the original payload bytes
    try:
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + "==").decode()
    except Exception:
        raise ValueError("Invalid token payload")
    # Verify the HMAC signature
    expected_sig = base64.urlsafe_b64encode(
        hmac.new(secret_key.encode(), payload_b64.encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    if not hmac.compare_digest(sig_b64, expected_sig):
        raise ValueError("Invalid token signature")
    # Parse the payload
    try:
        payload = json_decode(payload_bytes)
    except Exception:
        raise ValueError("Invalid token payload format")
    return payload


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Generate a signed access token for the given data."""
    secret_key = get_settings().secret_key
    return _encode_token(data, secret_key, expires_delta)


# ---------------------------------------------------------------------------
# User dependency
# ---------------------------------------------------------------------------

async def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    """Resolve the authenticated user from a signed access token.

    Raises ``HTTPException(401)`` if the token is missing, malformed, or
    the corresponding user record does not exist.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = _decode_token(token, get_settings().secret_key)
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except ValueError:
        raise credentials_exception

    user = db.get(User, int(user_id))
    if not user:
        raise credentials_exception
    return user


# ---------------------------------------------------------------------------
# Password helpers (unchanged from original)
# ---------------------------------------------------------------------------

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


# ---------------------------------------------------------------------------
# JSON encode/decode helpers (stdlib, no third-party deps)
# ---------------------------------------------------------------------------

import json

json_encode = json.dumps
json_decode = json.loads