"""
FastAPI Main Application for Autonomous AI Google Maps Lead Generation Agent.
Implements 8 core endpoints:
1. POST /api/scrape/start        (Initiate scraping job with AI Planner & Quota enforcement)
2. GET  /api/scrape/stream/{id}  (Server-Sent Events [SSE] live lead and status streaming)
3. POST /api/scrape/stop/{id}    (Instant graceful cancellation with zero data loss)
4. GET  /api/scrape/download/{id}(Download CSV or JSON export with UTF-8 BOM for Excel)
5. POST /api/auth/sync-session   (Transfer local SQLite leads to Supabase Cloud on Google Login)
6. GET  /api/user/my-leads       (Retrieve persistent leads history for verified user)
7. POST /api/reviews             (Submit product feedback and ratings)
8. GET  /api/reviews             (Fetch latest public product reviews)
"""

import io
import csv
import json
import uuid
import asyncio
import threading
from typing import Optional, List, Dict, Any

import aiosqlite
from fastapi import FastAPI, Request, Response, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import TEMP_DB_PATH, ANONYMOUS_LEAD_LIMIT
from agent.schemas import ActionPlan, LeadItem
from agent.planner import generate_plan
from agent.pipeline import run_pipeline
from backend import temp_store
from backend import security
from backend import supabase_db
from backend.excel_exporter import generate_leads_excel


# Rate Limiter setup
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Autonomous AI Google Maps Lead Generation API",
    description="Zero-Browser High Speed Reverse API Scraper with LLM Geo-Planner & Live SSE Streaming",
    version="1.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Frontend Static Assets & Root Route
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/", tags=["Frontend"])
    async def serve_frontend():
        return FileResponse(str(FRONTEND_DIR / "index.html"))


# ============================================================================
# Concurrency & Active Task Manager (Prevents memory leaks & race conditions)
# ============================================================================

class JobManager:
    """Manages running jobs, cancellation events, and per-user concurrency locks."""
    def __init__(self):
        self._active_jobs: Dict[str, threading.Event] = {}
        self._owner_to_job: Dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def can_start(self, session_owner: str) -> bool:
        async with self._lock:
            existing_job_id = self._owner_to_job.get(session_owner)
            if existing_job_id:
                job = await temp_store.get_job(existing_job_id)
                if job and job["status"] == "running":
                    return False
                else:
                    self._owner_to_job.pop(session_owner, None)
                    self._active_jobs.pop(existing_job_id, None)
            return True

    async def register(self, job_id: str, session_owner: str) -> threading.Event:
        async with self._lock:
            stop_event = threading.Event()
            self._active_jobs[job_id] = stop_event
            self._owner_to_job[session_owner] = job_id
            return stop_event

    async def stop(self, job_id: str) -> bool:
        async with self._lock:
            stop_event = self._active_jobs.get(job_id)
            if stop_event:
                stop_event.set()
                return True
            return False

    async def release(self, job_id: str, session_owner: str):
        async with self._lock:
            self._active_jobs.pop(job_id, None)
            if self._owner_to_job.get(session_owner) == job_id:
                self._owner_to_job.pop(session_owner, None)


job_manager = JobManager()


@app.on_event("startup")
async def on_startup():
    """Initializes SQLite database with WAL mode and runs cleanup of stale data."""
    await temp_store.init_db()
    temp_store.cleanup_old_temp_data_sync(hours=24)


# ============================================================================
# Pydantic Request & Response Schemas
# ============================================================================

class ScrapeStartRequest(BaseModel):
    prompt: str = Field(
        ...,
        min_length=5,
        max_length=300,
        description="Natural language scraping request (e.g. 'Software companies in Dhanmondi without websites')",
    )
    provider: Optional[str] = Field(None, description="Preferred LLM provider: 'gemini' or 'groq'")
    target_leads: Optional[int] = Field(None, ge=1, le=1000, description="Requested target leads count (e.g. 50)")


class SyncSessionRequest(BaseModel):
    job_id: str = Field(..., min_length=3, max_length=100, description="Job session ID to sync")


class ReviewSubmitRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="Star rating between 1 and 5")
    comment: str = Field(..., min_length=3, max_length=1000, description="Review feedback comment")
    wants_paid_version: bool = Field(default=False, description="Whether the user is interested in a paid plan")


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint verifying backend and Supabase connectivity."""
    return {
        "status": "healthy",
        "supabase_connected": supabase_db.is_supabase_connected(),
        "anonymous_lead_limit": ANONYMOUS_LEAD_LIMIT,
    }


@app.get("/api/quota", tags=["Quota"])
async def get_client_quota(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """Returns the caller's current quota usage (anonymous IP or authenticated user)."""
    sb_client = None
    try:
        sb_client = supabase_db.get_supabase_client()
    except Exception:
        pass

    user = security.get_current_user_optional(authorization, supabase_client=sb_client)
    if user:
        return {
            "is_authenticated": True,
            "session_owner": user["user_uid"],
            "email": user["email"],
            "total_leads_scraped": 0,
            "limit": "unlimited",
            "is_limit_reached": False,
        }

    session_owner = security.get_client_identifier(request)
    current_scraped = await temp_store.get_anonymous_quota(session_owner)
    return {
        "is_authenticated": False,
        "session_owner": session_owner,
        "total_leads_scraped": current_scraped,
        "limit": ANONYMOUS_LEAD_LIMIT,
        "is_limit_reached": current_scraped >= ANONYMOUS_LEAD_LIMIT,
    }


@app.post("/api/dev/reset-quota", tags=["Development"])
async def reset_dev_quota(request: Request):
    """Developer helper: Resets anonymous quota for the caller's IP/Fingerprint to 0."""
    session_owner = security.get_client_identifier(request)
    await temp_store.reset_anonymous_quota(session_owner)
    return {
        "status": "success",
        "message": f"Anonymous quota for {session_owner} reset to 0.",
        "session_owner": session_owner,
        "total_leads_scraped": 0,
    }


