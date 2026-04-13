"""
Unit tests for gap_analysis_tools.py

Covers:
- aggregate_proficiency: item_type-based rubric
- aggregate_confidence: Bayesian combination
- compute_student_scores: evidence aggregation per requirement
- compute_gaps: gap formula, gap_type classification, ranking, all-requirements capture
- build_gap_report: summary text generation
- build_student_model: evidence mapping and skills/experiences/education population
"""
from __future__ import annotations

from typing import List
from unittest.mock import MagicMock, patch

import pytest

from app.state import (
    AgentState,
    EvidenceItem,
    GapItem,
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
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_item(
    item_type: str,
    confidence: float,
    id: str = "x",
) -> EvidenceItem:
    return EvidenceItem(
        id=id,
        item_type=item_type,
        summary=f"{item_type} item",
        confidence=confidence,
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
    student_level: float = 0.0,
    required_level: float = 3.0,
    raw_gap: float = 3.0,
    weighted_gap: float = 9.0,
    proficiency: int = 0,
    confidence: float = 0.0,
    gap_type: str = "no_evidence",
) -> GapItem:
    return GapItem(
        summary=summary,
        category="skill",
        required_level=required_level,
        student_level=student_level,
        raw_gap=raw_gap,
        weighted_gap=weighted_gap,
        proficiency=proficiency,
        confidence=confidence,
        gap_type=gap_type,
    )


# ---------------------------------------------------------------------------
# aggregate_proficiency
# ---------------------------------------------------------------------------

class TestAggregateProficiency:
    """
    Proficiency is derived purely from item_type — no per-item score.
    experience → 3, project → 2, coursework → 1, claim → 0.
    Priority: experience > project > coursework > claim.
    """

    def test_empty_returns_zero(self):
        assert aggregate_proficiency([]) == 0

    def test_only_claims_return_zero(self):
        items = [make_item("claim", 0.1, id=f"c{i}") for i in range(3)]
        assert aggregate_proficiency(items) == 0

    def test_single_coursework_returns_one(self):
        items = [make_item("coursework", 0.4, id="c1")]
        assert aggregate_proficiency(items) == 1

    def test_single_project_returns_two(self):
        items = [make_item("project", 0.6, id="p1")]
        assert aggregate_proficiency(items) == 2

    def test_multiple_projects_still_returns_two(self):
        # Multiple projects do not compound beyond level 2
        items = [
            make_item("project", 0.6, id="p1"),
            make_item("project", 0.7, id="p2"),
        ]
        assert aggregate_proficiency(items) == 2

    def test_single_experience_returns_three(self):
        items = [make_item("experience", 0.8, id="e1")]
        assert aggregate_proficiency(items) == 3

    def test_experience_takes_priority_over_project(self):
        items = [
            make_item("project", 0.6, id="p1"),
            make_item("experience", 0.8, id="e1"),
        ]
        assert aggregate_proficiency(items) == 3

    def test_experience_takes_priority_over_coursework(self):
        items = [
            make_item("coursework", 0.4, id="c1"),
            make_item("experience", 0.8, id="e1"),
        ]
        assert aggregate_proficiency(items) == 3

    def test_project_takes_priority_over_coursework(self):
        items = [
            make_item("coursework", 0.4, id="c1"),
            make_item("project", 0.6, id="p1"),
        ]
        assert aggregate_proficiency(items) == 2

    def test_claim_plus_coursework_returns_one(self):
        items = [
            make_item("claim", 0.2, id="cl1"),
            make_item("coursework", 0.4, id="c1"),
        ]
        assert aggregate_proficiency(items) == 1


# ---------------------------------------------------------------------------
# aggregate_confidence
# ---------------------------------------------------------------------------

class TestAggregateConfidence:

    def test_empty_returns_zero(self):
        assert aggregate_confidence([]) == 0.0

    def test_single_item(self):
        items = [make_item("project", 0.6, id="p1")]
        assert aggregate_confidence(items) == pytest.approx(0.6, abs=1e-4)

    def test_two_independent_items(self):
        items = [
            make_item("project", 0.6, id="p1"),
            make_item("experience", 0.6, id="e1"),
        ]
        expected = 1 - (0.4 * 0.4)  # 0.84
        assert aggregate_confidence(items) == pytest.approx(expected, abs=1e-4)

    def test_three_items_increases_confidence(self):
        items = [make_item("claim", 0.5, id=f"i{n}") for n in range(3)]
        expected = 1 - (0.5 ** 3)  # 0.875
        assert aggregate_confidence(items) == pytest.approx(expected, abs=1e-4)

    def test_perfect_confidence_item(self):
        items = [make_item("experience", 1.0, id="e1")]
        assert aggregate_confidence(items) == pytest.approx(1.0, abs=1e-4)

    def test_zero_confidence_item(self):
        items = [make_item("claim", 0.0, id="c1")]
        assert aggregate_confidence(items) == pytest.approx(0.0, abs=1e-4)

    def test_weak_plus_strong_raises_confidence(self):
        items = [
            make_item("claim", 0.1, id="c1"),
            make_item("project", 0.8, id="p1"),
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
        assert scores["Machine Learning"]["student_level"] == 0.0
        assert scores["Machine Learning"]["proficiency"] == 0
        assert scores["Machine Learning"]["confidence"] == 0.0

    def test_single_project_match(self):
        item = make_item("project", 0.6, id="p1")
        req = make_req("Python programming")
        _, student_model, role_spec = self._make_state(
            [item], {"Python programming": ["p1"]}, [req]
        )
        scores = compute_student_scores([item], student_model, role_spec)
        s = scores["Python programming"]
        assert s["proficiency"] == 2
        assert s["confidence"] == pytest.approx(0.6, abs=1e-4)
        assert s["student_level"] == pytest.approx(2 * 0.6, abs=1e-4)

    def test_experience_beats_project(self):
        item1 = make_item("project", 0.6, id="p1")
        item2 = make_item("experience", 0.8, id="e1")
        req = make_req("Python programming")
        _, student_model, role_spec = self._make_state(
            [item1, item2], {"Python programming": ["p1", "e1"]}, [req]
        )
        scores = compute_student_scores([item1, item2], student_model, role_spec)
        s = scores["Python programming"]
        assert s["proficiency"] == 3  # experience wins
        expected_conf = round(1 - (0.4 * 0.2), 4)  # 0.92
        assert s["confidence"] == pytest.approx(expected_conf, abs=1e-4)

    def test_evidence_map_id_not_in_items_is_skipped(self):
        req = make_req("SQL")
        _, student_model, role_spec = self._make_state(
            [], {"SQL": ["nonexistent_id"]}, [req]
        )
        scores = compute_student_scores([], student_model, role_spec)
        assert scores["SQL"]["student_level"] == 0.0


# ---------------------------------------------------------------------------
# compute_gaps
# ---------------------------------------------------------------------------

class TestComputeGaps:

    def _scores(self, student_level: float, ids=None) -> dict:
        return {
            "proficiency": int(student_level // 1),
            "confidence": 0.8 if student_level > 0 else 0.0,
            "student_level": student_level,
            "evidence_item_ids": ids or [],
        }

    def _make_items(self, ids_and_types: dict) -> List[EvidenceItem]:
        """ids_and_types: {id: item_type}"""
        return [
            EvidenceItem(id=id_, item_type=itype, summary=f"{itype} item", confidence=0.7)
            for id_, itype in ids_and_types.items()
        ]

    def test_all_requirements_captured(self):
        """No filter — all requirements appear in output including met ones."""
        req = make_req("Python", required_level=3.0)
        role_spec = RoleSpecModel(canonical_role_title="Dev", requirements=[req])
        scores = {"Python": self._scores(3.0, ["e1"])}
        items = self._make_items({"e1": "experience"})
        gaps = compute_gaps(scores, role_spec, items)
        assert len(gaps) == 1
        assert gaps[0].gap_type == "met"

    def test_gap_computed_correctly(self):
        req = make_req("Python", required_level=3.0, importance=4.0)
        role_spec = RoleSpecModel(canonical_role_title="Dev", requirements=[req])
        scores = {"Python": self._scores(1.0, ["p1"])}
        items = self._make_items({"p1": "project"})
        gaps = compute_gaps(scores, role_spec, items)
        assert len(gaps) == 1
        g = gaps[0]
        assert g.raw_gap == pytest.approx(2.0, abs=1e-4)
        assert g.weighted_gap == pytest.approx(8.0, abs=1e-4)

    def test_gap_type_no_evidence_when_no_ids(self):
        req = make_req("Distributed Systems")
        role_spec = RoleSpecModel(canonical_role_title="Dev", requirements=[req])
        scores = {"Distributed Systems": self._scores(0.0, [])}
        gaps = compute_gaps(scores, role_spec, [])
        assert gaps[0].gap_type == "no_evidence"

    def test_gap_type_claimed_only_when_all_claims(self):
        req = make_req("ML")
        role_spec = RoleSpecModel(canonical_role_title="Dev", requirements=[req])
        scores = {"ML": self._scores(0.0, ["c1", "c2"])}
        items = self._make_items({"c1": "claim", "c2": "claim"})
        gaps = compute_gaps(scores, role_spec, items)
        assert gaps[0].gap_type == "claimed_only"

    def test_gap_type_partial_when_mixed_evidence(self):
        req = make_req("ML")
        role_spec = RoleSpecModel(canonical_role_title="Dev", requirements=[req])
        scores = {"ML": self._scores(1.4, ["p1"])}
        items = self._make_items({"p1": "project"})
        gaps = compute_gaps(scores, role_spec, items)
        assert gaps[0].gap_type == "partial"

    def test_gap_type_partial_when_claims_mixed_with_project(self):
        req = make_req("ML")
        role_spec = RoleSpecModel(canonical_role_title="Dev", requirements=[req])
        scores = {"ML": self._scores(1.0, ["p1", "c1"])}
        items = self._make_items({"p1": "project", "c1": "claim"})
        gaps = compute_gaps(scores, role_spec, items)
        # Not all items are claims — should be partial, not claimed_only
        assert gaps[0].gap_type == "partial"

    def test_gap_type_optional_gap_for_optional_requirement(self):
        req = make_req("Nice to have", required_level=2.0, importance=1.0, optional=True)
        role_spec = RoleSpecModel(canonical_role_title="Dev", requirements=[req])
        scores = {"Nice to have": self._scores(0.5, ["p1"])}
        items = self._make_items({"p1": "project"})
        gaps = compute_gaps(scores, role_spec, items)
        assert gaps[0].gap_type == "optional_gap"

    def test_met_gaps_sink_to_bottom(self):
        """met requirements have raw_gap ≈ 0, so weighted_gap ≈ 0 — they naturally sort last."""
        reqs = [
            make_req("SQL",  required_level=3.0, importance=2.0),
            make_req("ML",   required_level=4.0, importance=5.0),
            make_req("Comms",required_level=2.0, importance=3.0),
        ]
        role_spec = RoleSpecModel(canonical_role_title="Dev", requirements=reqs)
        scores = {
            "SQL":   self._scores(0.0, []),       # no_evidence — high gap
            "ML":    self._scores(0.0, []),        # no_evidence — highest gap
            "Comms": self._scores(2.0, ["e1"]),    # met
        }
        items = self._make_items({"e1": "experience"})
        gaps = compute_gaps(scores, role_spec, items)
        assert gaps[0].summary == "ML"
        assert gaps[1].summary == "SQL"
        assert gaps[2].summary == "Comms"
        assert gaps[2].gap_type == "met"

    def test_gaps_ranked_by_weighted_gap_descending(self):
        reqs = [
            make_req("SQL", required_level=3.0, importance=2.0),
            make_req("ML",  required_level=4.0, importance=5.0),
        ]
        role_spec = RoleSpecModel(canonical_role_title="Dev", requirements=reqs)
        scores = {
            "SQL": self._scores(0.0),
            "ML":  self._scores(0.0),
        }
        gaps = compute_gaps(scores, role_spec, [])
        assert gaps[0].summary == "ML"    # weighted_gap=20 vs SQL weighted_gap=6
        assert gaps[1].summary == "SQL"

    def test_student_level_stored_on_gap_item(self):
        req = make_req("Python", required_level=3.0)
        role_spec = RoleSpecModel(canonical_role_title="Dev", requirements=[req])
        scores = {"Python": self._scores(1.2, ["p1"])}
        items = self._make_items({"p1": "project"})
        gaps = compute_gaps(scores, role_spec, items)
        assert gaps[0].student_level == pytest.approx(1.2, abs=1e-4)


# ---------------------------------------------------------------------------
# build_gap_report
# ---------------------------------------------------------------------------

class TestBuildGapReport:

    def test_empty_gaps_produces_report(self):
        report = build_gap_report([])
        assert "0 requirement(s)" in report.summary
        assert report.gaps == []

    def test_summary_counts_all_types(self):
        gaps = [
            make_gap("A", gap_type="no_evidence"),
            make_gap("B", gap_type="claimed_only"),
            make_gap("C", gap_type="partial"),
            make_gap("D", gap_type="optional_gap"),
            make_gap("E", gap_type="met"),
        ]
        report = build_gap_report(gaps)
        assert "5 requirement(s)" in report.summary
        assert "1 met" in report.summary
        assert "1 with no evidence" in report.summary
        assert "1 claimed but not demonstrated" in report.summary
        assert "1 partially evidenced" in report.summary
        assert "1 optional" in report.summary

    def test_gaps_preserved_in_report(self):
        gaps = [make_gap("A"), make_gap("B")]
        report = build_gap_report(gaps)
        assert len(report.gaps) == 2

    def test_summary_omits_zero_count_types(self):
        gaps = [make_gap("A", gap_type="no_evidence")]
        report = build_gap_report(gaps)
        assert "claimed" not in report.summary
        assert "partially" not in report.summary
        assert "optional" not in report.summary
        assert "met" not in report.summary


# ---------------------------------------------------------------------------
# State schema validation
# ---------------------------------------------------------------------------

class TestStateSchema:

    def test_evidence_item_has_no_proficiency_score(self):
        item = EvidenceItem(item_type="claim", summary="Python", confidence=0.2)
        assert not hasattr(item, "proficiency_score")

    def test_evidence_item_types_are_valid(self):
        for itype in ("experience", "project", "coursework", "claim"):
            item = EvidenceItem(item_type=itype, summary="test", confidence=0.5)
            assert item.item_type == itype

    def test_gap_item_uses_student_level(self):
        gap = GapItem(
            summary="ML",
            category="skill",
            required_level=3.0,
            student_level=1.2,
            raw_gap=1.8,
            weighted_gap=7.2,
            proficiency=2,
            confidence=0.6,
            gap_type="partial",
        )
        assert gap.student_level == 1.2

    def test_gap_item_has_no_gap_root_cause(self):
        gap = make_gap("Test")
        assert not hasattr(gap, "gap_root_cause")

    def test_gap_type_literals(self):
        for gtype in ("no_evidence", "claimed_only", "partial", "optional_gap", "met"):
            gap = make_gap(gap_type=gtype)
            assert gap.gap_type == gtype

    def test_role_spec_requirement_has_level_and_importance(self):
        req = RoleSpecRequirement(
            req_summary="Python",
            category="skill",
            required_level=3.0,
            importance=4.0,
        )
        assert req.required_level == 3.0
        assert req.importance == 4.0


# ---------------------------------------------------------------------------
# build_student_model — evidence mapping and type bucketing
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

    def test_claim_items_populate_skills(self):
        from app.tools.evidence_llm import build_student_model
        role_spec = self._make_role_spec()
        items = [
            EvidenceItem(id="i1", item_type="claim", summary="PyTorch", confidence=0.2,
                         metadata={"matched_requirements": []}),
            EvidenceItem(id="i2", item_type="claim", summary="TensorFlow", confidence=0.2,
                         metadata={"matched_requirements": []}),
        ]
        model = build_student_model(items, role_spec)
        assert "PyTorch" in model.skills
        assert "TensorFlow" in model.skills

    def test_experience_items_populate_experiences(self):
        from app.tools.evidence_llm import build_student_model
        role_spec = self._make_role_spec()
        items = [
            EvidenceItem(id="i1", item_type="experience", summary="Worked at Acme",
                         confidence=0.8, metadata={"matched_requirements": []}),
        ]
        model = build_student_model(items, role_spec)
        assert "Worked at Acme" in model.experiences

    def test_coursework_items_populate_education(self):
        from app.tools.evidence_llm import build_student_model
        role_spec = self._make_role_spec()
        items = [
            EvidenceItem(id="i1", item_type="coursework", summary="BSc Computer Science",
                         confidence=0.5, metadata={"matched_requirements": []}),
        ]
        model = build_student_model(items, role_spec)
        assert "BSc Computer Science" in model.education

    def test_canonical_key_used_in_evidence_map(self):
        from app.tools.evidence_llm import build_student_model
        role_spec = self._make_role_spec()
        items = [
            EvidenceItem(id="i1", item_type="project", summary="Built ML model",
                         confidence=0.7,
                         metadata={"matched_requirements": ["Proficiency in Python."]}),
        ]
        model = build_student_model(items, role_spec)
        assert "Proficiency in Python." in model.evidence_map
        assert "i1" in model.evidence_map["Proficiency in Python."]

    def test_missing_period_still_maps_to_canonical(self):
        from app.tools.evidence_llm import build_student_model
        role_spec = self._make_role_spec()
        items = [
            EvidenceItem(id="i1", item_type="project", summary="Built ML model",
                         confidence=0.7,
                         # LLM dropped trailing period
                         metadata={"matched_requirements": ["Proficiency in Python"]}),
        ]
        model = build_student_model(items, role_spec)
        assert "Proficiency in Python." in model.evidence_map, (
            "Should resolve to canonical key even without trailing period"
        )
        assert "i1" in model.evidence_map["Proficiency in Python."]

    def test_single_item_maps_to_multiple_requirements(self):
        from app.tools.evidence_llm import build_student_model
        role_spec = self._make_role_spec()
        items = [
            EvidenceItem(id="i1", item_type="project", summary="Built ML pipeline",
                         confidence=0.7,
                         metadata={"matched_requirements": [
                             "Proficiency in Python.", "Experience with SQL."
                         ]}),
        ]
        model = build_student_model(items, role_spec)
        assert "i1" in model.evidence_map.get("Proficiency in Python.", [])
        assert "i1" in model.evidence_map.get("Experience with SQL.", [])

    def test_category_tag_not_added_to_evidence_map(self):
        from app.tools.evidence_llm import build_student_model
        role_spec = self._make_role_spec()
        items = [
            EvidenceItem(id="i1", item_type="experience", summary="Work exp",
                         confidence=0.8,
                         # LLM included category tag as a separate entry (old bug)
                         metadata={"matched_requirements": ["skill", "Experience with SQL."]}),
        ]
        model = build_student_model(items, role_spec)
        assert "skill" not in model.evidence_map
        assert "Experience with SQL." in model.evidence_map
        assert "i1" in model.evidence_map["Experience with SQL."]

    def test_project_items_do_not_populate_skills_or_education(self):
        from app.tools.evidence_llm import build_student_model
        role_spec = self._make_role_spec()
        items = [
            EvidenceItem(id="i1", item_type="project", summary="Sentiment analysis",
                         confidence=0.6, metadata={"matched_requirements": []}),
        ]
        model = build_student_model(items, role_spec)
        assert model.skills == []
        assert model.education == []
        assert model.experiences == []
