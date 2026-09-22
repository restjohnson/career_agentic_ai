"""
Golden tests for app/tools/posterior.py — Stage 3 arithmetic.

Every value here is taken directly from COMPASS_Implementation_Spec.md §10.
This module is pure arithmetic and is meant to be validated against these
hand-computed examples before any model call exists (spec §14).
"""
from __future__ import annotations

import pytest

from app.compass_config import DEPTH_THRESHOLDS, PRIOR_ALPHA, PRIOR_BETA, PRIOR_MASS
from app.state import Requirement, RequirementState
from app.tools.posterior import (
    aggregate_posterior,
    assign_disposition,
    classify_gap,
    diagnostic_cost,
    diagnostic_form,
    estimate,
    evidential_mass,
    omega,
    p_met,
    select_actionable,
    strongest_type,
    variance,
)

# ---------------------------------------------------------------------------
# Golden item sets, spec §10 notation: (type, quality, relevance)
# ---------------------------------------------------------------------------

T1 = []
T2 = [("claim", 0.10, 0.90)]
T3 = [("experience", 0.90, 0.90)]
T4 = [("experience", 0.90, 0.0)]
T5 = [("experience", 0.90, 0.10)]
T6 = [("experience", 0.30, 0.50), ("project", 0.90, 0.90), ("claim", 0.10, 0.90)]
T7 = [("coursework", 0.70, 0.90)] * 4
T8 = [("experience", 0.90, 0.90)] * 2


# ---------------------------------------------------------------------------
# Posterior table
# ---------------------------------------------------------------------------

class TestPosterior:

    @pytest.mark.parametrize(
        "items, exp_alpha, exp_beta, exp_estimate, exp_variance, exp_mass",
        [
            (T1, 1.0000, 3.0000, 0.2500, 0.037500, 0.0000),
            (T2, 1.0225, 3.2025, 0.2420, 0.035109, 0.2250),
            (T3, 3.4300, 3.2700, 0.5119, 0.032449, 2.7000),
            (T4, 1.0000, 3.0000, 0.2500, 0.037500, 0.0000),
            (T5, 1.2700, 3.0300, 0.2953, 0.039268, 0.3000),
            (T6, 3.0925, 4.4325, 0.4110, 0.028396, 3.5250),
            (T7, 3.5200, 4.0800, 0.4632, 0.028912, 3.6000),
            (T8, 5.8600, 3.5400, 0.6234, 0.022574, 5.4000),
        ],
        ids=["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"],
    )
    def test_golden_posterior(self, items, exp_alpha, exp_beta, exp_estimate, exp_variance, exp_mass):
        alpha, beta = aggregate_posterior(items)
        assert alpha == pytest.approx(exp_alpha, abs=1e-4)
        assert beta == pytest.approx(exp_beta, abs=1e-4)
        assert estimate(alpha, beta) == pytest.approx(exp_estimate, abs=1e-4)
        assert variance(alpha, beta) == pytest.approx(exp_variance, abs=1e-6)
        assert evidential_mass(alpha, beta) == pytest.approx(exp_mass, abs=1e-4)

    def test_T4_zero_relevance_leaves_posterior_at_prior(self):
        """
        The regression test that matters most (spec §10): a strong item with
        zero relevance must leave the posterior at the prior. If it doesn't,
        relevance has been folded into the success proportion and every
        estimate in the system is biased downward.
        """
        alpha, beta = aggregate_posterior(T4)
        assert alpha == pytest.approx(PRIOR_ALPHA, abs=1e-9)
        assert beta == pytest.approx(PRIOR_BETA, abs=1e-9)


# ---------------------------------------------------------------------------
# p_met by depth
# ---------------------------------------------------------------------------

class TestPMet:

    @pytest.mark.parametrize(
        "items, expected_by_depth",
        [
            (T1, [0.8574, 0.5120, 0.2160, 0.0640]),
            (T3, [0.9995, 0.9588, 0.7156, 0.3307]),
            (T6, [0.9977, 0.8911, 0.5058, 0.1458]),
            (T8, [1.0000, 0.9975, 0.9190, 0.5789]),
        ],
        ids=["T1", "T3", "T6", "T8"],
    )
    def test_golden_p_met(self, items, expected_by_depth):
        alpha, beta = aggregate_posterior(items)
        for depth, expected in enumerate(expected_by_depth):
            assert p_met(alpha, beta, depth) == pytest.approx(expected, abs=1e-4)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassifyGap:

    @pytest.mark.parametrize(
        "items, depth, expected",
        [
            (T1, 0, "no_evidence"), (T1, 1, "no_evidence"), (T1, 2, "no_evidence"), (T1, 3, "no_evidence"),
            (T2, 0, "claimed_only"), (T2, 1, "claimed_only"), (T2, 2, "claimed_only"), (T2, 3, "claimed_only"),
            (T3, 1, "met"),
            (T3, 2, "uncertain"),
            (T3, 3, "uncertain"),
            (T5, 3, "unmet"),
            (T6, 1, "met"),
            (T6, 2, "uncertain"),
            (T7, 2, "uncertain"),
            (T8, 2, "met"),
            (T8, 3, "partial"),
        ],
    )
    def test_golden_classification(self, items, depth, expected):
        alpha, beta = aggregate_posterior(items)
        mass = evidential_mass(alpha, beta)
        strongest = strongest_type(items)
        pm = p_met(alpha, beta, depth)
        assert classify_gap(mass, strongest, pm) == expected

    def test_T3_vs_T8_mass_gate(self):
        """
        T3 depth2 and T8 depth3 have similar p_met but different mass —
        the pair that exercises the mass gate rather than a variance gate.
        """
        a3, b3 = aggregate_posterior(T3)
        a8, b8 = aggregate_posterior(T8)
        assert classify_gap(evidential_mass(a3, b3), strongest_type(T3), p_met(a3, b3, 2)) == "uncertain"
        assert classify_gap(evidential_mass(a8, b8), strongest_type(T8), p_met(a8, b8, 3)) == "partial"


# ---------------------------------------------------------------------------
# Disposition / diagnostic form / omega
# ---------------------------------------------------------------------------

class TestDispositionAndOmega:

    def test_met_always_satisfied(self):
        assert assign_disposition("met", selected=True) == "satisfied"
        assert assign_disposition("met", selected=False) == "satisfied"

    def test_uncertain_always_verify(self):
        assert assign_disposition("uncertain", selected=True) == "verify"
        assert assign_disposition("uncertain", selected=False) == "verify"

    @pytest.mark.parametrize("gap_type", ["no_evidence", "claimed_only", "partial", "unmet"])
    def test_actionable_selected_vs_deferred(self, gap_type):
        assert assign_disposition(gap_type, selected=True) == "remediate"
        assert assign_disposition(gap_type, selected=False) == "defer"

    def test_diagnostic_form_by_importance(self):
        assert diagnostic_form(importance=5) == "external_validation"
        assert diagnostic_form(importance=4) == "external_validation"
        assert diagnostic_form(importance=3) == "artifact_submission"
        assert diagnostic_cost("artifact_submission") == 0.5
        assert diagnostic_cost("external_validation") == 8.0

    def test_omega_uses_the_one_depth_threshold_map(self):
        """
        omega's numerator must use the same DEPTH_THRESHOLDS as p_met — a
        second (e.g. linear) map would disagree with it at every level.
        """
        for depth in range(4):
            demand = DEPTH_THRESHOLDS[depth]
            # est == demand -> omega's numerator is exactly zero
            assert omega(importance=5, required_depth=depth, est=demand, closure_cost=2.0) == pytest.approx(0.0, abs=1e-9)

    def test_omega_negative_when_estimate_exceeds_demand(self):
        assert omega(importance=5, required_depth=1, est=0.9, closure_cost=2.0) < 0


# ---------------------------------------------------------------------------
# select_actionable — budget accounting and partition
# ---------------------------------------------------------------------------

def _req(rid: str, importance: int, depth: int) -> Requirement:
    return Requirement(
        id=rid, category="skill", description=f"req {rid}",
        required_depth=depth, importance=importance, provenance="grounded", source_ref="X",
    )


def _state(rid: str, gap_type: str, est: float, closure_cost: float) -> RequirementState:
    return RequirementState(
        requirement_id=rid, alpha=1.0, beta=3.0, estimate=est, variance=0.01,
        evidential_mass=1.0, p_met=0.5, gap_type=gap_type, closure_cost_est=closure_cost,
    )


class TestSelectActionable:

    def test_partition_covers_every_requirement_exactly_once(self):
        reqs = {r.id: r for r in [_req("a", 5, 3), _req("b", 2, 1), _req("c", 4, 2)]}
        states = [
            _state("a", "met", 0.8, 1.0),
            _state("b", "uncertain", 0.4, 1.0),
            _state("c", "unmet", 0.1, 2.0),
        ]
        result = select_actionable(states, reqs, available_hours=100)
        all_ids = result.satisfied_ids | result.verify_ids | result.remediate_ids | result.defer_ids
        assert all_ids == {"a", "b", "c"}
        assert len(all_ids) == 3  # no overlap between sets

    def test_met_goes_to_satisfied_not_deferral(self):
        reqs = {"a": _req("a", 5, 3)}
        states = [_state("a", "met", 0.9, 1.0)]
        result = select_actionable(states, reqs, available_hours=10)
        assert result.satisfied_ids == {"a"}
        assert not result.defer_ids

    def test_uncertain_goes_to_verify(self):
        reqs = {"a": _req("a", 5, 3)}
        states = [_state("a", "uncertain", 0.4, 1.0)]
        result = select_actionable(states, reqs, available_hours=100)
        assert result.verify_ids == {"a"}

    def test_infeasible_when_verify_alone_exhausts_budget(self):
        # importance>=4 -> external_validation (8h) diagnostic cost; tiny available_hours
        reqs = {"a": _req("a", 5, 3), "b": _req("b", 5, 1)}
        states = [
            _state("a", "uncertain", 0.4, 1.0),
            _state("b", "unmet", 0.1, 1.0),
        ]
        result = select_actionable(states, reqs, available_hours=1)  # 0.7*1=0.7 << 8+1
        assert result.infeasible is True
        assert result.defer_ids == {"b"}

    def test_higher_omega_selected_first_under_tight_budget(self):
        # both actionable, budget only fits one — higher omega (bigger gap, cheaper) wins
        reqs = {"cheap_urgent": _req("cheap_urgent", 5, 3), "expensive_minor": _req("expensive_minor", 1, 1)}
        states = [
            _state("cheap_urgent", "unmet", 0.05, 1.0),      # big demand-estimate gap, cheap
            _state("expensive_minor", "unmet", 0.15, 10.0),  # small importance, expensive
        ]
        result = select_actionable(states, reqs, available_hours=10)  # budget = 0.7*10 = 7
        assert "cheap_urgent" in result.remediate_ids
        assert "expensive_minor" in result.defer_ids
