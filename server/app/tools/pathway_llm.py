from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.state import (
    CareerPlan,
    CritiqueReport,
    EvidenceItem,
    GapReport,
    InternshipOpportunity,
    LearningAction,
    LearningResource,
    PlanPhase,
    RoleSpecModel,
    StudentConstraints,
    StudentModel,
)

# ---------------------------------------------------------------------------
# LLM output schema (internal to this module)
# ---------------------------------------------------------------------------

class _ProjectSpec(BaseModel):
    title: str                     # Concrete project name e.g. "Customer Churn Prediction API"
    description: str               # Step-by-step spec, detailed enough for the student to follow
    stack: List[str] = Field(default_factory=list)  # Tools, libraries, methodologies (from student's available skills)
    rationale: str                 # Personalised — references student's background, explains gap closure
    addresses_gaps: List[str] = Field(default_factory=list)  # ALL gap labels this project addresses (multi-gap)
    bloom_level: str = "apply"     # str allows LLM flexibility; validated on assembly


class _PhaseSpec(BaseModel):
    title: str
    rationale: str
    outcome: str
    checkpoint: str                # "After this phase, you will be able to ..."
    projects: List[_ProjectSpec] = Field(min_length=1, max_length=3)  # 1–3 concrete projects per phase
    resume_updates: List[str]
    weeks_estimate: int = Field(ge=1, default=2)


class _PlanSpec(BaseModel):
    phases: List[_PhaseSpec]


class _InternshipOpportunitySpec(BaseModel):
    """Schema for internship recommendation generation."""
    message: str                                 # Narrative explaining readiness and timing
    recruiting_season: str                       # e.g. "Fall 2026 recruiting cycle (Aug–Oct)"
    suggested_internship_types: List[str]        # e.g. ["Data Analyst Internship"]
    resume_updates: List[str]                    # Specific projects/skills to add before applying


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are an expert career pathway architect designing a personalised, concrete learning curriculum.

You receive:
- A student profile summarising their demonstrated skills, projects, and experience
- Their ACADEMIC LEVEL (freshman → senior/grad) and AVAILABLE SKILLS
- An ordered list of skill gaps and prerequisite concepts to address
- Available example resources for each gap (for reference only — projects are what matter)
- Student constraints (academic level, hours/week, target goal, learning mode)
- Optionally, critique fixes from a previous iteration that MUST be resolved

Your task: author a personalised curriculum in 3–6 phases. Each phase contains 1–3 CONCRETE PROJECTS.

CONCRETE PROJECTS:
Each project must be detailed enough for a student to follow step-by-step. Projects vary in scope:
- Some use public datasets, APIs, or real-world data
- Some are simpler (e.g., build a function, analyze a CSV, create a visualization, design a workflow)
- Each project addresses MULTIPLE skill gaps simultaneously (true real-world learning)
- Projects must match the student's cognitive level and be culturally relatable

Good project examples (varying by level):
  ✓ Freshman: "Download the Iris dataset. Use Pandas to load it, examine shape/dtypes. Create a scatter plot of petal_length vs petal_width. Calculate mean & std of each feature by species."
  ✓ Junior: "Build a movie recommendation system using collaborative filtering. Load MovieLens data, train matrix factorization model with surprise, evaluate RMSE, write function for top-5 recommendations."
  ✓ Senior: "Implement end-to-end time series forecasting for stock prices or energy demand. Use your choice (ARIMA/Prophet/neural net), validate with proper time series CV, backtest strategy."

Bad projects (vague, single-gap, not followable):
  ✗ "Complete the 'Data Science Projects with Python' course"
  ✗ "Implement statistical analysis on a dataset"
  ✗ "Learn machine learning frameworks"

Each project must have:
  - title: concrete project name (e.g., "Customer Churn Prediction API", "Local Housing Market Analysis")
  - description: step-by-step breakdown the student can follow (1–2 paragraphs, numbered steps or bullet points)
  - stack: tools, libraries, methodologies CHOSEN FROM AVAILABLE SKILLS (e.g., ["Pandas", "Matplotlib", "SQL"])
  - rationale: PERSONALISED — reference their actual skills/projects, explain why this project closes their specific gaps
  - addresses_gaps: LIST of ALL gap labels this project covers (multi-gap is expected)
  - bloom_level: remember | understand | apply | analyse | evaluate | create

