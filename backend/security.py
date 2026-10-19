"""
Security, Google OAuth2 JWT Token Verification, Temp-Mail Blocker,
and Client Fingerprint Tracker for FastAPI Backend.
"""

import hashlib
from typing import Optional, Dict, Any
from fastapi import Request, Header, HTTPException, status
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from config import GOOGLE_CLIENT_ID


# Common disposable / temporary email domains to strictly block
DISPOSABLE_EMAIL_DOMAINS = {
    "10minutemail.com", "10minutemail.net", "guerrillamail.com", "guerrillamail.net",
    "yopmail.com", "yopmail.net", "mailinator.com", "sharklasers.com", "tempmail.com",
    "temp-mail.org", "throwawaymail.com", "getairmail.com", "dispostable.com",
    "trashmail.com", "mytemp.email", "fakeinbox.com", "burnermail.io", "crazymailing.com",
}


def is_disposable_email(email: str) -> bool:
    """Checks if an email uses a disposable / temporary email service."""
    if not email or "@" not in email:
        return True
    domain = email.strip().lower().split("@")[-1]
    return domain in DISPOSABLE_EMAIL_DOMAINS


def generate_user_uid(verified_email: str) -> str:
    """
    Generates a deterministic cryptographic user identifier from a verified email:
    usr_<sha256(lowercase_email)[:20]>
    Guarantees user uniqueness without revealing plain email in URLs or public logs.
    """
    clean_email = verified_email.strip().lower()
    hashed = hashlib.sha256(clean_email.encode("utf-8")).hexdigest()[:20]
    return f"usr_{hashed}"


def get_client_identifier(request: Request) -> str:
    """
    Extracts the unique client tracking identifier for anonymous quotas.
    Combines client IP (respecting proxy headers) and X-Device-Fingerprint.
    """
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    elif request.client and request.client.host:
        client_ip = request.client.host
    else:
        client_ip = "127.0.0.1"

    device_fp = request.headers.get("x-device-fingerprint", "").strip()
    if device_fp:
        return f"anon_{device_fp}"
    
    clean_ip = client_ip.replace(":", "_").replace(".", "_")
    return f"anon_ip_{clean_ip}"


def verify_auth_token(token: str, supabase_client: Optional[Any] = None) -> Dict[str, Any]:
    """
    Verifies an authentication Bearer token.
    Supports:
    1. Supabase Auth JWT Access Token (supabase.auth.get_user(token))
    2. Google OAuth ID Token (google.oauth2.id_token.verify_oauth2_token)
    
    Returns a dict with:
    {
        "user_uid": str,
        "email": str,
        "full_name": str,
        "is_verified": bool,
        "provider": str
    }
    """
    if not token or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token is missing or empty.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    clean_token = token.strip()
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    verified_email: Optional[str] = None
    full_name: str = ""
    provider: str = "unknown"

    # Strategy 1: Verify via Supabase Auth
    if supabase_client is not None:
        try:
            user_resp = supabase_client.auth.get_user(clean_token)
            if user_resp and user_resp.user:
                sb_user = user_resp.user
                verified_email = sb_user.email
                meta = sb_user.user_metadata or {}
                full_name = meta.get("full_name") or meta.get("name") or ""
                provider = sb_user.app_metadata.get("provider", "supabase")
        except Exception:
            pass

    # Strategy 2: Verify via Google ID Token
    if not verified_email:
        try:
            req = google_requests.Request()
            audience = GOOGLE_CLIENT_ID if GOOGLE_CLIENT_ID else None
            id_info = id_token.verify_oauth2_token(clean_token, req, audience=audience)
            
            # Check issuer
            issuer = id_info.get("iss", "")
            if issuer not in ("accounts.google.com", "https://accounts.google.com"):
                raise ValueError("Untrusted Google Token issuer.")

            if not id_info.get("email_verified", False):
                raise ValueError("Google account email is not verified.")

            verified_email = id_info.get("email")
            full_name = id_info.get("name") or id_info.get("given_name", "")
            provider = "google"
        except Exception as g_err:
            pass

    if not verified_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token. Please login with a valid Google account.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Anti-Abuse: Block disposable temporary email services
    if is_disposable_email(verified_email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Disposable temporary emails are strictly prohibited. Please sign in with your official Google account.",
        )

    user_uid = generate_user_uid(verified_email)

    return {
        "user_uid": user_uid,
        "email": verified_email.lower().strip(),
        "full_name": full_name or verified_email.split("@")[0],
        "is_verified": True,
        "provider": provider,
    }


def get_current_user_optional(
    authorization: Optional[str] = Header(None),
    supabase_client: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """
    FastAPI dependency for endpoints that accept both anonymous and logged-in users.
    Returns user dict if valid Bearer token provided, else None.
    """
    if not authorization:
        return None
    try:
        return verify_auth_token(authorization, supabase_client=supabase_client)
    except HTTPException:
        return None


def get_current_user_required(
    authorization: Optional[str] = Header(None),
    supabase_client: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    FastAPI dependency that enforces a verified Google authenticated user.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Google login required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_auth_token(authorization, supabase_client=supabase_client)
