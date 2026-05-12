from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional

from app.state import AgentState, EvidenceItem, RoleSpecModel
from app.tools.docling_parser import infer_suffix, parse_document_to_markdown
from app.tools.evidence_llm import build_student_model, extract_evidence_items
from app.tools.selfreport_llm import assess_student_holistic
from app.tools.supabase_repo import SupabaseRepo

def _role_hash(role_spec: Optional[RoleSpecModel]) -> str:
    """
    SHA-256 hash of sorted requirement summaries.
    Used as a role-scoped cache key for evidence items — ensures that
    the same document re-extracted for a different role does not reuse
    stale matched_requirements from a previous run.
    """
    if not role_spec or not role_spec.requirements:
        return "no_role"
    summaries = sorted(r.req_summary for r in role_spec.requirements)
    return hashlib.sha256("|".join(summaries).encode()).hexdigest()


def evidence_ingestion_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evidence ingestion node.

    For each EvidenceDocument in state:
      1. Download the raw file from Supabase Storage.
      2. Parse it to markdown using Docling.
      3. Use an LLM to extract structured EvidenceItems, role-aware against role_spec.
      4. Persist EvidenceItems to the DB and back-fill their ids.

    After all documents are processed, build a StudentModel and attach it to state.
    """
    s = AgentState.model_validate(state)
    s.step = "evidence_ingestion"

    if not s.evidence_documents:
        print("[EVIDENCE] No evidence documents in state — skipping.", flush=True)
        s.errors.append("evidence_ingestion: no evidence documents found in state; skipping.")
        return s.model_dump(exclude_none=True)

    print(f"[EVIDENCE] Processing {len(s.evidence_documents)} document(s).", flush=True)

    repo = SupabaseRepo()
    all_items: list[EvidenceItem] = []

    role_hash = _role_hash(s.role_spec)
    onet_code = s.role_spec.matched_onet_code if s.role_spec else None
    use_ablation2 = s.condition == "ablation2"
    if use_ablation2:
        role_hash = f"ablation2_{role_hash}"

    for doc in s.evidence_documents:
        if not doc.storage_ref:
            s.errors.append(
                f"evidence_ingestion: document {doc.id} has no storage_ref; skipping."
            )
            continue

        print(f"[EVIDENCE] Document id={doc.id} storage_ref={doc.storage_ref}", flush=True)

        # Cache check — reuse persisted items only if extracted for same document + role
        if doc.id:
            cached_rows = repo.get_evidence_items_by_document(doc.id, role_hash)
            if cached_rows:
                items = [
                    EvidenceItem(
                        id=row["id"],
                        document_id=row["document_id"],
                        item_type=row["item_type"],
                        summary=row["summary"],
                        snippet=row.get("snippet"),
                        confidence=row.get("confidence", 0.8),
                        confidence_reason=row.get("confidence_reason"),
                        metadata=row.get("metadata") or {},
                    )
                    for row in cached_rows
                ]
                print(f"[EVIDENCE] Cache hit: {len(cached_rows)} items for doc {doc.id}", flush=True)
                all_items.extend(items)
                continue

        #download from Supabase Storage
        try:
            file_bytes = repo.download_evidence_file(doc.storage_ref)
            print(f"[EVIDENCE] Downloaded {len(file_bytes)} bytes from {doc.storage_ref}", flush=True)
        except Exception as e:
            print(f"[EVIDENCE] Download FAILED: {type(e).__name__}: {e}", flush=True)
            s.errors.append(
                f"evidence_ingestion: failed to download {doc.storage_ref}: "
                f"{type(e).__name__}: {e}"
            )
            continue

        # ----------------------------------------------------------------
        # ABLATION 2: Docling parse → single holistic LLM assessment.
        #   Bypasses per-item evidence extraction entirely.
        #   Populates selfreport_scores (req_summary → student_level 0–3).
        #   No evidence items are written; gap_analysis uses scores directly.
        # FULL COMPASS: Docling parse → typed evidence extraction.
        # ----------------------------------------------------------------
        if use_ablation2:
            try:
                suffix = infer_suffix(doc.storage_ref)
                markdown_content = parse_document_to_markdown(file_bytes, suffix)
                print(f"[ABLATION2] Docling parsed {len(markdown_content)} chars", flush=True)
            except Exception as e:
                print(f"[ABLATION2] Docling FAILED: {type(e).__name__}: {e}", flush=True)
                s.errors.append(
                    f"evidence_ingestion: ablation2 Docling parse failed for {doc.storage_ref}: "
                    f"{type(e).__name__}: {e}"
                )
                continue

            try:
                scores = assess_student_holistic(markdown_content, s.role_spec)
                s.selfreport_scores = scores
                print(f"[ABLATION2] Holistic assessment: {len(scores)} requirements scored.", flush=True)
            except Exception as e:
                print(f"[ABLATION2] Holistic assessment FAILED: {type(e).__name__}: {e}", flush=True)
                s.errors.append(
                    f"evidence_ingestion: ablation2 holistic assessment failed: "
                    f"{type(e).__name__}: {e}"
                )
                continue

            items = []

        else:
            # Full COMPASS path — Parse with Docling
            try:
                suffix = infer_suffix(doc.storage_ref)
                markdown_content = parse_document_to_markdown(file_bytes, suffix)
                print(f"[EVIDENCE] Docling parsed {len(markdown_content)} chars (suffix={suffix})", flush=True)
            except Exception as e:
                print(f"[EVIDENCE] Docling FAILED: {type(e).__name__}: {e}", flush=True)
                s.errors.append(
                    f"evidence_ingestion: Docling parse failed for {doc.storage_ref}: "
                    f"{type(e).__name__}: {e}"
                )
                continue

            if not markdown_content.strip():
                print(f"[EVIDENCE] WARNING: Docling returned empty content for {doc.storage_ref}", flush=True)

            try:
                items = extract_evidence_items(
                    markdown_content=markdown_content,
                    source_type=doc.source_type,
                    role_spec=s.role_spec,
                    consent_level=doc.consent_level,
                )
                print(f"[EVIDENCE] LLM extracted {len(items)} items from {doc.storage_ref}", flush=True)
            except Exception as e:
                print(f"[EVIDENCE] LLM extraction FAILED: {type(e).__name__}: {e}", flush=True)
                s.errors.append(
                    f"evidence_ingestion: LLM extraction failed for {doc.storage_ref}: "
                    f"{type(e).__name__}: {e}"
                )
                continue

        # Ablation2 produces no items — nothing to persist.
        if use_ablation2:
            continue

        #persist EvidenceItems and back-fill ids
        if doc.id and items:
            try:
                db_payload = [
                    {
                        "item_type": item.item_type,
                        "summary": item.summary,
                        "snippet": item.snippet,
                        "confidence": item.confidence,
                        "confidence_reason": item.confidence_reason,
                        "metadata": item.metadata,
                        "role_hash": role_hash,
                        "onet_code": onet_code,
                    }
                    for item in items
                ]
                inserted_ids = repo.insert_evidence_items(
                    document_id=doc.id, items=db_payload
                )
                for item, item_id in zip(items, inserted_ids):
                    item.id = item_id
                    item.document_id = doc.id
            except Exception as e:
                s.errors.append(
                    f"evidence_ingestion: DB write failed for {doc.storage_ref}: "
                    f"{type(e).__name__}: {e}"
                )

        all_items.extend(items)

    print(f"[EVIDENCE] Total items extracted: {len(all_items)}", flush=True)
    if s.errors:
        print(f"[EVIDENCE] Errors: {s.errors}", flush=True)
    s.evidence_items = all_items

    #build StudentModel from all extracted items (with ids set)
    try:
        s.student_model = build_student_model(all_items, role_spec=s.role_spec)
    except Exception as e:
        print(f"[EVIDENCE] StudentModel build FAILED: {type(e).__name__}: {e}", flush=True)
        s.errors.append(
            f"evidence_ingestion: StudentModel build failed: {type(e).__name__}: {e}"
        )

    return s.model_dump(exclude_none=True)
