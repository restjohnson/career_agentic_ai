from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from dotenv import load_dotenv

# Make server/app imports work when running this file directly.
SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

# Load server/.env so this script can run standalone from any shell.
load_dotenv(SERVER_ROOT / ".env")


def _sanitize_env_var(name: str) -> None:
    value = os.getenv(name)
    if not value:
        return
    cleaned = value.strip().strip('"').strip("'")
    os.environ[name] = cleaned


for _env_name in [
    "SUPABASE_PUBLIC_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "OPENAI_API_KEY",
    "ONET_API_KEY",
]:
    _sanitize_env_var(_env_name)

from app.nodes.critique import critique_node
from app.nodes.gap_analysis import gap_analysis_node
from app.nodes.pathway_planning import pathway_planning_node
from app.nodes.role_intake import role_intake_node
from app.state import AgentState, RoleSpecModel, RoleSpecRequirement, StudentConstraints
from app.tools.evidence_llm import build_student_model, extract_evidence_items
from app.tools.onet_client import OnetClient
from app.tools.supabase_repo import SupabaseRepo

SCENARIO_ROLE = "Machine Learning Engineer"

SCENARIO_PROFILE = """
Junior CS major, 2 years in.
Coursework: algorithms and linear algebra.
Project: sentiment analysis classifier in Jupyter notebook using scikit-learn.
Resume skills: Python, NumPy, Pandas, Git.
No production systems experience, no MLOps, no deployment.
""".strip()

DEFAULT_CONSTRAINTS = StudentConstraints(
    academic_level="junior",
    hours_per_week=12,
    target_goal="graduation",
    preferred_learning_mode="mixed",
)


def _initial_state(role: str, profile_text: str, constraints: StudentConstraints) -> AgentState:
    return AgentState(
        session_id=f"ablation-{uuid4()}",
        run_id=f"ablation-run-{uuid4()}",
        desired_role=role,
        raw_user_text=profile_text,
        student_constraints=constraints,
        status="running",
    )


def _ablation1_role_intake(state: AgentState) -> AgentState:
    """
    Ablation 1 baseline:
    - direct O*NET keyword search
    - top result only
    - raw structural mapping from O*NET tech payloads
    - no provenance attribution
    """
    s = AgentState.model_validate(state.model_dump())
    s.step = "role_intake"

    client = OnetClient()
    hits = client.search_occupations(s.desired_role, limit=5)

    if not hits:
        s.errors.append("Ablation1 role intake: no O*NET keyword matches found.")
        return s

    top = hits[0]
    onet_code = top.get("code") or top.get("onet_code") or top.get("id")
    role_title = top.get("title") or top.get("name") or s.desired_role

    if not onet_code:
        s.errors.append("Ablation1 role intake: top O*NET match missing code.")
        return s

    tech = client.get_occupation_technology(onet_code)
    hot_tech = client.get_hot_technology_skills(onet_code)

    reqs: List[RoleSpecRequirement] = []

    # tech payload shape from OnetClient: {category_title: [example1, example2, ...]}
    if isinstance(tech, dict):
        seen = set()
        for _, examples in tech.items():
            if not isinstance(examples, list):
                continue
            for item in examples:
                if not isinstance(item, str):
                    continue
                summary = item.strip()
                if not summary:
                    continue
                key = summary.lower()
                if key in seen:
                    continue
                seen.add(key)
                reqs.append(
                    RoleSpecRequirement(
                        req_summary=summary,
                        category="tech",
                        provenance=[],
                        optional=False,
                    )
                )

    # hot_tech payload typically includes a list under one of these keys.
    hot_items: List[Any] = []
    if isinstance(hot_tech, dict):
        for k in ["hot_technology", "hotTechnology", "technology", "tools", "tool"]:
            if isinstance(hot_tech.get(k), list):
                hot_items = hot_tech[k]
                break

    seen_hot = {r.req_summary.lower() for r in reqs}
    for item in hot_items:
        summary = None
        if isinstance(item, str):
            summary = item.strip()
        elif isinstance(item, dict):
            for key in ["title", "name", "description", "label", "example", "commodity_title"]:
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    summary = val.strip()
                    break
        if not summary:
            continue
        key = summary.lower()
        if key in seen_hot:
            continue
        seen_hot.add(key)
        reqs.append(
            RoleSpecRequirement(
                req_summary=summary,
                category="hot_technology",
                provenance=[],
                optional=False,
            )
        )

    spec = RoleSpecModel(
        canonical_role_title=role_title,
        matched_onet_code=onet_code,
        confidence_role_match=0.7,
        requirements=reqs,
        assumptions=[],
    )

    s.role_spec = spec
    return s


def _inject_student_evidence(state: AgentState, profile_text: str) -> AgentState:
    """
    Build evidence_items and student_model directly from scenario text so the
    experiment is reproducible without uploading files.
    """
    s = AgentState.model_validate(state.model_dump())
    s.step = "evidence_ingestion"

    if not s.role_spec:
        s.errors.append("evidence injection: role_spec missing.")
        return s

    items = extract_evidence_items(
        markdown_content=profile_text,
        source_type="resume",
        role_spec=s.role_spec,
        consent_level="derived_only",
    )

    # Use deterministic synthetic ids for downstream evidence_map linkage.
    for idx, item in enumerate(items, start=1):
        item.id = f"ev-{idx}"

    s.evidence_items = items
    s.student_model = build_student_model(items, role_spec=s.role_spec)
    return s


