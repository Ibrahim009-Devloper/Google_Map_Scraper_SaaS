# 🗺️ Autonomous AI Google Maps Lead Generation & Local SEO Engine

> **High-Performance B2B Lead Scraping & Agency-Grade Technical SEO Audit Platform**  
> *Zero-Browser Reverse Protobuf API • Multi-Threaded Website Deep Enricher • 14-Point Local SEO Auditor • Real-Time SSE Streamer • 42-Column Executive Excel Exporter*

---

## 📌 Executive Summary

This system is a modern, fully autonomous B2B lead generation and Local SEO audit platform.

**Its fundamental differences from ordinary scrapers:**
1. **Zero Browser Automation:** It does **not** use Selenium, Playwright, or Puppeteer. Without a browser, it sends requests directly to Google Maps' internal Protocol Buffer (`tbm=map`) endpoint using `curl_cffi` (Chrome 124 TLS/JA3 fingerprint) and scrapes hundreds of leads per second.
2. **AI Geo-Planner:** Google Maps returns a maximum of 120 results per search. When given a large city (e.g., "Dhaka", "Miami", "Dallas"), the AI automatically splits the city into 5 to 20 smaller sub-zones (micro-locations), finds the latitude (`lat`) and longitude (`lon`) of each zone's center, and runs searches for each.
3. **Website Intelligence & Contact Enrichment:** Using multi-threading (`ThreadPoolExecutor`), it extracts emails, social media links (Facebook, Instagram, LinkedIn, WhatsApp), and the CMS used (WordPress, Wix, Shopify) from business websites.
4. **Agency-Grade Local SEO Audit:** It audits each website's speed (TTFB), SSL, Robots.txt, XML Sitemap, Title, H1, Schema.org Markup, and NAP Consistency, produces an **SEO Health Score (0-100)**, and writes a personalized **AI Icebreaker Hook** for cold emails.
5. **Real-time Live Streaming:** Using a FastAPI backend and Server-Sent Events (SSE), it streams live counters and data to the screen the moment each lead is found.

---

## 🏛️ System Architecture & Data Flow

```mermaid
flowchart TD
    User([User Prompt: 'Roofing contractors in Little Rock 50 leads']) --> WebUI[Tailwind & Vanilla JS Web UI]
    WebUI -->|HTTP POST /api/scrape/start| FastAPI[FastAPI Backend Engine]
    
    subgraph AI Planning Phase
        FastAPI -->|Extract Intent & Geo-zones| Planner[agent/planner.py: LLM Geo-Planner]
        Planner -->|Generate Strict JSON| ActionPlan[ActionPlan Pydantic Object]
    end

    subgraph Google Maps Scraping Phase
        ActionPlan --> Client[agent/gmaps_client.py: Reverse API Client]
        Client -->|Encode lat, lon, offset into pb| GMapsProtobuf[Google Maps tbm=map Endpoint]
        GMapsProtobuf -->|Double-encoded Array Response| Parser[agent/gmaps_parser.py: Array Unwrapper]
        Parser -->|Clean & Deduplicate Place IDs| RawLeads[Unique Raw Leads]
    end

    subgraph Website Enrichment & SEO Audit Phase
        RawLeads --> Enricher[agent/web_enricher.py: Concurrent Enricher]
        Enricher -->|Chrome124 + TLS Fallback| BizSites[Business Websites]
        BizSites -->|Extract Emails & Socials| ContactData[Verified Contact Data]
        BizSites -->|14 SEO Signals & TTFB| SEOEngine[backend/seo_audit/: Local SEO Engine]
        SEOEngine -->|Score 0-100 & Pitch Angle| SEOMetrics[SEO Report & Cold Icebreaker Hook]
    end

    subgraph Storage & Real-Time Delivery
        ContactData & SEOMetrics --> Buffer[(Local SQLite WAL Cache: temp_cache.db)]
        Buffer -->|SSE Stream 1-by-1| WebUI
        Buffer -->|Sync Verified Users| Supabase[(Supabase Cloud Database)]
        Buffer --> Exporter[backend/excel_exporter.py & xlsx_appender.py]
        Exporter --> XLSX[42-Column Executive Excel Spreadsheet]
    end
```

---

## 🔄 Step-by-Step Workflow

### Step 1: AI Prompt Analysis & Geo-Planning (`agent/planner.py`)
- The user gives a prompt in plain language, e.g. *"Wealth Management Firms in Little Rock, Arkansas 100 lead"*.
- **Category Preservation:** The scraper keeps the exact category the user asked for intact (it does not add irrelevant synonyms and degrade lead quality).
- **Geo-Splitting:** To bypass Google Maps' 120 limit, it divides the entire city into 5 to 20 sub-zones based on zip codes or neighborhoods, sets the correct coordinates (`lat`, `lon`, `radius`) for each, and creates an `ActionPlan`.