For each phase also write:
  - checkpoint: "After completing this phase, you will be able to [specific measurable capability]."
  - resume_updates: what to add to the resume before the NEXT phase

Rules:
1. PREREQUISITE ORDERING: Any gap marked [PREREQUISITE] must be addressed by projects in a phase
   that strictly precedes the phase handling its parent gap.

2. LEARNING MODE BIAS:
   - structured    → sequence conceptual before applied projects
   - project_based → lead with build/create projects
   - self_paced    → lead with documentation/tutorial projects
   - mixed         → balance conceptual and applied

3. ADDRESSES_GAPS: must be a LIST of EXACT strings from the "VALID GAP LABELS" list.
   Copy the strings character-for-character. NEVER use prerequisite concept labels.
   One project can address 2–4 gaps.

4. STACK: choose ONLY from the AVAILABLE SKILLS block provided. Do not invent tools
   the student does not have access to. Stack should be 2–5 tools per project.

5. ACADEMIC LEVEL & COMPLEXITY: Projects for freshman/sophomore should be focused and scaffolded.
   Projects for junior/senior should be more integrated and open-ended.
   Projects for grad should be research-oriented or novel implementations.

6. PERSONALISATION: Always reference the student's specific background in rationale fields.
   A student with XGBoost experience needs a different project than one with none.

7. WEEKS_ESTIMATE: realistic per-phase estimate. Sum should approach the target timeline.

8. CRITIQUE REFLECTION: when a CRITIQUE REFLECTION block is provided, use it to guide
   structural decisions in this revision. It explains why previous scores were low and
   what to change strategically. Reason about the guidance — do not follow it mechanically.
   Do not reintroduce issues that were resolved in prior iterations.

9. PREVIOUS PLAN: when a PREVIOUS PLAN block is provided alongside a CRITIQUE REFLECTION,
   use them together. The reflection explains why the previous plan failed; the previous
   plan shows exactly what was built. Keep phases and projects that were not flagged as
   problematic. Make targeted structural changes rather than rebuilding from scratch.

10. NO INTERNSHIPS: Projects must NOT reference internship opportunities or recommendations.
    Internships are recommended separately outside the curriculum.
