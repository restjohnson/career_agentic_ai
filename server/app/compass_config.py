"""
compass_config.py — every tunable value in the COMPASS pipeline, in one place.

Nothing in this module should be duplicated as a literal anywhere else in the
codebase (see COMPASS_Implementation_Spec.md §9). This is what the eventual
sensitivity analysis perturbs.
"""
from __future__ import annotations

# --- Stage 2: evidence ---
TYPE_WEIGHTS = {"experience": 3.0, "project": 2.0, "coursework": 1.0, "claim": 0.25}
QUALITY_SCALE = [0.90, 0.70, 0.50, 0.30, 0.10]          # strong .. marginal
RELEVANCE_SCALE = [0.90, 0.70, 0.50, 0.30, 0.10, 0.0]   # direct .. none

# --- Stage 3: candidate filtering ---
CANDIDATE_PREFILTER_SIMILARITY = 0.3
# Below this embedding similarity, an (item, requirement) pair is dropped
# before relevance rating and never rated. Biased toward recall over
# precision — deliberately: a missed true match silently starves a
# posterior, while an unnecessary rating call only costs tokens. Not yet
# validated against this embedding model's behavior on career-domain text
# (spec §9) — revisit with a labelled validation set before trusting it.

# --- Stage 3: aggregation ---
PRIOR_ALPHA = 1.0
PRIOR_BETA = 3.0
PRIOR_MASS = PRIOR_ALPHA + PRIOR_BETA  # 4.0

# depth -> demanded quality level -> threshold at the midpoint below it.
# The ONE permitted depth-to-quality map. Both p_met and the omega
# numerator must use this; no second (e.g. linear) map is permitted.
DEPTH_THRESHOLDS = [0.05, 0.20, 0.40, 0.60]

MET_THRESHOLD = 0.75        # p_met above this -> met
UNMET_THRESHOLD = 0.25      # p_met at or below this -> unmet
UNCERTAIN_MASS_GATE = PRIOR_MASS

CAPACITY_DISCOUNT = 0.70
DIAGNOSTIC_COST = {"artifact_submission": 0.5, "external_validation": 8.0}  # hours
EXTERNAL_VALIDATION_IMPORTANCE = 4  # importance at or above this warrants the costly form

# --- Stage 1: retrieval ---
RRF_K = 60
SUBQUERY_MIN, SUBQUERY_MAX = 3, 5
DEDUP_SIMILARITY = 0.90     # cosine similarity above which candidates collapse
TOP_K_POSTINGS = 5          # postings entering the requirement prompt as examples

# --- Stage 4: planning ---
PHASE_MIN, PHASE_MAX = 3, 6

NOVELTY_V_MAX = 0.1994
# DERIVED, not chosen: the largest attainable value of sqrt(Beta variance)
# under Beta(1,3), taken at the system's actual quality ceiling (0.90,
# "Strong"), reached at mass ~= 0.618. Do not change without changing the
# prior — see spec §4 for why 1.0 as the ceiling (an earlier, wrong
# derivation) gives 0.2013 instead.
COUPLING_ETA = 0.50         # initial value; maximal coupling inflates load by 50%

# Load bounds are RELATIVE to the plan's own mean phase load, not absolute.
LOAD_MIN_RATIO = 0.60
LOAD_MAX_RATIO = 1.60

# --- Stage 5: quality check ---
MAX_ITERATIONS = 3

# UNSET per spec §9 -> set deliberately once the pipeline produces output on
# real scenarios; the placeholder of 3 lets the critique loop run without
# scattering ad hoc defaults through the code. Revisit in one commit, with
# the reasoning recorded, before relying on these for real feedback.
CRITERION_THRESHOLDS = {
    "coverage": 3,
    "realistic_effort": 3,
    "gradual_build": 3,
    "calibration": 3,
    "checkin_placement": 3,
}

# --- model ---
MODEL = "gpt-4o-mini"            # planner and all other calls
TEMPERATURE = 0.4
JUDGE_MODEL = "gpt-5-mini"       # calibration only; must differ from MODEL
JUDGE_TEMPERATURE = 0.0          # if the API rejects 0, fall back to JUDGE_VOTES
JUDGE_VOTES = 3                  # majority verdict per facet when temperature 0 is unavailable
RESOURCE_CACHE_DAYS = 30
