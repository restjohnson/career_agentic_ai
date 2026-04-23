from __future__ import annotations

from typing import Any, Dict

from app.state import AgentState, GapReport
from app.tools.pathway_llm import synthesise_plan_single_pass
from app.tools.supabase_repo import SupabaseRepo


def _decode_resume(file_bytes: bytes) -> str:
    """
    Decode raw file bytes to plain text for the single-pass LLM prompt.
    For PDF/DOCX this produces imperfect output – but that is appropriate
    for a non-agentic baseline that lacks structured document parsing.
    For best results, use .txt format test scenario resumes.
    """
    try:
        return file_bytes.decode("utf-8", errors="replace")
    except Exception:
        return file_bytes.decode("latin-1", errors="replace")


def single_pass_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ablation 3 – Non-Agentic Single-Pass Baseline.

    Bypasses the entire COMPASS pipeline. Produces a CareerPlan from
    a single LLM call receiving only:
    - The student's desired role
    - Raw resume text (decoded from uploaded artefact)
    - Student constraints

    No role specification, no evidence extraction, no gap analysis,
    no structured state, no resource retrieval, no critique loop.

    The critique node is called once after plan generation for
    measurement purposes only – it does not trigger replanning.
    """
    s = AgentState.model_validate(state)
    s.step = "pathway_planning"

    if not s.student_constraints:
        s.errors.append("ablation3 single_pass: student_constraints missing.")
        return s.model_dump(exclude_none=True)

    # Get raw resume text from uploaded artefact or raw_user_text fallback
    raw_resume_text = ""

    if s.evidence_documents:
        repo = SupabaseRepo()
        texts = []
        for doc in s.evidence_documents:
            if not doc.storage_ref:
                continue
            try:
                file_bytes = repo.download_evidence_file(doc.storage_ref)
                texts.append(_decode_resume(file_bytes))
            except Exception as e:
                s.errors.append(
                    f"ablation3 single_pass: failed to download "
                    f"{doc.storage_ref}: {type(e).__name__}: {e}"
                )
        raw_resume_text = "\n\n".join(texts)

    # Fall back to raw_user_text if no documents or download failed
    if not raw_resume_text and s.raw_user_text:
        raw_resume_text = s.raw_user_text

    if not raw_resume_text:
        s.errors.append(
            "ablation3 single_pass: no resume content available. "
            "Provide evidence_documents or raw_user_text."
        )
        return s.model_dump(exclude_none=True)

    # Single LLM call – entire pipeline replaced
    try:
        s.plan = synthesise_plan_single_pass(
            desired_role=s.desired_role,
            raw_resume_text=raw_resume_text,
            constraints=s.student_constraints,
        )
    except Exception as e:
        s.errors.append(
            f"ablation3 single_pass: plan synthesis failed: "
            f"{type(e).__name__}: {e}"
        )
        return s.model_dump(exclude_none=True)

    # Set synthetic empty gap_report so critique node guard passes
    # (Option A from design doc)
    s.gap_report = GapReport(
        summary="Single-pass baseline – no gap analysis performed.",
        gaps=[]
    )

    s.status = "done"
    s.step = "explanation"
    return s.model_dump(exclude_none=True)