@app.post("/api/scrape/start", tags=["Scraper"])
@limiter.limit("5/minute")
async def start_scraping_job(
    request: Request,
    payload: ScrapeStartRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Initiates a new autonomous scraping job:
    1. Authenticates user if Bearer token present; otherwise tracks IP/Fingerprint.
    2. Validates anonymous quota (1,000 lead ceiling).
    3. Prevents duplicate concurrent jobs for the same user/IP.
    4. Analyzes query via LLM Geo-Planner and launches background worker.
    """
    sb_client = None
    try:
        sb_client = supabase_db.get_supabase_client()
    except Exception:
        pass

    user = security.get_current_user_optional(authorization, supabase_client=sb_client)
    if user:
        session_owner = user["user_uid"]
        is_authenticated = True
        user_email = user["email"]
    else:
        session_owner = security.get_client_identifier(request)
        is_authenticated = False
        user_email = None

    # Check anonymous quota
    if not is_authenticated:
        current_scraped = await temp_store.get_anonymous_quota(session_owner)
        if current_scraped >= ANONYMOUS_LEAD_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "status": "limit_reached_login_required",
                    "message": f"Free anonymous limit of {ANONYMOUS_LEAD_LIMIT} leads reached. Please sign in with Google to continue.",
                    "current_quota": current_scraped,
                },
            )

    # Concurrency Lock: 1 active job per user/IP
    can_start = await job_manager.can_start(session_owner)
    if not can_start:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="A scraping job is already running for your account or IP. Please wait or stop the running job first.",
        )

    # Step 1: AI Planner
    try:
        action_plan = generate_plan(payload.prompt, provider=payload.provider)
        if payload.target_leads and not action_plan.target_leads:
            action_plan.target_leads = payload.target_leads
    except Exception as plan_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to generate search action plan: {str(plan_err)}",
        )

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    stop_event = await job_manager.register(job_id, session_owner)

    # Initialize job in SQLite
    await temp_store.create_job(
        job_id=job_id,
        session_owner=session_owner,
        is_authenticated=is_authenticated,
        prompt=payload.prompt,
    )

    # Step 2: Background Task Worker
    async def _run_scraper_task():
        try:
            limit = action_plan.target_leads
            if not is_authenticated:
                if limit is None or limit > ANONYMOUS_LEAD_LIMIT:
                    limit = ANONYMOUS_LEAD_LIMIT
            await asyncio.to_thread(
                run_pipeline,
                plan=action_plan,
                job_id=job_id,
                session_owner=session_owner,
                is_authenticated=is_authenticated,
                stop_event=stop_event,
                max_leads_limit=limit,
                export_files=True,
            )
        except Exception as exc:
            print(f"[Worker Error] Job {job_id} failed: {exc}", flush=True)
            await temp_store.update_job(job_id, status="failed", current_area=f"Error: {str(exc)[:100]}")
        finally:
            await job_manager.release(job_id, session_owner)

    asyncio.create_task(_run_scraper_task())

    return {
        "status": "started",
        "job_id": job_id,
        "is_authenticated": is_authenticated,
        "session_owner": session_owner,
        "prompt": payload.prompt,
        "keywords": action_plan.keywords,
        "sub_locations_count": len(action_plan.sub_locations),
        "enrichment_enabled": action_plan.enrichment.enabled,
    }


@app.get("/api/scrape/stream/{job_id}", tags=["Scraper"])
async def stream_scraping_events(job_id: str):
    """
    Server-Sent Events (SSE) live streaming endpoint:
    Streams live progress every ~800ms with:
    - job status ('running', 'completed', 'stopped', 'limit_reached')
    - current sub-location being searched
    - total leads count
    - batch of newly parsed unique leads
    """
    job = await temp_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Scraping job not found.")

    async def event_generator():
        last_seen_id = 0
        while True:
            current_job = await temp_store.get_job(job_id)
            if not current_job:
                payload = {"error": "Job disappeared", "done": True}
                yield f"data: {json.dumps(payload)}\n\n"
                break

            # Fetch any new leads added since last stream tick
            new_leads = []
            async with aiosqlite.connect(str(TEMP_DB_PATH)) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT id, lead_json FROM temp_leads WHERE job_id = ? AND id > ? ORDER BY id ASC LIMIT 50",
                    (job_id, last_seen_id),
                ) as cursor:
                    rows = await cursor.fetchall()
                    for row in rows:
                        last_seen_id = row["id"]
                        try:
                            new_leads.append(json.loads(row["lead_json"]))
                        except Exception:
                            pass

            current_status = current_job["status"]
            is_done = current_status in ("completed", "stopped", "limit_reached", "failed")

            data = {
                "job_id": job_id,
                "status": current_status,
                "current_area": current_job["current_area"],
                "leads_count": current_job["leads_count"],
                "new_leads": new_leads,
                "done": is_done,
            }
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

            if is_done and len(new_leads) == 0:
                try:
                    final_leads = await temp_store.get_temp_leads(job_id)
                    data["final_leads"] = [l.model_dump() for l in final_leads]
                    data["done"] = True
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                except Exception:
                    pass
                break

            await asyncio.sleep(0.8)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/scrape/stop/{job_id}", tags=["Scraper"])
async def stop_scraping_job(
    job_id: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """
    Signals the running scraper to stop immediately.
    All leads collected up to this moment are preserved in SQLite with zero data loss.
    """
    job = await temp_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    stopped = await job_manager.stop(job_id)
    await temp_store.update_job(job_id, status="stopped", current_area="Stopped by user")

    return {
        "status": "stopped",
        "job_id": job_id,
        "message": "Scraper stopped successfully. Preserved all scraped leads.",
        "leads_count": job["leads_count"],
    }


@app.get("/api/scrape/download/{job_id}", tags=["Scraper"])
async def download_scraped_leads(
    job_id: str,
    format: str = Query("csv", pattern="^(csv|json|xlsx)$"),
):
    """
    Downloads all leads scraped during the specified job session.
    - XLSX format provides an executive-grade styled Excel spreadsheet with auto-filters and styling.
    - CSV format includes UTF-8 BOM (\ufeff) for flawless opening in Microsoft Excel.
    - JSON format provides full structured LeadItem objects.
    """
    leads = await temp_store.get_temp_leads(job_id)
    if not leads:
        raise HTTPException(
            status_code=404,
            detail="No leads found for this job ID. Job may still be initializing or returned zero results.",
        )

    if format == "xlsx":
        excel_bytes = generate_leads_excel(leads, title=f"Job {job_id}")
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="leads_{job_id}.xlsx"'},
        )

    if format == "json":
        data = [lead.model_dump() for lead in leads]
        json_content = json.dumps(data, indent=2, ensure_ascii=False)
        return Response(
            content=json_content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="leads_{job_id}.json"'},
        )

    # CSV Format
    fieldnames = [
        "place_id", "name", "category", "phone", "website_status", "website_url",
        "facebook", "instagram", "linkedin", "whatsapp", "emails", "cms_tech",
        "rating", "reviews_count", "price_range", "is_unclaimed_business",
        "neighborhood", "address", "latitude", "longitude", "order_link",
        "google_maps_url", "source_query"
    ]

    output = io.StringIO()
    # Add UTF-8 BOM so Excel opens non-ASCII characters cleanly
    output.write("\ufeff")
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for lead in leads:
        writer.writerow({
            "place_id": lead.place_id,
            "name": lead.name,
            "category": lead.category or "",
            "phone": lead.phone or "",
            "website_status": lead.website_status,
            "website_url": lead.website_url or "",
            "facebook": lead.social_links.facebook or "",
            "instagram": lead.social_links.instagram or "",
            "linkedin": lead.social_links.linkedin or "",
            "whatsapp": lead.social_links.whatsapp or "",
            "emails": "; ".join(lead.emails) if lead.emails else "",
            "cms_tech": lead.cms_tech or "",
            "rating": lead.rating if lead.rating is not None else "",
            "reviews_count": lead.reviews_count,
            "price_range": lead.price_range or "",
            "is_unclaimed_business": "Yes" if lead.is_unclaimed_business else "No",
            "neighborhood": lead.neighborhood or "",
            "address": lead.address or "",
            "latitude": lead.lat if lead.lat is not None else "",
            "longitude": lead.lon if lead.lon is not None else "",
            "order_link": lead.order_link or "",
            "google_maps_url": lead.google_maps_url or "",
            "source_query": lead.source_query or "",
        })

    csv_content = output.getvalue()
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="leads_{job_id}.csv"'},
    )


@app.post("/api/auth/sync-session", tags=["Auth & Cloud Sync"])
async def sync_anonymous_session(
    payload: SyncSessionRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Migrates local SQLite temporary leads into the user's permanent Supabase Cloud storage.
    Triggered when an anonymous user finishes scraping (e.g. at 1,000 limit) and signs in with Google.
    """
    sb_client = supabase_db.get_supabase_client()
    user = security.get_current_user_required(authorization, supabase_client=sb_client)

    result = supabase_db.sync_temp_session_to_supabase(
        user_uid=user["user_uid"],
        email=user["email"],
        job_id=payload.job_id,
        full_name=user["full_name"],
    )

    if result.get("status") == "empty":
        raise HTTPException(status_code=404, detail="No leads found in temporary session to sync.")

    return result


@app.get("/api/user/my-leads", tags=["User"])
async def get_my_saved_leads(
    authorization: Optional[str] = Header(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """
    Retrieves all previously saved leads from Supabase Cloud for the authenticated user.
    """
    sb_client = supabase_db.get_supabase_client()
    user = security.get_current_user_required(authorization, supabase_client=sb_client)

    leads = supabase_db.get_user_saved_leads(
        user_uid=user["user_uid"],
        limit=limit,
        offset=offset,
    )

    return {
        "user_uid": user["user_uid"],
        "email": user["email"],
        "count": len(leads),
        "leads": leads,
    }


@app.post("/api/reviews", tags=["Reviews & Feedback"])
@limiter.limit("3/day")
async def submit_product_review(
    request: Request,
    payload: ReviewSubmitRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Submits user rating, comment, and interest in paid tiers to Supabase product_reviews.
    Rate-limited to 3 submissions per day to prevent spam.
    """
    user_email = None
    try:
        sb_client = supabase_db.get_supabase_client()
        user = security.get_current_user_optional(authorization, supabase_client=sb_client)
        if user:
            user_email = user["email"]
    except Exception:
        pass

    review = supabase_db.create_product_review(
        rating=payload.rating,
        comment=payload.comment,
        user_email=user_email,
        wants_paid_version=payload.wants_paid_version,
    )

    return {
        "status": "success",
        "message": "Thank you for your valuable feedback!",
        "review": review,
    }


@app.get("/api/reviews", tags=["Reviews & Feedback"])
async def list_recent_reviews(
    limit: int = Query(20, ge=1, le=100),
):
    """Returns recent product reviews for public display in the UI feedback section."""
    reviews = supabase_db.get_product_reviews(limit=limit)
    return {
        "count": len(reviews),
        "reviews": reviews,
    }
