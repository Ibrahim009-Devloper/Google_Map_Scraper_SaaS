"""
Configuration settings for Autonomous AI Google Maps Lead Generation Agent.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Base Directories
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
PLANS_DIR = OUTPUT_DIR / "plans"
LEADS_DIR = OUTPUT_DIR / "leads"
DATA_DIR = BASE_DIR / "data"

# Ensure directories exist
PLANS_DIR.mkdir(parents=True, exist_ok=True)
LEADS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Database & Quota Settings
TEMP_DB_PATH = DATA_DIR / "temp_cache.db"
ANONYMOUS_LEAD_LIMIT = 1000
ANONYMOUS_JOB_LIMIT = 1

# LLM Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
DEFAULT_LLM_PROVIDER = os.getenv("DEFAULT_LLM_PROVIDER", "gemini").lower().strip()

GEMINI_MODEL = "gemini-2.5-flash"
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

def clean_env_str(val: Optional[str]) -> str:
    """Strips outer quotes, whitespace, and formatting anomalies from environment variables."""
    if not val:
        return ""
    cleaned = str(val).strip().strip("\"'").strip()
    if cleaned.lower().startswith("bearer "):
        cleaned = cleaned[7:].strip()
    # If the user left dummy placeholder text from .env.example, treat as unset
    if "your_supabase_" in cleaned or "your_gemini_" in cleaned or "your_groq_" in cleaned:
        return ""
    return cleaned


# Supabase Configuration
SUPABASE_URL = clean_env_str(os.getenv("SUPABASE_URL", "")).rstrip("/")
SUPABASE_KEY = clean_env_str(os.getenv("SUPABASE_KEY", ""))
SUPABASE_ANON_KEY = clean_env_str(os.getenv("SUPABASE_ANON_KEY", ""))
GOOGLE_CLIENT_ID = clean_env_str(os.getenv("GOOGLE_CLIENT_ID", ""))

# If SUPABASE_ANON_KEY was not explicitly provided or invalid, check if SUPABASE_KEY is an anon key
if not SUPABASE_ANON_KEY and SUPABASE_KEY:
    try:
        import base64
        import json
        parts = SUPABASE_KEY.split(".")
        if len(parts) >= 2:
            padding = "=" * (4 - len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + padding).decode("utf-8"))
            if payload.get("role") == "anon":
                SUPABASE_ANON_KEY = SUPABASE_KEY
    except Exception:
        pass

# HTTP & Scraping Settings
DEFAULT_IMPERSONATE = "chrome124"
DEFAULT_TIMEOUT = 15
WEB_TIMEOUT = 6
MAX_CONCURRENT_ENRICHMENT = 10

# Pagination Defaults
DEFAULT_MAX_PAGES_PER_SEARCH = 6
RESULTS_PER_PAGE = 20

# Social & Directory domains (businesses with only these URLs are categorized as 'Social Link Only')
SOCIAL_OR_DIRECTORY_DOMAINS = (
    "facebook.com",
    "fb.com",
    "instagram.com",
    "linkedin.com",
    "linktr.ee",
    "wa.me",
    "youtube.com",
    "tiktok.com",
    "foodpanda.",
    "twitter.com",
    "x.com",
)
