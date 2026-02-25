from __future__ import annotations

from typing import Any, Dict

from app.state import AgentState, EvidenceItem
from app.tools.docling_parser import infer_suffix, parse_document_to_markdown
from app.tools.evidence_llm import build_student_model, extract_evidence_items
from app.tools.supabase_repo import SupabaseRepo


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
        s.errors.append("evidence_ingestion: no evidence documents found in state; skipping.")
        return s.model_dump(exclude_none=True)

    repo = SupabaseRepo()
    all_items: list[EvidenceItem] = []

    for doc in s.evidence_documents:
        if not doc.storage_ref:
            s.errors.append(
                f"evidence_ingestion: document {doc.id} has no storage_ref; skipping."
            )
            continue

        #download from Supabase Storage
        try:
            file_bytes = repo.download_evidence_file(doc.storage_ref)
        except Exception as e:
            s.errors.append(
                f"evidence_ingestion: failed to download {doc.storage_ref}: "
                f"{type(e).__name__}: {e}"
            )
            continue

        #Parse with Docling
        try:
            suffix = infer_suffix(doc.storage_ref)
            markdown_content = parse_document_to_markdown(file_bytes, suffix)
        except Exception as e:
            s.errors.append(
                f"evidence_ingestion: Docling parse failed for {doc.storage_ref}: "
                f"{type(e).__name__}: {e}"
            )
            continue

        #LLM extraction
        try:
            items = extract_evidence_items(
                markdown_content=markdown_content,
                source_type=doc.source_type,
                role_spec=s.role_spec,
                consent_level=doc.consent_level,
            )
        except Exception as e:
            s.errors.append(
                f"evidence_ingestion: LLM extraction failed for {doc.storage_ref}: "
                f"{type(e).__name__}: {e}"
            )
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
                        "metadata": item.metadata,
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

    s.evidence_items = all_items

    #build StudentModel from all extracted items (with ids set)
    try:
        s.student_model = build_student_model(all_items, role_spec=s.role_spec)
    except Exception as e:
        s.errors.append(
            f"evidence_ingestion: StudentModel build failed: {type(e).__name__}: {e}"
        )

    return s.model_dump(exclude_none=True)
