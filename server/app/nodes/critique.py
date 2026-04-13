from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

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
    "prerequisite_ordering": 4,   # high bar — KST compliance
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
) -> Tuple[int, List[str], List[str]]:
    addressed: Set[str] = {
        g.lower().strip()
        for phase in plan.phases
        for g in phase.addresses_gaps
    }
    all_gaps: Set[str] = {g.summary.lower().strip() for g in gap_report.gaps if g.gap_type != "met"}
    missing = all_gaps - addressed

    if not missing:
        return 5, [], []

    issues = [f"Gap not addressed by any phase: '{g}'" for g in missing]
    fixes  = [f"Extend an existing phase or add a new phase to cover: '{g}'" for g in missing]
    score  = max(1, round(5 * (1 - len(missing) / len(all_gaps))))
    return score, issues, fixes


# ---------------------------------------------------------------------------
# Dimension 2: Prerequisite ordering
# Foundational prerequisites must appear in an earlier phase than their parent gap.
# ---------------------------------------------------------------------------

def _check_prereq_ordering(
    plan: CareerPlan,
    gap_report: GapReport,
) -> Tuple[int, List[str], List[str]]:
    # Map normalised gap label → first phase index (0-based) where it appears.
    # Using first occurrence so multi-phase gaps (e.g. SQL in Phase 1 and Phase 3)
    # don't get their parent_idx pushed to the last phase by dict overwriting.
    phase_index: Dict[str, int] = {}
    for i, phase in enumerate(plan.phases):
        for g in phase.addresses_gaps:
            key = g.lower().strip()
            if key not in phase_index:
                phase_index[key] = i

    violations: List[Tuple[str, str, int, int]] = []

    for gap in gap_report.gaps:
        parent_idx = phase_index.get(gap.summary.lower().strip())
        if parent_idx is None:
            continue  # gap_coverage handles missing gaps

        for prereq in gap.knowledge_prerequisites:
            if not prereq.is_foundational:
                continue  # only enforce ordering for hard prerequisites

            prereq_idx = phase_index.get(prereq.concept.lower().strip())

            if prereq_idx is None:
                # Prerequisite concept not explicitly labeled in any phase.
                # The system prompt forbids using prereq concept labels as addresses_gap,
                # so absence from phase_index means implicit coverage within the parent
                # gap's phase — not a plan defect. Skip; only flag explicit misordering.
                pass
            elif prereq_idx >= parent_idx:
                violations.append((prereq.concept, gap.summary, prereq_idx, parent_idx))

    if not violations:
        return 5, [], []

    issues: List[str] = []
    fixes:  List[str] = []
    for prereq, parent, pi, parent_i in violations:
        if pi == -1:
            issues.append(
                f"Foundational prerequisite '{prereq}' for '{parent}' "
                f"is not addressed anywhere in the plan."
            )
            fixes.append(
                f"Add resources for '{prereq}' in a phase before the phase that covers '{parent}'."
            )
        else:
            issues.append(
                f"Prerequisite '{prereq}' (Phase {pi + 1}) must precede "
                f"its parent gap '{parent}' (Phase {parent_i + 1})."
            )
            fixes.append(
                f"Move '{prereq}' resources to a phase earlier than Phase {parent_i + 1}."
            )

    n_absent   = sum(1 for v in violations if v[2] == -1)
    n_ordering = len(violations) - n_absent
    score = max(1, 5 - n_absent * 2 - n_ordering)
    return score, issues, fixes


# ---------------------------------------------------------------------------
# Dimension 3: Feasibility
# Does the plan's total hour demand fit within the student's timeline?
# ---------------------------------------------------------------------------

def _check_feasibility(
    plan: CareerPlan,
    constraints: StudentConstraints,
) -> Tuple[int, List[str], List[str]]:
    total_hours = sum(
        r.estimated_hours
        for phase in plan.phases
        for r in phase.resources
        if r.estimated_hours is not None
    )

    if total_hours == 0:
        return 3, ["Resource hour estimates are missing; feasibility cannot be fully assessed."], []

    required_weeks   = total_hours / constraints.hours_per_week
    delta            = required_weeks - constraints.target_weeks
    overshoot_pct    = delta / constraints.target_weeks if constraints.target_weeks > 0 else 0

    if delta <= 0:
        return 5, [], []

    issues = [
        f"Plan requires ~{round(required_weeks)}w but target is {constraints.target_weeks}w "
        f"({round(overshoot_pct * 100)}% over budget — ~{round(delta)}w excess)."
    ]
    fixes: List[str] = []
    if plan.phases:
        last = plan.phases[-1]
        fixes.append(
            f"Consider deferring Phase {len(plan.phases)} ('{last.title}') "
            f"to reduce timeline by ~{last.weeks}w."
        )

    if overshoot_pct <= 0.10:
        score = 3
    elif overshoot_pct <= 0.25:
        score = 2
    else:
        score = 1

    return score, issues, fixes


# ---------------------------------------------------------------------------
# Dimension 4: Level appropriateness
# Resources must suit the student's academic level.
# ---------------------------------------------------------------------------

def _check_level_appropriateness(
    plan: CareerPlan,
    constraints: StudentConstraints,
) -> Tuple[int, List[str], List[str]]:
    issues: List[str] = []
    fixes:  List[str] = []
    level = constraints.academic_level

    # Early undergrads need conceptual resources in Phase 1
    if level in ("freshman", "sophomore") and plan.phases:
        phase1_rtypes = {r.resource_type for r in plan.phases[0].resources}
        if not phase1_rtypes & {"tutorial", "online_course", "documentation"}:
            issues.append(
                "Phase 1 has no tutorial, course, or documentation resources — "
                "required for an early-stage undergraduate to build conceptual grounding."
            )
            fixes.append(
                "Add at least one tutorial or online_course resource to Phase 1."
            )

    score = max(1, 5 - len(issues))
    return score, issues, fixes


# ---------------------------------------------------------------------------
# Main critique node
# ---------------------------------------------------------------------------

def critique_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Critique:
    1. Capture previous critique issues at the start (for stall detection by the router).
    2. Run all four rubric dimensions independently.
    3. Apply conjunctive satisficing: all dimensions must meet their threshold.
    4. Track best_plan across iterations (best mean rubric score).
    5. Increment critique_iterations.
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
    fixes:  List[str] = []

    for dim_fn, dim_key in [
        (_check_gap_coverage,          "gap_coverage"),
        (_check_prereq_ordering,       "prerequisite_ordering"),
        (_check_feasibility,           "feasibility"),
        (_check_level_appropriateness, "level_appropriateness"),
    ]:
        if dim_key in ("feasibility", "level_appropriateness"):
            score, dim_issues, dim_fixes = dim_fn(s.plan, s.student_constraints)
        else:
            score, dim_issues, dim_fixes = dim_fn(s.plan, s.gap_report)

        rubric_scores[dim_key] = score
        issues.extend(dim_issues)
        fixes.extend(dim_fixes)

    # Conjunctive satisficing — every dimension must meet its threshold
    satisfactory = all(
        rubric_scores.get(k, 0) >= v for k, v in _THRESHOLDS.items()
    )

    s.critique = CritiqueReport(
        rubric_scores=rubric_scores,
        issues=issues,
        fixes=fixes,
        satisfactory=satisfactory,
    )

    # Best-plan tracking — retain the plan with the highest mean rubric score
    mean_score = sum(rubric_scores.values()) / len(rubric_scores)
    if mean_score > s.best_critique_score:
        s.best_plan          = s.plan
        s.best_critique_score = mean_score

    s.critique_iterations += 1

    return s.model_dump(exclude_none=True)
