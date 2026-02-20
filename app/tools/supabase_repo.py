from __future__ import annotations
import os
from typing import Any, Dict, List, Optional, Tuple

from supabase import create_client, Client

class SupabaseRepo:
    """
    Persistence Contract (currently no login session due to IRB limitations)
    Uses SERVICE ROLE KEY
    """
    def __init__(self) -> None:
        url = os.environ["SUPABASE_PUBLIC_URL"]
        service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        self.sb: Client = create_client(url, service_key)
    
    #sessions
    def create_session(self, expires_at_iso: Optional[str] = None) -> str:
        payload: Dict[str, Any] = {}
        if expires_at_iso:
            payload["expires_at"] = expires_at_iso
        
        res = self.sb.table("sessions").insert(payload).execute()
        if not res.data:
            raise RuntimeError(f"Failed to create session: {res}")
        return res.data[0]["id"]
    
    def create_run(self, session_id: str, desired_role: str, status: str = "queued") -> str:
        res = self.sb.table("runs").insert(
            {"session_id": session_id, "desired_role": desired_role, "status": status}
        ).execute()
        if not res.data:
            raise RuntimeError(f"Failed to create run: {res}")
        return res.data[0]["id"]
    

    def set_run_satus(self, session_id: str, run_id: str, status: str) -> None:
        res = self.sb.table("runs").update({"status": status}).eq("id", run_id).eq("session_id", session_id).execute()
        return None
    
    def append_run_state(
            self, 
            session_id: str, 
            run_id: str, 
            step: str, 
            state_json: Dict[str, Any], 
            contains_free_text: bool = False
            ) -> str:
        
        run = self.sb.table("runs").select("id").eq("id", run_id).eq("session_id", session_id).limit(1).execute()
        if not run.data:
            raise PermissionError("Run does not belong to session")
        
        res = self.sb.table("run_states").insert(
            {
                "run_id": run_id,
                "step": step,
                "state": state_json,
                "contains_free_text": contains_free_text,
            }
        ).execute()

        if not res.data:
            raise RuntimeError(f"Failed to append run state: {res}")
        
        return res.data[0]["id"]

    def get_latest_run_state(self, session_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        run = self.sb.table("runs").select("id").eq("id", run_id).eq("session_id", session_id).limit(1).execute()
        if not run.data:
            raise PermissionError("Run does not belong to session")
        
        res = (
            self.sb.table("run_states")
            .select("*").eq("run_id", run_id)
            .order("created_at", desc=True).limit(1).execute()
            )
        return res.data[0] if res.data else None
    
    def insert_evidence_document(
            self, 
            session_id: str, 
            source_type: str, 
            content_hash: str, 
            strorage_ref: Optional[str] = None,
            consent_level: str = "derived_only",
            ) -> str:
        
        res = self.sb.table("evidence_documents").insert(
            {
                "session_id": session_id,
                "source_type": source_type,
                "content_hash": content_hash,
                "storage_ref": strorage_ref,
                "consent_level": consent_level,
            }
        ).execute()
        if not res.data:
            raise RuntimeError(f"failed to insert evidence document: {res}")
        return res.data[0]["id"]
    
    def insert_evidence_items(self, document_id, str, items: List[Dict[str, Any]]) -> List[str]:
        payload = [{"document_id": document_id, **it} for it in items]
        res = self.sb.table("evidence_items").insert(payload).execute()
        if not res.data:
            raise RuntimeError(f"Failed to insert evidence items: {res}")
        
        return [row["id"] for row in res.data]
    
    #Role caching using the ONEt baseline

    def upsert_role(
            self, 
            role_title: str, 
            onet_code: Optional[str], 
            version: Optional[str],
            summary: Dict[str, Any]
        ) -> str:

        payload = {
            "role_title": role_title,
            "onet_code": onet_code,
            "version": version,
            "summary": summary,
        }
        res = self.sb.table("roles").upsert(payload).execute()
        if not res.data:
            raise RuntimeError(f"Failed to upsert role: {res}")
        return res.data[0]["id"]
    
    def replace_role_requirement(
            self,
            role_id: str,
            requirements: List[Dict[str, Any]]
    ) -> None:
        self.sb.table("role_requirements").delete().eq("role_id", role_id).execute()
        payload = [{"role_id": role_id, **r} for r in requirements]
        if payload:
            self.sb.table("role_requirements").insert(payload).execute()
        
        return None