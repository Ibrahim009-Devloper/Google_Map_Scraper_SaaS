"""
Professional Data Formatter and Lead Cleaner for Autonomous AI Lead Scraper.
Polishes, standardizes, and validates business names, phone numbers, addresses,
emails, social links, and metadata into publication-ready executive format.
"""

import re
from typing import List, Optional, Union
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from agent.schemas import LeadItem, SocialLinks


# Blacklist of false-positive / boilerplate email domains and patterns
JUNK_EMAIL_DOMAINS = {
    "company.com", "yourcompany.com", "mycompany.com", "ourcompany.com",
    "domain.com", "yourdomain.com", "mydomain.com", "sample.com",
    "example.com", "example.org", "example.net", "test.com", "testing.com",
    "website.com", "yourwebsite.com", "mywebsite.com", "site.com", "yoursite.com",
    "email.com", "youremail.com", "temp.com", "temporary.com",
    "themeforest.net", "envato.com", "wix.com", "wixpress.com",
    "wordpress.org", "wordpress.com", "wp.com", "woocommerce.com",
    "shopify.com", "myshopify.com", "squarespace.com", "webflow.io",
    "bootstrap.com", "getbootstrap.com", "placeholder.com", "dummy.com",
    "sentry.io", "sentry-cdn.com", "bugsnag.com", "rollbar.com",
    "cloudflare.com", "gravatar.com", "schema.org", "w3.org",
    "googleapis.com", "gstatic.com", "google.com", "google-analytics.com",
    "facebook.com", "instagram.com", "twitter.com", "linkedin.com",
    "apple.com", "microsoft.com", "github.com", "gitlab.com",
    "bootstrapcdn.com", "jquery.com", "unpkg.com", "jsdelivr.net",
}

JUNK_EMAIL_USERNAMES = {
    "you", "your", "user", "username", "name", "yourname", "myname",
    "someone", "sample", "example", "test", "testing", "demo", "dummy",
    "admin_email", "email", "mail", "first.last", "firstname.lastname",
    "john.doe", "jane.doe", "user.name",
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "mailer-daemon", "postmaster", "hostmaster", "webmaster",
    "abuse", "security", "security-alert", "security.alerts", "alerts", "alert",
    "infosecurity", "infosecurity.alerts", "spam", "daemon", "root",
}

JUNK_EMAIL_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico",
    ".js", ".css", ".woff", ".woff2", ".ttf", ".mp4", ".pdf", ".zip",
)


def clean_business_name(raw_name: Optional[str]) -> str:
    """
    Cleans business name:
    - Removes leading index numbering (e.g. '1. Sultan's Dine' -> 'Sultan's Dine')
    - Removes trailing noise, bullet points, emoji clutter
    - Converts ALL-CAPS names to elegant Title Case while preserving acronyms (e.g. 'ABC Bank')
    """
    if not raw_name:
        return "Unknown Business"

    name = str(raw_name).strip()

    # Remove leading numbering like "1. ", "01. ", "#1 "
    name = re.sub(r'^(?:#?\d+[\.\-\)]\s*)+', '', name).strip()

    # Remove strange surrounding quotes or brackets
    name = re.sub(r'^[\'"“‘\(\[\{]+|[\'"”’\)\]\}]+$', '', name).strip()

    # Collapse multiple spaces and tabs
    name = re.sub(r'\s+', ' ', name).strip()

    # If the name is in ALL CAPS (and longer than 4 chars), convert to Title Case
    # but keep common acronyms capitalized (e.g. LTD, LLC, BD, AI, B2B)
    if name.isupper() and len(name) > 4:
        words = name.split()
        capitalized = []
        acronyms = {"LLC", "LTD", "PLC", "INC", "CORP", "AI", "IT", "BD", "USA", "UK", "B2B", "VIP", "CNG", "ATM"}
        for w in words:
            clean_w = w.strip(".,-")
            if clean_w in acronyms:
                capitalized.append(w)
            else:
                capitalized.append(w.capitalize())
        name = " ".join(capitalized)

    return name or "Unknown Business"


