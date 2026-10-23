"""
Security, Google OAuth2 JWT Token Verification, Temp-Mail Blocker,
and Client Fingerprint Tracker for FastAPI Backend.
"""

import hashlib
from typing import Optional, Dict, Any
from fastapi import Request, Header, HTTPException, status
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from config import GOOGLE_CLIENT_ID, PRIMARY_ADMIN_EMAIL

# Whitelist of verified administrators. Defaults exclusively to PRIMARY_ADMIN_EMAIL.
ADMIN_EMAILS = {PRIMARY_ADMIN_EMAIL}


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

    if not clean_token or clean_token.lower() in ("null", "undefined"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token is invalid (received empty or null token). Please sign in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: Optional[str] = None
    verified_email: Optional[str] = None
    full_name: str = ""
    provider: str = "unknown"
    role: str = "user"
    plan_id: str = "free"
    email_verified: bool = False
    plan_details: Optional[Dict[str, Any]] = None

    # Strategy 1: Verify via Supabase Auth Access Token
    if supabase_client is not None:
        try:
            user_resp = supabase_client.auth.get_user(clean_token)
            if user_resp and user_resp.user:
                sb_user = user_resp.user
                user_id = str(sb_user.id)
                verified_email = sb_user.email
                meta = sb_user.user_metadata or {}
                full_name = meta.get("full_name") or meta.get("name") or ""
                provider = sb_user.app_metadata.get("provider", "supabase")
                email_verified = sb_user.email_confirmed_at is not None
        except Exception as sb_err:
            print(f"[AUTH DIAGNOSTIC] Supabase get_user failed for token ({clean_token[:15]}...): {type(sb_err).__name__}: {sb_err}")

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
            email_verified = True
        except Exception as g_err:
            pass

    if not verified_email:
        print(f"[AUTH DIAGNOSTIC] verify_auth_token REJECTED token: {clean_token[:25]} (len={len(clean_token)})")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token. Please sign in with Supabase Auth or Google.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Anti-Abuse: Block disposable temporary email services
    if is_disposable_email(verified_email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Disposable temporary emails are strictly prohibited. Please sign in with your official account.",
        )

    user_uid = user_id if user_id else generate_user_uid(verified_email)

    is_admin_email = verified_email.lower().strip() in ADMIN_EMAILS

    # Strategy 3: Load Role & Plan from Supabase profiles table
    if supabase_client is not None:
        try:
            query = supabase_client.table("profiles").select("*, plans(*)")
            if user_id:
                query = query.eq("id", user_id)
            else:
                query = query.eq("email", verified_email.lower().strip())
            
            prof_resp = query.limit(1).execute()
            if prof_resp.data and len(prof_resp.data) > 0:
                prof = prof_resp.data[0]
                user_id = str(prof["id"])
                user_uid = user_id
                role = prof.get("role", "user")
                if is_admin_email and role != "admin":
                    role = "admin"
                    # Synchronize admin role back to profile in background
                    try:
                        supabase_client.table("profiles").update({"role": "admin"}).eq("id", user_id).execute()
                    except Exception:
                        pass
                elif not is_admin_email and role == "admin":
                    # Self-healing security demotion: Non-whitelisted accounts can NEVER be admin
                    role = "user"
                    try:
                        supabase_client.table("profiles").update({"role": "user"}).eq("id", user_id).execute()
                    except Exception:
                        pass
                plan_id = prof.get("plan_id", "free")
                email_verified = prof.get("email_verified", email_verified)
                plan_details = prof.get("plans")
            elif user_id:
                # Upsert profile record
                role = "admin" if is_admin_email else "user"
                new_profile = {
                    "id": user_id,
                    "email": verified_email.lower().strip(),
                    "full_name": full_name or verified_email.split("@")[0],
                    "role": role,
                    "plan_id": "free",
                    "email_verified": email_verified,
                }
                supabase_client.table("profiles").upsert(new_profile).execute()
        except Exception as prof_err:
            print(f"[Security] Profile synchronization note: {prof_err}")

    return {
        "id": user_id or user_uid,
        "user_uid": user_uid,
        "email": verified_email.lower().strip(),
        "full_name": full_name or verified_email.split("@")[0],
        "is_verified": email_verified,
        "email_verified": email_verified,
        "role": role,
        "plan_id": plan_id,
        "plan": plan_details,
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
    FastAPI dependency that enforces an authenticated user with Supabase Auth.
    """
    if not authorization:
        print("[AUTH DIAGNOSTIC] get_current_user_required: Authorization header is None or missing!")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Sign in required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_auth_token(authorization, supabase_client=supabase_client)


def require_admin_user(
    authorization: Optional[str] = Header(None),
    supabase_client: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    FastAPI dependency that enforces an Admin user role.
    Raises 403 Forbidden if user is authenticated but not an admin.
    """
    user = get_current_user_required(authorization, supabase_client=supabase_client)
    user_role = user.get("role")
    user_email = (user.get("email") or "").strip().lower()
    
    # Strict Double-Lock: Role MUST be "admin" AND email MUST be in ADMIN_EMAILS
    if user_role != "admin" or user_email not in ADMIN_EMAILS:
        print(f"[SECURITY ALERT] Unauthorized admin access attempt blocked: email='{user_email}', role='{user_role}'")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Admin access strictly prohibited. Only verified system owners are authorized.",
        )
    return user

