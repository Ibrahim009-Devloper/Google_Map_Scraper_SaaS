# ⚡ MANDATORY SYSTEM DIRECTIVE: ALWAYS USE SUPERPOWERS (`obra/superpowers`)
> **RULE #0 (ABSOLUTE PRIORITY):** You must ALWAYS use the `superpowers` framework (`obra/superpowers`) for any coding, architectural planning, debugging, and execution tasks. At the start of ANY task or conversation, you MUST invoke and adhere to the relevant `superpowers` skills (`using-superpowers`, `brainstorming`, `writing-plans`, `executing-plans`, `systematic-debugging`, `test-driven-development`, `verification-before-completion`). Jumping directly into writing code without following the structured superpowers workflow is strictly prohibited.

---

# GEMINI.md — Master Blueprint & Full-Stack Specification
**Project Name:** Autonomous AI Google Maps Lead Generation Agent & Secure FastAPI Backend  
**Architecture:** Zero-Browser Reverse API (`tbm=map`) + Multi-Threaded Website Enricher (`curl_cffi` + `BeautifulSoup4`) + LLM Geo-Planner + Secure FastAPI (SSE Live Stream + Local Temp Buffer + Supabase Auth Sync)

---

## 0. CRITICAL RULES FOR ANY AI READING THIS FILE (অন্যান্য AI-এর জন্য কঠোর নির্দেশনা)
তুমি যদি একটি AI কোডিং অ্যাসিস্ট্যান্ট (Cursor, Copilot, Windsurf, Claude, ChatGPT ইত্যাদি) হও, তবে কোড লেখার সময় নিচের নিয়মগুলো **অবশ্যই** মেনে চলবে:
1. **NO BROWSER AUTOMATION:** গুগল ম্যাপস স্ক্র্যাপ করার জন্য কখনোই Selenium, Playwright বা Puppeteer ব্যবহার করবে না। শুধুমাত্র `curl_cffi` (`impersonate="chrome124"`) দিয়ে সরাসরি ইন্টারনাল HTTP GET রিকোয়েস্ট পাঠাবে।
2. **PHASED EXECUTION (NO MONOLITHIC CODE):** এক ধাপে পুরো প্রজেক্টের সব কোড লিখবে না। ইউজার যে **Milestone** করতে বলবে, শুধুমাত্র সেই ফাইলগুলোর কোড লিখবে এবং টেস্ট করার সুযোগ দেবে।
3. **DO NOT GUESS ARRAY INDICES:** গুগল ম্যাপসের `tbm=map` রেসপন্স পার্স করার সময় কখনোই নিজের মনমতো ইনডেক্স বসাবে না। এই ডকুমেন্টের **Section 4.3**-তে দেওয়া ১০০% পরীক্ষিত ইনডেক্স ম্যাপ এবং `safe_get()` ফাংশন ব্যবহার করবে।
4. **DATA STORAGE RULE (ANONYMOUS VS LOGGED-IN):**
   - **Anonymous Users (লগইন ছাড়া):** এদের কোনো লিড স্থায়ীভাবে Supabase ক্লাউডে সেভ করা যাবে না! স্ক্র্যাপিং চলাকালীন ডেটা শুধুমাত্র ব্যাকএন্ডের লোকাল টেম্পোরারি বাফারে (Local SQLite/Memory with TTL) থাকবে যাতে স্ক্র্যাপার স্টপ করলে বা ক্র্যাশ করলে সে তার সেশনের ডেটা ডাউনলোড করতে পারে। তার সর্বোচ্চ ফ্রি লিমিট **১০০০ লিড**।
   - **Logged-in Users (Verified Google OAuth):** শুধুমাত্র যারা অফিশিয়াল Google Account দিয়ে লগইন করবে, তাদের জিমেইল থেকে একটি ক্রিপ্টোগ্রাফিক ইউনিক আইডি (`user_uid`) তৈরি হবে এবং তাদের ডেটা **Supabase**-এ স্থায়ীভাবে সেভ হবে, যাতে তারা ভবিষ্যতে যেকোনো সময় ফিরে এসে ডেটা ফেরত পায়।
5. **ANTI-TEMP MAIL & API SECURITY:** কোনো সাধারণ Email/Password সাইন-আপ রাখা যাবে না। শুধুমাত্র **Google OAuth2 (JWT Token Verification)** ব্যবহার করতে হবে যাতে কেউ Temp Mail (`10minutemail`, `yopmail` ইত্যাদি) ব্যবহার করতে না পারে।

---

## 1. Project Goals & Core Workflow (প্রজেক্টের লক্ষ্য ও কার্যপ্রণালী)

1. **AI Query & Location Analyzer (`agent/planner.py`):**
   - ইউজার সাধারণ ভাষায় প্রম্পট দেবে (যেমন: *"আমাকে ঢাকার এমন কিছু কোম্পানির লিড দাও যাদের ওয়েবসাইট নেই"* অথবা *"গুলশানের রেস্টুরেন্টগুলোর ইমেইল ও ফোন নাম্বার দাও"*)।
   - AI প্রম্পট বিশ্লেষণ করে উপযুক্ত কীওয়ার্ড বাছাই করবে এবং বড় শহরকে ৫ থেকে ২০টি ছোট অঞ্চলে (Micro-locations) ভাগ করে প্রতিটির সঠিক `lat` এবং `lon` বের করবে।
