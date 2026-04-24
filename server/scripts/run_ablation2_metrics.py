"""
run_ablation2_metrics.py
========================
Ablation 2 metrics collection script.

Uses the REAL pipeline — real Supabase storage, real DB, real LLM calls.
No mocking. No monkey-patching.

Runs the resume through both conditions, optionally N times each:
  - Full COMPASS  (Docling ON, typed items)
  - Ablation 2    (no Docling, all items forced to claim)

Each run gets its own fresh Supabase session so the one-run-per-session
guard in runs.py is never triggered.

Usage (from project root, on branch test/ablation2):
    python server/scripts/run_ablation2_metrics.py --resume path/to/resume.pdf
    python server/scripts/run_ablation2_metrics.py --resume path/to/resume.pdf --runs 5

Outputs (saved to server/scripts/ablation2_results/):
    ablation2_metrics_<timestamp>.csv     — per-metric mean ± stdev table
    ablation2_raw_<timestamp>.json        — aggregated metrics + per-run raw items
    ablation2_figures_<timestamp>.png     — publication-ready graphs (error bars when N > 1)

Requirements:
    pip install matplotlib --break-system-packages
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path bootstrap — works whether you run from project root or server/scripts/
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "server"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / "server" / ".env")

from app.state import (
    AgentState,
    ConditionType,
    EvidenceDocument,
    StudentConstraints,
)
from app.tools.supabase_repo import SupabaseRepo
from app.run_events import cleanup


# ---------------------------------------------------------------------------
# Upload resume to Supabase — returns (session_id, document_id)
# ---------------------------------------------------------------------------
def upload_resume(
    repo: SupabaseRepo,
    file_bytes: bytes,
    filename: str,
    content_type: str = "application/pdf",
) -> tuple[str, str]:
    """
    Creates a fresh Supabase session, uploads the resume to Storage,
    inserts an evidence_document record, and returns the IDs.
    """
    import hashlib
    import uuid
    from app.tools.docling_parser import infer_suffix

    session_id = repo.create_session()
    print(f"    Session created : {session_id}")

    # Salt the hash so each run gets a unique storage_ref even for the same file,
    # preventing the evidence_items cache from collapsing multiple runs into one.
    run_salt = uuid.uuid4().hex
    content_hash = hashlib.sha256(file_bytes + run_salt.encode()).hexdigest()
    suffix = infer_suffix(filename, content_type)
    storage_ref = f"{session_id}/{content_hash}{suffix}"

    repo.upload_evidence_file(
        storage_ref=storage_ref,
        file_bytes=file_bytes,
        content_type=content_type,
    )
    print(f"    Storage ref     : {storage_ref}")

    document_id = repo.insert_evidence_document(
        session_id=session_id,
        source_type="resume",
        content_hash=content_hash,
        strorage_ref=storage_ref,      # matches the typo in supabase_repo.py
        consent_level="excerpt_ok",
    )
    print(f"    Document id     : {document_id}")

    return session_id, document_id


# ---------------------------------------------------------------------------
# Run the full graph for one condition
# ---------------------------------------------------------------------------
def run_graph_condition(
    label: str,
    condition: ConditionType,
    file_bytes: bytes,
    filename: str,
    role: str,
    constraints: StudentConstraints,
) -> AgentState:
    """
    Runs the complete COMPASS graph for one ablation condition.
    Creates a fresh Supabase session so the one-run-per-session guard
    in runs.py is never triggered between conditions or repeated runs.
    Returns the final AgentState.
    """
    print(f"\n{'='*60}")
    print(f"  Condition : {label}")
    print(f"  Mode      : {'ablation2 (no Docling, all items -> claim)' if condition == 'ablation2' else 'full (Docling ON, typed items)'}")
    print(f"{'='*60}")

    from app.graph import build_graph
    repo = SupabaseRepo()
    graph = build_graph(repo)

    session_id, document_id = upload_resume(
        repo=repo,
        file_bytes=file_bytes,
        filename=filename,
    )

    run_id = repo.create_run(
        session_id=session_id,
        desired_role=role,
        status="running",
    )
    print(f"    Run id          : {run_id}")

    doc_data = repo.get_evidence_document(
        session_id=session_id,
        document_id=document_id,
    )
    if not doc_data:
        raise RuntimeError(f"Could not fetch evidence document {document_id}")

    initial_state = AgentState(
        session_id=session_id,
        run_id=run_id,
        desired_role=role,
        evidence_documents=[EvidenceDocument(**doc_data)],
        student_constraints=constraints,
        condition=condition,
        status="running",
    )

    config = {"configurable": {"thread_id": run_id}, "recursion_limit": 15}

    print(f"\n  Invoking graph... (may take 2-4 minutes)")
    final_output = graph.invoke(initial_state, config=config)
    repo.set_run_status(session_id=session_id, run_id=run_id, status="done")
    cleanup(run_id)

    final_state = AgentState.model_validate(final_output)
    print(f"\n  Completed.")
    print(f"    Evidence items  : {len(final_state.evidence_items)}")
    if final_state.gap_report:
        print(f"    Gaps found      : {len(final_state.gap_report.gaps)}")
    if final_state.critique:
        print(f"    Satisfactory    : {final_state.critique.satisfactory}")
        print(f"    Rubric scores   : {final_state.critique.rubric_scores}")

    return final_state


# ---------------------------------------------------------------------------
# Collect metrics from a single completed AgentState
# ---------------------------------------------------------------------------
def collect_metrics(label: str, state: AgentState) -> Dict[str, Any]:
    items = state.evidence_items
    evidence_map = state.student_model.evidence_map if state.student_model else {}
    gaps = state.gap_report.gaps if state.gap_report else []
    rubric_scores = state.critique.rubric_scores if state.critique else {}
    student_levels = [g.student_level for g in gaps]

    return {
        "label": label,
        # Layer 1 signals — parsing quality
        "total_evidence_items": len(items),
        "item_type_distribution": dict(Counter(item.item_type for item in items)),
        "requirements_matched": len(evidence_map),
        # Layer 2 signals — proficiency collapse
        "mean_student_level": round(
            statistics.mean(student_levels), 4
        ) if student_levels else 0.0,
        "gap_type_distribution": dict(Counter(g.gap_type for g in gaps)),
        # End-to-end — plan quality
        "rubric_scores": rubric_scores,
        # Raw items for qualitative inspection
        "raw_items": [
            {
                "item_type": i.item_type,
                "summary": i.summary,
                "confidence": i.confidence,
                "confidence_reason": i.confidence_reason or "",
            }
            for i in items
        ],
    }


# ---------------------------------------------------------------------------
# Aggregate a list of per-run metric dicts into mean ± stdev
# ---------------------------------------------------------------------------
def aggregate_metrics(label: str, runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Collapses N per-run metric dicts into a single aggregated dict.
    Scalar metrics become means; distribution dicts become mean-count dicts.
    Stdev sibling keys (suffix _stdev) are added for every numeric field.
    When N == 1 all stdevs are 0.
    """
    n = len(runs)

    def _mean(vals):
        return round(statistics.mean(vals), 4) if vals else 0.0

    def _stdev(vals):
        return round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0

    def _agg_scalar(key):
        vals = [r[key] for r in runs if key in r]
        return _mean(vals), _stdev(vals)

    def _agg_dist(key):
        all_keys = sorted(set(k for r in runs for k in r.get(key, {})))
        means, stdevs = {}, {}
        for k in all_keys:
            vals = [r.get(key, {}).get(k, 0) for r in runs]
            means[k] = _mean(vals)
            stdevs[k] = _stdev(vals)
        return means, stdevs

    total_mean, total_stdev   = _agg_scalar("total_evidence_items")
    req_mean,   req_stdev     = _agg_scalar("requirements_matched")
    level_mean, level_stdev   = _agg_scalar("mean_student_level")
    type_means, type_stdevs   = _agg_dist("item_type_distribution")
    gap_means,  gap_stdevs    = _agg_dist("gap_type_distribution")
    rub_means,  rub_stdevs    = _agg_dist("rubric_scores")

    return {
        "label": label,
        "n_runs": n,
        "total_evidence_items":        total_mean,
        "total_evidence_items_stdev":  total_stdev,
        "item_type_distribution":      type_means,
        "item_type_distribution_stdev": type_stdevs,
        "requirements_matched":        req_mean,
        "requirements_matched_stdev":  req_stdev,
        "mean_student_level":          level_mean,
        "mean_student_level_stdev":    level_stdev,
        "gap_type_distribution":       gap_means,
        "gap_type_distribution_stdev": gap_stdevs,
        "rubric_scores":               rub_means,
        "rubric_scores_stdev":         rub_stdevs,
        # Keep raw_items from every run for qualitative inspection
        "per_run_raw_items": [r["raw_items"] for r in runs],
    }


