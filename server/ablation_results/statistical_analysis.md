# COMPASS Ablation Study — Statistical Analysis
**Conditions:** COMPASS (full, n=15) vs. Ablation 3 (single-pass baseline, n=15)
**Tests:** Fisher's exact (binary); Mann-Whitney U + rank-biserial r (continuous); Levene's (variance)
**Effect size conventions (rank-biserial r):** small >= 0.1 | medium >= 0.3 | large >= 0.5

## 1. Satisfactory Rate (Binary — Fisher's Exact Test)
| Condition | Passes | Rate | 95% CI (Wilson) |
|---|---|---|---|
| COMPASS (full) | 15/15 | 100.0% | [79.6%, 100.0%] |
| Ablation 3 | 7/15 | 46.7% | [24.8%, 69.9%] |

**Fisher's exact test:** OR = inf, p = 0.002 **

## 2. Continuous Metrics — Mann-Whitney U Test
Direction of r: positive = COMPASS > Ablation 3

| Metric | Mdn (COMPASS) | Mdn (Ablation 3) | U | p | Sig | r | Effect |
|---|---|---|---|---|---|---|---|
| Feasibility | 5.00 | 5.00 | 157.5 | 0.008 | ** | 0.400 | medium |
| Level Appropriateness | 5.00 | 5.00 | 112.5 | 1.000 | ns | 0.000 | negligible |
| Gap Coverage | 5.00 | 5.00 | 60.0 | 0.003 | ** | -0.467 | medium |
| Plan Phases | 3.00 | 4.00 | 69.0 | 0.038 | * | -0.387 | medium |
| Total Learning Actions | 3.00 | 5.00 | 34.0 | 0.001 | *** | -0.698 | large |
| Action Specificity Ratio | 0.21 | 0.12 | 208.0 | 0.000 | *** | 0.849 | large |
| Resume Terms Mentioned | 19.00 | 11.00 | 208.0 | 0.000 | *** | 0.849 | large |

## 3. Timeline Variance — Levene's Test
Both conditions share identical mean timelines (14.93 weeks). Levene's test evaluates whether COMPASS reduces variance in timeline scope.

| Condition | SD (weeks) | Range |
|---|---|---|
| COMPASS (full) | 1.83 | [12–16] |
| Ablation 3 | 4.65 | [4–20] |

**Levene's test:** F = 9.459, p = 0.005 **

## 4. Interpretation

- **Feasibility:** COMPASS > Ablation 3, r = 0.400 (medium effect), p = 0.008 **
- **Level Appropriateness:** Ablation 3 > COMPASS, r = 0.000 (negligible effect), p = 1.000 ns
- **Gap Coverage:** Ablation 3 > COMPASS, r = -0.467 (medium effect), p = 0.003 **
- **Plan Phases:** Ablation 3 > COMPASS, r = -0.387 (medium effect), p = 0.038 *
- **Total Learning Actions:** Ablation 3 > COMPASS, r = -0.698 (large effect), p = 0.001 ***
- **Action Specificity Ratio:** COMPASS > Ablation 3, r = 0.849 (large effect), p = 0.000 ***
- **Resume Terms Mentioned:** COMPASS > Ablation 3, r = 0.849 (large effect), p = 0.000 ***

- **Satisfactory Rate:** Fisher's exact p = 0.002 **. COMPASS 95% CI [79.6%–100.0%] vs. Ablation 3 [24.8%–69.9%]. Non-overlapping intervals confirm a significant difference in plan reliability.

- **Timeline variance:** Levene's F = 9.459, p = 0.005 **. COMPASS SD = 1.83 weeks vs. Ablation 3 SD = 4.65 weeks. Significantly different variances — COMPASS produces substantially more consistent timelines.
