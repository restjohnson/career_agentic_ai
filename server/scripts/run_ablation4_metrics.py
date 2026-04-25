"""
Ablation 4 metrics runner.

Runs 15 trials × 2 conditions (full COMPASS + ablation4) against the
scenario resume (scenario_4_resume.pdf). Conditions are interleaved within
each trial to control for temporal API bias. Each trial creates two separate
sessions (API enforces one run per session).

Prerequisites:
  - Server running: uvicorn app.main:app --reload  (from server/)
  - .env populated with all required keys

Usage:
  python scripts/run_ablation4_metrics.py
  python scripts/run_ablation4_metrics.py --trials 3   # quick smoke test
  python scripts/run_ablation4_metrics.py --url http://localhost:8001
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import sys
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL  = "http://localhost:8000"
N_TRIALS  = 15
RESUME_PATH = Path(__file__).parent / "scenario_4_resume.pdf"

SCENARIO = {
    "desired_role": "Full Stack Developer",
    "student_constraints": {
        "academic_level":          "bootcamp",
        "hours_per_week":          10,
        "target_goal":             "job_ready",
        "target_date":             "2026-08-14",    
        "preferred_learning_mode": "project_based",
    },
}

# ---------------------------------------------------------------------------
# Helpers (mirrors test_app_e2e.py)
# ---------------------------------------------------------------------------

def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _check(resp: requests.Response, label: str) -> dict:
    if not resp.ok:
        print(f"\n[FAIL] {label} — HTTP {resp.status_code}")
        try:
            print(json.dumps(resp.json(), indent=2))
        except Exception:
            print(resp.text)
        sys.exit(1)
    return resp.json()


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def step_health() -> None:
    resp = requests.get(f"{BASE_URL}/health", timeout=10)
    _check(resp, "GET /health")
    print("[OK]   Server healthy")


def step_start_session() -> tuple[str, str]:
    resp = requests.post(f"{BASE_URL}/session/start", timeout=10)
    data = _check(resp, "POST /session/start")
    return data["session_token"], data["session_id"]


def step_upload_evidence(token: str) -> str:
    with open(RESUME_PATH, "rb") as fh:
        files = {"file": (RESUME_PATH.name, fh, "application/pdf")}
        resp = requests.post(
            f"{BASE_URL}/evidence",
            headers=_bearer(token),
            data={"source_type": "resume", "consent_level": "excerpt_ok"},
            files=files,
            timeout=30,
        )
    data = _check(resp, f"POST /evidence ({RESUME_PATH.name})")
    return data["document_id"]


def step_create_run(token: str, doc_id: str, condition: str) -> str:
    payload = {
        "desired_role":          SCENARIO["desired_role"],
        "evidence_document_ids": [doc_id],
        "student_constraints":   SCENARIO["student_constraints"],
        "condition":             condition,
    }
    resp = requests.post(
        f"{BASE_URL}/runs",
        headers=_bearer(token),
        json=payload,
        timeout=15,
    )
    data = _check(resp, f"POST /runs (condition={condition!r})")
    return data["run_id"]


def step_stream_run(run_id: str, token: str) -> dict:
    url = f"{BASE_URL}/runs/{run_id}/stream?token={token}"
    with requests.get(url, stream=True, timeout=600) as resp:
        if not resp.ok:
            raise RuntimeError(f"SSE stream HTTP {resp.status_code}")
        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:].strip())
            etype = event.get("type")
            if etype == "step":
                print(f"         step: {event.get('step')}")
            elif etype == "done":
                return event.get("final_state", {})
            elif etype == "error":
                raise RuntimeError(f"Run error: {event.get('detail')}")
    return {}


def run_one(condition: str, trial: int, max_retries: int = 3) -> dict | None:
    """Run a single condition with retry on transient failures."""
    import time
    for attempt in range(1, max_retries + 1):
        try:
            token, _ = step_start_session()
            doc_id   = step_upload_evidence(token)
            run_id   = step_create_run(token, doc_id, condition)
            print(f"         run_id: {run_id}")
            final    = step_stream_run(run_id, token)
            return final
        except Exception as e:
            wait = 15 * attempt
            print(f"         [attempt {attempt}/{max_retries}] failed: {e}")
            if attempt < max_retries:
                print(f"         retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"         [SKIP] trial {trial} condition={condition!r} failed after {max_retries} attempts")
                return None


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------

def extract_metrics(final_state: dict, condition: str, trial: int) -> dict:
    critique    = final_state.get("critique") or {}
    scores      = critique.get("rubric_scores") or {}
    plan        = final_state.get("plan") or {}
    phases      = plan.get("phases") or []
    issues      = critique.get("issues") or []
    constraints = final_state.get("student_constraints") or {}

    mean_score = sum(scores.values()) / len(scores) if scores else 0.0

    return {
        "trial":                      trial,
        "condition":                  condition,
        "critique_iterations":        final_state.get("critique_iterations", -1),
        "satisfactory":               critique.get("satisfactory", False),
        "gap_coverage":               scores.get("gap_coverage", -1),
        "jit_compliance":             scores.get("jit_compliance", -1),
        "feasibility":                scores.get("feasibility", -1),
        "level_appropriateness":      scores.get("level_appropriateness", -1),
        "mean_rubric_score":          round(mean_score, 3),
        "best_critique_score":        round(final_state.get("best_critique_score", 0.0), 3),
        "narrative_feedback_present": bool(critique.get("narrative_feedback")),
        "plan_timeline_weeks":        plan.get("timeline_weeks", -1),
        "target_weeks":               constraints.get("target_weeks", 16),
        "num_phases":                 len(phases),
        "num_issues":                 len(issues),
    }


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

def print_summary(rows: list[dict]) -> None:
    full_rows     = [r for r in rows if r["condition"] == "full"]
    ablation_rows = [r for r in rows if r["condition"] == "ablation4"]

    dims = ["gap_coverage", "jit_compliance", "feasibility", "level_appropriateness",
            "mean_rubric_score"]

    print("\n" + "=" * 72)
    print("ABLATION 4 SUMMARY  (mean ± std across trials)")
    print("=" * 72)
    print(f"{'Metric':<28} {'full mean±std':>16} {'ablation4 mean±std':>20}")
    print("-" * 66)

    def mean_sd(rows, key):
        vals = [r[key] for r in rows if isinstance(r[key], (int, float))]
        mu = sum(vals) / len(vals)
        sd = (sum((v - mu) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5
        return mu, sd

    for dim in dims:
        f_mu, f_sd = mean_sd(full_rows, dim)
        a_mu, a_sd = mean_sd(ablation_rows, dim)
        print(f"  {dim:<26} {f_mu:.2f} ± {f_sd:.2f}     {a_mu:.2f} ± {a_sd:.2f}")

    def sat_rate(rows):
        n = len(rows)
        return f"{sum(1 for r in rows if r['satisfactory']) / n * 100:.0f}%" if n else "—"

    print(f"  {'satisfactory rate':<26} {sat_rate(full_rows):>16} {sat_rate(ablation_rows):>20}")

    f_iters = [r["critique_iterations"] for r in full_rows if r["critique_iterations"] >= 0]
    a_iters = [r["critique_iterations"] for r in ablation_rows if r["critique_iterations"] >= 0]
    f_mu_i, f_sd_i = mean_sd(full_rows, "critique_iterations")
    a_mu_i, a_sd_i = mean_sd(ablation_rows, "critique_iterations")
    print(f"  {'critique_iterations':<26} {f_mu_i:.2f} ± {f_sd_i:.2f}     {a_mu_i:.2f} ± {a_sd_i:.2f}")

    narr_abl = sum(1 for r in ablation_rows if r["narrative_feedback_present"])
    print(f"\n  narrative_feedback_present (ablation4): {narr_abl}/{len(ablation_rows)} runs")
    print("  (confirms _reflect() ran but was never acted on)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    global BASE_URL
    parser = argparse.ArgumentParser(description="Ablation 4 metrics runner")
    parser.add_argument("--trials", type=int, default=N_TRIALS,
                        help=f"Number of trials per condition (default: {N_TRIALS})")
    parser.add_argument("--url", default=BASE_URL,
                        help=f"Base URL for the API (default: {BASE_URL})")
    args = parser.parse_args()

    BASE_URL = args.url

    if not RESUME_PATH.exists():
        print(f"[ERROR] Resume not found: {RESUME_PATH}")
        sys.exit(1)

    print(f"\nAblation 4 — Metrics Runner")
    print(f"  Trials per condition : {args.trials}")
    print(f"  Conditions           : full, ablation4  (interleaved)")
    print(f"  Resume               : {RESUME_PATH.name}")
    print(f"  Role                 : {SCENARIO['desired_role']}")
    print(f"  Constraints          : {SCENARIO['student_constraints']}\n")

    step_health()

    all_rows: list[dict] = []
    conditions = ["full", "ablation4"]

    skipped = 0
    for trial in range(1, args.trials + 1):
        print(f"\n--- Trial {trial}/{args.trials} ---")
        for condition in conditions:
            print(f"\n  [{condition}]")
            final = run_one(condition, trial)
            if final is None:
                skipped += 1
                continue
            row = extract_metrics(final, condition, trial)
            all_rows.append(row)

            scores = {k: row[k] for k in ["gap_coverage", "jit_compliance",
                                           "feasibility", "level_appropriateness"]}
            print(f"       scores: {scores}  sat={row['satisfactory']}  "
                  f"iters={row['critique_iterations']}")

    if skipped:
        print(f"\n[WARN] {skipped} run(s) were skipped after repeated failures.")

    print_summary(all_rows)

    # Write CSV
    ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(__file__).parent / f"ablation4_results_{ts}.csv"
    fieldnames = list(all_rows[0].keys())
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nResults saved → {out}")
    print("Run analyze_ablation4.py to generate plots and statistical tests.")


if __name__ == "__main__":
    main()