# ---------------------------------------------------------------------------
# Print comparison table to terminal
# ---------------------------------------------------------------------------
def print_comparison_table(full: Dict, abl: Dict):
    n = full.get("n_runs", 1)
    multi = n > 1

    print("\n" + "=" * 72)
    hdr = f"  {'METRIC':<38} {'FULL COMPASS':>16} {'ABLATION 2':>16}"
    print(hdr)
    print("=" * 72)

    def _fmt(val, stdev_key, d):
        v = d.get(val, "—")
        if multi:
            s = d.get(stdev_key, 0)
            return f"{v} ±{s}"
        return str(v)

    scalar_rows = [
        ("Total evidence items",           "total_evidence_items",  "total_evidence_items_stdev"),
        ("Requirements matched",           "requirements_matched",  "requirements_matched_stdev"),
        ("Mean student level (gap items)", "mean_student_level",    "mean_student_level_stdev"),
    ]
    for display, key, skey in scalar_rows:
        fv = _fmt(key, skey, full)
        av = _fmt(key, skey, abl)
        print(f"  {display:<38} {fv:>16} {av:>16}")

    print("=" * 72)

    print("\n  Item type distribution:")
    all_types = sorted(set(list(full["item_type_distribution"]) + list(abl["item_type_distribution"])))
    print(f"  {'Type':<20} {'Full COMPASS':>16} {'Ablation 2':>16}")
    print("  " + "-" * 54)
    for t in all_types:
        fv = full["item_type_distribution"].get(t, 0)
        av = abl["item_type_distribution"].get(t, 0)
        if multi:
            fs = full["item_type_distribution_stdev"].get(t, 0)
            as_ = abl["item_type_distribution_stdev"].get(t, 0)
            print(f"  {t:<20} {f'{fv} ±{fs}':>16} {f'{av} ±{as_}':>16}")
        else:
            print(f"  {t:<20} {str(fv):>16} {str(av):>16}")

    if full["gap_type_distribution"] or abl["gap_type_distribution"]:
        print("\n  Gap type distribution:")
        all_gap = sorted(set(list(full["gap_type_distribution"]) + list(abl["gap_type_distribution"])))
        print(f"  {'Gap type':<20} {'Full COMPASS':>16} {'Ablation 2':>16}")
        print("  " + "-" * 54)
        for t in all_gap:
            fv = full["gap_type_distribution"].get(t, 0)
            av = abl["gap_type_distribution"].get(t, 0)
            if multi:
                fs = full["gap_type_distribution_stdev"].get(t, 0)
                as_ = abl["gap_type_distribution_stdev"].get(t, 0)
                print(f"  {t:<20} {f'{fv} ±{fs}':>16} {f'{av} ±{as_}':>16}")
            else:
                print(f"  {t:<20} {str(fv):>16} {str(av):>16}")

    if full["rubric_scores"] or abl["rubric_scores"]:
        print("\n  Rubric scores (4 dimensions):")
        all_dims = sorted(set(list(full["rubric_scores"]) + list(abl["rubric_scores"])))
        print(f"  {'Dimension':<28} {'Full COMPASS':>16} {'Ablation 2':>16}")
        print("  " + "-" * 62)
        for d in all_dims:
            fv = full["rubric_scores"].get(d, "—")
            av = abl["rubric_scores"].get(d, "—")
            if multi:
                fs = full["rubric_scores_stdev"].get(d, 0)
                as_ = abl["rubric_scores_stdev"].get(d, 0)
                print(f"  {d:<28} {f'{fv} ±{fs}':>16} {f'{av} ±{as_}':>16}")
            else:
                print(f"  {d:<28} {str(fv):>16} {str(av):>16}")
    print()


