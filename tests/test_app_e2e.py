"""
End-to-end smoke test for the Career Agentic AI API.

Prerequisites:
  - Server running: .venv/Scripts/python -m uvicorn app.main:app --reload
  - .env populated with OPENAI_API_KEY, SUPABASE_URL, SUPABASE_KEY, SESSION_SECRET

Run:
  .venv/Scripts/python tests/test_app_e2e.py
  .venv/Scripts/python tests/test_app_e2e.py --role "Machine Learning Engineer"
  .venv/Scripts/python tests/test_app_e2e.py --file path/to/resume.pdf
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

BASE_URL = "http://localhost:8000"

# ---------------------------------------------------------------------------
# Sample resume text used when no file is provided
# ---------------------------------------------------------------------------
SAMPLE_RESUME = """
John Smith
john.smith@email.com | github.com/jsmith

EDUCATION
BSc Computer Science, University of Manchester, 2021–2024
Relevant coursework: Machine Learning, Statistics, Databases, Algorithms

EXPERIENCE
Data Analyst Intern — Accenture (Jun 2023 – Aug 2023)
- Built ETL pipelines in Python (pandas, SQLAlchemy) processing 2M+ rows daily
- Created dashboards in Power BI for weekly stakeholder reporting
- Collaborated with ML team to validate model outputs

PROJECTS
Sentiment Analysis Pipeline (2024)
- Fine-tuned BERT for product review classification (92% accuracy)
- Deployed as REST API on AWS Lambda using Docker
- Wrote unit tests with pytest; CI/CD via GitHub Actions

House Price Predictor (2023)
- Trained XGBoost regression model on UK housing data
- Feature engineering, cross-validation, and hyperparameter tuning with Optuna

SKILLS
Python, SQL, pandas, scikit-learn, PyTorch, Docker, Git, Power BI
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check(resp: requests.Response, label: str) -> dict:
    if not resp.ok:
        print(f"\n[FAIL] {label} — HTTP {resp.status_code}")
        print(resp.text)
        sys.exit(1)
    data = resp.json()
    print(f"[OK]   {label}")
    return data


def _header(token: str) -> dict:
    return {"X-Session-Token": token}


def _pretty(obj: dict) -> str:
    return json.dumps(obj, indent=2, default=str)


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def step_start_session() -> tuple[str, str]:
    resp = requests.post(f"{BASE_URL}/session/start")
    data = _check(resp, "POST /session/start")
    print(f"       session_id    = {data['session_id']}")
    print(f"       session_token = {data['session_token'][:20]}…")
    return data["session_token"], data["session_id"]


def step_upload_evidence(token: str, file_path: Path | None) -> str:
    if file_path:
        suffix = file_path.suffix.lower()
        mime_map = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".doc": "application/msword",
            ".txt": "text/plain",
            ".md": "text/markdown",
        }
        content_type = mime_map.get(suffix, "application/octet-stream")
        files = {"file": (file_path.name, file_path.read_bytes(), content_type)}
        label = f"POST /evidence  ({file_path.name})"
    else:
        # Upload sample resume as plain text
        files = {"file": ("resume.txt", SAMPLE_RESUME.encode(), "text/plain")}
        label = "POST /evidence  (sample resume text)"

    data_fields = {"source_type": "resume", "consent_level": "derived_only"}
    resp = requests.post(
        f"{BASE_URL}/evidence",
        headers=_header(token),
        data=data_fields,
        files=files,
    )
    data = _check(resp, label)
    print(f"       document_id   = {data['document_id']}")
    return data["document_id"]


def step_create_run(token: str, document_id: str, role: str) -> dict:
    payload = {
        "desired_role": role,
        "evidence_document_ids": [document_id],
    }
    resp = requests.post(
        f"{BASE_URL}/runs",
        headers=_header(token),
        json=payload,
    )
    data = _check(resp, f"POST /runs  (role={role!r})")
    print(f"       run_id        = {data['run_id']}")
    print(f"       status        = {data['status']}")
    return data


