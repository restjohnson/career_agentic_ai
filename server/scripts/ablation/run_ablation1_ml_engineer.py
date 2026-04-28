"""
Ablation 1 – Remove Role Grounding: API-based runner + matplotlib comparison plotter.

Calls the live COMPASS API server (default http://127.0.0.1:8000) to run both:
  - Full COMPASS  (ablation_mode="none")
  - Ablation 1    (ablation_mode="ablation1_no_role_grounding")

Each condition is run N times (default 15). Metrics are averaged across all runs
and standard deviations are computed. The plot shows mean bars with ±1 SD error
bars and is labelled clearly as an N-run average.

For each individual run the script:
  1. Creates a fresh session  (POST /session/start)
  2. Uploads test_resume.pdf  (POST /evidence)
  3. Starts a run             (POST /runs)
  4. Reads the SSE stream     (GET /runs/{id}/stream?token=…)
     until a {"type":"done"} or {"type":"error"} event arrives
  5. Extracts metrics from the returned final_state

After all runs it saves a JSON + CSV result file and generates a
matplotlib 4-panel comparison chart in results/ablation/.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import matplotlib.pyplot as plt
import numpy as np
import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SERVER_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESUME_PDF = SERVER_ROOT / "scripts" / "test_resume_jordan_hayes.pdf"
DEFAULT_OUT_DIR = SERVER_ROOT / "results" / "ablation"

SCENARIO_ROLE = "Machine Learning Engineer"

DEFAULT_CONSTRAINTS = {
    "academic_level": "junior",
    "hours_per_week": 12,
    "target_goal": "graduation",
    "preferred_learning_mode": "mixed",
}

# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _start_session(base: str) -> tuple[str, str]:
    """Returns (session_token, session_id)."""
    resp = requests.post(f"{base}/session/start", timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data["session_token"], data["session_id"]


def _upload_evidence(base: str, token: str, pdf_path: Path) -> str:
    """Upload the resume PDF and return the document_id."""
    with pdf_path.open("rb") as fh:
        resp = requests.post(
            f"{base}/evidence",
            headers={"Authorization": f"Bearer {token}"},
            data={"source_type": "resume", "consent_level": "derived_only"},
            files={"file": (pdf_path.name, fh, "application/pdf")},
            timeout=60,
        )
    resp.raise_for_status()
    return resp.json()["document_id"]


def _create_run(
    base: str,
    token: str,
    role: str,
    doc_id: str,
    ablation_mode: str,
    constraints: Dict[str, Any],
) -> str:
    """Create a run and return run_id."""
    resp = requests.post(
        f"{base}/runs",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "desired_role": role,
            "ablation_mode": ablation_mode,
            "evidence_document_ids": [doc_id],
            "student_constraints": constraints,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["run_id"]


def _stream_until_done(base: str, token: str, run_id: str, timeout: int = 600) -> Dict[str, Any]:
    """
    Read the SSE stream and return the final_state from the first
    ``{"type": "done"}`` event.  Raises on error or timeout.
    """
    url = f"{base}/runs/{run_id}/stream?token={token}"
    deadline = time.time() + timeout

    with requests.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        for raw_line in resp.iter_lines():
            if time.time() > deadline:
                raise TimeoutError(f"SSE stream timed out after {timeout}s for run {run_id}")
            if not raw_line:
                continue
            if isinstance(raw_line, bytes):
                raw_line = raw_line.decode("utf-8")
            if not raw_line.startswith("data:"):
                continue
            payload = json.loads(raw_line[5:].lstrip())
            event_type = payload.get("type", "")
            if event_type == "done":
                return payload["final_state"]
            if event_type == "error":
                raise RuntimeError(f"Run {run_id} failed: {payload.get('detail')}")
            # Progress events – just print a dot so the terminal shows activity
            print(".", end="", flush=True)

    raise RuntimeError(f"SSE stream closed without a 'done' event for run {run_id}")


# ---------------------------------------------------------------------------
# Metric extraction from final_state dict
# ---------------------------------------------------------------------------

def _collect_metrics(final_state: Dict[str, Any], condition: str) -> Dict[str, Any]:
    role_spec = final_state.get("role_spec") or {}
    gap_report = final_state.get("gap_report") or {}
    critique = final_state.get("critique") or {}

    requirements: List[Dict[str, Any]] = role_spec.get("requirements") or []
    gaps: List[Dict[str, Any]] = gap_report.get("gaps") or []
    rubric_scores: Dict[str, Any] = critique.get("rubric_scores") or {}

    return {
        "condition": condition,
        "canonical_role_title": role_spec.get("canonical_role_title"),
        "matched_onet_code": role_spec.get("matched_onet_code"),
        "num_requirements": len(requirements),
        "requirement_categories": sorted({r.get("category", "") for r in requirements}),
        "num_requirements_with_provenance": sum(
            1 for r in requirements if r.get("provenance")
        ),
        "num_gaps": len(gaps),
        "num_no_evidence_gaps": sum(
            1 for g in gaps if g.get("gap_type") == "no_evidence"
        ),
        "critique_satisfactory": bool(critique.get("satisfactory", False)),
        "critique_rubric_scores": {str(k): int(v) for k, v in rubric_scores.items()},
        "critique_iterations": int(final_state.get("critique_iterations", 0)),
        "errors": final_state.get("errors") or [],
    }


# ---------------------------------------------------------------------------
# Multi-run aggregation
# ---------------------------------------------------------------------------

_RUBRIC_DIMS = ["gap_coverage", "jit_compliance", "feasibility", "level_appropriateness"]


def _aggregate_metrics(runs: List[Dict[str, Any]], condition: str) -> Dict[str, Any]:
    """
    Compute per-metric mean and std across a list of individual run metric dicts.
    Returns a single dict whose numeric fields are means and whose *_std fields
    are standard deviations (0 if only one run).
    """
    if not runs:
        raise ValueError(f"No successful runs to aggregate for condition '{condition}'")

    numeric_keys = [
        "num_requirements",
        "num_requirements_with_provenance",
        "num_gaps",
        "num_no_evidence_gaps",
        "critique_iterations",
    ]

    agg: Dict[str, Any] = {
        "condition": condition,
        "n_runs": len(runs),
    }

    for key in numeric_keys:
        vals = [float(r[key]) for r in runs if key in r]
        agg[key] = statistics.mean(vals) if vals else 0.0
        agg[f"{key}_std"] = statistics.stdev(vals) if len(vals) > 1 else 0.0

    # critique_satisfactory as a success rate (0.0–1.0)
    sat_vals = [float(int(r.get("critique_satisfactory", False))) for r in runs]
    agg["critique_satisfactory"] = statistics.mean(sat_vals) if sat_vals else 0.0
    agg["critique_satisfactory_std"] = statistics.stdev(sat_vals) if len(sat_vals) > 1 else 0.0

    # rubric scores — mean and std per dimension
    agg["critique_rubric_scores"] = {}
    agg["critique_rubric_scores_std"] = {}
    for dim in _RUBRIC_DIMS:
        vals = [float(r.get("critique_rubric_scores", {}).get(dim, 0)) for r in runs]
        agg["critique_rubric_scores"][dim] = statistics.mean(vals)
        agg["critique_rubric_scores_std"][dim] = statistics.stdev(vals) if len(vals) > 1 else 0.0

    # metadata — most common role title, union of categories
    titles = [r.get("canonical_role_title") for r in runs if r.get("canonical_role_title")]
    agg["canonical_role_title"] = max(set(titles), key=titles.count) if titles else None

    cats: set = set()
    for r in runs:
        cats.update(r.get("requirement_categories", []))
    agg["requirement_categories"] = sorted(cats)

    codes = [r.get("matched_onet_code") for r in runs if r.get("matched_onet_code")]
    agg["matched_onet_code"] = max(set(codes), key=codes.count) if codes else None

    # collect all individual run metrics for JSON output
    agg["individual_runs"] = runs
    return agg


# ---------------------------------------------------------------------------
# Run one condition end-to-end via the API
# ---------------------------------------------------------------------------

def _run_condition_via_api(
    *,
    base: str,
    condition_name: str,
    ablation_mode: str,
    role: str,
    pdf_path: Path,
    constraints: Dict[str, Any],
    stream_timeout: int = 600,
) -> Dict[str, Any]:
    print(f"\n[{condition_name}] Starting session...", end=" ", flush=True)
    token, session_id = _start_session(base)
    print(f"session_id={session_id}")

    print(f"[{condition_name}] Uploading resume...", end=" ", flush=True)
    doc_id = _upload_evidence(base, token, pdf_path)
    print(f"doc_id={doc_id}")

    print(f"[{condition_name}] Creating run (ablation_mode={ablation_mode!r})...", end=" ", flush=True)
    run_id = _create_run(base, token, role, doc_id, ablation_mode, constraints)
    print(f"run_id={run_id}")

    print(f"[{condition_name}] Streaming (this may take several minutes) ", end="", flush=True)
    final_state = _stream_until_done(base, token, run_id, timeout=stream_timeout)
    print(" done.")

    metrics = _collect_metrics(final_state, condition=condition_name)
    return {"metrics": metrics, "final_state": final_state}


def _run_condition_n_times(
    *,
    base: str,
    n: int,
    condition_name: str,
    ablation_mode: str,
    role: str,
    pdf_path: Path,
    constraints: Dict[str, Any],
    stream_timeout: int = 600,
) -> Dict[str, Any]:
    """
    Run one condition n times, collect all individual metrics, and return
    the aggregated result alongside every individual run's final_state.
    Failed runs are skipped with a warning; raises if zero runs succeed.
    """
    individual_metrics: List[Dict[str, Any]] = []
    individual_final_states: List[Dict[str, Any]] = []

    for i in range(1, n + 1):
        print(f"\n[{condition_name}] ── Run {i}/{n} ──")
        try:
            result = _run_condition_via_api(
                base=base,
                condition_name=condition_name,
                ablation_mode=ablation_mode,
                role=role,
                pdf_path=pdf_path,
                constraints=constraints,
                stream_timeout=stream_timeout,
            )
            individual_metrics.append(result["metrics"])
            individual_final_states.append(result["final_state"])
            print(f"[{condition_name}] Run {i} complete – reqs={result['metrics']['num_requirements']}, gaps={result['metrics']['num_gaps']}, satisfactory={result['metrics']['critique_satisfactory']}")
        except Exception as exc:
            print(f"[{condition_name}] WARNING: run {i} failed – {exc}. Skipping.")

    if not individual_metrics:
        raise RuntimeError(f"All {n} runs failed for condition '{condition_name}'")

    print(f"\n[{condition_name}] Aggregating {len(individual_metrics)} successful run(s)...")
    aggregated = _aggregate_metrics(individual_metrics, condition=condition_name)
    return {
        "aggregated": aggregated,
        "individual_final_states": individual_final_states,
    }


# ---------------------------------------------------------------------------
# Persist results
# ---------------------------------------------------------------------------

def _write_results(out_dir: Path, payload: Dict[str, Any]) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = out_dir / f"ablation1_ml_engineer_{ts}.json"
    csv_path = out_dir / f"ablation1_ml_engineer_{ts}.csv"

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # CSV rows: one row per condition showing aggregate means
    csv_headers = [
        "condition",
        "n_runs",
        "canonical_role_title",
        "matched_onet_code",
        "num_requirements_mean",
        "num_requirements_std",
        "num_requirements_with_provenance_mean",
        "num_requirements_with_provenance_std",
        "num_gaps_mean",
        "num_gaps_std",
        "num_no_evidence_gaps_mean",
        "num_no_evidence_gaps_std",
        "critique_satisfactory_rate",
        "critique_satisfactory_std",
        "critique_rubric_scores_mean",
        "critique_rubric_scores_std",
        "critique_iterations_mean",
        "critique_iterations_std",
        "requirement_categories",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_headers)
        writer.writeheader()
        for agg in payload["aggregated_results"]:
            writer.writerow({
                "condition": agg["condition"],
                "n_runs": agg["n_runs"],
                "canonical_role_title": agg.get("canonical_role_title"),
                "matched_onet_code": agg.get("matched_onet_code"),
                "num_requirements_mean": round(agg["num_requirements"], 3),
                "num_requirements_std": round(agg.get("num_requirements_std", 0), 3),
                "num_requirements_with_provenance_mean": round(agg["num_requirements_with_provenance"], 3),
                "num_requirements_with_provenance_std": round(agg.get("num_requirements_with_provenance_std", 0), 3),
                "num_gaps_mean": round(agg["num_gaps"], 3),
                "num_gaps_std": round(agg.get("num_gaps_std", 0), 3),
                "num_no_evidence_gaps_mean": round(agg["num_no_evidence_gaps"], 3),
                "num_no_evidence_gaps_std": round(agg.get("num_no_evidence_gaps_std", 0), 3),
                "critique_satisfactory_rate": round(agg["critique_satisfactory"], 3),
                "critique_satisfactory_std": round(agg.get("critique_satisfactory_std", 0), 3),
                "critique_rubric_scores_mean": json.dumps(agg.get("critique_rubric_scores", {})),
                "critique_rubric_scores_std": json.dumps(agg.get("critique_rubric_scores_std", {})),
                "critique_iterations_mean": round(agg["critique_iterations"], 3),
                "critique_iterations_std": round(agg.get("critique_iterations_std", 0), 3),
                "requirement_categories": "|".join(agg.get("requirement_categories", [])),
            })

    return {"json": json_path, "csv": csv_path}


# ---------------------------------------------------------------------------
# matplotlib comparison chart (4-panel)
# ---------------------------------------------------------------------------

def _condition_label(value: str) -> str:
    return {
        "full_compass": "Full COMPASS",
        "ablation1_no_role_grounding": "Ablation 1",
    }.get(value, value)


def _plot(
    aggregated_list: List[Dict[str, Any]],
    scenario_role: str,
    output_path: Path,
    n_runs: int,
) -> None:
    """
    Generate a 4-panel comparison figure from aggregated (mean ± SD) metrics.
    Bar charts show mean with ±1 SD error bars.
    """
    labeled: Dict[str, Dict[str, Any]] = {
        _condition_label(m["condition"]): m for m in aggregated_list
    }
    conditions = ["Full COMPASS", "Ablation 1"]
    colors = ["#1f77b4", "#d62728"]
    ecolor = ["#0d4f8c", "#8b1a1a"]  # darker shades for error bars

    count_keys = ["num_requirements", "num_gaps", "num_no_evidence_gaps", "critique_iterations"]
    count_labels = ["Requirements", "Gaps", "No-Evidence Gaps", "Critique Iterations"]

    rubric_dimensions = _RUBRIC_DIMS
    rubric_labels = ["Gap Coverage", "JIT", "Feasibility", "Level Fit"]

    fig = plt.figure(figsize=(17, 13), constrained_layout=True)
    grid = fig.add_gridspec(2, 2)
    ax_counts = fig.add_subplot(grid[0, 0])
    ax_provenance = fig.add_subplot(grid[0, 1])
    ax_rubric = fig.add_subplot(grid[1, 0])
    ax_status = fig.add_subplot(grid[1, 1])

    x = np.arange(len(count_keys))
    width = 0.35

    # ----- Panel 1 – Core outcome metrics (mean ± SD) -----
    for idx, cond in enumerate(conditions):
        means = [labeled[cond][k] for k in count_keys]
        stds = [labeled[cond].get(f"{k}_std", 0) for k in count_keys]
        offset = -width / 2 if idx == 0 else width / 2
        bars = ax_counts.bar(
            x + offset, means, width=width, color=colors[idx], label=cond,
            yerr=stds, capsize=4, error_kw={"ecolor": ecolor[idx], "elinewidth": 1.5},
        )
        ax_counts.bar_label(bars, labels=[f"{v:.1f}" for v in means], padding=5, fontsize=9)
    ax_counts.set_xticks(x, count_labels, rotation=15, ha="right")
    ax_counts.set_title("Core Outcome Metrics", fontsize=14, fontweight="bold")
    ax_counts.set_ylabel(f"Count  (mean ± SD, N={n_runs})", fontsize=12)
    max_val = max(labeled[c][k] + labeled[c].get(f"{k}_std", 0) for c in conditions for k in count_keys)
    ax_counts.set_ylim(0, max_val * 1.35 + 2)
    ax_counts.tick_params(axis="both", labelsize=12)
    ax_counts.legend(frameon=False)
    ax_counts.text(
        0.01, 0.98,
        "Ablation 1 inflates requirement and gap counts\n"
        "because raw O*NET tech terms are not curated.",
        transform=ax_counts.transAxes, va="top", fontsize=10,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#cccccc"},
    )

    # ----- Panel 2 – Provenance (mean ± SD) -----
    prov_means = [labeled[c]["num_requirements_with_provenance"] for c in conditions]
    prov_stds = [labeled[c].get("num_requirements_with_provenance_std", 0) for c in conditions]
    bars = ax_provenance.bar(
        conditions, prov_means, color=colors,
        yerr=prov_stds, capsize=6, error_kw={"ecolor": "#333333", "elinewidth": 1.5},
    )
    ax_provenance.bar_label(bars, labels=[f"{v:.1f}" for v in prov_means], padding=5, fontsize=10)
    ax_provenance.set_title("Requirements With Provenance", fontsize=14, fontweight="bold")
    ax_provenance.set_ylabel(f"Count  (mean ± SD, N={n_runs})", fontsize=12)
    ax_provenance.set_ylim(0, max(prov_means) * 1.5 + 2)
    ax_provenance.tick_params(axis="both", labelsize=12)
    ax_provenance.text(
        0.01, 0.98,
        "Provenance supports traceability and auditability.\n"
        "Ablation 1 intentionally removes provenance (0).",
        transform=ax_provenance.transAxes, va="top", fontsize=10,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#cccccc"},
    )

    # ----- Panel 3 – Rubric scores (mean ± SD line chart) -----
    rubric_x = np.arange(len(rubric_dimensions))
    for idx, cond in enumerate(conditions):
        means = [labeled[cond]["critique_rubric_scores"].get(dim, 0) for dim in rubric_dimensions]
        stds = [labeled[cond]["critique_rubric_scores_std"].get(dim, 0) for dim in rubric_dimensions]
        ax_rubric.plot(rubric_x, means, marker="o", linewidth=2.5, color=colors[idx], label=cond)
        ax_rubric.fill_between(
            rubric_x,
            [m - s for m, s in zip(means, stds)],
            [m + s for m, s in zip(means, stds)],
            color=colors[idx], alpha=0.15,
        )
    ax_rubric.set_xticks(rubric_x, rubric_labels)
    ax_rubric.set_ylim(0, 8)
    ax_rubric.set_yticks(np.arange(0, 9, 1))
    ax_rubric.set_title("Final Critique Rubric Scores", fontsize=14, fontweight="bold")
    ax_rubric.set_ylabel(f"Score  (mean ± SD band, N={n_runs})", fontsize=12)
    ax_rubric.tick_params(axis="both", labelsize=12)
    ax_rubric.grid(axis="y", linestyle="--", alpha=0.35)
    ax_rubric.legend(frameon=False)
    ax_rubric.text(
        0.01, 0.98,
        "Largest separation is in Gap Coverage,\n"
        "showing weaker requirement-target alignment in Ablation 1.",
        transform=ax_rubric.transAxes, va="top", fontsize=10,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#cccccc"},
    )

    # ----- Panel 4 – Termination status (satisfactory rate) -----
    full_rate = labeled["Full COMPASS"]["critique_satisfactory"]
    abl_rate = labeled["Ablation 1"]["critique_satisfactory"]
    full_std = labeled["Full COMPASS"].get("critique_satisfactory_std", 0)
    abl_std = labeled["Ablation 1"].get("critique_satisfactory_std", 0)

    rate_labels = ["Full COMPASS", "Ablation 1"]
    rate_means = [full_rate, abl_rate]
    rate_stds = [full_std, abl_std]
    status_bars = ax_status.bar(
        rate_labels, rate_means, color=colors,
        yerr=rate_stds, capsize=6, error_kw={"ecolor": "#333333", "elinewidth": 1.5},
    )
    ax_status.bar_label(status_bars, labels=[f"{v*100:.0f}%" for v in rate_means], padding=5, fontsize=11)
    ax_status.set_ylim(0, 1.35)
    ax_status.set_yticks(np.arange(0, 1.2, 0.2))
    ax_status.set_yticklabels([f"{v*100:.0f}%" for v in np.arange(0, 1.2, 0.2)])
    ax_status.set_title("Satisfactory Run Rate", fontsize=14, fontweight="bold")
    ax_status.set_ylabel(f"Fraction satisfactory  (N={n_runs} runs)", fontsize=12)
    ax_status.tick_params(axis="both", labelsize=12)
    ax_status.text(
        0.01, 0.98,
        f"Full COMPASS converged satisfactorily in {full_rate*100:.0f}% of runs;\n"
        f"Ablation 1 converged in {abl_rate*100:.0f}% of runs.",
        transform=ax_status.transAxes, va="top", fontsize=10,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#cccccc"},
    )

    fig.suptitle(
        f"{n_runs}-Run Average: Ablation 1 vs Full COMPASS  ·  {scenario_role}\n"
        "Full COMPASS: curated, provenance-backed requirements  ·  "
        "Ablation 1: raw O*NET tech-only mapping, no curation",
        fontsize=16, fontweight="bold",
    )
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Chart saved → {output_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run Ablation 1 (Remove Role Grounding) vs Full COMPASS N times each via the live API, "
            "average the metrics, and generate a matplotlib comparison chart with error bars."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--role", default=SCENARIO_ROLE, help="Target role title")
    parser.add_argument(
        "--resume",
        type=Path,
        default=DEFAULT_RESUME_PDF,
        help="Path to the resume PDF to upload.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Directory to write JSON, CSV, and PNG outputs.",
    )
    parser.add_argument(
        "--n-runs",
        type=int,
        default=15,
        help="Number of times to run each condition (default 15). Results are averaged.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Seconds to wait for each SSE stream to finish (default 600).",
    )
    args = parser.parse_args()

    if not args.resume.exists():
        print(f"ERROR: Resume PDF not found at {args.resume}", file=sys.stderr)
        sys.exit(1)

    base = args.base_url.rstrip("/")

    # Verify the server is reachable before kicking off long runs
    try:
        requests.get(f"{base}/health", timeout=5).raise_for_status()
    except Exception as exc:
        print(f"ERROR: API server not reachable at {base} – {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Ablation 1 Experiment  ·  {args.n_runs} runs per condition")
    print(f"  Role: {args.role}")
    print(f"{'='*60}\n")

    print(f"=== Full COMPASS  ({args.n_runs} runs) ===")
    full = _run_condition_n_times(
        base=base,
        n=args.n_runs,
        condition_name="full_compass",
        ablation_mode="none",
        role=args.role,
        pdf_path=args.resume,
        constraints=DEFAULT_CONSTRAINTS,
        stream_timeout=args.timeout,
    )

    print(f"\n=== Ablation 1  ({args.n_runs} runs) ===")
    abl1 = _run_condition_n_times(
        base=base,
        n=args.n_runs,
        condition_name="ablation1_no_role_grounding",
        ablation_mode="ablation1_no_role_grounding",
        role=args.role,
        pdf_path=args.resume,
        constraints=DEFAULT_CONSTRAINTS,
        stream_timeout=args.timeout,
    )

    full_agg = full["aggregated"]
    abl1_agg = abl1["aggregated"]

    print(f"\n{'='*60}")
    print("  Aggregated Results Summary")
    print(f"{'='*60}")
    for agg in [full_agg, abl1_agg]:
        print(
            f"  {agg['condition']:40s}"
            f"  reqs={agg['num_requirements']:.1f}±{agg.get('num_requirements_std',0):.1f}"
            f"  gaps={agg['num_gaps']:.1f}±{agg.get('num_gaps_std',0):.1f}"
            f"  sat={agg['critique_satisfactory']*100:.0f}%"
            f"  iters={agg['critique_iterations']:.1f}"
        )

    payload = {
        "experiment": "ablation1_remove_role_grounding",
        "n_runs_per_condition": args.n_runs,
        "scenario": {
            "role": args.role,
            "resume_path": str(args.resume),
            "constraints": DEFAULT_CONSTRAINTS,
        },
        "aggregated_results": [full_agg, abl1_agg],
        "individual_final_states": {
            "full_compass": full["individual_final_states"],
            "ablation1_no_role_grounding": abl1["individual_final_states"],
        },
    }

    paths = _write_results(args.out_dir, payload)
    print(f"\nResults saved → JSON: {paths['json']}")
    print(f"               CSV:  {paths['csv']}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    png_path = args.out_dir / f"ablation1_ml_engineer_{ts}.png"
    _plot(
        aggregated_list=[full_agg, abl1_agg],
        scenario_role=args.role,
        output_path=png_path,
        n_runs=args.n_runs,
    )

    print(f"\nAblation experiment complete ({args.n_runs} runs per condition).")


if __name__ == "__main__":
    main()
