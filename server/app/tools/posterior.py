"""
posterior.py — Stage 3 (Gap Analysis) arithmetic. Pure functions: no I/O, no
LLM calls. Every number here is computed from model-supplied classifications
(type, quality, relevance, importance, closure cost) — never asked of the
model directly. See COMPASS_Implementation_Spec.md §4 Stage 3 and §11.

Relevance scales the evidence weight; quality splits it into alpha/beta.
Collapsing them into one product (x = quality * relevance) is the "natural
mistake" the spec calls out — it makes barely-relevant items count as
evidence the student CANNOT do something. Do not do that here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from scipy.stats import beta as beta_dist

from app.compass_config import (
    CAPACITY_DISCOUNT,
    DEPTH_THRESHOLDS,
    DIAGNOSTIC_COST,
    EXTERNAL_VALIDATION_IMPORTANCE,
    MET_THRESHOLD,
    PRIOR_ALPHA,
    PRIOR_BETA,
    PRIOR_MASS,
    TYPE_WEIGHTS,
    UNMET_THRESHOLD,
)
from app.state import EvidenceItemType, GapType, Requirement, RequirementState

# ---------------------------------------------------------------------------
# Step 3 — effective weight
# ---------------------------------------------------------------------------

def effective_weight(item_type: EvidenceItemType, relevance: float) -> float:
    """effective_weight[i,r] = w(type[i]) x relevance[i,r]."""
    return TYPE_WEIGHTS[item_type] * relevance

# ---------------------------------------------------------------------------
# Step 4 — posterior
# ---------------------------------------------------------------------------

def compute_posterior(weighted_qualities: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    """
    weighted_qualities: [(quality, effective_weight), ...] for the items
    matched to one requirement. Prior is Beta(PRIOR_ALPHA, PRIOR_BETA).

    alpha = PRIOR_ALPHA + sum(w * q)
    beta  = PRIOR_BETA  + sum(w * (1 - q))
    """
    alpha = PRIOR_ALPHA
    beta = PRIOR_BETA
    for quality, weight in weighted_qualities:
        alpha += weight * quality
        beta += weight * (1.0 - quality)
    return alpha, beta


def aggregate_posterior(items: Sequence[Tuple[EvidenceItemType, float, float]]) -> Tuple[float, float]:
    """
    Convenience wrapper matching the spec's golden-test notation directly:
    items = [(type, quality, relevance), ...] -> (alpha, beta).
    """
    weighted = [(quality, effective_weight(item_type, relevance)) for item_type, quality, relevance in items]
    return compute_posterior(weighted)

# ---------------------------------------------------------------------------
# Step 5 — derived quantities
# ---------------------------------------------------------------------------

def estimate(alpha: float, beta: float) -> float:
    return alpha / (alpha + beta)


def variance(alpha: float, beta: float) -> float:
    total = alpha + beta
    return (alpha * beta) / (total ** 2 * (total + 1))


def evidential_mass(alpha: float, beta: float) -> float:
    """Total effective weight fed into the posterior; PRIOR_MASS subtracted out."""
    return (alpha + beta) - PRIOR_MASS


def p_met(alpha: float, beta: float, required_depth: int) -> float:
    """
    1 - BetaCDF(t[required_depth]; alpha, beta). Computed from the whole
    distribution against required depth, not by thresholding a point
    estimate — this is what lets a confident estimate slightly below
    threshold differ from an uncertain one slightly above.
    """
    threshold = DEPTH_THRESHOLDS[required_depth]
    return 1.0 - float(beta_dist.cdf(threshold, alpha, beta))

# ---------------------------------------------------------------------------
# strongest_type — the highest-weight type among items that actually
# contributed evidence (effective_weight > 0). None if no item contributed.
# ---------------------------------------------------------------------------

def strongest_type(items: Sequence[Tuple[EvidenceItemType, float, float]]) -> Optional[EvidenceItemType]:
    contributing = [(item_type, relevance) for item_type, _quality, relevance in items if relevance > 0]
    if not contributing:
        return None
    return max(contributing, key=lambda pair: TYPE_WEIGHTS[pair[0]])[0]

# ---------------------------------------------------------------------------
# Step 6 — gap classification. Evaluated in order; first match wins.
# ---------------------------------------------------------------------------

def classify_gap(
    mass: float,
    strongest: Optional[EvidenceItemType],
    p_met_value: float,
) -> GapType:
    if mass == 0:
        return "no_evidence"
    if strongest == "claim":
        return "claimed_only"
    if p_met_value > MET_THRESHOLD:
        return "met"
    if UNMET_THRESHOLD < p_met_value <= MET_THRESHOLD:
        return "uncertain" if mass < PRIOR_MASS else "partial"
    return "unmet"  # p_met_value <= UNMET_THRESHOLD

# ---------------------------------------------------------------------------
# Step 7 — disposition, diagnostic form/cost, budget accounting, selection
# ---------------------------------------------------------------------------

def assign_disposition(gap_type: GapType, selected: bool) -> str:
    if gap_type == "met":
        return "satisfied"
    if gap_type == "uncertain":
        return "verify"
    return "remediate" if selected else "defer"


def diagnostic_form(importance: int) -> str:
    return "external_validation" if importance >= EXTERNAL_VALIDATION_IMPORTANCE else "artifact_submission"


def diagnostic_cost(form: str) -> float:
    return DIAGNOSTIC_COST[form]


def omega(importance: int, required_depth: int, est: float, closure_cost: float) -> float:
    """
    Selection priority for actionable (non-met, non-uncertain) gaps.
    Vanishes exactly where p_met crosses its threshold, since t[] is the
    SAME depth->quality map p_met uses — no second, linear map.
    """
    demand = DEPTH_THRESHOLDS[required_depth]
    safe_cost = closure_cost if closure_cost > 0 else 1e-9
    return importance * (demand - est) / safe_cost


@dataclass
class SelectionResult:
    satisfied_ids: Set[str] = field(default_factory=set)
    verify_ids: Set[str] = field(default_factory=set)
    remediate_ids: Set[str] = field(default_factory=set)
    defer_ids: Set[str] = field(default_factory=set)
    infeasible: bool = False
    budget_remaining: float = 0.0


def select_actionable(
    states: Sequence[RequirementState],
    requirements_by_id: Dict[str, Requirement],
    available_hours: float,
) -> SelectionResult:
    """
    Partitions every requirement into exactly one of
    {satisfied, verify, remediate, defer} (spec §4 Step 7).

    Verify work is priced before remediation is selected: diagnostics cost
    real hours in phase 1, and pessimistic evaluation means their
    requirements also occupy hours later.
    """
    result = SelectionResult()
    candidates: List[RequirementState] = []

    for state in states:
        if state.gap_type == "met":
            result.satisfied_ids.add(state.requirement_id)
        elif state.gap_type == "uncertain":
            result.verify_ids.add(state.requirement_id)
        else:
            candidates.append(state)

    verify_cost = 0.0
    for rid in result.verify_ids:
        req = requirements_by_id[rid]
        state = next(s for s in states if s.requirement_id == rid)
        verify_cost += diagnostic_cost(diagnostic_form(req.importance)) + state.closure_cost_est

    budget = CAPACITY_DISCOUNT * available_hours - verify_cost

    if budget <= 0:
        result.infeasible = True
        result.budget_remaining = budget
        for state in candidates:
            result.defer_ids.add(state.requirement_id)
        return result

    ranked = sorted(
        candidates,
        key=lambda s: omega(
            requirements_by_id[s.requirement_id].importance,
            requirements_by_id[s.requirement_id].required_depth,
            s.estimate,
            s.closure_cost_est,
        ),
        reverse=True,
    )

    remaining = budget
    for state in ranked:
        cost = state.closure_cost_est
        if cost <= remaining:
            result.remediate_ids.add(state.requirement_id)
            remaining -= cost
        else:
            result.defer_ids.add(state.requirement_id)

    result.budget_remaining = remaining
    return result
