# Ablation Study Metrics Guide

This guide shows how to collect and analyze metrics from your ablation tests.

## Overview

The metrics system measures:

1. **Critique Rubric Scores** — all 5 dimensions (feasibility, level_appropriateness, prerequisite_ordering, gap_coverage, internship_readiness) + composite
2. **Plan Structure** — number of phases, total actions, timeline in weeks
3. **Personalization** — action specificity ratio (what % of student's resume terms appear in plan rationale)
4. **Iterations** — how many times critique loop ran
5. **Errors** — whether the run completed successfully

## Workflow

### Step 1: Prepare Your Test Scenario

Save the student's resume as a text file:

```
path/to/test_resumes/ml_engineer_junior.txt
```

Note the desired role:
```
"ML Engineer"
```

### Step 2: Run Full COMPASS Baseline (N times)

Collect baseline metrics for the full system:

```bash
python collect_metrics.py \
  --scenario "ml_engineer_junior" \
  --desired-role "ML Engineer" \
  --resume-file "path/to/test_resumes/ml_engineer_junior.txt" \
  --condition "full" \
  --runs 5 \
  --output "ablation_metrics.csv"
```

This will:
- Run the full COMPASS pipeline 5 times
- Append each run's metrics to `ablation_metrics.csv`

**Expected time:** ~5 min per run (adjust `--runs` if this is too long)

### Step 3: Run Ablation 3 (N times on the same scenario)

```bash
python collect_metrics.py \
  --scenario "ml_engineer_junior" \
  --desired-role "ML Engineer" \
  --resume-file "path/to/test_resumes/ml_engineer_junior.txt" \
  --condition "ablation3" \
  --runs 5 \
  --output "ablation_metrics.csv"
```

This will:
- Run Ablation 3 (single-pass baseline) 5 times
- Append to the same `ablation_metrics.csv`

### Step 4: Analyze Results

```bash
python analyze_metrics.py \
  --input "ablation_metrics.csv" \
  --output "ablation_results" \
  --plot
```

This generates:
- `ablation_results/summary_table.md` — means, stdevs, ranges per metric per condition
- `ablation_results/all_runs.csv` — raw data for all runs
- `ablation_results/comparison_plots.png` — boxplots per metric

## CSV Schema

Each row represents one run:

| Column | Type | Notes |
|--------|------|-------|
| `timestamp` | ISO string | When run started |
| `run_id` | string | Unique run identifier |
| `condition` | "full" or "ablation3" | Which variant ran |
| `scenario` | string | Scenario ID (e.g., "ml_engineer_junior") |
| `attempt` | int | Run number (1, 2, 3, ...) |
| `critique_satisfactory` | bool | Did plan pass all rubric thresholds? |
| `rubric_feasibility` | float | Feasibility score (1–5) |
| `rubric_level_appropriateness` | float | Level appropriateness (1–5) |
| `rubric_prerequisite_ordering` | float | Prerequisite order (1–5) |
| `rubric_gap_coverage` | float | Gap coverage (1–5) |
| `rubric_internship_readiness` | float | Internship readiness (1–5) |
| `rubric_composite` | float | Mean of feasibility + level + ordering + internship (excludes gap_coverage) |
| `plan_phases` | int | Number of phases in plan |
| `plan_actions_total` | int | Total learning actions across all phases |
| `plan_timeline_weeks` | float | Total weeks in the plan |
| `action_specificity_ratio` | float | % of resume terms mentioned in action rationales [0–1] |
| `resume_terms_mentioned` | int | Count of resume terms found in rationales |
| `resume_terms_total` | int | Total unique terms extracted from resume |
| `critique_iterations` | int | How many times critique loop ran (1 for ablations) |
| `has_errors` | bool | Run encountered any errors? |
| `error_count` | int | Number of errors |

## Interpretation

### Rubric Scores

- **Composite (key metric):** Mean of feasibility, level_appropriateness, prerequisite_ordering, internship_readiness
  - Full COMPASS should be significantly higher if multi-agent orchestration produces quality
  - Ablation 3 may excel at feasibility (simpler plans are more feasible) but lag on level appropriateness and prerequisite ordering

- **Gap Coverage:** Inflated for Ablation 3 (empty gap_report = vacuously true). Do not compare this dimension.

### Personalization Metrics

- **`action_specificity_ratio`** (key metric for RQ4): 
  - Full COMPASS rationales should reference more student-specific skills/projects
  - Ablation 3 may resort to generic guidance
  - Example: Full = 0.65 (65% of resume terms mentioned), Ablation 3 = 0.25

### Plan Structure

- **`plan_phases` and `plan_actions_total`:**
  - Both conditions produce ~3–5 phases by design
  - May differ due to gap structure (full) vs. raw resume (ablation3)
  - Use as supporting evidence, not primary claim

## Example Analysis

After running 5 iterations on both conditions, your `summary_table.md` might look like:

```markdown
# Ablation Study Results

| Metric | full | ablation3 |
|--------|------|-----------|
| Rubric Composite Score | 3.65 ± 0.21 [3.40–3.95] | 3.12 ± 0.35 [2.65–3.52] |
| Feasibility | 4.20 ± 0.10 [4.05–4.35] | 4.15 ± 0.25 [3.80–4.45] |
| Level Appropriateness | 3.60 ± 0.32 [3.15–4.05] | 2.95 ± 0.43 [2.30–3.60] |
| Prerequisite Ordering | 3.40 ± 0.35 [2.90–3.85] | 2.65 ± 0.48 [2.10–3.25] |
| Internship Readiness | 3.65 ± 0.29 [3.30–4.00] | 3.10 ± 0.38 [2.65–3.65] |
| Action Specificity | 0.68 ± 0.08 [0.58–0.78] | 0.31 ± 0.12 [0.18–0.48] |

## Run Success Rate

| Condition | Successful | Failed | Error Rate |
|-----------|-----------|--------|------------|
| full | 5/5 | 0 | 0.0% |
| ablation3 | 5/5 | 0 | 0.0% |
```

**Claim for RQ4:** 
- Multi-agent orchestration (full COMPASS) produces higher-quality pathways (composite 3.65 vs 3.12, p<0.05)
- Full COMPASS is significantly more personalized (action specificity 0.68 vs 0.31, p<0.001)
- Both conditions succeed on feasibility, but full COMPASS is better at level-appropriate sequencing (3.60 vs 2.95)

## Multiple Scenarios

To run across multiple test scenarios, repeat Steps 2–3 for each scenario:

```bash
# Scenario 1
python collect_metrics.py --scenario s1 --desired-role "ML Engineer" --resume-file s1.txt --condition full --runs 5 --output metrics.csv
python collect_metrics.py --scenario s1 --desired-role "ML Engineer" --resume-file s1.txt --condition ablation3 --runs 5 --output metrics.csv

# Scenario 2
python collect_metrics.py --scenario s2 --desired-role "Full-Stack Developer" --resume-file s2.txt --condition full --runs 5 --output metrics.csv
python collect_metrics.py --scenario s2 --desired-role "Full-Stack Developer" --resume-file s2.txt --condition ablation3 --runs 5 --output metrics.csv

# Analyze all
python analyze_metrics.py --input metrics.csv --output results --plot
```

Then `summary_table.md` will show cross-scenario aggregates.

## Troubleshooting

### `graph_ablation3` not found

Ensure you've created `app/graph_ablation3.py` following the Ablation 3 implementation guide.

### Metrics CSV has all zeros

Check that critique node is running and returning scores. Print the final state to debug.

### `action_specificity_ratio` is 0

Resume parsing may have failed. Check:
1. Resume text is valid UTF-8
2. Resume contains common skill keywords (Python, React, etc.)
3. Rationales are non-empty

### Matplotlib import error

Optional; skipped by default. Install with: `pip install matplotlib`

## Next Steps

1. **Run baseline (full)** with your test scenario(s)
2. **Run ablation3** on the same scenario(s)
3. **Analyze** and compare metrics
4. **Document findings** in paper (focus on action_specificity_ratio + composite rubric score)
