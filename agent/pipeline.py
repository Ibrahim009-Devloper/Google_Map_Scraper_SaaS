"""
Master Orchestration Pipeline for Google Maps Lead Generation Agent.
Coordinates planning, geo-split scraping, global deduplication, filtering,
conditional website enrichment, and export to JSON & CSV.
"""

import os
import sys
import csv
import json
import time
import datetime
import re
from typing import List, Dict, Any, Optional, Callable

# Ensure Windows stdout never crashes on international characters
if sys.platform.startswith("win"):
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def safe_print(*args, **kwargs):
    """Safely prints to stdout without raising UnicodeEncodeError on Windows."""
    try:
        print(*args, **kwargs)
    except Exception:
        try:
            sanitized = [str(a).encode("ascii", errors="replace").decode("ascii") for a in args]
            print(*sanitized, **kwargs)
        except Exception:
            pass

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
    add_job_log_sync,
    save_temp_leads_batch_sync,
    delete_temp_lead_sync,
    increment_anonymous_quota_sync,
    get_anonymous_quota_sync,
)


def is_lead_category_relevant(lead_category: Optional[str], target_keywords: List[str], user_prompt: Optional[str] = None) -> bool:
    """
    Checks if a lead's business category is relevant to the target search keywords.
    Prevents irrelevant Google Maps results (e.g. gas stations, banks when searching for dentists/plumbers).
    """
    if not lead_category or not lead_category.strip():
        return True
    if not target_keywords:
        return True

    from backend.seo_audit.analyzer import matches_category_synonyms

    target_terms = list(target_keywords)
    if user_prompt:
        target_terms.append(user_prompt)

    cat_low = lead_category.strip().lower()
    for kw in target_terms:
        kw_low = kw.strip().lower()
        if matches_category_synonyms(kw_low, cat_low) or matches_category_synonyms(cat_low, kw_low):
            return True
        if kw_low in cat_low or cat_low in kw_low:
            return True

    return False


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

    # 3. Rating Filter (Minimum & Maximum)
    has_rating_filter = (filters.min_rating > 0.0) or (filters.max_rating is not None)
    if has_rating_filter:
        if lead.rating is None:
            return False
        if filters.min_rating > 0.0 and lead.rating < filters.min_rating:
            return False
        if filters.max_rating is not None and lead.rating > filters.max_rating:
            return False

    # 4. Reviews Filter (Minimum & Maximum)
    if filters.min_reviews > 0:
        if lead.reviews_count < filters.min_reviews:
            return False
    if filters.max_reviews is not None:
        if lead.reviews_count > filters.max_reviews:
            return False

    # 5. Category Relevancy Filter (Filter out irrelevant business categories)
    if plan.keywords and lead.category:
        if not is_lead_category_relevant(lead.category, plan.keywords, plan.user_prompt):
            return False

    return True


def export_leads_to_json(leads: List[LeadItem], filepath: str) -> None:
    """Exports leads list to formatted JSON file iteratively without RAM bloat."""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("[\n")
        total = len(leads)
        for i, lead in enumerate(leads):
            lead_json = json.dumps(lead.model_dump(), ensure_ascii=False)
            if i < total - 1:
                f.write(f"  {lead_json},\n")
            else:
                f.write(f"  {lead_json}\n")
        f.write("]\n")


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

    has_seo = any(bool(getattr(lead, "seo_report", None)) for lead in leads)
    if has_seo:
        fieldnames.extend(["seo_health_score", "lead_pitch_priority", "icebreaker_hook"])

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for lead in leads:
            row = {
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
            }
            if has_seo:
                seo_rep = getattr(lead, "seo_report", None)
                if isinstance(seo_rep, dict):
                    h_score = seo_rep.get("seo_health_score")
                    row["seo_health_score"] = f"{h_score}/100" if h_score is not None else "N/A"
                    row["lead_pitch_priority"] = seo_rep.get("lead_pitch_priority", "")
                    row["icebreaker_hook"] = seo_rep.get("icebreaker_hook", "")
                elif hasattr(seo_rep, "seo_health_score"):
                    h_score = seo_rep.seo_health_score
                    row["seo_health_score"] = f"{h_score}/100" if h_score is not None else "N/A"
                    row["lead_pitch_priority"] = getattr(seo_rep, "lead_pitch_priority", "")
                    row["icebreaker_hook"] = getattr(seo_rep, "icebreaker_hook", "")
                else:
                    row["seo_health_score"] = "N/A"
                    row["lead_pitch_priority"] = ""
                    row["icebreaker_hook"] = ""
            writer.writerow(row)


