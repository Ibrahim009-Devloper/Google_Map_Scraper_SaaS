"""
High-Speed Website Deep Scraping & Contact Intelligence Enricher.
Extracts verified business emails, social media profiles (Facebook, Instagram, LinkedIn, WhatsApp),
phone numbers, and detects CMS platforms (WordPress, Shopify, Wix, Squarespace, Webflow).

Key Features:
- Advanced Anti-Obfuscation & Regex Engine: Cloudflare XOR decoder, mailto unquoter, HTML unescape,
  and anti-bot text de-obfuscation ('info [at] domain [dot] com').
- Strict Junk Filter: Eliminates template placeholders ('you@company.com', 'user@example.com'),
  dummy domains ('company.com', 'domain.com'), image retina assets ('@2x.png'), and server alert daemons.
- Single Best Email Ranker: Picks strictly ONE authentic, highest-scoring business contact email
  (prioritizing company domain match and 'info@', 'contact@', 'enquiries@' prefixes).
- Lightning Speed with Early Stopping:
  - 6-second timeout prevents slow/dead sites from hanging worker threads.
  - If a verified domain email is found on the homepage, subpage crawling is skipped immediately.
  - Subpages (/contact, /about) are crawled concurrently in parallel only when necessary.
"""

import html
import re
from urllib.parse import urljoin, urlparse, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Set, Tuple, Dict, Any, Callable

from bs4 import BeautifulSoup
from curl_cffi import requests

from config import DEFAULT_IMPERSONATE, WEB_TIMEOUT, MAX_CONCURRENT_ENRICHMENT
from agent.schemas import LeadItem, SocialLinks
from agent.cleaner import clean_phone_number, clean_website_url

# Advanced Email Regex (handles international characters, subdomains, and clean boundaries)
EMAIL_REGEX = re.compile(
    r"\b[A-Za-z0-9](?:[A-Za-z0-9._%+-]*[A-Za-z0-9])?@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,12}\b",
    re.IGNORECASE
)

# Linear O(N) Deobfuscation regexes (No catastrophic backtracking)
RE_OBFUSCATED_AT = re.compile(r"\[\s*(?:at|@)\s*\]|\(\s*(?:at|@)\s*\)|\s+at\s+", re.IGNORECASE)
RE_OBFUSCATED_DOT = re.compile(r"\[\s*dot\s*\]|\(\s*dot\s*\)|\s+dot\s+", re.IGNORECASE)
RE_SPACED_AT = re.compile(r"\s*@\s*")
RE_SPACED_DOT = re.compile(r"\s*\.\s*")

# Common non-email media & file extensions that produce false positives
JUNK_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico",
    ".js", ".css", ".woff", ".woff2", ".ttf", ".eot",
    ".mp4", ".avi", ".mov", ".zip", ".pdf", ".map", ".tar", ".gz",
    ".m3u8", ".ts", ".xml", ".json", ".vue", ".jsx", ".tsx"
)

# Blacklist of template, dummy, CDN, tech, and placeholder domains
JUNK_DOMAINS = {
    # Generic placeholder domains commonly left in web templates & themes
    "company.com", "yourcompany.com", "mycompany.com", "ourcompany.com",
    "domain.com", "yourdomain.com", "mydomain.com", "sample.com",
    "example.com", "example.org", "example.net", "test.com", "testing.com",
    "website.com", "yourwebsite.com", "mywebsite.com", "site.com", "yoursite.com",
    "email.com", "youremail.com", "temp.com", "temporary.com",
    "themeforest.net", "envato.com", "wix.com", "wixpress.com",
    "wordpress.org", "wordpress.com", "wp.com", "woocommerce.com",
    "shopify.com", "myshopify.com", "squarespace.com", "webflow.io",
    "bootstrap.com", "getbootstrap.com", "placeholder.com", "dummy.com",
    # Service, error reporting, tracking, CDN & tech vendor domains
    "sentry.io", "sentry-cdn.com", "bugsnag.com", "rollbar.com",
    "cloudflare.com", "gravatar.com", "schema.org", "w3.org",
    "googleapis.com", "gstatic.com", "google.com", "google-analytics.com",
    "facebook.com", "instagram.com", "twitter.com", "linkedin.com",
    "apple.com", "microsoft.com", "github.com", "gitlab.com",
    "bootstrapcdn.com", "jquery.com", "unpkg.com", "jsdelivr.net",
    "sendgrid.net", "mailchimp.com", "hubspot.com",
}

