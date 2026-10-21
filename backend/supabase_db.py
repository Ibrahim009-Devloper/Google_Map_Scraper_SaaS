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
    user_name: Optional[str] = "Anonymous User",
    user_email: Optional[str] = None,
    wants_paid_version: bool = False,
) -> Dict[str, Any]:
    """Saves a user rating and review/problem comment to product_reviews table."""
    client = get_supabase_client()
    payload = {
        "user_name": user_name.strip() if user_name else "Anonymous User",
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


# ============================================================================
# SaaS Multi-Tenant Functions: Profiles, Plans, Usage & Jobs Ledger
# ============================================================================

def get_user_profile(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetches the profile for a user by their Supabase UUID.
    Joins with plans table to provide full plan details and limits.
    """
    client = get_supabase_client()
    try:
        resp = (
            client.table("profiles")
            .select("*, plans(*)")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if resp.data and len(resp.data) > 0:
            profile = resp.data[0]
            plan = profile.get("plans") or {}

            # Check if user has a custom quota override assigned by admin
            custom_daily = profile.get("custom_leads_per_day")
            if custom_daily and int(custom_daily) > 0:
                c_leads = int(custom_daily)
                c_job = int(profile.get("custom_leads_per_job") or c_leads)
                c_jobs_day = int(profile.get("custom_jobs_per_day") or 100)
                c_name = profile.get("custom_plan_name") or f"Custom Plan ({c_leads:,} Leads/Day)"
                plan = {
                    "id": "custom",
                    "name": c_name,
                    "leads_per_day": c_leads,
                    "daily_leads_limit": c_leads,
                    "leads_per_job": c_job,
                    "max_leads_per_job": c_job,
                    "jobs_per_day": c_jobs_day,
                    "daily_jobs_limit": c_jobs_day,
                    "website_enrichment_enabled": True,
                    "price_bdt": 0.0,
                    "price_usd": 0.0,
                }
            else:
                # For standard Pro plan, ensure leads_per_job matches leads_per_day (10,000)
                if profile.get("plan_id") == "pro" or plan.get("id") == "pro":
                    daily_limit = plan.get("leads_per_day", 10000)
                    plan["leads_per_job"] = max(plan.get("leads_per_job", daily_limit), daily_limit)

            plan["daily_leads_limit"] = plan.get("leads_per_day", 1000)
            profile["plan"] = plan
            return profile
    except Exception as e:
        print(f"[Supabase] Error fetching profile for {user_id}: {e}")
    return None


def get_daily_usage(user_id: str, usage_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns today's usage row for the user.
    If no record exists for today, returns a zeroed structure.
    """
    client = get_supabase_client()
    import datetime
    today = usage_date or datetime.date.today().isoformat()
    month = today[:7]

    try:
        resp = (
            client.table("usage_monthly")
            .select("*")
            .eq("user_id", user_id)
            .eq("usage_date", today)
            .limit(1)
            .execute()
        )
        if resp.data and len(resp.data) > 0:
            return resp.data[0]
    except Exception as e:
        print(f"[Supabase] Error fetching usage for {user_id}: {e}")

    return {
        "user_id": user_id,
        "usage_date": today,
        "month": month,
        "jobs_count": 0,
        "leads_scraped": 0,
        "enrichment_calls": 0,
    }


def record_usage(
    user_id: str,
    leads_count: int = 0,
    jobs_count: int = 0,
    enrichment_calls: int = 0,
) -> Dict[str, Any]:
    """
    Atomically updates usage_monthly for today's date.
    Inserts a new row if none exists; otherwise increments counters.
    """
    client = get_supabase_client()
    import datetime
    today = datetime.date.today().isoformat()
    month = today[:7]

    current = get_daily_usage(user_id, usage_date=today)
    new_jobs = current.get("jobs_count", 0) + jobs_count
    new_leads = current.get("leads_scraped", 0) + leads_count
    new_enrich = current.get("enrichment_calls", 0) + enrichment_calls

    payload = {
        "user_id": user_id,
        "usage_date": today,
        "month": month,
        "jobs_count": new_jobs,
        "leads_scraped": new_leads,
        "enrichment_calls": new_enrich,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    try:
        resp = (
            client.table("usage_monthly")
            .upsert(payload, on_conflict="user_id,usage_date")
            .execute()
        )
        return resp.data[0] if resp.data else payload
    except Exception as e:
        print(f"[Supabase] Error recording usage for {user_id}: {e}")
        return payload


def check_user_limits(
    user_id: str,
    requested_target_leads: int,
    requires_enrichment: bool = False,
) -> Dict[str, Any]:
    """
    Server-side enforcement of Plan limits before starting any scrape:
    - Free test plan: 1,000 leads/day, 3 jobs/day, 300 leads/job.
    - Prevents abuse by capping target_leads or blocking if daily limit reached.
    """
    profile = get_user_profile(user_id)
    if not profile:
        return {
            "allowed": False,
            "reason": "User profile not found. Please re-authenticate.",
            "effective_target": 0,
            "plan": None,
        }

    plan = profile.get("plan") or {
        "id": "free",
        "name": "Free Test Plan",
        "leads_per_day": 1000,
        "jobs_per_day": 3,
        "leads_per_job": 300,
        "website_enrichment_enabled": True,
    }

    usage = get_daily_usage(user_id)
    jobs_today = usage.get("jobs_count", 0)
    leads_today = usage.get("leads_scraped", 0)

    # 1. Check daily job count
    max_jobs_per_day = plan.get("jobs_per_day", 3)
    if jobs_today >= max_jobs_per_day:
        return {
            "allowed": False,
            "reason": f"Daily limit of {max_jobs_per_day} scraping jobs reached for your {plan.get('name', 'Free')} plan. Upgrade or try again tomorrow.",
            "effective_target": 0,
            "plan": plan,
            "usage": usage,
        }

    # 2. Check daily lead quota
    max_leads_per_day = plan.get("leads_per_day", 1000)
    if leads_today >= max_leads_per_day:
        return {
            "allowed": False,
            "reason": f"Daily limit of {max_leads_per_day:,} leads reached for your {plan.get('name', 'Free')} plan. Upgrade or try again tomorrow.",
            "effective_target": 0,
            "plan": plan,
            "usage": usage,
        }

    # 3. Check website enrichment permission
    if requires_enrichment and not plan.get("website_enrichment_enabled", True):
        return {
            "allowed": False,
            "reason": f"Website deep enrichment is not enabled on your current plan.",
            "effective_target": 0,
            "plan": plan,
            "usage": usage,
        }

    # 4. Calculate effective target leads (Ensure Pro and Custom plans are not choked)
    max_leads_per_job = plan.get("leads_per_job") or plan.get("leads_per_day", 300)
    # If the user has a custom quota or pro plan, allow the entire daily limit in a single job
    if plan.get("id") in ("pro", "custom") or profile.get("custom_leads_per_day"):
        max_leads_per_job = max(max_leads_per_job, max_leads_per_day)

    remaining_today = max_leads_per_day - leads_today
    effective_target = min(requested_target_leads, max_leads_per_job, remaining_today)

    if effective_target <= 0:
        return {
            "allowed": False,
            "reason": "No remaining lead quota available today.",
            "effective_target": 0,
            "plan": plan,
            "usage": usage,
        }

    return {
        "allowed": True,
        "reason": "OK",
        "effective_target": effective_target,
        "plan": plan,
        "usage": usage,
    }


def create_job_record(
    job_id: str,
    user_id: str,
    prompt: str,
    target_leads: int,
    enrichment_enabled: bool = False,
) -> Dict[str, Any]:
    """Records a new scraping job in the public.jobs table."""
    client = get_supabase_client()
    payload = {
        "id": job_id,
        "user_id": user_id,
        "prompt": prompt,
        "status": "running",
        "target_leads": target_leads,
        "leads_scraped": 0,
        "enrichment_enabled": enrichment_enabled,
        "current_area": "Initializing AI Geo-Planner...",
    }
    try:
        resp = client.table("jobs").insert(payload).execute()
        return resp.data[0] if resp.data else payload
    except Exception as e:
        print(f"[Supabase] Error creating job record {job_id}: {e}")
        return payload


def update_job_record(
    job_id: str,
    status: Optional[str] = None,
    leads_scraped: Optional[int] = None,
    current_area: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Updates status, count, and error in public.jobs table."""
    client = get_supabase_client()
    import datetime
    payload = {}
    if status is not None:
        payload["status"] = status
        if status in ("completed", "stopped", "failed", "limit_reached"):
            payload["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if leads_scraped is not None:
        payload["leads_scraped"] = leads_scraped
    if current_area is not None:
        payload["current_area"] = current_area
    if error_message is not None:
        payload["error_message"] = str(error_message)[:500]

    if not payload:
        return

    try:
        client.table("jobs").update(payload).eq("id", job_id).execute()
    except Exception as e:
        print(f"[Supabase] Error updating job record {job_id}: {e}")


def get_user_jobs(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Returns past scraping jobs for the specified user."""
    client = get_supabase_client()
    try:
        resp = (
            client.table("jobs")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        print(f"[Supabase] Error fetching jobs for {user_id}: {e}")
        return []


def get_admin_overview() -> Dict[str, Any]:
    """Provides high-level platform analytics for the Admin Dashboard."""
    client = get_supabase_client()
    import datetime
    today = datetime.date.today().isoformat()

    try:
        users_count_resp = client.table("profiles").select("id", count="exact").execute()
        total_users = users_count_resp.count or 0
    except Exception:
        total_users = 0

    try:
        jobs_count_resp = client.table("jobs").select("id", count="exact").execute()
        total_jobs = jobs_count_resp.count or 0
    except Exception:
        total_jobs = 0

    try:
        jobs_today_resp = (
            client.table("jobs")
            .select("id", count="exact")
            .gte("created_at", f"{today}T00:00:00Z")
            .execute()
        )
        jobs_today = jobs_today_resp.count or 0
    except Exception:
        jobs_today = 0

    try:
        leads_count_resp = client.table("saved_leads").select("id", count="exact").execute()
        total_leads = leads_count_resp.count or 0
    except Exception:
        total_leads = 0

    try:
        payments_resp = (
            client.table("payments")
            .select("amount")
            .eq("status", "completed")
            .execute()
        )
        total_revenue = sum(float(p["amount"]) for p in (payments_resp.data or []))
    except Exception:
        total_revenue = 0.0

    return {
        "total_users": total_users,
        "total_jobs": total_jobs,
        "jobs_today": jobs_today,
        "total_leads_scraped": total_leads,
        "total_revenue_bdt": total_revenue,
    }


def get_admin_users(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetches user list with roles and plans for Admin Dashboard."""
    client = get_supabase_client()
    try:
        resp = (
            client.table("profiles")
            .select("*, plans(*)")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        print(f"[Supabase] Admin users fetch error: {e}")
        return []


def update_user_plan_or_role(
    target_user_id: str,
    plan_id: Optional[str] = None,
    role: Optional[str] = None,
    custom_leads_per_day: Optional[int] = None,
    custom_leads_per_job: Optional[int] = None,
    custom_jobs_per_day: Optional[int] = None,
    custom_plan_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Admin function to update a user's subscription plan, admin status,
    or assign a custom lead scraping quota (e.g. 20,000 leads, 500,000 leads).
    """
    client = get_supabase_client()
    import datetime
    payload = {"updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if plan_id is not None:
        payload["plan_id"] = plan_id
    if role is not None:
        payload["role"] = role

    if custom_leads_per_day is not None:
        if custom_leads_per_day <= 0:
            # Clear custom quota override
            payload["custom_leads_per_day"] = None
            payload["custom_leads_per_job"] = None
            payload["custom_jobs_per_day"] = None
            payload["custom_plan_name"] = None
        else:
            payload["custom_leads_per_day"] = custom_leads_per_day
            payload["custom_leads_per_job"] = custom_leads_per_job or custom_leads_per_day
            payload["custom_jobs_per_day"] = custom_jobs_per_day or 100
            payload["custom_plan_name"] = custom_plan_name or f"Custom ({custom_leads_per_day:,} Leads/Day)"

    resp = client.table("profiles").update(payload).eq("id", target_user_id).execute()
    return resp.data[0] if resp.data else payload


def get_admin_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetches all platform jobs across users for error and progress audit."""
    client = get_supabase_client()
    try:
        resp = (
            client.table("jobs")
            .select("*, profiles(email, full_name)")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        print(f"[Supabase] Admin jobs fetch error: {e}")
        return []


def get_admin_payments(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetches payment records for Admin Ledger."""
    client = get_supabase_client()
    try:
        resp = (
            client.table("payments")
            .select("*, profiles(email, full_name), plans(name)")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        print(f"[Supabase] Admin payments fetch error: {e}")
        return []


def record_payment(
    user_id: str,
    plan_id: str,
    amount: float,
    currency: str = "BDT",
    provider: str = "manual",
    transaction_id: Optional[str] = None,
    status: str = "pending",
    raw_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Records a payment and upgrades the user's plan upon verified completion."""
    client = get_supabase_client()
    import datetime
    payload = {
        "user_id": user_id,
        "plan_id": plan_id,
        "amount": amount,
        "currency": currency,
        "provider": provider,
        "transaction_id": transaction_id,
        "status": status,
        "raw_webhook_data": raw_data or {},
    }
    if status == "completed":
        payload["verified_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    resp = client.table("payments").insert(payload).execute()
    payment_record = resp.data[0] if resp.data else payload

    # If completed, immediately update the user's profile plan
    if status == "completed":
        client.table("profiles").update({
            "plan_id": plan_id,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }).eq("id", user_id).execute()

    return payment_record


def get_admin_reviews(limit: int = 100) -> List[Dict[str, Any]]:
    """Fetches user reviews and reported issues for the Admin Command Center."""
    client = get_supabase_client()
    try:
        resp = (
            client.table("product_reviews")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        print(f"[Supabase] Admin reviews fetch error: {e}")
        return []


def delete_admin_review(review_id: int) -> bool:
    """Deletes a review record by ID. Admin only."""
    client = get_supabase_client()
    try:
        resp = client.table("product_reviews").delete().eq("id", review_id).execute()
        return bool(resp.data)
    except Exception as e:
        print(f"[Supabase] Admin delete review error: {e}")
        return False

