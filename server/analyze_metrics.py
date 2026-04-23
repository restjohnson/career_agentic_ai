#!/usr/bin/env python3
"""
Analyze metrics from ablation study CSV and generate comparison tables.

Usage:
    python analyze_metrics.py --input ablation_metrics.csv --output results/

Generates:
    - summary_table.md (mean/std/min/max per condition)
    - full_table.csv (all raw data)
    - comparison_plots.png (optional: matplotlib visualization)
"""

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Any
from dataclasses import dataclass
from statistics import mean, stdev, StatisticsError


@dataclass
class MetricStats:
    """Statistics for a single metric across runs."""
    name: str
    count: int
    mean: float
    stdev: float
    min: float
    max: float

    def __str__(self) -> str:
        """Format for markdown table."""
        return f"{self.mean:.2f} ± {self.stdev:.2f} [{self.min:.2f}–{self.max:.2f}]"


def load_metrics_csv(csv_path: Path) -> List[Dict[str, Any]]:
    """Load metrics from CSV file."""
    rows = []
    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert numeric columns to float
            numeric_cols = [
                'rubric_feasibility', 'rubric_level_appropriateness',
                'rubric_prerequisite_ordering', 'rubric_gap_coverage',
                'rubric_internship_readiness', 'rubric_composite',
                'plan_phases', 'plan_actions_total', 'plan_timeline_weeks',
                'action_specificity_ratio',
                'resume_terms_mentioned', 'resume_terms_total',
                'critique_iterations', 'error_count',
            ]
            for col in numeric_cols:
                if col in row and row[col]:
                    try:
                        row[col] = float(row[col])
                    except ValueError:
                        row[col] = None

            # Convert boolean columns
            if 'critique_satisfactory' in row:
                row['critique_satisfactory'] = row['critique_satisfactory'].lower() == 'true'
            if 'has_errors' in row:
                row['has_errors'] = row['has_errors'].lower() == 'true'

            rows.append(row)

    return rows


