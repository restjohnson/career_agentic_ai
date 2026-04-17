from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from langchain_openai import ChatOpenAI

from app.state import (
    AgentState,
    CareerPlan,
    CritiqueReport,
    GapReport,
    PlanPhase,
    StudentConstraints,
)

# ---------------------------------------------------------------------------
# Rubric thresholds — conjunctive satisficing (Simon, 1955)
# No dimension's score can compensate for another's failure.
# ---------------------------------------------------------------------------

_THRESHOLDS: Dict[str, int] = {
    "gap_coverage":          3,
    "feasibility":           3,
    "level_appropriateness": 3,
}

# ---------------------------------------------------------------------------
# Dimension 1: Gap coverage
# Are all gaps from the report addressed by at least one phase?
# ---------------------------------------------------------------------------

def _check_gap_coverage(
    plan: CareerPlan,
    gap_report: GapReport,
) -> Tuple[int, List[str]]:
    addressed: Set[str] = {
        g.lower().strip()
        for phase in plan.phases
        for g in phase.addresses_gaps
    }
    all_gaps: Set[str] = {g.summary.lower().strip() for g in gap_report.gaps if g.gap_type != "met"}
    missing = all_gaps - addressed

    if not missing:
        return 5, []

    issues = [f"Gap not addressed by any phase: '{g}'" for g in missing]
    score  = max(1, round(5 * (1 - len(missing) / len(all_gaps))))
    return score, issues


# ---------------------------------------------------------------------------
# Dimension 2: Feasibility
# Does the plan's total timeline fit within the student's target?
# ---------------------------------------------------------------------------

def _check_feasibility(
    plan: CareerPlan,
    constraints: StudentConstraints,
) -> Tuple[int, List[str]]:
    target = constraints.target_weeks
    actual = plan.timeline_weeks
    delta  = actual - target
    overshoot_pct = delta / target if target > 0 else 0

    if delta <= 0:
        return 5, []

    issues = [
        f"Plan runs {actual}w but target is {target}w "
        f"({round(overshoot_pct * 100)}% over budget — {delta}w excess)."
    ]

    if overshoot_pct <= 0.10:
        score = 3
    elif overshoot_pct <= 0.25:
        score = 2
    else:
        score = 1

    return score, issues


# ---------------------------------------------------------------------------
# Dimension 3: Level appropriateness
# Resources must suit the student's academic level.
# ---------------------------------------------------------------------------

def _check_level_appropriateness(
    plan: CareerPlan,
    constraints: StudentConstraints,
) -> Tuple[int, List[str]]:
    issues: List[str] = []
    level = constraints.academic_level

    # Early undergrads need conceptual resources in Phase 1
    if level in ("freshman", "sophomore") and plan.phases:
        phase1_rtypes = {r.resource_type for r in plan.phases[0].resources}
        if not phase1_rtypes & {"tutorial", "online_course", "documentation"}:
            issues.append(
                f"Phase 1 has no tutorial, course, or documentation resources "
                f"(student level: {level})."
            )

    score = max(1, 5 - len(issues))
    return score, issues


# ---------------------------------------------------------------------------
# Reflexion — narrative feedback LLM (Shinn et al., 2023)
# Called only when the plan is not satisfactory.
# Receives the deterministic rubric verdict and reasons about WHY, then gives
# strategic guidance for the next planning iteration.
# ---------------------------------------------------------------------------

_REFLECT_SYSTEM = """\
You are a strategic curriculum advisor reviewing a student's personalised learning pathway.

You will be given:
- The student's constraints and target role
- A structured summary of the proposed plan (phases, projects, gaps addressed, week counts)
- Scores from a deterministic rubric (gap_coverage, feasibility, level_appropriateness) each out of 5 with a minimum passing threshold of 3
- A list of specific issues the rubric detected
- Optionally, the structure of the previous plan iteration for comparison

Your task is to write a NARRATIVE FEEDBACK paragraph (150–250 words) that:
1. Explains WHY each failing dimension scored what it did — reference specific phases, projects, and gap names by name
2. Identifies the root cause of the problem, not just the symptom (e.g. if gap coverage is low, is it because phases are too broad, the timeline is too tight, or certain gaps are being crowded out?)
3. Gives concrete, reasoned strategic guidance for the NEXT planning iteration — what structural change would most improve the scores? (e.g. "split Phase 2 into two phases", "compress Phase 1 to 2 weeks to make room", "address gap X earlier because projects Y and Z depend on it")
4. Acknowledges what the plan DID get right — reinforcing correct decisions helps the planner avoid regressing them

Rules:
- Be specific: name phases, projects, and gaps from the data given. Do not speak in generalities.
- Be constructive: this feedback goes directly to the curriculum planner for the next iteration.
- Do NOT use bullet points. Write continuous prose.
- Do NOT restate the rubric scores as numbers. Interpret them.
- Do NOT suggest adding internship recommendations — that is handled separately.
- Length: 150–250 words.
"""


