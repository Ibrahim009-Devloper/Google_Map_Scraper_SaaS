"""
Master Orchestration Pipeline for Google Maps Lead Generation Agent.
Coordinates planning, geo-split scraping, global deduplication, filtering,
conditional website enrichment, and export to JSON & CSV.
"""

import os
import csv
import json
import datetime
from typing import List, Dict, Any, Optional, Callable

from config import LEADS_DIR, ANONYMOUS_LEAD_LIMIT
from agent.schemas import ActionPlan, LeadItem
from agent.cleaner import clean_lead_item
from agent.gmaps_client import fetch_all_pages_for_location
from agent.web_enricher import enrich_leads_concurrently
from backend.temp_store import (
    init_db_sync,
    create_job_sync,
    update_job_sync,
    get_job_sync,
    save_temp_leads_batch_sync,
    increment_anonymous_quota_sync,
    get_anonymous_quota_sync,
)


def filter_lead(lead: LeadItem, plan: ActionPlan) -> bool:
    """
    Applies criteria from plan.filters to a parsed LeadItem.
    Returns True if lead passes all criteria, False otherwise.
    """
    filters = plan.filters

    # 1. Website Requirement Filter
    if filters.website_requirement == "no_website":
        if lead.website_status not in ("No Website", "Social Link Only"):
            return False
    elif filters.website_requirement == "has_real_website":
        if lead.website_status != "Has Own Website":
            return False

    # 2. Phone Requirement Filter
    if filters.must_have_phone:
        if not lead.phone or not str(lead.phone).strip():
            return False

    # 3. Minimum Rating Filter
    if filters.min_rating > 0.0:
        if lead.rating is None or lead.rating < filters.min_rating:
            return False

    # 4. Minimum Reviews Filter
    if filters.min_reviews > 0:
        if lead.reviews_count < filters.min_reviews:
            return False

    return True


def export_leads_to_json(leads: List[LeadItem], filepath: str) -> None:
    """Exports leads list to formatted JSON file."""
    leads_data = [lead.model_dump() for lead in leads]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(leads_data, f, indent=2, ensure_ascii=False)


def export_leads_to_csv(leads: List[LeadItem], filepath: str) -> None:
    """
    Exports leads list to UTF-8-SIG CSV file for direct opening in Excel/Google Sheets.
    Flattens nested social links and emails into clean semicolon/comma separated strings.
    """
    fieldnames = [
        "place_id",
        "name",
        "category",
        "phone",
        "website_status",
        "website_url",
        "facebook",
        "instagram",
        "linkedin",
        "whatsapp",
        "emails",
        "cms_tech",
        "rating",
        "reviews_count",
        "price_range",
        "is_unclaimed_business",
        "neighborhood",
        "address",
        "latitude",
        "longitude",
        "order_link",
        "google_maps_url",
        "source_query",
    ]

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
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


