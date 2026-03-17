# app/api/runs.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.state import AgentState, EvidenceDocument
from app.tools.supabase_repo import SupabaseRepo
from app.tools.session_token import get_session_id
from app.graph import build_graph

router = APIRouter(prefix="/runs", tags=["runs"])
repo = SupabaseRepo()
graph = build_graph(repo)


class RunCreateRequest(BaseModel):
    desired_role: str = Field(min_length=2)
    raw_user_text: Optional[str] = None
    evidence_document_ids: List[str] = Field(
        default_factory=list,
        description="IDs of evidence documents previously uploaded via POST /evidence.",
    )


class RunCreateResponse(BaseModel):
    run_id: str
    status: str
    final_state: Dict[str, Any]


@router.post("", response_model=RunCreateResponse)
def create_run(payload: RunCreateRequest, session_id: str = Depends(get_session_id)):
    run_id = repo.create_run(session_id=session_id, desired_role=payload.desired_role, status="running")

    evidence_documents: List[EvidenceDocument] = []
    for doc_id in payload.evidence_document_ids:
        doc_data = repo.get_evidence_document(session_id=session_id, document_id=doc_id)
        if not doc_data:
            raise HTTPException(
                status_code=404,
                detail=f"Evidence document '{doc_id}' not found or does not belong to this session.",
            )
        evidence_documents.append(EvidenceDocument(**doc_data))

    state = AgentState(
        session_id=session_id,
        run_id=run_id,
        desired_role=payload.desired_role,
        raw_user_text=payload.raw_user_text,
        evidence_documents=evidence_documents,
        status="running",
    )

    config = {"configurable": {"thread_id": run_id}}

    try:
        out: Any = graph.invoke(state, config=config)
        repo.set_run_status(session_id=session_id, run_id=run_id, status="done")
        final_state = AgentState.model_validate(out).model_dump(exclude_none=True)
        return RunCreateResponse(run_id=run_id, status="done", final_state=final_state)

    except Exception as e:
        repo.set_run_status(session_id=session_id, run_id=run_id, status="failed")
        raise HTTPException(status_code=500, detail=f"Run failed: {type(e).__name__}: {e}")


class RunLatestStateResponse(BaseModel):
    run_id: str
    latest_step: Optional[str] = None
    latest_state: Optional[Dict[str, Any]] = None


@router.get("/{run_id}", response_model=RunLatestStateResponse)
def get_run_latest(run_id: str, session_id: str = Depends(get_session_id)):
    latest = repo.get_latest_run_state(session_id=session_id, run_id=run_id)
    if not latest:
        return RunLatestStateResponse(run_id=run_id, latest_step=None, latest_state=None)

    return RunLatestStateResponse(
        run_id=run_id,
        latest_step=latest.get("step"),
        latest_state=latest.get("state"),
    )
