"""
Supabase Cloud Database Client & Synchronization Module.
Handles verified users, persistent lead storage, session migration from SQLite to Cloud,
and user feedback reviews.
"""

from typing import List, Dict, Any, Optional, Union
from supabase import create_client, Client

from config import SUPABASE_URL, SUPABASE_KEY
from agent.schemas import LeadItem
from backend.temp_store import get_temp_leads_sync, update_job_sync


_supabase_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """
    Returns a singleton instance of the Supabase Client.
    Initializes using SUPABASE_URL and SUPABASE_KEY.
    """
    global _supabase_client
    if _supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_KEY must be configured in environment or .env file."
            )
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client


def is_supabase_connected() -> bool:
    """Checks if the Supabase client is configured and can connect to the database."""
    try:
        client = get_supabase_client()
        resp = client.table("verified_users").select("user_uid").limit(1).execute()
        return resp is not None
    except Exception as e:
        print(f"[Supabase] Healthcheck failed: {e}")
        return False


def ensure_verified_user(
    user_uid: str,
    email: str,
    full_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Ensures that a record exists in verified_users for the given user_uid.
    Upserts without modifying existing lead counts or plan type.
    """
    client = get_supabase_client()
    payload = {
        "user_uid": user_uid,
        "email": email.strip().lower(),
        "full_name": full_name or email.split("@")[0],
    }

    resp = client.table("verified_users").upsert(
        payload,
        on_conflict="user_uid",
    ).execute()

    return resp.data[0] if resp.data else payload


def lead_item_to_supabase_record(lead: Union[LeadItem, Dict[str, Any]], user_uid: str, job_id: str) -> Dict[str, Any]:
    """Transforms a LeadItem or dict into a Supabase saved_leads record."""
    if isinstance(lead, LeadItem):
        data = lead.model_dump()
    else:
        data = dict(lead)

    socials = data.get("social_links")
    if isinstance(socials, dict):
        social_dict = socials
    elif hasattr(socials, "model_dump"):
        social_dict = socials.model_dump()
    else:
        social_dict = {}

    return {
        "user_uid": user_uid,
        "job_id": job_id,
        "place_id": data.get("place_id", ""),
        "name": data.get("name", ""),
        "category": data.get("category"),
        "phone": data.get("phone"),
        "website_status": data.get("website_status", "No Website"),
        "website_url": data.get("website_url"),
        "emails": data.get("emails", []),
        "social_links": social_dict,
        "cms_tech": data.get("cms_tech"),
        "rating": data.get("rating"),
        "reviews_count": data.get("reviews_count", 0),
        "price_range": data.get("price_range"),
        "is_unclaimed_business": bool(data.get("is_unclaimed_business", False)),
        "neighborhood": data.get("neighborhood"),
        "address": data.get("address"),
        "lat": data.get("lat"),
        "lon": data.get("lon"),
        "google_maps_url": data.get("google_maps_url"),
        "source_query": data.get("source_query"),
    }


def save_leads_to_supabase(
    user_uid: str,
    job_id: str,
    leads: List[Union[LeadItem, Dict[str, Any]]],
    batch_size: int = 50,
) -> int:
    """
    Saves a batch of leads to the Supabase saved_leads table for a verified user.
    Uses ON CONFLICT (user_uid, place_id) to eliminate duplicate businesses for the user.
    Updates verified_users.total_leads_saved.
    Returns the count of leads processed.
    """
    if not leads:
        return 0

    client = get_supabase_client()
    records = [
        lead_item_to_supabase_record(lead, user_uid=user_uid, job_id=job_id)
        for lead in leads
        if (lead.place_id if isinstance(lead, LeadItem) else lead.get("place_id"))
    ]

    if not records:
        return 0

    saved_total = 0
    # Chunk records into smaller batches for Supabase HTTP API
    for i in range(0, len(records), batch_size):
        chunk = records[i : i + batch_size]
        client.table("saved_leads").upsert(
            chunk,
            on_conflict="user_uid,place_id",
        ).execute()
        saved_total += len(chunk)

    # Update total saved count on verified_users
    try:
        count_resp = (
            client.table("saved_leads")
            .select("id", count="exact")
            .eq("user_uid", user_uid)
            .execute()
        )
        total_count = count_resp.count or saved_total
        client.table("verified_users").update({"total_leads_saved": total_count}).eq("user_uid", user_uid).execute()
    except Exception as count_err:
        print(f"[Supabase] Note on updating total_leads_saved: {count_err}")

    return saved_total


def get_user_saved_leads(
    user_uid: str,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Retrieves previously saved leads for a verified user from Supabase.
    Ordered by creation date descending.
    """
    client = get_supabase_client()
    resp = (
        client.table("saved_leads")
        .select("*")
        .eq("user_uid", user_uid)
        .order("id", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return resp.data or []


def sync_temp_session_to_supabase(
    user_uid: str,
    email: str,
    job_id: str,
    full_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Transfers local SQLite temp leads to Supabase Cloud for a user after Google login.
    1. Ensures user exists in verified_users.
    2. Retrieves all cached leads for job_id from local SQLite WAL buffer.
    3. Saves them to Supabase saved_leads under user_uid.
    4. Updates local SQLite active_jobs to record verified ownership.
    """
    # Step 1: Ensure user profile
    ensure_verified_user(user_uid=user_uid, email=email, full_name=full_name)

    # Step 2: Retrieve cached leads from local SQLite
    temp_leads = get_temp_leads_sync(job_id)
    if not temp_leads:
        return {
            "status": "empty",
            "message": "No local temporary leads found for this job session.",
            "job_id": job_id,
            "user_uid": user_uid,
            "synced_leads_count": 0,
        }

    # Step 3: Upsert into Supabase saved_leads
    saved_count = save_leads_to_supabase(user_uid=user_uid, job_id=job_id, leads=temp_leads)

    # Step 4: Update local job status to authenticated
    update_job_sync(job_id, status=None, current_area=None, leads_count=None)
    from backend.temp_store import get_sync_connection
    with get_sync_connection() as conn:
        conn.execute(
            "UPDATE active_jobs SET is_authenticated = 1, session_owner = ? WHERE job_id = ?",
            (user_uid, job_id),
        )
        conn.commit()

    return {
        "status": "success",
        "message": f"Successfully synced {saved_count} leads to your cloud account.",
        "job_id": job_id,
        "user_uid": user_uid,
        "synced_leads_count": saved_count,
    }


def create_product_review(
    rating: int,
    comment: str,
    user_email: Optional[str] = None,
    wants_paid_version: bool = False,
) -> Dict[str, Any]:
    """Saves a user rating and review comment to product_reviews table."""
    client = get_supabase_client()
    payload = {
        "user_email": user_email.strip().lower() if user_email else None,
        "rating": max(1, min(5, int(rating))),
        "comment": comment.strip(),
        "wants_paid_version": bool(wants_paid_version),
    }
    resp = client.table("product_reviews").insert(payload).execute()
    return resp.data[0] if resp.data else payload


def get_product_reviews(limit: int = 20) -> List[Dict[str, Any]]:
    """Retrieves recent product reviews for display in the UI feedback section."""
    client = get_supabase_client()
    resp = (
        client.table("product_reviews")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []
