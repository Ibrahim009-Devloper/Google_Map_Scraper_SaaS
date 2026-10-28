"""
Pydantic data models and schemas for the Local SEO Audit Engine.
"""

from typing import Optional, Dict, Literal
from pydantic import BaseModel, Field

AuditStatus = Literal["Pass", "Warning", "Fail", "Unverified"]
Priority = Literal["High", "Medium", "Low", "None"]


class AuditIssue(BaseModel):
    """Represents the outcome and evidence of a single SEO check."""
    check_name: str
    audit_status: AuditStatus
    priority: Priority = "None"
    evidence: str
    recommended_fix: Optional[str] = None
    xlsx_summary: str = ""


class AuditInput(BaseModel):
    """Input payload for auditing a business."""
    url: str
    business_name: Optional[str] = None
    category: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None


class SEOReport(BaseModel):
    """Complete comprehensive SEO audit report for a business."""
    url: str
    opportunity_score: Optional[int] = None
    load_time_seconds: Optional[float] = None
    issues: Dict[str, AuditIssue] = Field(default_factory=dict)
    xlsx_row_data: Dict[str, str] = Field(default_factory=dict)
    error_message: Optional[str] = None
