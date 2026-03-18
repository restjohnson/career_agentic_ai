from __future__ import annotations
from datetime import date
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, computed_field

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
    summary: str
    snippet: Optional[str] = None
    confidence: float = 0.8
    proficiency_score: Optional[int] = None   # 0–4, LLM-assessed per rubric
    action_verbs: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

# ---------------------------------------------------------------------------
# Student constraints (supplied upfront at API call time)
# ---------------------------------------------------------------------------

AcademicLevel = Literal[
    "freshman", "sophomore", "junior", "senior",   # undergrad years
    "grad", "bootcamp", "self_taught", "working_professional",
]

LearningMode = Literal["structured", "project_based", "self_paced", "mixed"]

TargetGoal = Literal[
    "first_internship",   # wants to land their first internship
    "graduation",         # wants to be job-ready by graduation
    "job_ready",          # wants to be ready for full-time roles
    "career_change",      # transitioning from another field
]

# Default planning horizons when no target_date is given
_GOAL_DEFAULT_WEEKS: Dict[str, int] = {
    "first_internship": 16,   # ~1 semester of prep
    "graduation":       52,   # ~1 academic year
    "job_ready":        26,   # ~6 months
    "career_change":    39,   # ~9 months
}


class StudentConstraints(BaseModel):
    academic_level: AcademicLevel
    hours_per_week: int                       # 1–40
    target_goal: TargetGoal                   # what the student is working toward
    target_date: Optional[str] = None         # ISO "YYYY-MM-DD"; compute weeks from today if given
    preferred_learning_mode: LearningMode

    @computed_field
    @property
    def target_weeks(self) -> int:
        """Weeks from today to target_date, or the goal-based default."""
        if self.target_date:
            try:
                delta = (date.fromisoformat(self.target_date) - date.today()).days
                return max(1, round(delta / 7))
            except ValueError:
                pass
        return _GOAL_DEFAULT_WEEKS.get(self.target_goal, 26)

#student model
class StudentModel(BaseModel):
    skills: List[str] = Field(default_factory=list, description="career-related skills extracted from evidence")
    experiences: List[str] = Field(default_factory=list, description="career-related experiences extracted from evidence")
    education: List[str] = Field(default_factory=list, description="career-related education extracted from student submitted evidence")
    constraints: Dict[str, Any] = Field(
        default_factory=dict,
        description="student constraints such as time/week, current college year, anticipated graduation date")
    evidence_map: Dict[str, List[str]] = Field(default_factory=dict)

RoleReqType = Literal["skill", "task", "tech", "hot_technology", "knowledge"]

# role requirement and role model retrived from ONET
class RoleRequirement(BaseModel):
    req_type: RoleReqType
    req_summary: str
    importance: Optional[float] = None
    source_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RoleModel(BaseModel):
    role_title: str
    onet_code: Optional[str] = None
    version: Optional[str] = None
    summary: Dict[str, Any] = Field(default_factory=dict)
    requirements: List[RoleRequirement] = Field(default_factory=list)

#LLM curated verification of role requirement (provenance)
SpecSourceType = Literal["ONET", "JOB_POSTINGS", "CURATED", "USER_INPUT", "INFERRED"]

class ProvenanceRef(BaseModel):
    source_type: SpecSourceType
    source_ids: Optional[List[str]] = None  # required for ONET (onet_code); null for all other source types
    note: Optional[str] = None

class RoleSpecRequirement(BaseModel):
    req_summary: str
    category: RoleReqType
    provenance: List[ProvenanceRef] = Field(default_factory=list)
    optional: bool = False
    required_level: float = 3.0   # 0–4, LLM-assigned at role_intake time
    importance: float = 3.0       # 1–5, LLM-assigned at role_intake time

class RoleSpecModel(BaseModel):
    canonical_role_title: str
    matched_onet_code: Optional[str] = None
    confidence_role_match: float = Field(ge=0.0, le=1.0, default=0.7)
    requirements: List[RoleSpecRequirement] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)

# Gap Analysis, Planning, and critique
class KnowledgePrerequisite(BaseModel):
    concept: str                          # specific knowledge concept, role-grounded
    parent_skill_gap: str                 #req_summary of the parent GapItem
    is_foundational: bool                 # hard prerequisite vs supporting knowledge
    inferred_confidence: float            #0–1, LLM-estimated from evidence
    inference_tier: Literal["direct", "skill_implied", "degree_baseline", "none"]
    inference_basis: List[str] = Field(default_factory=list)  # evidence summaries
    final_confidence: float = 0.0


