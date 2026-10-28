"""
Configuration settings, scoring weights, and thresholds for the Local SEO Audit Engine.
"""

import os

# Audit execution parameters
SEO_AUDIT_TIMEOUT = int(os.getenv("SEO_AUDIT_TIMEOUT", "12"))
SEO_AUDIT_MAX_RETRIES = int(os.getenv("SEO_AUDIT_MAX_RETRIES", "2"))
SEO_SLOW_LOAD_THRESHOLD = float(os.getenv("SEO_SLOW_LOAD_THRESHOLD", "5.0"))
SEO_MODERATE_LOAD_THRESHOLD = float(os.getenv("SEO_MODERATE_LOAD_THRESHOLD", "2.5"))
PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY", "").strip()

# Strict weights for all 11 checks (Total = 100)
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
    "contact_maps_embed": 4,      # Clickable tel: link & Google Map iframe
}
