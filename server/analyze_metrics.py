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
                'rubric_gap_coverage',
                'plan_phases', 'plan_actions_total', 'plan_timeline_weeks',
                'action_specificity_ratio',
                'resume_terms_mentioned', 'resume_terms_total',
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
    # Tuples of (key, label, is_satisfactory_rate)
    metrics = [
        ('critique_satisfactory', 'Satisfactory Rate', True),
        ('rubric_feasibility', 'Feasibility', False),
        ('rubric_level_appropriateness', 'Level Appropriateness', False),
        ('rubric_gap_coverage', 'Gap Coverage', False),
        ('plan_phases', 'Plan Phases', False),
        ('plan_actions_total', 'Total Actions', False),
        ('plan_timeline_weeks', 'Timeline (weeks)', False),
        ('action_specificity_ratio', 'Specificity Ratio', False),
        ('resume_terms_mentioned', 'Resume Terms Mentioned', False),
    ]

    conditions = sorted(grouped_rows.keys())

    # Build table header
    header = "| Metric | " + " | ".join(conditions) + " |\n"
    separator = "|--------|" + "|".join(["---" for _ in conditions]) + "|\n"

    rows_md = [header, separator]

    # For each metric, compute stats per condition and add row
    for metric_key, metric_label, is_rate in metrics:
        row_parts = [f"| {metric_label} |"]

        for condition in conditions:
            condition_rows = grouped_rows[condition]

            if is_rate:
                vals = [r.get(metric_key) for r in condition_rows]
                vals = [v for v in vals if v is not None]
                n_pass = sum(1 for v in vals if v is True)
                pct = (n_pass / len(vals) * 100) if vals else 0.0
                cell = f"{pct:.1f}% ({n_pass}/{len(vals)})"
            else:
                values = [r.get(metric_key) for r in condition_rows]
                stats = compute_metric_stats(values, metric_key)
                cell = str(stats)

            row_parts.append(f" {cell} |")

        rows_md.append("".join(row_parts) + "\n")

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
            fig.suptitle("Ablation 3: COMPASS vs Non-Agentic LLM run", fontsize=16)

            plot_metrics = [
                ('critique_satisfactory', 'Satisfactory Rate', True),
                ('plan_actions_total', 'Total Learning Actions', False),
                ('action_specificity_ratio', 'Action Specificity', False),
                ('plan_timeline_weeks', 'Timeline (weeks)', False),
                ('rubric_feasibility', 'Feasibility', False),
                ('resume_terms_mentioned', 'Resume Terms Mentioned', False),
            ]

            colors_cycle = ['#2196F3', '#FF5722', '#4CAF50', '#9C27B0']

            for idx, (metric_key, metric_label, is_rate) in enumerate(plot_metrics):
                ax = axes[idx // 3, idx % 3]

                conds = sorted(grouped.keys())

                if is_rate:
                    sat_rates = []
                    for condition in conds:
                        vals = [r.get(metric_key) for r in grouped[condition]]
                        vals = [v for v in vals if v is not None]
                        rate = sum(1 for v in vals if v is True) / len(vals) * 100 if vals else 0.0
                        sat_rates.append(rate)
                    x_pos = np.arange(len(conds))
                    bars = ax.bar(x_pos, sat_rates,
                                  color=colors_cycle[:len(conds)], width=0.5)
                    ax.set_xticks(x_pos)
                    ax.set_xticklabels(conds)
                    ax.set_ylim(0, 110)
                    ax.set_ylabel('%')
                    for bar, rate in zip(bars, sat_rates):
                        ax.text(bar.get_x() + bar.get_width() / 2,
                                bar.get_height() + 2,
                                f'{rate:.0f}%', ha='center', va='bottom', fontsize=11)
                else:
                    positions = []
                    labels = []
                    data_to_plot = []

                    for pos, condition in enumerate(conds):
                        condition_rows = grouped[condition]
                        values = [r.get(metric_key) for r in condition_rows]
                        values = [v for v in values if isinstance(v, (int, float))]
                        if values:
                            data_to_plot.append(values)
                            positions.append(pos)
                            labels.append(condition)

                    if data_to_plot:
                        bp = ax.boxplot(
                            data_to_plot,
                            positions=positions,
                            tick_labels=labels,
                            patch_artist=True,
                        )
                        for patch in bp['boxes']:
                            patch.set_facecolor('lightblue')

                ax.set_title(metric_label)
                ax.grid(True, alpha=0.3)

            plt.tight_layout()
            plot_path = args.output / "comparison_plots.png"
            plt.savefig(plot_path, dpi=150)
            print(f"  [OK] Saved to {plot_path}")
            plt.close()

            # --- Radar chart: rubric dimensions per condition ---
            # critique_satisfactory is scaled 0-5 (rate * 5) to match rubric scale
            radar_metrics = [
                ('critique_satisfactory', 'Satisfactory\nRate', True),
                ('rubric_feasibility', 'Feasibility', False),
                ('rubric_level_appropriateness', 'Level\nAppropriateness', False),
                ('rubric_gap_coverage', 'Gap\nCoverage', False),
                ('action_specificity_ratio', 'Action\nSpecificity', False),
            ]
            radar_labels = [label for _, label, _ in radar_metrics]
            num_vars = len(radar_labels)
            angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
            angles += angles[:1]  # close the polygon

            fig_r, ax_r = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
            fig_r.suptitle("Rubric Profile by Condition", fontsize=14)

            colors = ['#2196F3', '#FF5722', '#4CAF50', '#9C27B0']
            for color, condition in zip(colors, sorted(grouped.keys())):
                condition_rows = grouped[condition]
                vals = []
                for metric_key, _, is_bool_rate in radar_metrics:
                    raw = [r.get(metric_key) for r in condition_rows]
                    if is_bool_rate:
                        valid = [v for v in raw if v is not None]
                        rate = sum(1 for v in valid if v is True) / len(valid) if valid else 0.0
                        vals.append(rate * 5)
                    else:
                        valid = [v for v in raw if isinstance(v, (int, float))]
                        vals.append(mean(valid) if valid else 0.0)
                vals += vals[:1]
                ax_r.plot(angles, vals, color=color, linewidth=2, label=condition)
                ax_r.fill(angles, vals, color=color, alpha=0.15)

            ax_r.set_xticks(angles[:-1])
            ax_r.set_xticklabels(radar_labels, size=10)
            ax_r.set_ylim(0, 5)
            ax_r.set_yticks([1, 2, 3, 4, 5])
            ax_r.set_yticklabels(['1', '2', '3', '4', '5'], size=8)
            ax_r.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1))
            ax_r.grid(True)

            radar_path = args.output / "radar_chart.png"
            plt.savefig(radar_path, dpi=150, bbox_inches='tight')
            print(f"  [OK] Saved to {radar_path}")
            plt.close()

            # --- Bar chart: satisfactory rate per condition ---
            conditions_sorted = sorted(grouped.keys())
            sat_rates = []
            for condition in conditions_sorted:
                rows_c = grouped[condition]
                sat_vals = [r.get('critique_satisfactory') for r in rows_c]
                sat_vals = [v for v in sat_vals if v is not None]
                rate = sum(1 for v in sat_vals if v is True) / len(sat_vals) * 100 if sat_vals else 0.0
                sat_rates.append(rate)

            _, ax_b = plt.subplots(figsize=(6, 5))
            x_pos = np.arange(len(conditions_sorted))
            bars = ax_b.bar(x_pos, sat_rates, color=['#2196F3', '#FF5722', '#4CAF50', '#9C27B0'][:len(conditions_sorted)], width=0.5)
            ax_b.set_xticks(x_pos)
            ax_b.set_xticklabels(conditions_sorted, fontsize=12)
            ax_b.set_ylabel('Satisfactory Rate (%)', fontsize=11)
            ax_b.set_title('Critique Satisfactory Rate by Condition', fontsize=13)
            ax_b.set_ylim(0, 110)
            ax_b.grid(axis='y', alpha=0.3)
            for bar, rate in zip(bars, sat_rates):
                ax_b.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2,
                          f'{rate:.0f}%', ha='center', va='bottom', fontsize=12, fontweight='bold')

            bar_path = args.output / "satisfactory_rate.png"
            plt.savefig(bar_path, dpi=150, bbox_inches='tight')
            print(f"  [OK] Saved to {bar_path}")
            plt.close()

        except ImportError:
            print("  [WARN] matplotlib not found; skipping plots. Install with: pip install matplotlib")

    print(f"\n[DONE] Analysis complete! Results in {args.output}/")


if __name__ == "__main__":
    main()