class GapItem(BaseModel):
    summary: str
    category: RoleReqType
    required_level: float
    student_score: float
    raw_gap: float
    weighted_gap: float
    proficiency: int                      #0–4, aggregated from evidence collection
    confidence: float                     #0–1, Bayesian-combined from evidence
    gap_type: Literal["missing", "weak", "not_evidenced", "irrelevant"] = "missing"
    gap_root_cause: Optional[Literal["missing_entirely", "no_theory", "no_practice"]] = None
    evidence_item_ids: List[str] = Field(default_factory=list)
    knowledge_prerequisites: List[KnowledgePrerequisite] = Field(default_factory=list)

class GapReport(BaseModel):
    summary: str = ""
    gaps: List[GapItem] = Field(default_factory=list)

# ---------------------------------------------------------------------------
# Pathway planning — learning resources and plan structure
# ---------------------------------------------------------------------------

ResourceType = Literal[
    "tutorial",       # blog posts, YouTube walkthroughs — primary informal channel
    "project",        # hands-on build (guided or self-directed)
    "open_source",    # contributing to existing OSS repos
    "workshop",       # hackathons, bootcamp-style intensives
    "certification",  # professional certs (AWS, Google, etc.)
    "internship",     # internship opportunity
    "online_course",  # structured MOOCs — secondary (less informal)
    "documentation",  # official docs + guided practice
]

BloomLevel = Literal[
    "remember", "understand", "apply", "analyse", "evaluate", "create"
]

class LearningResource(BaseModel):
    title: str
    provider: Optional[str] = None            # "Coursera", "GitHub", "Handshake", etc.
    url: Optional[str] = None
    resource_type: ResourceType
    estimated_hours: Optional[int] = None
    is_free: Optional[bool] = None
    addresses_gap: str                        # req_summary of the gap this covers


class LearningAction(BaseModel):
    """
    An authored learning step within a phase.
    The LLM writes the curriculum; resources are attached as examples.
    """
    title: str                                # e.g. "Build a SQL analytics dashboard on the NYC taxi dataset"
    summary: str                              # what the student will practise / produce
    rationale: str                            # personalised: why this closes their specific gap
    addresses_gap: str                        # gap label this action primarily advances
    bloom_level: BloomLevel = "apply"
    example_resources: List[LearningResource] = Field(default_factory=list)


class PlanPhase(BaseModel):
    title: str
    rationale: str
    outcome: str
    checkpoint: str = ""                      # "After this phase, you will be able to..."
    weeks: int = Field(ge=1, default=2)
    learning_actions: List[LearningAction] = Field(default_factory=list)
    resources: List[LearningResource] = Field(default_factory=list)
    # ^ derived from learning_actions[].example_resources; kept for critique compatibility
    addresses_gaps: List[str] = Field(default_factory=list)
    resume_updates: List[str] = Field(default_factory=list)
    # ^ Skills/projects to add to resume before the NEXT phase (machine-readable for critique)


class CareerPlan(BaseModel):
    timeline_weeks: int = Field(ge=1, default=8)
    phases: List[PlanPhase] = Field(default_factory=list)

class CritiqueReport(BaseModel):
    rubric_scores: Dict[str, int] = Field(default_factory=dict)
    '''Dimensions and minimum passing thresholds (out of 5)
    feasibility >= 3
    internship_readiness >= 4
    prerequisite_ordering >= 4
    level_appropriateness >= 3
    gap_coverage   >= 3'''
    issues: List[str] = Field(default_factory=list)
    fixes: List[str] = Field(default_factory=list)
    satisfactory: bool = False

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
    evidence_documents: List[EvidenceDocument] = Field(default_factory=list)
    evidence_items: List[EvidenceItem] = Field(default_factory=list)
    raw_user_text: Optional[str] = None

    #information from agents
    student_model: Optional[StudentModel] = None
    student_constraints: Optional[StudentConstraints] = None
    role_model: Optional[RoleModel] = None
    role_spec: Optional[RoleSpecModel] = None
    gap_report: Optional[GapReport] = None
    plan: Optional[CareerPlan] = None
    critique: Optional[CritiqueReport] = None

    # Iterative refinement tracking
    critique_iterations: int = 0
    best_plan: Optional[CareerPlan] = None
    best_critique_score: float = 0.0
    prev_critique_issues: List[str] = Field(default_factory=list)
    # ^ holds the issues from the previous critique iteration for stall detection

    status: RunStatus = "queued"
    step: Optional[StepName] = None
    errors: List[str] = Field(default_factory=list)
