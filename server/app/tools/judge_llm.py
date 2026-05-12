from __future__ import annotations

import random
import statistics
from typing import Dict, List, Tuple

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.state import CareerPlan, RoleSpecModel


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class _DimScore(BaseModel):
    score: int = Field(ge=1, le=5)
    reasoning: str


class _PlanEval(BaseModel):
    precision: _DimScore
    gap_specificity: _DimScore
    level_appropriateness: _DimScore
    actionability: _DimScore


class _JudgeResult(BaseModel):
    plan_a: _PlanEval
    plan_b: _PlanEval


_DIMS = ["precision", "gap_specificity", "level_appropriateness", "actionability"]

_SYSTEM = """\
You are an expert career counselor evaluating career development plans.

You will be given a student resume, a list of role requirements, and two anonymised plans
(Plan A and Plan B). Rate each plan INDEPENDENTLY on four dimensions using a 1–5 integer
scale. Do not compare the plans to each other — evaluate each against the resume and role.

Dimensions:
  precision             — Does the plan avoid recommending skills the student has already
                          clearly demonstrated in their resume?
  gap_specificity       — Are the identified gaps specific to this student's weaknesses,
                          not just a generic list of role requirements?
  level_appropriateness — Are recommendations calibrated to the student's actual demonstrated
                          skill level (not too basic, not too advanced)?
  actionability         — Are recommendations concrete and achievable given the student's
                          current state (specific resources, clear next steps)?

Scale: 1 = Very poor  2 = Poor  3 = Acceptable  4 = Good  5 = Excellent

For each dimension provide a score and a one-sentence reasoning.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_plan(plan: CareerPlan) -> str:
    lines = [f"Timeline: {plan.timeline_weeks} weeks", ""]
    for i, phase in enumerate(plan.phases, 1):
        lines.append(f"Phase {i}: {phase.title} ({phase.weeks} weeks)")
        lines.append(f"  Outcome: {phase.outcome}")
        if phase.addresses_gaps:
            lines.append(f"  Addresses: {', '.join(phase.addresses_gaps[:5])}")
        for action in phase.learning_actions[:3]:
            desc = action.description[:120] + ("..." if len(action.description) > 120 else "")
            lines.append(f"  - {action.title}: {desc}")
        lines.append("")
    return "\n".join(lines)


def _eval_to_dict(eval_: _PlanEval) -> Dict[str, int]:
    return {dim: getattr(eval_, dim).score for dim in _DIMS}


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def evaluate_plans_blind(
    resume_markdown: str,
    role_spec: RoleSpecModel,
    plan_full: CareerPlan,
    plan_selfreport: CareerPlan,
    k: int = 5,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    Blind LLM-as-judge evaluation (Zheng et al., 2023).

    Runs K independent calls. Each call randomly assigns which plan is 'A'
    and which is 'B' to control for position bias. Returns aggregated scores
    as (full_scores, selfreport_scores), each a dict with keys:
      precision, gap_specificity, level_appropriateness, actionability,
      overall  (mean across dims)
      <dim>_stdev  for every numeric key
    """
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7)
    llm_struct = llm.with_structured_output(
        _JudgeResult, method="json_schema", strict=True
    )

    req_list = "\n".join(
        f"- [{r.category}] {r.req_summary}" for r in role_spec.requirements
    )
    resume_snippet = resume_markdown[:3000]

    raw_full: Dict[str, List[int]] = {d: [] for d in _DIMS}
    raw_sr:   Dict[str, List[int]] = {d: [] for d in _DIMS}

    for _ in range(k):
        full_is_a = random.random() < 0.5
        plan_a = plan_full if full_is_a else plan_selfreport
        plan_b = plan_selfreport if full_is_a else plan_full

        user_msg = (
            f"Target role: {role_spec.canonical_role_title}\n\n"
            f"Role requirements:\n{req_list}\n\n"
            f"Student resume (excerpt):\n{resume_snippet}\n\n"
            f"Plan A:\n{_format_plan(plan_a)}\n\n"
            f"Plan B:\n{_format_plan(plan_b)}"
        )

        result: _JudgeResult = llm_struct.invoke(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user",   "content": user_msg},
            ]
        )

        full_eval = result.plan_a if full_is_a else result.plan_b
        sr_eval   = result.plan_b if full_is_a else result.plan_a

        for dim in _DIMS:
            raw_full[dim].append(getattr(full_eval, dim).score)
            raw_sr[dim].append(getattr(sr_eval,   dim).score)

    def _agg(raw: Dict[str, List[int]]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        all_scores: List[int] = []
        for dim, vals in raw.items():
            out[dim]              = round(statistics.mean(vals), 4)
            out[f"{dim}_stdev"]   = round(statistics.stdev(vals) if len(vals) > 1 else 0.0, 4)
            all_scores.extend(vals)
        out["overall"]       = round(statistics.mean(all_scores), 4)
        out["overall_stdev"] = round(statistics.stdev(all_scores) if len(all_scores) > 1 else 0.0, 4)
        return out

    return _agg(raw_full), _agg(raw_sr)
