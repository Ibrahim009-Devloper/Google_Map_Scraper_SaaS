"""
Grounded AI Audit Generator for White-Label Agency Reports.
Converts structured SEO findings and selected audit sections into
evidence-backed, client-ready agency audits with a 100% reliable rule-based fallback.
"""

import json
import re
import datetime
from typing import Optional, List, Dict, Any

from config import (
    GEMINI_API_KEY,
    GROQ_API_KEY,
    DEFAULT_LLM_PROVIDER,
    GEMINI_MODEL,
    GROQ_MODEL,
)
from backend.seo_audit.models import (
    AuditInput,
    SEOReport,
    AuditSectionConfig,
    AgencyBranding,
    CompetitorComparison,
    PageSpeedResult,
    ActionPlanItem,
    AIAuditReport,
)
from backend.seo_audit.auditor import audit_single_business


def _classify_issue_category(check_key: str) -> str:
    """Maps audit check names to high-level report categories."""
    check_lower = check_key.lower()
    if any(k in check_lower for k in ("ssl", "canonical", "robots", "sitemap", "ttfb", "status", "http")):
        return "technical_seo"
    elif any(k in check_lower for k in ("mobile", "pagespeed", "speed", "vitals", "lcp")):
        return "pagespeed_mobile"
    elif any(k in check_lower for k in ("tracking", "analytics", "pixel", "gtm", "ga4", "ads")):
        return "ads_tracking"
    elif any(k in check_lower for k in ("inner", "sitemap_pages", "content_freshness", "blog", "service_pages")):
        return "inner_pages"
    else:
        return "onpage_seo"


