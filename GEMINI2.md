# GEMINI.md — Agency-Ready AI Google Maps Scraper & Local SEO Audit Platform

This file is the authoritative engineering, architecture, and product specification for developing and maintaining this repository. Every code change, prompt, schema update, and feature implementation MUST strictly follow the constraints, guardrails, and phased roadmap defined below.

---

## 1. Product Vision & Target Market

- **Core Mission:** Evolve the existing Autonomous Google Maps Lead Generation & Local SEO Engine into a production-grade, **AI-powered, White-Label Local SEO Audit Platform** built specifically for **SEO Agencies** (initial target market).
- **Core Workflow (Automatic Analysis + Customizable Report):**
  1. Agency enters a target niche and location to scrape local businesses.
  2. The scraper collects business data, contacts, website HTML, and automatically runs available SEO checks and local competitor discovery.
  3. All raw data and audit findings are persisted in **Supabase** (with timestamps and source metadata) so agencies do not re-scrape the same business repeatedly.
  4. In the **Audit Builder UI**, the agency selects/deselects which audit sections to include (e.g., Website Technical SEO, Competitor Research, PageSpeed & Mobile, Tracking/Ads, GBP, etc.).
  5. The AI Audit Engine generates a strictly evidence-backed, client-ready report using **only** the selected sections and verified findings.
  6. The agency exports a **White-Label Branded PDF** (or shareable report link) featuring their own logo, agency details, brand colors, and preferred template.

---

## 2. Hard Infrastructure & Hosting Constraints (Non-Negotiable)

All engineering decisions MUST respect these deployment realities:

1. **Hosted on Render (Low RAM, Ephemeral Disk, Single Worker):**
   - **NO Headless Browsers:** Never introduce Playwright, Selenium, Puppeteer, or Chromium into the scraping, SEO audit, or PDF generation pipelines.
   - **HTTP-Only Scraping:** Keep Google Maps (`tbm=map`) and website fetching strictly HTTP/HTML-based via `curl_cffi` (Chrome TLS/JA3 impersonation).
   - **Lightweight PDF Rendering:** For white-label PDF generation, use lightweight Python libraries (**WeasyPrint** or **ReportLab**) instead of headless Chrome.
   - **Single Uvicorn Worker:** Run `uvicorn backend.main:app --workers 1` so in-memory SSE streams and local SQLite buffers remain consistent.
   - **Persistence:** Local SQLite WAL (`data/temp_cache.db`) is strictly a temporary running-job buffer (Render disk is ephemeral). All agency accounts, branding settings, saved leads, competitor snapshots, and generated audits MUST persist in **Supabase**.
2. **No Rotating/Paid Proxies (Current Phase):**
   - Do NOT add paid proxy pool dependencies yet.
   - Protect the single Render server IP using:
     - Randomized request jitter (`0.8s–2.0s`) between Google Maps pagination offsets.
     - Exponential backoff (max 3 retries) on HTTP `429` / `503`.
     - Bounded concurrency (`MAX_WORKERS = 6`, configurable via env var) for website enrichment and SEO auditing to prevent Render OOM crashes and burst rate-limiting.
     - Serialized SQLite WAL writes with `timeout=30.0` and `PRAGMA busy_timeout=30000`.
     - Tightened anonymous free quota (`50–100 leads / 24h per IP`, configurable via env var) to prevent API/bandwidth abuse.

---

## 3. Non-Negotiable Product & Data Integrity Guardrails

Every module—especially `analyzer.py`, `scorer.py`, `icebreaker.py`, and the AI Audit Generator—MUST obey these rules:

1. **Zero Fabrication / Evidence-Only AI:** AI-generated opening lines and audit reports MUST ONLY reference verified issues present in the structured audit JSON. Never invent missing issues, scores, competitor stats, or business claims.
2. **Explicit Honesty on Unchecked or Unreadable Data:** Any metric that failed to fetch, requires an unconfigured third-party API, or could not be parsed MUST be explicitly labeled `Could Not Read`, `Unavailable`, or `Not Checked`—never marked as `Pass`, `0`, or `Failed`.
3. **0 Word Count ≠ Thin Content:** If a site loads content via client-side JavaScript (CSR/SPA), `curl_cffi` receives an empty HTML shell. Never label JS-rendered shells as `Thin Content` or `No H1`, and never penalize their SEO score.
4. **Shared Contacts ≠ Fraud/Duplicates:** When multiple Google Business Profiles share the same phone number or email, flag them as `Shared Contact (Review)`—never automatically label them as "duplicate businesses" or "front companies."
5. **Email Verification Transparency:** Always distinguish email type (`Business Domain` vs. `Free Provider`) and explicitly define what verification checked (e.g., `Valid (Syntax + MX)` vs. `Mailbox Verified` vs. `Risky` vs. `Invalid`). Never claim guaranteed inbox deliverability from syntax/MX checks alone.
6. **Audit Provenance:** Every audit record MUST store `audited_url`, `audited_page_type` (`homepage` or `landing_page`), `audit_timestamp`, and `data_source` for every metric.

---

## 4. Repository Architecture & Module Responsibilities

| Path | Responsibility |
| --- | --- |
| `agent/planner.py` | LLM geo-planner: preserves exact user niche/category and splits large cities into micro-zones (`lat`, `lon`, `radius`). |
| `agent/gmaps_client.py` | Reverse Protobuf (`tbm=map`) client using `curl_cffi`, jittered pagination, and exponential backoff. |
| `agent/gmaps_parser.py` | Double-encoded JSON unwrapper with defensive index checks and schema-drift warnings. |
| `agent/web_enricher.py` | Multi-threaded HTTP contact/social/CMS/tracking extractor and email classifier. |
| `agent/cleaner.py` | Business name sanitizer (for outreach copy), phone formatter, and social URL query-string stripper. |
| `agent/pipeline.py` | Master orchestrator: `place_id` deduplication, shared-contact flagging, batch caching, and Supabase sync. |
| `backend/seo_audit/config.py` | Single source of truth for all SEO thresholds, scoring weights, stopwords, and feature flags. |
| `backend/seo_audit/fetcher.py` | Homepage canonicalizer, redirect-following HTTP/HTTPS prober, robots/sitemap validator, and JS-shell detector. |
| `backend/seo_audit/analyzer.py` | Technical/On-Page/Local SEO checks, tracking/ads detector, and lightweight inner-page scanner. |
| `backend/seo_audit/pagespeed.py` | Google PageSpeed Insights API client (Mobile/Desktop scores, Core Web Vitals, mobile-friendliness, screenshot URL). |
| `backend/seo_audit/competitor.py` | Local Top-3 competitor discovery and structured gap comparison engine. |
| `backend/seo_audit/scorer.py` | Numeric `0–100` SEO score calculator and structured `Pass / Warning / Critical / Could Not Read` status mapper. |
| `backend/seo_audit/icebreaker.py` | Strictly evidence-branched outreach hook generator with clean business naming and grammar rules. |
| `backend/seo_audit/ai_report.py` | Customizable section-based AI audit generator (strictly grounded in selected verified sections). |
| `backend/seo_audit/pdf_exporter.py` | White-label agency-branded PDF report generator (WeasyPrint / ReportLab) with logo, colors, and template support. |
| `backend/excel_exporter.py` & `xlsx_appender.py` | Agency-friendly sortable/filterable Excel exporter with numeric scores and split `Status` + `Details` columns. |
| `backend/temp_store.py` & `supabase_db.py` | SQLite WAL job buffer (with lock/busy_timeout) and Supabase persistent store for agencies, audits, and branding. |

---

## 5. Phased Implementation Roadmap

### Phase 1 — Data Accuracy & Bug Fixes (Mandatory First Milestone)

Fix all 7 client-reported bugs from sample QA plus all technical audit bugs before adding new features:

1. **AI Opening Line / Audit Consistency (`icebreaker.py`):**
   - Strictly branch NAP outreach hooks by exact missing field:
     - `phone_missing_only` → mention missing GBP phone on website (NEVER mention street address).
     - `address_missing_only` → mention missing street address.
     - `both_missing` → mention both phone and address.
   - Add a high-priority branch for `Critical: Canonical Points to Different Domain`.
   - If numeric `seo_score >= 90` and zero Critical/High issues exist, do NOT fabricate "several high-ROI technical optimizations"; output `"Healthy site — skip technical pitch or use a competitor/GBP angle."`
   - Sanitize business names for copy: strip keyword-stuffed text after `:` or `|`, strip legal suffixes (`Inc.`, `LLC`, `Corp`), and fix English possessives (`Contractors'` instead of `Contractors's`).

2. **JS-Rendered / 0-Word False Positive Fix (`fetcher.py`, `analyzer.py`, `scorer.py`):**
   - Detect CSR/SPA shells without a browser: if `visible_word_count < 30` AND HTML contains SPA/JS indicators (`<div id="root">`, `<div id="app">`, `<div id="__next">`, `<noscript>` JS warnings, or script-heavy empty body), mark `render_status = "Could Not Read (JS-Rendered)"`.
   - Skip Thin Content, Missing H1, and Missing NAP penalties for JS-rendered sites; set `seo_score = None` (displayed as `N/A — Could Not Read`), `pitch_priority = "Manual Review"`, and suppress false on-page icebreakers.

3. **Homepage Canonicalization vs. Subpage Audit (`fetcher.py`, `analyzer.py`):**
   - When Google Maps provides a subpage URL (e.g., `/contact`, `/los-angeles`, `/service-areas/...`), resolve and audit the root domain homepage (`scheme://netloc/`) first while preserving the original GBP URL.
   - If the root homepage is unreachable and a subpage is audited instead, explicitly set `audited_page_type = "landing_page"` and display `audited_url` in both Excel and AI reports—never mislabel a `/contact` page as `"homepage"`.

4. **Remove Permanently Blank Columns (`excel_exporter.py`):**
   - Remove the `Price Range` column from exports unless a verified, populated data source is available. Do not export 100% empty columns.

5. **Shared Contact Flagging (`pipeline.py`):**
   - Keep `place_id` as the unique listing deduplication key.
   - Add a `Shared Contact Flag` column (`Yes — Shared Email/Phone` vs. `No`) whenever multiple listings share the same normalized email or phone number, so agencies can review before outreach without falsely labeling businesses as fraudulent duplicates.

6. **Sortable & Filterable Excel Format (`excel_exporter.py`, `xlsx_appender.py`):**
   - Store `SEO Health Score` as a pure numeric integer (`0–100`) or blank (`N/A` if unreadable)—NEVER as a `"73/100"` string.
   - Split key audit checks into two clean columns: `<Check> Status` (strict enum: `Pass`, `Warning`, `Critical`, `Could Not Read`, `Not Checked`) and `<Check> Details` (human-readable diagnostic text).

7. **Email Classification & Honest Verification (`web_enricher.py`, `cleaner.py`):**
   - Add `Email Type` (`Business Domain` vs. `Free Provider` for Gmail/Yahoo/Outlook/Live/Verizon/etc.).
   - Add `Email Verification Status` (`Valid (Syntax + MX)`, `Risky`, `Invalid`, `Unverified`) using DNS MX record validation (plus optional third-party mailbox verification API if configured). Document verification scope clearly.