def group_by_condition(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group rows by condition (full, ablation3, etc.)."""
    groups = {}
    for row in rows:
        condition = row['condition']
        if condition not in groups:
            groups[condition] = []
        groups[condition].append(row)
    return groups


def compute_metric_stats(
    values: List[float],
    metric_name: str
) -> MetricStats:
    """Compute mean, stdev, min, max for a metric."""
    valid_values = [v for v in values if v is not None and isinstance(v, (int, float))]

    if not valid_values:
        return MetricStats(
            name=metric_name,
            count=0,
            mean=0.0,
            stdev=0.0,
            min=0.0,
            max=0.0,
        )

    try:
        stdev_val = stdev(valid_values) if len(valid_values) > 1 else 0.0
    except StatisticsError:
        stdev_val = 0.0

    return MetricStats(
        name=metric_name,
        count=len(valid_values),
        mean=mean(valid_values),
        stdev=stdev_val,
        min=min(valid_values),
        max=max(valid_values),
    )


def generate_summary_table(
    grouped_rows: Dict[str, List[Dict[str, Any]]]
) -> str:
    """Generate markdown summary table with stats per condition."""
    # Metrics to include in summary
    metrics = [
        ('rubric_composite', 'Rubric Composite Score'),
        ('rubric_feasibility', 'Feasibility'),
        ('rubric_level_appropriateness', 'Level Appropriateness'),
        ('rubric_prerequisite_ordering', 'Prerequisite Ordering'),
        ('rubric_internship_readiness', 'Internship Readiness'),
        ('plan_phases', 'Plan Phases'),
        ('plan_actions_total', 'Total Actions'),
        ('plan_timeline_weeks', 'Timeline (weeks)'),
        ('action_specificity_ratio', 'Specificity Ratio'),
        ('resume_terms_mentioned', 'Resume Terms Mentioned'),
        ('critique_iterations', 'Critique Iterations'),
    ]

    # Build table header
    header = "| Metric | " + " | ".join(grouped_rows.keys()) + " |\n"
    separator = "|--------|" + "|".join(["---" for _ in grouped_rows.keys()]) + "|\n"

    rows_md = [header, separator]

    # For each metric, compute stats per condition and add row
    for metric_key, metric_label in metrics:
        row_parts = [f"| {metric_label} |"]

        for condition in sorted(grouped_rows.keys()):
            condition_rows = grouped_rows[condition]
            values = [r.get(metric_key) for r in condition_rows]
            stats = compute_metric_stats(values, metric_key)

            row_parts.append(f" {stats} |")

        rows_md.append("".join(row_parts) + "\n")

    return "".join(rows_md)


def generate_success_rate_table(
    grouped_rows: Dict[str, List[Dict[str, Any]]]
) -> str:
    """Generate table showing success rate and error counts."""
    header = "| Condition | Successful | Failed | Error Rate |\n"
    separator = "|-----------|-----------|--------|------------|\n"

    rows_md = [header, separator]

    for condition in sorted(grouped_rows.keys()):
        condition_rows = grouped_rows[condition]
        total = len(condition_rows)
        failed = sum(1 for r in condition_rows if r.get('has_errors', False))
        successful = total - failed
        error_rate = (failed / total * 100) if total > 0 else 0

        row = f"| {condition} | {successful}/{total} | {failed} | {error_rate:.1f}% |\n"
        rows_md.append(row)

    return "".join(rows_md)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze ablation metrics and generate comparison tables"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("ablation_metrics.csv"),
        help="Input CSV file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ablation_results"),
        help="Output directory for results",
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Generate matplotlib plots (requires matplotlib)",
    )

    args = parser.parse_args()

    # Check input exists
    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}")
        sys.exit(1)

    # Create output directory
    args.output.mkdir(parents=True, exist_ok=True)

    print(f"\nLoading metrics from {args.input}...")
    rows = load_metrics_csv(args.input)
    print(f"  Loaded {len(rows)} runs")

    grouped = group_by_condition(rows)
    print(f"  Conditions: {', '.join(sorted(grouped.keys()))}")

    for condition, cond_rows in grouped.items():
        print(f"    - {condition}: {len(cond_rows)} runs")

    # Generate summary table
    print("\nGenerating summary statistics table...")
    summary_md = generate_summary_table(grouped)
    summary_path = args.output / "summary_table.md"
    summary_path.write_text("# Ablation Study Results\n\n" + summary_md)
    print(f"  [OK] Saved to {summary_path}")

    # Generate success rate table
    print("Generating success rate table...")
    success_md = generate_success_rate_table(grouped)
    summary_path.write_text(
        summary_path.read_text() + "\n## Run Success Rate\n\n" + success_md
    )
    print(f"  [OK] Updated {summary_path}")

    # Generate CSV with all data
    print("Generating full data table...")
    all_data_path = args.output / "all_runs.csv"
    with open(all_data_path, 'w', newline='') as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    print(f"  [OK] Saved to {all_data_path}")


    if args.plot:
        try:
            import matplotlib.pyplot as plt
            import numpy as np

            print("Generating plots...")

            fig, axes = plt.subplots(2, 3, figsize=(15, 10))
            fig.suptitle("Ablation Study: Metric Comparison", fontsize=16)

            plot_metrics = [
                ('rubric_composite', 'Rubric Composite Score'),
                ('plan_actions_total', 'Total Learning Actions'),
                ('action_specificity_ratio', 'Action Specificity'),
                ('plan_timeline_weeks', 'Timeline (weeks)'),
                ('rubric_feasibility', 'Feasibility'),
                ('resume_terms_mentioned', 'Resume Terms Mentioned'),
            ]

            for idx, (metric_key, metric_label) in enumerate(plot_metrics):
                ax = axes[idx // 3, idx % 3]

                positions = []
                labels = []
                data_to_plot = []

                for pos, condition in enumerate(sorted(grouped.keys())):
                    condition_rows = grouped[condition]
                    values = [r.get(metric_key) for r in condition_rows]
                    values = [v for v in values if v is not None]
                    if values:
                        data_to_plot.append(values)
                        positions.append(pos)
                        labels.append(condition)

                if data_to_plot:
                    bp = ax.boxplot(
                        data_to_plot,
                        positions=positions,
                        labels=labels,
                        patch_artist=True,
                    )
                    # Color boxes
                    for patch in bp['boxes']:
                        patch.set_facecolor('lightblue')
                    ax.set_title(metric_label)
                    ax.grid(True, alpha=0.3)

            plt.tight_layout()
            plot_path = args.output / "comparison_plots.png"
            plt.savefig(plot_path, dpi=150)
            print(f"  [OK] Saved to {plot_path}")
            plt.close()

        except ImportError:
            print("  [WARN] matplotlib not found; skipping plots. Install with: pip install matplotlib")

    print(f"\n[DONE] Analysis complete! Results in {args.output}/")


if __name__ == "__main__":
    main()
