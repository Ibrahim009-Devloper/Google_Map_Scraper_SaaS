# Admin CRM Cleanup & Guest Search Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all mock/test data from the Admin CRM database and implement comprehensive tracking for unauthenticated (guest) users who attempt or run searches, displaying their search prompts, timestamps, and search durations in the Admin CRM.

**Architecture:** 
1. Clean test artefacts from SQLite (`data/temp_cache.db`).
2. Intercept and log all guest search attempts in `backend/main.py` (including requests blocked by guest quota limits) using `backend/temp_store.py`.
3. Track and persist exact search duration (`duration_seconds`) across all outcomes (completed, stopped, failed, limit-blocked).
4. Enhance `backend/supabase_db.py` (`get_admin_jobs`) and the Admin CRM UI (`frontend/js/app.js` + `frontend/index.html`) with dedicated Guest vs Registered filtering and intuitive metrics.

**Tech Stack:** Python 3.11, FastAPI, SQLite (WAL mode), JavaScript (ES6+), TailwindCSS.

**Spec:** Approach 1 approved by user — Unified Tracking & Enhanced CRM.

## Global Constraints
- Do not affect legitimate registered user data or Supabase sync.
- Anonymous/Guest search data resides in local SQLite buffer with TTL, not saved permanently to Supabase cloud.
- Passwords or sensitive auth tokens must never be logged.
- Exact tested index map and schema must be preserved.

## Review Focus
- Guest users exceeding quota (1 job or 100 leads) must have their search query logged as `blocked_limit` rather than disappearing silently.
- Guest search duration must be calculated accurately if the guest stops the search midway via the Stop button.
- CRM Search filtering by query (prompt) and status must work seamlessly for guest searches.
- No dummy/mock jobs (`job_test_*`, `client.alex@gmail.com`) should reappear in the CRM table.
- Mobile/Responsive UI layout of the CRM table must remain unbroken with the new Guest filter.

---

### Task 1: Clean Up Fake / Mock Test Data from SQLite

**Files:**
- Modify: `backend/temp_store.py`
- Test: `tests/test_crm_cleanup.py`

**Interfaces:**
- Produces: `clean_mock_jobs_sync() -> int` in `backend/temp_store.py`.

- [ ] **Step 1: Write the test verifying mock jobs cleanup**

```python
# tests/test_crm_cleanup.py
from backend.temp_store import clean_mock_jobs_sync, get_sync_connection

def test_clean_mock_jobs():
    with get_sync_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO active_jobs (job_id, session_owner, prompt) VALUES ('job_test_dummy_999', 'anon', 'test')")
        conn.commit()
    cleaned = clean_mock_jobs_sync()
    assert cleaned >= 1
    with get_sync_connection() as conn:
        r = conn.execute("SELECT job_id FROM active_jobs WHERE job_id = 'job_test_dummy_999'").fetchone()
        assert r is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_crm_cleanup.py -v`
Expected: FAIL with ImportError / AttributeError `clean_mock_jobs_sync`

- [ ] **Step 3: Implement `clean_mock_jobs_sync()` in `backend/temp_store.py`**

Delete from `active_jobs`, `job_logs`, `temp_leads` where `job_id LIKE 'job_test_%'` OR `job_id LIKE 'job_sync_test_%'` OR `job_id LIKE 'job_stream_%'` OR `job_id LIKE 'job_running_%'` OR `job_id LIKE 'job_download_%'` OR `user_email = 'client.alex@gmail.com'`. Also execute once immediately to purge legacy test rows.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_crm_cleanup.py -v`
Expected: PASS

---

### Task 2: Backend Guest Search Tracking & Attempt Logging

**Files:**
- Modify: `backend/main.py:380-490`
- Modify: `backend/temp_store.py`
- Test: `tests/test_guest_tracking.py`

**Interfaces:**
- Produces: Interception in `/api/scrape/start` that records `blocked_limit` jobs before raising 403, and records `user_email=f"Guest ({client_ip})"` for guest searches.
- Updates: `/api/scrape/stop/{job_id}` to compute and persist elapsed duration if stopped midway.

- [ ] **Step 1: Write the test for guest search tracking**

```python
# tests/test_guest_tracking.py
from fastapi.testclient import TestClient
from backend.main import app
from backend.temp_store import get_job_sync

client = TestClient(app)

def test_guest_search_recorded():
    # Attempt search as guest
    resp = client.post("/api/scrape/start", json={"prompt": "Guest Plumbers in Dhanmondi", "target_leads": 10})
    # If 200 or 403 (if limit reached), verify job is recorded in SQLite
    assert resp.status_code in [200, 403]
