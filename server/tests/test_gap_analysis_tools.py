"""
Unit tests for gap_analysis_tools.py

Covers:
- aggregate_proficiency: all rubric branches
- aggregate_confidence: Bayesian combination
- compute_student_scores: evidence aggregation per requirement
- compute_gaps: gap formula, gap_type classification, ranking
- finalise_knowledge_confidence: with and without self-assessment
- derive_root_causes: all root cause branches
- build_gap_report: summary text generation
- Phase1 / Phase2 node logic (LLM mocked)
"""
from __future__ import annotations

import math
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from app.state import (
    AgentState,
    EvidenceItem,
    GapItem,
    KnowledgePrerequisite,
    RoleSpecModel,
    RoleSpecRequirement,
    StudentModel,
    ProvenanceRef,
)
from app.tools.gap_analysis_tools import (
    aggregate_confidence,
    aggregate_proficiency,
    build_gap_report,
    compute_gaps,
    compute_student_scores,
    derive_root_causes,
    finalise_knowledge_confidence,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_item(
    item_type: str,
    proficiency_score: int,
    confidence: float,
    id: str = "x",
) -> EvidenceItem:
    return EvidenceItem(
        id=id,
        item_type=item_type,
        summary=f"{item_type} item",
        confidence=confidence,
        proficiency_score=proficiency_score,
    )


def make_req(
    summary: str,
    required_level: float = 3.0,
    importance: float = 3.0,
    optional: bool = False,
    category: str = "skill",
) -> RoleSpecRequirement:
    return RoleSpecRequirement(
        req_summary=summary,
        category=category,
        required_level=required_level,
        importance=importance,
        optional=optional,
        provenance=[ProvenanceRef(source_type="ONET", source_ids=["15-1252.00"])],
    )


def make_gap(
    summary: str = "Test gap",
    student_score: float = 0.0,
    required_level: float = 3.0,
    raw_gap: float = 3.0,
    weighted_gap: float = 9.0,
    proficiency: int = 0,
    confidence: float = 0.0,
    gap_type: str = "missing",
) -> GapItem:
    return GapItem(
        summary=summary,
        category="skill",
        required_level=required_level,
        student_score=student_score,
        raw_gap=raw_gap,
        weighted_gap=weighted_gap,
        proficiency=proficiency,
        confidence=confidence,
        gap_type=gap_type,
    )


def make_prereq(
    concept: str,
    parent: str,
    is_foundational: bool = True,
    inferred_confidence: float = 0.3,
    inference_tier: str = "skill_implied",
    needs_self_assessment: bool = True,
    self_assessment: int = None,
    final_confidence: float = None,
) -> KnowledgePrerequisite:
    return KnowledgePrerequisite(
        concept=concept,
        parent_skill_gap=parent,
        is_foundational=is_foundational,
        inferred_confidence=inferred_confidence,
        inference_tier=inference_tier,
        inference_basis=[],
        needs_self_assessment=needs_self_assessment,
        self_assessment=self_assessment,
        final_confidence=final_confidence,
    )


# ---------------------------------------------------------------------------
# aggregate_proficiency
# ---------------------------------------------------------------------------

class TestAggregateProficiency:

    def test_empty_returns_zero(self):
        assert aggregate_proficiency([]) == 0

    def test_only_claims_return_zero(self):
        items = [make_item("claim", 0, 0.5, id=f"c{i}") for i in range(3)]
        assert aggregate_proficiency(items) == 0

    def test_single_coursework_returns_one(self):
        items = [make_item("coursework", 1, 0.4, id="c1")]
        assert aggregate_proficiency(items) == 1

    def test_skill_item_with_proficiency_one_returns_one(self):
        items = [make_item("skill", 1, 0.3, id="s1")]
        assert aggregate_proficiency(items) == 1

    def test_single_project_returns_two(self):
        items = [make_item("project", 2, 0.6, id="p1")]
        assert aggregate_proficiency(items) == 2

    def test_project_low_proficiency_not_counted(self):
        # project with proficiency_score = 1 does NOT qualify as an independent project
        items = [make_item("project", 1, 0.6, id="p1")]
        assert aggregate_proficiency(items) == 1  # falls to coursework level

    def test_two_projects_returns_three(self):
        items = [
            make_item("project", 2, 0.6, id="p1"),
            make_item("project", 2, 0.7, id="p2"),
        ]
        assert aggregate_proficiency(items) == 3

    def test_single_experience_returns_three(self):
        items = [make_item("experience", 3, 0.8, id="e1")]
        assert aggregate_proficiency(items) == 3

    def test_professional_returns_four(self):
        items = [make_item("skill", 4, 0.9, id="s1")]
        assert aggregate_proficiency(items) == 4

    def test_professional_takes_priority_over_experience(self):
        items = [
            make_item("experience", 3, 0.8, id="e1"),
            make_item("skill", 4, 0.95, id="s1"),
        ]
        assert aggregate_proficiency(items) == 4

    def test_mixed_evidence_ranks_correctly(self):
        # coursework + one project → should be 2 (project wins over coursework)
        items = [
            make_item("coursework", 1, 0.4, id="c1"),
            make_item("project", 2, 0.6, id="p1"),
        ]
        assert aggregate_proficiency(items) == 2


# ---------------------------------------------------------------------------
# aggregate_confidence
# ---------------------------------------------------------------------------

class TestAggregateConfidence:

    def test_empty_returns_zero(self):
        assert aggregate_confidence([]) == 0.0

    def test_single_item(self):
        items = [make_item("skill", 2, 0.6, id="s1")]
        assert aggregate_confidence(items) == pytest.approx(0.6, abs=1e-4)

    def test_two_independent_items(self):
        items = [
            make_item("skill", 2, 0.6, id="s1"),
            make_item("project", 2, 0.6, id="p1"),
        ]
        expected = 1 - (0.4 * 0.4)  # 0.84
        assert aggregate_confidence(items) == pytest.approx(expected, abs=1e-4)

    def test_three_items_increases_confidence(self):
        items = [make_item("skill", 1, 0.5, id=f"i{n}") for n in range(3)]
        expected = 1 - (0.5 ** 3)  # 0.875
        assert aggregate_confidence(items) == pytest.approx(expected, abs=1e-4)

    def test_perfect_confidence_item(self):
        items = [make_item("skill", 4, 1.0, id="s1")]
        assert aggregate_confidence(items) == pytest.approx(1.0, abs=1e-4)

    def test_zero_confidence_item(self):
        items = [make_item("claim", 0, 0.0, id="c1")]
        assert aggregate_confidence(items) == pytest.approx(0.0, abs=1e-4)

    def test_weak_plus_strong_raises_confidence(self):
        items = [
            make_item("claim", 0, 0.1, id="c1"),
            make_item("project", 2, 0.8, id="p1"),
        ]
        expected = 1 - (0.9 * 0.2)  # 0.82
        assert aggregate_confidence(items) == pytest.approx(expected, abs=1e-4)


# ---------------------------------------------------------------------------
# compute_student_scores
# ---------------------------------------------------------------------------

class TestComputeStudentScores:

    def _make_state(self, items, evidence_map, reqs):
        student_model = StudentModel(evidence_map=evidence_map)
        role_spec = RoleSpecModel(
            canonical_role_title="Data Scientist",
            matched_onet_code="15-2051.00",
            requirements=reqs,
        )
        return items, student_model, role_spec

    def test_no_matching_evidence_scores_zero(self):
        req = make_req("Machine Learning")
        items, student_model, role_spec = self._make_state([], {}, [req])
        scores = compute_student_scores([], student_model, role_spec)
        assert scores["Machine Learning"]["student_score"] == 0.0
        assert scores["Machine Learning"]["proficiency"] == 0
        assert scores["Machine Learning"]["confidence"] == 0.0

    def test_single_project_match(self):
        item = make_item("project", 2, 0.6, id="p1")
        req = make_req("Python programming")
        _, student_model, role_spec = self._make_state(
            [item], {"Python programming": ["p1"]}, [req]
        )
        scores = compute_student_scores([item], student_model, role_spec)
        s = scores["Python programming"]
        assert s["proficiency"] == 2
        assert s["confidence"] == pytest.approx(0.6, abs=1e-4)
        assert s["student_score"] == pytest.approx(2 * 0.6, abs=1e-4)

    def test_multiple_items_aggregate(self):
        item1 = make_item("project", 2, 0.6, id="p1")
        item2 = make_item("experience", 3, 0.8, id="e1")
        req = make_req("Python programming")
        _, student_model, role_spec = self._make_state(
            [item1, item2], {"Python programming": ["p1", "e1"]}, [req]
        )
        scores = compute_student_scores([item1, item2], student_model, role_spec)
        s = scores["Python programming"]
        expected_prof = 3  # experience → rubric level 3
        expected_conf = round(1 - (0.4 * 0.2), 4)  # 0.92
        assert s["proficiency"] == expected_prof
        assert s["confidence"] == pytest.approx(expected_conf, abs=1e-4)

    def test_evidence_map_id_not_in_items_is_skipped(self):
        req = make_req("SQL")
        _, student_model, role_spec = self._make_state(
            [], {"SQL": ["nonexistent_id"]}, [req]
        )
        scores = compute_student_scores([], student_model, role_spec)
        assert scores["SQL"]["student_score"] == 0.0


# ---------------------------------------------------------------------------
# compute_gaps
# ---------------------------------------------------------------------------

class TestComputeGaps:

    def _scores(self, student_score: float, ids=None) -> dict:
        return {
            "proficiency": int(student_score // 1),
            "confidence": 0.8 if student_score > 0 else 0.0,
            "student_score": student_score,
            "evidence_item_ids": ids or [],
        }

    def test_no_gap_when_student_meets_requirement(self):
        req = make_req("Python", required_level=3.0)
        role_spec = RoleSpecModel(
            canonical_role_title="Dev", requirements=[req]
        )
        scores = {"Python": self._scores(3.0, ["e1"])}
        gaps = compute_gaps(scores, role_spec)
        assert len(gaps) == 0

    def test_gap_computed_correctly(self):
        req = make_req("Python", required_level=3.0, importance=4.0)
        role_spec = RoleSpecModel(canonical_role_title="Dev", requirements=[req])
        scores = {"Python": self._scores(1.0, ["p1"])}
        gaps = compute_gaps(scores, role_spec)
        assert len(gaps) == 1
        g = gaps[0]
        assert g.raw_gap == pytest.approx(2.0, abs=1e-4)
        assert g.weighted_gap == pytest.approx(8.0, abs=1e-4)

    def test_gap_type_missing_when_no_evidence(self):
        req = make_req("Distributed Systems")
        role_spec = RoleSpecModel(canonical_role_title="Dev", requirements=[req])
        scores = {"Distributed Systems": self._scores(0.0, [])}
        gaps = compute_gaps(scores, role_spec)
        assert gaps[0].gap_type == "missing"

    def test_gap_type_not_evidenced_when_score_very_low(self):
        req = make_req("ML")
        role_spec = RoleSpecModel(canonical_role_title="Dev", requirements=[req])
        scores = {"ML": {
            "proficiency": 1, "confidence": 0.3,
            "student_score": 0.3, "evidence_item_ids": ["c1"]
        }}
        gaps = compute_gaps(scores, role_spec)
        assert gaps[0].gap_type == "not_evidenced"

    def test_gap_type_weak_when_partial_evidence(self):
        req = make_req("ML")
        role_spec = RoleSpecModel(canonical_role_title="Dev", requirements=[req])
        scores = {"ML": {
            "proficiency": 2, "confidence": 0.7,
            "student_score": 1.4, "evidence_item_ids": ["p1"]
        }}
        gaps = compute_gaps(scores, role_spec)
        assert gaps[0].gap_type == "weak"

    def test_gaps_ranked_by_weighted_gap_descending(self):
        reqs = [
            make_req("SQL", required_level=3.0, importance=2.0),
            make_req("ML", required_level=4.0, importance=5.0),
        ]
        role_spec = RoleSpecModel(canonical_role_title="Dev", requirements=reqs)
        scores = {
            "SQL": self._scores(0.0),
            "ML": self._scores(0.0),
        }
        gaps = compute_gaps(scores, role_spec)
        assert gaps[0].summary == "ML"   # weighted_gap=20 vs SQL weighted_gap=6
        assert gaps[1].summary == "SQL"

    def test_optional_gap_below_threshold_is_irrelevant(self):
        req = make_req("Nice to have", required_level=1.0, importance=1.0, optional=True)
        role_spec = RoleSpecModel(canonical_role_title="Dev", requirements=[req])
        scores = {"Nice to have": {
            "proficiency": 1, "confidence": 0.5,
            "student_score": 0.6, "evidence_item_ids": ["c1"]
        }}
        gaps = compute_gaps(scores, role_spec)
        assert len(gaps) == 1
        assert gaps[0].gap_type == "irrelevant"


# ---------------------------------------------------------------------------
# finalise_knowledge_confidence
# ---------------------------------------------------------------------------

class TestFinaliseKnowledgeConfidence:

    def test_no_self_assessment_uses_inferred(self):
        prereq = make_prereq("Backprop", "ML", inferred_confidence=0.3)
        result = finalise_knowledge_confidence([prereq], {})
        assert result[0].final_confidence == pytest.approx(0.3, abs=1e-4)

    def test_self_assessment_zero_gives_low_confidence(self):
        prereq = make_prereq("Backprop", "ML", inferred_confidence=0.3)
        result = finalise_knowledge_confidence([prereq], {"Backprop": 0})
        # min(0/3 + 0.2, 1.0) = 0.2
        assert result[0].final_confidence == pytest.approx(0.2, abs=1e-4)

    def test_self_assessment_three_gives_capped_confidence(self):
        prereq = make_prereq("Backprop", "ML", inferred_confidence=0.3)
        result = finalise_knowledge_confidence([prereq], {"Backprop": 3})
        # min(3/3 + 0.2, 1.0) = min(1.2, 1.0) = 1.0
        assert result[0].final_confidence == pytest.approx(1.0, abs=1e-4)

    def test_self_assessment_two_gives_correct_confidence(self):
        prereq = make_prereq("CAP theorem", "Distributed Systems", inferred_confidence=0.2)
        result = finalise_knowledge_confidence([prereq], {"CAP theorem": 2})
        # min(2/3 + 0.2, 1.0) = min(0.867, 1.0) = 0.867
        assert result[0].final_confidence == pytest.approx(2/3 + 0.2, abs=1e-3)

    def test_multiple_prereqs_each_resolved(self):
        prereqs = [
            make_prereq("Concept A", "Gap X", inferred_confidence=0.2),
            make_prereq("Concept B", "Gap Y", inferred_confidence=0.4),
        ]
        user_inputs = {"Concept A": 1, "Concept B": 0}
        result = finalise_knowledge_confidence(prereqs, user_inputs)
        # A: min(1/3 + 0.2, 1.0) ≈ 0.533
        assert result[0].final_confidence == pytest.approx(1/3 + 0.2, abs=1e-3)
        # B: min(0/3 + 0.2, 1.0) = 0.2
        assert result[1].final_confidence == pytest.approx(0.2, abs=1e-4)

    def test_partial_self_assessment_mixed(self):
        prereqs = [
            make_prereq("Concept A", "Gap X", inferred_confidence=0.3),
            make_prereq("Concept B", "Gap X", inferred_confidence=0.6),
        ]
        # only A has self-assessment; B falls back to inferred
        result = finalise_knowledge_confidence(prereqs, {"Concept A": 2})
        assert result[0].final_confidence == pytest.approx(2/3 + 0.2, abs=1e-3)
        assert result[1].final_confidence == pytest.approx(0.6, abs=1e-4)


# ---------------------------------------------------------------------------
# derive_root_causes
# ---------------------------------------------------------------------------

class TestDeriveRootCauses:

    def _make_gap_with_prereqs(
        self, student_score: float, prereq_confidences: list, is_foundational=True
    ) -> GapItem:
        gap = make_gap(
            student_score=student_score,
            raw_gap=max(0, 3.0 - student_score),
            weighted_gap=max(0, 3.0 - student_score) * 3.0,
            proficiency=int(student_score),
            confidence=student_score / 4.0,
            gap_type="missing" if student_score < 0.5 else "weak",
        )
        gap.knowledge_prerequisites = [
            make_prereq(f"Concept {i}", gap.summary, is_foundational=is_foundational,
                        final_confidence=c)
            for i, c in enumerate(prereq_confidences)
        ]
        return gap

    def test_missing_entirely_low_score_low_knowledge(self):
        gap = self._make_gap_with_prereqs(0.0, [0.2, 0.3])
        result = derive_root_causes([gap], gap.knowledge_prerequisites)
        assert result[0].gap_root_cause == "missing_entirely"

    def test_no_practice_low_score_high_knowledge(self):
        gap = self._make_gap_with_prereqs(0.0, [0.7, 0.8])
        result = derive_root_causes([gap], gap.knowledge_prerequisites)
        assert result[0].gap_root_cause == "no_practice"

    def test_no_theory_high_score_low_knowledge(self):
        gap = self._make_gap_with_prereqs(1.5, [0.1, 0.2])
        result = derive_root_causes([gap], gap.knowledge_prerequisites)
        assert result[0].gap_root_cause == "no_theory"

    def test_none_high_score_high_knowledge(self):
        gap = self._make_gap_with_prereqs(1.5, [0.7, 0.8])
        result = derive_root_causes([gap], gap.knowledge_prerequisites)
        assert result[0].gap_root_cause is None

    def test_no_prereqs_leaves_root_cause_none(self):
        gap = make_gap(student_score=0.0)
        result = derive_root_causes([gap], [])
        assert result[0].gap_root_cause is None

    def test_only_non_foundational_prereqs_leaves_root_cause_none(self):
        gap = self._make_gap_with_prereqs(0.0, [0.2, 0.3], is_foundational=False)
        result = derive_root_causes([gap], gap.knowledge_prerequisites)
        assert result[0].gap_root_cause is None

    def test_prereqs_attached_to_correct_gap(self):
        gap1 = make_gap("Gap A", student_score=0.0)
        gap2 = make_gap("Gap B", student_score=0.0)
        prereq_a = make_prereq("Concept A", "Gap A", final_confidence=0.2)
        prereq_b = make_prereq("Concept B", "Gap B", final_confidence=0.8)

        result = derive_root_causes([gap1, gap2], [prereq_a, prereq_b])
        gap_a = next(g for g in result if g.summary == "Gap A")
        gap_b = next(g for g in result if g.summary == "Gap B")

        assert gap_a.gap_root_cause == "missing_entirely"
        assert gap_b.gap_root_cause == "no_practice"


# ---------------------------------------------------------------------------
# build_gap_report
# ---------------------------------------------------------------------------

class TestBuildGapReport:

    def test_empty_gaps_produces_report(self):
        report = build_gap_report([])
        assert "0 gap(s)" in report.summary
        assert report.gaps == []

    def test_summary_counts_correctly(self):
        gaps = [
            make_gap("A", gap_type="missing"),
            make_gap("B", gap_type="weak", student_score=1.0),
            make_gap("C", gap_type="missing"),
        ]
        gaps[0].gap_root_cause = "missing_entirely"
        gaps[1].gap_root_cause = "no_theory"
        gaps[2].gap_root_cause = "no_practice"

        report = build_gap_report(gaps)
        assert "3 gap(s)" in report.summary
        assert "1 missing entirely" in report.summary
        assert "1 lacking conceptual grounding" in report.summary
        assert "1 with knowledge but no demonstrated practice" in report.summary

    def test_gaps_preserved_in_report(self):
        gaps = [make_gap("A"), make_gap("B")]
        report = build_gap_report(gaps)
        assert len(report.gaps) == 2


# ---------------------------------------------------------------------------
# Phase 1 node — with mocked LLM
# ---------------------------------------------------------------------------

class TestGapAnalysisPhase1Node:

    def _make_state(self, has_role_spec=True, has_student_model=True):
        evidence_items = [
            EvidenceItem(
                id="e1", item_type="project", summary="Built a classifier",
                confidence=0.65, proficiency_score=2,
            )
        ]
        student_model = StudentModel(
            evidence_map={"Python programming": ["e1"]}
        )
        role_spec = RoleSpecModel(
            canonical_role_title="Data Scientist",
            requirements=[
                make_req("Python programming", required_level=3.0, importance=4.0),
                make_req("Distributed systems", required_level=3.0, importance=5.0),
            ],
        )
        state = AgentState(
            session_id="test-session",
            run_id="test-run",
            desired_role="Data Scientist",
            evidence_items=evidence_items if has_student_model else [],
            student_model=student_model if has_student_model else None,
            role_spec=role_spec if has_role_spec else None,
        )
        return state.model_dump(exclude_none=True)

    def test_errors_when_role_spec_missing(self):
        from app.nodes.gap_analysis_phase1 import gap_analysis_phase1_node
        state = self._make_state(has_role_spec=False)
        out = gap_analysis_phase1_node(state)
        result = AgentState.model_validate(out)
        assert any("role_spec missing" in e for e in result.errors)

    def test_errors_when_student_model_missing(self):
        from app.nodes.gap_analysis_phase1 import gap_analysis_phase1_node
        state = self._make_state(has_student_model=False)
        out = gap_analysis_phase1_node(state)
        result = AgentState.model_validate(out)
        assert any("student_model missing" in e for e in result.errors)

    @patch("app.tools.gap_analysis_tools.ChatOpenAI")
    def test_phase1_produces_gap_report_and_assessment_list(self, mock_llm_class):
        from app.nodes.gap_analysis_phase1 import gap_analysis_phase1_node
        from app.tools.gap_analysis_tools import _DecompositionResult, _KnowledgePrereqRaw

        mock_result = _DecompositionResult(prerequisites=[
            _KnowledgePrereqRaw(
                concept="Backpropagation and gradient descent",
                parent_skill_gap="Distributed systems",
                is_foundational=True,
                inferred_confidence=0.1,
                inference_tier="none",
                inference_basis=[],
            )
        ])
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value.invoke.return_value = mock_result
        mock_llm_class.return_value = mock_llm

        state = self._make_state()
        out = gap_analysis_phase1_node(state)
        result = AgentState.model_validate(out)

        assert result.gap_report is not None
        assert len(result.gap_report.gaps) > 0
        # "Distributed systems" should be a gap (no evidence)
        summaries = [g.summary for g in result.gap_report.gaps]
        assert "Distributed systems" in summaries
        # self assessment should be flagged
        assert "Backpropagation and gradient descent" in result.knowledge_needing_assessment


# ---------------------------------------------------------------------------
# Phase 2 node
# ---------------------------------------------------------------------------

class TestGapAnalysisPhase2Node:

    def test_phase2_finalises_confidence_and_derives_root_cause(self):
        from app.nodes.gap_analysis_phase2 import gap_analysis_phase2_node
        from app.state import GapReport

        prereq = make_prereq("Backprop", "ML gap", inferred_confidence=0.2)
        gap = make_gap("ML gap", student_score=0.0, raw_gap=3.0, weighted_gap=9.0)
        gap.knowledge_prerequisites = [prereq]

        state = AgentState(
            session_id="test-session",
            desired_role="Data Scientist",
            gap_report=GapReport(summary="pending", gaps=[gap]),
            user_knowledge_inputs={"Backprop": 0},  # None → low confidence
        )

        out = gap_analysis_phase2_node(state.model_dump(exclude_none=True))
        result = AgentState.model_validate(out)

        assert result.gap_report is not None
        assert result.gap_report.summary != "pending"
        gap_out = result.gap_report.gaps[0]
        # student_score=0 + low knowledge → missing_entirely
        assert gap_out.gap_root_cause == "missing_entirely"
        # knowledge_needing_assessment cleared
        assert result.knowledge_needing_assessment == []

    def test_phase2_no_self_assessment_uses_inferred(self):
        from app.nodes.gap_analysis_phase2 import gap_analysis_phase2_node
        from app.state import GapReport

        prereq = make_prereq("CAP theorem", "Distributed Systems", inferred_confidence=0.8)
        gap = make_gap("Distributed Systems", student_score=0.0)
        gap.knowledge_prerequisites = [prereq]

        state = AgentState(
            session_id="test-session",
            desired_role="SWE",
            gap_report=GapReport(summary="pending", gaps=[gap]),
            user_knowledge_inputs={},  # no self-assessment
        )

        out = gap_analysis_phase2_node(state.model_dump(exclude_none=True))
        result = AgentState.model_validate(out)

        gap_out = result.gap_report.gaps[0]
        # student_score=0, knowledge=0.8 → no_practice
        assert gap_out.gap_root_cause == "no_practice"

    def test_phase2_errors_on_empty_gap_report(self):
        from app.nodes.gap_analysis_phase2 import gap_analysis_phase2_node

        state = AgentState(session_id="test", desired_role="Dev")
        out = gap_analysis_phase2_node(state.model_dump(exclude_none=True))
        result = AgentState.model_validate(out)
        assert any("no gap_items" in e for e in result.errors)


# ---------------------------------------------------------------------------
# State schema validation
# ---------------------------------------------------------------------------

class TestStateSchema:

    def test_evidence_item_new_fields_have_defaults(self):
        item = EvidenceItem(item_type="skill", summary="Python", confidence=0.7)
        assert item.proficiency_score is None
        assert item.action_verbs == []

    def test_role_spec_requirement_has_level_and_importance(self):
        req = RoleSpecRequirement(
            req_summary="Python",
            category="skill",
            required_level=3.0,
            importance=4.0,
        )
        assert req.required_level == 3.0
        assert req.importance == 4.0

    def test_role_spec_requirement_defaults(self):
        req = RoleSpecRequirement(req_summary="Python", category="skill")
        assert req.required_level == 3.0
        assert req.importance == 3.0

    def test_gap_item_full_construction(self):
        gap = GapItem(
            summary="ML",
            category="skill",
            required_level=3.0,
            student_score=1.2,
            raw_gap=1.8,
            weighted_gap=7.2,
            proficiency=2,
            confidence=0.6,
            gap_type="weak",
            gap_root_cause="no_theory",
        )
        assert gap.gap_root_cause == "no_theory"
        assert gap.knowledge_prerequisites == []

    def test_knowledge_prerequisite_construction(self):
        kp = KnowledgePrerequisite(
            concept="Backprop",
            parent_skill_gap="ML model development",
            is_foundational=True,
            inferred_confidence=0.3,
            inference_tier="skill_implied",
        )
        assert kp.needs_self_assessment is False
        assert kp.self_assessment is None
        assert kp.final_confidence is None

    def test_agent_state_new_fields(self):
        state = AgentState(session_id="s", desired_role="Dev")
        assert state.knowledge_needing_assessment == []
        assert state.user_knowledge_inputs == {}


# ---------------------------------------------------------------------------
# Normalised parent_skill_gap matching (phase 1 node)
# ---------------------------------------------------------------------------

class TestNormalisedParentSkillGapMatching:
    """
    Verifies that prerequisites with parent_skill_gap strings that differ from
    gap.summary only by trailing punctuation or casing are still attached correctly.
    """

    def _make_state_with_gap_summary(self, gap_summary: str):
        """State where one gap exists for gap_summary, one evidence item supports it."""
        evidence_items = [
            EvidenceItem(
                id="e1", item_type="experience", summary="Used Python at work",
                confidence=0.8, proficiency_score=3,
            )
        ]
        student_model = StudentModel(evidence_map={gap_summary: ["e1"]})
        role_spec = RoleSpecModel(
            canonical_role_title="Data Scientist",
            requirements=[
                make_req(gap_summary, required_level=4.0, importance=5.0),
                make_req("Unrelated requirement", required_level=2.0, importance=2.0),
            ],
        )
        state = AgentState(
            session_id="s", run_id="r", desired_role="Data Scientist",
            evidence_items=evidence_items,
            student_model=student_model,
            role_spec=role_spec,
        )
        return state.model_dump(exclude_none=True)

    @patch("app.tools.gap_analysis_tools.ChatOpenAI")
    def test_prereq_attached_when_parent_matches_exactly(self, mock_llm_class):
        from app.nodes.gap_analysis_phase1 import gap_analysis_phase1_node
        from app.tools.gap_analysis_tools import _DecompositionResult, _KnowledgePrereqRaw

        gap_summary = "Unrelated requirement"   # this one has no evidence → will be a gap
        mock_result = _DecompositionResult(prerequisites=[
            _KnowledgePrereqRaw(
                concept="Some concept",
                parent_skill_gap=gap_summary,   # exact match
                is_foundational=False,
                inferred_confidence=0.3,
                inference_tier="none",
                inference_basis=[],
            )
        ])
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value.invoke.return_value = mock_result
        mock_llm_class.return_value = mock_llm

        state = self._make_state_with_gap_summary("Python programming")
        out = gap_analysis_phase1_node(state)
        result = AgentState.model_validate(out)

        gap = next(g for g in result.gap_report.gaps if g.summary == gap_summary)
        assert len(gap.knowledge_prerequisites) == 1
        assert gap.knowledge_prerequisites[0].concept == "Some concept"

    @patch("app.tools.gap_analysis_tools.ChatOpenAI")
    def test_prereq_attached_when_parent_missing_trailing_period(self, mock_llm_class):
        from app.nodes.gap_analysis_phase1 import gap_analysis_phase1_node
        from app.tools.gap_analysis_tools import _DecompositionResult, _KnowledgePrereqRaw

        # Canonical gap summary includes trailing period; LLM drops it in parent_skill_gap.
        # The helper creates "Unrelated requirement." as the second requirement when we pass
        # the canonical string for the first (evidenced) requirement.
        canonical_gap_summary = "Unrelated requirement."
        mock_result = _DecompositionResult(prerequisites=[
            _KnowledgePrereqRaw(
                concept="Some concept",
                parent_skill_gap="Unrelated requirement",   # LLM drops trailing period
                is_foundational=False,
                inferred_confidence=0.3,
                inference_tier="none",
                inference_basis=[],
            )
        ])
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value.invoke.return_value = mock_result
        mock_llm_class.return_value = mock_llm

        # Build state where the second requirement IS "Unrelated requirement." (with period)
        evidence_items = [
            EvidenceItem(id="e1", item_type="experience", summary="Used Python at work",
                         confidence=0.8, proficiency_score=3)
        ]
        evidenced_summary = "Python programming."
        student_model = StudentModel(evidence_map={evidenced_summary: ["e1"]})
        role_spec = RoleSpecModel(
            canonical_role_title="Data Scientist",
            requirements=[
                make_req(evidenced_summary, required_level=4.0, importance=5.0),
                make_req(canonical_gap_summary, required_level=2.0, importance=2.0),
            ],
        )
        state = AgentState(
            session_id="s", run_id="r", desired_role="Data Scientist",
            evidence_items=evidence_items,
            student_model=student_model,
            role_spec=role_spec,
        ).model_dump(exclude_none=True)

        out = gap_analysis_phase1_node(state)
        result = AgentState.model_validate(out)

        gap = next(g for g in result.gap_report.gaps if g.summary == canonical_gap_summary)
        assert len(gap.knowledge_prerequisites) == 1, (
            "Prerequisite should be attached despite missing trailing period in parent_skill_gap"
        )

    @patch("app.tools.gap_analysis_tools.ChatOpenAI")
    def test_prereq_not_attached_when_parent_genuinely_unmatched(self, mock_llm_class):
        from app.nodes.gap_analysis_phase1 import gap_analysis_phase1_node
        from app.tools.gap_analysis_tools import _DecompositionResult, _KnowledgePrereqRaw

        mock_result = _DecompositionResult(prerequisites=[
            _KnowledgePrereqRaw(
                concept="Some concept",
                parent_skill_gap="Completely made up gap name",   # no gap has this summary
                is_foundational=False,
                inferred_confidence=0.3,
                inference_tier="none",
                inference_basis=[],
            )
        ])
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value.invoke.return_value = mock_result
        mock_llm_class.return_value = mock_llm

        state = self._make_state_with_gap_summary("Python programming")
        out = gap_analysis_phase1_node(state)
        result = AgentState.model_validate(out)

        for gap in result.gap_report.gaps:
            assert gap.knowledge_prerequisites == [], (
                f"Gap '{gap.summary}' should have no prerequisites when parent_skill_gap is unrecognised"
            )


# ---------------------------------------------------------------------------
# build_student_model — index-based evidence mapping
# ---------------------------------------------------------------------------

class TestBuildStudentModel:

    def _make_role_spec(self):
        return RoleSpecModel(
            canonical_role_title="Data Scientist",
            requirements=[
                make_req("Proficiency in Python.", required_level=4.0, importance=5.0),
                make_req("Experience with SQL.", required_level=3.0, importance=4.0),
            ],
        )

    def test_canonical_key_used_in_evidence_map(self):
        from app.tools.evidence_llm import build_student_model
        role_spec = self._make_role_spec()
        items = [
            EvidenceItem(
                id="i1", item_type="project", summary="Built ML model",
                confidence=0.7, proficiency_score=2,
                metadata={"matched_requirements": ["Proficiency in Python."]},
            )
        ]
        model = build_student_model(items, role_spec)
        assert "Proficiency in Python." in model.evidence_map
        assert "i1" in model.evidence_map["Proficiency in Python."]

    def test_missing_period_still_maps_to_canonical(self):
        from app.tools.evidence_llm import build_student_model
        role_spec = self._make_role_spec()
        items = [
            EvidenceItem(
                id="i1", item_type="project", summary="Built ML model",
                confidence=0.7, proficiency_score=2,
                # LLM dropped trailing period
                metadata={"matched_requirements": ["Proficiency in Python"]},
            )
        ]
        model = build_student_model(items, role_spec)
        assert "Proficiency in Python." in model.evidence_map, (
            "Should resolve to canonical key even without trailing period"
        )
        assert "i1" in model.evidence_map["Proficiency in Python."]

    def test_single_item_maps_to_multiple_requirements(self):
        """One evidence item with multiple matched_requirements appears in all their evidence_map entries."""
        from app.tools.evidence_llm import build_student_model
        role_spec = self._make_role_spec()
        items = [
            EvidenceItem(
                id="i1", item_type="project", summary="Built ML pipeline",
                confidence=0.7, proficiency_score=2,
                metadata={"matched_requirements": ["Proficiency in Python.", "Experience with SQL."]},
            )
        ]
        model = build_student_model(items, role_spec)
        assert "i1" in model.evidence_map.get("Proficiency in Python.", [])
        assert "i1" in model.evidence_map.get("Experience with SQL.", [])

    def test_category_tag_not_added_to_evidence_map(self):
        from app.tools.evidence_llm import build_student_model
        role_spec = self._make_role_spec()
        items = [
            EvidenceItem(
                id="i1", item_type="experience", summary="Work exp",
                confidence=0.8, proficiency_score=3,
                # LLM included category tag as a separate entry (old bug)
                metadata={"matched_requirements": ["skill", "Experience with SQL."]},
            )
        ]
        model = build_student_model(items, role_spec)
        assert "skill" not in model.evidence_map
        assert "Experience with SQL." in model.evidence_map
        assert "i1" in model.evidence_map["Experience with SQL."]
