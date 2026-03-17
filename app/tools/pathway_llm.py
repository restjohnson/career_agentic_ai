from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.state import (
    CareerPlan,
    CritiqueReport,
    EvidenceItem,
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

class _LearningActionSpec(BaseModel):
    title: str        # verb-led, specific action e.g. "Build a SQL dashboard on the NYC taxi dataset"
    summary: str      # what the student will practise / produce
    rationale: str    # personalised to their background — why this closes their gap
    addresses_gap: str
    bloom_level: str = "apply"  # str allows LLM flexibility; validated on assembly


class _PhaseSpec(BaseModel):
    title: str
    rationale: str
    outcome: str
    checkpoint: str              # "After this phase, you will be able to ..."
    learning_actions: List[_LearningActionSpec] = Field(min_length=2, max_length=4)
    resume_updates: List[str]
    weeks_estimate: int = Field(ge=1, default=2)


class _PlanSpec(BaseModel):
    phases: List[_PhaseSpec]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are an expert career pathway architect designing a personalised, action-oriented learning curriculum.

You receive:
- A student profile summarising their demonstrated skills, projects, and experience
- An ordered list of skill gaps and prerequisite concepts to address
- Available example resources for each gap (for reference — the ACTIONS are what matter)
- Student constraints (academic level, hours/week, target goal, learning mode)
- Optionally, critique fixes from a previous iteration that MUST be resolved

Your task: author a personalised curriculum in 2–5 phases.

For each phase, write 2–4 specific learning_actions. Each action is a step YOU author —
not a restatement of a URL or article title.

Good action titles (verb-led, specific, outcome-oriented):
  ✓ "Build a SQL analytics dashboard on the NYC taxi dataset to master JOINs and window functions"
  ✓ "Implement a scikit-learn pipeline comparing Logistic Regression and XGBoost on a Kaggle dataset"
  ✓ "Contribute a beginner-friendly bug fix to an open-source pandas or scikit-learn repository"
Bad action titles (generic, just restates a resource):
  ✗ "Read tutorial: How to Improve Your SQL Skills 2026"
  ✗ "Watch Apache Spark Full Course on YouTube"

Each action must have:
  - title: concrete, specific, verb-led
  - summary: what the student will practise, build, or demonstrate
  - rationale: PERSONALISED — reference their actual skills/projects, explain exactly why this
    action closes their specific gap (e.g. "You built an XGBoost model but haven't used SQL
    directly — this project bridges that gap by querying the data you'll then model.")
  - addresses_gap: the exact quoted gap label this action primarily advances (from the list)
  - bloom_level: remember | understand | apply | analyse | evaluate | create

For each phase also write:
  - checkpoint: "After completing this phase, you will be able to [specific measurable capability]."
  - resume_updates: what to add to the resume before the NEXT phase

Rules:
1. BLOOM'S PROGRESSION: Phase 1 → remember/understand. Each phase escalates:
   apply → analyse → evaluate → create.

2. PREREQUISITE ORDERING: Any gap marked [PREREQUISITE] must be addressed by actions in a phase
   that strictly precedes the phase handling its parent gap.

3. INTERNSHIP GATING: Only include an internship action when the student has prior demonstrated
   practice (project or tutorial) for that gap in an earlier phase. The preceding phase must
   declare resume_updates for that skill. Apply ZPD judgement based on academic level and
   current proficiency.

4. LEARNING MODE BIAS:
   - structured    → sequence conceptual before applied actions
   - project_based → lead with build/create actions
   - self_paced    → lead with documentation/tutorial actions
   - mixed         → balance conceptual and applied

5. ADDRESSES_GAP: must be one of the EXACT strings from the "VALID ADDRESSES_GAP LABELS"
   numbered list — copy the string character-for-character. NEVER use a prerequisite concept
   label. NEVER paraphrase or shorten a gap label.

6. PERSONALISATION: Always reference the student's specific background in rationale fields.
   A student with XGBoost experience needs a different rationale than one with none.

7. WEEKS_ESTIMATE: realistic per-phase estimate. Sum should approach the target timeline.

8. CRITIQUE FIXES: address every fix provided. Do not reintroduce previously flagged issues.
"""


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def _format_student_context(
    student_model: Optional[StudentModel],
    evidence_items: List[EvidenceItem],
) -> str:
    if not student_model and not evidence_items:
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
    lines = ["VALID ADDRESSES_GAP LABELS — copy these EXACTLY into every addresses_gap field:"]
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


def _format_fixes(critique: Optional[CritiqueReport]) -> str:
    if not critique or not critique.fixes:
        return ""
    block = "\n".join(f"  - {f}" for f in critique.fixes)
    return f"CRITIQUE FIXES TO ADDRESS IN THIS REVISION:\n{block}"


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
) -> _PlanSpec:
    """
    Ask the LLM to author a personalised curriculum (learning_actions per phase).
    Retrieved resources are passed as example references, not the plan's primary content.
    """
    role_title   = role_spec.canonical_role_title if role_spec else "the target role"
    student_ctx  = _format_student_context(student_model, evidence_items or [])
    fixes_block  = _format_fixes(critique)

    user_prompt = f"""\
Target role: {role_title}

{student_ctx}
STUDENT CONSTRAINTS:
{_format_constraints(constraints)}

GAPS TO ADDRESS (in priority order — respect this ordering):
{_format_gap_context(ordered_items, resources_by_gap)}

{fixes_block}
Design a personalised learning pathway with 2–5 phases.
For each phase, write 2–4 specific learning_actions that YOU author (see system prompt for format).
Use the example resources as references you may attach to actions, but the action titles and
rationale must be your own authored curriculum — not restatements of resource titles.

"""

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)
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
) -> CareerPlan:
    """
    Map the LLM _PlanSpec to a CareerPlan:
    - Attach retrieved resources to each LearningAction as example_resources.
    - Derive phase.addresses_gaps from the actions (no LLM double-output).
    - Derive phase.resources from all example_resources for critique compatibility.
    """
    _phase_prefix = re.compile(r"^phase\s*\d+\s*[:\-–]\s*", re.IGNORECASE)

    phases: List[PlanPhase] = []

    for spec in plan_spec.phases:
        learning_actions: List[LearningAction] = []
        seen_keys: set = set()
        phase_resources: List[LearningResource] = []

        for action_spec in spec.learning_actions:
            gap_label = action_spec.addresses_gap
            bloom     = action_spec.bloom_level if action_spec.bloom_level in _VALID_BLOOM else "apply"

            # Attach retrieved resources that match this action's gap
            action_resources = resources_by_gap.get(gap_label, [])

            learning_actions.append(LearningAction(
                title=action_spec.title,
                summary=action_spec.summary,
                rationale=action_spec.rationale,
                addresses_gap=gap_label,
                bloom_level=bloom,
                example_resources=action_resources,
            ))

            # Accumulate deduplicated phase.resources for critique node
            for r in action_resources:
                key = (r.title, r.resource_type)
                if key not in seen_keys:
                    seen_keys.add(key)
                    phase_resources.append(r)

        # Derive addresses_gaps from actions (ordered, deduplicated)
        addresses_gaps = list(dict.fromkeys(a.addresses_gap for a in learning_actions))

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
        ))

    return CareerPlan(
        timeline_weeks=sum(p.weeks for p in phases),
        phases=phases,
    )
