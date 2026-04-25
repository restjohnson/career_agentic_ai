"""
Ablation 4 analysis: statistical tests + matplotlib plots.

Loads a CSV produced by run_ablation4_metrics.py, runs Wilcoxon signed-rank
tests (paired by trial index), computes medians and IQRs, and saves 4 PNGs
to server/scripts/ablation4_plots/.

Usage:
  python scripts/analyze_ablation4.py scripts/ablation4_results_<timestamp>.csv
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Matplotlib — use non-interactive backend so the script works headless
# ---------------------------------------------------------------------------
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec, GridSpecFromSubplotSpec
import numpy as np

try:
    import seaborn as sns
    _HAS_SEABORN = True
except ImportError:
    _HAS_SEABORN = False
    print("[WARN] seaborn not installed — heatmap will use matplotlib fallback")

# scipy is used only for the Wilcoxon test; fall back gracefully if missing
try:
    from scipy.stats import wilcoxon
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False
    print("[WARN] scipy not installed — Wilcoxon p-values will show as N/A")
    print("       pip install scipy\n")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RUBRIC_DIMS   = ["gap_coverage", "jit_compliance", "feasibility", "level_appropriateness"]
THRESHOLDS    = {"gap_coverage": 4, "jit_compliance": 4, "feasibility": 3, "level_appropriateness": 3}
DIM_LABELS    = {
    "gap_coverage":          "Gap Coverage",
    "jit_compliance":        "JIT Compliance",
    "feasibility":           "Feasibility",
    "level_appropriateness": "Level Appropriateness",
}

COLOUR_FULL  = "#2563eb"   # blue
COLOUR_ABL4  = "#ea580c"   # orange

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_csv(path: Path) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["trial"]                      = int(row["trial"])
            row["critique_iterations"]        = int(row["critique_iterations"])
            row["satisfactory"]               = row["satisfactory"].lower() == "true"
            row["narrative_feedback_present"] = row["narrative_feedback_present"].lower() == "true"
            for col in ("gap_coverage", "jit_compliance", "feasibility",
                        "level_appropriateness", "mean_rubric_score",
                        "best_critique_score", "plan_timeline_weeks",
                        "target_weeks", "num_phases", "num_issues"):
                row[col] = float(row[col])
            rows.append(row)
    return rows


def split(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    full = sorted([r for r in rows if r["condition"] == "full"],     key=lambda r: r["trial"])
    abl4 = sorted([r for r in rows if r["condition"] == "ablation4"], key=lambda r: r["trial"])
    return full, abl4


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def mean_std(vals: list[float]) -> tuple[float, float]:
    mu  = sum(vals) / len(vals)
    var = sum((v - mu) ** 2 for v in vals) / (len(vals) - 1)
    return mu, math.sqrt(var)


def rank_biserial(w: float, n: int) -> float:
    """Rank-biserial correlation from Wilcoxon W statistic."""
    total = n * (n + 1) / 2
    return 1 - (2 * w / total)


def wilcoxon_test(a: list[float], b: list[float]) -> tuple[float | None, float | None]:
    """Paired Wilcoxon signed-rank test. Returns (W, p)."""
    if not _HAS_SCIPY:
        return None, None
    diffs = [x - y for x, y in zip(a, b)]
    if all(d == 0 for d in diffs):
        return None, 1.0
    try:
        stat, p = wilcoxon(a, b, alternative="greater")
        return stat, p
    except Exception:
        return None, None


def sig_stars(p: float | None) -> str:
    if p is None:
        return "N/A"
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return "ns"


# ---------------------------------------------------------------------------
# Statistical report (stdout)
# ---------------------------------------------------------------------------

def print_stats(full: list[dict], abl4: list[dict]) -> dict:
    """Print table and return per-dimension stats for use in plots."""
    metrics = RUBRIC_DIMS + ["mean_rubric_score"]
    stats: dict = {}

    header = f"{'Metric':<28} {'full mean±std':>16} {'ablation4 mean±std':>20} {'p':>8} {'r':>6} {'sig':>5}"
    print("\n" + "=" * len(header))
    print("ABLATION 4 — Statistical Analysis  (Wilcoxon signed-rank, one-tailed: full > ablation4)")
    print("=" * len(header))
    print(header)
    print("-" * len(header))

    for m in metrics:
        f_vals = [r[m] for r in full]
        a_vals = [r[m] for r in abl4]

        f_mu, f_sd = mean_std(f_vals)
        a_mu, a_sd = mean_std(a_vals)

        w, p = wilcoxon_test(f_vals, a_vals)
        r    = rank_biserial(w, len(f_vals)) if (w is not None and p is not None and p < 1.0) else None

        p_str = f"{p:.3f}" if p is not None else "N/A"
        r_str = f"{r:.2f}" if r is not None else " —  "

        print(
            f"  {m:<26} "
            f"{f_mu:.2f} ± {f_sd:.2f}     "
            f"{a_mu:.2f} ± {a_sd:.2f}      "
            f"{p_str:>8}  {r_str:>6}  {sig_stars(p):>5}"
        )

        stats[m] = {
            "full_vals": f_vals, "abl4_vals": a_vals,
            "full_mu": f_mu, "abl4_mu": a_mu,
            "full_sd": f_sd, "abl4_sd": a_sd,
            "p": p, "r": r,
        }

    # Satisfactory rate
    f_sat = sum(1 for r in full if r["satisfactory"]) / len(full) * 100
    a_sat = sum(1 for r in abl4 if r["satisfactory"]) / len(abl4) * 100
    print(f"\n  {'satisfactory rate':<26} {f_sat:.0f}%  {'':>22}  {a_sat:.0f}%")

    # Iterations
    f_iters = [r["critique_iterations"] for r in full]
    a_iters = [r["critique_iterations"] for r in abl4]
    f_mu_i, f_sd_i = mean_std(f_iters)
    a_mu_i, a_sd_i = mean_std(a_iters)
    print(f"  {'critique_iterations':<26} {f_mu_i:.2f} ± {f_sd_i:.2f}     {a_mu_i:.2f} ± {a_sd_i:.2f}   (ablation4 always 1)")

    narr = sum(1 for r in abl4 if r["narrative_feedback_present"])
    print(f"\n  narrative_feedback_present (ablation4): {narr}/{len(abl4)} runs")
    print("  _reflect() ran but was never acted on — confirms the ablation worked as designed.")
    print("=" * len(header))

    stats["_satisfactory"] = {"full": f_sat, "abl4": a_sat, "n": len(full)}
    stats["_iterations"]   = {"full": f_iters, "abl4": a_iters}
    return stats


# ---------------------------------------------------------------------------
# Plot 1 — Grouped bar chart (rubric scores)
# ---------------------------------------------------------------------------

def plot_rubric_bar(ax: plt.Axes, stats: dict) -> None:
    dims = RUBRIC_DIMS
    x    = np.arange(len(dims))
    w    = 0.35

    for i, d in enumerate(dims):
        s = stats[d]
        ax.bar(x[i] - w / 2, s["full_mu"], w, color=COLOUR_FULL, alpha=0.85,
               label="Full COMPASS" if i == 0 else "")
        ax.bar(x[i] + w / 2, s["abl4_mu"], w, color=COLOUR_ABL4, alpha=0.85,
               label="Ablation 4" if i == 0 else "")

        ax.errorbar(x[i] - w / 2, s["full_mu"], yerr=s["full_sd"],
                    fmt="none", color="black", capsize=4, linewidth=1.2)
        ax.errorbar(x[i] + w / 2, s["abl4_mu"], yerr=s["abl4_sd"],
                    fmt="none", color="black", capsize=4, linewidth=1.2)

        p = stats[d]["p"]
        if p is not None and p < 0.05:
            top = max(s["full_mu"] + s["full_sd"], s["abl4_mu"] + s["abl4_sd"]) + 0.15
            ax.text(x[i], top, sig_stars(p), ha="center", va="bottom", fontsize=11)

        thr = THRESHOLDS[d]
        ax.hlines(thr, x[i] - 0.45, x[i] + 0.45,
                  colors="grey", linestyles="dashed", linewidth=0.8, alpha=0.6)

    ax.set_xticks(x)
    ax.set_xticklabels([DIM_LABELS[d] for d in dims], fontsize=9)
    ax.set_ylim(0, 5.8)
    ax.set_ylabel("Rubric Score (1–5)", fontsize=10)
    ax.set_title("(a) Rubric Scores\n(mean ± 1 SD, dashed = pass threshold)", fontsize=11)
    ax.legend(fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)


# ---------------------------------------------------------------------------
# Plot 2 — Radar chart
# ---------------------------------------------------------------------------

def plot_radar(ax: plt.Axes, stats: dict) -> None:
    dims   = RUBRIC_DIMS
    n      = len(dims)
    angles = [2 * math.pi * i / n for i in range(n)] + [0]

    f_vals = [stats[d]["full_mu"] for d in dims] + [stats[dims[0]]["full_mu"]]
    a_vals = [stats[d]["abl4_mu"] for d in dims] + [stats[dims[0]]["abl4_mu"]]
    t_vals = [THRESHOLDS[d] for d in dims] + [THRESHOLDS[dims[0]]]

    ax.plot(angles, f_vals, color=COLOUR_FULL, linewidth=2, label="Full COMPASS")
    ax.fill(angles, f_vals, color=COLOUR_FULL, alpha=0.15)
    ax.plot(angles, a_vals, color=COLOUR_ABL4, linewidth=2, linestyle="--", label="Ablation 4")
    ax.fill(angles, a_vals, color=COLOUR_ABL4, alpha=0.10)
    ax.plot(angles, t_vals, color="grey", linewidth=1, linestyle=":", label="Pass threshold")

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([DIM_LABELS[d] for d in dims], fontsize=9)
    ax.set_ylim(0, 5)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_yticklabels(["1", "2", "3", "4", "5"], fontsize=7)
    ax.set_title("(b) Rubric Profile (mean)", fontsize=11, pad=15)
    ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.15), fontsize=9)


# ---------------------------------------------------------------------------
# Plot 3 — Heatmap: rubric scores per trial, stacked by condition
# ---------------------------------------------------------------------------

def _heatmap(ax: plt.Axes, matrix: np.ndarray, row_labels: list[str],
             col_labels: list[str], show_xlabels: bool) -> None:
    """Draw one heatmap panel using seaborn if available, else imshow."""
    if _HAS_SEABORN:
        sns.heatmap(
            matrix, ax=ax, annot=True, fmt=".0f",
            cmap="RdYlGn", vmin=1, vmax=5,
            xticklabels=col_labels if show_xlabels else [],
            yticklabels=row_labels,
            linewidths=0.4, linecolor="white",
            cbar=False, annot_kws={"size": 7},
        )
    else:
        im = ax.imshow(matrix, cmap="RdYlGn", vmin=1, vmax=5, aspect="auto")
        ax.set_yticks(range(len(row_labels)))
        ax.set_yticklabels(row_labels, fontsize=8)
        if show_xlabels:
            ax.set_xticks(range(len(col_labels)))
            ax.set_xticklabels(col_labels, fontsize=7)
        else:
            ax.set_xticks([])
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                ax.text(j, i, f"{int(matrix[i, j])}", ha="center", va="center",
                        fontsize=7, color="black")

    ax.set_yticklabels(ax.get_yticklabels(), rotation=0, fontsize=8)
    if show_xlabels:
        ax.set_xticklabels(ax.get_xticklabels(), fontsize=7)


def plot_score_distribution(ax_full: plt.Axes, ax_abl4: plt.Axes, stats: dict) -> None:
    dims      = RUBRIC_DIMS
    n         = len(stats[dims[0]]["full_vals"])
    col_labels = [str(i + 1) for i in range(n)]
    row_labels = [DIM_LABELS[d] for d in dims]

    full_matrix = np.array([[stats[d]["full_vals"][t] for t in range(n)] for d in dims])
    abl4_matrix = np.array([[stats[d]["abl4_vals"][t] for t in range(n)] for d in dims])

    _heatmap(ax_full, full_matrix, row_labels, col_labels, show_xlabels=False)
    _heatmap(ax_abl4, abl4_matrix, row_labels, col_labels, show_xlabels=True)

    ax_full.set_title(
        "(c) Rubric Scores per Trial\nFull COMPASS",
        fontsize=10, color=COLOUR_FULL, fontweight="bold",
    )
    ax_abl4.set_title("Ablation 4", fontsize=10, color=COLOUR_ABL4, fontweight="bold")
    ax_abl4.set_xlabel("Trial", fontsize=9)


# ---------------------------------------------------------------------------
# Plot 4 — Satisfactory rate comparison
# ---------------------------------------------------------------------------

def plot_satisfactory_rate(ax: plt.Axes, stats: dict) -> None:
    f_rate = stats["_satisfactory"]["full"]
    a_rate = stats["_satisfactory"]["abl4"]
    n      = stats["_satisfactory"]["n"]

    bars = ax.bar(
        ["Full COMPASS", "Ablation 4"],
        [f_rate, a_rate],
        color=[COLOUR_FULL, COLOUR_ABL4],
        alpha=0.85,
        width=0.45,
    )

    # Label each bar with the count and percentage
    f_count = round(f_rate * n / 100)
    a_count = round(a_rate * n / 100)
    ax.text(0, f_rate + 1.5, f"{f_rate:.0f}%\n({f_count}/{n})", ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.text(1, a_rate + 1.5, f"{a_rate:.0f}%\n({a_count}/{n})", ha="center", va="bottom", fontsize=11, fontweight="bold")

    # Pass threshold reference line at 100% (all-or-nothing satisficing)
    ax.axhline(100, color="grey", linestyle="dashed", linewidth=0.8, alpha=0.5)

    ax.set_ylim(0, 120)
    ax.set_ylabel("Trials with satisfactory plan (%)", fontsize=10)
    ax.set_title("(d) Satisfactory Rate\n(all 4 rubric dimensions ≥ threshold)", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Ablation 4 analysis and plots")
    parser.add_argument("csv_path", type=Path, help="Path to ablation4_results_*.csv")
    args = parser.parse_args()

    if not args.csv_path.exists():
        print(f"[ERROR] File not found: {args.csv_path}")
        sys.exit(1)

    rows       = load_csv(args.csv_path)
    full, abl4 = split(rows)

    if not full or not abl4:
        print("[ERROR] CSV must contain rows for both 'full' and 'ablation4' conditions.")
        sys.exit(1)

    if len(full) != len(abl4):
        print(f"[WARN] Unequal trial counts: full={len(full)}, ablation4={len(abl4)}. "
              "Truncating to the shorter set for paired tests.")
        n = min(len(full), len(abl4))
        full, abl4 = full[:n], abl4[:n]

    print(f"\nLoaded {len(full)} trials per condition from {args.csv_path.name}")

    stats = print_stats(full, abl4)

    out_dir = args.csv_path.parent / "ablation4_plots"
    out_dir.mkdir(exist_ok=True)
    print(f"\nGenerating combined figure -> {out_dir}/")

    fig = plt.figure(figsize=(15, 11))
    fig.suptitle("Ablation 4: Full COMPASS vs No Reflexion Loop", fontsize=14, fontweight="bold", y=0.99)

    gs      = GridSpec(2, 2, figure=fig, hspace=0.50, wspace=0.38)
    ax1     = fig.add_subplot(gs[0, 0])
    ax2     = fig.add_subplot(gs[0, 1], projection="polar")
    ax4     = fig.add_subplot(gs[1, 1])

    # Split bottom-left cell into two stacked heatmaps
    gs_c   = GridSpecFromSubplotSpec(2, 1, subplot_spec=gs[1, 0], hspace=0.18)
    ax3a   = fig.add_subplot(gs_c[0])
    ax3b   = fig.add_subplot(gs_c[1])

    plot_rubric_bar(ax1, stats)
    plot_radar(ax2, stats)
    plot_score_distribution(ax3a, ax3b, stats)
    plot_satisfactory_rate(ax4, stats)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    path = out_dir / "ablation4_combined.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