2. **High-Speed Reverse API Scraper (`agent/gmaps_client.py` & `agent/gmaps_parser.py`):**
   - প্রতিটি সাব-লোকেশন ও কীওয়ার্ডের জন্য গুগল ম্যাপসের প্রোটোকল বাফার (`pb`) প্যারামিটার তৈরি করবে।
   - `!8i0`, `!8i20`, `!8i40`, `!8i60`, `!8i80`, `!8i100` (Pagination) ব্যবহার করে প্রতি এলাকা থেকে সর্বোচ্চ ১২০টি করে রেজাল্ট আনবে।
   - `place_id` ব্যবহার করে ডুপ্লিকেট বিজনেস রিমুভ করবে।
3. **Conditional Website Deep Scraper (`agent/web_enricher.py`):**
   - ইউজার যদি শুধু "No Website" লিড চায়, তবে এই মডিউলটি স্কিপ হবে।
   - ইউজার যদি ইমেইল বা সোশ্যাল লিংক চায়, তবে `curl_cffi` + `BeautifulSoup4` দিয়ে মাল্টি-থ্রেডিং (`ThreadPoolExecutor`) ব্যবহার করে ওয়েবসাইটের হোমপেজ ও কনট্যাক্ট পেজ থেকে ইমেইল, সোশ্যাল লিংক এবং CMS বের করবে।
4. **Secure FastAPI Backend & Live Streaming (`backend/`):**
   - ইউজার ইনপুট সরাসরি FastAPI-তে আসবে এবং ব্যাকগ্রাউন্ড টাস্কে স্ক্র্যাপার চালু হবে।
   - **SSE (Server-Sent Events)** এন্ডপয়েন্টের মাধ্যমে প্রতি ব্যাচ স্ক্র্যাপ হওয়ার সাথে সাথে UI-তে লাইভ কাউন্ট ও লাইভ ডেটা স্ট্রিম হবে।
   - স্ক্র্যাপ হওয়ার সাথে সাথে লোকাল টেম্প ডাটাবেসে (SQLite WAL mode) ডেটা ক্যাশ হবে, যাতে ইউজার মাঝপথে **"Stop"** চাপলেও কোনো ডেটা না হারায়।
   - ইউজার যদি Google লগইন করা থাকে, তবেই কেবল ডেটাগুলো Supabase-এ তার ইউনিক আইডির বিপরীতে সিঙ্ক (Sync) হবে।

---

## 2. Complete Directory & File Structure (প্রজেক্টের ফোল্ডার স্ট্রাকচার)

```text
gmaps-ai-lead-agent/
├── GEMINI.md                  # এই মাস্টার ব্লুপ্রিন্ট ফাইল (Single Source of Truth)
├── .env                       # গোপন API Keys (GEMINI_API_KEY, SUPABASE_URL, SUPABASE_KEY, JWT_SECRET)
├── .env.example               # এনভায়রনমেন্ট ভেরিয়েবল টেমপ্লেট
├── requirements.txt           # প্রজেক্টের সব ডিপেন্ডেন্সি লিস্ট
├── config.py                  # গ্লোবাল কনফিগারেশন, রেট লিমিট, টাইমআউট ও কনস্ট্যান্টস
│
├── agent/                     # PART A: CORE AI SCRAPER ENGINE
│   ├── __init__.py
│   ├── schemas.py             # Pydantic Models (ActionPlan, SubLocation, LeadItem, ReviewItem)
│   ├── planner.py             # LLM ইন্টিগ্রেশন ও JSON Action Plan জেনারেটর
│   ├── gmaps_client.py        # pb প্যারামিটার বিল্ডার, প্যাজিনেশন লুপ ও tbm=map রিকোয়েস্টার
│   ├── gmaps_parser.py        # ডাবল-এনকোডেড JSON ক্লিনার ও এক্স্যাক্ট ইনডেক্স পার্সার
│   ├── web_enricher.py        # BS4 + Regex দিয়ে ওয়েবসাইট থেকে ইমেইল ও সোশ্যাল স্ক্র্যাপার
│   └── pipeline.py            # অর্কেস্ট্রেটর (Stop Flag চেক, ডিডুপ্লিকেশন ও ব্যাচ কলব্যাক)
│
├── backend/                   # PART B: SECURE FASTAPI & DATABASE ENGINE
│   ├── __init__.py
│   ├── main.py                # FastAPI App, CORS, Rate Limiter, এবং API Routes
│   ├── security.py            # Google OAuth Token Verifier, Temp-Mail Blocker, IP Quota Tracker
│   ├── temp_store.py          # Local SQLite (WAL mode) Temp Buffer (কাজ চলাকালীন জিরো ডেটা লস ও অ্যানোনিমাস ক্যাশ)
│   └── supabase_db.py         # Supabase Client (শুধুমাত্র লগইন ইউজারদের লিড ও পাবলিক রিভিউ সেভ করার জন্য)
│
├── cli_test.py                # লোকাল টার্মিনাল থেকে কোর এজেন্ট টেস্ট করার স্ক্রিপ্ট
└── data/                      # লোকাল `temp_cache.db` (SQLite) ও এক্সপোর্ট ফাইল থাকার ফোল্ডার (Auto-cleaned)
```

