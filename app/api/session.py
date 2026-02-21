from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel
from app.tools.supabase_repo import SupabaseRepo
from app.tools.session_token import mint_session_token

router = APIRouter(prefix="/session", tags=["session"])
repo = SupabaseRepo()

class SessionStartResponse(BaseModel):
    session_token: str
    session_id: str

@router.post("/start", response_model=SessionStartResponse)
def start_session():
    session_id = repo.create_session()
    token = mint_session_token(session_id)
    return SessionStartResponse(session_token=token, session_id=session_id)

