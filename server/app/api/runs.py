# app/api/runs.py
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.state import AgentState, EvidenceDocument, StudentConstraints
from app.tools.supabase_repo import SupabaseRepo
from app.tools.session_token import get_session_id, get_session_id_from_query
from app.graph import build_graph
from app.run_events import get_queue, publish, cleanup

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
    student_constraints: Optional[StudentConstraints] = Field(
        default=None,
        description="Learning constraints: academic_level, hours_per_week, target_goal, target_date (optional ISO date), preferred_learning_mode.",
    )


class RunCreateResponse(BaseModel):
    run_id: str
    status: str


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
        student_constraints=payload.student_constraints,
        status="running",
    )

    config = {"configurable": {"thread_id": run_id}}

    def _run_graph():
        try:
            print(f"[{run_id}] Starting graph invocation...")
            out: Any = graph.invoke(state, config=config)
            print(f"[{run_id}] Graph completed, setting status to done...")
            repo.set_run_status(session_id=session_id, run_id=run_id, status="done")
            final_state = AgentState.model_validate(out).model_dump(exclude_none=True)
            print(f"[{run_id}] Publishing done event...")
            publish(run_id, {"type": "done", "final_state": final_state})
            print(f"[{run_id}] Done event published")
        except Exception as e:
            print(f"[{run_id}] Graph error: {type(e).__name__}: {e}", flush=True)
            import traceback
            traceback.print_exc()
            repo.set_run_status(session_id=session_id, run_id=run_id, status="failed")
            publish(run_id, {"type": "error", "detail": f"{type(e).__name__}: {e}"})

    threading.Thread(target=_run_graph, daemon=True).start()

    return RunCreateResponse(run_id=run_id, status="running")


@router.get("/{run_id}/stream")
async def stream_run(run_id: str, session_id: str = Depends(get_session_id_from_query)):
    """SSE endpoint — streams step events as the agent graph executes."""
    q = get_queue(run_id)
    print(f"[{run_id}] SSE stream opened")

    async def event_generator():
        try:
            loop = asyncio.get_event_loop()
            while True:
                try:
                    # Use run_in_executor to call blocking queue.get() from thread pool
                    def get_event():
                        return q.get(block=True, timeout=300)

                    event = await asyncio.wait_for(
                        loop.run_in_executor(None, get_event),
                        timeout=310
                    )
                    print(f"[{run_id}] SSE sending event: {event.get('type')}")
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("type") in ("done", "error"):
                        print(f"[{run_id}] SSE stream closing (type={event.get('type')})")
                        break
                except asyncio.TimeoutError:
                    print(f"[{run_id}] SSE timeout")
                    yield f"data: {json.dumps({'type': 'error', 'detail': 'Timeout waiting for agent'})}\n\n"
                    break
        except Exception as e:
            print(f"[{run_id}] SSE error: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            print(f"[{run_id}] SSE stream cleaned up")
            cleanup(run_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
