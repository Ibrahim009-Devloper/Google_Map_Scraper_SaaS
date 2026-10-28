"""
Fault-tolerant HTTP fetcher with Chrome TLS impersonation, response timing,
and automatic SSL fallback.
"""

import time
import logging
from typing import Optional, Dict
from dataclasses import dataclass, field
from urllib.parse import urlparse

from curl_cffi import requests
from curl_cffi.requests.errors import RequestsError

from seo_audit.config import SEO_AUDIT_TIMEOUT, SEO_AUDIT_MAX_RETRIES

logger = logging.getLogger("seo_audit")


@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    status_code: Optional[int] = None
    elapsed_seconds: Optional[float] = None
    html: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    error_message: Optional[str] = None
    ssl_failed: bool = False
    redirect_count: int = 0


def fetch_page_for_audit(
    url: str,
    timeout: int = SEO_AUDIT_TIMEOUT,
    max_retries: int = SEO_AUDIT_MAX_RETRIES,
) -> FetchResult:
    """
    Fetches a webpage using curl_cffi with Chrome TLS impersonation.
    Measures response time, catches errors gracefully, and automatically
    falls back to HTTP if HTTPS fails with an SSL verification error.
    """
    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    ssl_failed = False
    headers_to_send = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }

    current_url = clean_url
    for attempt in range(max(1, max_retries)):
        start_time = time.perf_counter()
        try:
            resp = requests.get(
                current_url,
                impersonate="chrome124",
                timeout=timeout,
                headers=headers_to_send,
                allow_redirects=True,
            )
            elapsed = round(time.perf_counter() - start_time, 2)
            final_url = str(getattr(resp, "url", current_url))
            headers_dict = {k.lower(): str(v) for k, v in getattr(resp, "headers", {}).items()}

            return FetchResult(
                url=clean_url,
                final_url=final_url,
                status_code=int(resp.status_code),
                elapsed_seconds=elapsed,
                html=resp.text or "",
                headers=headers_dict,
                ssl_failed=ssl_failed,
            )

        except (RequestsError, Exception) as exc:
            elapsed = round(time.perf_counter() - start_time, 2)
            err_str = str(exc)
            is_ssl_err = any(kw in err_str.lower() for kw in ["ssl", "certificate", "handshake", "tls"])

            # Automatic fallback to HTTP if HTTPS had an SSL error
            if is_ssl_err and current_url.startswith("https://") and not ssl_failed:
                logger.warning("SSL failure on %s (%s). Retrying with HTTP fallback.", current_url, err_str)
                current_url = "http://" + current_url[8:]
                ssl_failed = True
                continue

            if attempt < max_retries - 1 and not ("timed out" in err_str.lower() or "timeout" in err_str.lower()):
                time.sleep(0.5)
                continue

            logger.error("Audit fetch failed for %s: %s", clean_url, err_str)
            return FetchResult(
                url=clean_url,
                final_url=current_url,
                status_code=None,
                elapsed_seconds=elapsed,
                html="",
                headers={},
                error_message=err_str,
                ssl_failed=ssl_failed,
            )

    return FetchResult(
        url=clean_url,
        final_url=current_url,
        status_code=None,
        elapsed_seconds=None,
        html="",
        headers={},
        error_message="Max retries exhausted",
        ssl_failed=ssl_failed,
    )
