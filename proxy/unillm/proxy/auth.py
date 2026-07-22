"""
Authentication module for UniLLM

Uses environment variable UNILLM_API_KEYS to store allowed API keys.
Format: comma-separated list of keys, e.g., "sk-key1,sk-key2,sk-key3"

Additionally accepts the per-session candidate key the portal publishes in the control
file — valid only while that file names an active
session, so clearing the file at session close/reset revokes it.
"""

import hmac
import json
import os
from typing import Optional
from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from unillm._logging import verbose_proxy_logger
from unillm.types import UserAPIKeyAuth


# Security scheme
security = HTTPBearer(auto_error=False)


def _session_key() -> Optional[str]:
    """The per-session candidate key from the portal's control file, if a session is
    active. Read per request so revocation (clear_control at close/reset) takes
    effect immediately; any read/parse problem simply means 'no session key'."""
    control_file = os.getenv("CONTROL_FILE", "/control/active.json")
    try:
        with open(control_file, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    if doc.get("state") != "active":
        return None
    key = doc.get("llm_api_key")
    return key if isinstance(key, str) and key else None


def is_session_key(api_key: Optional[str]) -> bool:
    """True if this key is the live per-session candidate key — i.e. the
    request came from the candidate's own workspace rather than a server-side/master-key
    caller (the portal playground or admin test). Used to attribute transcript entries to
    a trustworthy source: a candidate can be tagged 'api' authoritatively and can never
    forge a 'ui' tag, because they never hold the master key."""
    sk = _session_key()
    return bool(sk and api_key and hmac.compare_digest(api_key, sk))


def get_allowed_keys() -> set:
    """
    Get the set of allowed API keys from environment variables,
    plus the per-session candidate key from the control file (if any).

    Supports both UNILLM_API_KEYS (comma-separated list) and
    UNILLM_MASTER_KEY (single master key).
    """
    allowed_keys = set()
  
    # Get master key
    master_key = os.getenv("UNILLM_MASTER_KEY", "")
    if master_key:
        allowed_keys.add(master_key)
  
    # Also support LITELLM_MASTER_KEY for backward compatibility
    litellm_master_key = os.getenv("LITELLM_MASTER_KEY", "")
    if litellm_master_key:
        allowed_keys.add(litellm_master_key)
  
    # Get additional API keys (comma-separated)
    api_keys_str = os.getenv("UNILLM_API_KEYS", "")
    if api_keys_str:
        keys = [k.strip() for k in api_keys_str.split(",") if k.strip()]
        allowed_keys.update(keys)

    # Per-session candidate key: live only while a session is active.
    session_key = _session_key()
    if session_key:
        allowed_keys.add(session_key)

    return allowed_keys


async def user_api_key_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> UserAPIKeyAuth:
    """
    Authenticate the user based on their API key.
  
    The API key can be provided via:
    1. Authorization: Bearer <api_key> header
    2. x-api-key header
    """
    api_key: Optional[str] = None
  
    # Try to get the API key from Bearer token
    if credentials is not None:
        api_key = credentials.credentials
  
    # Fall back to x-api-key header
    if api_key is None:
        api_key = request.headers.get("x-api-key")
  
    # Check if API key is provided
    if api_key is None:
        verbose_proxy_logger.warning("No API key provided in request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Provide via 'Authorization: Bearer <key>' or 'x-api-key' header.",
        )
  
    # Get allowed keys
    allowed_keys = get_allowed_keys()
  
    # Fail closed: a blank/typo'd UNILLM_MASTER_KEY must not silently open the
    # SA-backed proxy to anyone who can reach it. No configured keys => refuse.
    if not allowed_keys:
        verbose_proxy_logger.error(
            "No API keys configured (UNILLM_MASTER_KEY / UNILLM_API_KEYS empty) - refusing all requests"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Proxy has no API keys configured; refusing to serve.",
        )
  
    # Validate the API key. Constant-time compare against each allowed key so a
    # timing side-channel can't confirm a partial guess; don't log any prefix
    # of a rejected key at WARNING (default level).
    if not any(hmac.compare_digest(api_key, k) for k in allowed_keys):
        verbose_proxy_logger.warning("Invalid API key provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    verbose_proxy_logger.debug("API key authenticated")
    return UserAPIKeyAuth(api_key=api_key, valid=True)
