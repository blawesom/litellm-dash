import logging
from typing import Optional, Dict, Any
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException, status
from app.config import settings

logger = logging.getLogger("litellm_dash.auth")

# Serializer for creating tamper-proof session tokens
serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="litellm-dashboard-auth-v1")

def create_session_token(user_id: str, api_key: str) -> str:
    """
    Creates a signed session token storing user_id and a preview/hash of the API key.
    """
    key_preview = api_key[:7] + "..." if len(api_key) > 10 else api_key
    payload = {
        "user_id": user_id,
        "key_preview": key_preview,
        "api_key": api_key
    }
    return serializer.dumps(payload)

def verify_session_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verifies a signed session token and returns the payload if valid.
    """
    if not token:
        return None
    try:
        max_age_seconds = settings.SESSION_MAX_AGE_DAYS * 86400
        payload = serializer.loads(token, max_age=max_age_seconds)
        return payload
    except SignatureExpired:
        logger.warning("Session token has expired")
        return None
    except BadSignature:
        logger.warning("Invalid session token signature")
        return None
    except Exception as e:
        logger.error(f"Unexpected error verifying session token: {e}")
        return None

def get_current_user_from_request(request: Request) -> Dict[str, Any]:
    """
    FastAPI dependency/helper to extract and verify current authenticated user from session cookie.
    Raises HTTP 401 if unauthenticated.
    """
    cookie_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    payload = verify_session_token(cookie_token)
    if not payload or not payload.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please log in again."
        )
    return payload
