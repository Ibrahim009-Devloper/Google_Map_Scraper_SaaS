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
ANONYMOUS_LEAD_LIMIT = 100
ANONYMOUS_JOB_LIMIT = 1

# LLM Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
DEFAULT_LLM_PROVIDER = os.getenv("DEFAULT_LLM_PROVIDER", "gemini").lower().strip()

GEMINI_MODEL = "gemini-2.5-flash"
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Supabase Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()

# HTTP & Scraping Settings
DEFAULT_IMPERSONATE = "chrome124"
DEFAULT_TIMEOUT = 15
WEB_TIMEOUT = 15
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