### Step 2: Reverse Protocol Buffer Request (`agent/gmaps_client.py`)
- Requests are made directly to Google's internal endpoint without any heavy web browser:
  ```python
  # pb parameter builder (lon=longitude first, lat=latitude second)
  pb = f"!4m8!1m3!1d{radius}!2d{lon}!3d{lat}!3m2!1i1024!2i768!4f13.1!7i20!8i{offset}!10b1!12m8!1m1!18b1!2m3!5m1!6e2!20e3!10b1!16b1"
  ```
- By running an offset loop (`offset = 0, 20, 40, 60, 80, 100`), all leads in each area are collected without scrolling.
- `curl_cffi` is used to send requests, exactly mimicking the Chrome browser's TLS JA3 fingerprint, so Google does not block or show a CAPTCHA.

### Step 3: Double-Encoded JSON Parsing (`agent/gmaps_parser.py`)
- Google Maps sends a security prefix `)]}'` and double-encoded nested arrays in its response.
- The parser cleans the prefix and extracts data from verified correct indexes using the safe navigation function `safe_get()`:
  - `b_data = item[14]`
  - **`place_id`**: `b_data[78]` (the global key for removing duplicates)
  - **`name`**: `b_data[11]`
  - **`categories`**: `b_data[13]`
  - **`address`**: `b_data[39]`
  - **`phone`**: `b_data[178][0][1][1][0]`
  - **`rating` & `reviews`**: `b_data[4][7]` and `b_data[4][8]`
  - **`website`**: `b_data[7][0]`
  - **`is_unclaimed`**: `b_data[57][1] == "Claim this business"` (unclaimed goldmine lead)

### Step 4: Website Deep Scraping & Data Enrichment (`agent/web_enricher.py`)
- Business website status is classified into 3 categories:
  1. `No Website` (those without a website)
  2. `Social Link Only` (those with only a Facebook or Instagram page on Google Maps)
  3. `Has Own Website` (those with a real website)
- For those with a website, the homepage is fetched in a multi-threaded engine.
- **Cloudflare XOR Decoder & Anti-Obfuscation:** Emails hidden in code or text like `info [at] company [dot] com` are converted into real emails.
- **Email Hygiene:** Image files (`logo@2x.png`), web design agency footer emails, and dummy emails are filtered out, strictly selecting **1 best authentic domain email**.
- Social media handles and CMS platforms (WordPress, Shopify, Wix, Squarespace) are detected.

### Step 5: Local SEO Audit Engine (`backend/seo_audit/`)
In the same single fetch cycle, 14 senior technical audits are completed on the website:
1. **HTTP Status & Final URL:** Redirect chain and response code.
2. **SSL Security:** Whether the site runs on secure `HTTPS`.
3. **Honest Speed (TTFB):** The server's first byte response time (in seconds).
4. **Meta Robots:** Whether Google indexing is accidentally disabled with a `noindex` tag.
5. **Canonical Tag:** Whether there is a canonical duplicate content issue.
6. **Robots.txt & XML Sitemap:** Whether the sitemap is properly communicated to Google.
7. **Title & Meta Description:** SEO-friendly meta data optimization.
8. **Primary H1 Tag:** Whether there is a single H1 tag.
9. **Image Alt Text:** Image SEO gap detection.
10. **Target City & Category Alignment:** Whether the main keyword and city name are in the Title/H1.
11. **Schema.org JSON-LD:** LocalBusiness schema markup check.
12. **NAP Consistency:** Whether the website's name, address, and phone number match Google Maps.
13. **SEO Health Score (0-100):** Overall score.
14. **Dynamic Cold Outreach Hook:** Custom icebreaker hook generation for emailing the client.

### Step 6: Dual-Storage Buffer & Live Stream (`backend/temp_store.py`)
- As the scraper runs, each batch of data is saved to a local SQLite WAL database (`data/temp_cache.db`).
- Even if the user presses the **"Stop"** button midway or refreshes the browser, no data collected so far is lost.
- If the user is logged in, leads are automatically synced to their Supabase account in the background.

---

## 📂 Project Directory Structure

