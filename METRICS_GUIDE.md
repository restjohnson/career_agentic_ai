# Ablation Study Metrics Guide

This guide documents how to collect, analyze, and interpret metrics from COMPASS ablation tests.

## Overview

The metrics system measures four dimensions:

1. **Plan Quality** — critique satisfactory rate and rubric scores across three dimensions (feasibility, level appropriateness, gap coverage)
2. **Plan Structure** — number of phases, total actions, timeline in weeks
3. **Personalization** — action specificity ratio (proportion of student resume terms appearing in action rationales)
4. **Statistical Analysis** — Mann-Whitney U, Fisher's exact test, rank-biserial effect sizes, Levene's variance test

---

## Workflow

### Step 1: Prepare Your Test Scenario

Save the student's resume as a plain text file and note the desired role:

```
scenario_3_backend.txt
```

### Step 2: Start the Server

```bash
cd server
python -m uvicorn app.main:app --reload
```

### Step 3: Collect Metrics — Full COMPASS

```bash
python collect_metrics.py \
  --scenario "scenario_3_backend" \
  --desired-role "Backend Software Engineer" \
  --resume-file "scenario_3_backend.txt" \
  --condition "full" \
  --runs 15 \
  --output "ablation_metrics.csv"
```

### Step 4: Collect Metrics — Ablation 3

```bash
python collect_metrics.py \
  --scenario "scenario_3_backend" \
  --desired-role "Backend Software Engineer" \
  --resume-file "scenario_3_backend.txt" \
  --condition "ablation3" \
  --runs 15 \
  --output "ablation_metrics.csv"
```

The second run appends to the same CSV. Always delete `ablation_metrics.csv` before starting a fresh collection to avoid schema mismatches from prior runs.

### Step 5: Analyze and Plot

```bash
python analyze_metrics.py \
  --input "ablation_metrics.csv" \
  --output "ablation_results" \
  --plot
```

Generates:

| File | Contents |
|------|----------|
| `ablation_results/summary_table.md` | Mean ± SD [min–max] per metric per condition |
| `ablation_results/all_runs.csv` | Full raw data for all runs |
| `ablation_results/comparison_plots.png` | 2×3 grid: satisfactory rate bar + 5 box plots |
| `ablation_results/radar_chart.png` | Rubric profile overlay per condition (polar) |
| `ablation_results/satisfactory_rate.png` | Standalone satisfactory rate bar chart |

### Step 6: Statistical Analysis

```bash
python stats_analysis.py \
  --input "ablation_results/all_runs.csv" \
  --output "ablation_results"
```

Generates `ablation_results/statistical_analysis.md` with:
- Fisher's exact test + Wilson 95% CI on satisfactory rate
- Mann-Whitney U + rank-biserial r on all continuous metrics
- Levene's test on timeline variance

---

## CSV Schema

Each row represents one completed run. **Do not mix rows from different schema versions** — delete and re-collect if columns change.

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | ISO string | When the run started |
| `run_id` | string | Unique run identifier |
| `condition` | string | `"full"` or `"ablation3"` |
| `scenario` | string | Scenario identifier |
| `attempt` | int | Run number within this condition |
| `critique_satisfactory` | bool | Did the plan pass all rubric thresholds simultaneously? |
| `rubric_feasibility` | float 1–5 | Is the plan scoped to student's stated time constraints? |
| `rubric_level_appropriateness` | float 1–5 | Does difficulty match the student's academic level? |
| `rubric_gap_coverage` | float 1–5 | Does the plan address the identified skill gaps? |
| `plan_phases` | int | Number of phases in the generated plan |
| `plan_actions_total` | int | Total learning actions across all phases |
| `plan_timeline_weeks` | float | Total plan duration in weeks |
| `action_specificity_ratio` | float 0–1 | Proportion of student's resume terms referenced in action rationales |
| `resume_terms_mentioned` | int | Count of resume terms found in rationales |
| `resume_terms_total` | int | Total unique terms extracted from the resume |

---

## Metric Interpretation

### Satisfactory Rate (primary reliability metric)

A plan is satisfactory only when **all three** rubric dimensions simultaneously meet their thresholds — no compensation across dimensions is permitted (conjunctive satisficing). This is the headline metric for comparing conditions.

- **Full COMPASS (observed):** 100% (15/15), 95% CI [79.6%, 100.0%]
- **Ablation 3 (observed):** 46.7% (7/15), 95% CI [24.8%, 69.9%]
- **Test:** Fisher's exact, p = 0.002

### Rubric Scores

