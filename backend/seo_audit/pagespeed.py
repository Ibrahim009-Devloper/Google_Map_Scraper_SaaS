"""
Google PageSpeed Insights API Client for Agency-Grade Local SEO Audits (GEMINI2.md Phase 2).
Uses direct HTTP GET requests to runPagespeed v5 endpoint without browser automation.
Extracts Mobile and Desktop Performance scores (0-100), Core Web Vitals (LCP, CLS, INP/FCP),
mobile-friendliness signals, and Lighthouse viewport screenshot thumbnails.
Gracefully handles unconfigured API keys, rate limits, and network errors with 'Unavailable' / 'Not Checked'.
"""

import os
import re
import time
from typing import Optional, Dict, Any
from urllib.parse import quote
from pydantic import BaseModel, Field

try:
    from curl_cffi import requests
except ImportError:
    import requests

from backend.seo_audit.config import PAGESPEED_API_KEY

PAGESPEED_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
PAGESPEED_TIMEOUT = 8.0  # 8-second strict timeout


class CoreWebVitals(BaseModel):
    """Core Web Vitals metrics from Lighthouse."""
    lcp: str = Field(default="Unavailable", description="Largest Contentful Paint (e.g., '1.8 s')")
    cls: str = Field(default="Unavailable", description="Cumulative Layout Shift (e.g., '0.04')")
    inp: str = Field(default="Unavailable", description="Interaction to Next Paint (or FCP if unavailable)")
    fcp: str = Field(default="Unavailable", description="First Contentful Paint (e.g., '1.2 s')")


class PageSpeedStrategyResult(BaseModel):
    """Performance and Core Web Vitals for a single strategy (mobile or desktop)."""
    strategy: str = Field(description="'mobile' or 'desktop'")
    status: str = Field(default="Not Checked", description="'Pass', 'Warning', 'Critical', 'Unavailable', 'Not Checked'")
    performance_score: Optional[int] = Field(default=None, description="0-100 integer score or None if unavailable")
    core_web_vitals: CoreWebVitals = Field(default_factory=CoreWebVitals)
    is_mobile_friendly: Optional[bool] = Field(default=None, description="True if mobile viewport audit passed")
    screenshot_data_url: Optional[str] = Field(default=None, description="Base64 data URL of the Lighthouse screenshot thumbnail")
    diagnostics: str = Field(default="", description="Summary of audit findings or error details")
    error_message: Optional[str] = Field(default=None, description="Error reason if unavailable")


class PageSpeedAuditReport(BaseModel):
    """Combined Mobile and Desktop PageSpeed audit report."""
    url: str
    status: str = Field(default="Not Checked", description="'Completed', 'Unavailable', 'Not Checked'")
    mobile: PageSpeedStrategyResult
    desktop: PageSpeedStrategyResult
    audit_timestamp: Optional[str] = None