def _get_plain_english_meaning(check_name: str, status: str, evidence: str) -> Dict[str, str]:
    """Provides client-friendly plain English explanation and business impact for an issue."""
    c_lower = check_name.lower()
    if "ssl" in c_lower:
        return {
            "check": check_name,
            "meaning": "Your website traffic is not securely redirected to HTTPS, causing modern browsers to show security warnings to prospective clients.",
            "impact": "High drop-off rate as visitors are scared away by 'Not Secure' browser warnings; Google also penalizes non-secure pages.",
            "recommendation": "Configure a permanent 301 redirect rule from HTTP to HTTPS across all domain URLs and renew SSL certificate."
        }
    elif "canonical" in c_lower:
        return {
            "check": check_name,
            "meaning": "Search engines are confused about which page is the official, authoritative version of your website.",
            "impact": "Dilutes search authority and can lead to incorrect or duplicate search results in Google rankings.",
            "recommendation": "Add a self-referencing rel='canonical' tag in the <head> section pointing to the exact preferred URL."
        }
    elif "title" in c_lower:
        return {
            "check": check_name,
            "meaning": "Your webpage title is missing, malformed, or doesn't mention your core business service.",
            "impact": "The title tag is the #1 on-page ranking factor and the main headline people click in Google search results.",
            "recommendation": "Craft a 50-60 character title containing your core service, primary city, and company name."
        }
    elif "h1" in c_lower:
        return {
            "check": check_name,
            "meaning": "Your page lacks a clear primary headline (H1 tag) that tells visitors and search engines what service you provide.",
            "impact": "Hurts keyword relevance and makes it harder for Google to understand your primary service offering.",
            "recommendation": "Add exactly one descriptive H1 tag near the top of the page summarizing your core service."
        }
    elif "meta_description" in c_lower:
        return {
            "check": check_name,
            "meaning": "Your search result preview snippet (meta description) is missing or suboptimal.",
            "impact": "Google may generate an unflattering or disjointed text snippet, reducing clicks from potential customers.",
            "recommendation": "Write a compelling 120-160 character description with a clear call-to-action and phone number."
        }
    elif "nap" in c_lower or "phone" in c_lower:
        return {
            "check": check_name,
            "meaning": "Your contact information (Name, Address, Phone) on the website does not match your Google Business Profile.",
            "impact": "Creates distrust with search algorithms and causes confused local customers to call competitors instead.",
            "recommendation": "Display your verified phone number and physical address prominently in the header and footer."
        }
    elif "schema" in c_lower:
        return {
            "check": check_name,
            "meaning": "Your website lacks structured LocalBusiness Schema markup that helps search engines understand your business details.",
            "impact": "Misses out on rich search result snippets (star ratings, operating hours, service areas) in Google search.",
            "recommendation": "Implement JSON-LD LocalBusiness Schema with your name, address, phone, opening hours, and geo-coordinates."
        }
    elif "category" in c_lower:
        return {
            "check": check_name,
            "meaning": "Your website's main heading and title do not clearly match your verified Google Maps business category.",
            "impact": "Reduces ranking power for high-intent search queries related to your primary trade or specialty.",
            "recommendation": "Incorporate your primary trade category prominently in the Title tag and page headings."
        }
    elif "ttfb" in c_lower or "speed" in c_lower:
        return {
            "check": check_name,
            "meaning": "Your server took a long time to respond before beginning to load the website.",
            "impact": "Slow load speeds cause mobile visitors to bounce immediately before seeing your services.",
            "recommendation": "Implement server-level caching, optimize database queries, or migrate to a high-speed hosting provider / CDN."
        }
    elif "mobile" in c_lower:
        return {
            "check": check_name,
            "meaning": "Your website does not have a properly configured viewport meta tag for mobile devices.",
            "impact": "Over 65% of local searches happen on mobile phones. A poor mobile layout severely hurts Google mobile rankings.",
            "recommendation": "Add '<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">' and ensure responsive CSS."
        }
    elif "word_count" in c_lower:
        return {
            "check": check_name,
            "meaning": "The page has relatively low visible text content compared to industry standards.",
            "impact": "Search engines have difficulty ranking pages with very little text for diverse keyword searches.",
            "recommendation": "Expand your homepage copy to 350+ words describing your services, service areas, and customer testimonials."
        }
    elif "image_alt" in c_lower:
        return {
            "check": check_name,
            "meaning": "Images on your website are missing descriptive alternative (alt) text.",
            "impact": "Misses Google Image search traffic and reduces accessibility for visually impaired users.",
            "recommendation": "Add concise, descriptive alt attributes to all content images describing what is shown."
        }
    else:
        return {
            "check": check_name,
            "meaning": f"Identified issue: {evidence}",
            "impact": "Negatively affects overall local search visibility and user conversion rate.",
            "recommendation": f"Review and resolve: {evidence}"
        }