def clean_phone_number(raw_phone: Optional[str], country_code: str = "bd") -> Optional[str]:
    """
    Standardizes phone numbers into clean international presentation format without
    imposing wrong country codes onto international numbers:
    - If raw_phone already has an international prefix '+', respect and format that country's prefix:
      * '+1' -> US/Canada: '+1 (XXX) XXX-XXXX'
      * '+44' -> UK: '+44 XXXX XXXXXX'
      * '+880' -> Bangladesh: '+880 1XXX-XXXXXX'
      * other '+' -> preserve clean international format
    - If raw_phone has no '+', use country_code:
      * For Canada/US ('ca', 'us'): format 10 digits as '+1 (XXX) XXX-XXXX'
      * For Bangladesh ('bd'): format 10/11 digits as '+880 1XXX-XXXXXX'
      * General: return raw string
    """
    if not raw_phone:
        return None

    raw = str(raw_phone).strip()
    digits = re.sub(r'\D', '', raw)

    if not digits or len(digits) < 6:
        return raw

    # 1. If phone already has an international prefix '+'
    if raw.startswith("+"):
        if digits.startswith("1") and len(digits) == 11:
            return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        elif digits.startswith("880"):
            rest = digits[3:]
            if rest.startswith("0"):
                rest = rest[1:]
            if len(rest) == 10 and rest.startswith("1"):
                return f"+880 {rest[:4]}-{rest[4:]}"
            return f"+880 {rest}"
        elif digits.startswith("44") and len(digits) >= 10:
            rest = digits[2:]
            return f"+44 {rest[:4]} {rest[4:]}"
        return raw

    # 2. If phone has no '+', format according to target country_code
    cc = (country_code or "bd").lower().strip()

    # Canada & USA (cc in 'ca', 'us')
    if cc in ("ca", "us") or (len(digits) == 11 and digits.startswith("1")):
        d = digits[1:] if (len(digits) == 11 and digits.startswith("1")) else digits
        if len(d) == 10:
            return f"+1 ({d[:3]}) {d[3:6]}-{d[6:]}"
        return f"+1 {digits}"

    # Bangladesh (cc == 'bd')
    if cc == "bd" or digits.startswith("880") or (len(digits) in (10, 11) and digits.startswith("01")):
        d = digits
        if d.startswith("880"):
            d = d[3:]
        if d.startswith("0"):
            d = d[1:]
        if len(d) == 10 and d.startswith("1"):
            return f"+880 {d[:4]}-{d[4:]}"
        elif len(d) in (8, 9) and d.startswith("2"):
            return f"+880 2-{d[1:]}"
        return f"+880 {d}"

    # Default fallback for other countries
    return raw


def clean_address(raw_address: Optional[str]) -> Optional[str]:
    """
    Cleans street address:
    - Removes double commas and strange spacing
    - Strips plus codes (e.g. 'Q98C+94 Dhaka') when standard address is available
    - Normalizes comma spacing ('Dhaka, Bangladesh' instead of 'Dhaka ,Bangladesh')
    """
    if not raw_address:
        return None

    addr = str(raw_address).strip()
    # Normalize double commas and dangling punctuation
    addr = re.sub(r'[\,]{2,}', ', ', addr)
    addr = re.sub(r'\s*,\s*', ', ', addr)
    addr = re.sub(r'\s+', ' ', addr)
    addr = addr.strip(" ,.-")

    # If address contains plus code at beginning followed by real address, clean it
    plus_code_match = re.match(r'^[A-Z0-9]{4}\+[A-Z0-9]{2,}\s*,\s*(.+)$', addr)
    if plus_code_match:
        addr = plus_code_match.group(1).strip()

    return addr or None


def clean_email_list(emails: List[str]) -> List[str]:
    """
    Cleans, deduplicates, and filters extracted email addresses:
    - Lowercases all addresses
    - Removes fake / image / placeholder / dummy emails
    - Strips trailing punctuation
    - Selects the single best authentic contact email
    """
    if not emails:
        return []

    valid_emails = []
    seen = set()

    primary_keywords = ("info", "contact", "hello", "enquiry", "enquiries", "support", "sales", "office", "mail")

    for e in emails:
        clean_e = str(e).strip().lower().rstrip(".,;:)\"'>")
        if not clean_e or "@" not in clean_e:
            continue

        # Check junk extensions
        if any(clean_e.endswith(ext) for ext in JUNK_EMAIL_EXTENSIONS):
            continue

        parts = clean_e.split("@")
        if len(parts) != 2:
            continue
        user, domain = parts

        # Check junk domains
        if domain in JUNK_EMAIL_DOMAINS or any(domain.endswith("." + jd) for jd in JUNK_EMAIL_DOMAINS):
            continue

        # Check junk usernames
        if user in JUNK_EMAIL_USERNAMES:
            continue
        if any(user.startswith(ju) for ju in ("noreply", "no-reply", "donotreply", "mailer-daemon", "infosecurity")):
            continue
        if any(user.endswith(ju) for ju in (".alerts", "_alerts", "-alerts")):
            continue

        # Check basic email regex syntax
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', clean_e):
            continue

        if clean_e not in seen:
            seen.add(clean_e)
            valid_emails.append(clean_e)

    if not valid_emails:
        return []

    # Sort valid emails so primary prefixes (info, contact, hello, enquiry, etc.) are top priority
    def _email_rank(em: str) -> int:
        u = em.split("@")[0]
        if u in primary_keywords:
            return 100
        if any(u.startswith(p) for p in primary_keywords):
            return 80
        if any(p in u for p in primary_keywords):
            return 60
        return 20

    valid_emails.sort(key=_email_rank, reverse=True)
    # Return single best email
    return [valid_emails[0]]


