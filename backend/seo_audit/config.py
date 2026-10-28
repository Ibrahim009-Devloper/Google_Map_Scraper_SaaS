"""
Configuration settings, scoring weights, and thresholds for the Local SEO Audit Engine.
"""

import os

# Audit execution parameters
SEO_AUDIT_TIMEOUT = int(os.getenv("SEO_AUDIT_TIMEOUT", "10"))
SEO_AUDIT_MAX_RETRIES = int(os.getenv("SEO_AUDIT_MAX_RETRIES", "2"))
SEO_SLOW_LOAD_THRESHOLD = float(os.getenv("SEO_SLOW_LOAD_THRESHOLD", "4.0"))
SEO_MODERATE_LOAD_THRESHOLD = float(os.getenv("SEO_MODERATE_LOAD_THRESHOLD", "2.0"))
PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY", "").strip()

# Complete 21 Standard Agency-Grade Local SEO Columns
SEO_XLSX_COLUMNS = [
    # A. Technical Foundation & Crawlability
    "Final URL & HTTP Status",
    "SSL & HTTPS Redirect Status",
    "Server Response (TTFB)",
    "Indexability (Meta Robots)",
    "Canonical Tag Status",
    "Robots.txt & XML Sitemap",
    # B. Raw Evidence Extraction
    "Extracted Title Text",
    "Title Tag Status",
    "Meta Description Status",
    "Extracted Primary H1",
    "H1 Tag Status",
    "Homepage Word Count",
    "Image Alt Text Gap",
    # C. Local SEO Signals
    "Local Keyword Status",
    "Schema Status",
    "NAP Status",
    "Google Maps Embed",
    "GBP Category Alignment",
    # D. Scoring & Outreach
    "SEO Health Score",
    "Lead Pitch Priority",
    "AI / Dynamic Icebreaker Hook",
]

# Penalty deductions for SEO Health Score (0-100, where 100 is pristine)
SEO_CHECK_PENALTIES = {
    "ssl_redirect": 20,           # Unencrypted HTTP or missing 301
    "server_response_ttfb": 12,   # Slow server response > 2.5s
    "meta_robots": 35,            # noindex tag present on homepage
    "canonical_tag": 8,           # Missing or cross-domain canonical
    "robots_sitemap": 6,          # Missing robots.txt or sitemap
    "title_tag": 12,              # Missing, too short, or bloated
    "meta_description": 8,        # Missing or extreme length
    "h1_status": 12,              # Missing or multiple H1s
    "word_count": 10,             # Thin content < 300 words
    "image_alt": 6,               # Missing image alt tags
    "local_keywords": 12,         # Missing city or category in Title/H1
    "schema_markup": 12,          # Missing LocalBusiness schema
    "nap_consistency": 14,        # Missing GBP phone or address
    "maps_embed": 4,              # Missing Google Maps embed
    "gbp_category_alignment": 8,  # Mismatch between GBP category and page content
}

# Backward compatibility alias
SEO_CHECK_WEIGHTS = SEO_CHECK_PENALTIES