---

## 3. Dependencies (`requirements.txt`)
```text
curl_cffi>=0.7.0
beautifulsoup4>=4.12.3
lxml>=5.2.0
pydantic>=2.7.0
python-dotenv>=1.0.1
google-genai>=0.3.0
groq>=0.9.0
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
slowapi>=0.1.9
supabase>=2.7.0
google-auth>=2.30.0
requests>=2.32.0
aiosqlite>=0.20.0
rich>=13.7.1
```

---

## 4. Core Scraper & Reverse API Specification (`agent/`)

### 4.1. AI Planner System Prompt & Output Schema (`agent/planner.py`)
LLM-কে (Gemini 2.5 Flash বা Groq Llama-3.3-70b) নিচের প্রম্পট দিয়ে কল করতে হবে যাতে সে সবসময় স্ট্রিক্ট JSON রিটার্ন করে:

```text
You are an expert B2B Lead Generation Strategist and Geographic Data Planner.
Convert the user's natural language lead request into a strict JSON execution plan.

RULES:
1. KEYWORDS: Generate 2 to 4 specific Google Maps business category keywords based on the user's request.
2. GEO-SPLITTING (CRITICAL): Google Maps limits results to 120 per search area. If the user specifies a large city or region (e.g., "Dhaka", "Chittagong", "London", "New York"), you MUST break it down into smaller neighborhoods/sub-areas (e.g., Dhanmondi, Gulshan, Banani, Uttara, Mirpur, Motijheel, Khilgaon) with accurate center Latitude (`lat`), Longitude (`lon`), and `radius` in meters (2500 to 4000). If the user already specified a small area (e.g., "Banani"), return 1 to 2 sub-locations covering that area.
3. WEBSITE FILTER:
   - `"no_website"`: User wants leads without websites (includes businesses with only Facebook/Instagram links).
   - `"has_real_website"`: User wants to scrape emails from websites or explicitly needs businesses with websites.
   - `"any"`: User wants all leads regardless of website status.
4. WEBSITE ENRICHMENT:
   - Set `"enabled": true` ONLY if the user asks for emails, social media links, website titles, or extra info from business websites. Otherwise `"enabled": false`.
5. OUTPUT: Respond ONLY with valid JSON matching the exact schema.
```

**Action Plan JSON Schema:**
```json
{
  "user_prompt": "ঢাকার রেস্টুরেন্টগুলোর লিড দাও যাদের ওয়েবসাইট নেই",
  "keywords": ["Restaurant", "Bangladeshi restaurant"],
  "country_code": "bd",
  "language": "en",
  "sub_locations": [
    {"area_name": "Dhanmondi, Dhaka", "lat": 23.7461, "lon": 90.3742, "radius": 3000},
    {"area_name": "Gulshan, Dhaka", "lat": 23.7925, "lon": 90.4078, "radius": 3500}
  ],
  "filters": {
    "website_requirement": "no_website",
    "must_have_phone": true,
    "min_rating": 0.0,
    "max_rating": null,
    "min_reviews": 0,
    "max_reviews": null,
    "max_pages_per_search": 6
  },
  "enrichment": {
    "enabled": false,
    "extract_emails": false,
    "extract_socials": false,
    "detect_cms": false
  }
}
```

### 4.2. Building the `pb` Parameter & Infinite Scrolling Pagination (`agent/gmaps_client.py`)
```python
from urllib.parse import quote
import time
import random

def build_pb_parameter(lat: float, lon: float, offset: int = 0, radius: float = 3500.0) -> str:
    """
    CRITICAL GEO RULE:
    !1d = Radius in meters (float)
    !2d = LONGITUDE (দ্রাঘিমাংশ - e.g., 90.4125) -> MUST BE LON FIRST!
    !3d = LATITUDE (অক্ষাংশ - e.g., 23.8103)  -> MUST BE LAT SECOND!
    !7i20 = Results per page (20)
    !8i{offset} = Pagination offset simulating sidebar scroll (0, 20, 40, 60, 80, 100)
    """
    return (
        f"!4m8!1m3!1d{radius}!2d{lon}!3d{lat}"
        f"!3m2!1i1024!2i768!4f13.1"
        f"!7i20!8i{offset}"
        f"!10b1!12m8!1m1!18b1!2m3!5m1!6e2!20e3!10b1!16b1"
    )

def build_search_url(keyword: str, area_name: str, lat: float, lon: float, offset: int = 0, radius: float = 3500.0, gl: str = "bd", hl: str = "en") -> str:
    full_query = f"{keyword} in {area_name}"
    encoded_q = quote(full_query)
    pb = build_pb_parameter(lat=lat, lon=lon, offset=offset, radius=radius)
    return f"[https://www.google.com/search?tbm=map&authuser=0&hl=](https://www.google.com/search?tbm=map&authuser=0&hl=){hl}&gl={gl}&q={encoded_q}&pb={pb}"
```

