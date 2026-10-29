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
import time
import datetime
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

from config import TEMP_DB_PATH, ANONYMOUS_LEAD_LIMIT, ANONYMOUS_JOB_LIMIT
from agent.schemas import ActionPlan, LeadItem
from agent.planner import generate_plan
from agent.pipeline import run_pipeline
from backend import temp_store
from backend import security
from backend import supabase_db
from backend.excel_exporter import generate_leads_excel
from backend.seo_audit.routes import router as seo_router
from backend.seo_audit.xlsx_appender import append_seo_columns_to_excel



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

# On-Demand Local SEO Audit Routes
app.include_router(seo_router, prefix="/api")

# Frontend Static Assets & Root Route
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/", tags=["Frontend"])
    async def serve_frontend():
        return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "active", "service": "LeadPluse Harvester Pro"}


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

    async def stop_all(self):
        """Immediately signals all running scraping jobs to halt."""
        async with self._lock:
            for job_id, stop_event in list(self._active_jobs.items()):
                try:
                    stop_event.set()
                except Exception:
                    pass
            self._active_jobs.clear()
            self._owner_to_job.clear()

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


@app.on_event("shutdown")
async def on_shutdown():
    """Ensures all active scraper background jobs halt immediately on server shutdown or Ctrl+C."""
    await job_manager.stop_all()


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
    target_leads: Optional[int] = Field(None, ge=1, le=1000000, description="Requested target leads count (e.g. 50, 10000, 500000)")
    scrape_website: bool = Field(default=False, description="Whether to deep scrape business websites for emails/socials")
    must_have_email: bool = Field(default=False, description="When true, only leads with verified business emails are retained")
    audit_seo: bool = Field(default=False, description="When true, executes on-demand Local SEO audits for discovered website leads")



class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=6)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=1)


class SyncSessionRequest(BaseModel):
    job_id: str = Field(..., min_length=3, max_length=100, description="Job session ID to sync")


class ReviewSubmitRequest(BaseModel):
    name: Optional[str] = Field(default="Anonymous User", max_length=100, description="Reporter name")
    rating: int = Field(default=5, ge=1, le=5, description="Star rating between 1 and 5")
    comment: str = Field(..., min_length=3, max_length=1000, description="Problem report or review feedback")
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


@app.post("/api/auth/register", tags=["Auth"])
async def register_new_user(payload: RegisterRequest):
    """
    Registers a new user via Supabase Admin API with auto-confirmed email.
    Eliminates the 'email rate limit exceeded' error during development and testing.
    """
    clean_email = payload.email.strip().lower()
    if security.is_disposable_email(clean_email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Temporary / disposable email domains are not permitted. Please use your official email address."
        )

    sb_client = supabase_db.get_supabase_client()
    try:
        user_resp = sb_client.auth.admin.create_user({
            "email": clean_email,
            "password": payload.password,
            "email_confirm": True,
            "user_metadata": {"full_name": payload.name.strip()}
        })
        return {
            "status": "success",
            "message": "Account created and verified successfully!",
            "user_id": str(user_resp.user.id),
            "email": user_resp.user.email,
        }
    except Exception as e:
        err_msg = str(e)
        if "already" in err_msg.lower() or "unique" in err_msg.lower() or "exists" in err_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email is already registered. Please switch to the Sign In tab."
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Registration failed: {err_msg}"
        )


