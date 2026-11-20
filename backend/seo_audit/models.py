"""
Pydantic data models and schemas for the Local SEO Audit Engine.
"""

import re
from typing import Optional, Dict, List, Literal, Any
from pydantic import BaseModel, Field

AuditStatus = Literal["Pass", "Warning", "Fail", "Unverified"]
Priority = Literal["Critical", "High", "Medium", "Low", "None"]
Confidence = Literal["High", "Medium", "Low", "Unverified"]

# Metro and neighborhood relationships for local SEO keyword matching
METRO_NEIGHBORHOOD_MAPPINGS: Dict[str, List[str]] = {
    # NYC
    "flushing": ["queens", "new york", "nyc", "new york city"],
    "astoria": ["queens", "new york", "nyc", "new york city"],
    "long island city": ["queens", "new york", "nyc", "new york city"],
    "jamaica": ["queens", "new york", "nyc", "new york city"],
    "brooklyn": ["new york", "nyc", "new york city", "kings county"],
    "williamsburg": ["brooklyn", "new york", "nyc", "new york city"],
    "manhattan": ["new york", "nyc", "new york city"],
    "harlem": ["manhattan", "new york", "nyc", "new york city"],
    "bronx": ["new york", "nyc", "new york city"],
    "staten island": ["new york", "nyc", "new york city"],
    "queens": ["new york", "nyc", "new york city"],
    # Los Angeles
    "hollywood": ["los angeles", "la"],
    "van nuys": ["los angeles", "la", "san fernando valley"],
    "north hollywood": ["los angeles", "la"],
    "santa monica": ["los angeles", "la"],
    "pasadena": ["los angeles", "la"],
    # Chicago
    "lincoln park": ["chicago"],
    "lakeview": ["chicago"],
    "evanston": ["chicago"],
    # Houston
    "woodlands": ["the woodlands", "houston"],
    "katy": ["houston"],
    "sugar land": ["houston"],
    # Miami
    "miami beach": ["miami", "south beach"],
    "coral gables": ["miami"],
    "doral": ["miami"],
    # Boston
    "brookline": ["boston", "greater boston"],
    "cambridge": ["boston", "greater boston"],
    "somerville": ["boston", "greater boston"],
}


class AuditIssue(BaseModel):
    """Represents the outcome and evidence of a single SEO check."""
    check_name: str
    audit_status: AuditStatus
    priority: Priority = "None"
    severity: Priority = "None"
    confidence: Confidence = "High"
    evidence_url: Optional[str] = None
    evidence: str
    recommended_fix: Optional[str] = None
    xlsx_summary: str = ""

    def model_post_init(self, __context):
        if self.severity != "None" and self.priority == "None":
            self.priority = self.severity
        elif self.priority != "None" and self.severity == "None":
            self.severity = self.priority
        if self.audit_status == "Unverified" and self.confidence == "High":
            self.confidence = "Unverified"


class AuditInput(BaseModel):
    """Input payload for auditing a business."""
    url: str
    business_name: Optional[str] = None
    category: Optional[str] = None
    city: Optional[str] = None
    target_city: Optional[str] = None
    phone: Optional[str] = None
    claimed_phone: Optional[str] = None
    address: Optional[str] = None
    rating: Optional[float] = None
    reviews_count: Optional[int] = None
    job_id: Optional[str] = None
    place_id: Optional[str] = None

    def get_actual_city(self) -> Optional[str]:
        """Extracts actual city from full address using standard US address regex."""
        if self.address:
            m = re.search(r',\s*([A-Za-z\s\.]+),\s*[A-Z]{2}\s*\d{5}', self.address)
            if m:
                extracted = m.group(1).strip().strip(".,")
                if extracted and len(extracted) > 1:
                    return extracted
        return None

    def get_candidate_cities(self) -> List[str]:
        """Returns list of valid non-empty candidate city/location names."""
        candidates = []
        actual = self.get_actual_city()
        if actual and actual.strip():
            candidates.append(actual.strip())
        if self.city and self.city.strip():
            candidates.append(self.city.strip())
        if self.target_city and self.target_city.strip():
            candidates.append(self.target_city.strip())

        seen = set()
        clean_list = []
        for c in candidates:
            c_low = c.lower().strip()
            if c_low and c_low not in seen:
                seen.add(c_low)
                clean_list.append(c.strip())
                # Add mapped parent metro and sister areas
                if c_low in METRO_NEIGHBORHOOD_MAPPINGS:
                    for parent_metro in METRO_NEIGHBORHOOD_MAPPINGS[c_low]:
                        if parent_metro not in seen:
                            seen.add(parent_metro)
                            clean_list.append(parent_metro.title())
        return clean_list

    def get_primary_city(self) -> str:
        """Returns the single best resolved city name (never empty string if any candidate exists)."""
        actual = self.get_actual_city()
        if actual:
            return actual
        if self.city and self.city.strip():
            return self.city.strip()
        if self.target_city and self.target_city.strip():
            return self.target_city.strip()
        return ""

    def model_post_init(self, __context):
        if not self.city and self.target_city:
            self.city = self.target_city
        actual = self.get_actual_city()
        if actual and (not self.city or self.city.lower() in ("downtown", "midtown", "uptown", "city center")):
            self.city = actual
        if not self.phone and self.claimed_phone:
            self.phone = self.claimed_phone