**Pagination (Scrolling) Rules:**
- একটি সাব-লোকেশনে সবগুলো লিড পাওয়ার জন্য `offsets = [0, 20, 40, 60, 80, 100]` লুপ চালাতে হবে।
- **Early Stop Conditions:**
  1. যদি কোনো পেজে ০টি রেজাল্ট আসে (`len(page_leads) == 0`), সাথে সাথে `break`।
  2. যদি কোনো পেজে নতুন কোনো ইউনিক `place_id` না পাওয়া যায় (`new_unique_count == 0`), সাথে সাথে `break`।
  3. যদি কোনো পেজে ১৫টির কম রেজাল্ট আসে (`len(page_leads) < 15`), তবে সেটি শেষ পেজ—ডেটা সেভ করে `break`।
- প্রতি পেজ রিকোয়েস্টের মাঝে `time.sleep(random.uniform(0.8, 1.5))` ডিলে দিতে হবে।

### 4.3. Double-Encoded JSON Unwrapping & Exact Index Map (`agent/gmaps_parser.py`)
```python
import json

def safe_get(data, path: list, default=None):
    curr = data
    for idx in path:
        if isinstance(curr, list) and 0 <= idx < len(curr) and curr[idx] is not None:
            curr = curr[idx]
        else:
            return default
    return curr

def unwrap_gmaps_json(raw_response_text: str) -> list:
    text = raw_response_text.strip()
    if text.startswith("{"):
        outer_obj = json.loads(text)
        text = outer_obj.get("d", "")
    clean_text = text.lstrip(")]}'\n ")
    return json.loads(clean_text) if clean_text else []
```

**Exact Tested Index Table (inside `root[0][1]` -> `b_data = item[14]`):**
- প্রথমে `results = safe_get(root, [0, 1], [])` নিতে হবে।
- প্রতিটি `item`-এ চেক করতে হবে: `b_data = safe_get(item, [14])`। যদি `b_data` লিস্ট না হয় (যেমন প্রথম আইটেমটি ম্যাপ মেটাডেটা বা পেইড অ্যাড হয়), তবে `continue` দিয়ে স্কিপ করতে হবে।

| ডেটা ফিল্ড | পাইথন এক্সপ্রেশন (`b_data` থেকে) | নোট ও উদাহরণ |
| :--- | :--- | :--- |
| **`place_id`** | `safe_get(b_data, [78])` | `"ChIJLz68Xgy5VTcR_rcp5wyZfp4"` (Deduplication Key) |
| **`feature_hex_id`** | `safe_get(b_data, [10])` | `"0x3755b90c5ebc3e2f:0x9e7e990ce729b7fe"` |
| **`name`** | `safe_get(b_data, [11])` | `"Cafe Boyati Kabab & Seafood-2"` |
| **`categories`** | `safe_get(b_data, [13], [])` | `["Seafood restaurant"]` |
| **`neighborhood`** | `safe_get(b_data, [14])` | `"Khilgaon"` |
| **`full_address`** | `safe_get(b_data, [39]) or safe_get(b_data, [18])` | `"79, Block-B, South Bansree, Dhaka 1219"` |
| **`website_url`** | `safe_get(b_data, [7, 0])` | ওয়েবসাইট না থাকলে `None`। থাকলে পূর্ণ URL। |
| **`website_domain`**| `safe_get(b_data, [7, 1])` | `"thewindlounge.com"` বা `"facebook.com"` |
| **`phone_local`** | `safe_get(b_data, [178, 0, 0])` | `"01689-384960"` |
| **`phone_intl`** | `safe_get(b_data, [178, 0, 1, 1, 0])` | `"+880 1689-384960"` |
| **`phone_clean`** | `safe_get(b_data, [178, 0, 3])` | `"01689384960"` |
| **`rating`** | `safe_get(b_data, [4, 7])` | `4.8` |
| **`reviews_count`** | `safe_get(b_data, [4, 8], 0)` | `99` |
| **`price_range`** | `safe_get(b_data, [4, 2])` | `"৳200–400"` |
| **`latitude`** | `safe_get(b_data, [9, 2])` | `23.7518453` |
| **`longitude`** | `safe_get(b_data, [9, 3])` | `90.4411504` |
| **`order_link`** | `safe_get(b_data, [75, 0, 0, 2, 0, 1, 2, 0])` | Foodpanda বা বুকিং লিংক |
| **`is_unclaimed`** | `safe_get(b_data, [57, 1]) == "Claim this business"` | `True` হলে বিজনেসটি গুগল ম্যাপসে আনক্লেইমড |