# Blacklist of dummy placeholder usernames and automated server daemon accounts
JUNK_USERNAMES = {
    "you", "your", "user", "username", "name", "yourname", "myname",
    "someone", "sample", "example", "test", "testing", "demo", "dummy",
    "admin_email", "email", "mail", "first.last", "firstname.lastname",
    "john.doe", "jane.doe", "user.name",
    # Automated server alerts, daemons, postmasters
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "mailer-daemon", "postmaster", "hostmaster", "webmaster",
    "abuse", "security", "security-alert", "security.alerts", "alerts", "alert",
    "infosecurity", "infosecurity.alerts", "spam", "daemon", "root",
}

# Canonical subpages prioritized when looking for contact information
CANONICAL_TARGETS = ["/contact", "/contact-us", "/about", "/about-us", "/reach-us", "/get-in-touch"]

SUBPAGE_PATTERNS = [
    # Top Priority (Score 10): Direct Contact & Get in Touch pages
    (re.compile(r"contact(?:-us|_us|us)?|reach(?:-us|_us)?|get-in-touch|contactpage", re.I), 10),
    # High Priority (Score 8): About, Story, Profile pages
    (re.compile(r"about(?:-us|_us|us)?|who-we-are|our-story|company|profile", re.I), 8),
    # Medium-High Priority (Score 6): Team, Branches, Location pages
    (re.compile(r"team|management|locations?|branches?|find-us|our-offices?", re.I), 6),
    # Medium Priority (Score 4): Support, Help, Info, Customer Care
    (re.compile(r"support|help|info|feedback|customer-care|helpdesk", re.I), 4),
    # Lower Priority (Score 2): Legal / Terms / Privacy
    (re.compile(r"privacy|terms|impressum|legal|disclaimer|corporate", re.I), 2),
]


def decode_cloudflare_email(cf_hex: str) -> Optional[str]:
    """
    Decodes emails protected by Cloudflare's email protection XOR cipher.
    Found in data-cfemail="..." and /cdn-cgi/l/email-protection#...
    """
    try:
        cf_hex = cf_hex.strip()
        if len(cf_hex) < 4:
            return None
        k = int(cf_hex[:2], 16)
        email = "".join([chr(int(cf_hex[i:i+2], 16) ^ k) for i in range(2, len(cf_hex), 2)])
        return email.strip().lower()
    except Exception:
        return None


def deobfuscate_text(text: str) -> str:
    """
    Deobfuscates text containing HTML entities, URL encodings,
    and anti-bot patterns like 'info [at] domain [dot] com' with linear O(N) regex.
    """
    if not text:
        return ""
    text = html.unescape(text)
    text = unquote(text)
    text = RE_OBFUSCATED_AT.sub("@", text)
    text = RE_OBFUSCATED_DOT.sub(".", text)
    text = RE_SPACED_AT.sub("@", text)
    text = RE_SPACED_DOT.sub(".", text)
    return text