def fetch_pagespeed_strategy(
    url: str,
    strategy: str = "mobile",
    api_key: Optional[str] = None,
    timeout: float = PAGESPEED_TIMEOUT,
) -> PageSpeedStrategyResult:
    """
    Fetches PageSpeed Insights data for a specific strategy ('mobile' or 'desktop').
    Returns PageSpeedStrategyResult with 'Unavailable' / 'Not Checked' status if unconfigured or failed.
    Never raises an unhandled exception.
    """
    clean_url = (url or "").strip()
    if not clean_url or not clean_url.startswith(("http://", "https://")):
        return PageSpeedStrategyResult(
            strategy=strategy,
            status="Unavailable",
            diagnostics="Invalid or missing URL provided for PageSpeed audit",
            error_message="Invalid URL"
        )

    resolved_key = (api_key or PAGESPEED_API_KEY or os.getenv("PAGESPEED_API_KEY", "")).strip()
    params = [
        f"url={quote(clean_url, safe=':/?=&')}",
        f"strategy={strategy}",
        "category=performance",
    ]
    if resolved_key:
        params.append(f"key={resolved_key}")

    query_str = "&".join(params)
    api_url = f"{PAGESPEED_ENDPOINT}?{query_str}"

    headers = {
        "User-Agent": "LeadPulse-Agency-Auditor/2.0 (PageSpeed Client)",
        "Accept": "application/json",
    }

    try:
        resp = requests.get(api_url, headers=headers, timeout=timeout)
        if resp.status_code == 429:
            return PageSpeedStrategyResult(
                strategy=strategy,
                status="Unavailable",
                diagnostics="Google PageSpeed API rate limit reached (429)",
                error_message="Rate limit reached"
            )
        if resp.status_code == 400:
            return PageSpeedStrategyResult(
                strategy=strategy,
                status="Unavailable",
                diagnostics="Google PageSpeed API returned 400 (Site unreachable or blocked)",
                error_message="Site unreachable"
            )
        if resp.status_code != 200:
            return PageSpeedStrategyResult(
                strategy=strategy,
                status="Unavailable",
                diagnostics=f"PageSpeed API HTTP {resp.status_code}",
                error_message=f"HTTP {resp.status_code}"
            )

        data = resp.json()
        lighthouse = data.get("lighthouseResult", {})
        categories = lighthouse.get("categories", {})
        perf = categories.get("performance", {})
        raw_score = perf.get("score")

        perf_score = int(round(raw_score * 100)) if raw_score is not None else None

        # Determine status enum
        if perf_score is not None:
            if perf_score >= 90:
                status = "Pass"
            elif perf_score >= 50:
                status = "Warning"
            else:
                status = "Critical"
        else:
            status = "Unavailable"

        # Core Web Vitals
        audits = lighthouse.get("audits", {})
        lcp_val = audits.get("largest-contentful-paint", {}).get("displayValue", "Unavailable")
        cls_val = audits.get("cumulative-layout-shift", {}).get("displayValue", "Unavailable")
        fcp_val = audits.get("first-contentful-paint", {}).get("displayValue", "Unavailable")
        inp_val = audits.get("interaction-to-next-paint", {}).get("displayValue")
        if not inp_val or inp_val == "Unavailable":
            inp_val = audits.get("experimental-interaction-to-next-paint", {}).get("displayValue", fcp_val)

        cwv = CoreWebVitals(
            lcp=str(lcp_val),
            cls=str(cls_val),
            inp=str(inp_val),
            fcp=str(fcp_val)
        )

        # Mobile viewport check
        viewport_audit = audits.get("viewport", {})
        viewport_score = viewport_audit.get("score")
        is_mobile_friendly = (viewport_score == 1) if viewport_score is not None else None

        # Screenshot thumbnail
        screenshot_data = audits.get("final-screenshot", {}).get("details", {}).get("data")

        diag_parts = []
        if perf_score is not None:
            diag_parts.append(f"Score: {perf_score}/100")
        if lcp_val != "Unavailable":
            diag_parts.append(f"LCP: {lcp_val}")
        if cls_val != "Unavailable":
            diag_parts.append(f"CLS: {cls_val}")
        if strategy == "mobile" and is_mobile_friendly is not None:
            diag_parts.append("Mobile Viewport: Pass" if is_mobile_friendly else "Mobile Viewport: Missing")

        return PageSpeedStrategyResult(
            strategy=strategy,
            status=status,
            performance_score=perf_score,
            core_web_vitals=cwv,
            is_mobile_friendly=is_mobile_friendly,
            screenshot_data_url=screenshot_data,
            diagnostics=" | ".join(diag_parts) if diag_parts else "Audit completed",
        )

    except Exception as e:
        err_msg = str(e)
        return PageSpeedStrategyResult(
            strategy=strategy,
            status="Unavailable",
            diagnostics=f"PageSpeed request failed: {err_msg[:60]}",
            error_message=err_msg[:100]
        )


def audit_pagespeed(
    url: str,
    api_key: Optional[str] = None,
    check_desktop: bool = True,
    timeout: float = PAGESPEED_TIMEOUT,
) -> PageSpeedAuditReport:
    """
    Runs PageSpeed Insights for both Mobile and (optionally) Desktop.
    Returns complete PageSpeedAuditReport with guaranteed non-null sub-results.
    """
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    mobile_res = fetch_pagespeed_strategy(url, strategy="mobile", api_key=api_key, timeout=timeout)
    
    if check_desktop and mobile_res.status != "Unavailable":
        desktop_res = fetch_pagespeed_strategy(url, strategy="desktop", api_key=api_key, timeout=timeout)
    else:
        desktop_res = PageSpeedStrategyResult(
            strategy="desktop",
            status="Not Checked",
            diagnostics="Desktop audit skipped or mobile was unavailable"
        )

    overall_status = "Completed" if (mobile_res.status in ("Pass", "Warning", "Critical") or desktop_res.status in ("Pass", "Warning", "Critical")) else "Unavailable"
    if mobile_res.status == "Not Checked" and desktop_res.status == "Not Checked":
        overall_status = "Not Checked"

    return PageSpeedAuditReport(
        url=url,
        status=overall_status,
        mobile=mobile_res,
        desktop=desktop_res,
        audit_timestamp=timestamp
    )


def check_pagespeed(url: str, api_key: Optional[str] = None) -> Any:
    """Convenience bridge returning PageSpeedResult schema for API endpoints."""
    from backend.seo_audit.models import PageSpeedResult
    rep = audit_pagespeed(url, api_key=api_key)

    def _parse_float(val: str) -> Optional[float]:
        try:
            m = re.search(r"[\d\.]+", str(val))
            return float(m.group(0)) if m else None
        except Exception:
            return None

    return PageSpeedResult(
        mobile_score=rep.mobile.performance_score,
        desktop_score=rep.desktop.performance_score,
        lcp_seconds=_parse_float(rep.mobile.core_web_vitals.lcp),
        cls_value=_parse_float(rep.mobile.core_web_vitals.cls),
        inp_ms=_parse_float(rep.mobile.core_web_vitals.inp),
        fcp_seconds=_parse_float(rep.mobile.core_web_vitals.fcp),
        mobile_friendly_status="Pass" if rep.mobile.is_mobile_friendly else ("Fail" if rep.mobile.is_mobile_friendly is False else "Not Checked"),
        screenshot_url=rep.mobile.screenshot_data_url,
        status=rep.mobile.status if rep.mobile.status != "Not Checked" else rep.status,
        details=rep.mobile.diagnostics or rep.desktop.diagnostics or "",
    )