def clean_website_url(raw_url: Optional[str]) -> Optional[str]:
    """
    Cleans and standardizes company website URL:
    - Unwraps Google redirection and tracking wrappers (e.g. google.com/url?q=..., google.ca/url?url=...)
    - Rejects internal Google search / maps links that are not actual business websites
    - Strips UTM marketing query parameters and tracking parameters (ved, usg, sa, fbclid, gclid)
    - Ensures proper http/https scheme
    """
    if not raw_url:
        return None

    url = str(raw_url).strip()
    if not url:
        return None

    # Iteratively unwrap Google redirect wrapper (handles double-encoded redirects)
    for _ in range(2):
        if "google." in url.lower() and "/url" in url.lower():
            try:
                parsed_g = urlparse(url if url.startswith(("http://", "https://")) else "https://" + url)
                qs = parse_qs(parsed_g.query)
                candidate_target = None
                if "q" in qs and qs["q"]:
                    candidate_target = qs["q"][0]
                elif "url" in qs and qs["url"]:
                    candidate_target = qs["url"][0]

                if candidate_target and (candidate_target.startswith(("http://", "https://")) or candidate_target.startswith("www.")):
                    url = candidate_target
            except Exception:
                pass

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urlparse(url)
        netloc_lower = parsed.netloc.lower().replace("www.", "")

        # Reject if the URL is any Google internal domain or search/maps service
        if any(g in netloc_lower for g in ("google.", "google.com", "google.ca", "google.co.uk", "google.com.bd", "maps.google", "goo.gl")):
            return None

        # Strip tracking query params
        qs = parse_qs(parsed.query)
        strip_keys = {"fbclid", "gclid", "ved", "usg", "sa", "ei", "sei", "sxsrf"}
        filtered_qs = {k: v for k, v in qs.items() if not k.lower().startswith("utm_") and k.lower() not in strip_keys}
        new_query = urlencode(filtered_qs, doseq=True)
        clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip('/') or '/', parsed.params, new_query, ""))
        return clean
    except Exception:
        return url


def clean_lead_item(lead: Union[LeadItem, dict], country_code: str = "bd") -> Union[LeadItem, dict]:
    """
    Applies comprehensive professional formatting and data cleaning to a LeadItem or lead dictionary.
    """
    if isinstance(lead, dict):
        lead["name"] = clean_business_name(lead.get("name", ""))
        lead["phone"] = clean_phone_number(lead.get("phone"), country_code=country_code)
        lead["address"] = clean_address(lead.get("address"))
        lead["website_url"] = clean_website_url(lead.get("website_url"))
        lead["emails"] = clean_email_list(lead.get("emails", []))

        if lead.get("category"):
            lead["category"] = clean_business_name(lead["category"])

        if lead.get("neighborhood"):
            lead["neighborhood"] = clean_address(lead["neighborhood"])

        return lead

    # If it is a Pydantic LeadItem instance
    lead.name = clean_business_name(lead.name)
    lead.phone = clean_phone_number(lead.phone, country_code=country_code)
    lead.address = clean_address(lead.address)
    lead.website_url = clean_website_url(lead.website_url)
    lead.emails = clean_email_list(lead.emails)

    if lead.category:
        lead.category = clean_business_name(lead.category)

    if lead.neighborhood:
        lead.neighborhood = clean_address(lead.neighborhood)

    return lead
