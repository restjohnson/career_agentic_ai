"""
End-to-end smoke test for the Career Agentic AI API.

Prerequisites:
  - Server running: .venv/Scripts/python -m uvicorn app.main:app --reload
  - .env populated with all required keys

Run:
  .venv/Scripts/python tests/test_app_e2e.py
  .venv/Scripts/python tests/test_app_e2e.py --role "Machine Learning Engineer"
  .venv/Scripts/python tests/test_app_e2e.py --file path/to/resume.pdf
  .venv/Scripts/python tests/test_app_e2e.py --dump
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

BASE_URL = "http://localhost:8000"

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
- Collaborated with ML team to validate model outputs using SQL queries

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
        try:
            print(json.dumps(resp.json(), indent=2))
        except Exception:
            print(resp.text)
        sys.exit(1)
    data = resp.json()
    print(f"[OK]   {label}")
    return data


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _pretty(obj: dict) -> str:
    return json.dumps(obj, indent=2, default=str)


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def step_health() -> None:
    resp = requests.get(f"{BASE_URL}/health")
    _check(resp, "GET /health")


def step_start_session() -> tuple[str, str]:
    resp = requests.post(f"{BASE_URL}/session/start")
    data = _check(resp, "POST /session/start")
    print(f"       session_id    = {data['session_id']}")
    print(f"       session_token = {data['session_token'][:24]}…")
    return data["session_token"], data["session_id"]


def step_upload_evidence(token: str, file_path: Path | None) -> str:
    if file_path:
        suffix = file_path.suffix.lower()
        mime_map = {
            ".pdf":  "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".doc":  "application/msword",
            ".txt":  "text/plain",
            ".md":   "text/markdown",
        }
        content_type = mime_map.get(suffix, "application/octet-stream")
        files = {"file": (file_path.name, file_path.read_bytes(), content_type)}
        label = f"POST /evidence  ({file_path.name})"
    else:
        files = {"file": ("resume.txt", SAMPLE_RESUME.encode(), "text/plain")}
        label = "POST /evidence  (sample resume text)"

    resp = requests.post(
        f"{BASE_URL}/evidence",
        headers=_bearer(token),
        data={"source_type": "resume", "consent_level": "excerpt_ok"},
        files=files,
    )
    data = _check(resp, label)
    print(f"       document_id   = {data['document_id']}")
    return data["document_id"]


def step_create_run(token: str, document_id: str, role: str, constraints: dict) -> dict:
    payload = {
        "desired_role": role,
        "evidence_document_ids": [document_id],
        "student_constraints": constraints,
    }
    resp = requests.post(
        f"{BASE_URL}/runs",
        headers=_bearer(token),
        json=payload,
    )
    data = _check(resp, f"POST /runs  (role={role!r})")
    print(f"       run_id        = {data['run_id']}")
    print(f"       status        = {data['status']}")
    return data


# ---------------------------------------------------------------------------
# Result printers
# ---------------------------------------------------------------------------

def print_gap_report(final_state: dict) -> None:
    report = final_state.get("gap_report")
    if not report:
        print("\n[WARN] No gap_report in final state.")
        return

    print("\n" + "=" * 70)
    print("GAP REPORT")
    print("=" * 70)
    print(report.get("summary", ""))

    gaps = report.get("gaps", [])
    if not gaps:
        print("No gaps found.")
        return

    print(f"\n{'#':<4} {'Requirement':<42} {'Cat':<10} {'Level':<7} {'Req':<5} {'wGap':<7} {'Type'}")
    print("-" * 90)
    for i, g in enumerate(gaps, 1):
        print(
            f"{i:<4} {g.get('summary', '')[:41]:<42} "
            f"{g.get('category', '')[:9]:<10} "
            f"{g.get('student_level', 0):<7.2f} "
            f"{g.get('required_level', 0):<5.1f} "
            f"{g.get('weighted_gap', 0):<7.3f} "
            f"{g.get('gap_type', '')}"
        )

    print("\n--- Knowledge Prerequisites ---")
    for g in gaps:
        prereqs = g.get("knowledge_prerequisites", [])
        if prereqs:
            print(f"\n  [{g.get('summary', '')[:65]}]")
            for p in prereqs:
                fc   = p.get("final_confidence", 0)
                ic   = p.get("inferred_confidence", 0)
                tier = p.get("inference_tier", "none")
                tag  = "FOUND" if p.get("is_foundational") else "supp."
                print(f"    [{tag}] {p.get('concept', '')[:55]:<56} fc={fc:.2f}  ic={ic:.2f}  ({tier})")


def print_plan(final_state: dict) -> None:
    plan = final_state.get("plan")
    if not plan:
        print("\n[WARN] No plan in final state.")
        return

    print("\n" + "=" * 70)
    print("CAREER PLAN")
    print("=" * 70)
    print(f"Total timeline: {plan.get('timeline_weeks')} weeks\n")

    for i, phase in enumerate(plan.get("phases", []), 1):
        print(f"Phase {i}: {phase.get('title')}  ({phase.get('weeks')}w)")
        print(f"  Outcome    : {phase.get('outcome', '')[:120]}")
        if phase.get("checkpoint"):
            print(f"  Checkpoint : {phase['checkpoint'][:120]}")
        if phase.get("resume_updates"):
            print(f"  Resume adds: {', '.join(phase['resume_updates'])[:120]}")

        for j, action in enumerate(phase.get("learning_actions", []), 1):
            bloom = action.get("bloom_level", "?")
            print(f"\n  Action {j} [{bloom}]: {action.get('title', '')}")
            print(f"    Summary  : {action.get('summary', '')[:110]}")
            print(f"    Rationale: {action.get('rationale', '')[:110]}")
            for r in action.get("example_resources", []):
                free = "free" if r.get("is_free") else ("paid" if r.get("is_free") is False else "?")
                hrs  = f"{r.get('estimated_hours')}h" if r.get("estimated_hours") else "?h"
                print(f"    └ [{r.get('resource_type','?'):<12}] {r.get('title','')[:55]:<56} ({free}, {hrs})")
        print()



def print_critique(final_state: dict) -> None:
    critique = final_state.get("critique")
    if not critique:
        print("\n[WARN] No critique in final state.")
        return

    print("\n" + "=" * 70)
    print("CRITIQUE REPORT")
    print("=" * 70)
    scores = critique.get("rubric_scores", {})
    thresholds = {
        "gap_coverage": 3, "prerequisite_ordering": 4,
        "feasibility": 3, "level_appropriateness": 3, "internship_readiness": 4,
    }
    for dim, score in scores.items():
        threshold = thresholds.get(dim, 3)
        status = "PASS" if score >= threshold else "FAIL"
        print(f"  {dim:<28} {score}/5  [{status}]")

    print(f"\n  Satisfactory     : {critique.get('satisfactory')}")
    print(f"  Iterations used  : {final_state.get('critique_iterations', '?')}")

    issues = critique.get("issues", [])
    if issues:
        print(f"\n  Issues ({len(issues)}):")
        for iss in issues:
            print(f"    - {iss}")
    else:
        print("\n  No issues.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="E2E smoke test for Career Agentic AI")
    parser.add_argument("--role",   default="Data Scientist",     help="Target role")
    parser.add_argument("--file",   type=Path, default=None,      help="Path to evidence file")
    parser.add_argument("--level",  default="junior",             help="academic_level")
    parser.add_argument("--hours",  type=int, default=15,         help="hours_per_week")
    parser.add_argument("--goal",   default="graduation",
                        choices=["first_internship", "graduation", "job_ready", "career_change"],
                        help="target_goal")
    parser.add_argument("--date",   default=None,                 help="target_date ISO YYYY-MM-DD (optional)")
    parser.add_argument("--mode",   default="mixed",              help="preferred_learning_mode")
    parser.add_argument("--dump",   action="store_true",          help="Dump full final_state JSON")
    args = parser.parse_args()

    constraints = {
        "academic_level":          args.level,
        "hours_per_week":          args.hours,
        "target_goal":             args.goal,
        "preferred_learning_mode": args.mode,
    }
    if args.date:
        constraints["target_date"] = args.date

    print(f"\nCareer Agentic AI — E2E Test")
    print(f"  Target role  : {args.role}")
    print(f"  Evidence     : {args.file or 'sample resume text'}")
    print(f"  Constraints  : {constraints}")
    print(f"  Server       : {BASE_URL}\n")

    step_health()
    token, _ = step_start_session()
    doc_id   = step_upload_evidence(token, args.file)
    run_data = step_create_run(token, doc_id, args.role, constraints)

    final = run_data.get("final_state", {})

    errors = final.get("errors", [])
    if errors:
        print(f"\n[WARN] Errors in final state ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")

    print_gap_report(final)
    print_plan(final)
    print_critique(final)

    if args.dump:
        print("\n--- Full final_state ---")
        print(_pretty(final))

    print("\nDone.")


if __name__ == "__main__":
    main()