def generate_fallback_ai_report(
    audit_input: AuditInput,
    seo_report: SEOReport,
    sections: AuditSectionConfig,
    branding: AgencyBranding,
    competitors: Optional[List[CompetitorComparison]] = None,
    pagespeed: Optional[PageSpeedResult] = None,
) -> AIAuditReport:
    """
    100% deterministic, grounded rule-based report generator.
    Guarantees evidence-only findings, no hallucinations, and strict section filtering.
    """
    biz_name = audit_input.business_name or seo_report.extracted_title or "Local Business"
    category = audit_input.category or "Local Service Business"
    city = audit_input.get_primary_city()
    location_str = f"{city}, {audit_input.address}" if (city and audit_input.address) else (city or audit_input.address or "Local Area")
    today_str = datetime.date.today().strftime("%B %d, %Y")

    # Build Audit Scope list based on selected sections
    audit_scope = []
    if sections.technical_seo:
        audit_scope.append("Website Technical SEO")
    if sections.onpage_seo:
        audit_scope.append("On-Page & Local SEO")
    if sections.competitor_research:
        audit_scope.append("Competitor Gap Research")
    if sections.pagespeed_mobile:
        audit_scope.append("PageSpeed & Mobile Experience")
    if sections.ads_tracking:
        audit_scope.append("Tracking & Marketing Analytics")
    if sections.inner_pages:
        audit_scope.append("Content & Architecture")

    # Filter issues according to selected sections
    critical_issues: List[str] = []
    warnings: List[str] = []
    passed_checks: List[str] = []
    explanations: List[Dict[str, str]] = []
    data_limitations: List[str] = []
    action_plan: List[ActionPlanItem] = []

    # Handle client-side rendered / JS-SPA site limitation
    if seo_report.is_js_rendered:
        data_limitations.append(
            "Client-Side Rendered (JS/SPA) Architecture: The website serves an empty HTML shell dynamically populated by JavaScript. "
            "Standard crawler checks were skipped or marked unverified to avoid false penalties; manual browser inspection is recommended."
        )

    for key, issue in seo_report.issues.items():
        category_group = _classify_issue_category(issue.check_name)

        # Skip issue if section not selected
        if category_group == "technical_seo" and not sections.technical_seo:
            continue
        if category_group == "onpage_seo" and not sections.onpage_seo:
            continue
        if category_group == "pagespeed_mobile" and not sections.pagespeed_mobile:
            continue
        if category_group == "ads_tracking" and not sections.ads_tracking:
            continue
        if category_group == "inner_pages" and not sections.inner_pages:
            continue

        # Check for unreadable/unverified data limitations
        if issue.audit_status == "Unverified" or "Could Not Read" in issue.evidence or "Not Checked" in issue.evidence:
            data_limitations.append(f"{issue.check_name}: {issue.evidence}")
            continue

        if issue.audit_status == "Pass":
            passed_checks.append(f"{issue.check_name}: {issue.evidence}")
        elif issue.severity in ("Critical", "High") or issue.audit_status == "Fail":
            critical_issues.append(f"{issue.check_name}: {issue.evidence}")
            explanations.append(_get_plain_english_meaning(issue.check_name, issue.audit_status, issue.evidence))
            # Map into Action Plan
            action_plan.append(ActionPlanItem(
                title=f"Resolve {issue.check_name}",
                timeframe="Quick Win (1-7 Days)",
                priority="Critical" if issue.severity == "Critical" else "High",
                category="Technical SEO" if category_group == "technical_seo" else "On-Page SEO",
                impact=issue.recommended_fix or "Direct improvement in search visibility and user trust.",
                description=issue.evidence
            ))
        elif issue.audit_status == "Warning" or issue.severity == "Medium":
            warnings.append(f"{issue.check_name}: {issue.evidence}")
            explanations.append(_get_plain_english_meaning(issue.check_name, issue.audit_status, issue.evidence))
            action_plan.append(ActionPlanItem(
                title=f"Optimize {issue.check_name}",
                timeframe="Medium-Term (2-4 Weeks)",
                priority="Medium",
                category="Technical SEO" if category_group == "technical_seo" else "On-Page SEO",
                impact=issue.recommended_fix or "Strengthens competitive relevance and ranking stability.",
                description=issue.evidence
            ))

    # Add strategic long-term action plan items if applicable
    if sections.onpage_seo:
        action_plan.append(ActionPlanItem(
            title="Local Review & Reputation Growth Engine",
            timeframe="Long-Term (1-3 Months)",
            priority="Medium",
            category="Local SEO & Reputation",
            impact="Systematically increases Google Maps pack ranking through sustained positive customer reviews.",
            description="Establish an automated SMS/email review invitation workflow for verified customers."
        ))

    # PageSpeed / Mobile data handling
    if sections.pagespeed_mobile:
        if pagespeed and pagespeed.status != "Unavailable" and pagespeed.status != "Not Checked":
            if pagespeed.mobile_score is not None and pagespeed.mobile_score < 50:
                critical_issues.append(f"Mobile Performance Score: Critical ({pagespeed.mobile_score}/100)")
                action_plan.append(ActionPlanItem(
                    title="Optimize Core Web Vitals & Mobile Speed",
                    timeframe="Medium-Term (2-4 Weeks)",
                    priority="High",
                    category="Mobile Performance",
                    impact="Reduces mobile bounce rates and satisfies Google Page Experience algorithm.",
                    description=pagespeed.details or f"Mobile performance scored {pagespeed.mobile_score}/100."
                ))
            elif pagespeed.mobile_score is not None and pagespeed.mobile_score < 80:
                warnings.append(f"Mobile Performance Score: Moderate ({pagespeed.mobile_score}/100)")
            elif pagespeed.mobile_score is not None:
                passed_checks.append(f"Mobile Performance Score: Excellent ({pagespeed.mobile_score}/100)")
        else:
            data_limitations.append("Google PageSpeed Insights: Metric unavailable or API key not configured; fallback HTTP checks used.")

    # Competitor research handling
    competitor_gap_summary = None
    competitors_list: List[CompetitorComparison] = []
    if sections.competitor_research:
        if competitors:
            competitors_list = competitors
            # Build competitor gap analysis text
            gaps = []
            target_rating = audit_input.rating or 0.0
            target_reviews = audit_input.reviews_count or 0
            for comp in competitors[:3]:
                if comp.reviews_count and comp.reviews_count > target_reviews:
                    diff = comp.reviews_count - target_reviews
                    gaps.append(f"{comp.business_name} has {comp.reviews_count} reviews (+{diff} more than you)")
                if comp.has_schema and not any("schema" in p.lower() for p in passed_checks):
                    gaps.append(f"{comp.business_name} has structured Schema markup implemented")
            
            if gaps:
                competitor_gap_summary = (
                    f"In {city or 'the local area'}, key competitors hold measurable advantages: "
                    + "; ".join(gaps[:3])
                    + ". Bridging these gaps will directly lift Google 3-Pack placement."
                )
            else:
                competitor_gap_summary = (
                    f"Analyzed {len(competitors)} local competitors in {city or 'your area'}. "
                    "Your business maintains competitive review volume; primary upside lies in technical on-page authority."
                )
        else:
            competitor_gap_summary = "Local competitor benchmark pool not available for this immediate zone."
            data_limitations.append("Competitor Discovery: Scraped local pool did not yield comparable competitors in this sector.")

    # Craft Agency Executive Summary
    score_val = seo_report.seo_health_score
    score_display = f"{score_val}/100" if score_val is not None else "N/A (JS-Rendered)"

    if seo_report.is_js_rendered:
        executive_summary = (
            f"This audit evaluated the online visibility and search foundation of {biz_name} in {location_str}. "
            f"The website utilizes a modern JavaScript framework that renders content client-side. "
            f"While this provides interactive user interfaces, it requires special search engine indexing considerations. "
            f"We have outlined the immediate technical and local visibility priorities to ensure search bots index your business accurately."
        )
    elif score_val is not None and score_val >= 85:
        executive_summary = (
            f"Executive assessment conducted by {branding.agency_name} for {biz_name} ({category}) in {location_str}. "
            f"The website demonstrates a solid baseline technical health score of {score_display}. "
            f"Core structural elements are largely intact. The primary opportunity lies in fine-tuning competitive local differentiators: "
            f"addressing remaining warning signals, capturing rich snippet real estate via advanced schema, and outpacing local competitors in review velocity."
        )
    elif score_val is not None and score_val >= 60:
        executive_summary = (
            f"Prepared by {branding.agency_name} for {biz_name}. "
            f"Our technical audit identified that the business is currently operating at a {score_display} SEO Health Score, "
            f"leaving significant qualified customer search volume on the table in {location_str}. "
            f"We detected {len(critical_issues)} critical priority bottlenecks and {len(warnings)} moderate warnings. "
            f"By executing the prioritized roadmap below, {biz_name} can rapidly eliminate conversion drop-offs and improve local Map Pack placement."
        )
    else:
        executive_summary = (
            f"Urgent digital performance review prepared by {branding.agency_name} for {biz_name}. "
            f"The website's current SEO Health Score is {score_display}, indicating foundational technical and structural deficits "
            f"that directly impair local organic discovery and lead capture in {location_str}. "
            f"Key friction points—including {len(critical_issues)} critical items—require immediate remediation to prevent prospective customers from reaching competitors."
        )

    return AIAuditReport(
        business_name=biz_name,
        category=category,
        website_url=audit_input.url,
        audited_url=seo_report.final_url or audit_input.url,
        location=location_str,
        audit_date=today_str,
        seo_health_score=seo_report.seo_health_score,
        audit_scope=audit_scope,
        executive_summary=executive_summary,
        critical_issues=critical_issues,
        warnings=warnings,
        passed_checks=passed_checks,
        plain_english_explanations=explanations,
        action_plan=action_plan,
        competitor_analysis=competitor_gap_summary,
        competitors=competitors_list,
        pagespeed_data=pagespeed,
        data_limitations=data_limitations,
        branding=branding,
        raw_seo_report=seo_report,
    )