```text
Google_Map_Scraper_SaaS_Project/
├── agent/                         # Core AI Scraper & Reverse API Engine
│   ├── schemas.py                 # Pydantic data models (ActionPlan, LeadItem, SubLocation)
│   ├── planner.py                 # LLM integration and multi-location action planner
│   ├── gmaps_client.py            # Protobuf pb builder, offset pagination and tbm=map client
│   ├── gmaps_parser.py            # Double-encoded JSON cleaner and precise index parser
│   ├── web_enricher.py            # Multi-threaded website scraper (email, social, CMS)
│   ├── cleaner.py                 # Phone number formatter, name and address sanitizer
│   └── pipeline.py                # Master orchestrator (deduplication, filtering and batch sync)
│
├── backend/                       # FastAPI Server, Databases & SEO Auditor
│   ├── main.py                    # API routes, CORS, rate limiter and SSE live streamer
│   ├── security.py                # Google OAuth2 JWT verifier and fake-email blocker
│   ├── temp_store.py              # Local SQLite (WAL Mode) temp buffer (zero data loss)
│   ├── supabase_db.py             # Supabase cloud database handler (for logged-in users)
│   ├── excel_exporter.py          # Main 21-column leads Excel generator
│   └── seo_audit/                 # Professional Local SEO audit engine
│       ├── config.py              # SEO weights, scoring rules and TLD whitelist
│       ├── models.py              # SEOReport, AuditInput, AuditIssue Pydantic models
│       ├── fetcher.py             # Chrome TLS fetcher and Robots.txt / XML Sitemap validator
│       ├── analyzer.py            # 14 SEO signal checker (Schema, NAP, H1, Meta, City)
│       ├── scorer.py              # Health Score (0-100) and Lead Pitch Priority calculator
│       ├── icebreaker.py          # Dynamic outreach hook generator for cold emails
│       ├── auditor.py             # Domain cache deduplicator and concurrency orchestrator
│       ├── routes.py              # On-demand /api/seo-audit and /api/seo-audit/bulk endpoints
│       └── xlsx_appender.py       # Styler that appends 21 SEO columns to the Excel file
│
├── frontend/                      # SaaS Web User Interface
│   ├── index.html                 # Dashboard, terminal drawer, modal and live feed UI
│   ├── js/app.js                  # SSE client, on-demand audit modal and real-time controller
│   └── css/                       # Styling and custom theme configuration
│
├── tests/                         # Automated test suite (44 tests)
│   ├── test_seo_audit.py          # SEO signal and fallback tests
│   ├── test_seo_pipeline_integration.py # Full end-to-end pipeline integration test
│   └── ...                        # Quota, security, filtering and cleanup tests
│
├── config.py                      # Global environment configuration and timeouts
├── main.py                        # CLI runner to run the scraper from the terminal
└── requirements.txt               # List of all project dependencies
```

---

## 📊 Complete 42-Column Executive Excel Specification

When the scraped data is downloaded in XLSX format, it creates the following 42 organized columns:

| # | Column Name | Data Source | Description |
|---|---|---|---|
| **1-7** | Business Name, Category, Phone Number, Emails, Website Status, Website URL, Rating | Google Maps + Enricher | Core business identity and verified domain emails |
| **8-12** | Reviews Count, Price Range, Unclaimed Business, Neighborhood, Full Address | Google Maps | Review count, local area and unclaimed status |
| **13-17** | Facebook, Instagram, LinkedIn, WhatsApp, CMS / Tech | Website Enricher | Social media profile links and the site's CMS |
| **18-21** | Latitude, Longitude, Google Maps Link, Place ID | Google Maps | Geo-coordinates and unique deduplication ID |
| **22-26** | Final URL & HTTP Status, SSL & HTTPS Redirect, Server Response (TTFB), Indexability (Meta Robots), Canonical Tag Status | Technical SEO Audit | Site's HTTP code, security, speed and indexability |
| **27-31** | Robots.txt & XML Sitemap, Extracted Title Text, Title Tag Status, Meta Description Status, Extracted Primary H1 | Technical SEO Audit | Sitemap validation and meta tag optimization |
| **32-35** | H1 Tag Status, Homepage Word Count, Image Alt Text Gap, Local Keyword Status | On-Page SEO Audit | Content quality and local keyword alignment |
| **36-39** | Schema Status, NAP Status, Google Maps Embed, GBP Category Alignment | Local SEO Audit | LocalBusiness schema and name-address-phone match |
| **40-42** | **SEO Health Score**, **Lead Pitch Priority**, **AI / Dynamic Icebreaker Hook** | SEO Engine & AI | Site score out of 100, pitch priority and cold email hook |

---

## 🚀 How to Run Locally

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure the environment file
Rename the `.env.example` file to `.env` and enter your API keys:
```env
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_anon_key
JWT_SECRET=your_secret_key
```

### 3. Start the web server (Web UI & API)
```bash
uvicorn main:app --reload --port 8000
```
Open it in your browser: `http://localhost:8000`

### 4. To scrape in terminal CLI mode
```bash
python main.py --prompt "Roofing contractors in Little Rock, Arkansas 50 leads" --yes
```

### 5. To run the test suite
```bash
python -m pytest tests/
```

---

## 🛡️ Security & Anti-Bot Philosophy
- **Zero Browser Fingerprint Discrepancy:** There are no headless browser flags, so Cloudflare or bots are not suspected.
- **Non-blocking Cancellation:** When the user presses stop while the scraper is running, background threads are released within milliseconds.
- **IP Quota & Temp Buffer:** Anonymous users have a quota of a maximum of 1,000 free leads per 24 hours, stored in the local buffer.