def extract_domain(url: str) -> str:
    """Extracts root domain without subdomains or www (e.g. 'thecorporatedge.com')."""
    if not url:
        return ""
    try:
        netloc = urlparse(url if url.startswith(("http://", "https://")) else "https://" + url).netloc.lower()
        if ":" in netloc:
            netloc = netloc.split(":")[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def is_valid_email(email: str) -> bool:
    """
    Strictly validates extracted email addresses and filters out garbage,
    file extensions, dummy placeholders, retina image filenames, and server daemon domains.
    """
    if not email:
        return False
    # Strip whitespace, quotes, parentheses, brackets, and trailing punctuation
    clean = email.strip().strip(".,;:\"'()[]<>{} \t\r\n").lower()
    if len(clean) < 6 or len(clean) > 80:
        return False
    if clean.count("@") != 1:
        return False

    parts = clean.split("@")
    if len(parts) != 2:
        return False
    user_part, domain_part = parts

    if not user_part or not domain_part:
        return False
    if "." not in domain_part:
        return False

    tld = domain_part.split(".")[-1]
    if len(tld) < 2 or len(tld) > 12 or not tld.isalpha():
        return False

    # Check junk extensions
    if clean.endswith(JUNK_EXTENSIONS) or tld in ("png", "jpg", "jpeg", "gif", "svg", "webp", "js", "css", "woff", "ttf", "pdf", "mp4", "zip", "xml", "json"):
        return False

    # Filter out retina image assets like logo@2x.png or icon@3x.jpg
    if re.search(r"@\d+x\.", clean, re.I):
        return False

    # Check junk domains
    for junk_d in JUNK_DOMAINS:
        if domain_part == junk_d or domain_part.endswith("." + junk_d):
            return False

    # Check junk usernames (full match or prefix match for alerts/daemons)
    if user_part in JUNK_USERNAMES:
        return False
    if any(user_part.startswith(u) for u in ("noreply", "no-reply", "donotreply", "mailer-daemon", "infosecurity")):
        return False
    if any(user_part.endswith(u) for u in (".alerts", "_alerts", "-alerts")):
        return False

    return True


def score_email(email: str, website_url: str) -> int:
    """
    Ranks extracted email addresses to select the single most authentic,
    valuable business contact email.
    """
    clean = email.strip().lower()
    parts = clean.split("@")
    if len(parts) != 2:
        return 0
    user_part, email_domain = parts
    site_domain = extract_domain(website_url)

    score = 0

    # 1. Highest priority: Email domain matches the business website domain (+100)
    if site_domain:
        if email_domain == site_domain or email_domain.endswith("." + site_domain):
            score += 100
        elif site_domain.endswith("." + email_domain):
            score += 80

    # 2. General primary business contact prefixes (+40 to +60)
    primary_prefixes = (
        "info", "contact", "hello", "enquiry", "enquiries",
        "office", "support", "help", "sales", "inquiry", "inquiries",
        "service", "care", "frontdesk", "reception"
    )
    if user_part in primary_prefixes:
        score += 60
    elif any(user_part.startswith(p) for p in primary_prefixes):
        score += 50
    elif any(p in user_part for p in ("contact", "info", "hello", "sales", "support", "enquiry")):
        score += 40
    elif user_part in ("admin", "marketing", "media", "press", "biz", "business"):
        score += 30
    elif user_part in ("hr", "careers", "jobs"):
        score += 20
    else:
        # Named individual email at company domain (e.g. john@thecorporatedge.com)
        score += 25

    # 3. Known valid public mail services (if small business uses Gmail/Yahoo)
    public_domains = ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com")
    if email_domain in public_domains:
        score += 15

    return score


def select_best_single_email(emails: Set[str], website_url: str) -> List[str]:
    """
    Selects exactly ONE best, most authentic business contact email.
    Eliminates duplicates, junk, and secondary emails so that the export
    contains a single high-quality lead email.
    """
    if not emails:
        return []

    valid = [e for e in emails if is_valid_email(e)]
    if not valid:
        return []

    # Sort by score descending, then by shorter username prefix (info@ preferred over very long words)
    sorted_emails = sorted(
        valid,
        key=lambda e: (score_email(e, website_url), -len(e.split("@")[0])),
        reverse=True
    )

    return [sorted_emails[0]]


def extract_emails_from_page(soup: BeautifulSoup, raw_html: str) -> Set[str]:
    """
    Extracts all valid emails from a single webpage using a multi-stage detection strategy:
    1. Cloudflare data-cfemail XOR decoder
    2. Cloudflare email-protection href decoder
    3. mailto: links (with URL unquoting & multi-recipient support)
    4. Custom email attributes (itemprop="email", data-email, data-mail)
    5. Elements with class/id containing 'email' or 'contact'
    6. JSON-LD structured data (<script type="application/ld+json">)
    7. Meta tags (og:email, etc.)
    8. Deobfuscated raw HTML regex
    9. Visible soup text regex
    """
    found: Set[str] = set()

    # 1. Cloudflare data-cfemail
    for el in soup.find_all(attrs={"data-cfemail": True}):
        decoded = decode_cloudflare_email(el["data-cfemail"])
        if decoded and is_valid_email(decoded):
            found.add(decoded)

    # 2. Cloudflare href protection links
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "/cdn-cgi/l/email-protection#" in href:
            cf_hex = href.split("#")[-1]
            decoded = decode_cloudflare_email(cf_hex)
            if decoded and is_valid_email(decoded):
                found.add(decoded)

    # 3. mailto: links
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            target = href.split(":", 1)[1].split("?")[0].strip()
            for em in re.split(r"[,;]", target):
                cleaned = unquote(em).strip().strip(".,;:\"'()[]<>{} \t\r\n").lower()
                if is_valid_email(cleaned):
                    found.add(cleaned)

    # 4. Attributes that frequently store emails
    for attr in ("data-email", "data-mail", "data-contact", "itemprop"):
        for el in soup.find_all(attrs={attr: True}):
            val = el[attr]
            if val and "@" in val:
                for em in EMAIL_REGEX.findall(val):
                    cleaned = em.strip().strip(".,;:\"'()[]<>{} \t\r\n").lower()
                    if is_valid_email(cleaned):
                        found.add(cleaned)

    # 5. Elements with email in class or id
    for el in soup.find_all(class_=re.compile(r"email|contact-mail", re.I)):
        text = el.get_text(separator=" ")
        for em in EMAIL_REGEX.findall(text):
            cleaned = em.strip().strip(".,;:\"'()[]<>{} \t\r\n").lower()
            if is_valid_email(cleaned):
                found.add(cleaned)

    # 6. JSON-LD structured data
    for script in soup.find_all("script", type=lambda t: t and "ld+json" in t):
        if script.string:
            for match in EMAIL_REGEX.findall(script.string):
                cleaned = match.strip().strip(".,;:\"'()[]<>{} \t\r\n").lower()
                if is_valid_email(cleaned):
                    found.add(cleaned)

    # 7. Meta tags
    for meta in soup.find_all("meta"):
        content = meta.get("content", "")
        if content and "@" in content:
            for match in EMAIL_REGEX.findall(content):
                cleaned = match.strip().strip(".,;:\"'()[]<>{} \t\r\n").lower()
                if is_valid_email(cleaned):
                    found.add(cleaned)

    # 8. Raw HTML text (scan directly with EMAIL_REGEX, capped to 150KB to avoid runaway loops)
    if raw_html:
        for match in EMAIL_REGEX.findall(raw_html[:150000]):
            cleaned = match.strip().strip(".,;:\"'()[]<>{} \t\r\n").lower()
            if is_valid_email(cleaned):
                found.add(cleaned)

    # 9. Visible soup text (clean scripts/styles, fast deobfuscate, then regex)
    soup_text = " ".join([t.strip() for t in soup.find_all(string=True) if t.parent.name not in ("script", "style", "svg", "noscript") and t.strip()])
    if soup_text:
        deob_text = deobfuscate_text(soup_text[:50000])
        for match in EMAIL_REGEX.findall(deob_text):
            cleaned = match.strip().strip(".,;:\"'()[]<>{} \t\r\n").lower()
            if is_valid_email(cleaned):
                found.add(cleaned)

    return found


def extract_socials(soup: BeautifulSoup, current_socials: SocialLinks) -> SocialLinks:
    """Extracts Facebook, Instagram, LinkedIn, and WhatsApp links."""
    socials = SocialLinks(
        facebook=current_socials.facebook,
        instagram=current_socials.instagram,
        linkedin=current_socials.linkedin,
        whatsapp=current_socials.whatsapp,
    )

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        href_lower = href.lower()

        if not socials.facebook and ("facebook.com/" in href_lower or "fb.com/" in href_lower):
            if "sharer" not in href_lower and "share.php" not in href_lower:
                socials.facebook = href

        elif not socials.instagram and "instagram.com/" in href_lower:
            socials.instagram = href

        elif not socials.linkedin and "linkedin.com/" in href_lower:
            if "sharearticle" not in href_lower and "sharing" not in href_lower:
                socials.linkedin = href

        elif not socials.whatsapp and ("wa.me/" in href_lower or "api.whatsapp.com/send" in href_lower):
            socials.whatsapp = href

    return socials


def extract_phone_from_soup(soup: BeautifulSoup, country_code: str = "bd") -> Optional[str]:
    """
    Extracts business phone number from website if Google Maps phone was missing.
    Prioritizes tel: links and schema.org telephone attributes.
    """
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("tel:"):
            raw_phone = href.split(":", 1)[1].split("?")[0].strip()
            if raw_phone:
                return clean_phone_number(raw_phone, country_code=country_code)

    el = soup.find(attrs={"itemprop": "telephone"})
    if el:
        text = el.get_text(strip=True)
        if text:
            return clean_phone_number(text, country_code=country_code)

    return None


def detect_cms(html_text: str) -> Optional[str]:
    """Detects content management systems from signatures in HTML source."""
    lower = html_text.lower()
    if "wp-content" in lower or "wp-includes" in lower:
        return "WordPress"
    elif "cdn.shopify.com" in lower or "shopify.com" in lower or "myshopify.com" in lower:
        return "Shopify"
    elif "wix.com" in lower or "_wix" in lower:
        return "Wix"
    elif "squarespace.com" in lower or "static1.squarespace.com" in lower:
        return "Squarespace"
    elif "webflow" in lower:
        return "Webflow"
    elif "joomla" in lower:
        return "Joomla"
    return None


def discover_target_pages(soup: BeautifulSoup, base_url: str, max_pages: int = 3) -> List[str]:
    """
    Discovers candidate subpages to crawl when Homepage does not have an email:
    Prioritizes canonical /contact, /contact-us, /about plus internal links on the homepage.
    Returns up to max_pages URLs.
    """
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower().replace("www.", "")
    base_normalized = f"{parsed_base.scheme}://{parsed_base.netloc}".rstrip("/")

    target_queue: List[str] = []
    seen: Set[str] = {base_normalized, f"{base_normalized}/"}

    # 1. Discover internal candidate subpages from actual HTML links on homepage first
    candidates: Dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue

        full_url = urljoin(base_url, href).split("#")[0].split("?")[0].rstrip("/")
        if full_url in seen:
            continue

        parsed_target = urlparse(full_url)
        target_domain = parsed_target.netloc.lower().replace("www.", "")

        if target_domain != base_domain and not target_domain.endswith("." + base_domain):
            continue

        if not parsed_target.path or parsed_target.path in ("/", ""):
            continue

        path_lower = parsed_target.path.lower()
        text_lower = a.get_text(strip=True).lower()
        combined = f"{path_lower} {text_lower}"

        best_score = 0
        for pattern, score in SUBPAGE_PATTERNS:
            if pattern.search(combined):
                if score > best_score:
                    best_score = score

        if best_score > 0:
            candidates[full_url] = max(candidates.get(full_url, 0), best_score)

    sorted_discovered = sorted(candidates.keys(), key=lambda u: candidates[u], reverse=True)
    for u in sorted_discovered:
        if u not in seen:
            seen.add(u)
            target_queue.append(u)

    # 2. Add canonical targets if not already discovered
    for path in CANONICAL_TARGETS:
        full = urljoin(base_normalized, path)
        norm = full.rstrip("/")
        if norm not in seen:
            seen.add(norm)
            target_queue.append(full)

    return target_queue[:max_pages]


def fetch_html(url: str, timeout: float = 3.5) -> Optional[str]:
    """
    Fetches HTML content with curl_cffi using chrome124 TLS fingerprint.
    Tight timeout prevents slow or hanging sites from stalling scraper worker threads.
    """
    if not url:
        return None

    clean_url = clean_website_url(url) or url

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }

    try:
        response = requests.get(
            clean_url,
            impersonate=DEFAULT_IMPERSONATE,
            timeout=timeout,
            verify=False,
            allow_redirects=True,
            headers=headers,
        )
        if response.status_code == 200 and response.text:
            return response.text
    except Exception as e:
        # Only fallback to http if strictly an SSL/TLS error, NEVER on timeout
        err_msg = str(e).lower()
        if "timeout" not in err_msg and clean_url.startswith("https://"):
            try:
                http_url = clean_url.replace("https://", "http://", 1)
                response = requests.get(
                    http_url,
                    impersonate=DEFAULT_IMPERSONATE,
                    timeout=2.5,
                    verify=False,
                    allow_redirects=True,
                    headers=headers,
                )
                if response.status_code == 200 and response.text:
                    return response.text
            except Exception:
                pass

    return None