### 4.4. Website Classification & BS4 Deep Enricher (`agent/web_enricher.py`)
```python
SOCIAL_DOMAINS = (
    "facebook.com", "fb.com", "instagram.com", "linkedin.com",
    "linktr.ee", "wa.me", "youtube.com", "tiktok.com", "foodpanda."
)
```
- `website_url` যদি `None` হয় -> `website_status = "No Website"`।
- `website_url`-এ যদি `SOCIAL_DOMAINS`-এর কোনোটি থাকে -> `website_status = "Social Link Only"` (এবং ওই লিংকটি সরাসরি `social_links` ডিকশনারিতে বসে যাবে, আলাদা করে স্ক্র্যাপ করতে হবে না)।
- অন্যথায় -> `website_status = "Has Own Website"`।
- যদি `enrichment.enabled == True` হয় এবং `website_status == "Has Own Website"` হয়:
  - `ThreadPoolExecutor(max_workers=10)` দিয়ে হোমপেজ এবং ১টি কনট্যাক্ট/অ্যাবাউট পেজ (`timeout=8`) স্ক্র্যাপ করতে হবে।
  - ইমেইল Regex চালানোর পর `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.webp`, `.js`, `.css`, `sentry.io`, `example.com`, `wixpress.com` ফিল্টার করে বাদ দিতে হবে।

---

## 5. Secure FastAPI & Dual-Storage Architecture (`backend/`)

### 5.1. Data Storage Strategy (কার ডেটা কোথায় যাবে?)
1. **Local SQLite Temp Buffer (`backend/temp_store.py`):**
   - প্রতিটি স্ক্র্যাপিং জব শুরু হলে স্ক্র্যাপার প্রতি ব্যাচে (২০টি করে লিড) পাওয়ার সাথে সাথে লোকাল SQLite ডাটাবেসে (`data/temp_cache.db`, `PRAGMA journal_mode=WAL;`) সেভ করবে।
   - **কেন?**
     - ইউজার যদি লগইন না করে (Anonymous), তার ডেটা শুধু এই লোকাল বাফারেই থাকবে (Supabase-এর ফ্রি স্টোরেজ নষ্ট হবে না)।
     - ইউজার যদি মাঝপথে **"Stop"** বাটন চাপে বা নেটওয়ার্ক ডিসকানেক্ট হয়, তবুও ওই মুহূর্ত পর্যন্ত পাওয়া সব লিড অক্ষত থাকবে এবং সে CSV/JSON ডাউনলোড করতে পারবে।
     - অ্যানোনিমাস ডেটা ২৪ ঘণ্টা পর অটোমেটিক ক্লিন হয়ে যাবে।
2. **Supabase Cloud Database (`backend/supabase_db.py`):**
   - **শুধুমাত্র যদি ইউজার ভেরিফাইড Google Account দিয়ে লগইন করা থাকে**, তবেই তার লিডগুলো Supabase-এ সেভ হবে।
   - ইউজারের ভেরিফাইড জিমেইল থেকে একটি স্থায়ী ইউনিক আইডি তৈরি হবে:
     `user_uid = "usr_" + hashlib.sha256(verified_email.lower().encode()).hexdigest()[:20]`
   - ইউজার যদি লগইন ছাড়া ১০০০ লিড স্ক্র্যাপ করার পর Google দিয়ে লগইন করে, তবে `/api/auth/sync-session` এন্ডপয়েন্ট কল হয়ে তার লোকাল টেম্প বাফারের ডেটাগুলো সাথে সাথে Supabase-এ তার `user_uid`-তে ট্রান্সফার হয়ে যাবে!

### 5.2. Zero-Bug Security & Anti-Abuse Rules (`backend/security.py`)
FastAPI ব্যাকএন্ডকে ১০০% সিকিউর এবং বাগ-মুক্ত রাখতে নিচের ৫টি নিরাপত্তা ব্যবস্থা কোডে থাকতে হবে:
1. **Google OAuth Token Verification (No Fake/Temp Emails):**
   - ফ্রন্টএন্ড থেকে কখনোই প্লেইন টেক্সটে `email` গ্রহণ করা যাবে না (হ্যাকাররা Postman দিয়ে ফেক জিমেইল পাঠাতে পারে)।
   - ফ্রন্টএন্ড থেকে **Google ID Token (JWT)** বা **Supabase Auth Access Token** হেডার হিসেবে (`Authorization: Bearer <token>`) আসবে।
   - ব্যাকএন্ডে `google.oauth2.id_token.verify_oauth2_token` অথবা `supabase.auth.get_user(token)` দিয়ে টোকেন ভেরিফাই করে সেখান থেকে আসল জিমেইল বের করতে হবে এবং চেক করতে হবে `email_verified == True` কি না।
2. **1,000 Free Lead Quota Enforcement (IP + Device Fingerprint):**
   - লগইন ছাড়া ইউজারদের ক্ষেত্রে ব্যাকএন্ডে `client_ip` এবং `X-Device-Fingerprint` হেডার দুটিই SQLite-এর `anonymous_quotas` টেবিলে ট্র্যাক করতে হবে।
   - একজন অ্যানোনিমাস ইউজার তার ডিভাইস আইডি বদলালেও একই IP থেকে মোট ১০০০ লিডের বেশি স্ক্র্যাপ করতে পারবে না। ১০০০ পূর্ণ হলেই স্ক্র্যাপার অটোমেটিক থেমে যাবে এবং স্ট্যাটাস হবে `"limit_reached_login_required"`।