# ---------------------------------------------------------------------------
# Save CSV  (mean ± stdev columns when N > 1)
# ---------------------------------------------------------------------------
def save_csv(full: Dict, abl: Dict, out_path: Path):
    multi = full.get("n_runs", 1) > 1
    fieldnames = ["metric", "full_compass", "ablation_2", "delta"]
    if multi:
        fieldnames = ["metric",
                      "full_compass_mean", "full_compass_stdev",
                      "ablation_2_mean",   "ablation_2_stdev",
                      "delta_mean"]

    rows = []

    def _row(label, key, skey=None):
        fv = full.get(key, 0)
        av = abl.get(key, 0)
        try:
            delta = round(float(av) - float(fv), 4)
        except (TypeError, ValueError):
            delta = ""
        if multi:
            return {"metric": label,
                    "full_compass_mean": fv,
                    "full_compass_stdev": full.get(skey, 0) if skey else 0,
                    "ablation_2_mean": av,
                    "ablation_2_stdev": abl.get(skey, 0) if skey else 0,
                    "delta_mean": delta}
        return {"metric": label, "full_compass": fv, "ablation_2": av, "delta": delta}

    rows.append(_row("Total Evidence Items",          "total_evidence_items",  "total_evidence_items_stdev"))
    rows.append(_row("Requirements Matched",           "requirements_matched",  "requirements_matched_stdev"))
    rows.append(_row("Mean Student Level (gap items)", "mean_student_level",    "mean_student_level_stdev"))

    for t in sorted(set(list(full["item_type_distribution"]) + list(abl["item_type_distribution"]))):
        fv = full["item_type_distribution"].get(t, 0)
        av = abl["item_type_distribution"].get(t, 0)
        if multi:
            rows.append({"metric": f"item_type:{t}",
                         "full_compass_mean": fv,
                         "full_compass_stdev": full["item_type_distribution_stdev"].get(t, 0),
                         "ablation_2_mean": av,
                         "ablation_2_stdev": abl["item_type_distribution_stdev"].get(t, 0),
                         "delta_mean": round(av - fv, 4)})
        else:
            rows.append({"metric": f"item_type:{t}", "full_compass": fv, "ablation_2": av, "delta": av - fv})

    for t in sorted(set(list(full["gap_type_distribution"]) + list(abl["gap_type_distribution"]))):
        fv = full["gap_type_distribution"].get(t, 0)
        av = abl["gap_type_distribution"].get(t, 0)
        if multi:
            rows.append({"metric": f"gap_type:{t}",
                         "full_compass_mean": fv,
                         "full_compass_stdev": full["gap_type_distribution_stdev"].get(t, 0),
                         "ablation_2_mean": av,
                         "ablation_2_stdev": abl["gap_type_distribution_stdev"].get(t, 0),
                         "delta_mean": round(av - fv, 4)})
        else:
            rows.append({"metric": f"gap_type:{t}", "full_compass": fv, "ablation_2": av, "delta": av - fv})

    for d in sorted(set(list(full["rubric_scores"]) + list(abl["rubric_scores"]))):
        fv = full["rubric_scores"].get(d, "")
        av = abl["rubric_scores"].get(d, "")
        try:
            delta = round(float(av) - float(fv), 4)
        except (TypeError, ValueError):
            delta = ""
        if multi:
            rows.append({"metric": f"rubric:{d}",
                         "full_compass_mean": fv,
                         "full_compass_stdev": full["rubric_scores_stdev"].get(d, 0),
                         "ablation_2_mean": av,
                         "ablation_2_stdev": abl["rubric_scores_stdev"].get(d, 0),
                         "delta_mean": delta})
        else:
            rows.append({"metric": f"rubric:{d}", "full_compass": fv, "ablation_2": av, "delta": delta})

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  CSV saved     -> {out_path}")