def generate_ai_audit_report(
    audit_input: AuditInput,
    seo_report: Optional[SEOReport] = None,
    sections: Optional[AuditSectionConfig] = None,
    branding: Optional[AgencyBranding] = None,
    competitors: Optional[List[CompetitorComparison]] = None,
    pagespeed: Optional[PageSpeedResult] = None,
) -> AIAuditReport:
    """
    Main entry point: Generates a complete, client-ready agency AI SEO report.
    Uses LLM (Gemini or Groq) when configured to polish copy, with guaranteed 100% rule-based fallback.
    """
    if seo_report is None:
        seo_report = audit_single_business(audit_input)

    if sections is None:
        sections = AuditSectionConfig()

    if branding is None:
        branding = AgencyBranding()

    # Always generate rule-based grounded report first
    base_report = generate_fallback_ai_report(
        audit_input=audit_input,
        seo_report=seo_report,
        sections=sections,
        branding=branding,
        competitors=competitors,
        pagespeed=pagespeed,
    )

    # If LLM API key is present, attempt LLM refinement of the executive summary & recommendations
    api_key = GEMINI_API_KEY if DEFAULT_LLM_PROVIDER == "gemini" else GROQ_API_KEY
    if not api_key:
        api_key = GEMINI_API_KEY or GROQ_API_KEY

    if not api_key:
        return base_report

    try:
        prompt_data = {
            "business_name": base_report.business_name,
            "category": base_report.category,
            "location": base_report.location,
            "seo_health_score": base_report.seo_health_score,
            "critical_issues": base_report.critical_issues,
            "warnings": base_report.warnings,
            "passed_checks": base_report.passed_checks,
            "audit_scope": base_report.audit_scope,
            "competitor_summary": base_report.competitor_analysis,
            "agency_name": branding.agency_name,
        }

        system_instruction = (
            "You are a Senior SEO Strategist writing an executive client presentation for a local business. "
            "STRICT RULES:\n"
            "1. Grounding: You must ONLY refer to the issues and facts provided in the JSON input. NEVER invent, hallucinate, or assume issues not explicitly provided.\n"
            "2. Unselected Sections: Do not mention topics outside the provided audit_scope.\n"
            "3. Tone: Professional, authoritative, actionable, client-ready agency tone.\n"
            "4. Return strict JSON with exact keys: 'executive_summary' (string: 2-3 concise paragraphs) and 'action_plan_insights' (array of strings: key strategic takeaways)."
        )

        user_content = f"Generate an executive agency summary for this business:\n{json.dumps(prompt_data, ensure_ascii=False)}"

        if DEFAULT_LLM_PROVIDER == "gemini" and GEMINI_API_KEY:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=user_content,
                config=dict(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0.2,
                )
            )
            raw_text = resp.text or ""
        elif GROQ_API_KEY:
            from groq import Groq
            client = Groq(api_key=GROQ_API_KEY)
            resp = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            raw_text = resp.choices[0].message.content or ""
        else:
            return base_report

        # Clean and parse LLM response
        text = raw_text.strip()
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if m:
            text = m.group(1).strip()
        parsed = json.loads(text)

        if "executive_summary" in parsed and parsed["executive_summary"].strip():
            base_report.executive_summary = parsed["executive_summary"].strip()

    except Exception:
        # Graceful fallback to rule-based report on any LLM network/format error
        pass

    return base_report