8. **Core Technical Audit & Data Hygiene Fixes:**
   - **HTTP/SSL Accuracy:** Fetch with `allow_redirects=True`. If GBP URL is `http://` and stays `http://`, explicitly probe `https://<host>` to distinguish `Warning: HTTPS Works, Missing 301 Redirect` from `Critical: No Valid SSL`.
   - **Threshold Alignment (`config.py`):** Single constant for TTFB (`Warning > 2.0s`, `High > 4.0s`; do not mark Critical Pitch solely on single-region TTFB) and Meta Description (`Optimal: 120–160 chars`, `< 120` Too Short, `> 160` Truncated).
   - **Title & Category Alignment:** Flag raw-URL titles (`www.`, `.com`) and generic titles (`Home - ...`) as `High Issue`. In `GBP Category Alignment`, ignore generic stopwords (`contractor`, `company`, `services`, `inc`, `group`) and require core niche stems (e.g., `roof`).
   - **City Matching & State Leak:** Accept either neighborhood/sub-city (`Flushing`, `Canoga Park`) OR parent metro/borough (`Queens`, `NYC`, `Los Angeles`, `LA`). Never carry over `target_city` from a previous search zone when `Full Address` is blank (`Not Checked (No GBP Address)`).
   - **Social URL Sanitizer:** Strip all tracking/redirect junk (`&ved=`, `&usg=`, `?igsh=`, `?igshid=`, `?mibextid=`, `?utm_*`, `?ref=`, `?next=`, `?viewAsMember=`) and repair malformed paths.
   - **CMS Detection & Parser Resilience:** Expand CMS fingerprints (Webflow, Framer, GoDaddy, Duda, Weebly, Next.js, Shopify, Elementor/Divi). Add defensive fallback parsing for `is_unclaimed` in `gmaps_parser.py` and log schema-drift warnings when 100% of a batch returns null/default for a field.

---

### Phase 2 — High-Impact Render-Safe SEO & Competitor Features

Implement these using HTTP-only methods and free/low-cost APIs (no headless browser required):

1. **Competitor Research Engine (`backend/seo_audit/competitor.py` — Key Agency Feature):**
   - For each target business, identify up to **Top 3 local competitors** in the same category and geographic area (from the scraped zone pool or targeted `tbm=map` query).
   - Compare verified metrics side-by-side: Rating, Review Count, Website SEO Score, PageSpeed Mobile Score, Schema/NAP/Tracking presence, and key gaps.
   - Clearly display evidence of where the target business trails competitors. Any uncollected competitor metric MUST show `Unavailable`.
2. **Real PageSpeed & Mobile Check (`backend/seo_audit/pagespeed.py`):**
   - Integrate **Google PageSpeed Insights API** (free tier with API key) over HTTP to fetch:
     - Mobile & Desktop Performance Scores (`0–100`).
     - Core Web Vitals (`LCP`, `CLS`, `INP` / `FCP`).
     - Mobile-friendliness signals and Lighthouse mobile viewport screenshot thumbnail (no Playwright needed).
3. **Ads & Tracking Detection (`analyzer.py`):**
   - Detect marketing/analytics scripts in homepage HTML: Google Analytics (`GA4`/`gtag`), Google Tag Manager (`GTM-`), Google Ads (`AW-`), Meta Pixel (`fbq`), and Microsoft Clarity/Hotjar.
4. **Inner Pages & Content Freshness Scan (`analyzer.py`):**
   - Parse `sitemap.xml` and primary navigation links (capped at 5–10 lightweight checks per domain) to detect: Service Pages, Location Pages, Blog presence, and latest `lastmod` date.

---

### Phase 3 — Pluggable Provider-Backed Advanced SEO Modules

Build clean, modular provider interfaces in `backend/seo_audit/providers/` that remain disabled (`Not Checked — Provider Not Configured`) until API keys and client budget are confirmed:

- **Map Pack Ranking:** Exact local pack position (`1–20`) for primary keyword + city (e.g., DataForSEO / SerpApi).
- **Backlinks & Authority:** Domain Authority/Rating, Referring Domains, Estimated Organic Traffic (e.g., DataForSEO / Moz / Ahrefs API).
- **Keyword Visibility:** Ranked keyword count and top ranking keywords (e.g., DataForSEO / SEMrush API).
- **Local Citations:** NAP consistency checks across Yelp, Bing Places, BBB, Apple Maps, and Yell.
- **Extended GBP Signals:** Photo count, posts, opening hours, business description, review reply rate, and latest review date (strictly separating public scraped data from owner-authorized GBP API data).
- **Lead Qualification:** Domain age (RDAP/WHOIS), multi-location count, and estimated business size signals.

---

### Phase 4 — Customizable Audit Builder, Grounded AI Audit & White-Label PDF