"""


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def _format_student_context(
    student_model: Optional[StudentModel],
    evidence_items: List[EvidenceItem],
    constraints: Optional[StudentConstraints] = None,
    prior_phases: Optional[List[PlanPhase]] = None,
) -> str:
    if not student_model and not evidence_items and not constraints:
        return ""

    lines = ["STUDENT PROFILE (personalise rationale fields to this — be specific):"]
    if student_model:
        if student_model.skills:
            lines.append(f"  Skills demonstrated  : {', '.join(student_model.skills[:12])}")
        if student_model.education:
            lines.append(f"  Education            : {'; '.join(student_model.education[:3])}")
        if student_model.experiences:
            lines.append(f"  Experience           : {'; '.join(student_model.experiences[:4])}")

    # Projects from evidence_items (item_type==project; derived — safe for all consent levels)
    projects = [e for e in evidence_items if e.item_type == "project"]
    if projects:
        lines.append(f"  Projects             : {'; '.join(p.summary[:80] for p in projects[:4])}")

    # Academic level (influences project scope and scaffolding)
    if constraints:
        lines.append(f"  ACADEMIC LEVEL       : {constraints.academic_level}")

    # Accumulated available skills
    available = list(student_model.skills) if student_model else []
    if prior_phases:
        for ph in prior_phases:
            for g in ph.addresses_gaps:
                if g and g not in available:
                    available.append(g)

    if available:
        lines.append(f"  AVAILABLE SKILLS (use these for stack): {', '.join(set(available[:20]))}")

    # Project guidance by academic level
    level_guidance = {
        "freshman": "Focus on simple, focused projects with clear scaffolding. Students need guided practice.",
        "sophomore": "Mix of guided and slightly open-ended projects. Build confidence.",
        "junior": "Integrated projects combining 2–3 skills. Encourage exploration.",
        "senior": "Complex, multi-part projects with real-world data or open-ended design.",
        "grad": "Research-oriented or novel implementations. Allow for experimentation.",
        "bootcamp": "Practical, industry-ready projects. Fast-paced.",
        "self_taught": "Self-directed projects with clear learning outcomes.",
        "working_professional": "Project-based learning tied to job relevance. Efficient.",
    }
    if constraints and constraints.academic_level in level_guidance:
        lines.append(f"  PROJECT GUIDANCE     : {level_guidance[constraints.academic_level]}")

    lines.append("")
    return "\n".join(lines)


def _format_gap_context(
    ordered_items: List[Dict[str, Any]],
    resources_by_gap: Dict[str, List[LearningResource]],
) -> str:
    """
    Renders gap context in two sections:
    1. Numbered reference list of VALID ADDRESSES_GAP labels (gaps only).
    2. Full gap detail with prerequisite context and example resources.
    """
    gap_items    = [it for it in ordered_items if not it.get("is_prereq")]
    prereq_items = [it for it in ordered_items if it.get("is_prereq")]

    # --- Section 1: valid label reference list ---
    lines = ["VALID GAP LABELS — copy these EXACTLY into addresses_gaps list:"]
    for i, item in enumerate(gap_items, 1):
        label       = item["label"]
        gap_type    = item.get("gap_type", "").upper()
        proficiency = item.get("proficiency", 0)
        lines.append(f'  {i}. "{label}"  [{gap_type}]  proficiency={proficiency}/4')

    if prereq_items:
        lines.append("")
        lines.append("PREREQUISITE CONCEPTS (context only — NEVER use as addresses_gap):")
        for p in prereq_items:
            parent = p.get("parent_gap", "?")
            lines.append(f'  - "{p["label"]}"  →  sub-component of: "{parent}"')

    # --- Section 2: full detail with example resources ---
    lines.append("")
    lines.append("GAP DETAILS AND EXAMPLE RESOURCES:")
    for item in ordered_items:
        label       = item["label"]
        gap_type    = item.get("gap_type", "")
        root        = item.get("root_cause", "")
        proficiency = item.get("proficiency", 0)
        is_prereq   = item.get("is_prereq", False)

        tag = "PREREQUISITE" if is_prereq else gap_type.upper()
        lines.append(f'  "{label}"  [{tag}]  proficiency={proficiency}/4')
        if root:
            lines.append(f"    root_cause: {root}")
        reasoning = item.get("student_level_reasoning")
        if reasoning:
            lines.append(f"    student_level_reasoning: {reasoning}")

        resources = resources_by_gap.get(label, [])
        if resources:
            for r in resources:
                hours = f"~{r.estimated_hours}h" if r.estimated_hours else "?h"
                free  = "free" if r.is_free else ("paid" if r.is_free is False else "?")
                lines.append(
                    f"    - [{r.resource_type}] {r.title} ({free}, {hours})"
                    f" → {r.url or 'no URL'}"
                )
        else:
            lines.append("    (no example resources)")
        lines.append("")

    return "\n".join(lines)


def _format_constraints(c: StudentConstraints) -> str:
    return (
        f"Academic level:        {c.academic_level}\n"
        f"Hours available/week:  {c.hours_per_week}\n"
        f"Target goal:           {c.target_goal} ({c.target_weeks} weeks)\n"
        f"Preferred learning:    {c.preferred_learning_mode}"
    )


def _format_reflection(critique: Optional[CritiqueReport]) -> str:
    if not critique or not critique.narrative_feedback:
        return ""
    return (
        "CRITIQUE REFLECTION — STRATEGIC GUIDANCE FOR THIS REVISION:\n"
        f"{critique.narrative_feedback}"
    )


def _format_prev_plan(prev_plan: Optional[CareerPlan]) -> str:
    if not prev_plan or not prev_plan.phases:
        return ""
    lines = [f"PREVIOUS PLAN ({prev_plan.timeline_weeks}w total — your last iteration):"]
    for i, phase in enumerate(prev_plan.phases, 1):
        gaps     = ", ".join(phase.addresses_gaps[:6]) or "none"
        projects = "; ".join(a.title for a in phase.learning_actions[:3])
        lines.append(
            f"  Phase {i}: '{phase.title}' ({phase.weeks}w) | "
            f"projects: [{projects}] | gaps: [{gaps}]"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main LLM call
# ---------------------------------------------------------------------------

_VALID_BLOOM = {"remember", "understand", "apply", "analyse", "evaluate", "create"}


def synthesise_phases(
    ordered_items: List[Dict[str, Any]],
    resources_by_gap: Dict[str, List[LearningResource]],
    constraints: StudentConstraints,
    role_spec: Optional[RoleSpecModel],
    student_model: Optional[StudentModel] = None,
    evidence_items: Optional[List[EvidenceItem]] = None,
    critique: Optional[CritiqueReport] = None,
    prev_plan: Optional[CareerPlan] = None,
) -> _PlanSpec:
    """
    Ask the LLM to author a personalised curriculum with concrete, multi-gap projects per phase.
    Retrieved resources are passed as example references, not the plan's primary content.
    """
    role_title       = role_spec.canonical_role_title if role_spec else "the target role"
    student_ctx      = _format_student_context(student_model, evidence_items or [], constraints)
    reflection_block = _format_reflection(critique)
    prev_plan_block  = _format_prev_plan(prev_plan)

    user_prompt = f"""\