def _run_planning_loop(state: AgentState, repo: SupabaseRepo) -> AgentState:
    """
    Mirrors graph routing:
    - pathway_planning -> critique
    - stop on satisfactory, max 3 iterations, or convergence stall
    - finalise fallback to best_plan if not satisfactory
    """
    s = AgentState.model_validate(state.model_dump())

    while True:
        s = AgentState.model_validate(pathway_planning_node(s.model_dump(exclude_none=True), repo))
        s = AgentState.model_validate(critique_node(s.model_dump(exclude_none=True)))

        if s.critique_iterations >= 3:
            break

        if s.critique and s.critique.satisfactory:
            break

        if s.critique_iterations > 0 and s.critique:
            prev = set(s.prev_critique_issues)
            curr = set(s.critique.issues)
            if prev == curr:
                break

    if s.best_plan and not (s.critique and s.critique.satisfactory):
        s.plan = s.best_plan

    s.step = "explanation"
    s.status = "done"
    return s


def _collect_metrics(state: AgentState, condition: str) -> Dict[str, Any]:
    role_spec = state.role_spec
    gap_report = state.gap_report
    critique = state.critique

    requirements = role_spec.requirements if role_spec else []
    gaps = gap_report.gaps if gap_report else []

    return {
        "condition": condition,
        "canonical_role_title": role_spec.canonical_role_title if role_spec else None,
        "matched_onet_code": role_spec.matched_onet_code if role_spec else None,
        "num_requirements": len(requirements),
        "requirement_categories": sorted({r.category for r in requirements}),
        "num_requirements_with_provenance": sum(1 for r in requirements if len(r.provenance) > 0),
        "num_gaps": len(gaps),
        "num_no_evidence_gaps": sum(1 for g in gaps if g.gap_type == "no_evidence"),
        "critique_satisfactory": bool(critique.satisfactory) if critique else False,
        "critique_rubric_scores": (critique.rubric_scores if critique else {}),
        "critique_iterations": state.critique_iterations,
        "errors": state.errors,
    }


def _run_condition(
    *,
    condition_name: str,
    use_ablation1_role_intake: bool,
    repo: SupabaseRepo,
    role: str,
    profile_text: str,
    constraints: StudentConstraints,
) -> Dict[str, Any]:
    s = _initial_state(role=role, profile_text=profile_text, constraints=constraints)

    if use_ablation1_role_intake:
        s = _ablation1_role_intake(s)
    else:
        s = AgentState.model_validate(role_intake_node(s.model_dump(exclude_none=True)))

    s = _inject_student_evidence(s, profile_text=profile_text)
    s = AgentState.model_validate(gap_analysis_node(s.model_dump(exclude_none=True)))
    s = _run_planning_loop(s, repo=repo)

    metrics = _collect_metrics(s, condition=condition_name)
    return {
        "metrics": metrics,
        "final_state": s.model_dump(exclude_none=True),
    }


def _write_results(out_dir: Path, payload: Dict[str, Any]) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = out_dir / f"ablation1_ml_engineer_{ts}.json"
    csv_path = out_dir / f"ablation1_ml_engineer_{ts}.csv"

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    rows = payload["results"]
    csv_headers = [
        "condition",
        "canonical_role_title",
        "matched_onet_code",
        "num_requirements",
        "requirement_categories",
        "num_requirements_with_provenance",
        "num_gaps",
        "num_no_evidence_gaps",
        "critique_satisfactory",
        "critique_rubric_scores",
        "critique_iterations",
        "errors",
    ]

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **row,
                    "requirement_categories": "|".join(row.get("requirement_categories", [])),
                    "critique_rubric_scores": json.dumps(row.get("critique_rubric_scores", {})),
                    "errors": json.dumps(row.get("errors", [])),
                }
            )

    return {"json": json_path, "csv": csv_path}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Ablation 1 (Remove Role Grounding) vs Full COMPASS for ML Engineer scenario."
    )
    parser.add_argument("--role", default=SCENARIO_ROLE, help="Target role title")
    parser.add_argument(
        "--profile-file",
        type=Path,
        default=None,
        help="Optional path to a text/markdown file overriding the built-in student profile.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=SERVER_ROOT / "results" / "ablation",
        help="Directory to write JSON and CSV outputs.",
    )
    args = parser.parse_args()

    profile_text = SCENARIO_PROFILE
    if args.profile_file:
        profile_text = args.profile_file.read_text(encoding="utf-8")

    repo = SupabaseRepo()

    print("Running Full COMPASS condition...")
    full = _run_condition(
        condition_name="full_compass",
        use_ablation1_role_intake=False,
        repo=repo,
        role=args.role,
        profile_text=profile_text,
        constraints=DEFAULT_CONSTRAINTS,
    )

    print("Running Ablation 1 condition...")
    abl1 = _run_condition(
        condition_name="ablation1_no_role_grounding",
        use_ablation1_role_intake=True,
        repo=repo,
        role=args.role,
        profile_text=profile_text,
        constraints=DEFAULT_CONSTRAINTS,
    )

    results = [full["metrics"], abl1["metrics"]]
    payload = {
        "experiment": "ablation1_remove_role_grounding",
        "scenario": {
            "role": args.role,
            "student_profile": profile_text,
            "constraints": DEFAULT_CONSTRAINTS.model_dump(),
        },
        "results": results,
        "final_states": {
            "full_compass": full["final_state"],
            "ablation1_no_role_grounding": abl1["final_state"],
        },
    }

    paths = _write_results(args.out_dir, payload)

    print("\nAblation run complete.")
    print(f"JSON: {paths['json']}")
    print(f"CSV:  {paths['csv']}")


if __name__ == "__main__":
    main()
