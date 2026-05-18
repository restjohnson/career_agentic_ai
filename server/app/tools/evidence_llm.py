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
    confidence_reason: Optional[str] = None
    matched_requirement_indices: List[int] = Field(default_factory=list)


class _ExtractionResult(BaseModel):
    items: List[_ExtractedItem]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM = """You are an expert career evidence analyst.

You are given a parsed document from a student (resume, portfolio, etc.) and a list of role requirements for a target career role.

Your job is to extract ALL evidence items from the document — exhaustively, without filtering by role relevance.

Item types:
- experience: A work, internship, research, or teaching role entry.
- project: A standalone project the student built or contributed to.
- coursework: A degree (B.S., M.S., Ph.D., etc.), diploma, academic coursework, certification, or academic programme. Degrees and academic qualifications are ALWAYS coursework.
- claim: Any self-reported skill, tool, technology, or capability that is listed but not independently demonstrated by a project or experience entry. This includes all COMPETENCIES, Technical Skills, Summary statements, and skill list sections. Academic degrees are NOT claims.

Rules:
1. Extract EVERY item in the document regardless of relevance to the target role. Do not filter.
2. For COMPETENCIES, Technical Skills, or any skill list section: extract each distinct tool, technology, or skill as a SEPARATE claim item with its own entry. Do not group or summarise them into one item. For example, "Python, PyTorch, TensorFlow" should become three separate claim items.
3. For matched_requirement_indices: list the INDEX NUMBERS (0-based integers) of role requirements this item supports. Be generous — a project typically supports multiple requirements. Return an empty list if the item does not map to any requirement (this is fine).
4. Set confidence (0.00–1.00) based on the belief that the student truly possesses the requirement, given this evidence item:
   - 0.76–1.00: Production/deployed usage with measurable outcomes at professional level.
   - 0.51–0.75: Used independently in a self-directed project with clear outcomes.
   - 0.26–0.50: Used in coursework, guided, or tutorial setting.
   - 0.10–0.25: Only mentioned or listed without any demonstration context (typical for claim items).
   - 0.00–0.09: Completely unsupported — vague or unverifiable assertion.
5. For each assigned confidence level, include a reason why that evidence item deserves that confidence score.
   For example, "This project involved building a web scraper using Python and BeautifulSoup, which demonstrates independent use of Python with a clear outcome, so I assigned it a confidence of 0.65."
6. snippet: Include the most relevant quoted text when it strengthens the evidence item. Prefer direct quotes for projects and experience entries. For individual skill or tool claim items (e.g. "Python", "TensorFlow"), set to null.
7. Do not invent capabilities the document does not support.
"""


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def extract_evidence_items(
    *,
    markdown_content: str,
    source_type: str,
    role_spec: Optional[RoleSpecModel] = None,
) -> List[EvidenceItem]:
    """
    Use an LLM to extract structured EvidenceItems from Docling markdown output.

    Extraction is exhaustive — all items in the document are captured regardless
    of role relevance. Skill list entries (COMPETENCIES, Technical Skills, etc.)
    are each extracted as individual claim items.

    Args:
        markdown_content: Markdown representation of the parsed document.
        source_type: One of EvidenceSourceType ("resume", "portfolio", etc.).
        role_spec: The current RoleSpecModel so the LLM can match evidence to requirements.
    Returns:
        List of EvidenceItem objects (without DB ids — caller sets those after insert).
    """
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
    llm_struct = llm.with_structured_output(_ExtractionResult, method="json_schema", strict=True)

    req_index: List[str] = []
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

Role requirements (use index number, starting from 0, in matched_requirement_indices):
{requirements_text}

---
Parsed document content:

{markdown_content}
---

Extract ALL evidence items from this document. For skill list or competency sections, extract each tool or skill as a separate claim item. Use matched_requirement_indices to link items to requirements where applicable; leave it empty if an item does not map to any requirement.
"""

    result: _ExtractionResult = llm_struct.invoke(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}]
    )

    from collections import Counter
    type_counts = Counter(item.item_type for item in result.items)
    print(f"[EVIDENCE_LLM] Extracted {len(result.items)} items: {dict(type_counts)}", flush=True)
    for item in result.items:
        snippet_len = len(item.snippet) if item.snippet else 0
        print(f"[EVIDENCE_LLM]   {item.item_type:12s} | snippet_len={snippet_len:4d} | {item.summary[:60]}", flush=True)

    return [
        EvidenceItem(
            item_type=item.item_type,
            summary=item.summary,
            snippet=item.snippet,
            confidence=item.confidence,
            confidence_reason = item.confidence_reason,
            metadata={
                "matched_requirements": [
                    req_index[i] for i in item.matched_requirement_indices
                    if 0 <= i < len(req_index)
                ]
            },
        )
        for item in result.items
    ]


# ---------------------------------------------------------------------------
# StudentModel builder
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    """Normalise a requirement string for fuzzy matching."""
    return s.lower().strip().rstrip(".,;:")


def build_student_model(
    evidence_items: List[EvidenceItem],
    role_spec: Optional[RoleSpecModel] = None,
) -> StudentModel:
    """
    Aggregate persisted EvidenceItems (with DB ids) into a StudentModel.

    - skills:       populated from claim items (self-reported tools/skills)
    - experiences:  populated from experience items
    - education:    populated from coursework items
    - evidence_map: req_summary -> [evidence_item_id, ...] for gap analysis
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
        if item.item_type == "claim":
            skills.append(item.summary)
        elif item.item_type == "experience":
            experiences.append(item.summary)
        elif item.item_type == "coursework":
            education.append(item.summary)

        if item.id:
            for llm_req in item.metadata.get("matched_requirements", []):
                key = canonical.get(_norm(llm_req))
                if key:
                    evidence_map.setdefault(key, []).append(item.id)

    return StudentModel(
        skills=skills,
        experiences=experiences,
        education=education,
        evidence_map=evidence_map,
    )