def normalize_phone_key(phone: Optional[str]) -> Optional[str]:
    """Extracts normalized digit key for phone deduplication."""
    if not phone:
        return None
    digits = re.sub(r'\D', '', str(phone))
    if len(digits) < 7:
        return None
    return digits[-10:] if len(digits) >= 10 else digits


def normalize_email_key(email: Optional[str]) -> Optional[str]:
    """Extracts normalized lower-case email key for deduplication."""
    if not email:
        return None
    e = str(email).strip().lower()
    return e if "@" in e else None


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

    if stop_event is None:
        import threading
        stop_event = threading.Event()

    if not plan.sub_locations or len(plan.sub_locations) == 0:
        from agent.planner import get_default_sub_locations
        plan.sub_locations = get_default_sub_locations(plan.country_code or "bd")

    # Target limit & Anonymous user quota enforcement
    effective_limit = max_leads_limit
    if plan.target_leads and plan.target_leads > 0:
        if effective_limit is None or plan.target_leads < effective_limit:
            effective_limit = plan.target_leads

    if not is_authenticated:
        if effective_limit is None or effective_limit > ANONYMOUS_LEAD_LIMIT:
            effective_limit = ANONYMOUS_LEAD_LIMIT

    # For large target goals, ensure full 6-page scrolling (120 leads/query) and multi-location expansion
    if effective_limit and effective_limit > 100:
        plan.filters.max_pages_per_search = 6
        from agent.planner import expand_sub_locations_for_target
        plan.sub_locations = expand_sub_locations_for_target(
            base_sub_locations=plan.sub_locations,
            target_leads=effective_limit,
            keywords=plan.keywords,
            country_code=plan.country_code or "bd",
        )

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
                update_job_sync(job_id, status="limit_reached", current_area=f"{ANONYMOUS_LEAD_LIMIT:,} Lead Quota Reached. Login required.")
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
    seen_root_domains: set = set()
    phone_to_lead_idx: Dict[str, int] = {}
    email_to_lead_idx: Dict[str, int] = {}
    job_status = "running"
    start_time = time.time()

    def pipeline_log(msg: str, level: str = "INFO") -> None:
        print(msg, flush=True)
        if job_id:
            try:
                add_job_log_sync(job_id, msg, level=level)
            except Exception:
                pass

    total_tasks = len(plan.sub_locations) * len(plan.keywords)
    completed_tasks = 0

    pipeline_log(f"[Pipeline] Starting scrape for {len(plan.sub_locations)} sub-locations and {len(plan.keywords)} keywords ({total_tasks} total searches). Target: {effective_limit or 'Unlimited'} leads.", "INFO")

    pending_db_leads: List[LeadItem] = []

    def flush_pending_db_leads() -> None:
        nonlocal pending_db_leads
        if not pending_db_leads or not job_id:
            return
        batch_to_save = pending_db_leads
        pending_db_leads = []
        save_temp_leads_batch_sync(job_id, batch_to_save)
        update_job_sync(job_id, leads_count=len(filtered_leads))
        if session_owner and not is_authenticated:
            increment_anonymous_quota_sync(session_owner, len(batch_to_save))

    # Helper: Clean, filter, commit in batches to SQLite, and stream live to user
    def save_and_stream_lead(lead: LeadItem) -> bool:
        nonlocal filtered_leads, job_status

        if stop_event and stop_event.is_set():
            job_status = "stopped"
            flush_pending_db_leads()
            return False

        # Strictly enforce target leads limit
        if effective_limit and len(filtered_leads) >= effective_limit:
            if plan.target_leads and len(filtered_leads) >= plan.target_leads and effective_limit == plan.target_leads:
                job_status = "completed"
            else:
                job_status = "limit_reached"
            flush_pending_db_leads()
            if stop_event and hasattr(stop_event, "set"):
                stop_event.set()
            return False

        # Professional formatting and cleaning pass on lead
        cleaned_lead = clean_lead_item(lead, country_code=plan.country_code)

        # Must Have Email Filter: If enabled, skip leads without verified emails
        if plan.filters.must_have_email:
            if not cleaned_lead.emails:
                print(f"    -> [Filter Skip: No Email] '{cleaned_lead.name}' has no verified public email. Continuing search...", flush=True)
                return False

        # Multi-Key Deduplication: normalized phone and email checks
        p_key = normalize_phone_key(cleaned_lead.phone)
        e_keys = [normalize_email_key(em) for em in cleaned_lead.emails if normalize_email_key(em)]

        matched_idx = None
        dup_field = ""

        if p_key and p_key in phone_to_lead_idx:
            matched_idx = phone_to_lead_idx[p_key]
            dup_field = f"phone '{cleaned_lead.phone}'"
        elif e_keys:
            for ek in e_keys:
                if ek in email_to_lead_idx:
                    matched_idx = email_to_lead_idx[ek]
                    dup_field = f"email '{ek}'"
                    break

        if matched_idx is not None and matched_idx < len(filtered_leads):
            existing_lead = filtered_leads[matched_idx]
            existing_reviews = existing_lead.reviews_count or 0
            new_reviews = cleaned_lead.reviews_count or 0

            if new_reviews > existing_reviews:
                # Upgraded listing with higher review count replaces earlier lower-review duplicate
                print(
                    f"    -> [Deduplication Upgrade] Replacing '{existing_lead.name}' ({existing_reviews} reviews) with "
                    f"'{cleaned_lead.name}' ({new_reviews} reviews) sharing {dup_field}.",
                    flush=True
                )
                if job_id and existing_lead.place_id != cleaned_lead.place_id:
                    try:
                        delete_temp_lead_sync(job_id, existing_lead.place_id)
                    except Exception:
                        pass

                # Clear old mappings
                old_p = normalize_phone_key(existing_lead.phone)
                if old_p and old_p in phone_to_lead_idx:
                    del phone_to_lead_idx[old_p]
                for old_e in existing_lead.emails:
                    old_ek = normalize_email_key(old_e)
                    if old_ek and old_ek in email_to_lead_idx:
                        del email_to_lead_idx[old_ek]

                # Update in filtered_leads
                filtered_leads[matched_idx] = cleaned_lead

                # Register new mappings
                if p_key:
                    phone_to_lead_idx[p_key] = matched_idx
                for ek in e_keys:
                    email_to_lead_idx[ek] = matched_idx

                if job_id:
                    pending_db_leads.append(cleaned_lead)
                    flush_pending_db_leads()
                    if on_batch:
                        try:
                            on_batch(job_id, [cleaned_lead])
                        except Exception as cb_err:
                            print(f"[Warning] on_batch callback error: {cb_err}")
                return True
            else:
                # Existing listing has equal or more reviews: skip duplicate to protect outreach
                print(
                    f"    -> [Filter Skip: Duplicate Contact] '{cleaned_lead.name}' ({new_reviews} reviews) shares {dup_field} "
                    f"with existing lead '{existing_lead.name}' ({existing_reviews} reviews). Skipping.",
                    flush=True
                )
                return False

        # If not a duplicate, add to qualified list
        target_idx = len(filtered_leads)
        filtered_leads.append(cleaned_lead)
        if p_key:
            phone_to_lead_idx[p_key] = target_idx
        for ek in e_keys:
            email_to_lead_idx[ek] = target_idx

        # Instant real-time streaming: flush each lead immediately to SQLite so the UI displays it without delay
        if job_id:
            pending_db_leads.append(cleaned_lead)
            flush_pending_db_leads()

            if on_batch:
                try:
                    on_batch(job_id, [cleaned_lead])
                except Exception as cb_err:
                    print(f"[Warning] on_batch callback error: {cb_err}")

        email_str = f" | Email: {cleaned_lead.emails[0]}" if cleaned_lead.emails else ""
        safe_print(f"    [+1 Lead Harvested] #{len(filtered_leads)} '{cleaned_lead.name}' ({cleaned_lead.website_status}){email_str}", flush=True)

        # Check quota limit or user requested target
        if effective_limit and len(filtered_leads) >= effective_limit:
            flush_pending_db_leads()
            if plan.target_leads and len(filtered_leads) >= plan.target_leads and effective_limit == plan.target_leads:
                print(f"[Target] Achieved requested target ({len(filtered_leads)}/{plan.target_leads} leads). Stopping dynamic loop.", flush=True)
                job_status = "completed"
            else:
                print(f"[Quota] Reached lead limit ({len(filtered_leads)}/{effective_limit}). Stopping early.", flush=True)
                job_status = "limit_reached"
            if stop_event and hasattr(stop_event, "set"):
                stop_event.set()
            return False

        return True

    # Page callback for real-time saving, filtering, and quota tracking
    def handle_page_leads(new_raw_leads: List[LeadItem]):
        nonlocal all_raw_leads, filtered_leads, job_status

        if stop_event and stop_event.is_set():
            job_status = "stopped"
            return

        if effective_limit and len(filtered_leads) >= effective_limit:
            return

        batch_candidates: List[LeadItem] = []
        for lead in new_raw_leads:
            if lead.place_id not in seen_place_ids:
                seen_place_ids.add(lead.place_id)

                # Pre-filter by phone if listing already exists with equal or more reviews
                p_key = normalize_phone_key(lead.phone)
                if p_key and p_key in phone_to_lead_idx:
                    existing_lead = filtered_leads[phone_to_lead_idx[p_key]]
                    if (lead.reviews_count or 0) <= (existing_lead.reviews_count or 0):
                        continue

                # Domain Deduplication: If lead has own website, check if domain was already seen
                if lead.website_status == "Has Own Website" and lead.website_url:
                    from backend.seo_audit.auditor import extract_root_domain
                    root_dom = extract_root_domain(lead.website_url)
                    if root_dom:
                        if root_dom in seen_root_domains:
                            # Skip duplicate practitioner or duplicate business on same root domain
                            continue
                        seen_root_domains.add(root_dom)

                all_raw_leads.append(lead)
                if filter_lead(lead, plan):
                    batch_candidates.append(lead)

        if not batch_candidates:
            return

        # 1. IMMEDIATE WEBSITE DEEP SCRAPING (1-by-1 real-time streaming)
        if plan.enrichment.enabled and any(l.website_status == "Has Own Website" and l.website_url for l in batch_candidates):
            enrichable = [l for l in batch_candidates if l.website_status == "Has Own Website" and l.website_url]
            non_enrichable = [l for l in batch_candidates if l.website_status != "Has Own Website" or not l.website_url]

            # Stream non-website leads immediately if verified email is not required
            for lead in non_enrichable:
                if stop_event and stop_event.is_set():
                    break
                save_and_stream_lead(lead)

            # Deep scrape company websites with concurrent streaming callback
            if enrichable and not (stop_event and stop_event.is_set()):
                print(f"    -> [Website Scraper] Deep scraping {len(enrichable)} websites for verified emails & contact info...", flush=True)
                if job_id:
                    update_job_sync(job_id, current_area=f"Deep scraping {len(enrichable)} websites for emails & contact info...")

                # Determine dataset's default_search_city (mode of non-empty addresses) or from search sub-location
                from collections import Counter
                city_counts = Counter()
                for l in all_raw_leads:
                    if l.address:
                        m = re.search(r',\s*([A-Za-z\s\.]+),\s*[A-Z]{2}\s*\d{5}', l.address)
                        if m:
                            c = m.group(1).strip().strip(".,")
                            if c and len(c) > 1:
                                city_counts[c] += 1
                batch_default_city = city_counts.most_common(1)[0][0] if city_counts else None
                if not batch_default_city and plan.sub_locations:
                    for sl in plan.sub_locations:
                        parts = [p.strip() for p in sl.area_name.split(",")]
                        if len(parts) >= 2 and parts[-1]:
                            batch_default_city = parts[-1]
                            break
                        elif parts[0]:
                            batch_default_city = parts[0]
                            break

                enrich_leads_concurrently(
                    enrichable,
                    country_code=plan.country_code,
                    extract_email_opt=plan.enrichment.extract_emails,
                    extract_social_opt=plan.enrichment.extract_socials,
                    detect_cms_opt=plan.enrichment.detect_cms,
                    audit_seo_opt=bool(getattr(plan.enrichment, "audit_seo", False)),
                    max_pages_per_site=1,
                    stop_event=stop_event,
                    on_lead_completed=save_and_stream_lead,
                    default_target_city=batch_default_city,
                )
        else:
            # Google Maps only: Stream every lead 1-by-1 immediately
            for lead in batch_candidates:
                if stop_event and stop_event.is_set():
                    break
                save_and_stream_lead(lead)

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

    # Dynamic Geo-Expansion Loop: If target leads not yet reached and more leads needed,
    # expand search grid dynamically to neighboring sectors to satisfy user's goal
    expansion_round = 1
    while (
        effective_limit
        and len(filtered_leads) < effective_limit
        and not (stop_event and stop_event.is_set())
        and job_status == "running"
        and expansion_round <= 5
    ):
        from agent.planner import expand_sub_locations_for_target
        current_count = len(plan.sub_locations)
        expanded_locs = expand_sub_locations_for_target(
            base_sub_locations=plan.sub_locations,
            target_leads=int(effective_limit * (1 + 0.5 * expansion_round)),
            keywords=plan.keywords,
            country_code=plan.country_code or "bd",
            min_additional_locations=6 * expansion_round,
        )
        new_locs = expanded_locs[current_count:]
        if not new_locs:
            break

        print(f"\n[Dynamic Expansion] Expanding search grid with {len(new_locs)} additional micro-zones to reach target ({len(filtered_leads)}/{effective_limit} leads)...", flush=True)
        plan.sub_locations.extend(new_locs)
        total_tasks = len(plan.sub_locations) * len(plan.keywords)

        for sub_loc in new_locs:
            if (stop_event and stop_event.is_set()) or job_status in ("limit_reached", "completed"):
                break
            for keyword in plan.keywords:
                if (stop_event and stop_event.is_set()) or job_status in ("limit_reached", "completed"):
                    break

                completed_tasks += 1
                search_desc = f"'{keyword}' in {sub_loc.area_name}"
                print(f"[{completed_tasks}/{total_tasks}] (Expansion) Scraping {search_desc}...", flush=True)

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

                if on_progress:
                    try:
                        on_progress(completed_tasks, total_tasks, search_desc, len(filtered_leads))
                    except Exception as prog_err:
                        print(f"[Warning] on_progress callback error: {prog_err}")

        expansion_round += 1

    # Determine status if not stopped/limit_reached
    if job_status == "running":
        job_status = "completed"

    elapsed_duration = round(time.time() - start_time, 1)
    pipeline_log(f"[Deduplication & Filtering] {len(filtered_leads)}/{len(all_raw_leads)} unique leads qualified and enriched. Status: {job_status}. Runtime: {elapsed_duration}s", "SUCCESS" if job_status == "completed" else "INFO")

    # Trim to exact target requested if batch delivered extra
    if plan.target_leads and len(filtered_leads) > plan.target_leads:
        filtered_leads = filtered_leads[:plan.target_leads]

    # Flush any remaining leads from the buffer to SQLite
    if job_id:
        flush_pending_db_leads()

    # Update final state in temp_store
    if job_id:
        update_job_sync(
            job_id,
            status=job_status,
            current_area="Done" if job_status == "completed" else job_status.capitalize(),
            leads_count=len(filtered_leads),
            duration_seconds=elapsed_duration,
        )

    # Step 3: Supabase Cloud Sync (Logged-in verified users only)
    if is_authenticated and session_owner and session_owner.startswith("usr_") and filtered_leads:
        try:
            from backend.supabase_db import save_leads_to_supabase
            pipeline_log(f"[Supabase] Syncing {len(filtered_leads)} leads to cloud for verified user {session_owner}...", "INFO")
            save_leads_to_supabase(user_uid=session_owner, job_id=job_id or "job_direct", leads=filtered_leads)
            pipeline_log("[Supabase] Cloud sync completed successfully.", "SUCCESS")
        except Exception as sb_err:
            pipeline_log(f"[Warning] Supabase auto-sync error: {sb_err}", "WARN")

    # Step 4: Export to JSON & CSV (if requested)
    json_path = None
    csv_path = None
    if export_files:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = str(LEADS_DIR / f"leads_{timestamp}.json")
        csv_path = str(LEADS_DIR / f"leads_{timestamp}.csv")
        xlsx_path = str(LEADS_DIR / f"leads_{timestamp}.xlsx")

        export_leads_to_json(filtered_leads, json_path)
        export_leads_to_csv(filtered_leads, csv_path)

        try:
            from backend.excel_exporter import generate_leads_excel
            from backend.seo_audit.xlsx_appender import append_seo_columns_to_excel
            excel_bytes = generate_leads_excel(filtered_leads, title="Verified Leads", include_enrichment=plan.enrichment.enabled)
            has_seo = any(bool(getattr(l, "seo_report", None)) for l in filtered_leads)
            if has_seo or getattr(plan.enrichment, "audit_seo", False):
                seo_reports = {}
                for l in filtered_leads:
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
                excel_bytes = append_seo_columns_to_excel(excel_bytes, seo_reports)
            with open(xlsx_path, "wb") as xf:
                xf.write(excel_bytes)
        except Exception as xerr:
            print(f"[Warning] XLSX export failed: {xerr}")

        pipeline_log(f"[Export] Results saved to JSON ({json_path}), CSV ({csv_path}), and XLSX ({xlsx_path})", "INFO")

    return {
        "job_id": job_id,
        "status": job_status,
        "duration_seconds": elapsed_duration,
        "total_raw": len(all_raw_leads),
        "total_filtered": len(filtered_leads),
        "json_path": json_path,
        "csv_path": csv_path,
        "xlsx_path": xlsx_path if export_files else None,
        "leads": filtered_leads,
    }