# ---------------------------------------------------------------------------
# Save raw JSON
# ---------------------------------------------------------------------------
def save_json(full: Dict, abl: Dict, out_path: Path, role: str = ""):
    data = {
        "run_timestamp": datetime.utcnow().isoformat(),
        "role": role,
        "n_runs": full.get("n_runs", 1),
        "full_compass": {k: v for k, v in full.items()},
        "ablation_2":   {k: v for k, v in abl.items()},
    }
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"  JSON saved    -> {out_path}")


# ---------------------------------------------------------------------------
# Save publication-ready figures (error bars when N > 1)
# ---------------------------------------------------------------------------
def save_figures(full: Dict, abl: Dict, out_path: Path, role: str = ""):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec
        import numpy as np
        from matplotlib.patches import Patch
    except ImportError:
        print("  [WARN] matplotlib not installed -- skipping figures.")
        print("         pip install matplotlib --break-system-packages")
        return

    FULL = "#4FC3F7"
    ABL  = "#FF8A65"
    multi = full.get("n_runs", 1) > 1

    has_gaps   = bool(full["gap_type_distribution"] or abl["gap_type_distribution"])
    has_rubric = bool(full["rubric_scores"]         or abl["rubric_scores"])
    n_rows = 3

    fig = plt.figure(figsize=(17, 5 * n_rows))
    gs = gridspec.GridSpec(n_rows, 3, figure=fig, hspace=0.52, wspace=0.36)

    def style(ax, title):
        ax.set_title(title, fontsize=10, fontweight="bold", pad=9)
        ax.tick_params(labelsize=8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.yaxis.grid(True, linewidth=0.4, alpha=0.4)
        ax.set_axisbelow(True)

    xlabels = ["Full COMPASS", "Ablation 2"]
    w = 0.36

    def simple_bar(ax, vals, errs, title, ylabel="Count"):
        yerr = errs if multi else None
        bars = ax.bar(xlabels, vals, color=[FULL, ABL], width=0.48, edgecolor="none",
                      yerr=yerr, capsize=5, error_kw={"elinewidth": 1.2, "ecolor": "black"})
        top = max(vals) if vals else 1
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + top * 0.03,
                    str(round(v, 4)), ha="center", va="bottom",
                    fontsize=9, fontweight="bold")
        ax.set_ylabel(ylabel, fontsize=8)
        style(ax, title)

    def grouped_bar(ax, keys, fd, ad, fd_s, ad_s, title, ylabel="Count", rotate=18):
        x = np.arange(len(keys))
        fvals = [fd.get(k, 0) for k in keys]
        avals = [ad.get(k, 0) for k in keys]
        f_err = [fd_s.get(k, 0) for k in keys] if multi else None
        a_err = [ad_s.get(k, 0) for k in keys] if multi else None
        ax.bar(x - w/2, fvals, w, label="Full COMPASS", color=FULL, edgecolor="none",
               yerr=f_err, capsize=4, error_kw={"elinewidth": 1.0, "ecolor": "black"})
        ax.bar(x + w/2, avals, w, label="Ablation 2",   color=ABL,  edgecolor="none",
               yerr=a_err, capsize=4, error_kw={"elinewidth": 1.0, "ecolor": "black"})
        ax.set_xticks(x)
        ax.set_xticklabels(keys, rotation=rotate, ha="right", fontsize=7)
        ax.legend(fontsize=7)
        ax.set_ylabel(ylabel, fontsize=8)
        style(ax, title)

    # ── Row 0: Layer 1 signals — parsing quality ──────────────────────
    simple_bar(fig.add_subplot(gs[0, 0]),
               [full["total_evidence_items"], abl["total_evidence_items"]],
               [full.get("total_evidence_items_stdev", 0), abl.get("total_evidence_items_stdev", 0)],
               "Total Evidence Items")

    all_types = sorted(set(list(full["item_type_distribution"]) + list(abl["item_type_distribution"])))
    grouped_bar(fig.add_subplot(gs[0, 1]),
                all_types,
                full["item_type_distribution"], abl["item_type_distribution"],
                full.get("item_type_distribution_stdev", {}), abl.get("item_type_distribution_stdev", {}),
                "Item Type Distribution")

    simple_bar(fig.add_subplot(gs[0, 2]),
               [full["requirements_matched"], abl["requirements_matched"]],
               [full.get("requirements_matched_stdev", 0), abl.get("requirements_matched_stdev", 0)],
               "Requirements Matched")

    # ── Row 1: Layer 2 signals ─────────────────────────────────────────
    simple_bar(fig.add_subplot(gs[1, 0]),
               [full["mean_student_level"], abl["mean_student_level"]],
               [full.get("mean_student_level_stdev", 0), abl.get("mean_student_level_stdev", 0)],
               "Mean Student Level",
               ylabel="Student Level (0 - 3)")

    if has_gaps:
        all_gap = sorted(set(list(full["gap_type_distribution"]) + list(abl["gap_type_distribution"])))
        grouped_bar(fig.add_subplot(gs[1, 1]),
                    all_gap,
                    full["gap_type_distribution"], abl["gap_type_distribution"],
                    full.get("gap_type_distribution_stdev", {}), abl.get("gap_type_distribution_stdev", {}),
                    "Gap Type Distribution")

    # ── Row 2: End-to-end — plan quality ──────────────────────────────
    if has_rubric:
        all_dims = sorted(set(list(full["rubric_scores"]) + list(abl["rubric_scores"])))
        ax_rub = fig.add_subplot(gs[2, 0])
        x = np.arange(len(all_dims))
        fvals = [full["rubric_scores"].get(d, 0) for d in all_dims]
        avals = [abl["rubric_scores"].get(d, 0)  for d in all_dims]
        f_err = [full.get("rubric_scores_stdev", {}).get(d, 0) for d in all_dims] if multi else None
        a_err = [abl.get("rubric_scores_stdev",  {}).get(d, 0) for d in all_dims] if multi else None
        ax_rub.bar(x - w/2, fvals, w, label="Full COMPASS", color=FULL, edgecolor="none",
                   yerr=f_err, capsize=4, error_kw={"elinewidth": 1.0, "ecolor": "black"})
        ax_rub.bar(x + w/2, avals, w, label="Ablation 2",   color=ABL,  edgecolor="none",
                   yerr=a_err, capsize=4, error_kw={"elinewidth": 1.0, "ecolor": "black"})
        ax_rub.set_xticks(x)
        ax_rub.set_xticklabels(all_dims, rotation=18, ha="right", fontsize=7)
        ax_rub.set_ylim(0, 5.8)
        ax_rub.legend(fontsize=7)
        ax_rub.set_ylabel("Score (0 - 5)", fontsize=8)
        style(ax_rub, "Rubric Scores (4 Dimensions)")

    n_label = f"  (N={full.get('n_runs', 1)} runs per condition)" if multi else ""
    fig.suptitle(
        f"Ablation 2 -- Remove Evidence Grounding  |  {role}{n_label}",
        fontsize=13, fontweight="bold", y=0.998,
    )
    fig.legend(
        handles=[
            Patch(facecolor=FULL, label="COMPASS"),
            Patch(facecolor=ABL,  label="Ablation 2"),
        ],
        loc="lower center", ncol=2, fontsize=9,
        bbox_to_anchor=(0.5, 0.002),
    )

    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Figures saved -> {out_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Ablation 2 metrics runner")
    parser.add_argument("--resume", required=True,
                        help="Path to the resume file (PDF, DOCX, or TXT)")
    parser.add_argument("--role", default="Data Analyst",
                        help="Desired role (default: 'Data Analyst')")
    parser.add_argument("--runs", type=int, default=1,
                        help="Number of times to run each condition (default: 1). "
                             "Use 3-5 to average out LLM stochasticity.")
    parser.add_argument("--academic-level",
                        choices=["freshman","sophomore","junior","senior",
                                 "grad","bootcamp","self_taught","working_professional"],
                        default="sophomore")
    parser.add_argument("--hours-per-week", type=int, default=10)
    parser.add_argument("--target-goal",
                        choices=["first_internship","graduation","job_ready","career_change"],
                        default="first_internship")
    parser.add_argument("--learning-mode",
                        choices=["structured","project_based","self_paced","mixed"],
                        default="mixed")
    args = parser.parse_args()

    resume_path = Path(args.resume).resolve()
    if not resume_path.exists():
        print(f"ERROR: File not found: {resume_path}")
        sys.exit(1)

    constraints = StudentConstraints(
        academic_level=args.academic_level,
        hours_per_week=args.hours_per_week,
        target_goal=args.target_goal,
        preferred_learning_mode=args.learning_mode,
    )

    n = args.runs
    print("\n" + "=" * 60)
    print("  ABLATION 2 METRICS RUNNER")
    print(f"  Role           : {args.role}")
    print(f"  Runs/condition : {n}")
    print(f"  Academic level : {args.academic_level}")
    print(f"  Hours/week     : {args.hours_per_week}")
    print(f"  Target goal    : {args.target_goal}")
    print(f"  Learning mode  : {args.learning_mode}")
    print(f"  Resume         : {resume_path.name}")
    print("=" * 60)

    file_bytes = resume_path.read_bytes()
    print(f"\n  Resume loaded : {len(file_bytes):,} bytes")

    out_dir = PROJECT_ROOT / "server" / "scripts" / "ablation2_results"
    out_dir.mkdir(parents=True, exist_ok=True)

    total_runs = n * 2
    run_num = 0

    # ── Full COMPASS runs ─────────────────────────────────────────────
    full_runs: List[Dict] = []
    for i in range(n):
        run_num += 1
        print(f"\n[{run_num}/{total_runs}] Full COMPASS — run {i+1}/{n}")
        state = run_graph_condition(
            "Full COMPASS", "full", file_bytes, resume_path.name,
            role=args.role, constraints=constraints,
        )
        full_runs.append(collect_metrics("full_compass", state))

    # ── Ablation 2 runs ───────────────────────────────────────────────
    abl_runs: List[Dict] = []
    for i in range(n):
        run_num += 1
        print(f"\n[{run_num}/{total_runs}] Ablation 2 — run {i+1}/{n}")
        state = run_graph_condition(
            "Ablation 2", "ablation2", file_bytes, resume_path.name,
            role=args.role, constraints=constraints,
        )
        abl_runs.append(collect_metrics("ablation_2", state))

    # ── Aggregate ─────────────────────────────────────────────────────
    full_agg = aggregate_metrics("full_compass", full_runs)
    abl_agg  = aggregate_metrics("ablation_2",   abl_runs)

    # ── Results ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  RESULTS  (N={n} runs per condition)")
    print("=" * 60)
    print_comparison_table(full_agg, abl_agg)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    save_csv(full_agg,  abl_agg, out_dir / f"ablation2_metrics_{ts}.csv")
    save_json(full_agg, abl_agg, out_dir / f"ablation2_raw_{ts}.json", role=args.role)
    save_figures(full_agg, abl_agg, out_dir / f"ablation2_figures_{ts}.png", role=args.role)

    print(f"\n  All outputs -> {out_dir}")
    print("\nDone.\n")


if __name__ == "__main__":
    main()