3. **Concurrency Lock & Memory Leak Prevention:**
   - একজন ইউজার (বা একটি IP) একসাথে মাত্র **১টি লাইভ স্ক্র্যাপিং জব** চালাতে পারবে। একটি জব `running` থাকা অবস্থায় আরেকটি স্টার্ট করলে `429 Too Many Requests` দেবে।
   - ব্যাকগ্রাউন্ড টাস্কে `asyncio.Event()` ব্যবহার করে স্টপ সিগন্যাল হ্যান্ডেল করতে হবে এবং `try...finally` ব্লকের ভেতর মেমোরি থেকে জব ফ্ল্যাগ ক্লিন করতে হবে যাতে মেমোরি লিক না হয়।
4. **Rate Limiting (`slowapi`):**
   - `/api/scrape/start` এন্ডপয়েন্টে প্রতি মিনিটে সর্বোচ্চ ৫টি রিকোয়েস্ট (`5/minute`) এবং `/api/reviews` এন্ডপয়েন্টে প্রতিদিন ৩টি রিকোয়েস্টের লিমিট থাকতে হবে।
5. **Input Sanitization:**
   - ইউজারের `prompt` সর্বোচ্চ ৩০০ ক্যারেক্টারের হতে পারবে (Pydantic `Field(min_length=5, max_length=300)`), যাতে কেউ বিশাল টেক্সট পাঠিয়ে LLM টোকেন শেষ করতে না পারে।

---

## 6. Database Schemas (SQLite Temp Buffer & Supabase Cloud)

### 6.1. Local SQLite Schema (`backend/temp_store.py` - For All Live Jobs & Anonymous Users)
```sql
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS anonymous_quotas (
    identifier TEXT PRIMARY KEY,        -- IP Address বা Device Fingerprint
    total_leads_scraped INTEGER DEFAULT 0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS active_jobs (
    job_id TEXT PRIMARY KEY,
    session_owner TEXT NOT NULL,        -- anon_{fingerprint} অথবা usr_{sha256_gmail}
    is_authenticated INTEGER DEFAULT 0, -- 0 = Anonymous, 1 = Verified Google User
    prompt TEXT NOT NULL,
    status TEXT DEFAULT 'running',      -- 'running', 'completed', 'stopped', 'limit_reached', 'failed'
    current_area TEXT DEFAULT 'Initializing AI Planner...',
    leads_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS temp_leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    place_id TEXT NOT NULL,
    lead_json TEXT NOT NULL,            -- সম্পূর্ণ লিড অবজেক্ট JSON স্ট্রিং আকারে
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, place_id)
);
```

