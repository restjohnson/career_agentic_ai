# test_evidence_pipeline.py  (run from project root)
import os
from dotenv import load_dotenv
load_dotenv()

from app.tools.docling_parser import parse_document_to_markdown
from app.tools.evidence_llm import extract_evidence_items, build_student_model

with open("test_resume.pdf", "rb") as f:
    file_bytes = f.read()

# Step 1: Docling parse
print("=== Docling markdown output (first 3000 chars) ===")
md = parse_document_to_markdown(file_bytes, ".pdf")
print(md[:3000])

# Step 2: LLM extraction (no role_spec = no requirement matching)
print("\n=== LLM-extracted evidence items ===")
items = extract_evidence_items(
    markdown_content=md,
    source_type="resume",
    role_spec=None,
    consent_level="excerpt_ok",
)
for item in items:
    print(f"[{item.item_type}] ({item.confidence:.2f}) {item.summary}")
    if item.snippet:
        print(f"    snippet: {item.snippet[:100]}")
    if item.metadata.get("matched_requirements"):
        print(f"    matched: {item.metadata['matched_requirements']}")
