from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

EvidenceSourceType = Literal["resume", "transcript", "portfolio", "job_posting", "other"]
EvidenceItemType = Literal["skill", "experience", "project", "coursework", "claim"]

#student evidence such as resume and others

class EvidenceDocument(BaseModel):
    id: Optional[str] = None
    source_type: EvidenceSourceType
    content_hash: str
    storage_ref: Optional[str] = None
    consent_level: Literal["derived_only", "excerpt_ok", "raw_ok"] = "derived_only"

class EvidenceItem(BaseModel):
    id: Optional[str] = None
    document_id: Optional[str] = None
    item_type: EvidenceItemType
    label: str
    snippet: Optional[str] = None
    confidence: float = 0.8
    metadata: Dict[str, Any] = Field(default_factory=dict, description="")

#student model
class StudentModel(BaseModel):
    skills: List[str] = Field(default_factory=list, description="career-related skills extracted from evidence")
    experiences: List[str] = Field(default_factory=list, description="career-related experiences extracted from evidence")
    education: List[str] = Field(default_factory=list, desctiption="career-related education extracted from student submitted evidence")
    constraints: Dict[str, Any] = Field(
        default_factory=dict, 
        description="student constraints such as time/week, current college year, anticipated graduation date")
    evidence_map: Dict[str, List[str]] = Field(default_factory=dict)

RoleReqType = Literal["skill", "knowledge", "task", "tech"]

# role requirement and role model retrived from ONET
class RoleRequirement(BaseModel):
    req_type: RoleReqType
    label: str
    importance: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RoleModel(BaseModel):
    role_title: str
    onet_code: Optional[str] = None
    version: Optional[str] = None
    summary: Dict[str, Any] = Field(default_factory=list)
    requirements: List[RoleRequirement] = Field(default_factory=list)

#LLM curated verification of role requirement (provenance)
SpecSourceType = Literal["ONET", "JOB_POSTINGS", "CURATED", "USER_INPUT", "INFERRED"]

class ProvenanceRef(BaseModel):
    source_type: SpecSourceType
    source_ids: List[str] = Field(default_factory=list) #role_requirement row IDs, doc IDs, URL IDs
    note: Optional[str] = None

class RoleSpecRequirement(BaseModel):
    label: str
    category: RoleReqType
    priority: int = Field(ge=1, le=5, default=3)
    provenance: List[ProvenanceRef] = Field(default_factory=list)
    optional: bool = False

class RoleSpecModel(BaseModel):
    canonical_role_title: str
    matched_onet_code: Optional[str] = None
    confidence_role_match: float = Field(ge=0.0, le=1.0, default=0.7)
    requirements: List[RoleSpecRequirement] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)

# Gap Analysis, Planning, and critque
class GapItem(BaseModel):
    label: str
    category: RoleReqType
    gap_type: Literal["missing", "weak"] = "missing"
    evidence_item_ids: List[str] = Field(
        default_factory=list, description="what evidence support the student's current categroy level"
        )
    target_priority: int = Field(ge=1, le=5, default=3)

class GapReport(BaseModel):
    summary: str = ""
    gaps: List[GapItem] = Field(default_factory=list)

class PlanMilestone(BaseModel):
    title: str
    outcome: str
    weeks: int = Field(ge=1, default=2)
    resources: List[str] = Field(default_factory=list)

class CareerPlan(BaseModel):
    timeline_weeks: int = Field(ge=1, default=8)
    milestones: List[PlanMilestone] = Field(default_factory=list)
    projects: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)

class CritqueReport(BaseModel):
    rubric_scores: Dict[str, int] = Field(default_factory=dict)
    issues: List[str] = Field(default_factory=list)
    fixes: List[str] = Field(default_factory=list)
    satisfactory: bool=False

#Shared State
RunStatus = Literal["queued", "running", "done", "failed"]
StepName = Literal[
    "role_intake",
    "evidence_ingestion",
    "gap_analysis",
    "pathway_planning",
    "critique",
    "explanation",
]

class AgentState(BaseModel):
    #for ownership of a session
    session_id: str
    run_id: Optional[str] = None

    #colelct the user's intent
    desired_role: str

    #evidence from user
    evidence_documents: List[EvidenceDocument] =Field(default_factory=list)
    evidence_items: List[EvidenceItem] = Field(default_factory=list)
    raw_user_text: Optional[str] =None

    #information from agents
    student_model: Optional[StudentModel] = None
    role_model: Optional[RoleModel] = None
    role_spec: Optional[RoleSpecModel] = None
    gap_report: Optional[GapReport] = None
    plan: Optional[CareerPlan] = None
    critique: Optional[CritqueReport] = None

    status: RunStatus = "queued"
    step: Optional[StepName] = None
    errors: List[str] = Field(default_factory=list)