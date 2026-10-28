"""
Verified-Findings-Only SEO Opportunity Score (0–100) Calculator.
Strictly excludes missing inputs and unverified checks from the calculation denominator.
"""

from typing import Dict, Optional
from seo_audit.models import AuditIssue
from seo_audit.config import SEO_CHECK_WEIGHTS


def calculate_seo_opportunity_score(issues: Dict[str, AuditIssue]) -> Optional[int]:
    """
    Calculates the SEO Opportunity Score (0–100) using strictly verified findings.

    Rules:
    - Pass: 0.0 * weight
    - Warning: 0.5 * weight
    - Fail: 1.0 * weight
    - Unverified: excluded from denominator completely

    Formula:
        Score = round((sum(opportunity_points) / sum(verified_weights)) * 100)

    Special Rules:
    - If verified_weight_sum == 0, returns None (rendered as "N/A" or "Unverified").
    - If a 'noindex' directive is detected on canonical_robots, enforces minimum score of 85.
    """
    opportunity_points = 0.0
    verified_weight_sum = 0.0
    has_noindex_block = False

    for check_name, weight in SEO_CHECK_WEIGHTS.items():
        issue = issues.get(check_name)
        if not issue:
            continue

        status = issue.audit_status
        if status not in ("Pass", "Warning", "Fail"):
            # Unverified or undefined status excluded from denominator
            continue

        verified_weight_sum += weight

        if status == "Pass":
            opportunity_points += 0.0 * weight
        elif status == "Warning":
            opportunity_points += 0.5 * weight
        elif status == "Fail":
            opportunity_points += 1.0 * weight

        # Detect critical noindex directive
        if check_name == "canonical_robots" and status == "Fail":
            evidence_lower = issue.evidence.lower()
            summary_lower = issue.xlsx_summary.lower()
            if "noindex" in evidence_lower or "noindex" in summary_lower:
                has_noindex_block = True

    if verified_weight_sum == 0.0:
        return None

    score = round((opportunity_points / verified_weight_sum) * 100)
    score = max(0, min(100, score))

    if has_noindex_block:
        score = max(score, 85)

    return int(score)