### 6.2. Supabase PostgreSQL Schema (Only for Logged-In Users & Reviews)
Supabase-এর SQL Editor-এ নিচের টেবিলগুলো তৈরি করতে হবে:
```sql
-- ১. ভেরিফাইড লগইন ইউজারদের প্রোফাইল ও কোটা টেবিল
CREATE TABLE verified_users (
    user_uid TEXT PRIMARY KEY,          -- 'usr_' + SHA256(verified_gmail)
    email TEXT UNIQUE NOT NULL,
    full_name TEXT,
    total_leads_saved INT DEFAULT 0,
    plan_type TEXT DEFAULT 'free_logged_in',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ২. ভেরিফাইড ইউজারদের স্থায়ী লিডস টেবিল (ইউজার পরে ফিরে এসে এখান থেকেই ডেটা পাবে)
CREATE TABLE saved_leads (
    id BIGSERIAL PRIMARY KEY,
    user_uid TEXT REFERENCES verified_users(user_uid) ON DELETE CASCADE,
    job_id TEXT NOT NULL,
    place_id TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT,
    phone TEXT,
    website_status TEXT,
    website_url TEXT,
    emails JSONB DEFAULT '[]',
    social_links JSONB DEFAULT '{}',
    cms_tech TEXT,
    rating FLOAT,
    reviews_count INT,
    price_range TEXT,
    is_unclaimed_business BOOLEAN DEFAULT FALSE,
    neighborhood TEXT,
    address TEXT,
    lat FLOAT,
    lon FLOAT,
    google_maps_url TEXT,
    source_query TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_uid, place_id)          -- একজন ইউজারের একাউন্টে একই দোকান দুইবার সেভ হবে না
);

-- ৩. ইউজার ফিডব্যাক ও রিভিউ টেবিল (UI-এর নিচের রিভিউ সেকশনের জন্য)
CREATE TABLE product_reviews (
    id BIGSERIAL PRIMARY KEY,
    user_email TEXT,                    -- Optional (লগইন থাকলে অটো বসবে)
    rating INT CHECK (rating >= 1 AND rating <= 5),
    comment TEXT NOT NULL,
    wants_paid_version BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 7. FastAPI Endpoints Specification (`backend/main.py`)

| Method & Endpoint | কাজের বিবরণ (Functionality) | Auth Requirement |
| :--- | :--- | :--- |
| **`POST /api/scrape/start`** | প্রম্পট নেবে, কোটা চেক করবে, নতুন `job_id` তৈরি করে ব্যাকগ্রাউন্ডে স্ক্র্যাপার স্টার্ট করবে। | Optional (`Bearer Token` থাকলে লগইন মোড, না থাকলে ১০০০ লিমিট অ্যানোনিমাস মোড) |
| **`GET /api/scrape/stream/{job_id}`** | **SSE (Server-Sent Events):** প্রতি ১ সেকেন্ডে ইউজারের স্ক্রিনে লাইভ `leads_count`, `current_area`, `status`, এবং নতুন পাওয়া লিডগুলোর অ্যারে স্ট্রিম করবে। | Public (Valid `job_id`) |
| **`POST /api/scrape/stop/{job_id}`** | সাথে সাথে রানিং স্ক্র্যাপার থামিয়ে দেবে (`stop_event.set()`)। ইতিমধ্যে পাওয়া সব লিড সুরক্ষিত থাকবে। | Owner of `job_id` |
| **`GET /api/scrape/download/{job_id}`** | বর্তমান জবের সব লিড `.csv` অথবা `.json` ফরম্যাটে ডাউনলোড করতে দেবে। | Public (যদি ১০০০ লিমিটের ভেতরে থাকে) বা Verified Auth |
| **`POST /api/auth/sync-session`** | অ্যানোনিমাস ইউজার ১০০০ লিড হওয়ার পর যখন Google লগইন করবে, তখন তার লোকাল `temp_leads` গুলো Supabase-এর `saved_leads`-এ স্থায়ীভাবে সেভ করে দেবে। | **Required** (Verified Google JWT) |
| **`GET /api/user/my-leads`** | লগইন করা ইউজার পরবর্তীতে সাইটে ফিরে এলে তার জিমেইল ইউনিক আইডি (`user_uid`) দিয়ে আগের সেভ করা সব লিড ফেরত দেবে। | **Required** (Verified Google JWT) |
| **`POST /api/reviews`** | UI-এর নিচের রিভিউ বক্স থেকে স্টার রেটিং, কমেন্ট এবং পেইড ভার্সন চায় কি না তা Supabase-এ সেভ করবে। | Public (Rate-limited) |
| **`GET /api/reviews`** | সর্বশেষ সাবমিট করা রিভিউগুলো UI-তে দেখানোর জন্য রিটার্ন করবে। | Public |

---

## 8. Phased Implementation Roadmap (কাজের ধারাবাহিক ধাপ)
যেকোনো AI অ্যাসিস্ট্যান্টকে কাজ দেওয়ার সময় নিচের ক্রমানুসারে একটি করে ধাপ সম্পন্ন ও টেস্ট করতে হবে:

- [x] **Milestone 1: Core Scraper & AI Planner (`agent/`)** — *(Completed)*
- [x] **Milestone 2: Local SQLite Temp Buffer & Pipeline Callbacks (`backend/temp_store.py` & `agent/pipeline.py`)** — *(Completed)*
  - স্ক্র্যাপার যেন প্রতি ব্যাচে (২০টি লিড) পাওয়ার সাথে সাথে লোকাল SQLite-এ সেভ করে এবং `stop_event` চেক করে থামতে পারে।
  - অ্যানোনিমাস ইউজারদের ১০০০ লিমিট চেক করার লজিক তৈরি করা।
- [x] **Milestone 3: Supabase Cloud Sync & Google Auth Security (`backend/security.py` & `backend/supabase_db.py`)** — *(Completed)*
  - Google JWT Token ভেরিফিকেশন, Temp-mail ব্লকিং, জিমেইল থেকে `user_uid` তৈরি এবং শুধুমাত্র লগইন ইউজারদের ডেটা Supabase-এ সিঙ্ক করার মেথড তৈরি করা।
- [x] **Milestone 4: Secure FastAPI Server & SSE Live Stream (`backend/main.py`)** — *(Completed)*
  - উপরের ৮টি এন্ডপয়েন্ট, CORS, Rate Limiting (`slowapi`) এবং SSE স্ট্রিমিং যুক্ত করে `http://localhost:8000/docs` (Swagger UI) থেকে পুরো ব্যাকএন্ড টেস্ট করা।
- [x] **Milestone 5: Minimalist Live Web UI (Frontend)** — *(Completed)*
  - ব্যাকএন্ড ১০০% বাগ-মুক্ত হওয়ার পর ১-পেজের ক্লিন UI (Prompt Box + Live Counter/Table + Stop Button + 1000 Limit Google Login Gate + Review Section) তৈরি করা।