1. **Audit Section Selection (`frontend/` + `backend/seo_audit/routes.py`):**
   - Provide selectable checkboxes per audit section:
     - `website_technical_seo`
     - `onpage_local_seo`
     - `competitor_research`
     - `pagespeed_mobile`
     - `ads_tracking`
     - `inner_pages`
     - `gbp_insights` (when available)
     - `authority_keywords_citations` (when provider enabled)
   - Store full analysis results in Supabase so agencies can toggle sections and regenerate reports without re-scraping.
   - Only selected sections appear in the final AI audit and PDF. Uncollected sections are never shown as completed.
2. **Grounded AI SEO Audit Generator (`backend/seo_audit/ai_report.py`):**
   - Input: Strict JSON payload containing only selected sections and verified findings.
   - Required Report Structure:
     1. Business Overview (Name, Category, Website, Audited URL, Location, Audit Date).
     2. Overall Numeric SEO Score & Audit Scope.
     3. Agency Executive Summary (client-ready language).
     4. Critical Issues, Warnings, and Passed Checks (separated cleanly).
     5. Plain-English Explanations & Practical Recommendations mapped 1-to-1 to verified findings.
     6. Prioritized Action Plan (Quick Wins vs. Medium-Term vs. Long-Term).
     7. Competitor Gap Summary (when selected).
     8. Data Limitations & Unchecked Metrics (explicitly listing any `Could Not Read`, `Unavailable`, or `Not Checked` items).
3. **White-Label Branding & PDF Export (`backend/seo_audit/pdf_exporter.py`):**
   - Agency brand profile stored in Supabase: Agency Logo upload, Agency Name, Contact Info/Website, Primary/Accent Brand Colors, and Preferred Report Template.
   - One-click export to **Branded PDF** (rendered via WeasyPrint or ReportLab on Render) plus optional shareable read-only report link.

---

### Phase 5 — Email Outreach Module (Scoped & Compliant)

- **Phase 5A (Default Built-In Scope):**
  - Exportable verified lead lists with `Email Type`, `Email Verification Status`, `Shared Contact Flag`, and evidence-backed **AI Personalized Cold Email Drafts** + follow-up draft templates.
- **Phase 5B (Optional — Gated on Client Confirmation):**
  - Automated sending, follow-up sequences, and reply tracking ONLY if explicitly confirmed by Ajay, and strictly compliant with CAN-SPAM, GDPR, opt-out handling, and sending-domain warm-up/rate limits.

---

## 6. Automated Testing & QA Standards (`tests/`)

Every pull request or feature update MUST pass `python -m pytest tests/` and maintain tests covering:

1. **Evidence-Hook Alignment:** `Address Found, Phone Missing` never mentions missing street address; `score >= 90` never outputs fake optimization claims; cross-domain canonical triggers high-priority warning.
2. **JS-Rendered Shell Detection:** 0-word SPA shell returns `Could Not Read (JS-Rendered)` and `seo_score = None` (never `7/100` or `Thin Content`).
3. **Homepage vs. Subpage Normalization:** `/contact` GBP URL resolves to root domain or explicitly flags `landing_page`.
4. **HTTP/HTTPS Probing:** `http://` URLs with working `https://` return `Warning (Missing 301 Redirect)`, not `Critical (No SSL)`.
5. **Excel Schema & Sortability:** Numeric integer score (`0–100`), split `Status` + `Details` columns, no `Price Range` blank column, and `Shared Contact Flag` populated on matching email/phone.
6. **Email & Social Hygiene:** `Business Domain` vs. `Free Provider` classification, MX check handling, social URL tracking-parameter stripping (`&ved=`, `?igsh=`, `?viewAsMember=`), and possessive grammar (`Contractors'` vs. `Contractors's`).
7. **Customizable Report Guardrails:** Unselected sections are excluded from AI prompts and PDFs; `Not Checked` / `Unavailable` fields are never misrepresented as passed or zero.
8. **Render Safety:** Zero imports of `playwright`, `selenium`, or `puppeteer`; bounded concurrency and SQLite lock handling verified.