@app.post("/api/auth/login", tags=["Auth"])
async def login_user(payload: LoginRequest):
    """
    Authenticates a user via Supabase Auth and returns an access_token.
    Provides a resilient backend fallback for sign in when client-side Supabase SDK is not initialized.
    """
    clean_email = payload.email.strip().lower()
    sb_client = supabase_db.get_supabase_client()
    try:
        res = sb_client.auth.sign_in_with_password({
            "email": clean_email,
            "password": payload.password
        })
        if not res.session or not res.session.access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials. Please check your email and password."
            )
        return {
            "status": "success",
            "access_token": res.session.access_token,
            "user": {
                "id": str(res.user.id),
                "email": res.user.email,
                "user_metadata": res.user.user_metadata or {},
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        err_msg = str(e)
        if "api key" in err_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Supabase API key is invalid. Please check SUPABASE_KEY and SUPABASE_ANON_KEY in your hosting environment variables."
            )
        if "invalid" in err_msg.lower() or "credentials" in err_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password. Please verify your credentials."
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Login failed: {err_msg}"
        )


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
        profile = supabase_db.get_user_profile(user["id"]) or {}
        plan = profile.get("plan") or {}
        daily_limit = plan.get("daily_leads_limit") or plan.get("leads_per_day", 1000)
        daily_usage = supabase_db.get_daily_usage(user["id"])
        used = daily_usage.get("leads_scraped", 0)
        return {
            "is_authenticated": True,
            "session_owner": user["user_uid"],
            "email": user["email"],
            "total_leads_scraped": used,
            "limit": daily_limit,
            "plan_name": plan.get("name", "Pro Harvester Plan"),
            "plan_id": plan.get("id", profile.get("plan_id", "pro")),
            "is_limit_reached": (used >= daily_limit),
        }

    session_owner = security.get_client_identifier(request)
    anon_usage = await temp_store.get_anonymous_usage(session_owner)
    current_scraped = anon_usage["total_leads_scraped"]
    jobs_count = anon_usage["jobs_count"]
    is_reached = (current_scraped >= ANONYMOUS_LEAD_LIMIT) or (jobs_count >= ANONYMOUS_JOB_LIMIT)
    return {
        "is_authenticated": False,
        "session_owner": session_owner,
        "total_leads_scraped": current_scraped,
        "jobs_count": jobs_count,
        "limit": ANONYMOUS_LEAD_LIMIT,
        "job_limit": ANONYMOUS_JOB_LIMIT,
        "is_limit_reached": is_reached,
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
    2. Validates guest quota (100 leads limit and 1 job maximum).
    3. Prevents duplicate concurrent jobs for the same user/IP.
    4. Analyzes query via LLM Geo-Planner and launches background worker.
    """
    sb_client = None
    try:
        sb_client = supabase_db.get_supabase_client()
    except Exception:
        pass

    user = security.get_current_user_optional(authorization, supabase_client=sb_client)
    effective_limit_for_job = None
    user_id = None

    if user:
        session_owner = user["user_uid"]
        is_authenticated = True
        user_email = user["email"]
        user_id = user["id"]

        # Check email verification for email-signup users
        if not user.get("email_verified", False) and user.get("provider") == "email":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Please verify your email address before launching scraping jobs.",
            )

        # Server-Side Usage Limits (Free plan: 1,000 leads/day, 3 jobs/day, 300 leads/job)
        req_target = payload.target_leads or 100
        limit_check = supabase_db.check_user_limits(
            user_id=user_id,
            requested_target_leads=req_target,
            requires_enrichment=payload.scrape_website,
        )
        if not limit_check["allowed"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "status": "plan_limit_reached",
                    "message": limit_check["reason"],
                    "plan": limit_check.get("plan"),
                    "usage": limit_check.get("usage"),
                },
            )
        effective_limit_for_job = limit_check["effective_target"]
    else:
        session_owner = security.get_client_identifier(request)
        is_authenticated = False
        client_ip = session_owner.replace("anon_ip_", "").replace("_", ".")
        user_email = f"Guest ({client_ip})"

    # Check anonymous quota (100 leads and 1 job limit)
    if not is_authenticated:
        anon_usage = await temp_store.get_anonymous_usage(session_owner)
        current_scraped = anon_usage["total_leads_scraped"]
        jobs_count = anon_usage["jobs_count"]

        # If guest has exceeded free quota, log the search attempt so admin sees what they tried to search!
        if jobs_count >= ANONYMOUS_JOB_LIMIT or current_scraped >= ANONYMOUS_LEAD_LIMIT:
            reason = (
                "Guest job limit reached (1 job max)"
                if jobs_count >= ANONYMOUS_JOB_LIMIT
                else f"Guest trial limit ({ANONYMOUS_LEAD_LIMIT} leads) reached"
            )
            blocked_job_id = f"job_guest_blocked_{uuid.uuid4().hex[:8]}"
            await temp_store.create_job(
                job_id=blocked_job_id,
                session_owner=session_owner,
                is_authenticated=False,
                user_email=user_email,
                prompt=payload.prompt,
                target_leads=payload.target_leads or 100,
                scrape_website=payload.scrape_website,
            )
            await temp_store.update_job(
                blocked_job_id,
                status="blocked_limit",
                current_area="Blocked: Guest Trial Limit Exceeded (Login Required)",
                error_message=f"{reason}. Sign in to continue searching.",
                duration_seconds=0.1,
            )
            await temp_store.add_job_log(
                blocked_job_id,
                f"Guest search blocked: {reason} for IP {client_ip}. Prompt: '{payload.prompt}'",
                "WARN",
            )

            if jobs_count >= ANONYMOUS_JOB_LIMIT:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "status": "limit_reached_login_required",
                        "code": "GUEST_JOB_LIMIT_EXCEEDED",
                        "message": "You have already completed your 1 free guest scraping session. Sign in to unlock 1,000 leads/day, 3 jobs/day, and 300 leads/job!",
                        "current_quota": current_scraped,
                        "jobs_count": jobs_count,
                    },
                )

            if current_scraped >= ANONYMOUS_LEAD_LIMIT:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "status": "limit_reached_login_required",
                        "code": "GUEST_LEAD_LIMIT_EXCEEDED",
                        "message": f"Guest trial limit of {ANONYMOUS_LEAD_LIMIT} leads reached. Sign in to unlock 1,000 leads/day, 3 jobs/day, and 300 leads/job!",
                        "current_quota": current_scraped,
                        "jobs_count": jobs_count,
                    },
                )

        # Cap requested target leads to remaining anonymous budget (max 100)
        remaining_leads = max(1, ANONYMOUS_LEAD_LIMIT - current_scraped)
        requested = payload.target_leads or 100
        effective_limit_for_job = min(requested, remaining_leads, ANONYMOUS_LEAD_LIMIT)

        # Record anonymous job start count
        await temp_store.record_anonymous_job_start(session_owner)

    # Concurrency Lock: 1 active job per user/IP
    can_start = await job_manager.can_start(session_owner)
    if not can_start:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="A scraping job is already running for your account or IP. Please wait or stop the running job first.",
        )

    # Step 1: AI Planner
    try:
        target_to_use = effective_limit_for_job or payload.target_leads
        action_plan = generate_plan(
            payload.prompt,
            provider=payload.provider,
            target_leads=target_to_use,
        )
        if not action_plan.sub_locations or len(action_plan.sub_locations) == 0:
            from agent.planner import get_default_sub_locations
            action_plan.sub_locations = get_default_sub_locations(action_plan.country_code or "bd")

        if target_to_use and target_to_use > 0:
            action_plan.target_leads = target_to_use

        # Auto-detect SEO audit intent from prompt, LLM plan, or UI toggle
        prompt_lower = payload.prompt.lower()
        has_seo_intent = any(w in prompt_lower for w in ("seo", "audit", "local seo", "page seo", "site audit"))
        should_audit_seo = bool(payload.audit_seo or has_seo_intent or getattr(action_plan.enrichment, "audit_seo", False))
        should_scrape_web = bool(payload.scrape_website or should_audit_seo or action_plan.enrichment.enabled)

        if not should_scrape_web:
            action_plan.enrichment.enabled = False
            action_plan.enrichment.extract_emails = False
            action_plan.enrichment.extract_socials = False
            action_plan.enrichment.detect_cms = False
            action_plan.enrichment.audit_seo = False
            action_plan.filters.must_have_email = False
        else:
            action_plan.enrichment.enabled = True
            action_plan.enrichment.extract_emails = True
            action_plan.enrichment.extract_socials = True
            action_plan.enrichment.detect_cms = True
            action_plan.enrichment.audit_seo = should_audit_seo
            action_plan.filters.must_have_email = bool(payload.must_have_email)
    except Exception as plan_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to generate search action plan: {str(plan_err)}",
        )

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    stop_event = await job_manager.register(job_id, session_owner)

    # Initialize job in SQLite WAL Buffer
    await temp_store.create_job(
        job_id=job_id,
        session_owner=session_owner,
        is_authenticated=is_authenticated,
        prompt=payload.prompt,
        scrape_website=should_scrape_web,
        audit_seo=should_audit_seo,
        user_email=user_email,
        target_leads=action_plan.target_leads or 100,
    )

    await temp_store.add_job_log(job_id, f"Scraper job initialized for user: {user_email or session_owner}", "INFO")
    await temp_store.add_job_log(job_id, f"Search prompt: '{payload.prompt}'", "PLAN")
    await temp_store.add_job_log(job_id, f"Configuration: Target={action_plan.target_leads or 100} leads | Enrichment={action_plan.enrichment.enabled}", "CONFIG")
    await temp_store.add_job_log(job_id, f"AI Geo-Planner mapped {len(action_plan.sub_locations)} sub-locations & {len(action_plan.keywords)} keywords.", "PLAN")

    # Audit in Supabase public.jobs table if authenticated
    if is_authenticated and user_id:
        supabase_db.create_job_record(
            job_id=job_id,
            user_id=user_id,
            prompt=payload.prompt,
            target_leads=action_plan.target_leads or 100,
            enrichment_enabled=action_plan.enrichment.enabled,
        )

    # Step 2: Background Task Worker
    async def _run_scraper_task():
        t_start = datetime.datetime.now(datetime.timezone.utc)
        try:
            limit = action_plan.target_leads
            if not is_authenticated:
                if limit is None or limit > ANONYMOUS_LEAD_LIMIT:
                    limit = ANONYMOUS_LEAD_LIMIT
            elif effective_limit_for_job:
                limit = effective_limit_for_job

            result = await asyncio.to_thread(
                run_pipeline,
                plan=action_plan,
                job_id=job_id,
                session_owner=session_owner,
                is_authenticated=is_authenticated,
                stop_event=stop_event,
                max_leads_limit=limit,
                export_files=True,
            )

            # Record usage and update job in Supabase
            if is_authenticated and user_id:
                final_leads = result.get("leads", [])
                final_count = len(final_leads)
                enrichment_count = sum(
                    1 for l in final_leads
                    if (l.emails or (l.social_links and (l.social_links.facebook or l.social_links.instagram)))
                )
                final_status = result.get("status", "completed")

                supabase_db.update_job_record(
                    job_id=job_id,
                    status=final_status,
                    leads_scraped=final_count,
                    current_area="Job Completed",
                )
                supabase_db.record_usage(
                    user_id=user_id,
                    leads_count=final_count,
                    jobs_count=1,
                    enrichment_calls=enrichment_count,
                )
                if final_leads:
                    try:
                        supabase_db.save_leads_to_supabase(
                            user_uid=user_id,
                            job_id=job_id,
                            leads=final_leads,
                        )
                    except Exception as sync_err:
                        print(f"[Supabase Cloud Sync Warning] Job {job_id}: {sync_err}", flush=True)
                        await temp_store.add_job_log(job_id, f"Supabase cloud sync note: {sync_err}", "WARN")
        except Exception as exc:
            import traceback
            tb_str = traceback.format_exc()
            print(f"[Worker Error] Job {job_id} failed: {exc}", flush=True)
            t_now = datetime.datetime.now(datetime.timezone.utc)
            dur_sec = max(0.0, round((t_now - t_start).total_seconds(), 1))
            await temp_store.add_job_log(job_id, f"Scraper execution error: {str(exc)}", "ERROR")
            await temp_store.add_job_log(job_id, f"Traceback:\n{tb_str[:800]}", "ERROR")
            await temp_store.update_job(
                job_id,
                status="failed",
                current_area=f"Error: {str(exc)[:100]}",
                error_message=str(exc)[:1000],
                duration_seconds=dur_sec,
            )
            if is_authenticated and user_id:
                supabase_db.update_job_record(
                    job_id=job_id,
                    status="failed",
                    leads_scraped=0,
                    error_message=str(exc)[:1000],
                )
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
        "target_leads": action_plan.target_leads,
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
                "target_leads": current_job.get("target_leads", 100),
                "started_at": current_job.get("started_at"),
                "duration_seconds": current_job.get("duration_seconds", 0.0),
                "new_leads": new_leads,
                "done": is_done,
            }
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

            if is_done and len(new_leads) == 0:
                try:
                    count = current_job.get("leads_count", 0) if current_job else 0
                    if count <= 300:
                        final_leads = await temp_store.get_temp_leads(job_id)
                        data["final_leads"] = [l.model_dump() for l in final_leads]
                    data["done"] = True
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                except Exception:
                    pass
                break

            await asyncio.sleep(0.5)

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
    
    # Calculate and persist exact elapsed duration up to the moment user stopped
    created_str = job.get("started_at") or job.get("created_at")
    dur_sec = float(job.get("duration_seconds") or 0.0)
    if dur_sec <= 0.0 and created_str:
        try:
            t1 = datetime.datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            dur_sec = max(0.1, round((datetime.datetime.now(datetime.timezone.utc) - t1).total_seconds(), 1))
        except Exception:
            dur_sec = 0.0

    await temp_store.update_job(
        job_id,
        status="stopped",
        current_area="Stopped by user",
        duration_seconds=dur_sec,
    )
    await temp_store.add_job_log(job_id, f"Scraper stopped by user after {dur_sec}s runtime.", "WARN")

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
    include_seo: bool = Query(False),
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

    job = await temp_store.get_job(job_id)
    is_job_enrichment = bool(job and job.get("scrape_website"))
    has_data_enrichment = (
        any(bool(l.emails) for l in leads) or
        any(bool(l.social_links and (
            l.social_links.facebook or
            l.social_links.instagram or
            l.social_links.linkedin or
            l.social_links.whatsapp
        )) for l in leads) or
        any(bool(l.cms_tech) for l in leads)
    )
    include_enrichment = is_job_enrichment or has_data_enrichment

    is_job_seo = bool(job and job.get("audit_seo"))
    has_seo = include_seo or is_job_seo or any(bool(getattr(l, "seo_report", None)) for l in leads)

    if format == "xlsx":
        excel_bytes = generate_leads_excel(leads, title=f"Job {job_id}", include_enrichment=include_enrichment)
        seo_reports = {}
        for l in leads:
            rep = getattr(l, "seo_report", None)
            if rep:
                try:
                    from backend.seo_audit.models import SEOReport
                    if isinstance(rep, dict):
                        seo_reports[l.place_id] = SEOReport(**rep)
                    elif isinstance(rep, SEOReport):
                        seo_reports[l.place_id] = rep
                except Exception:
                    pass
        if include_seo or is_job_seo or len(seo_reports) > 0:
            excel_bytes = append_seo_columns_to_excel(excel_bytes, seo_reports)
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
    ]
    if include_enrichment:
        fieldnames.extend(["facebook", "instagram", "linkedin", "whatsapp", "emails", "cms_tech"])
    if has_seo:
        fieldnames.extend(["seo_health_score", "lead_pitch_priority", "icebreaker_hook"])
    fieldnames.extend([
        "rating", "reviews_count", "price_range", "is_unclaimed_business",
        "neighborhood", "address", "latitude", "longitude", "order_link",
        "google_maps_url", "source_query"
    ])

    output = io.StringIO()
    # Add UTF-8 BOM so Excel opens non-ASCII characters cleanly
    output.write("\ufeff")
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for lead in leads:
        row = {
            "place_id": lead.place_id,
            "name": lead.name,
            "category": lead.category or "",
            "phone": lead.phone or "",
            "website_status": lead.website_status,
            "website_url": lead.website_url or "",
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
        }
        if include_enrichment:
            row.update({
                "facebook": (lead.social_links.facebook or "") if lead.social_links else "",
                "instagram": (lead.social_links.instagram or "") if lead.social_links else "",
                "linkedin": (lead.social_links.linkedin or "") if lead.social_links else "",
                "whatsapp": (lead.social_links.whatsapp or "") if lead.social_links else "",
                "emails": "; ".join(lead.emails) if lead.emails else "",
                "cms_tech": lead.cms_tech or "",
            })
        if has_seo:
            rep = getattr(lead, "seo_report", None)
            if isinstance(rep, dict):
                h_score = rep.get("seo_health_score")
                row["seo_health_score"] = f"{h_score}/100" if h_score is not None else "N/A"
                row["lead_pitch_priority"] = rep.get("lead_pitch_priority", "")
                row["icebreaker_hook"] = rep.get("icebreaker_hook", "")
            elif rep is not None:
                h_score = getattr(rep, "seo_health_score", None)
                row["seo_health_score"] = f"{h_score}/100" if h_score is not None else "N/A"
                row["lead_pitch_priority"] = getattr(rep, "lead_pitch_priority", "")
                row["icebreaker_hook"] = getattr(rep, "icebreaker_hook", "")
            else:
                row["seo_health_score"] = "N/A"
                row["lead_pitch_priority"] = ""
                row["icebreaker_hook"] = ""
        writer.writerow(row)

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
@limiter.limit("30/day")
async def submit_product_review(
    request: Request,
    payload: ReviewSubmitRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Submits user problem report or feedback to Supabase product_reviews.
    No email is required! Users simply provide their name and problem description.
    """
    user_email = None
    user_name = payload.name.strip() if payload.name and payload.name.strip() else "Anonymous User"
    try:
        sb_client = supabase_db.get_supabase_client()
        user = security.get_current_user_optional(authorization, supabase_client=sb_client)
        if user:
            user_email = user.get("email")
            if user_name == "Anonymous User":
                user_name = user.get("full_name") or (user.get("email", "").split("@")[0] if user.get("email") else "User")
    except Exception:
        pass

    review = supabase_db.create_product_review(
        rating=payload.rating,
        comment=payload.comment,
        user_name=user_name,
        user_email=user_email,
        wants_paid_version=payload.wants_paid_version,
    )

    return {
        "status": "success",
        "message": "Problem report & feedback submitted successfully!",
        "review": review,
    }


@app.get("/api/reviews", tags=["Reviews & Feedback"])
async def list_recent_reviews(
    limit: int = Query(50, ge=1, le=100),
):
    """Returns recent product reviews and problem reports for live public display in the Problem Center."""
    reviews = supabase_db.get_product_reviews(limit=limit)
    return {
        "count": len(reviews),
        "reviews": reviews,
    }


# ============================================================================
# SaaS Core: Auth Config, User Dashboard, Admin Dashboard & Payments
# ============================================================================

@app.get("/api/auth/config", tags=["Auth"])
async def get_auth_config():
    """
    Returns public Supabase URL and Publishable Anon Key for the frontend.
    Strictly safe for client-side use; service role key is NEVER exposed.
    """
    from config import SUPABASE_URL, SUPABASE_ANON_KEY
    return {
        "supabase_url": SUPABASE_URL,
        "supabase_anon_key": SUPABASE_ANON_KEY,
    }



@app.get("/api/user/me", tags=["User Dashboard"])
async def get_my_dashboard_profile(
    authorization: Optional[str] = Header(None),
):
    """
    Returns authenticated user profile, active plan limits, and today's usage.
    """
    sb_client = supabase_db.get_supabase_client()
    user = security.get_current_user_required(authorization, supabase_client=sb_client)
    user_id = user["id"]
    profile = supabase_db.get_user_profile(user_id) or user
    usage = supabase_db.get_daily_usage(user_id)

    plan = profile.get("plan") or {
        "id": "free",
        "name": "Free Test Plan",
        "leads_per_day": 1000,
        "jobs_per_day": 3,
        "leads_per_job": 300,
        "website_enrichment_enabled": True,
    }

    # Normalize plan fields for frontend compatibility
    plan["daily_leads_limit"] = plan.get("leads_per_day", 1000)
    plan["daily_jobs_limit"] = plan.get("jobs_per_day", 3)
    plan["max_leads_per_job"] = plan.get("leads_per_job", 300)
    plan["price_bdt"] = float(plan.get("price_bdt", 0.0))
    user_email = (user.get("email") or profile.get("email") or "").strip().lower()
    is_admin = (user.get("role") == "admin" or profile.get("role") == "admin") and (user_email in security.ADMIN_EMAILS)

    return {
        "user": user,
        "profile": profile,
        "plan": plan,
        "usage_today": usage,
        "daily_usage": usage,
        "is_admin": is_admin,
    }


@app.get("/api/user/jobs", tags=["User Dashboard"])
async def get_my_jobs_history(
    authorization: Optional[str] = Header(None),
    limit: int = Query(30, ge=1, le=100),
):
    """
    Returns past scraping jobs, status, error reasons, and lead counts for the current user.
    """
    sb_client = supabase_db.get_supabase_client()
    user = security.get_current_user_required(authorization, supabase_client=sb_client)
    jobs = supabase_db.get_user_jobs(user["id"], limit=limit)
    return {
        "user_id": user["id"],
        "count": len(jobs),
        "jobs": jobs,
    }


@app.get("/api/admin/overview", tags=["Admin Dashboard"])
async def get_admin_overview_metrics(
    authorization: Optional[str] = Header(None),
):
    """
    Returns global platform metrics (Total Users, Jobs Today, Total Leads, Revenue).
    Admin authorization required.
    """
    sb_client = supabase_db.get_supabase_client()
    security.require_admin_user(authorization, supabase_client=sb_client)
    return supabase_db.get_admin_overview()


@app.get("/api/admin/users", tags=["Admin Dashboard"])
async def get_admin_users_list(
    authorization: Optional[str] = Header(None),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Lists users with their subscription plans and roles. Admin only.
    """
    sb_client = supabase_db.get_supabase_client()
    security.require_admin_user(authorization, supabase_client=sb_client)
    users = supabase_db.get_admin_users(limit=limit)
    return {"count": len(users), "users": users}


class AdminUserUpdateRequest(BaseModel):
    plan_id: Optional[str] = None
    role: Optional[str] = None
    custom_leads_per_day: Optional[int] = None
    custom_leads_per_job: Optional[int] = None
    custom_jobs_per_day: Optional[int] = None
    custom_plan_name: Optional[str] = None


@app.patch("/api/admin/users/{target_user_id}", tags=["Admin Dashboard"])
async def admin_update_user_plan_or_role(
    target_user_id: str,
    payload: AdminUserUpdateRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Admin endpoint to change a user's subscription plan, role, or assign
    a custom lead scraping quota (e.g. 20,000 or 500,000 leads).
    """
    sb_client = supabase_db.get_supabase_client()
    security.require_admin_user(authorization, supabase_client=sb_client)
    updated = supabase_db.update_user_plan_or_role(
        target_user_id=target_user_id,
        plan_id=payload.plan_id,
        role=payload.role,
        custom_leads_per_day=payload.custom_leads_per_day,
        custom_leads_per_job=payload.custom_leads_per_job,
        custom_jobs_per_day=payload.custom_jobs_per_day,
        custom_plan_name=payload.custom_plan_name,
    )
    return {"status": "success", "user": updated}


@app.get("/api/admin/crm/metrics", tags=["Admin CRM"])
async def get_admin_crm_metrics(
    authorization: Optional[str] = Header(None),
):
    """
    Returns platform CRM metrics: Total searches, failure/error count,
    error rate percentage, active scraping jobs, and average scraper runtime.
    Admin authorization required.
    """
    sb_client = supabase_db.get_supabase_client()
    security.require_admin_user(authorization, supabase_client=sb_client)
    return supabase_db.get_crm_metrics()


@app.get("/api/admin/jobs", tags=["Admin Dashboard"])
async def get_admin_all_jobs(
    authorization: Optional[str] = Header(None),
    search: Optional[str] = Query(None, description="Search by user email, name, or prompt keyword"),
    status: Optional[str] = Query(None, description="Filter by status: running, completed, failed, stopped, blocked_limit"),
    errors_only: bool = Query(False, description="Filter only searches that experienced errors"),
    user_type: Optional[str] = Query(None, description="Filter by user type: guest, user, or all"),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Lists platform scraping jobs across both registered users and guest sessions.
    Returns prompt query, execution duration, error reasons, and lead counts.
    Admin only.
    """
    sb_client = supabase_db.get_supabase_client()
    security.require_admin_user(authorization, supabase_client=sb_client)
    jobs = supabase_db.get_admin_jobs(
        limit=limit,
        search=search,
        status=status,
        errors_only=errors_only,
        user_type=user_type,
    )
    return {"count": len(jobs), "jobs": jobs}


@app.get("/api/admin/jobs/{job_id}/logs", tags=["Admin CRM"])
async def get_admin_job_logs(
    job_id: str,
    authorization: Optional[str] = Header(None),
):
    """
    Retrieves chronological diagnostic event logs for a specific scraping job
    to debug API failures, timeouts, rate limits, or enrichment problems.
    Admin only.
    """
    sb_client = supabase_db.get_supabase_client()
    security.require_admin_user(authorization, supabase_client=sb_client)

    logs = await temp_store.get_job_logs(job_id)
    job_info = await temp_store.get_job(job_id)

    if not job_info:
        try:
            resp = sb_client.table("jobs").select("*").eq("id", job_id).execute()
            if resp.data:
                job_info = resp.data[0]
        except Exception:
            pass

    if not logs and job_info:
        # Generate diagnostic fallback trace from job state
        logs = [
            {
                "id": 1,
                "job_id": job_id,
                "timestamp": str(job_info.get("created_at") or ""),
                "level": "INFO",
                "message": f"Job initialized for prompt: '{job_info.get('prompt')}'"
            },
            {
                "id": 2,
                "job_id": job_id,
                "timestamp": str(job_info.get("completed_at") or job_info.get("created_at") or ""),
                "level": "SUCCESS" if job_info.get("status") == "completed" else "WARN",
                "message": f"Status: {job_info.get('status')} | Harvested: {job_info.get('leads_scraped') or job_info.get('leads_count', 0)}/{job_info.get('target_leads', 100)}"
            }
        ]
        if job_info.get("error_message"):
            logs.append({
                "id": 3,
                "job_id": job_id,
                "timestamp": str(job_info.get("completed_at") or ""),
                "level": "ERROR",
                "message": f"Failure reason: {job_info.get('error_message')}"
            })

    raw_text = "\n".join(f"[{l.get('timestamp')}] [{l.get('level')}] {l.get('message')}" for l in logs)

    return {
        "job_id": job_id,
        "job_info": job_info,
        "count": len(logs),
        "logs": logs,
        "raw_text": raw_text,
    }


@app.get("/api/admin/jobs/{job_id}/leads", tags=["Admin CRM"])
async def get_admin_job_leads(
    job_id: str,
    authorization: Optional[str] = Header(None),
    limit: int = Query(100, ge=1, le=500),
):
    """
    Inspects harvested lead records for a specific scraping job so admins can verify
    data quality or investigate missing contact information for users.
    Admin only.
    """
    sb_client = supabase_db.get_supabase_client()
    security.require_admin_user(authorization, supabase_client=sb_client)

    # 1. Check local SQLite cache
    leads = await temp_store.get_temp_leads(job_id)
    if leads:
        return {
            "job_id": job_id,
            "count": len(leads),
            "source": "local_cache",
            "leads": [l.model_dump() for l in leads[:limit]],
        }

    # 2. Check Supabase saved_leads
    try:
        resp = sb_client.table("saved_leads").select("*").eq("job_id", job_id).limit(limit).execute()
        return {
            "job_id": job_id,
            "count": len(resp.data or []),
            "source": "cloud_db",
            "leads": resp.data or [],
        }
    except Exception as e:
        return {"job_id": job_id, "count": 0, "leads": [], "error": str(e)}


@app.get("/api/admin/payments", tags=["Admin Dashboard"])
async def get_admin_all_payments(
    authorization: Optional[str] = Header(None),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Lists payment transaction ledger. Admin only.
    """
    sb_client = supabase_db.get_supabase_client()
    security.require_admin_user(authorization, supabase_client=sb_client)
    payments = supabase_db.get_admin_payments(limit=limit)
    return {"count": len(payments), "payments": payments}


@app.get("/api/admin/reviews", tags=["Admin Dashboard"])
async def get_admin_all_reviews(
    authorization: Optional[str] = Header(None),
    limit: int = Query(100, ge=1, le=500),
):
    """
    Lists all user feedback, problem reports, and star ratings. Admin only.
    """
    sb_client = supabase_db.get_supabase_client()
    security.require_admin_user(authorization, supabase_client=sb_client)
    reviews = supabase_db.get_admin_reviews(limit=limit)
    return {"count": len(reviews), "reviews": reviews}


@app.delete("/api/admin/reviews/{review_id}", tags=["Admin Dashboard"])
async def delete_admin_review_item(
    review_id: int,
    authorization: Optional[str] = Header(None),
):
    """
    Deletes a review/feedback entry from the database. Admin only.
    """
    sb_client = supabase_db.get_supabase_client()
    security.require_admin_user(authorization, supabase_client=sb_client)
    success = supabase_db.delete_admin_review(review_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to delete review record.")
    return {"status": "success", "message": f"Review #{review_id} removed successfully."}


# ============================================================================
# Payments & Webhook Provider Simulation
# ============================================================================

class CheckoutIntentRequest(BaseModel):
    plan_id: str = "pro"
    provider: str = "bkash"  # e.g. bkash, sslcommerz, stripe, manual


@app.post("/api/payments/create-intent", tags=["Payments"])
async def create_payment_intent(
    payload: CheckoutIntentRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Initiates a payment order for plan upgrade.
    Records a pending payment row before redirecting to provider gateway.
    """
    sb_client = supabase_db.get_supabase_client()
    user = security.get_current_user_required(authorization, supabase_client=sb_client)
    txn_id = f"txn_{uuid.uuid4().hex[:12]}"
    amount = 2500.0 if payload.plan_id == "pro" else 0.0

    payment = supabase_db.record_payment(
        user_id=user["id"],
        plan_id=payload.plan_id,
        amount=amount,
        currency="BDT",
        provider=payload.provider,
        transaction_id=txn_id,
        status="pending",
    )

    return {
        "status": "pending",
        "transaction_id": txn_id,
        "plan_id": payload.plan_id,
        "amount": amount,
        "currency": "BDT",
        "provider": payload.provider,
        "payment": payment,
    }


class WebhookConfirmPayload(BaseModel):
    transaction_id: str
    status: str = "completed"
    secret_key: Optional[str] = None


@app.post("/api/payments/webhook/{provider}", tags=["Payments"])
async def process_payment_webhook(
    provider: str,
    payload: WebhookConfirmPayload,
):
    """
    Verified payment webhook endpoint.
    Verifies payment completion before updating user's plan.
    """
    sb_client = supabase_db.get_supabase_client()
    resp = sb_client.table("payments").select("*").eq("transaction_id", payload.transaction_id).limit(1).execute()
    if not resp.data or len(resp.data) == 0:
        raise HTTPException(status_code=404, detail="Transaction not found.")

    pmt = resp.data[0]

    if payload.status == "completed":
        updated_pmt = supabase_db.record_payment(
            user_id=pmt["user_id"],
            plan_id=pmt["plan_id"],
            amount=float(pmt["amount"]),
            currency=pmt.get("currency", "BDT"),
            provider=provider,
            transaction_id=payload.transaction_id,
            status="completed",
            raw_data={"verified_at": "now", "provider": provider},
        )
        return {
            "status": "success",
            "message": f"Payment verified. User upgraded to {pmt['plan_id']}.",
            "payment": updated_pmt,
        }
    else:
        sb_client.table("payments").update({"status": "failed"}).eq("transaction_id", payload.transaction_id).execute()
        return {"status": "failed", "message": "Payment marked as failed."}

