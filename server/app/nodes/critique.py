from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from langchain_openai import ChatOpenAI

from app.state import (
    AgentState,
    CareerPlan,
    CritiqueReport,
    GapReport,
    StudentConstraints,
)

# ---------------------------------------------------------------------------
# Rubric thresholds — conjunctive satisficing (Simon, 1955)
# No dimension's score can compensate for another's failure.
# ---------------------------------------------------------------------------

_THRESHOLDS: Dict[str, int] = {
    "gap_coverage":          4,   # raised from 3 — plan may miss at most 1 gap before failing
    "jit_compliance":        4,   # high bar — every phase must lead with applied projects
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
# Dimension 2: Just-in-time (JIT) compliance
# Every phase must lead with at least one applied project (bloom_level ≥ apply).
# Additionally, phase titles must not signal a conceptual preamble (e.g. "Foundations
# of X", "Introduction to Y") — this check is independent of the LLM-controlled
# bloom_level field and cannot be trivially gamed.
# ---------------------------------------------------------------------------

_APPLIED_BLOOM: set = {"apply", "analyse", "evaluate", "create"}

_FOUNDATION_KEYWORDS: set = {
    "foundation", "foundations", "introduction", "intro", "basics",
    "overview", "theory", "fundamentals", "concepts", "prerequisite",
    "prerequisites",
}


def _check_jit_compliance(
    plan: CareerPlan,
    gap_report: GapReport,  # kept for dispatch-loop compatibility
) -> Tuple[int, List[str]]:
    issues: List[str] = []

    for i, phase in enumerate(plan.phases):
        # Bloom-level check (LLM-controlled — defence-in-depth only)
        has_applied = any(
            a.bloom_level in _APPLIED_BLOOM for a in phase.learning_actions
        )
        if not has_applied:
            issues.append(
                f"Phase {i + 1} ('{phase.title}') has no applied project "
                f"(bloom_level ≥ 'apply'). Foundations must be embedded in projects, "
                f"not isolated in a standalone conceptual phase."
            )

        # Title keyword check — structural signal independent of self-reported bloom_level
        title_words = set(phase.title.lower().split())
        if title_words & _FOUNDATION_KEYWORDS:
            issues.append(
                f"Phase {i + 1} title ('{phase.title}') suggests a conceptual preamble. "
                f"Every phase must lead with a concrete applied project — "
                f"foundations are embedded within projects, not frontloaded."
            )

    if not issues:
        return 5, []

    score = max(1, 5 - len(issues))
    return score, issues


# ---------------------------------------------------------------------------
# Dimension 3: Feasibility
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

    # --- Overshoot (unchanged) ---
    if delta > 0:
        issues = [
            f"Plan runs {actual}w but target is {target}w "
            f"({round(overshoot_pct * 100)}% over budget — {delta}w excess)."
        ]
        if overshoot_pct <= 0.10:
            return 3, issues
        elif overshoot_pct <= 0.25:
            return 2, issues
        else:
            return 1, issues

    # --- Underplanning ---
    # Applied universally via utilisation ratio — no target-length carve-out.
    # Thresholds (< 0.30 hard fail, < 0.45 marginal) are empirically-motivated
    # design parameters that prevent degenerate plans; optimal values are a
    # function of the student's constraint set and left for future calibration.
    undershoot_ratio = actual / target
    if undershoot_ratio < 0.30:
        return 2, [
            f"Plan is only {actual}w against a {target}w target "
            f"({round(undershoot_ratio * 100)}% of available time). "
            f"The plan is too short to comprehensively address all gaps — "
            f"expand phases or add phases to use more of the available time."
        ]
    if undershoot_ratio < 0.45:
        return 3, [
            f"Plan is {actual}w against a {target}w target "
            f"({round(undershoot_ratio * 100)}% of available time). "
            f"Consider expanding the plan to make fuller use of the available time."
        ]

    return 5, []


# ---------------------------------------------------------------------------
# Dimension 4: Level appropriateness
# Projects must suit the student's academic level.
# All levels: Phase 1 must contain at least one applied project.
# Advanced students (senior/grad/working_professional): Phase 1 projects must each
# address ≥ 2 gaps — single-gap projects are too narrow for integrative advanced work.
# This uses the addresses_gaps list length (structural, not LLM-self-reported).
# ---------------------------------------------------------------------------

_ADVANCED_LEVELS: set = {"senior", "grad", "working_professional"}


def _check_level_appropriateness(
    plan: CareerPlan,
    constraints: StudentConstraints,
) -> Tuple[int, List[str]]:
    issues: List[str] = []
    level = constraints.academic_level

    if not plan.phases:
        return 5, []

    phase1 = plan.phases[0]

    # All levels: Phase 1 must contain at least one applied project (bloom check)
    has_applied_in_phase1 = any(
        a.bloom_level in _APPLIED_BLOOM for a in phase1.learning_actions
    )
    if not has_applied_in_phase1:
        issues.append(
            f"Phase 1 ('{phase1.title}') has no applied project at bloom_level ≥ 'apply' "
            f"(student level: {level}). Every student starts with a project."
        )

    # Advanced students: Phase 1 projects must each address ≥ 2 gaps.
    # Single-gap projects are too narrow — advanced learners need integrative work.
    # addresses_gaps length is structural (validated against gap report labels) and
    # cannot be trivially gamed by self-reporting bloom_level.
    if level in _ADVANCED_LEVELS:
        single_gap_actions = [
            a.title for a in phase1.learning_actions
            if len(a.addresses_gaps) < 2
        ]
        if single_gap_actions:
            issues.append(
                f"Phase 1 has single-gap projects for an advanced student ({level}): "
                f"{', '.join(single_gap_actions[:3])}. "
                f"Advanced students need integrative projects addressing ≥ 2 gaps simultaneously."
            )

    # Freshman / sophomore: Phase 1 should include scaffolding resources
    if level in ("freshman", "sophomore") and phase1.resources:
        phase1_rtypes = {r.resource_type for r in phase1.resources}
        if not phase1_rtypes & {"tutorial", "online_course", "documentation"}:
            issues.append(
                f"Phase 1 has no tutorial, course, or documentation resources "
                f"for scaffolding (student level: {level})."
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
- Scores from a deterministic rubric (gap_coverage, jit_compliance, feasibility,
  level_appropriateness) each out of 5 with their minimum passing thresholds
- A list of specific issues the rubric detected
- Optionally, the structure of the previous plan iteration for comparison

Your task is to write a NARRATIVE FEEDBACK paragraph (150–250 words) that:
1. Explains WHY each failing dimension scored what it did — reference specific phases,
   projects, and gap names by name
2. Identifies the root cause of the problem, not just the symptom (e.g. if gap coverage
   is low, is it because phases are too broad, the timeline is too tight, or certain gaps
   are being crowded out?)
3. Gives concrete, reasoned strategic guidance for the NEXT planning iteration — what
   structural change would most improve the scores? (e.g. "split Phase 2 into two phases",
   "compress Phase 1 to 2 weeks to make room", "move gap X earlier because Y depends on it")
4. Acknowledges what the plan DID get right — reinforcing correct decisions helps the
   planner avoid regressing them

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
    phase_lines = []
    for i, phase in enumerate(plan.phases, 1):
        gaps     = ", ".join(phase.addresses_gaps[:6]) or "none"
        projects = "; ".join(a.title for a in phase.learning_actions[:3])
        phase_lines.append(
            f"  Phase {i}: '{phase.title}' ({phase.weeks}w) | "
            f"projects: [{projects}] | gaps: [{gaps}]"
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
        f"RUBRIC SCORES (threshold \u2265 listed value to pass):\n"
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
            + "\nNote what structural changes were made between the previous plan and "
              "this one, and whether those changes helped or introduced new issues.\n"
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
    Critique (Reflexion agent — Shinn et al., 2023):
    1. Capture previous critique issues at the start (for stall detection by the router).
    2. Run all four rubric dimensions independently — deterministic, auditable.
    3. Apply conjunctive satisficing: all dimensions must meet their threshold.
    4. If not satisfactory, call _reflect() to produce narrative feedback for the planner.
    5. Track best_plan across iterations (best mean rubric score).
    6. Increment critique_iterations.
    """
    s = AgentState.model_validate(state)
    s.step = "critique"

    print(f"[CRITIQUE] Iteration #{s.critique_iterations + 1}. plan={'present' if s.plan else 'MISSING'}, gap_report={'present' if s.gap_report else 'MISSING'}", flush=True)

    if not s.plan or not s.student_constraints or not s.gap_report:
        print("[CRITIQUE] ERROR: plan, student_constraints, or gap_report missing.", flush=True)
        s.errors.append("critique: plan, student_constraints, or gap_report missing.")
        return s.model_dump(exclude_none=True)

    # Capture previous issues BEFORE overwriting (router uses prev vs current for stall detection)
    s.prev_critique_issues = list(s.critique.issues) if s.critique else []

    rubric_scores: Dict[str, int] = {}
    issues: List[str] = []

    for dim_fn, dim_key in [
        (_check_gap_coverage,          "gap_coverage"),
        (_check_jit_compliance,        "jit_compliance"),
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

    score_str = ", ".join(f"{k}={v}/{_THRESHOLDS[k]}" for k, v in rubric_scores.items())
    print(f"[CRITIQUE] Scores: {score_str}. satisfactory={satisfactory}", flush=True)
    if issues:
        for iss in issues:
            print(f"[CRITIQUE]   issue: {iss}", flush=True)

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
    print(f"[CRITIQUE] best_critique_score now {s.best_critique_score:.2f}. Total iterations: {s.critique_iterations}", flush=True)

    return s.model_dump(exclude_none=True)
