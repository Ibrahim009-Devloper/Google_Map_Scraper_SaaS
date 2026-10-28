"""
SEO Health Score and Lead Pitch Priority Scorer (Section 2.5).
Calculates an intuitive, client-ready 0-100 Health Score (Higher = Better)
and categorizes lead pitch priority for cold outreach.
"""

from typing import Dict, Tuple, Optional
from backend.seo_audit.models import AuditIssue
from backend.seo_audit.config import SEO_CHECK_PENALTIES


def calculate_seo_health_and_pitch(
    issues: Dict[str, AuditIssue],
    has_website: bool = True,
    is_https: bool = True,
    business_rating: Optional[float] = None,
    reviews_count: Optional[int] = None,
) -> Tuple[Optional[int], str]:
    """
    Computes:
    1. SEO Health Score (0-100): 100 is pristine. Penalties deducted for verified flaws.
       Returns None if site is not tested or has no website.
    2. Lead Pitch Priority:
       - Critical Pitch (No Website)
       - Not Tested (if checks were unverified/unreachable)
       - Critical Pitch (for active indexing blockers or critical breakdowns)
       - High Value (for substantial actionable gaps or high-reputation businesses with missing local signals)
       - Moderate (medium on-page gaps)
       - Low Priority - Well Optimized (healthy sites)
    """
    if not has_website:
        return None, "Critical Pitch (No Website)"

    if not issues:
        return None, "Not Tested"

    penalties_incurred = 0
    verified_checks_count = 0
    active_noindex = False
    server_error = False

    for check_key, issue in issues.items():
        if issue.audit_status == "Unverified":
            continue

        verified_checks_count += 1
        base_penalty = SEO_CHECK_PENALTIES.get(check_key, 8)

        if issue.audit_status == "Fail":
            penalties_incurred += base_penalty
            if check_key == "meta_robots" and "noindex" in issue.evidence.lower():
                active_noindex = True
            if check_key == "final_url_status" and "http error" in issue.evidence.lower():
                server_error = True
        elif issue.audit_status == "Warning":
            penalties_incurred += round(base_penalty * 0.5)

    # If no checks could be verified (e.g. host unreachable or timed out), return None and "Not Tested"
    if verified_checks_count == 0:
        return None, "Not Tested"

    health_score = max(0, min(100, 100 - penalties_incurred))

    # Lead Pitch Priority: Decoupled commercial valuation (Stop marking 88/100 sites as Critical Pitch!)
    # Base Lead Pitch Priority strictly on SEO Health Score and true critical blockers (noindex or unencrypted HTTP):
    # - If noindex is present OR site is unencrypted HTTP OR score < 50: Critical Pitch
    # - Else if 50 <= score < 70: High Value
    # - Else if 70 <= score < 85: Moderate
    # - Else (score >= 85): Low Priority (Healthy Site)
    if active_noindex or not is_https or health_score < 50 or server_error:
        pitch_priority = "Critical Pitch"
    elif health_score < 70:
        pitch_priority = "High Value"
    elif health_score < 85:
        pitch_priority = "Moderate"
    else:
        pitch_priority = "Low Priority (Healthy Site)"

    return health_score, pitch_priority


# Backward compatibility alias
def calculate_seo_opportunity_score(issues: Dict[str, AuditIssue]) -> Optional[int]:
    """Legacy helper returning opportunity score (100 - health_score)."""
    health, _ = calculate_seo_health_and_pitch(issues)
    return (100 - health) if health is not None else None
