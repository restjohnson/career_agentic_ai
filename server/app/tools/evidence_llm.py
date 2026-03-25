from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.tools.llm_resilience import invoke_with_retry
from app.state import (
    EvidenceItem,
    EvidenceItemType,
    RoleSpecModel,
    StudentModel,
)

# ---------------------------------------------------------------------------
# LLM output schema
# ---------------------------------------------------------------------------

class _ExtractedItem(BaseModel):
    item_type: EvidenceItemType
    summary: str
    snippet: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    proficiency_score: int = Field(ge=0, le=4, default=0)
    action_verbs: List[str] = Field(default_factory=list)
    matched_requirement_indices: List[int] = Field(default_factory=list)


class _ExtractionResult(BaseModel):
    items: List[_ExtractedItem]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM = """You are an expert career evidence analyst.

You are given a parsed document from a student (resume, portfolio, etc.) and a list of role requirements for a target career role.

Your job is to extract structured evidence items that demonstrate the student's capabilities relevant to the target role.

Rules:
1. Extract only items that are relevant to the target role or broadly useful for a career context (skills, experiences, projects, education).
2. Classify each item as one of: skill, experience, project, coursework, claim.
   - skill: A specific technical or soft skill the student demonstrates.
   - experience: A work, internship, or research experience entry.
   - project: A standalone project the student built or contributed to.
   - coursework: A course, certification, or academic program.
   - claim: A self-description or goal statement that cannot be independently verified.
3. For matched_requirement_indices: list the INDEX NUMBERS (0-based integers) of ALL role requirements
   this evidence item supports. The requirements are numbered starting from 0 in the list provided.
   Be GENEROUS: a single project or experience typically supports multiple requirements.

   Reasoning process for project and experience items:
   a) Identify every language, framework, tool, and technique the work required — including those
      only implied (e.g. a machine learning project implies Python, statistical analysis, and a
      framework even if not all are named explicitly).
   b) For each requirement in the list, ask: "Would completing this project require or demonstrate
      this skill?" If yes, include the index.
   c) A project that trains and evaluates a model should match: the ML framework, Python,
      statistical analysis, and any visualisation or communication requirement it touches.

   - For skill items: match the skill and any closely related requirements.
   - For coursework items: match the subject area and any requirements it underpins.
   - Return an empty list ONLY if the item is completely unrelated to all requirements (e.g. a hobby
     with no career relevance). Aim for at least 1 match for every project or experience item.
4. Set confidence (0.00–1.00) based on how strongly this evidence relates to the matched role requirement(s).
   - range = [0.76 to 1.00]: Production or deployed usage with measurable outcomes at professional/internship levels (e.g. shipped a feature, led a team, deployed to users).
   - range = [0.51 to 0.75]: Used independently in a self-directed project with clear context and outcomes.
   - range = [0.26 to 0.50]: Used in a coursework, guided, or tutorial setting with limited independent application.
   - range = [0.0 to 0.25]: Only mentioned or loosely implied — no demonstration of actual usage.
   If the item has no matched requirements, set confidence to 0.5 as a neutral default.
5. Set proficiency_score (0–4) using this rubric for the skill or capability described:
   - 0: No meaningful demonstration — only mentioned or claimed.
   - 1: Coursework or guided assignment — learned under instruction, limited independent application.
   - 2: One independent project — used in a self-directed context with clear outcomes.
   - 3: Multiple substantial projects OR an internship/work placement — repeated independent use.
   - 4: Professional or production-level usage — shipped to users, used in employment, measurable impact.
6. Extract action_verbs: list the key action verbs from the item text that signal the level of engagement
   (e.g. ["built", "deployed", "optimised"] for high engagement; ["studied", "learned", "attended"] for low).
   Return an empty list if none are present.
7. snippet: Include the most relevant quoted text from the document ONLY if the consent_level is "excerpt_ok" or "raw_ok". Otherwise set snippet to null.
8. Do not invent capabilities the document does not support. If unsure, lower confidence and proficiency_score rather than omitting.
9. Produce items in order of relevance to the target role (most relevant first).
"""


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def extract_evidence_items(
    *,
    markdown_content: str,
    source_type: str,
    role_spec: Optional[RoleSpecModel] = None,
    consent_level: str = "derived_only",
) -> List[EvidenceItem]:
    """
    Use an LLM to extract structured EvidenceItems from Docling markdown output.

    Args:
        markdown_content: Markdown representation of the parsed document.
        source_type: One of EvidenceSourceType ("resume", "portfolio", etc.).
        role_spec: The current RoleSpecModel so the LLM can match evidence to requirements.
        consent_level: Controls whether snippets are included.

    Returns:
        List of EvidenceItem objects (without DB ids — caller sets those after insert).
    """
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
    llm_struct = llm.with_structured_output(_ExtractionResult, method="json_schema", strict=True)

    req_index: List[str] = []  # index → canonical req_summary
    requirements_text = "No role requirements provided."
    if role_spec and role_spec.requirements:
        req_index = [r.req_summary for r in role_spec.requirements]
        requirements_text = "\n".join(
            f"{i}. [{r.category}] {r.req_summary}"
            for i, r in enumerate(role_spec.requirements)
        )

    prompt = f"""\
Document type: {source_type}
Target role: {role_spec.canonical_role_title if role_spec else "Unknown"}
Consent level: {consent_level}

Role requirements (use the index number, starting from 0, in matched_requirement_indices):
{requirements_text}

---
Parsed document content:

{markdown_content}
---

Extract all relevant evidence items from this document. For each item, return the index numbers of the requirements it supports in matched_requirement_indices.
"""

    result: _ExtractionResult = invoke_with_retry(
        llm_struct,
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
    )

    return [
        EvidenceItem(
            item_type=item.item_type,
            summary=item.summary,
            snippet=item.snippet,
            confidence=item.confidence,
            proficiency_score=item.proficiency_score,
            action_verbs=item.action_verbs,
            metadata={
                "matched_requirements": [
                    req_index[i] for i in item.matched_requirement_indices
                    if 0 <= i < len(req_index)
                ]
            },
        )
        for item in result.items
    ]