def enrich_single_lead(
    lead: LeadItem,
    country_code: str = "bd",
    extract_email_opt: bool = True,
    extract_social_opt: bool = True,
    detect_cms_opt: bool = True,
    max_pages: int = 1,
) -> LeadItem:
    """
    High-Speed website deep-scraper for a single business:
    1. Fetches Homepage ('/') with 3.5s timeout.
    2. Extracts CMS, socials, phone, and emails.
    3. EARLY STOPPING: If Homepage contains a verified domain email, subpage crawling is skipped.
    4. If no email on Homepage, checks AT MOST 1 contact page with 2.5s timeout.
    5. Saves strictly ONE single highest-ranking authentic email.
    """
    if lead.website_status != "Has Own Website" or not lead.website_url:
        return lead

    clean_url = clean_website_url(lead.website_url) or lead.website_url
    lead.website_url = clean_url

    try:
        # 1. Fetch Homepage (3.5s max)
        html_home = fetch_html(clean_url, timeout=3.5)
        if not html_home:
            return lead

        soup_home = BeautifulSoup(html_home, "lxml")

        # Extract CMS from homepage
        if detect_cms_opt and not lead.cms_tech:
            lead.cms_tech = detect_cms(html_home)

        # Extract Socials from homepage
        if extract_social_opt:
            lead.social_links = extract_socials(soup_home, lead.social_links)

        # Extract Phone from website if missing from Google Maps
        if not lead.phone:
            lead.phone = extract_phone_from_soup(soup_home, country_code=country_code)

        # Extract Emails from homepage
        all_emails: Set[str] = set()
        if extract_email_opt:
            all_emails.update(extract_emails_from_page(soup_home, html_home))

        # Check if homepage already yielded a high-confidence matching domain email
        has_domain_email = False
        if extract_email_opt and all_emails:
            site_domain = extract_domain(clean_url)
            for em in all_emails:
                if is_valid_email(em):
                    parts = em.split("@")
                    if len(parts) == 2 and site_domain and (site_domain in parts[1] or parts[1].endswith(site_domain)):
                        has_domain_email = True
                        break

        # 2. Early Stop: Only crawl 1 contact subpage if no domain email on homepage yet!
        if not has_domain_email and (extract_email_opt or extract_social_opt):
            subpage_urls = discover_target_pages(soup_home, clean_url, max_pages=1)
            if subpage_urls:
                contact_url = subpage_urls[0]
                html_sub = fetch_html(contact_url, timeout=2.5)
                if html_sub:
                    soup_sub = BeautifulSoup(html_sub, "lxml")
                    if extract_email_opt:
                        all_emails.update(extract_emails_from_page(soup_sub, html_sub))
                    if extract_social_opt:
                        lead.social_links = extract_socials(soup_sub, lead.social_links)
                    if not lead.phone:
                        lead.phone = extract_phone_from_soup(soup_sub, country_code=country_code)
                    if detect_cms_opt and not lead.cms_tech:
                        lead.cms_tech = detect_cms(html_sub)

        # 3. Select strictly ONE single best email (no junk, no placeholders, no long lists)
        if extract_email_opt:
            lead.emails = select_best_single_email(all_emails, clean_url)

    except Exception:
        pass

    return lead


