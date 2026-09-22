from __future__ import annotations
from datetime import date
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, computed_field, model_validator

EvidenceSourceType = Literal["resume", "transcript", "portfolio", "job_posting", "other"]
EvidenceItemType = Literal["experience", "project", "coursework", "claim"]
EvidenceProvenance = Literal["self_supplied", "externally_verified"]

# ---------------------------------------------------------------------------
# Evidence documents and items (Stage 2 output)
# ---------------------------------------------------------------------------

class EvidenceDocument(BaseModel):
    id: Optional[str] = None
    source_type: EvidenceSourceType
    content_hash: str
    storage_ref: Optional[str] = None


class EvidenceItem(BaseModel):
    """
    Stage 2 output. Goal-independent: no field on this object references a
    requirement, so accumulated evidence survives a change of target role.
    `type` and `quality` are assigned by two separate LLM calls — the quality
    call receives neither type nor any requirement (COMPASS spec §4 Stage 2).
    """
    id: Optional[str] = None
    document_id: Optional[str] = None
    type: EvidenceItemType
    summary: str
    snippet: Optional[str] = None
    quality: float = Field(ge=0.0, le=1.0, default=0.10)
    provenance: EvidenceProvenance = "self_supplied"
    type_rationale: Optional[str] = None
    quality_rationale: Optional[str] = None

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

# ---------------------------------------------------------------------------
# Requirement (Stage 1 output)
# ---------------------------------------------------------------------------

RequirementCategory = Literal["skill", "knowledge", "task", "technology"]
RequirementProvenance = Literal["grounded", "inferred"]


class Requirement(BaseModel):
    id: Optional[str] = None
    category: RequirementCategory
    description: str
    required_depth: int = Field(ge=0, le=3)     # the quality level of demonstration the role demands
    importance: int = Field(ge=1, le=5)
    provenance: RequirementProvenance
    justification: Optional[str] = None         # required when provenance == inferred
    source_ref: Optional[str] = None            # O*NET code or posting id when grounded

    @model_validator(mode="after")
    def _justification_required_when_inferred(self) -> "Requirement":
        if self.provenance == "inferred" and not self.justification:
            raise ValueError("Requirement.justification is required when provenance == 'inferred'.")
        return self


class RoleSpecModel(BaseModel):
    """Role-level container around the requirement set produced by Stage 1."""
    canonical_role_title: str
    matched_onet_code: Optional[str] = None
    confidence_role_match: float = Field(ge=0.0, le=1.0, default=0.7)
    requirements: List[Requirement] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)

# ---------------------------------------------------------------------------
# RequirementState (Stage 3 output) — one per requirement; the set of these
# is the "student state" passed to Stages 4 and 5.
# ---------------------------------------------------------------------------

GapType = Literal["no_evidence", "claimed_only", "met", "partial", "uncertain", "unmet"]
Disposition = Literal["satisfied", "remediate", "verify", "defer"]
DiagnosticForm = Literal["artifact_submission", "external_validation"]


class MatchedItem(BaseModel):
    item_id: str
    relevance: float = Field(ge=0.0, le=1.0)


class RequirementState(BaseModel):
    requirement_id: str
    alpha: float
    beta: float
    estimate: float
    variance: float
    evidential_mass: float
    p_met: float
    gap_type: GapType = "no_evidence"
    disposition: Disposition = "defer"
    strongest_type: Optional[EvidenceItemType] = None
    closure_cost_est: float = 0.0            # hours; a budget heuristic, not an effort prediction
    matched_items: List[MatchedItem] = Field(default_factory=list)
    reasoning: Optional[str] = None          # explanatory only, cannot modify any number above

# ---------------------------------------------------------------------------
# Plan (Stage 4 output)
# ---------------------------------------------------------------------------

ActivityKind = Literal["development", "diagnostic"]

ResourceType = Literal[
    "tutorial", "project", "open_source", "workshop",
    "certification", "online_course", "documentation",
]


class Resource(BaseModel):
    title: str
    url: Optional[str] = None
    verified: bool = False               # false when model-generated (not URL-validated)
    provider: Optional[str] = None
    resource_type: Optional[ResourceType] = None
    estimated_hours: Optional[int] = None
    is_free: Optional[bool] = None


class ExpectedYield(BaseModel):
    type: EvidenceItemType
    provenance: EvidenceProvenance
    quality: float


class Activity(BaseModel):
    kind: ActivityKind
    addresses: List[str] = Field(default_factory=list)   # requirement ids
    title: str
    steps: List[str] = Field(default_factory=list)
    tech_stack: List[str] = Field(default_factory=list)
    rationale: str                        # why this activity for this student
    hours: float
    resources: List[Resource] = Field(default_factory=list)

    # diagnostic only
    target_uncertain: List[str] = Field(default_factory=list)
    discriminating_question: Optional[str] = None
    expected_yield: Optional[ExpectedYield] = None
    branch_consequence: Optional[str] = None


class Phase(BaseModel):
    index: int
    activities: List[Activity] = Field(default_factory=list)
    novelty_mass: float = 0.0
    coupling: float = Field(ge=0.0, le=1.0, default=0.0)
    load: float = 0.0                     # computed, not model-assigned


class DeferralEntry(BaseModel):
    requirement_id: str
    reason: str


class Plan(BaseModel):
    phases: List[Phase] = Field(default_factory=list)
    deferral_report: List[DeferralEntry] = Field(default_factory=list)
    total_hours: float = 0.0
    horizon_weeks: int = 0

# ---------------------------------------------------------------------------
# Stage 5: quality check — score_report (logging only) and diagnosis
# (feedback-generator input) are structurally separate types; diagnosis
# carries no score or threshold fields at all.
# ---------------------------------------------------------------------------

class CriterionScore(BaseModel):
    criterion: str
    score: int = Field(ge=1, le=5)
    threshold: int


class DiagnosisEntry(BaseModel):
    criterion: str
    location: str
    direction: str


class CritiqueReport(BaseModel):
    score_report: List[CriterionScore] = Field(default_factory=list)   # -> logging only
    diagnosis: List[DiagnosisEntry] = Field(default_factory=list)      # -> feedback generator
    satisfactory: bool = False

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

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
    turn_id: Optional[str] = None

    #collect the user's intent
    desired_role: str

    #evidence from user — accumulates across turns, never turn-scoped
    evidence_documents: List[EvidenceDocument] = Field(default_factory=list)
    evidence_items: List[EvidenceItem] = Field(default_factory=list)
    raw_user_text: Optional[str] = None
    raw_documents_markdown: Dict[str, str] = Field(default_factory=dict)
    # ^ doc_id -> parsed markdown; read by the Stage 5 calibration judge,
    #   which must see source documents directly rather than the assessment.

    #information from agents
    student_constraints: Optional[StudentConstraints] = None
    role_spec: Optional[RoleSpecModel] = None
    requirement_states: List[RequirementState] = Field(default_factory=list)
    plan: Optional[Plan] = None
    critique: Optional[CritiqueReport] = None

    # Iterative refinement tracking
    critique_iterations: int = 0
    best_plan: Optional[Plan] = None
    best_critique_score: float = 0.0
    prev_plan: Optional[Plan] = None
    # ^ snapshot of plan before current iteration, for feedback-generation comparison
    prev_failing_criteria: List[str] = Field(default_factory=list)
    # ^ criterion names that failed last iteration; stall detection compares
    #   this SET, not issue text, to the current iteration's failing set.

    status: RunStatus = "queued"
    step: Optional[StepName] = None
    errors: List[str] = Field(default_factory=list)