Target role: {role_title}

{student_ctx}
STUDENT CONSTRAINTS:
{_format_constraints(constraints)}

GAPS TO ADDRESS (in priority order — respect this ordering):
{_format_gap_context(ordered_items, resources_by_gap)}

{reflection_block}
{prev_plan_block}
Design a personalised learning pathway with 3–6 phases.
For each phase, write 1–3 concrete PROJECTS that YOU author (see system prompt for format).
Each project should address multiple gaps naturally. Use available skills from the student context
to populate the project stack. Use example resources as inspiration, but author projects directly.

"""

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
    llm_struct = llm.with_structured_output(_PlanSpec, method="json_schema", strict=True)

    return llm_struct.invoke([
        {"role": "system", "content": _SYSTEM},
        {"role": "user",   "content": user_prompt},
    ])


# ---------------------------------------------------------------------------
# Plan assembly
# ---------------------------------------------------------------------------

def assemble_plan(
    plan_spec: _PlanSpec,
    resources_by_gap: Dict[str, List[LearningResource]],
    internship_specs: Optional[Dict[int, _InternshipOpportunitySpec]] = None,
) -> CareerPlan:
    """
    Map the LLM _PlanSpec to a CareerPlan:
    - Convert projects to LearningAction objects with multi-gap support
    - Attach lean resources to each project (up to 3 per project, merged from all addressed gaps)
    - Derive phase.addresses_gaps by flattening all project addresses_gaps
    - Derive phase.resources from all example_resources for critique compatibility
    - Attach internship opportunity recommendations to phases
    """
    if internship_specs is None:
        internship_specs = {}
    _phase_prefix = re.compile(r"^phase\s*\d+\s*[:\-–]\s*", re.IGNORECASE)

    phases: List[PlanPhase] = []

    for spec in plan_spec.phases:
        learning_actions: List[LearningAction] = []
        seen_keys: set = set()
        phase_resources: List[LearningResource] = []

        for proj_spec in spec.projects:
            bloom = proj_spec.bloom_level if proj_spec.bloom_level in _VALID_BLOOM else "apply"

            # Lean resource attachment: merge resources for all addressed gaps, cap at 3 per project
            action_resources = []
            for gap_label in proj_spec.addresses_gaps:
                for r in resources_by_gap.get(gap_label, []):
                    key = (r.title, r.resource_type)
                    if key not in seen_keys and len(action_resources) < 3:
                        seen_keys.add(key)
                        action_resources.append(r)

            learning_actions.append(LearningAction(
                title=proj_spec.title,
                description=proj_spec.description,
                stack=proj_spec.stack,
                rationale=proj_spec.rationale,
                addresses_gaps=proj_spec.addresses_gaps,
                bloom_level=bloom,
                example_resources=action_resources,
            ))

            # Accumulate deduplicated phase.resources for critique node
            for r in action_resources:
                key = (r.title, r.resource_type)
                if key not in seen_keys:
                    seen_keys.add(key)
                    phase_resources.append(r)

        # Derive addresses_gaps by flattening all project addresses_gaps (ordered, deduplicated)
        addresses_gaps = list(dict.fromkeys(
            g for action in learning_actions for g in action.addresses_gaps
        ))

        # Build internship opportunity if one exists for this phase
        internship_opp = None
        if len(phases) in internship_specs:
            spec_opp = internship_specs[len(phases)]
            internship_opp = InternshipOpportunity(
                message=spec_opp.message,
                recruiting_season=spec_opp.recruiting_season,
                suggested_internship_types=spec_opp.suggested_internship_types,
                resume_updates=spec_opp.resume_updates,
            )

        phases.append(PlanPhase(
            title=_phase_prefix.sub("", spec.title).strip(),
            rationale=spec.rationale,
            outcome=spec.outcome,
            checkpoint=spec.checkpoint,
            weeks=spec.weeks_estimate,
            learning_actions=learning_actions,
            resources=phase_resources,
            addresses_gaps=addresses_gaps,
            resume_updates=spec.resume_updates,
            internship_opportunity=internship_opp,
        ))

    return CareerPlan(
        timeline_weeks=sum(p.weeks for p in phases),
        phases=phases,
    )


# ---------------------------------------------------------------------------
# Internship opportunity recommendation synthesis
# ---------------------------------------------------------------------------

_INTERNSHIP_SYSTEM = """\
You are an internship recruiting advisor. Given a student's planned learning pathway,
recommend when they should apply for internships based on:
1. When they've completed sufficient projects in a relevant area
2. Recruiting cycles (Summer internship: apply in Fall; Spring internship: apply in late Fall)
3. Academic level and readiness tier

