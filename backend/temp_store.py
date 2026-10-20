"""
Local SQLite Temp Buffer (WAL Mode) for Live Jobs & Anonymous Sessions.
Provides zero data loss on cancellation/crash, live batch caching,
and quota tracking for unauthenticated users.
"""

import os
import json
import sqlite3
import datetime
from typing import List, Dict, Any, Optional, Tuple, Union

import aiosqlite

from config import TEMP_DB_PATH, ANONYMOUS_LEAD_LIMIT, ANONYMOUS_JOB_LIMIT
from agent.schemas import LeadItem


INIT_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS anonymous_quotas (
    identifier TEXT PRIMARY KEY,
    total_leads_scraped INTEGER DEFAULT 0,
    jobs_count INTEGER DEFAULT 0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS active_jobs (
    job_id TEXT PRIMARY KEY,
    session_owner TEXT NOT NULL,
    is_authenticated INTEGER DEFAULT 0,
    prompt TEXT NOT NULL,
    status TEXT DEFAULT 'running',
    current_area TEXT DEFAULT 'Initializing AI Planner...',
    leads_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS temp_leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    place_id TEXT NOT NULL,
    lead_json TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, place_id)
);

CREATE INDEX IF NOT EXISTS idx_temp_leads_job_id ON temp_leads(job_id);
CREATE INDEX IF NOT EXISTS idx_active_jobs_owner ON active_jobs(session_owner);
"""


def get_sync_connection() -> sqlite3.Connection:
    """Returns a synchronous SQLite connection configured with WAL mode."""
    conn = sqlite3.connect(str(TEMP_DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db_sync() -> None:
    """Synchronously initializes database tables and sets WAL mode."""
    os.makedirs(TEMP_DB_PATH.parent, exist_ok=True)
    with get_sync_connection() as conn:
        conn.executescript(INIT_SQL)
        try:
            conn.execute("ALTER TABLE anonymous_quotas ADD COLUMN jobs_count INTEGER DEFAULT 0;")
            conn.commit()
        except Exception:
            pass


async def init_db() -> None:
    """Asynchronously initializes database tables and sets WAL mode."""
    os.makedirs(TEMP_DB_PATH.parent, exist_ok=True)
    async with aiosqlite.connect(str(TEMP_DB_PATH)) as db:
        await db.executescript(INIT_SQL)
        try:
            await db.execute("ALTER TABLE anonymous_quotas ADD COLUMN jobs_count INTEGER DEFAULT 0;")
        except Exception:
            pass
        await db.commit()


# ============================================================================
# Quota Management (Anonymous Users: 100 Leads & 1 Job Limit)
# ============================================================================

def get_anonymous_quota_sync(identifier: str) -> int:
    """Returns total leads scraped so far by an IP or device fingerprint."""
    with get_sync_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT total_leads_scraped FROM anonymous_quotas WHERE identifier = ?", (identifier,))
        row = cursor.fetchone()
        return row["total_leads_scraped"] if row else 0


async def get_anonymous_usage(identifier: str) -> Dict[str, int]:
    """Async: Returns total leads scraped and jobs count for unauthenticated user."""
    async with aiosqlite.connect(str(TEMP_DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT total_leads_scraped, COALESCE(jobs_count, 0) as jobs_count FROM anonymous_quotas WHERE identifier = ?",
            (identifier,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "total_leads_scraped": row["total_leads_scraped"] or 0,
                    "jobs_count": row["jobs_count"] or 0,
                }
            return {"total_leads_scraped": 0, "jobs_count": 0}


async def record_anonymous_job_start(identifier: str) -> None:
    """Increments jobs_count for an unauthenticated user upon starting a scrape job."""
    async with aiosqlite.connect(str(TEMP_DB_PATH)) as db:
        await db.execute(
            """
            INSERT INTO anonymous_quotas (identifier, total_leads_scraped, jobs_count, updated_at)
            VALUES (?, 0, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(identifier) DO UPDATE SET
                jobs_count = COALESCE(jobs_count, 0) + 1,
                updated_at = CURRENT_TIMESTAMP;
            """,
            (identifier,),
        )
        await db.commit()


async def get_anonymous_quota(identifier: str) -> int:
    """Async: Returns total leads scraped so far by an IP or device fingerprint."""
    usage = await get_anonymous_usage(identifier)
    return usage["total_leads_scraped"]


def increment_anonymous_quota_sync(identifier: str, count: int) -> int:
    """Increments the scraped count for an identifier and returns new total."""
    if count <= 0:
        return get_anonymous_quota_sync(identifier)
    with get_sync_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO anonymous_quotas (identifier, total_leads_scraped, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(identifier) DO UPDATE SET
                total_leads_scraped = total_leads_scraped + excluded.total_leads_scraped,
                updated_at = CURRENT_TIMESTAMP
            RETURNING total_leads_scraped;
            """,
            (identifier, count),
        )
        row = cursor.fetchone()
        conn.commit()
        return row[0] if row else count