def run_pipeline(
    plan: ActionPlan,
    job_id: Optional[str] = None,
    session_owner: Optional[str] = None,
    is_authenticated: bool = False,
    stop_event: Optional[Any] = None,
    on_progress: Optional[Callable[[int, int, str, int], None]] = None,
    on_batch: Optional[Callable[[str, List[LeadItem]], None]] = None,
    max_leads_limit: Optional[int] = None,
    export_files: bool = True,
) -> Dict[str, Any]:
    """
    Executes end-to-end lead generation pipeline:
    1. Quota verification (1,000 leads for anonymous users)
    2. Local SQLite WAL temp buffer initialization & real-time caching
    3. Geo-split scraping across all keywords and sub-locations
    4. Global deduplication by place_id & live user criteria filtering
    5. Real-time batch callbacks & stop_event responsiveness (zero data loss)
    6. Conditional deep website enrichment
    7. Export to JSON and CSV
    """
    init_db_sync()

    # Target limit & Anonymous user quota enforcement
    effective_limit = max_leads_limit
    if plan.target_leads and plan.target_leads > 0:
        if effective_limit is None or plan.target_leads < effective_limit:
            effective_limit = plan.target_leads

    if not is_authenticated:
        if effective_limit is None or effective_limit > ANONYMOUS_LEAD_LIMIT:
            effective_limit = ANONYMOUS_LEAD_LIMIT

    if session_owner and not is_authenticated:
        existing_scraped = get_anonymous_quota_sync(session_owner)
        if existing_scraped >= ANONYMOUS_LEAD_LIMIT:
            print(f"[Quota] Identifier {session_owner} reached anonymous limit ({existing_scraped}/{ANONYMOUS_LEAD_LIMIT}). Login required.")
            if job_id:
                existing_job = get_job_sync(job_id)
                if not existing_job:
                    create_job_sync(
                        job_id=job_id,
                        session_owner=session_owner,
                        is_authenticated=False,
                        prompt=plan.user_prompt or "",
                    )
                update_job_sync(job_id, status="limit_reached", current_area="1,000 Lead Quota Reached. Login required.")
            return {
                "job_id": job_id,
                "status": "limit_reached",
                "total_raw": 0,
                "total_filtered": 0,
                "json_path": None,
                "csv_path": None,
                "leads": [],
            }

    # Initialize job in SQLite if job_id provided
    if job_id:
        existing_job = get_job_sync(job_id)
        if not existing_job:
            create_job_sync(
                job_id=job_id,
                session_owner=session_owner or f"anon_{job_id[:8]}",
                is_authenticated=is_authenticated,
                prompt=plan.user_prompt or "",
            )
        else:
            update_job_sync(job_id, status="running", current_area="Initializing AI Planner...")

    all_raw_leads: List[LeadItem] = []
    filtered_leads: List[LeadItem] = []
    seen_place_ids: set = set()
    job_status = "running"

    total_tasks = len(plan.sub_locations) * len(plan.keywords)
    completed_tasks = 0

    print(f"\n[Pipeline] Starting scrape for {len(plan.sub_locations)} sub-locations and {len(plan.keywords)} keywords ({total_tasks} total searches)...", flush=True)

    # Page callback for real-time saving and quota tracking
    def handle_page_leads(new_raw_leads: List[LeadItem]):
        nonlocal all_raw_leads, filtered_leads, job_status

        if stop_event and stop_event.is_set():
            job_status = "stopped"
            return

        batch_candidates: List[LeadItem] = []
        for lead in new_raw_leads:
            if lead.place_id not in seen_place_ids:
                seen_place_ids.add(lead.place_id)
                all_raw_leads.append(lead)
                if filter_lead(lead, plan):
                    batch_candidates.append(lead)

        if not batch_candidates:
            return

        # Strictly enforce target leads limit so we do not over-collect
        if effective_limit:
            remaining = effective_limit - len(filtered_leads)
            if remaining <= 0:
                if stop_event and hasattr(stop_event, "set"):
                    stop_event.set()
                return
            if len(batch_candidates) > remaining:
                batch_candidates = batch_candidates[:remaining]

        # 1. IMMEDIATE WEBSITE DEEP SCRAPING (Before saving to DB or streaming to user)
        if plan.enrichment.enabled and any(l.website_status == "Has Own Website" and l.website_url for l in batch_candidates):
            sites_in_batch = sum(1 for l in batch_candidates if l.website_status == "Has Own Website" and l.website_url)
            print(f"    -> [Website Scraper] Deep scraping {sites_in_batch} company websites across 5 pages (/contact, /about)...", flush=True)
            if job_id:
                update_job_sync(job_id, current_area=f"Deep scraping {sites_in_batch} websites for emails & contact info...")

            batch_candidates = enrich_leads_concurrently(
                batch_candidates,
                country_code=plan.country_code,
                extract_email_opt=plan.enrichment.extract_emails,
                extract_social_opt=plan.enrichment.extract_socials,
                detect_cms_opt=plan.enrichment.detect_cms,
                max_pages_per_site=5,
                stop_event=stop_event,
            )

        # 2. Professional formatting and cleaning pass on enriched batch
        batch_candidates = [clean_lead_item(lead, country_code=plan.country_code) for lead in batch_candidates]

        for lead in batch_candidates:
            filtered_leads.append(lead)

        # 3. NOW AND ONLY NOW: Save 100% enriched leads to SQLite & stream to user
        if job_id:
            save_temp_leads_batch_sync(job_id, batch_candidates)
            if session_owner and not is_authenticated:
                increment_anonymous_quota_sync(session_owner, len(batch_candidates))
            if on_batch:
                try:
                    on_batch(job_id, batch_candidates)
                except Exception as cb_err:
                    print(f"[Warning] on_batch callback error: {cb_err}")

        # Check quota limit or user requested target
        if effective_limit and len(filtered_leads) >= effective_limit:
            if plan.target_leads and len(filtered_leads) >= plan.target_leads and effective_limit == plan.target_leads:
                print(f"[Target] Achieved requested target ({len(filtered_leads)}/{plan.target_leads} leads). Stopping dynamic loop.", flush=True)
                job_status = "completed"
            else:
                print(f"[Quota] Reached lead limit ({len(filtered_leads)}/{effective_limit}). Stopping early.", flush=True)
                job_status = "limit_reached"
            if stop_event and hasattr(stop_event, "set"):
                stop_event.set()

    # Step 1: Scrape all locations and keywords
    for sub_loc in plan.sub_locations:
        if stop_event and stop_event.is_set():
            if job_status == "running":
                job_status = "stopped"
            break
        if job_status in ("limit_reached", "completed"):
            break

        for keyword in plan.keywords:
            if stop_event and stop_event.is_set():
                if job_status == "running":
                    job_status = "stopped"
                break
            if job_status in ("limit_reached", "completed"):
                break

            completed_tasks += 1
            search_desc = f"'{keyword}' in {sub_loc.area_name}"
            print(f"[{completed_tasks}/{total_tasks}] Scraping {search_desc}...", flush=True)

            if job_id:
                update_job_sync(job_id, current_area=search_desc, leads_count=len(filtered_leads))

            fetch_all_pages_for_location(
                keyword=keyword,
                area_name=sub_loc.area_name,
                lat=sub_loc.lat,
                lon=sub_loc.lon,
                radius=sub_loc.radius,
                max_pages=plan.filters.max_pages_per_search,
                gl=plan.country_code,
                hl=plan.language,
                stop_event=stop_event,
                on_page_leads=handle_page_leads,
            )

            print(f"    -> Progress: {len(all_raw_leads)} raw discovered, {len(filtered_leads)} qualified fully-enriched leads (Target: {effective_limit or 'Unlimited'})", flush=True)

            if on_progress:
                try:
                    on_progress(completed_tasks, total_tasks, search_desc, len(filtered_leads))
                except Exception as prog_err:
                    print(f"[Warning] on_progress callback error: {prog_err}")

    # Determine status if not stopped/limit_reached
    if job_status == "running":
        job_status = "completed"

    print(f"\n[Deduplication & Filtering] {len(filtered_leads)}/{len(all_raw_leads)} unique leads qualified and enriched. Status: {job_status}", flush=True)

    # Trim to exact target requested if batch delivered extra
    if plan.target_leads and len(filtered_leads) > plan.target_leads:
        filtered_leads = filtered_leads[:plan.target_leads]

    # Update SQLite with final cleaned and enriched fields
    if job_id:
        save_temp_leads_batch_sync(job_id, filtered_leads)

    # Update final state in temp_store
    if job_id:
        update_job_sync(
            job_id,
            status=job_status,
            current_area="Done" if job_status == "completed" else job_status.capitalize(),
            leads_count=len(filtered_leads),
        )

    # Step 3: Supabase Cloud Sync (Logged-in verified users only)
    if is_authenticated and session_owner and session_owner.startswith("usr_") and filtered_leads:
        try:
            from backend.supabase_db import save_leads_to_supabase
            print(f"[Supabase] Syncing {len(filtered_leads)} leads to cloud for verified user {session_owner}...", flush=True)
            save_leads_to_supabase(user_uid=session_owner, job_id=job_id or "job_direct", leads=filtered_leads)
            print("[Supabase] Cloud sync completed successfully.", flush=True)
        except Exception as sb_err:
            print(f"[Warning] Supabase auto-sync error: {sb_err}", flush=True)

    # Step 4: Export to JSON & CSV (if requested)
    json_path = None
    csv_path = None
    if export_files:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = str(LEADS_DIR / f"leads_{timestamp}.json")
        csv_path = str(LEADS_DIR / f"leads_{timestamp}.csv")

        export_leads_to_json(filtered_leads, json_path)
        export_leads_to_csv(filtered_leads, csv_path)

        print(f"\n[Export] Results saved:", flush=True)
        print(f"  - JSON: {json_path}", flush=True)
        print(f"  - CSV:  {csv_path}", flush=True)

    return {
        "job_id": job_id,
        "status": job_status,
        "total_raw": len(all_raw_leads),
        "total_filtered": len(filtered_leads),
        "json_path": json_path,
        "csv_path": csv_path,
        "leads": filtered_leads,
    }
