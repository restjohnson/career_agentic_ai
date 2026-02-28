from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

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
    matched_requirements: List[str] = Field(default_factory=list)


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
3. For matched_requirements: list the exact req_summary strings from the role requirements list that this evidence item supports.
   - For skill items: match directly against requirements of the same name or close equivalent.
   - For project and experience items: reason about what technologies, tools, and skills the work
     DEMONSTRATES (not just mentions), then match those inferred skills to the requirements list.
     Example: a project "Built a REST API with Django and PostgreSQL" demonstrates Python, Django,
     and PostgreSQL — match all three to their corresponding requirements if present in the list.
   - For coursework items: match the subject of the course to relevant requirements.
   - Leave empty only if no reasonable inference connects this item to any requirement.
4. Set confidence (0.00–1.00) based on how strongly this evidence relates to the matched role requirement(s).
   - range = [0.76 to 1.00]: Production or deployed usage with measurable outcomes at professional/internship levels (e.g. shipped a feature, led a team, deployed to users).
   - range = [0.51 to 0.75]: Used independently in a self-directed project with clear context and outcomes.
   - range = [0.26 to 0.50]: Used in a coursework, guided, or tutorial setting with limited independent application.
   - range = [0.0 to 0.25]: Only mentioned or loosely implied — no demonstration of actual usage.
   If the item has no matched requirements, set confidence to 0.5 as a neutral default.
5. snippet: Include the most relevant quoted text from the document ONLY if the consent_level is "excerpt_ok" or "raw_ok". Otherwise set snippet to null.
6. Do not invent capabilities the document does not support. If unsure, lower confidence rather than omitting.
7. Produce items in order of relevance to the target role (most relevant first).
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

    requirements_text = "No role requirements provided."
    if role_spec and role_spec.requirements:
        requirements_text = "\n".join(
            f"- [{r.category}] {r.req_summary}" for r in role_spec.requirements
        )

    prompt = f"""\
Document type: {source_type}
Target role: {role_spec.canonical_role_title if role_spec else "Unknown"}
Consent level: {consent_level}

Role requirements to match against:
{requirements_text}

---
Parsed document content:

{markdown_content}
---

Extract all relevant evidence items from this document. For each item, identify which role requirements it supports.
"""

    result: _ExtractionResult = llm_struct.invoke(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}]
    )

    return [
        EvidenceItem(
            item_type=item.item_type,
            summary=item.summary,
            snippet=item.snippet,
            confidence=item.confidence,
            metadata={"matched_requirements": item.matched_requirements},
        )
        for item in result.items
    ]


# StudentModel builder

def build_student_model(
    evidence_items: List[EvidenceItem],
    role_spec: Optional[RoleSpecModel] = None,
) -> StudentModel:
    """
    Aggregate persisted EvidenceItems (with DB ids) into a StudentModel.
    evidence_map: req_summary -> [evidence_item_id, ...]
    """
    skills: List[str] = []
    experiences: List[str] = []
    education: List[str] = []
    evidence_map: Dict[str, List[str]] = {}

    for item in evidence_items:
        if item.item_type == "skill":
            skills.append(item.summary)
        elif item.item_type == "experience":
            experiences.append(item.summary)
        elif item.item_type == "coursework":
            education.append(item.summary)

        if item.id:
            for req_summary in item.metadata.get("matched_requirements", []):
                evidence_map.setdefault(req_summary, []).append(item.id)

    return StudentModel(
        skills=skills,
        experiences=experiences,
        education=education,
        evidence_map=evidence_map,
    )