Return a JSON object mapping phase_index (0-based) → InternshipOpportunitySpec.
Only recommend internship windows after Phase 1. Do not recommend if insufficient evidence.
"""


def synthesise_internship_opportunities(
    ordered_items: List[Dict[str, Any]],
    plan: CareerPlan,
    constraints: StudentConstraints,
    gap_report: GapReport,
    student_model: Optional[StudentModel] = None,
    evidence_items: Optional[List[EvidenceItem]] = None,
) -> Dict[int, _InternshipOpportunitySpec]:
    """
    Generate internship application recommendations for phases that are natural milestones.
    Returns dict mapping phase_index → InternshipOpportunitySpec.
    """
    if not plan.phases or len(plan.phases) < 2:
        return {}

    # Build phase summary for LLM context
    phase_summaries = []
    cumulative_weeks = 0
    for i, phase in enumerate(plan.phases):
        cumulative_weeks += phase.weeks
        projects = [a for a in phase.learning_actions if any(
            r.resource_type == "project" for r in a.example_resources
        )]
        phase_summaries.append(
            f"Phase {i}: {phase.title} ({phase.weeks}w, cumulative {cumulative_weeks}w) — "
            f"{len(projects)} project-based actions, addresses: {', '.join(phase.addresses_gaps[:3])}"
        )

    user_prompt = f"""\
Student: {constraints.academic_level} level
Target date: {constraints.target_date or "not specified"}
Total plan duration: {plan.timeline_weeks} weeks

Phase breakdown:
{chr(10).join(phase_summaries)}

Based on this pathway, recommend internship opportunities.
For each recommended phase, provide:
- message: Narrative explaining readiness (reference actual projects/milestones from prior phases)
- recruiting_season: e.g. "Fall 2026 recruiting cycle (Aug–Oct 2026)"
- suggested_internship_types: 2–3 types of internships to target (e.g. "Data Analyst Internship", "ML Research Intern")
- resume_updates: 2–3 specific items to add to resume before applying (reference projects from prior phases)

Return a JSON object: {{"phase_index": InternshipOpportunitySpec, ...}}
Only recommend after Phase 1. Return empty object {{}} if no good windows exist.
"""

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7)
    llm_struct = llm.with_structured_output(
        Dict[int, _InternshipOpportunitySpec],
        method="json_schema",
        strict=True,
    )

    try:
        result = llm_struct.invoke([
            {"role": "system", "content": _INTERNSHIP_SYSTEM},
            {"role": "user",   "content": user_prompt},
        ])
        return result or {}
    except Exception:
        return {}