async def increment_anonymous_quota(identifier: str, count: int) -> int:
    """Async: Increments the scraped count for an identifier and returns new total."""
    if count <= 0:
        return await get_anonymous_quota(identifier)
    async with aiosqlite.connect(str(TEMP_DB_PATH)) as db:
        cursor = await db.execute(
            """
            INSERT INTO anonymous_quotas (identifier, total_leads_scraped, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(identifier) DO UPDATE SET
                total_leads_scraped = total_leads_scraped + excluded.total_leads_scraped,
                updated_at = CURRENT_TIMESTAMP
            RETURNING total_leads_scraped;
            """,
            (identifier, count),
        )
        row = await cursor.fetchone()
        await db.commit()
        return row[0] if row else count


async def reset_anonymous_quota(identifier: str) -> None:
    """Async: Resets anonymous quota for an identifier back to 0."""
    async with aiosqlite.connect(str(TEMP_DB_PATH)) as db:
        await db.execute(
            "UPDATE anonymous_quotas SET total_leads_scraped = 0 WHERE identifier = ?",
            (identifier,),
        )
        await db.commit()


def reset_anonymous_quota_sync(identifier: str) -> None:
    """Sync: Resets anonymous quota for an identifier back to 0."""
    with get_sync_connection() as conn:
        conn.execute(
            "UPDATE anonymous_quotas SET total_leads_scraped = 0 WHERE identifier = ?",
            (identifier,),
        )
        conn.commit()


# ============================================================================
# Job State Management
# ============================================================================

def create_job_sync(job_id: str, session_owner: str, is_authenticated: bool, prompt: str) -> Dict[str, Any]:
    """Creates a new active scraping job record synchronously."""
    with get_sync_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO active_jobs (job_id, session_owner, is_authenticated, prompt, status, current_area, leads_count)
            VALUES (?, ?, ?, ?, 'running', 'Initializing AI Planner...', 0)
            """,
            (job_id, session_owner, 1 if is_authenticated else 0, prompt),
        )
        conn.commit()
    return {
        "job_id": job_id,
        "session_owner": session_owner,
        "is_authenticated": is_authenticated,
        "prompt": prompt,
        "status": "running",
        "current_area": "Initializing AI Planner...",
        "leads_count": 0,
    }


async def create_job(job_id: str, session_owner: str, is_authenticated: bool, prompt: str) -> Dict[str, Any]:
    """Async: Creates a new active scraping job record."""
    async with aiosqlite.connect(str(TEMP_DB_PATH)) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO active_jobs (job_id, session_owner, is_authenticated, prompt, status, current_area, leads_count)
            VALUES (?, ?, ?, ?, 'running', 'Initializing AI Planner...', 0)
            """,
            (job_id, session_owner, 1 if is_authenticated else 0, prompt),
        )
        await db.commit()
    return {
        "job_id": job_id,
        "session_owner": session_owner,
        "is_authenticated": is_authenticated,
        "prompt": prompt,
        "status": "running",
        "current_area": "Initializing AI Planner...",
        "leads_count": 0,
    }


