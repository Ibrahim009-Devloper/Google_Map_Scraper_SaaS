# Graph Report - Google_Map_Scraper_SaaS_Project  (2026-10-21)

## Corpus Check
- Corpus is ~39,105 words - fits in a single context window. You may not need a graph.

## Summary
- 536 nodes · 1230 edges · 39 communities (28 shown, 11 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 26 edges (avg confidence: 0.93)
- Token cost: 1,250 input · 380 output

## Community Hubs (Navigation)
- Frontend Application State
- AI Planner and Query Decomposition
- Website Contact and Email Enricher
- Security and OAuth Token Verification
- SQLite Synchronous Temp Store
- Pipeline Data Models and Schemas
- Supabase Cloud Database Client
- SQLite Async Storage Engine
- FastAPI Core Application Routes
- User Jobs and Payment Ledgers
- Client Health and Quota Sync
- Scraper Pipeline Orchestration
- Lead Formatting and Address Cleaner
- Scrape Job Lifecycle and Payments
- Google Maps Reverse API Client
- Google Maps Protocol Buffer Parser
- CLI Terminal Runner and Banners
- Authentication and Profile Modals
- Admin Overview and Cloud Sync
- Excel XLSX Exporter
- Frontend Feed Filtering and Formatting
- Admin Quota and Plan Management
- Usage Limits and Quota Enforcement
- Scraping Job Concurrency Manager
- Problem Center and Feedback Service
- Server Sent Events Live Stream
- Global Project Configuration
- Admin Dashboard and Audit View
- Custom Quotas and Role Management
- Interactive Community Feedback Widget
- Platform Jobs Audit Service
- User Reviews Administration
- User Directory Administration
- Frontend Dashboard and Modals UI
- Supabase User Authentication
- FastAPI Lifecycle and SQLite Init
- Payment Webhook Processing
- Deployment and System Dependencies

## God Nodes (most connected - your core abstractions)
1. `get_supabase_client()` - 43 edges
2. `LeadItem` - 37 edges
3. `run_pipeline()` - 30 edges
4. `showToast()` - 21 edges
5. `start_scraping_job()` - 19 edges
6. `get_sync_connection()` - 19 edges
7. `generate_plan()` - 16 edges
8. `SocialLinks` - 16 edges
9. `save_temp_leads_batch_sync()` - 16 edges
10. `ActionPlan` - 15 edges

## Surprising Connections (you probably didn't know these)
- `_run_scraper_task()` --indirect_call--> `run_pipeline()`  [INFERRED]
  backend/main.py → agent/pipeline.py
- `generate_leads_excel()` --uses--> `LeadItem`  [INFERRED]
  backend/excel_exporter.py → agent/schemas.py
- `lead_item_to_supabase_record()` --uses--> `LeadItem`  [INFERRED]
  backend/supabase_db.py → agent/schemas.py
- `save_leads_to_supabase()` --uses--> `LeadItem`  [INFERRED]
  backend/supabase_db.py → agent/schemas.py
- `get_temp_leads()` --uses--> `LeadItem`  [INFERRED]
  backend/temp_store.py → agent/schemas.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Frontend Modals and Interactive Feed Flow** — frontend_index_html_leads_dashboard, frontend_index_html_leads_feed, frontend_index_html_admin_quota_modal, frontend_index_html_problem_center_modal [INFERRED 0.85]

## Communities (39 total, 11 thin omitted)

### Community 0 - "Frontend Application State"
Cohesion: 0.04
Nodes (40): accuracyBar, activeHubName, allLeads, authBtn, authBtnLabel, authModal, batchProgressBar, charBudgetCounter (+32 more)

### Community 1 - "AI Planner and Query Decomposition"
Cohesion: 0.09
Nodes (20): clean_email_list(), clean_json_response(), create_offline_fallback_plan(), detect_and_preserve_core_keyword(), expand_sub_locations_for_target(), extract_target_count(), generate_plan(), get_comprehensive_country_hubs() (+12 more)

### Community 2 - "Website Contact and Email Enricher"
Cohesion: 0.09
Nodes (15): clean_phone_number(), clean_website_url(), decode_cloudflare_email(), deobfuscate_text(), detect_cms(), discover_target_pages(), enrich_single_lead(), extract_domain() (+7 more)

### Community 3 - "Security and OAuth Token Verification"
Cohesion: 0.12
Nodes (9): generate_user_uid(), get_client_identifier(), get_current_user_optional(), get_current_user_required(), is_disposable_email(), require_admin_user(), verify_auth_token(), cleanup_test_records() (+1 more)

### Community 4 - "SQLite Synchronous Temp Store"
Cohesion: 0.12
Nodes (12): cleanup_old_temp_data_sync(), get_anonymous_quota_sync(), get_sync_connection(), get_temp_leads_count_sync(), get_temp_leads_sync(), increment_anonymous_quota_sync(), init_db(), init_db_sync() (+4 more)

### Community 5 - "Pipeline Data Models and Schemas"
Cohesion: 0.14
Nodes (11): flush_pending_db_leads(), SocialLinks, create_job_sync(), get_job_sync(), save_temp_leads_batch(), save_temp_leads_batch_sync(), update_job_sync(), test_job_and_temp_leads() (+3 more)

### Community 6 - "Supabase Cloud Database Client"
Cohesion: 0.15
Nodes (9): create_job_record(), ensure_verified_user(), get_user_saved_leads(), lead_item_to_supabase_record(), record_payment(), record_usage(), save_leads_to_supabase(), sync_temp_session_to_supabase() (+1 more)

### Community 7 - "SQLite Async Storage Engine"
Cohesion: 0.11
Nodes (9): create_job(), get_anonymous_quota(), get_anonymous_usage(), get_temp_leads(), get_temp_leads_count(), increment_anonymous_quota(), record_anonymous_job_start(), reset_anonymous_quota() (+1 more)

### Community 8 - "FastAPI Core Application Routes"
Cohesion: 0.12
Nodes (4): get_auth_config(), register_new_user(), RegisterRequest, serve_frontend()

### Community 9 - "User Jobs and Payment Ledgers"
Cohesion: 0.13
Nodes (8): delete_admin_review_item(), get_admin_all_payments(), get_my_jobs_history(), delete_admin_review(), get_admin_payments(), get_supabase_client(), get_user_jobs(), update_job_record()

### Community 10 - "Client Health and Quota Sync"
Cohesion: 0.21
Nodes (17): appendTerminalLog(), checkServerHealth(), copyAllLeads(), downloadExport(), fetchCurrentQuota(), handleGoogleSignIn(), initSSEStream(), refreshStatus() (+9 more)

### Community 11 - "Scraper Pipeline Orchestration"
Cohesion: 0.17
Nodes (8): export_leads_to_csv(), export_leads_to_json(), filter_lead(), run_pipeline(), handle_page_leads(), save_and_stream_lead(), LeadItem, enrich_leads_concurrently()

### Community 12 - "Lead Formatting and Address Cleaner"
Cohesion: 0.21
Nodes (3): clean_address(), clean_business_name(), clean_lead_item()

### Community 13 - "Scrape Job Lifecycle and Payments"
Cohesion: 0.17
Nodes (6): create_payment_intent(), reset_dev_quota(), ReviewSubmitRequest, start_scraping_job(), _run_scraper_task(), submit_product_review()

### Community 14 - "Google Maps Reverse API Client"
Cohesion: 0.21
Nodes (4): build_pb_parameter(), build_search_url(), fetch_all_pages_for_location(), fetch_single_page()

### Community 15 - "Google Maps Protocol Buffer Parser"
Cohesion: 0.22
Nodes (5): classify_website(), parse_gmaps_leads(), parse_single_business(), safe_get(), unwrap_gmaps_json()

### Community 16 - "CLI Terminal Runner and Banners"
Cohesion: 0.22
Nodes (4): display_plan_summary_human(), display_results_summary(), display_welcome_banner(), main()

### Community 17 - "Authentication and Profile Modals"
Cohesion: 0.26
Nodes (13): clearAuthInputs(), closeAuthModal(), fetchUserProfile(), handleAuthButtonClick(), handleEmailSignIn(), handleEmailSignUp(), initSupabaseClient(), loadUserJobHistory() (+5 more)

### Community 18 - "Admin Overview and Cloud Sync"
Cohesion: 0.17
Nodes (6): get_admin_overview_metrics(), get_my_saved_leads(), health_check(), get_admin_overview(), is_supabase_connected(), test_supabase_connection()

### Community 20 - "Frontend Feed Filtering and Formatting"
Cohesion: 0.18
Nodes (11): applyFeedFilter(), cleanDomain(), clearFeed(), getFilteredLeads(), getInitialColor(), getInitials(), loadMoreFeedLeads(), openLeadModal() (+3 more)

### Community 21 - "Admin Quota and Plan Management"
Cohesion: 0.20
Nodes (6): admin_update_user_plan_or_role(), AdminUserUpdateRequest, CheckoutIntentRequest, ScrapeStartRequest, sync_anonymous_session(), SyncSessionRequest

### Community 22 - "Usage Limits and Quota Enforcement"
Cohesion: 0.24
Nodes (5): get_client_quota(), get_my_dashboard_profile(), check_user_limits(), get_daily_usage(), get_user_profile()

### Community 24 - "Problem Center and Feedback Service"
Cohesion: 0.29
Nodes (4): list_recent_reviews(), create_product_review(), get_product_reviews(), test_product_reviews()

### Community 25 - "Server Sent Events Live Stream"
Cohesion: 0.29
Nodes (3): stop_scraping_job(), stream_scraping_events(), get_job()

### Community 27 - "Admin Dashboard and Audit View"
Cohesion: 0.38
Nodes (7): deleteAdminReview(), escapeHtml(), loadAdminJobs(), loadAdminPayments(), loadAdminReviews(), openAdminDashboardModal(), switchAdminTab()

### Community 28 - "Custom Quotas and Role Management"
Cohesion: 0.40
Nodes (6): changeUserPlan(), changeUserRole(), closeCustomQuotaModal(), handleSaveCustomQuota(), loadAdminUsers(), resetUserCustomQuota()

### Community 29 - "Interactive Community Feedback Widget"
Cohesion: 0.33
Nodes (5): handleProblemReportSubmit(), initStarRatingSelector(), loadLiveProblemFeed(), openProblemCenterModal(), scrollToFeedback()

### Community 33 - "Frontend Dashboard and Modals UI"
Cohesion: 0.50
Nodes (4): Admin Custom Quota Modal, Leads Harvester Web Dashboard, Live Stream Leads Feed UI, Problem Center & Community Review Modal

## Knowledge Gaps
- **45 isolated node(s):** `allLeads`, `leadPlaceIdMap`, `scraperPrompt`, `charBudgetCounter`, `samplePromptsDropdown` (+40 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 255 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **11 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `LeadItem` connect `Scraper Pipeline Orchestration` to `AI Planner and Query Decomposition`, `Website Contact and Email Enricher`, `Security and OAuth Token Verification`, `SQLite Synchronous Temp Store`, `Pipeline Data Models and Schemas`, `Supabase Cloud Database Client`, `SQLite Async Storage Engine`, `FastAPI Core Application Routes`, `Lead Formatting and Address Cleaner`, `Google Maps Reverse API Client`, `Google Maps Protocol Buffer Parser`, `Excel XLSX Exporter`?**
  _High betweenness centrality (0.088) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `LeadItem` (e.g. with `clean_lead_item()` and `fetch_all_pages_for_location()`) actually correct?**
  _`LeadItem` has 16 INFERRED edges - model-reasoned connections that need verification._
- **What connects `allLeads`, `leadPlaceIdMap`, `scraperPrompt` to the rest of the system?**
  _45 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Frontend Application State` be split into smaller, more focused modules?**
  _Cohesion score 0.0392156862745098 - nodes in this community are weakly interconnected._
- **Why does `get_supabase_client()` connect `User Jobs and Payment Ledgers` to `User Directory Administration`, `AI Planner and Query Decomposition`, `Supabase User Authentication`, `Security and OAuth Token Verification`, `Payment Webhook Processing`, `Supabase Cloud Database Client`, `FastAPI Core Application Routes`, `Scrape Job Lifecycle and Payments`, `Admin Overview and Cloud Sync`, `Admin Quota and Plan Management`, `Usage Limits and Quota Enforcement`, `Problem Center and Feedback Service`, `Platform Jobs Audit Service`, `User Reviews Administration`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `run_pipeline()` (e.g. with `handle_page_leads()` and `ActionPlan`) actually correct?**
  _`run_pipeline()` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Should `AI Planner and Query Decomposition` be split into smaller, more focused modules?**
  _Cohesion score 0.09393939393939393 - nodes in this community are weakly interconnected._