**Feasibility** is the most discriminating dimension. The full pipeline enforces constraint-aware planning and iterative critique, producing zero-variance feasibility scores. The single-pass baseline exhibits a bimodal distribution (either 2 or 5) — it either over-scopes dramatically or gets it right, with no reliable mechanism to regulate scope.

**Level appropriateness** is a baseline LLM capability. Both conditions score uniformly at 5.00. Do not use this dimension to distinguish conditions.

**Gap coverage** is expected to favor Ablation 3. Without a feasibility constraint, the single-pass baseline generates broader plans that address more gaps. This is not evidence of higher quality — it reflects unconstrained generation. The high gap coverage in Ablation 3 co-occurs with a 46.7% satisfactory rate, confirming breadth without constraint adherence is not educationally useful.

### Action Specificity (primary personalization metric)

Measures how grounded the plan is in the individual student's background. Higher values mean the plan's learning actions explicitly reference skills, technologies, and projects from the student's resume rather than generic recommendations.

- **Full COMPASS (observed):** Mdn = 0.21, SD = 0.02 — consistently personalized
- **Ablation 3 (observed):** Mdn = 0.12, SD = 0.04 — less personalized, more variable
- **Effect:** r = +0.85 (large), p < 0.001

### Plan Structure

Both conditions produce similar average phase counts, but the key difference is **variance**:

- COMPASS: 3.13 actions ± 0.35 — consistent, scope-regulated plans
- Ablation 3: 5.47 actions ± 2.47 (range 1–10) — highly variable, unregulated scope

**Timeline** should be analyzed for variance, not mean. Both conditions average 14.93 weeks, but COMPASS SD = 1.83 vs. Ablation 3 SD = 4.65 (Levene's F = 9.46, p = 0.005).

---

## Statistical Tests Reference

| Metric type | Test | Effect size | Reported as |
|---|---|---|---|
| Binary (satisfactory rate) | Fisher's exact | Odds ratio + Wilson 95% CI | OR, p, [CI_lo%, CI_hi%] |
| Continuous (rubric, actions, specificity) | Mann-Whitney U | Rank-biserial r | U, p, r |
| Variance (timeline) | Levene's | F statistic | F, p |

**Rank-biserial r interpretation:**
- r > 0: COMPASS > Ablation 3
- r < 0: Ablation 3 > COMPASS
- |r| ≥ 0.1 small · |r| ≥ 0.3 medium · |r| ≥ 0.5 large

---

## Observed Results (Scenario 3: Backend Software Engineer, n = 15)

| Metric | COMPASS (Full) | Ablation 3 | p | r | Effect |
|---|---|---|---|---|---|
| Satisfactory Rate | **100.0%** | 46.7% | 0.002\*\* | OR = ∞ | — |
| Feasibility | Mdn = 5.00 | Mdn = 5.00 | 0.008\*\* | +0.40 | medium |
| Level Appropriateness | Mdn = 5.00 | Mdn = 5.00 | 1.000 ns | 0.00 | negligible |
| Gap Coverage | Mdn = 5.00 | Mdn = 5.00 | 0.003\*\* | −0.47 | medium |
| Plan Phases | Mdn = 3.00 | Mdn = 4.00 | 0.038\* | −0.39 | medium |
| Total Actions | Mdn = 3.00 | Mdn = 5.00 | 0.001\*\*\* | −0.70 | large |
| Timeline variance | SD = 1.83 wk | SD = 4.65 wk | 0.005\*\* | F = 9.46 | — |
| Action Specificity | Mdn = 0.21 | Mdn = 0.12 | <0.001\*\*\* | +0.85 | large |
| Resume Terms | Mdn = 19 | Mdn = 11 | <0.001\*\*\* | +0.85 | large |

---

## Troubleshooting

**CSV column misalignment:** If you get unexpected values in plan_phases or other structural columns, the CSV likely mixes rows from two different schema versions. Delete `ablation_metrics.csv` and re-collect from scratch.

**`action_specificity_ratio` is 0:** Resume parsing may have failed. Verify the resume file is valid UTF-8 and contains recognizable skill keywords (Python, React, SQL, etc.). Check that action rationales are non-empty in the final state.

**Satisfactory rate always 0 for ablation3:** Confirm `graph_ablation3.py` exists and is imported correctly in `app/api/runs.py`. The critique node must still run even in the ablation condition for the satisfactory flag to be set.

**Matplotlib deprecation warning on `labels`:** Use `tick_labels` instead of `labels` in `ax.boxplot()` (Matplotlib >= 3.9).

**scipy not found:** `pip install scipy` — required for `stats_analysis.py`.