def step_knowledge_assessment(token: str, run_id: str, concepts: list[str]) -> dict:
    print("\n[INFO] Graph paused for knowledge self-assessment.")
    print("       Concepts needing rating (0=None, 1=Familiar, 2=Working, 3=Strong):\n")

    inputs: dict[str, int] = {}
    for concept in concepts:
        while True:
            try:
                raw = input(f"  {concept}: ").strip()
                rating = int(raw)
                if rating not in (0, 1, 2, 3):
                    raise ValueError
                inputs[concept] = rating
                break
            except (ValueError, EOFError):
                # Non-interactive fallback: default all to 1
                print(f"  (non-interactive — defaulting to 1)")
                inputs[concept] = 1
                break

    resp = requests.post(
        f"{BASE_URL}/runs/{run_id}/knowledge-assessment",
        headers=_header(token),
        json={"inputs": inputs},
    )
    return _check(resp, f"POST /runs/{run_id}/knowledge-assessment")


def print_gap_report(final_state: dict) -> None:
    report = final_state.get("gap_report")
    if not report:
        print("\n[WARN] No gap_report in final state.")
        return

    print("\n" + "=" * 60)
    print("GAP REPORT SUMMARY")
    print("=" * 60)
    print(report.get("summary", ""))

    gaps = report.get("gaps", [])
    if not gaps:
        print("No gaps found.")
        return

    print(f"\n{'#':<4} {'Requirement':<45} {'Cat':<12} {'Score':<7} {'Req':<5} {'wGap':<7} {'Type':<14} {'RootCause'}")
    print("-" * 120)
    for i, g in enumerate(gaps, 1):
        print(
            f"{i:<4} {g.get('summary', '')[:44]:<45} "
            f"{g.get('category', '')[:11]:<12} "
            f"{g.get('student_score', 0):<7.2f} "
            f"{g.get('required_level', 0):<5.1f} "
            f"{g.get('weighted_gap', 0):<7.3f} "
            f"{g.get('gap_type', ''):<14} "
            f"{g.get('gap_root_cause') or '-'}"
        )

    # Knowledge prerequisites
    print("\n--- Knowledge Prerequisites ---")
    for g in gaps:
        prereqs = g.get("knowledge_prerequisites", [])
        if prereqs:
            print(f"\n  [{g.get('summary', '')[:60]}]")
            for p in prereqs:
                flag = " [ASSESS]" if p.get("needs_self_assessment") else ""
                fc = p.get("final_confidence")
                ic = p.get("inferred_confidence", 0)
                conf_str = f"final={fc:.2f}" if fc is not None else f"inferred={ic:.2f}"
                tier = p.get("inference_tier", "none")
                foundational = "FOUND" if p.get("is_foundational") else "supp."
                print(f"    [{foundational}] {p.get('concept', '')[:55]:<55}  {conf_str}  ({tier}){flag}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="E2E smoke test for Career Agentic AI")
    parser.add_argument("--role", default="Data Scientist", help="Target role (default: Data Scientist)")
    parser.add_argument("--file", type=Path, default=None, help="Path to evidence file (PDF, DOCX, TXT, MD)")
    parser.add_argument("--dump", action="store_true", help="Dump full final_state JSON at the end")
    args = parser.parse_args()

    print(f"\nCareer Agentic AI — E2E Test")
    print(f"  Target role : {args.role}")
    print(f"  Evidence    : {args.file or 'sample resume text'}")
    print(f"  Server      : {BASE_URL}\n")

    # 1. Session
    token, _ = step_start_session()

    # 2. Evidence
    doc_id = step_upload_evidence(token, args.file)

    # 3. Run
    run_data = step_create_run(token, doc_id, args.role)

    # 4. Handle interrupt
    if run_data["status"] == "awaiting_knowledge_assessment":
        concepts = run_data.get("knowledge_needing_assessment", [])
        run_data = step_knowledge_assessment(token, run_data["run_id"], concepts)

    # 5. Results
    final = run_data.get("final_state", {})
    print_gap_report(final)

    if args.dump:
        print("\n--- Full final_state ---")
        print(_pretty(final))

    print("\nDone.")


if __name__ == "__main__":
    main()
