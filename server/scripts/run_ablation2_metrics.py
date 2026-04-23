"""
hi
run_ablation2_metrics.py
========================
Ablation 2 metrics collection script.

Uses the REAL pipeline — real Supabase storage, real DB, real LLM calls.
No mocking. No monkey-patching.

Runs the Skills Claimer resume through both conditions:
  - Full COMPASS  (ABLATION_2_NO_DOCLING=false)
  - Ablation 2    (ABLATION_2_NO_DOCLING=true)

Each condition gets its own fresh Supabase session so the
"one run per session" guard in runs.py is never hit.

Usage (from project root, on branch test/ablation2):
    python server/scripts/run_ablation2_metrics.py --resume path/to/resume.pdf

Outputs (saved to server/scripts/ablation2_results/):
    ablation2_metrics_<timestamp>.csv     — all metrics in table form
    ablation2_raw_<timestamp>.json        — full evidence items from both runs
    ablation2_figures_<timestamp>.png     — publication-ready graphs

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
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path bootstrap — works whether you run from project root or server/scripts/
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "server"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from app.state import (
    AgentState,
    EvidenceDocument,
    StudentConstraints,
)
from app.tools.supabase_repo import SupabaseRepo
from app.run_events import cleanup


# ---------------------------------------------------------------------------
# Student constraints for the Skills Claimer scenario
# ---------------------------------------------------------------------------
SKILLS_CLAIMER_CONSTRAINTS = StudentConstraints(
    academic_level="sophomore",
    hours_per_week=10,
    target_goal="first_internship",
    preferred_learning_mode="mixed",
)


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
    from app.tools.docling_parser import infer_suffix

    session_id = repo.create_session()
    print(f"    Session created : {session_id}")

    content_hash = hashlib.sha256(file_bytes).hexdigest()
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
    ablation: bool,
    file_bytes: bytes,
    filename: str,
) -> AgentState:
    """
    Runs the complete COMPASS graph for one ablation condition.
    Creates a fresh Supabase session so the one-run-per-session guard
    in runs.py is never triggered between the two conditions.
    Returns the final AgentState.
    """
    print(f"\n{'='*60}")
    print(f"  Condition : {label}")
    print(f"  Docling   : {'OFF  (Ablation 2)' if ablation else 'ON   (Full COMPASS)'}")
    print(f"{'='*60}")

    # Set env flag BEFORE importing/reloading the node
    os.environ["ABLATION_2_NO_DOCLING"] = "true" if ablation else "false"

    # Reload evidence_ingestion so it picks up the updated env flag
    import importlib
    import app.nodes.evidence_ingestion as ei_mod
    importlib.reload(ei_mod)

    # Build a fresh graph (uses the reloaded node)
    from app.graph import build_graph
    repo = SupabaseRepo()
    graph = build_graph(repo)

    # Upload the resume as a fresh session
    session_id, document_id = upload_resume(
        repo=repo,
        file_bytes=file_bytes,
        filename=filename,
    )

    # Create the run record
    run_id = repo.create_run(
        session_id=session_id,
        desired_role="Data Analyst",
        status="running",
    )
    print(f"    Run id          : {run_id}")

    # Fetch the document row back so we have the full EvidenceDocument
    doc_data = repo.get_evidence_document(
        session_id=session_id,
        document_id=document_id,
    )
    if not doc_data:
        raise RuntimeError(f"Could not fetch evidence document {document_id}")

    # Build initial AgentState
    initial_state = AgentState(
        session_id=session_id,
        run_id=run_id,
        desired_role="Data Analyst",
        evidence_documents=[EvidenceDocument(**doc_data)],
        student_constraints=SKILLS_CLAIMER_CONSTRAINTS,
        status="running",
    )

    config = {"configurable": {"thread_id": run_id}, "recursion_limit": 15}

    print(f"\n  Invoking graph... (may take 2–4 minutes)")
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
# Collect all metrics from a completed AgentState
# ---------------------------------------------------------------------------
def collect_metrics(label: str, state: AgentState) -> Dict[str, Any]:
    items = state.evidence_items
    confidences = [item.confidence for item in items]
    confidence_reasons = [item.confidence_reason or "" for item in items]
    reason_populated = sum(1 for r in confidence_reasons if r.strip())

    evidence_map = state.student_model.evidence_map if state.student_model else {}
    gaps = state.gap_report.gaps if state.gap_report else []
    reasoning_populated = sum(
        1 for g in gaps if (g.student_level_reasoning or "").strip()
    )

    rubric_scores = state.critique.rubric_scores if state.critique else {}

    return {
        "label": label,
        # M1 — total evidence items
        "total_evidence_items": len(items),
        # M2 — item type distribution
        "item_type_distribution": dict(Counter(item.item_type for item in items)),
        # M3 — requirements matched
        "requirements_matched": len(evidence_map),
        # M4 — mean confidence
        "mean_confidence": round(statistics.mean(confidences), 4) if confidences else 0.0,
        # M5 — stdev confidence
        "stdev_confidence": round(statistics.stdev(confidences), 4) if len(confidences) > 1 else 0.0,
        # M6 — gap type distribution
        "gap_type_distribution": dict(Counter(g.gap_type for g in gaps)),
        "total_gaps": len(gaps),
        # M7 — student_level_reasoning population rate
        "student_level_reasoning_rate": round(
            reasoning_populated / len(gaps), 4
        ) if gaps else 0.0,
        # M8 — rubric scores
        "rubric_scores": rubric_scores,
        "rubric_mean": round(
            statistics.mean(rubric_scores.values()), 4
        ) if rubric_scores else 0.0,
        # Extra — confidence reason population rate (first-tier signal)
        "confidence_reason_populated_rate": round(
            reason_populated / len(items), 4
        ) if items else 0.0,
        # Raw items kept for histogram + qualitative analysis
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
# Print comparison table to terminal
# ---------------------------------------------------------------------------
def print_comparison_table(full: Dict, abl: Dict):
    print("\n" + "=" * 72)
    print(f"  {'METRIC':<40} {'FULL COMPASS':>14} {'ABLATION 2':>14}")
    print("=" * 72)

    rows = [
        ("Total evidence items",               "total_evidence_items"),
        ("Requirements matched",                "requirements_matched"),
        ("Total gaps",                          "total_gaps"),
        ("Mean confidence score",               "mean_confidence"),
        ("Stdev confidence score",              "stdev_confidence"),
        ("Confidence reason pop. rate",         "confidence_reason_populated_rate"),
        ("Student reasoning pop. rate",         "student_level_reasoning_rate"),
        ("Rubric mean score",                   "rubric_mean"),
    ]
    for display, key in rows:
        fv = full.get(key, "—")
        av = abl.get(key, "—")
        print(f"  {display:<40} {str(fv):>14} {str(av):>14}")

    print("=" * 72)

    # Item type breakdown
    print("\n  Item type distribution:")
    all_types = sorted(
        set(list(full["item_type_distribution"]) + list(abl["item_type_distribution"]))
    )
    print(f"  {'Type':<20} {'Full COMPASS':>14} {'Ablation 2':>14}")
    print("  " + "-" * 50)
    for t in all_types:
        print(f"  {t:<20} {full['item_type_distribution'].get(t,0):>14} "
              f"{abl['item_type_distribution'].get(t,0):>14}")

    # Gap type breakdown
    if full["gap_type_distribution"] or abl["gap_type_distribution"]:
        print("\n  Gap type distribution:")
        all_gap = sorted(
            set(list(full["gap_type_distribution"]) + list(abl["gap_type_distribution"]))
        )
        print(f"  {'Gap type':<20} {'Full COMPASS':>14} {'Ablation 2':>14}")
        print("  " + "-" * 50)
        for t in all_gap:
            print(f"  {t:<20} {full['gap_type_distribution'].get(t,0):>14} "
                  f"{abl['gap_type_distribution'].get(t,0):>14}")

    # Rubric scores
    if full["rubric_scores"] or abl["rubric_scores"]:
        print("\n  Rubric scores (all 4 dimensions):")
        all_dims = sorted(
            set(list(full["rubric_scores"]) + list(abl["rubric_scores"]))
        )
        print(f"  {'Dimension':<30} {'Full COMPASS':>14} {'Ablation 2':>14}")
        print("  " + "-" * 60)
        for d in all_dims:
            print(f"  {d:<30} {str(full['rubric_scores'].get(d,'—')):>14} "
                  f"{str(abl['rubric_scores'].get(d,'—')):>14}")
    print()


# ---------------------------------------------------------------------------
# Save CSV
# ---------------------------------------------------------------------------
def save_csv(full: Dict, abl: Dict, out_path: Path):
    rows = []

    scalar_keys = [
        ("total_evidence_items",              "Total Evidence Items"),
        ("requirements_matched",               "Requirements Matched"),
        ("total_gaps",                         "Total Gaps"),
        ("mean_confidence",                    "Mean Confidence Score"),
        ("stdev_confidence",                   "Stdev Confidence Score"),
        ("confidence_reason_populated_rate",   "Confidence Reason Population Rate"),
        ("student_level_reasoning_rate",       "Student Reasoning Population Rate"),
        ("rubric_mean",                        "Rubric Mean Score"),
    ]
    for key, label in scalar_keys:
        fv, av = full.get(key, 0), abl.get(key, 0)
        try:
            delta = round(float(av) - float(fv), 4)
        except (TypeError, ValueError):
            delta = ""
        rows.append({"metric": label, "full_compass": fv, "ablation_2": av, "delta": delta})

    for t in sorted(set(list(full["item_type_distribution"]) + list(abl["item_type_distribution"]))):
        fv = full["item_type_distribution"].get(t, 0)
        av = abl["item_type_distribution"].get(t, 0)
        rows.append({"metric": f"item_type:{t}", "full_compass": fv, "ablation_2": av, "delta": av - fv})

    for t in sorted(set(list(full["gap_type_distribution"]) + list(abl["gap_type_distribution"]))):
        fv = full["gap_type_distribution"].get(t, 0)
        av = abl["gap_type_distribution"].get(t, 0)
        rows.append({"metric": f"gap_type:{t}", "full_compass": fv, "ablation_2": av, "delta": av - fv})

    for d in sorted(set(list(full["rubric_scores"]) + list(abl["rubric_scores"]))):
        fv = full["rubric_scores"].get(d, "")
        av = abl["rubric_scores"].get(d, "")
        try:
            delta = round(float(av) - float(fv), 4)
        except (TypeError, ValueError):
            delta = ""
        rows.append({"metric": f"rubric:{d}", "full_compass": fv, "ablation_2": av, "delta": delta})

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "full_compass", "ablation_2", "delta"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"  CSV saved     → {out_path}")


# ---------------------------------------------------------------------------
# Save raw JSON
# ---------------------------------------------------------------------------
def save_json(full: Dict, abl: Dict, out_path: Path):
    data = {
        "run_timestamp": datetime.utcnow().isoformat(),
        "scenario": "skills_claimer",
        "role": "Data Analyst",
        "full_compass": {k: v for k, v in full.items()},
        "ablation_2":   {k: v for k, v in abl.items()},
    }
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"  JSON saved    → {out_path}")


# ---------------------------------------------------------------------------
# Save publication-ready figures
# ---------------------------------------------------------------------------
def save_figures(full: Dict, abl: Dict, out_path: Path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec
        import numpy as np
        from matplotlib.patches import Patch
    except ImportError:
        print("  [WARN] matplotlib not installed — skipping figures.")
        print("         pip install matplotlib --break-system-packages")
        return

    FULL  = "#4FC3F7"
    ABL   = "#FF8A65"
    BG    = "#0a0a0f"
    PANEL = "#0f3460"
    TEXT  = "#e0e0e0"
    GRID  = "#2a2a3e"

    has_gaps   = bool(full["gap_type_distribution"] or abl["gap_type_distribution"])
    has_rubric = bool(full["rubric_scores"]         or abl["rubric_scores"])
    n_rows = 3 if (has_gaps or has_rubric) else 2

    fig = plt.figure(figsize=(17, 5 * n_rows))
    fig.patch.set_facecolor(BG)
    gs = gridspec.GridSpec(n_rows, 3, figure=fig, hspace=0.52, wspace=0.36)

    def style(ax, title):
        ax.set_facecolor(PANEL)
        ax.set_title(title, color=TEXT, fontsize=10, fontweight="bold", pad=9)
        ax.tick_params(colors=TEXT, labelsize=8)
        for spine in ["bottom", "left"]:
            ax.spines[spine].set_color(GRID)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.yaxis.grid(True, color=GRID, linewidth=0.4, alpha=0.6)
        ax.set_axisbelow(True)

    xlabels = ["Full COMPASS", "Ablation 2"]
    w = 0.36

    def simple_bar(ax, vals, title, ylabel="Count"):
        bars = ax.bar(xlabels, vals, color=[FULL, ABL], width=0.48, edgecolor="none")
        top = max(vals) if vals else 1
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + top * 0.03,
                    str(round(v, 4)), ha="center", va="bottom",
                    color=TEXT, fontsize=9, fontweight="bold")
        ax.set_ylabel(ylabel, color=TEXT, fontsize=8)
        style(ax, title)

    def grouped_bar(ax, keys, fd, ad, title, ylabel="Count", rotate=18):
        x = np.arange(len(keys))
        ax.bar(x - w/2, [fd.get(k, 0) for k in keys], w,
               label="Full COMPASS", color=FULL, edgecolor="none")
        ax.bar(x + w/2, [ad.get(k, 0) for k in keys], w,
               label="Ablation 2",   color=ABL,  edgecolor="none")
        ax.set_xticks(x)
        ax.set_xticklabels(keys, rotation=rotate, ha="right", color=TEXT, fontsize=7)
        ax.legend(fontsize=7, facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT)
        ax.set_ylabel(ylabel, color=TEXT, fontsize=8)
        style(ax, title)

    # ── Row 0 ──────────────────────────────────────────────────────────
    simple_bar(fig.add_subplot(gs[0, 0]),
               [full["total_evidence_items"], abl["total_evidence_items"]],
               "Total Evidence Items")

    all_types = sorted(set(list(full["item_type_distribution"]) + list(abl["item_type_distribution"])))
    grouped_bar(fig.add_subplot(gs[0, 1]),
                all_types, full["item_type_distribution"], abl["item_type_distribution"],
                "Item Type Distribution")

    simple_bar(fig.add_subplot(gs[0, 2]),
               [full["requirements_matched"], abl["requirements_matched"]],
               "Requirements Matched")

    # ── Row 1 ──────────────────────────────────────────────────────────
    ax_conf = fig.add_subplot(gs[1, 0])
    means  = [full["mean_confidence"],  abl["mean_confidence"]]
    stdevs = [full["stdev_confidence"], abl["stdev_confidence"]]
    bars = ax_conf.bar(xlabels, means, color=[FULL, ABL], width=0.48,
                       yerr=stdevs, capsize=6,
                       error_kw={"ecolor": TEXT, "linewidth": 1.4},
                       edgecolor="none")
    for bar, v in zip(bars, means):
        ax_conf.text(bar.get_x() + bar.get_width()/2,
                     bar.get_height() + max(stdevs) + 0.02,
                     f"{v:.3f}", ha="center", va="bottom",
                     color=TEXT, fontsize=9, fontweight="bold")
    ax_conf.set_ylim(0, 1.1)
    ax_conf.set_ylabel("Score  (0 – 1)", color=TEXT, fontsize=8)
    style(ax_conf, "Mean Confidence ± Stdev")

    ax_hist = fig.add_subplot(gs[1, 1])
    bins = [i / 10 for i in range(11)]
    fc = [i["confidence"] for i in full["raw_items"]]
    ac = [i["confidence"] for i in abl["raw_items"]]
    ax_hist.hist(fc, bins=bins, alpha=0.65, color=FULL, label="Full COMPASS", edgecolor="none")
    ax_hist.hist(ac, bins=bins, alpha=0.65, color=ABL,  label="Ablation 2",   edgecolor="none")
    ax_hist.set_xlabel("Confidence", color=TEXT, fontsize=8)
    ax_hist.set_ylabel("Item count",  color=TEXT, fontsize=8)
    ax_hist.legend(fontsize=7, facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT)
    style(ax_hist, "Confidence Score Distribution")

    simple_bar(fig.add_subplot(gs[1, 2]),
               [full["confidence_reason_populated_rate"], abl["confidence_reason_populated_rate"]],
               "Confidence Reason Pop. Rate", ylabel="Rate (0 – 1)")

    # ── Row 2 (conditional) ────────────────────────────────────────────
    if n_rows == 3:
        if has_gaps:
            all_gap = sorted(set(list(full["gap_type_distribution"]) + list(abl["gap_type_distribution"])))
            grouped_bar(fig.add_subplot(gs[2, 0]),
                        all_gap, full["gap_type_distribution"], abl["gap_type_distribution"],
                        "Gap Type Distribution")

        simple_bar(fig.add_subplot(gs[2, 1]),
                   [full["student_level_reasoning_rate"], abl["student_level_reasoning_rate"]],
                   "Student Reasoning Pop. Rate", ylabel="Rate (0 – 1)")

        if has_rubric:
            all_dims = sorted(set(list(full["rubric_scores"]) + list(abl["rubric_scores"])))
            ax_rub = fig.add_subplot(gs[2, 2])
            x = np.arange(len(all_dims))
            ax_rub.bar(x - w/2, [full["rubric_scores"].get(d, 0) for d in all_dims],
                       w, label="Full COMPASS", color=FULL, edgecolor="none")
            ax_rub.bar(x + w/2, [abl["rubric_scores"].get(d,  0) for d in all_dims],
                       w, label="Ablation 2",   color=ABL,  edgecolor="none")
            ax_rub.set_xticks(x)
            ax_rub.set_xticklabels(all_dims, rotation=18, ha="right", color=TEXT, fontsize=7)
            ax_rub.set_ylim(0, 5.8)
            ax_rub.legend(fontsize=7, facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT)
            ax_rub.set_ylabel("Score (0 – 5)", color=TEXT, fontsize=8)
            style(ax_rub, "Rubric Scores (4 Dimensions)")

    fig.suptitle(
        "Ablation 2 — Remove Evidence Grounding  |  Skills Claimer Scenario (Data Analyst)",
        color=TEXT, fontsize=13, fontweight="bold", y=0.998,
    )
    fig.legend(
        handles=[
            Patch(facecolor=FULL, label="Full COMPASS  (Docling ON)"),
            Patch(facecolor=ABL,  label="Ablation 2     (Docling OFF)"),
        ],
        loc="lower center", ncol=2, fontsize=9,
        facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT,
        bbox_to_anchor=(0.5, 0.002),
    )

    plt.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    print(f"  Figures saved → {out_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Ablation 2 metrics runner")
    parser.add_argument(
        "--resume", required=True,
        help="Path to the Skills Claimer resume PDF",
    )
    args = parser.parse_args()

    resume_path = Path(args.resume).resolve()
    if not resume_path.exists():
        print(f"ERROR: File not found: {resume_path}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  ABLATION 2 METRICS RUNNER")
    print("  Scenario : Skills Claimer")
    print("  Role     : Data Analyst")
    print(f"  Resume   : {resume_path.name}")
    print("=" * 60)

    file_bytes = resume_path.read_bytes()
    print(f"\n  Resume loaded : {len(file_bytes):,} bytes")

    out_dir = PROJECT_ROOT / "server" / "scripts" / "ablation2_results"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Run 1: Full COMPASS ───────────────────────────────────────────
    print("\n[1/2] Full COMPASS (Docling ON)")
    full_state   = run_graph_condition("Full COMPASS", False, file_bytes, resume_path.name)
    full_metrics = collect_metrics("full_compass", full_state)

    # ── Run 2: Ablation 2 ─────────────────────────────────────────────
    print("\n[2/2] Ablation 2 (Docling OFF)")
    abl_state   = run_graph_condition("Ablation 2", True, file_bytes, resume_path.name)
    abl_metrics = collect_metrics("ablation_2", abl_state)

    # ── Results ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)
    print_comparison_table(full_metrics, abl_metrics)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    save_csv(full_metrics,     abl_metrics, out_dir / f"ablation2_metrics_{ts}.csv")
    save_json(full_metrics,    abl_metrics, out_dir / f"ablation2_raw_{ts}.json")
    save_figures(full_metrics, abl_metrics, out_dir / f"ablation2_figures_{ts}.png")

    print(f"\n  All outputs → {out_dir}")
    print("\nDone.\n")


if __name__ == "__main__":
    main()