- [x] **Milestone 6: Reusable On-Demand Local SEO Audit Engine (`seo_audit/`)** — *(Completed)*
  - **Core Scraper Protection:** The existing Google Maps scraper (`agent/`) remains 100% untouched.
  - **11 Local SEO Check Engines (`seo_audit/analyzer.py`):** Speed/SSL, Mobile Viewport, Title Tag, Meta Description, H1, Canonical, Robots noindex, Image Alt Coverage, Local Keywords (City+Niche), NAP Consistency, Schema LocalBusiness & Contact/Maps embed.
  - **Verified-Only Scoring Engine (`seo_audit/scorer.py`):** 0–100 Opportunity Score strictly excluding unverified weights from denominator; critical `noindex` enforces minimum score of 85.
  - **Fault-Tolerant Fetcher (`seo_audit/fetcher.py`):** `curl_cffi` (Chrome TLS impersonation), response timing, and automatic SSL error fallback.
  - **Non-Destructive XLSX Column Appender (`seo_audit/xlsx_appender.py`):** Preserves 100% of existing columns in original order and appends the exact 9 SEO columns to the far right with Royal Navy table styling.
  - **FastAPI Endpoints (`seo_audit/routes.py` mounted in `backend/main.py`):** `POST /api/seo-audit` (single) and `POST /api/seo-audit/bulk` (batch), plus `include_seo=true` query param on `GET /api/scrape/download/{job_id}`.
  - **Comprehensive Offline Test Suite (`tests/test_seo_audit.py`):** 15 tests covering all 11 checks, edge cases, error resilience, and XLSX export.

---

## 9. On-Demand Local SEO Audit Engine Specification (`seo_audit/`)

### 9.1. Architecture & Design Principles
1. **On-Demand Only (Decoupled):** The SEO audit module never runs automatically during initial Google Maps scraping. It executes strictly when triggered via API or UI button (`Page SEO`).
2. **Zero Browser Automation:** Pure HTTP requests using `curl_cffi` (`impersonate="chrome124"`) and `BeautifulSoup4` for minimal RAM footprint on cloud hosts like Render.
3. **Non-Blocking & Fault-Tolerant:** Each business audit is wrapped in a per-business `try...except` block with structured logging. A single broken or timing-out website never crashes the batch or API stream.
4. **Verified-Only Scoring Law:** If input data is missing (e.g. Google Maps lead lacks phone or city), the check is marked `Unverified` and its weight is completely excluded from the denominator. Never penalize unverified checks.
5. **Preserve Existing XLSX Columns:** When exporting to Excel, all existing columns and cell values are preserved in their exact order, and 9 standardized SEO columns are appended to the far right.

### 9.2. File Layout
```text
seo_audit/
├── __init__.py           # Package exports (models, config)
├── config.py             # SEO_AUDIT_TIMEOUT (12s), MAX_RETRIES (2), weights, thresholds
├── models.py             # Pydantic schemas: AuditIssue, AuditStatus, Priority, SEOReport, AuditInput
├── fetcher.py            # Fault-tolerant curl_cffi fetcher with response timing and SSL fallback
├── analyzer.py           # 11 Local SEO Check implementations (Speed, Viewport, Title, Meta, H1, Canonical, Robots, Alt, Keywords, NAP, Schema)
├── scorer.py             # Verified-only Opportunity Score (0–100) formula
├── auditor.py            # Main Orchestrator with per-business error isolation and thread pooling
├── routes.py             # FastAPI Endpoints: POST /api/seo-audit and POST /api/seo-audit/bulk
└── xlsx_appender.py      # Non-destructive XLSX column appender preserving existing cols
```

### 9.3. Check Weights & Opportunity Score Formula
```python
SEO_CHECK_WEIGHTS = {
    "website_speed": 12,          # HTTP Status, SSL & Load Time
    "mobile_friendly": 12,        # Viewport & Mobile Usability
    "title_tag": 10,              # Title presence & length
    "meta_description": 6,        # Meta description presence & length
    "h1_status": 10,              # Single descriptive H1
    "canonical_robots": 8,        # Canonical & Indexability (If 'noindex' -> min score 85)
    "image_alt": 4,               # Image Alt Text coverage
    "local_keywords": 12,         # City + Category in Title/H1
    "nap_consistency": 12,        # Name, Address, Phone match
    "schema_markup": 10,          # JSON-LD LocalBusiness Schema
    "contact_maps_embed": 4       # Clickable tel: link & Google Map iframe
}
```
Formula:
$$\text{SEO Opportunity Score} = \text{round}\left( \frac{\sum \text{opportunity\_points of verified checks}}{\sum \text{weight of verified checks}} \times 100 \right)$$
- `Pass` = 0.0 * weight
- `Warning` = 0.5 * weight
- `Fail` = 1.0 * weight
- `Unverified` = excluded from denominator
- If `verified_weight_sum == 0`, score is `None` (rendered as `"N/A"` or `"Unverified"`).
- If `noindex` is detected, score is enforced as `max(score, 85)`.

### 9.4. Standard Appended XLSX Columns
1. `Website Speed`
2. `Mobile Friendly`
3. `Title Tag Status`
4. `Meta Description Status`
5. `H1 Status`
6. `Local Keyword Status`
7. `Schema Status`
8. `NAP Status`
9. `SEO Opportunity Score`