def _reflect(
    plan: CareerPlan,
    rubric_scores: Dict[str, int],
    issues: List[str],
    constraints: StudentConstraints,
    role_title: str,
    prev_plan: Optional[CareerPlan] = None,
) -> str:
    # Build plan summary for LLM context
    phase_lines = []
    for i, phase in enumerate(plan.phases, 1):
        gaps_covered  = ", ".join(phase.addresses_gaps[:6]) or "none"
        project_titles = "; ".join(a.title for a in phase.learning_actions[:3])
        phase_lines.append(
            f"  Phase {i}: '{phase.title}' ({phase.weeks}w) | "
            f"projects: [{project_titles}] | addresses_gaps: [{gaps_covered}]"
        )
    plan_summary = "\n".join(phase_lines) if phase_lines else "  (no phases)"

    rubric_block = "\n".join(
        f"  {k}: {v}/5 (threshold: {_THRESHOLDS.get(k, 3)})"
        for k, v in rubric_scores.items()
    )

    issues_block = "\n".join(f"  - {iss}" for iss in issues) if issues else "  (none)"

    user_prompt = (
        f"TARGET ROLE: {role_title}\n\n"
        f"STUDENT CONSTRAINTS:\n"
        f"  Academic level:       {constraints.academic_level}\n"
        f"  Hours available/week: {constraints.hours_per_week}\n"
        f"  Target timeline:      {constraints.target_weeks} weeks\n"
        f"  Preferred learning:   {constraints.preferred_learning_mode}\n\n"
        f"PLAN STRUCTURE ({plan.timeline_weeks}w total, {len(plan.phases)} phases):\n"
        f"{plan_summary}\n\n"
        f"RUBRIC SCORES (threshold \u2265 3 to pass):\n"
        f"{rubric_block}\n\n"
        f"DETECTED ISSUES:\n"
        f"{issues_block}\n"
    )

    if prev_plan is not None:
        prev_lines = [
            f"  Phase {i}: '{p.title}' ({p.weeks}w)"
            for i, p in enumerate(prev_plan.phases, 1)
        ]
        user_prompt += (
            f"\nPREVIOUS PLAN STRUCTURE (iteration before this one):\n"
            + "\n".join(prev_lines)
            + "\nNote what structural changes were made between the previous plan and this one, "
              "and whether those changes helped or introduced new issues.\n"
        )

    user_prompt += "\nWrite narrative feedback for the next planning iteration."

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.4)
    response = llm.invoke([
        {"role": "system", "content": _REFLECT_SYSTEM},
        {"role": "user",   "content": user_prompt},
    ])
    return response.content.strip()


# ---------------------------------------------------------------------------
# Main critique node
# ---------------------------------------------------------------------------

def critique_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Critique (Reflexion agent):
    1. Capture previous critique issues at the start (for stall detection by the router).
    2. Run all three rubric dimensions independently — deterministic, auditable.
    3. Apply conjunctive satisficing: all dimensions must meet their threshold.
    4. If not satisfactory, call _reflect() to produce narrative feedback for the planner.
    5. Track best_plan across iterations (best mean rubric score).
    6. Increment critique_iterations.
    """
    s = AgentState.model_validate(state)
    s.step = "critique"

    if not s.plan or not s.student_constraints or not s.gap_report:
        s.errors.append("critique: plan, student_constraints, or gap_report missing.")
        return s.model_dump(exclude_none=True)

    # Capture previous issues BEFORE overwriting (router uses prev vs current for stall detection)
    s.prev_critique_issues = list(s.critique.issues) if s.critique else []

    rubric_scores: Dict[str, int] = {}
    issues: List[str] = []

    for dim_fn, dim_key in [
        (_check_gap_coverage,          "gap_coverage"),
        (_check_feasibility,           "feasibility"),
        (_check_level_appropriateness, "level_appropriateness"),
    ]:
        if dim_key in ("feasibility", "level_appropriateness"):
            score, dim_issues = dim_fn(s.plan, s.student_constraints)
        else:
            score, dim_issues = dim_fn(s.plan, s.gap_report)

        rubric_scores[dim_key] = score
        issues.extend(dim_issues)

    # Conjunctive satisficing — every dimension must meet its threshold
    satisfactory = all(
        rubric_scores.get(k, 0) >= v for k, v in _THRESHOLDS.items()
    )

    # Reflexion — generate narrative feedback only when the plan is not satisfactory.
    # No point reflecting on a passing plan; the planner will not re-run.
    narrative_feedback: Optional[str] = None
    if not satisfactory:
        role_title = (
            s.role_spec.canonical_role_title if s.role_spec else s.desired_role
        )
        try:
            narrative_feedback = _reflect(
                plan=s.plan,
                rubric_scores=rubric_scores,
                issues=issues,
                constraints=s.student_constraints,
                role_title=role_title,
                prev_plan=s.prev_plan,
            )
        except Exception as e:
            s.errors.append(f"critique: reflection LLM failed: {type(e).__name__}: {e}")
            # graceful degradation — rubric scores are still stored; loop continues

    s.critique = CritiqueReport(
        rubric_scores=rubric_scores,
        issues=issues,
        narrative_feedback=narrative_feedback,
        satisfactory=satisfactory,
    )

    # Best-plan tracking — retain the plan with the highest mean rubric score
    mean_score = sum(rubric_scores.values()) / len(rubric_scores)
    if mean_score > s.best_critique_score:
        s.best_plan           = s.plan
        s.best_critique_score = mean_score

    s.critique_iterations += 1

    return s.model_dump(exclude_none=True)