def update_job_sync(
    job_id: str,
    status: Optional[str] = None,
    current_area: Optional[str] = None,
    leads_count: Optional[int] = None,
) -> None:
    """Updates job progress, status, or current area synchronously."""
    updates = []
    params = []
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if current_area is not None:
        updates.append("current_area = ?")
        params.append(current_area)
    if leads_count is not None:
        updates.append("leads_count = ?")
        params.append(leads_count)

    if not updates:
        return

    params.append(job_id)
    query = f"UPDATE active_jobs SET {', '.join(updates)} WHERE job_id = ?"
    with get_sync_connection() as conn:
        conn.execute(query, params)
        conn.commit()


async def update_job(
    job_id: str,
    status: Optional[str] = None,
    current_area: Optional[str] = None,
    leads_count: Optional[int] = None,
) -> None:
    """Async: Updates job progress, status, or current area."""
    updates = []
    params = []
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if current_area is not None:
        updates.append("current_area = ?")
        params.append(current_area)
    if leads_count is not None:
        updates.append("leads_count = ?")
        params.append(leads_count)

    if not updates:
        return

    params.append(job_id)
    query = f"UPDATE active_jobs SET {', '.join(updates)} WHERE job_id = ?"
    async with aiosqlite.connect(str(TEMP_DB_PATH)) as db:
        await db.execute(query, params)
        await db.commit()