# StudentModel builder

def _norm(s: str) -> str:
    """Normalise a requirement string for fuzzy matching: lowercase, strip whitespace and trailing punctuation."""
    return s.lower().strip().rstrip(".,;:")


def build_student_model(
    evidence_items: List[EvidenceItem],
    role_spec: Optional[RoleSpecModel] = None,
) -> StudentModel:
    """
    Aggregate persisted EvidenceItems (with DB ids) into a StudentModel.
    evidence_map: req_summary -> [evidence_item_id, ...]

    LLM-produced matched_requirements strings often drop trailing punctuation or
    slightly rephrase the canonical req_summary. A normalised lookup maps them
    back to the canonical form so compute_student_scores can find the entries.
    """
    skills: List[str] = []
    experiences: List[str] = []
    education: List[str] = []
    evidence_map: Dict[str, List[str]] = {}

    # normalised_key -> canonical req_summary from role_spec
    canonical: Dict[str, str] = {}
    if role_spec:
        for r in role_spec.requirements:
            canonical[_norm(r.req_summary)] = r.req_summary

    for item in evidence_items:
        if item.item_type == "skill":
            skills.append(item.summary)
        elif item.item_type == "experience":
            experiences.append(item.summary)
        elif item.item_type == "coursework":
            education.append(item.summary)

        if item.id:
            for llm_req in item.metadata.get("matched_requirements", []):
                # resolve to canonical req_summary; skip category tags like "skill"/"knowledge"
                key = canonical.get(_norm(llm_req))
                if key:
                    evidence_map.setdefault(key, []).append(item.id)

    return StudentModel(
        skills=skills,
        experiences=experiences,
        education=education,
        evidence_map=evidence_map,
    )