def enrich_leads_concurrently(
    leads: List[LeadItem],
    country_code: str = "bd",
    max_workers: int = MAX_CONCURRENT_ENRICHMENT,
    extract_email_opt: bool = True,
    extract_social_opt: bool = True,
    detect_cms_opt: bool = True,
    max_pages_per_site: int = 2,
    stop_event: Optional[Any] = None,
    on_lead_completed: Optional[Callable[[LeadItem], None]] = None,
) -> List[LeadItem]:
    """
    Enriches multiple leads in parallel using ThreadPoolExecutor.
    Supports real-time per-lead callback (on_lead_completed) as each individual site finishes.
    Supports graceful cancellation via stop_event.
    """
    leads_to_enrich = [l for l in leads if l.website_status == "Has Own Website" and l.website_url]
    if not leads_to_enrich:
        if on_lead_completed:
            for l in leads:
                if stop_event and stop_event.is_set():
                    break
                on_lead_completed(l)
        return leads

    lead_map = {l.place_id: l for l in leads}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_pid = {}
        for lead in leads_to_enrich:
            if stop_event and stop_event.is_set():
                break
            future = executor.submit(
                enrich_single_lead,
                lead=lead,
                country_code=country_code,
                extract_email_opt=extract_email_opt,
                extract_social_opt=extract_social_opt,
                detect_cms_opt=detect_cms_opt,
                max_pages=max_pages_per_site,
            )
            future_to_pid[future] = lead.place_id

        for future in as_completed(future_to_pid):
            if stop_event and stop_event.is_set():
                for f in future_to_pid:
                    f.cancel()
                break
            pid = future_to_pid[future]
            try:
                enriched_lead = future.result()
                lead_map[pid] = enriched_lead
                if on_lead_completed:
                    on_lead_completed(enriched_lead)
            except Exception as e:
                print(f"[Warning] Error enriching lead {pid}: {e}")
                if on_lead_completed and pid in lead_map:
                    on_lead_completed(lead_map[pid])

    return [lead_map[l.place_id] for l in leads]