```

- [ ] **Step 2: Run test to observe baseline behavior**

Run: `pytest tests/test_guest_tracking.py -v`

- [ ] **Step 3: Implement guest tracking in `backend/main.py`**

1. In `/api/scrape/start`, extract client IP via `security.get_client_identifier(request)` and format as `guest_label = f"Guest ({client_ip})"`.
2. If `jobs_count >= ANONYMOUS_JOB_LIMIT` or `current_scraped >= ANONYMOUS_LEAD_LIMIT`:
   Create an audit job record:
   ```python
   blocked_job_id = f"job_guest_blocked_{uuid.uuid4().hex[:8]}"
   await temp_store.create_job(
       job_id=blocked_job_id,
       session_owner=session_owner,
       is_authenticated=False,
       user_email=guest_label,
       prompt=payload.prompt,
       target_leads=payload.target_leads or 100,
       scrape_website=payload.scrape_website,
   )
   await temp_store.update_job(
       blocked_job_id,
       status="blocked_limit",
       current_area="Guest Quota Limit Reached (Login Required)",
       error_message="Guest quota exceeded. Sign in required to unlock full access.",
       duration_seconds=0.1,
   )
   ```
   Then raise the `HTTPException(403)`.
3. For permitted guest jobs, pass `user_email=guest_label` so the guest's IP is clearly identified in the CRM.
4. In `/api/scrape/stop/{job_id}`, calculate `duration_seconds` from `started_at` to now and update `active_jobs`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_guest_tracking.py -v`
Expected: PASS

---

### Task 3: Admin CRM Backend API Enhancements

**Files:**
- Modify: `backend/supabase_db.py:674-845`
- Modify: `backend/main.py` (admin router)
- Test: `tests/test_admin_guest_filter.py`

**Interfaces:**
- Consumes: `get_admin_jobs(limit, search, status, errors_only, user_type)`
- Produces: Updated `/api/admin/jobs?user_type=guest|user|all` and `status=blocked_limit`.

- [ ] **Step 1: Write test for admin guest filtering**

```python
# tests/test_admin_guest_filter.py
from backend.supabase_db import get_admin_jobs

def test_get_admin_jobs_guest_filter():
    jobs = get_admin_jobs(limit=50, user_type="guest")
    assert all(not j.get("is_authenticated") or j.get("user_role") == "guest" for j in jobs)
```

- [ ] **Step 2: Run test to verify failure / parameter missing**

Run: `pytest tests/test_admin_guest_filter.py -v`

- [ ] **Step 3: Update `get_admin_jobs` in `backend/supabase_db.py` and route in `backend/main.py`**

Add `user_type: Optional[str] = None` parameter. If `user_type == "guest"`, filter to `not is_authenticated or user_role == "guest"`. If `user_type == "user"`, filter to `is_authenticated and user_role != "guest"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_admin_guest_filter.py -v`
Expected: PASS

---

### Task 4: Admin CRM Frontend UI & Filter Updates

**Files:**
- Modify: `frontend/index.html:985-1030`
- Modify: `frontend/js/app.js:1930-2240`

**Interfaces:**
- Adds UI filters: `All`, `Registered Users`, `Guest (Non-Logged-in)`, `Errors`, `Running`, `Completed`.
- Enhances table rendering: Displays Guest badge with IP, Search query, Start time, Duration (e.g. `25s`), Harvest count, and Status.

- [ ] **Step 1: Add Guest Filter tab in `frontend/index.html`**

Add button `<button type="button" id="crmTabFilterGuest" onclick="filterAdminCrm('guest')" ...>Guest Searches</button>` and `<button type="button" id="crmTabFilterUser" onclick="filterAdminCrm('user')" ...>Registered Users</button>`.

- [ ] **Step 2: Update `filterAdminCrm(status)` and `renderAdminJobsTable()` in `frontend/js/app.js`**

Support `adminCrmFilter = "guest"` and `adminCrmFilter = "user"`.
Format status `blocked_limit` as a warning badge: `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-100 text-amber-800 border border-amber-300">LIMIT REACHED</span>`.

- [ ] **Step 3: Test UI in browser or with automated client request**

Verify Admin CRM renders smoothly, buttons switch filters accurately, and all fake data is gone.

---

### Task 5: End-to-End Verification

**Files:**
- Test: `test_e2e_guest_crm.py`

- [ ] **Step 1: Run complete test suite**

Run: `python test_e2e_guest_crm.py`
Expected:
1. Fake data is 0.
2. Guest search with query is logged with timestamp & duration.
3. Blocked guest search attempt is logged with query & timestamp.
4. Filter by 'guest' returns only guest searches.