def get_job_sync(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves active job record synchronously."""
    with get_sync_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM active_jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


async def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Async: Retrieves active job record."""
    async with aiosqlite.connect(str(TEMP_DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM active_jobs WHERE job_id = ?", (job_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


# ============================================================================
# Leads Storage & Retrieval
# ============================================================================

def save_temp_leads_batch_sync(job_id: str, leads: List[Union[LeadItem, Dict[str, Any]]]) -> int:
    """
    Saves a batch of leads to temp_leads table synchronously.
    Uses INSERT OR IGNORE to guarantee deduplication on (job_id, place_id).
    Updates leads_count on active_jobs.
    Returns the number of newly added leads.
    """
    if not leads:
        return 0

    records = []
    for lead in leads:
        if isinstance(lead, LeadItem):
            pid = lead.place_id
            lead_json = lead.model_dump_json()
        elif isinstance(lead, dict):
            pid = lead.get("place_id", "")
            lead_json = json.dumps(lead, ensure_ascii=False)
        else:
            continue
        if pid:
            records.append((job_id, pid, lead_json))

    if not records:
        return 0

    with get_sync_connection() as conn:
        cursor = conn.cursor()
        # Count existing before batch
        cursor.execute("SELECT COUNT(*) FROM temp_leads WHERE job_id = ?", (job_id,))
        count_before = cursor.fetchone()[0]

        cursor.executemany(
            """
            INSERT INTO temp_leads (job_id, place_id, lead_json) VALUES (?, ?, ?)
            ON CONFLICT(job_id, place_id) DO UPDATE SET lead_json = excluded.lead_json
            """,
            records,
        )

        cursor.execute("SELECT COUNT(*) FROM temp_leads WHERE job_id = ?", (job_id,))
        count_after = cursor.fetchone()[0]

        new_inserted = count_after - count_before
        cursor.execute("UPDATE active_jobs SET leads_count = ? WHERE job_id = ?", (count_after, job_id))
        conn.commit()

        return new_inserted


async def save_temp_leads_batch(job_id: str, leads: List[Union[LeadItem, Dict[str, Any]]]) -> int:
    """
    Async: Saves a batch of leads to temp_leads table.
    Returns the number of newly added leads.
    """
    if not leads:
        return 0

    records = []
    for lead in leads:
        if isinstance(lead, LeadItem):
            pid = lead.place_id
            lead_json = lead.model_dump_json()
        elif isinstance(lead, dict):
            pid = lead.get("place_id", "")
            lead_json = json.dumps(lead, ensure_ascii=False)
        else:
            continue
        if pid:
            records.append((job_id, pid, lead_json))

    if not records:
        return 0

    async with aiosqlite.connect(str(TEMP_DB_PATH)) as db:
        async with db.execute("SELECT COUNT(*) FROM temp_leads WHERE job_id = ?", (job_id,)) as c:
            row = await c.fetchone()
            count_before = row[0] if row else 0

        await db.executemany(
            """
            INSERT INTO temp_leads (job_id, place_id, lead_json) VALUES (?, ?, ?)
            ON CONFLICT(job_id, place_id) DO UPDATE SET lead_json = excluded.lead_json
            """,
            records,
        )

        async with db.execute("SELECT COUNT(*) FROM temp_leads WHERE job_id = ?", (job_id,)) as c:
            row = await c.fetchone()
            count_after = row[0] if row else 0

        new_inserted = count_after - count_before
        await db.execute("UPDATE active_jobs SET leads_count = ? WHERE job_id = ?", (count_after, job_id))
        await db.commit()

        return new_inserted


def get_temp_leads_sync(job_id: str) -> List[LeadItem]:
    """Retrieves all LeadItem objects for a job synchronously."""
    with get_sync_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT lead_json FROM temp_leads WHERE job_id = ? ORDER BY id ASC", (job_id,))
        rows = cursor.fetchall()
        leads: List[LeadItem] = []
        for row in rows:
            try:
                leads.append(LeadItem.model_validate_json(row["lead_json"]))
            except Exception:
                continue
        return leads


async def get_temp_leads(job_id: str) -> List[LeadItem]:
    """Async: Retrieves all LeadItem objects for a job."""
    async with aiosqlite.connect(str(TEMP_DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT lead_json FROM temp_leads WHERE job_id = ? ORDER BY id ASC", (job_id,)) as cursor:
            rows = await cursor.fetchall()
            leads: List[LeadItem] = []
            for row in rows:
                try:
                    leads.append(LeadItem.model_validate_json(row["lead_json"]))
                except Exception:
                    continue
            return leads


def get_temp_leads_count_sync(job_id: str) -> int:
    """Returns the total number of leads stored in temp buffer for a job."""
    with get_sync_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM temp_leads WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        return row[0] if row else 0


async def get_temp_leads_count(job_id: str) -> int:
    """Async: Returns the total number of leads stored in temp buffer for a job."""
    async with aiosqlite.connect(str(TEMP_DB_PATH)) as db:
        async with db.execute("SELECT COUNT(*) FROM temp_leads WHERE job_id = ?", (job_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


# ============================================================================
# Housekeeping & TTL Cleanup (Old Anonymous Sessions)
# ============================================================================

def cleanup_old_temp_data_sync(hours: int = 24) -> int:
    """
    Deletes anonymous jobs and their associated temp leads older than the given hours.
    Preserves verified user records if any were linked.
    """
    threshold = (datetime.datetime.utcnow() - datetime.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    with get_sync_connection() as conn:
        cursor = conn.cursor()
        # Find old anonymous job ids
        cursor.execute(
            """
            SELECT job_id FROM active_jobs
            WHERE is_authenticated = 0 AND created_at < ?
            """,
            (threshold,),
        )
        old_jobs = [row[0] for row in cursor.fetchall()]
        if not old_jobs:
            return 0

        placeholders = ",".join("?" for _ in old_jobs)
        cursor.execute(f"DELETE FROM temp_leads WHERE job_id IN ({placeholders})", old_jobs)
        cursor.execute(f"DELETE FROM active_jobs WHERE job_id IN ({placeholders})", old_jobs)
        conn.commit()
        return len(old_jobs)


# Ensure tables and migrations exist on load
try:
    init_db_sync()
except Exception:
    pass