class SEOReport(BaseModel):
    """Complete comprehensive agency-grade SEO audit report for a business."""
    url: str
    final_url: str = ""
    http_status_summary: str = ""
    ssl_status: str = ""
    server_response_ttfb: str = ""
    ttfb_seconds: Optional[float] = None
    seo_health_score: Optional[int] = None
    opportunity_score: Optional[int] = None
    lead_pitch_priority: str = "Low Priority - Well Optimized"
    extracted_title: str = ""
    extracted_h1: str = ""
    word_count: int = 0
    icebreaker_hook: str = ""
    load_time_seconds: Optional[float] = None
    is_js_rendered: bool = False
    audited_page_type: str = "homepage"
    issues: Dict[str, AuditIssue] = Field(default_factory=dict)
    xlsx_row_data: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None


class AuditSectionConfig(BaseModel):
    """Flags for enabling/disabling individual audit sections in the report."""
    technical_seo: bool = Field(default=True, alias="website_technical_seo")
    onpage_seo: bool = Field(default=True, alias="onpage_local_seo")
    competitor_research: bool = True
    pagespeed_mobile: bool = True
    ads_tracking: bool = True
    inner_pages: bool = True

    model_config = {
        "populate_by_name": True
    }


class AgencyBranding(BaseModel):
    """Agency branding details for white-label reports and PDFs."""
    agency_name: str = "Apex Digital Marketing"
    logo_url: Optional[str] = None
    tagline: Optional[str] = "Professional Local SEO & Digital Growth Agency"
    primary_color: str = "#2563EB"
    accent_color: str = "#10B981"
    contact_email: Optional[str] = "contact@agency.com"
    website: Optional[str] = "https://agency.com"
    phone: Optional[str] = None


class CompetitorComparison(BaseModel):
    """Structured side-by-side local competitor metric snapshot."""
    business_name: str
    place_id: Optional[str] = None
    rating: Optional[float] = None
    reviews_count: Optional[int] = None
    seo_score: Optional[int] = None
    pagespeed_score: Optional[int] = None
    has_schema: Optional[bool] = None
    has_nap: Optional[bool] = None
    has_tracking: Optional[bool] = None
    trailing_gaps: List[str] = Field(default_factory=list)


class PageSpeedResult(BaseModel):
    """Google PageSpeed Insights score and Web Vitals metrics."""
    mobile_score: Optional[int] = None
    desktop_score: Optional[int] = None
    lcp_seconds: Optional[float] = None
    cls_value: Optional[float] = None
    inp_ms: Optional[float] = None
    fcp_seconds: Optional[float] = None
    mobile_friendly_status: str = "Not Checked"
    screenshot_url: Optional[str] = None
    status: str = "Unavailable"  # e.g., "Pass", "Warning", "Critical", "Unavailable", "Not Checked"
    details: str = ""


class ActionPlanItem(BaseModel):
    """Prioritized action item for client roadmap."""
    title: str
    timeframe: Literal["Quick Win (1-7 Days)", "Medium-Term (2-4 Weeks)", "Long-Term (1-3 Months)"] = "Quick Win (1-7 Days)"
    priority: Literal["Critical", "High", "Medium", "Low"] = "High"
    category: str = "Technical SEO"
    impact: str = "Immediate SEO improvement"
    description: str = ""


class AIAuditReport(BaseModel):
    """Full grounded, evidence-backed agency AI audit report."""
    business_name: str
    category: str = ""
    website_url: str = ""
    audited_url: str = ""
    location: str = ""
    audit_date: str = ""
    seo_health_score: Optional[int] = None
    audit_scope: List[str] = Field(default_factory=list)
    executive_summary: str = ""
    critical_issues: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    passed_checks: List[str] = Field(default_factory=list)
    plain_english_explanations: List[Dict[str, str]] = Field(default_factory=list)
    action_plan: List[ActionPlanItem] = Field(default_factory=list)
    competitor_analysis: Optional[str] = None
    competitors: List[CompetitorComparison] = Field(default_factory=list)
    pagespeed_data: Optional[PageSpeedResult] = None
    data_limitations: List[str] = Field(default_factory=list)
    branding: Optional[AgencyBranding] = None
    raw_seo_report: Optional[SEOReport] = None


class GenerateReportRequest(BaseModel):
    audit_input: Optional[AuditInput] = None
    url: Optional[str] = None
    business_name: Optional[str] = None
    category: Optional[str] = None
    city: Optional[str] = None
    target_city: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    rating: Optional[float] = None
    reviews_count: Optional[int] = None
    job_id: Optional[str] = None
    place_id: Optional[str] = None
    sections: Optional[AuditSectionConfig] = Field(default_factory=AuditSectionConfig)
    branding: Optional[AgencyBranding] = None


class ExportPdfRequest(BaseModel):
    audit_input: Optional[AuditInput] = None
    url: Optional[str] = None
    business_name: Optional[str] = None
    category: Optional[str] = None
    city: Optional[str] = None
    target_city: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    rating: Optional[float] = None
    reviews_count: Optional[int] = None
    job_id: Optional[str] = None
    place_id: Optional[str] = None
    sections: Optional[AuditSectionConfig] = Field(default_factory=AuditSectionConfig)
    branding: Optional[AgencyBranding] = None
    report_data: Optional[AIAuditReport] = None

