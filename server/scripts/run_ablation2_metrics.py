"""
run_ablation2_metrics.py
========================
Ablation study: Full COMPASS vs. Self-report baseline.

Research question:
  To what extent does an evidence-stratified career gap analysis produce
  career recommendations that differ meaningfully from self-report only baselines?

Conditions:
  full      — Docling parse → typed evidence extraction → proficiency-weighted student_level
  ablation2 — Docling parse → single holistic LLM assessment → student_level per requirement

Three evaluation layers:
  Layer 1  Student model divergence  — mean student_level per condition, delta
  Layer 2  Gap identification        — Jaccard similarity, condition-exclusive gaps
  Layer 3  LLM-as-judge              — blind plan evaluation on 4 dimensions (k=5 calls/pair)

Usage (from project root):
    python server/scripts/run_ablation2_metrics.py --resume path/to/resume.pdf
    python server/scripts/run_ablation2_metrics.py --resume path/to/resume.pdf --runs 5

Outputs (server/scripts/ablation2_results/):
    ablation2_metrics_<ts>.csv
    ablation2_raw_<ts>.json
    ablation2_figures_<ts>.png

Requirements:
    pip install matplotlib
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
from typing import Any, Dict, List, Optional, Tuple

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
# Upload resume to Supabase
# ---------------------------------------------------------------------------

def upload_resume(
    repo: SupabaseRepo,
    file_bytes: bytes,
    filename: str,
    content_type: str = "application/pdf",
) -> Tuple[str, str]:
    import hashlib, uuid
    from app.tools.docling_parser import infer_suffix

    session_id   = repo.create_session()
    print(f"    Session created : {session_id}")

    run_salt     = uuid.uuid4().hex
    content_hash = hashlib.sha256(file_bytes + run_salt.encode()).hexdigest()
    suffix       = infer_suffix(filename, content_type)
    storage_ref  = f"{session_id}/{content_hash}{suffix}"

    repo.upload_evidence_file(storage_ref=storage_ref, file_bytes=file_bytes, content_type=content_type)
    print(f"    Storage ref     : {storage_ref}")

    document_id = repo.insert_evidence_document(
        session_id=session_id,
        source_type="resume",
        content_hash=content_hash,
        strorage_ref=storage_ref,
        consent_level="excerpt_ok",
    )
    print(f"    Document id     : {document_id}")
    return session_id, document_id


# ---------------------------------------------------------------------------
# Run one condition
# ---------------------------------------------------------------------------

def run_graph_condition(
    label: str,
    condition: ConditionType,
    file_bytes: bytes,
    filename: str,
    role: str,
    constraints: StudentConstraints,
    inject_role_spec=None,
) -> AgentState:
    from app.state import RoleSpecModel
    mode_desc = {
        "full":       "full (Docling + typed evidence)",
        "ablation2":  "ablation2 (Docling + holistic LLM assessment)",
        "ablation2":  "ablation2 (no Docling, file content block)",
    }.get(condition, condition)

    print(f"\n{'='*60}")
    print(f"  Condition : {label}")
    print(f"  Mode      : {mode_desc}")
    if inject_role_spec:
        print(f"  Role spec : pre-injected ({len(inject_role_spec.requirements)} reqs — skipping role_intake)")
    print(f"{'='*60}")

    from app.graph import build_graph
    repo  = SupabaseRepo()
    graph = build_graph(repo)

    session_id, document_id = upload_resume(repo, file_bytes, filename)

    run_id = repo.create_run(session_id=session_id, desired_role=role, status="running")
    print(f"    Run id          : {run_id}")

    doc_data = repo.get_evidence_document(session_id=session_id, document_id=document_id)
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
        role_spec=inject_role_spec,
    )

    config = {"configurable": {"thread_id": run_id}, "recursion_limit": 15}
    print(f"\n  Invoking graph... (may take 2–4 minutes)")
    final_output = graph.invoke(initial_state, config=config)
    repo.set_run_status(session_id=session_id, run_id=run_id, status="done")
    cleanup(run_id)

    final_state = AgentState.model_validate(final_output)
    print(f"\n  Completed.")
    print(f"    Evidence items  : {len(final_state.evidence_items)}")
    if final_state.selfreport_scores:
        print(f"    Ablation2 reqs  : {len(final_state.selfreport_scores)}")
    if final_state.gap_report:
        print(f"    Gaps found      : {len(final_state.gap_report.gaps)}")
    if final_state.critique:
        print(f"    Satisfactory    : {final_state.critique.satisfactory}")
        print(f"    Rubric scores   : {final_state.critique.rubric_scores}")
    return final_state


# ---------------------------------------------------------------------------
# Layer 1 + 2 metrics per state
# ---------------------------------------------------------------------------

def collect_metrics(label: str, state: AgentState) -> Dict[str, Any]:
    items     = state.evidence_items
    gaps      = state.gap_report.gaps if state.gap_report else []
    rubric    = state.critique.rubric_scores if state.critique else {}
    ev_map    = state.student_model.evidence_map if state.student_model else {}

    if state.condition == "ablation2" and state.selfreport_scores:
        student_levels = list(state.selfreport_scores.values())
    else:
        student_levels = [g.student_level for g in gaps]

    return {
        "label": label,
        "total_evidence_items":    len(items),
        "item_type_distribution":  dict(Counter(i.item_type for i in items)),
        "requirements_matched":    len(ev_map),
        "mean_student_level":      round(statistics.mean(student_levels), 4) if student_levels else 0.0,
        "gap_type_distribution":   dict(Counter(g.gap_type for g in gaps)),
        "rubric_scores":           rubric,
        "raw_items": [
            {"item_type": i.item_type, "summary": i.summary,
             "confidence": i.confidence, "confidence_reason": i.confidence_reason or ""}
            for i in items
        ],
    }


# ---------------------------------------------------------------------------
# Layer 2: Gap divergence per run-pair
# ---------------------------------------------------------------------------

def compute_divergence(full_state: AgentState, sr_state: AgentState) -> Dict[str, Any]:
    full_gaps = {g.summary for g in full_state.gap_report.gaps if g.gap_type != "met"} \
                if full_state.gap_report else set()
    sr_gaps   = {g.summary for g in sr_state.gap_report.gaps if g.gap_type != "met"} \
                if sr_state.gap_report else set()

    union        = full_gaps | sr_gaps
    intersection = full_gaps & sr_gaps
    jaccard      = round(len(intersection) / len(union), 4) if union else 1.0

    compass_only  = sorted(full_gaps - sr_gaps)
    sr_only       = sorted(sr_gaps - full_gaps)

    # Per-requirement student_level delta (COMPASS minus selfreport)
    full_levels = {g.summary: g.student_level for g in full_state.gap_report.gaps} \
                  if full_state.gap_report else {}
    sr_levels   = sr_state.selfreport_scores or {}
    common      = set(full_levels) & set(sr_levels)
    deltas      = [full_levels[r] - sr_levels[r] for r in common]
    mean_delta  = round(statistics.mean(deltas), 4) if deltas else 0.0

    return {
        "gap_jaccard":               jaccard,
        "compass_only_gap_count":    len(compass_only),
        "ablation2_only_gap_count": len(sr_only),
        "mean_student_level_delta":  mean_delta,
        "compass_only_gaps":         compass_only,
        "ablation2_only_gaps":      sr_only,
    }


# ---------------------------------------------------------------------------
# Aggregate N runs
# ---------------------------------------------------------------------------

def _mean(vals: list) -> float:
    return round(statistics.mean(vals), 4) if vals else 0.0

def _stdev(vals: list) -> float:
    return round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0

def _agg_scalar(runs: list, key: str) -> Tuple[float, float]:
    vals = [r[key] for r in runs if key in r]
    return _mean(vals), _stdev(vals)

def _agg_dist(runs: list, key: str) -> Tuple[Dict, Dict]:
    all_keys = sorted(set(k for r in runs for k in r.get(key, {})))
    means, stdevs = {}, {}
    for k in all_keys:
        vals = [r.get(key, {}).get(k, 0) for r in runs]
        means[k], stdevs[k] = _mean(vals), _stdev(vals)
    return means, stdevs


def aggregate_metrics(label: str, runs: List[Dict]) -> Dict[str, Any]:
    n = len(runs)
    total_m,  total_s  = _agg_scalar(runs, "total_evidence_items")
    req_m,    req_s    = _agg_scalar(runs, "requirements_matched")
    level_m,  level_s  = _agg_scalar(runs, "mean_student_level")
    type_m,   type_s   = _agg_dist(runs, "item_type_distribution")
    gap_m,    gap_s    = _agg_dist(runs, "gap_type_distribution")
    rub_m,    rub_s    = _agg_dist(runs, "rubric_scores")

    return {
        "label": label, "n_runs": n,
        "total_evidence_items":          total_m,
        "total_evidence_items_stdev":    total_s,
        "requirements_matched":          req_m,
        "requirements_matched_stdev":    req_s,
        "mean_student_level":            level_m,
        "mean_student_level_stdev":      level_s,
        "item_type_distribution":        type_m,
        "item_type_distribution_stdev":  type_s,
        "gap_type_distribution":         gap_m,
        "gap_type_distribution_stdev":   gap_s,
        "rubric_scores":                 rub_m,
        "rubric_scores_stdev":           rub_s,
        "per_run_raw_items": [r["raw_items"] for r in runs],
    }


def aggregate_divergence(div_runs: List[Dict]) -> Dict[str, Any]:
    jac_m,   jac_s   = _agg_scalar(div_runs, "gap_jaccard")
    co_m,    co_s    = _agg_scalar(div_runs, "compass_only_gap_count")
    sr_m,    sr_s    = _agg_scalar(div_runs, "ablation2_only_gap_count")
    delta_m, delta_s = _agg_scalar(div_runs, "mean_student_level_delta")
    return {
        "gap_jaccard":                   jac_m,
        "gap_jaccard_stdev":             jac_s,
        "compass_only_gap_count":        co_m,
        "compass_only_gap_count_stdev":  co_s,
        "ablation2_only_gap_count":     sr_m,
        "selfreport_only_gap_count_stdev": sr_s,
        "mean_student_level_delta":      delta_m,
        "mean_student_level_delta_stdev": delta_s,
    }


def aggregate_judge(
    full_judge_runs: List[Dict],
    sr_judge_runs:   List[Dict],
) -> Dict[str, Any]:
    """Aggregate K*N judge scores across all run-pairs."""
    dims = ["precision", "gap_specificity", "level_appropriateness", "actionability", "overall"]

    def _agg_judge(runs: List[Dict]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for dim in dims:
            vals = [r[dim] for r in runs if dim in r]
            out[dim]             = _mean(vals)
            out[f"{dim}_stdev"]  = _stdev(vals)
        return out

    return {
        "full_compass": _agg_judge(full_judge_runs),
        "ablation2":    _agg_judge(sr_judge_runs),
    }


# ---------------------------------------------------------------------------
# Print comparison table
# ---------------------------------------------------------------------------

def print_comparison_table(
    full: Dict, sr: Dict, div: Dict, judge: Dict
):
    n     = full.get("n_runs", 1)
    multi = n > 1

    def _f(key, skey, d):
        v = d.get(key, "—")
        return f"{v} ±{d.get(skey, 0)}" if multi else str(v)

    print("\n" + "=" * 72)
    print(f"  {'METRIC':<40} {'FULL COMPASS':>14} {'ABLATION 2':>14}")
    print("=" * 72)

    for display, key, skey in [
        ("Mean student level",          "mean_student_level",   "mean_student_level_stdev"),
        ("Rubric: gap_coverage",         "gap_coverage",         None),
        ("Rubric: feasibility",          "feasibility",          None),
        ("Rubric: level_appropriateness","level_appropriateness",None),
    ]:
        if key in ["gap_coverage","feasibility","level_appropriateness"]:
            fv = full["rubric_scores"].get(key, "—")
            sv = sr["rubric_scores"].get(key, "—")
            print(f"  {display:<40} {str(fv):>14} {str(sv):>14}")
        else:
            print(f"  {display:<40} {_f(key, skey, full):>14} {_f(key, skey, sr):>14}")

    print()
    print(f"  {'DIVERGENCE METRIC':<40} {'VALUE':>14}")
    print("-" * 56)
    print(f"  {'Gap set Jaccard similarity':<40} {div.get('gap_jaccard','—'):>14}")
    print(f"  {'COMPASS-only gaps':<40} {div.get('compass_only_gap_count','—'):>14}")
    print(f"  {'Ablation2-only gaps':<40} {div.get('ablation2_only_gap_count','—'):>14}")
    print(f"  {'Mean student_level delta (C - A2)':<40} {div.get('mean_student_level_delta','—'):>14}")

    if judge:
        fc = judge.get("full_compass", {})
        sj = judge.get("ablation2",    {})
        print()
        print(f"  {'JUDGE DIMENSION':<30} {'FULL':>10} {'ABLATION 2':>12}")
        print("-" * 54)
        for dim in ["precision", "gap_specificity", "level_appropriateness", "actionability", "overall"]:
            print(f"  {dim:<30} {fc.get(dim,'—'):>10} {sj.get(dim,'—'):>12}")
    print()


# ---------------------------------------------------------------------------
# Save CSV
# ---------------------------------------------------------------------------

def save_csv(full: Dict, sr: Dict, div: Dict, judge: Dict, out_path: Path):
    multi = full.get("n_runs", 1) > 1
    if multi:
        fnames = ["metric","full_compass_mean","full_compass_stdev",
                  "ablation2_mean","ablation2_stdev","delta_mean"]
    else:
        fnames = ["metric","full_compass","ablation2","delta"]

    rows: List[Dict] = []

    def _row(label, fv, sv, fs=0, ss=0):
        try:    delta = round(float(sv) - float(fv), 4)
        except: delta = ""
        if multi:
            return {"metric": label, "full_compass_mean": fv, "full_compass_stdev": fs,
                    "ablation2_mean": sv, "ablation2_stdev": ss, "delta_mean": delta}
        return {"metric": label, "full_compass": fv, "ablation2": sv, "delta": delta}

    rows.append(_row("Mean Student Level",
                     full["mean_student_level"], sr["mean_student_level"],
                     full.get("mean_student_level_stdev", 0), sr.get("mean_student_level_stdev", 0)))

    for t in sorted(set(list(full["gap_type_distribution"]) + list(sr["gap_type_distribution"]))):
        rows.append(_row(f"gap_type:{t}",
                         full["gap_type_distribution"].get(t, 0),
                         sr["gap_type_distribution"].get(t, 0),
                         full.get("gap_type_distribution_stdev", {}).get(t, 0),
                         sr.get("gap_type_distribution_stdev", {}).get(t, 0)))

    for d in sorted(set(list(full["rubric_scores"]) + list(sr["rubric_scores"]))):
        rows.append(_row(f"rubric:{d}",
                         full["rubric_scores"].get(d, ""),
                         sr["rubric_scores"].get(d, ""),
                         full.get("rubric_scores_stdev", {}).get(d, 0),
                         sr.get("rubric_scores_stdev", {}).get(d, 0)))

    # Divergence
    for key in ["gap_jaccard", "compass_only_gap_count", "ablation2_only_gap_count",
                "mean_student_level_delta"]:
        rows.append(_row(f"divergence:{key}", div.get(key, ""), "",
                         div.get(f"{key}_stdev", 0), 0))

    # Judge
    fc = judge.get("full_compass", {})
    sj = judge.get("ablation2",    {})
    for dim in ["precision", "gap_specificity", "level_appropriateness", "actionability", "overall"]:
        rows.append(_row(f"judge:{dim}",
                         fc.get(dim, ""), sj.get(dim, ""),
                         fc.get(f"{dim}_stdev", 0), sj.get(f"{dim}_stdev", 0)))

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  CSV saved     -> {out_path}")


# ---------------------------------------------------------------------------
# Save JSON
# ---------------------------------------------------------------------------

def save_json(
    full: Dict, sr: Dict, div: Dict, judge: Dict,
    out_path: Path, role: str = "",
    div_runs: Optional[List[Dict]] = None,
):
    data = {
        "run_timestamp":  datetime.utcnow().isoformat(),
        "role":           role,
        "n_runs":         full.get("n_runs", 1),
        "full_compass":   full,
        "ablation2":      sr,
        "divergence":     div,
        "divergence_runs": div_runs or [],
        "judge_scores":   judge,
    }
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"  JSON saved    -> {out_path}")


# ---------------------------------------------------------------------------
# Save figures  (2-row layout)
# ---------------------------------------------------------------------------

def save_figures(
    full: Dict, sr: Dict, div: Dict, judge: Dict,
    out_path: Path, role: str = "",
    div_runs: Optional[List[Dict]] = None,
):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec
        import numpy as np
        from matplotlib.patches import Patch
    except ImportError:
        print("  [WARN] matplotlib not installed — skipping figures.")
        return

    FULL   = "#4FC3F7"  # blue — full COMPASS
    SR     = "#FF8A65"  # orange — self-report
    GRAY   = "#90A4AE"
    multi  = full.get("n_runs", 1) > 1
    BAR_W  = 0.36

    plt.rcParams.update({
        "font.family":      "DejaVu Sans",
        "font.size":        10,
        "axes.titlesize":   11,
        "axes.labelsize":   10,
        "xtick.labelsize":  9,
        "ytick.labelsize":  9,
        "legend.fontsize":  9,
        "axes.titlepad":    6,
    })

    # ── Layout: 2 rows, 3 cols
    #    Row 0: [student level] [gap type distribution] [COMPASS evidence taxonomy]
    #    Row 1: [LLM-as-judge — full width]
    fig = plt.figure(figsize=(14, 7))
    gs  = gridspec.GridSpec(
        2, 3, figure=fig,
        top=0.88, bottom=0.10,
        left=0.07, right=0.97,
        hspace=0.52, wspace=0.38,
    )

    def _style(ax, title):
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.yaxis.grid(True, linewidth=0.5, alpha=0.35, color="#BBBBBB")
        ax.set_axisbelow(True)

    def _label_bars(ax, bars, vals, fmt=".2f", offset_frac=0.04):
        top = max((v for v in vals if v is not None), default=1) or 1
        for bar, v in zip(bars, vals):
            if v is None:
                continue
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + top * offset_frac,
                format(v, fmt),
                ha="center", va="bottom", fontsize=9, fontweight="bold",
            )

    # ── Panel 0,0: Mean Student Level ────────────────────────────────
    ax0 = fig.add_subplot(gs[0, 0])
    vals  = [full["mean_student_level"], sr["mean_student_level"]]
    yerr  = [full.get("mean_student_level_stdev", 0), sr.get("mean_student_level_stdev", 0)] if multi else None
    bars  = ax0.bar(
        ["COMPASS", "Ablation\n2"], vals,
        color=[FULL, SR], width=0.5, edgecolor="none",
        yerr=yerr, capsize=5, error_kw={"elinewidth": 1.2, "ecolor": "#555"},
    )
    _label_bars(ax0, bars, vals)
    ax0.set_ylabel("Student Level (0–3)")
    ax0.set_ylim(0, 3.0)
    ax0.set_yticks([0, 1, 2, 3])
    _style(ax0, "Mean Student Level\n(Layer 1 — Calibration)")

    # ── Panel 0,1: Gap Type Distribution ─────────────────────────────
    ax1 = fig.add_subplot(gs[0, 1])
    # Canonical order — tells the story from no evidence → fully met
    gap_order   = ["no_evidence", "claimed_only", "partial", "met"]
    gap_labels  = ["No evidence", "Claimed only", "Partial", "Met"]
    fd    = full.get("gap_type_distribution", {})
    sd    = sr.get("gap_type_distribution", {})
    fd_s  = full.get("gap_type_distribution_stdev", {})
    sd_s  = sr.get("gap_type_distribution_stdev", {})
    x     = np.arange(len(gap_order))
    fvals = [fd.get(k, 0) for k in gap_order]
    svals = [sd.get(k, 0) for k in gap_order]
    f_err = [fd_s.get(k, 0) for k in gap_order] if multi else None
    s_err = [sd_s.get(k, 0) for k in gap_order] if multi else None
    bars_f = ax1.bar(x - BAR_W/2, fvals, BAR_W, label="Full COMPASS", color=FULL,
                     edgecolor="none", yerr=f_err, capsize=3,
                     error_kw={"elinewidth": 1.0, "ecolor": "#555"})
    bars_s = ax1.bar(x + BAR_W/2, svals, BAR_W, label="Ablation2",  color=SR,
                     edgecolor="none", yerr=s_err, capsize=3,
                     error_kw={"elinewidth": 1.0, "ecolor": "#555"})
    ax1.set_xticks(x)
    ax1.set_xticklabels(gap_labels, rotation=20, ha="right")
    ax1.set_ylabel("Requirement count")
    ax1.legend(loc="upper right", fontsize=8)
    _style(ax1, "Gap Type Distribution\n(Layer 2 — Identification)")

    # ── Panel 0,2: Gap Set Divergence — dual line plot ────────────────
    ax2 = fig.add_subplot(gs[0, 2])
    jaccard = div.get("gap_jaccard", 0)

    if div_runs and len(div_runs) >= 1:
        run_x   = list(range(1, len(div_runs) + 1))
        co_vals = [r.get("compass_only_gap_count", 0) for r in div_runs]
        a2_vals = [r.get("ablation2_only_gap_count", 0) for r in div_runs]

        ax2.plot(run_x, co_vals, color=FULL, linewidth=1.8, marker="o",
                 markersize=5, label="Full COMPASS", zorder=2)
        ax2.plot(run_x, a2_vals, color=SR,   linewidth=1.8, marker="o",
                 markersize=5, label="Ablation2",    zorder=2)

        ax2.set_xticks(run_x if len(run_x) <= 15 else run_x[::3])
        ax2.set_xlabel("Run", fontsize=9)
        ax2.set_ylabel("Exclusive gap count")
        ax2.legend(fontsize=8, loc="upper right")
    else:
        # No per-run data — show mean values as labelled points
        co_mean = div.get("compass_only_gap_count", 0)
        a2_mean = div.get("ablation2_only_gap_count", 0)
        ax2.plot([1], [co_mean], color=FULL, marker="o", markersize=9, label="Full COMPASS", zorder=2)
        ax2.plot([1], [a2_mean], color=SR,   marker="o", markersize=9, label="Ablation2",    zorder=2)
        ax2.set_xticks([1])
        ax2.set_xticklabels(["Run 1"])
        ax2.set_ylabel("Exclusive gap count")
        ax2.legend(fontsize=8, loc="upper right")

    ax2.text(0.97, 0.96,
             f"Jaccard = {jaccard:.2f}",
             transform=ax2.transAxes, ha="right", va="top",
             fontsize=8.5, color="#333", fontweight="bold",
             bbox=dict(boxstyle="round,pad=0.35", facecolor="white", edgecolor="#CCC", alpha=0.9))
    _style(ax2, "Gap Set Divergence\n(Layer 2 — Identification)")

    # ── Row 1: LLM-as-Judge ──────────────────────────────────────────
    fc = judge.get("full_compass", {})
    sj = judge.get("ablation2",    {})
    ax_j = fig.add_subplot(gs[1, :])

    if fc and sj:
        dims       = ["precision", "gap_specificity", "level_appropriateness", "actionability", "overall"]
        dim_labels = ["Precision", "Gap Specificity", "Level\nAppropriateness", "Actionability", "Overall"]
        x      = np.arange(len(dims))
        fvals  = [fc.get(d, 0) for d in dims]
        svals  = [sj.get(d, 0) for d in dims]
        f_err  = [fc.get(f"{d}_stdev", 0) for d in dims] if multi else None
        s_err  = [sj.get(f"{d}_stdev", 0) for d in dims] if multi else None
        bars_jf = ax_j.bar(x - BAR_W/2, fvals, BAR_W, label="COMPASS", color=FULL,
                           edgecolor="none", yerr=f_err, capsize=5,
                           error_kw={"elinewidth": 1.2, "ecolor": "#555"})
        bars_js = ax_j.bar(x + BAR_W/2, svals, BAR_W, label="Ablation2",  color=SR,
                           edgecolor="none", yerr=s_err, capsize=5,
                           error_kw={"elinewidth": 1.2, "ecolor": "#555"})
        _label_bars(ax_j, bars_jf, fvals)
        _label_bars(ax_j, bars_js, svals)
        ax_j.set_xticks(x)
        ax_j.set_xticklabels(dim_labels, fontsize=10)
        ax_j.set_ylim(0, 5.8)
        ax_j.set_yticks([1, 2, 3, 4, 5])
        ax_j.set_ylabel("Score (1–5)")
        ax_j.axhline(y=3, color="#999", linewidth=0.8, linestyle="--", alpha=0.6)
        ax_j.legend(loc="upper right", fontsize=9)
        # Annotate the overall delta
        overall_delta = fc.get("overall", 0) - sj.get("overall", 0)
        ax_j.text(0.5, 0.93,
                  f"Overall Δ = +{overall_delta:.2f} in favour of Full COMPASS" if overall_delta > 0
                  else f"Overall Δ = {overall_delta:.2f}",
                  transform=ax_j.transAxes, ha="center", va="top",
                  fontsize=9, color="#333",
                  bbox=dict(boxstyle="round,pad=0.35", facecolor="#FFFDE7", edgecolor="#F9A825", alpha=0.9))
        _style(ax_j, "LLM-as-Judge Plan Quality  (Layer 3 — Downstream Impact)")
    else:
        ax_j.axis("off")
        ax_j.text(0.5, 0.5, "Judge scores not available\n(plans missing from one or both conditions)",
                  transform=ax_j.transAxes, ha="center", va="center",
                  fontsize=11, color="#888")
        _style(ax_j, "LLM-as-Judge Plan Quality  (Layer 3 — Downstream Impact)")

    # ── Suptitle ─────────────────────────────────────────────────────
    n_label = f"  ·  N = {full.get('n_runs', 1)} run{'s' if full.get('n_runs', 1) > 1 else ''} per condition" if True else ""
    judge_k = 5  # default; not stored in aggregated dict

    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"  Figures saved -> {out_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="COMPASS vs. Ablation2 (self-report baseline) runner")
    parser.add_argument("--resume",      default=None)
    parser.add_argument("--from-json",   default=None, help="Regenerate outputs from existing JSON")
    parser.add_argument("--role",        default="Data Analyst")
    parser.add_argument("--runs",        type=int, default=1)
    parser.add_argument("--judge-calls", type=int, default=5,
                        help="LLM judge calls per run-pair (default: 5)")
    parser.add_argument("--academic-level",
                        choices=["freshman","sophomore","junior","senior",
                                 "grad","bootcamp","self_taught","working_professional"],
                        default="sophomore")
    parser.add_argument("--hours-per-week",  type=int, default=10)
    parser.add_argument("--target-goal",
                        choices=["first_internship","graduation","job_ready","career_change"],
                        default="first_internship")
    parser.add_argument("--learning-mode",
                        choices=["structured","project_based","self_paced","mixed"],
                        default="mixed")
    args = parser.parse_args()

    # ── Fast path: regenerate from JSON ──────────────────────────────
    if args.from_json:
        json_path = Path(args.from_json).resolve()
        with open(json_path) as f:
            data = json.load(f)
        full_agg = data["full_compass"]
        sr_agg   = data["ablation2"]
        div_agg  = data.get("divergence", {})
        div_runs = data.get("divergence_runs") or None
        judge    = data.get("judge_scores", {})
        role     = data.get("role", "")
        out_dir  = json_path.parent
        ts       = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        save_csv(full_agg, sr_agg, div_agg, judge, out_dir / f"ablation2_metrics_{ts}.csv")
        save_figures(full_agg, sr_agg, div_agg, judge, out_dir / f"ablation2_figures_{ts}.png", role=role, div_runs=div_runs)
        print("Done.\n")
        return

    if not args.resume:
        parser.error("--resume is required unless --from-json is provided.")

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
    print("  COMPASS vs. ABLATION2 (SELF-REPORT BASELINE) RUNNER")
    print(f"  Role           : {args.role}")
    print(f"  Runs/condition : {n}")
    print(f"  Judge calls/pr : {args.judge_calls}")
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

    # Parse resume once with Docling for the judge
    from app.tools.docling_parser import parse_document_to_markdown, infer_suffix
    print("\n  Parsing resume with Docling (for judge context)...")
    try:
        resume_markdown = parse_document_to_markdown(file_bytes, infer_suffix(resume_path.name))
        print(f"  Docling parsed {len(resume_markdown)} chars.")
    except Exception as e:
        print(f"  [WARN] Docling parse failed for judge context: {e}. Judge will use empty string.")
        resume_markdown = ""

    total_runs = n * 2
    run_num    = 0

    full_runs: List[Dict] = []
    sr_runs:   List[Dict] = []
    div_runs:  List[Dict] = []
    # Store (full_state, sr_state) pairs for the judge
    state_pairs: List[Tuple[AgentState, AgentState]] = []

    # ── Paired runs ───────────────────────────────────────────────────
    for i in range(n):
        run_num += 1
        print(f"\n[{run_num}/{total_runs}] Full COMPASS — run {i+1}/{n}")
        full_state = run_graph_condition(
            "Full COMPASS", "full", file_bytes, resume_path.name,
            role=args.role, constraints=constraints,
        )

        run_num += 1
        print(f"\n[{run_num}/{total_runs}] Ablation2 — run {i+1}/{n}")
        sr_state = run_graph_condition(
            "Ablation2", "ablation2", file_bytes, resume_path.name,
            role=args.role, constraints=constraints,
            inject_role_spec=full_state.role_spec,
        )

        full_runs.append(collect_metrics("full_compass", full_state))
        sr_runs.append(collect_metrics("ablation2",      sr_state))
        div_runs.append(compute_divergence(full_state, sr_state))
        state_pairs.append((full_state, sr_state))

    # ── Layer 3: LLM judge ────────────────────────────────────────────
    print(f"\n  Running LLM judge ({args.judge_calls} calls per pair)...")
    full_judge_runs: List[Dict] = []
    sr_judge_runs:   List[Dict] = []

    from app.tools.judge_llm import evaluate_plans_blind

    for pair_i, (fs, ss) in enumerate(state_pairs):
        if not fs.plan or not ss.plan:
            print(f"  [WARN] Pair {pair_i+1}: missing plan — skipping judge.")
            continue
        role_spec = fs.role_spec or ss.role_spec
        if not role_spec:
            print(f"  [WARN] Pair {pair_i+1}: missing role_spec — skipping judge.")
            continue
        print(f"  Judge pair {pair_i+1}/{n}...")
        fj, sj = evaluate_plans_blind(
            resume_markdown=resume_markdown,
            role_spec=role_spec,
            plan_full=fs.plan,
            plan_selfreport=ss.plan,
            k=args.judge_calls,
        )
        full_judge_runs.append(fj)
        sr_judge_runs.append(sj)

    # ── Aggregate ─────────────────────────────────────────────────────
    full_agg  = aggregate_metrics("full_compass", full_runs)
    sr_agg    = aggregate_metrics("ablation2",    sr_runs)
    div_agg   = aggregate_divergence(div_runs)
    judge_agg = aggregate_judge(full_judge_runs, sr_judge_runs)

    # ── Print & save ──────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  RESULTS  (N={n} runs per condition)")
    print("=" * 60)
    print_comparison_table(full_agg, sr_agg, div_agg, judge_agg)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    save_csv(full_agg, sr_agg, div_agg, judge_agg, out_dir / f"ablation2_metrics_{ts}.csv")
    save_json(full_agg, sr_agg, div_agg, judge_agg, out_dir / f"ablation2_raw_{ts}.json", role=args.role, div_runs=div_runs)
    save_figures(full_agg, sr_agg, div_agg, judge_agg, out_dir / f"ablation2_figures_{ts}.png", role=args.role, div_runs=div_runs)

    print(f"\n  All outputs -> {out_dir}")
    print("\nDone.\n")


if __name__ == "__main__":
    main()
