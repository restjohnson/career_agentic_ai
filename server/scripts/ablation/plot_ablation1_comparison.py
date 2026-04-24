from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np


SERVER_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_DIR = SERVER_ROOT / "results" / "ablation"


def _latest_file(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime)
    if not matches:
        raise FileNotFoundError(f"No files matching {pattern!r} found in {directory}")
    return matches[-1]


def _load_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_json_payload(json_path: Path) -> dict[str, Any]:
    return json.loads(json_path.read_text(encoding="utf-8"))


def _parse_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def _parse_scores(value: str) -> dict[str, int]:
    parsed = json.loads(value)
    return {str(key): int(score) for key, score in parsed.items()}


def _condition_label(value: str) -> str:
    labels = {
        "full_compass": "Full COMPASS",
        "ablation1_no_role_grounding": "Ablation 1",
    }
    return labels.get(value, value)


def _build_metrics(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    for row in rows:
        label = _condition_label(row["condition"])
        metrics[label] = {
            "num_requirements": int(row["num_requirements"]),
            "num_requirements_with_provenance": int(row["num_requirements_with_provenance"]),
            "num_gaps": int(row["num_gaps"]),
            "num_no_evidence_gaps": int(row["num_no_evidence_gaps"]),
            "critique_iterations": int(row["critique_iterations"]),
            "critique_satisfactory": 1 if _parse_bool(row["critique_satisfactory"]) else 0,
            "rubric_scores": _parse_scores(row["critique_rubric_scores"]),
            "requirement_categories": row["requirement_categories"],
        }
    return metrics


def _plot(metrics: dict[str, dict[str, Any]], scenario_role: str, output_path: Path) -> None:
    conditions = ["Full COMPASS", "Ablation 1"]
    colors = ["#1f77b4", "#d62728"]

    counts = {
        "Requirements": [metrics[c]["num_requirements"] for c in conditions],
        "Gaps": [metrics[c]["num_gaps"] for c in conditions],
        "No-Evidence Gaps": [metrics[c]["num_no_evidence_gaps"] for c in conditions],
        "Critique Iterations": [metrics[c]["critique_iterations"] for c in conditions],
    }

    rubric_dimensions = ["gap_coverage", "jit_compliance", "feasibility", "level_appropriateness"]
    rubric_labels = ["Gap Coverage", "JIT", "Feasibility", "Level Fit"]

    fig = plt.figure(figsize=(17, 13), constrained_layout=True)
    grid = fig.add_gridspec(2, 2)
    ax_counts = fig.add_subplot(grid[0, 0])
    ax_provenance = fig.add_subplot(grid[0, 1])
    ax_rubric = fig.add_subplot(grid[1, 0])
    ax_status = fig.add_subplot(grid[1, 1])

    x = np.arange(len(counts))
    width = 0.35
    for index, condition in enumerate(conditions):
        values = [counts[name][index] for name in counts]
        offset = (-width / 2) if index == 0 else (width / 2)
        bars = ax_counts.bar(x + offset, values, width=width, color=colors[index], label=condition)
        ax_counts.bar_label(bars, padding=3, fontsize=9)
    ax_counts.set_xticks(x, list(counts.keys()), rotation=15, ha="right")
    ax_counts.set_title("Core Outcome Metrics", fontsize=14, fontweight="bold")
    ax_counts.set_ylabel("Count", fontsize=14)
    ax_counts.set_ylim(0, 22)
    ax_counts.set_yticks(np.arange(0, 23, 2))
    ax_counts.tick_params(axis="both", labelsize=13)
    ax_counts.legend(frameon=False)
    ax_counts.text(
        0.01,
        0.98,
        "Ablation 1 inflates requirement and gap counts\n"
        "because raw O*NET tech terms are not curated.",
        transform=ax_counts.transAxes,
        va="top",
        fontsize=10,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#cccccc"},
    )

    prov_values = [metrics[c]["num_requirements_with_provenance"] for c in conditions]
    bars = ax_provenance.bar(conditions, prov_values, color=colors)
    ax_provenance.bar_label(bars, padding=3, fontsize=10)
    ax_provenance.set_title("Requirements With Provenance", fontsize=14, fontweight="bold")
    ax_provenance.set_ylabel("Count", fontsize=14)
    ax_provenance.set_ylim(0, 22)
    ax_provenance.set_yticks(np.arange(0, 23, 2))
    ax_provenance.tick_params(axis="both", labelsize=13)
    ax_provenance.text(
        0.01,
        0.98,
        "Provenance supports traceability and auditability.\n"
        "Ablation 1 intentionally removes provenance (0).",
        transform=ax_provenance.transAxes,
        va="top",
        fontsize=10,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#cccccc"},
    )

    rubric_x = np.arange(len(rubric_dimensions))
    for index, condition in enumerate(conditions):
        values = [metrics[condition]["rubric_scores"].get(dim, 0) for dim in rubric_dimensions]
        ax_rubric.plot(rubric_x, values, marker="o", linewidth=2.5, color=colors[index], label=condition)
    ax_rubric.set_xticks(rubric_x, rubric_labels)
    ax_rubric.set_ylim(0, 8)
    ax_rubric.set_yticks(np.arange(0, 9, 1))
    ax_rubric.set_title("Final Critique Rubric Scores", fontsize=14, fontweight="bold")
    ax_rubric.set_ylabel("Score", fontsize=14)
    ax_rubric.tick_params(axis="both", labelsize=13)
    ax_rubric.grid(axis="y", linestyle="--", alpha=0.35)
    ax_rubric.legend(frameon=False)
    ax_rubric.text(
        0.01,
        0.98,
        "Largest separation is in Gap Coverage,\n"
        "showing weaker requirement-target alignment in Ablation 1.",
        transform=ax_rubric.transAxes,
        va="top",
        fontsize=10,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#cccccc"},
    )

    status_labels = ["Satisfactory", "Not Satisfactory"]
    full_status = [metrics["Full COMPASS"]["critique_satisfactory"], 1 - metrics["Full COMPASS"]["critique_satisfactory"]]
    abl_status = [metrics["Ablation 1"]["critique_satisfactory"], 1 - metrics["Ablation 1"]["critique_satisfactory"]]
    status_x = np.arange(len(status_labels))
    full_bars = ax_status.bar(status_x - width / 2, full_status, width=width, color=colors[0], label="Full COMPASS")
    abl_bars = ax_status.bar(status_x + width / 2, abl_status, width=width, color=colors[1], label="Ablation 1")
    ax_status.bar_label(full_bars, padding=3, fontsize=10)
    ax_status.bar_label(abl_bars, padding=3, fontsize=10)
    ax_status.set_xticks(status_x, status_labels)
    ax_status.set_ylim(0, 1.3)
    ax_status.set_title("Termination Status", fontsize=14, fontweight="bold")
    ax_status.set_ylabel("Count", fontsize=14)
    ax_status.set_yticks(np.arange(0, 1.4, 0.2))
    ax_status.tick_params(axis="both", labelsize=13)
    ax_status.legend(frameon=False)
    ax_status.text(
        0.01,
        0.98,
        "Full COMPASS terminated satisfactory;\n"
        "Ablation 1 ended not satisfactory after max iterations.",
        transform=ax_status.transAxes,
        va="top",
        fontsize=10,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#cccccc"},
    )

    fig.suptitle(
        "Ablation 1 Comparison for "
        f"{scenario_role}\n"
        "Full COMPASS keeps curated, provenance-backed requirements; "
        "Ablation 1 collapses to raw O*NET tech-only mapping.",
        fontsize=17,
        fontweight="bold",
    )
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot a matplotlib comparison for Ablation 1 results.")
    parser.add_argument("--csv", type=Path, default=None, help="Path to a specific ablation CSV file.")
    parser.add_argument("--json", type=Path, default=None, help="Path to a specific ablation JSON file.")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional output PNG path. Defaults to the CSV filename with _comparison.png suffix.",
    )
    args = parser.parse_args()

    csv_path = args.csv or _latest_file(DEFAULT_RESULTS_DIR, "ablation1_ml_engineer_*.csv")
    json_path = args.json or csv_path.with_suffix(".json")
    if not json_path.exists():
        json_path = _latest_file(DEFAULT_RESULTS_DIR, "ablation1_ml_engineer_*.json")

    rows = _load_csv_rows(csv_path)
    payload = _load_json_payload(json_path)
    metrics = _build_metrics(rows)

    scenario_role = str(payload.get("scenario", {}).get("role", "Machine Learning Engineer"))
    output_path = args.out or csv_path.with_name(csv_path.stem + "_comparison.png")
    _plot(metrics, scenario_role, output_path)
    print(f"Saved comparison plot to {output_path}")


if __name__ == "__main__":
    main()