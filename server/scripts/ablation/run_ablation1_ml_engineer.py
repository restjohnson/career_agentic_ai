"""
Ablation 1 – LLM-Only Role Spec vs Full COMPASS: API-based runner + matplotlib comparison plotter.

Calls the live COMPASS API server (default http://127.0.0.1:8000) to run both:
  - Full COMPASS  (ablation_mode="none")
  - Ablation 1    (ablation_mode="ablation1_llm_only")

Both conditions receive identical input (role title only) and produce the same
RoleSpecModel output schema. The only controlled difference is whether O*NET
grounding via RAG-Fusion is present.

Each condition is run N times (default 15). Metrics are averaged across all runs
and standard deviations are computed.

Metrics
-------
Layer 1 — Role spec quality (direct comparison):
  - unique_to_full      : requirements Full COMPASS surfaces that LLM-only does not
  - unique_to_ablation  : requirements LLM-only surfaces that Full COMPASS does not
  - category distribution of each unique set

Layer 2 — Downstream impact:
  - known_gap_recall    : fraction of ground-truth gaps appearing in gap_report
                          (returns 0.0 while ground_truth_gaps_ml_engineer.json is empty)

Layer 1 is computed by embedding req_summary strings with text-embedding-3-small
and applying a cosine similarity threshold of 0.85.
Layer 2 uses the same embeddings at threshold 0.80 against the ground truth file.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import openai
import requests
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SERVER_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESUME_PDF = SERVER_ROOT / "scripts" / "test_resume_jordan_hayes.pdf"
DEFAULT_OUT_DIR = SERVER_ROOT / "results" / "ablation"
GROUND_TRUTH_PATH = SERVER_ROOT / "scripts" / "ablation" / "ground_truth_gaps_ml_engineer.json"

SCENARIO_ROLE = "Machine Learning Engineer"

DEFAULT_CONSTRAINTS = {
    "academic_level": "junior",
    "hours_per_week": 12,
    "target_goal": "graduation",
    "preferred_learning_mode": "mixed",
}


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _start_session(base: str) -> Tuple[str, str]:
    resp = requests.post(f"{base}/session/start", timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data["session_token"], data["session_id"]


def _upload_evidence(base: str, token: str, pdf_path: Path) -> str:
    with pdf_path.open("rb") as fh:
        resp = requests.post(
            f"{base}/evidence",
            headers={"Authorization": f"Bearer {token}"},
            data={"source_type": "resume", "consent_level": "derived_only"},
            files={"file": (pdf_path.name, fh, "application/pdf")},
            timeout=60,
        )
    resp.raise_for_status()
    return resp.json()["document_id"]


def _create_run(
    base: str,
    token: str,
    role: str,
    doc_id: str,
    ablation_mode: str,
    constraints: Dict[str, Any],
) -> str:
    resp = requests.post(
        f"{base}/runs",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "desired_role": role,
            "ablation_mode": ablation_mode,
            "bypass_role_cache": True,
            "evidence_document_ids": [doc_id],
            "student_constraints": constraints,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["run_id"]


def _stream_until_done(base: str, token: str, run_id: str, timeout: int = 600) -> Dict[str, Any]:
    url = f"{base}/runs/{run_id}/stream?token={token}"
    deadline = time.time() + timeout

    with requests.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        for raw_line in resp.iter_lines():
            if time.time() > deadline:
                raise TimeoutError(f"SSE stream timed out after {timeout}s for run {run_id}")
            if not raw_line:
                continue
            if isinstance(raw_line, bytes):
                raw_line = raw_line.decode("utf-8")
            if not raw_line.startswith("data:"):
                continue
            payload = json.loads(raw_line[5:].lstrip())
            event_type = payload.get("type", "")
            if event_type == "done":
                return payload["final_state"]
            if event_type == "error":
                raise RuntimeError(f"Run {run_id} failed: {payload.get('detail')}")
            print(".", end="", flush=True)

    raise RuntimeError(f"SSE stream closed without a 'done' event for run {run_id}")


# ---------------------------------------------------------------------------
# Metric extraction from final_state
# ---------------------------------------------------------------------------

def _collect_metrics(final_state: Dict[str, Any], condition: str) -> Dict[str, Any]:
    role_spec = final_state.get("role_spec") or {}
    gap_report = final_state.get("gap_report") or {}
    critique = final_state.get("critique") or {}

    requirements: List[Dict[str, Any]] = role_spec.get("requirements") or []
    gaps: List[Dict[str, Any]] = gap_report.get("gaps") or []
    rubric_scores: Dict[str, Any] = critique.get("rubric_scores") or {}

    return {
        "condition": condition,
        "canonical_role_title": role_spec.get("canonical_role_title"),
        "matched_onet_code": role_spec.get("matched_onet_code"),
        "num_requirements": len(requirements),
        "requirement_categories": sorted({r.get("category", "") for r in requirements}),
        "num_gaps": len(gaps),
        "num_no_evidence_gaps": sum(1 for g in gaps if g.get("gap_type") == "no_evidence"),
        "critique_satisfactory": bool(critique.get("satisfactory", False)),
        "critique_rubric_scores": {str(k): int(v) for k, v in rubric_scores.items()},
        "critique_iterations": int(final_state.get("critique_iterations", 0)),
        "errors": final_state.get("errors") or [],
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

_RUBRIC_DIMS = ["gap_coverage", "jit_compliance", "feasibility", "level_appropriateness"]


def _aggregate_metrics(runs: List[Dict[str, Any]], condition: str) -> Dict[str, Any]:
    if not runs:
        raise ValueError(f"No successful runs to aggregate for condition '{condition}'")

    numeric_keys = ["num_requirements", "num_gaps", "num_no_evidence_gaps", "critique_iterations"]

    agg: Dict[str, Any] = {"condition": condition, "n_runs": len(runs)}

    for key in numeric_keys:
        vals = [float(r[key]) for r in runs if key in r]
        agg[key] = statistics.mean(vals) if vals else 0.0
        agg[f"{key}_std"] = statistics.stdev(vals) if len(vals) > 1 else 0.0

    sat_vals = [float(int(r.get("critique_satisfactory", False))) for r in runs]
    agg["critique_satisfactory"] = statistics.mean(sat_vals) if sat_vals else 0.0
    agg["critique_satisfactory_std"] = statistics.stdev(sat_vals) if len(sat_vals) > 1 else 0.0

    agg["critique_rubric_scores"] = {}
    agg["critique_rubric_scores_std"] = {}
    for dim in _RUBRIC_DIMS:
        vals = [float(r.get("critique_rubric_scores", {}).get(dim, 0)) for r in runs]
        agg["critique_rubric_scores"][dim] = statistics.mean(vals)
        agg["critique_rubric_scores_std"][dim] = statistics.stdev(vals) if len(vals) > 1 else 0.0

    titles = [r.get("canonical_role_title") for r in runs if r.get("canonical_role_title")]
    agg["canonical_role_title"] = max(set(titles), key=titles.count) if titles else None

    cats: set = set()
    for r in runs:
        cats.update(r.get("requirement_categories", []))
    agg["requirement_categories"] = sorted(cats)

    codes = [r.get("matched_onet_code") for r in runs if r.get("matched_onet_code")]
    agg["matched_onet_code"] = max(set(codes), key=codes.count) if codes else None

    agg["individual_runs"] = runs
    return agg


def _aggregate_category_counts(counts_list: List[Dict[str, int]]) -> Dict[str, float]:
    """Average category counts across runs."""
    all_cats: set = set()
    for c in counts_list:
        all_cats.update(c.keys())
    result = {}
    for cat in all_cats:
        vals = [c.get(cat, 0) for c in counts_list]
        result[cat] = statistics.mean(vals)
    return result


# ---------------------------------------------------------------------------
# Layer 1: role spec quality (LLM-as-judge)
# ---------------------------------------------------------------------------

class _Layer1Result(BaseModel):
    unique_to_a: List[str]  # req_summaries from A (Full COMPASS) with no semantic equivalent in B
    unique_to_b: List[str]  # req_summaries from B (Ablation 1) with no semantic equivalent in A


def _layer1_single_pair_llm(
    full_role_spec: Dict[str, Any],
    abl_role_spec: Dict[str, Any],
    llm_client: openai.OpenAI,
) -> Dict[str, Any]:
    """LLM-as-judge: identify requirements unique to each condition for one run pair."""
    reqs_full = full_role_spec.get("requirements") or []
    reqs_abl = abl_role_spec.get("requirements") or []

    summaries_full = [r["req_summary"] for r in reqs_full if r.get("req_summary")]
    summaries_abl = [r["req_summary"] for r in reqs_abl if r.get("req_summary")]

    if not summaries_full or not summaries_abl:
        return {
            "unique_to_full": 0,
            "unique_to_ablation": 0,
            "unique_to_full_by_category": {},
            "unique_to_ablation_by_category": {},
        }

    system = (
        "You are evaluating two Machine Learning Engineer role specifications. "
        "Your task: identify which requirements are genuinely unique to each spec — "
        "meaning they cover a skill or capability with NO semantic equivalent in the other spec. "
        "Two requirements are equivalent if they address the same underlying skill or capability, "
        "even if worded differently. Do not mark requirements as unique just because of phrasing differences.\n\n"
        "Return:\n"
        "- unique_to_a: req_summaries from Spec A that have no equivalent in Spec B\n"
        "- unique_to_b: req_summaries from Spec B that have no equivalent in Spec A\n"
        "Copy the req_summary strings exactly as they appear in the input."
    )

    spec_a = "\n".join(f"{i+1}. {s}" for i, s in enumerate(summaries_full))
    spec_b = "\n".join(f"{i+1}. {s}" for i, s in enumerate(summaries_abl))
    user_msg = f"Spec A (Full COMPASS):\n{spec_a}\n\nSpec B (Ablation 1):\n{spec_b}"

    try:
        response = llm_client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            response_format=_Layer1Result,
            temperature=0,
        )
        result = response.choices[0].message.parsed
        unique_full_summaries = set(result.unique_to_a)
        unique_abl_summaries = set(result.unique_to_b)
    except Exception as exc:
        print(f"  [Layer 1 judge] failed: {exc}. Returning zeros.")
        return {
            "unique_to_full": 0,
            "unique_to_ablation": 0,
            "unique_to_full_by_category": {},
            "unique_to_ablation_by_category": {},
        }

    cat_full: Dict[str, int] = {}
    for r in reqs_full:
        if r.get("req_summary") in unique_full_summaries:
            cat = r.get("category", "unknown")
            cat_full[cat] = cat_full.get(cat, 0) + 1

    cat_abl: Dict[str, int] = {}
    for r in reqs_abl:
        if r.get("req_summary") in unique_abl_summaries:
            cat = r.get("category", "unknown")
            cat_abl[cat] = cat_abl.get(cat, 0) + 1

    return {
        "unique_to_full": len(unique_full_summaries),
        "unique_to_ablation": len(unique_abl_summaries),
        "unique_to_full_by_category": cat_full,
        "unique_to_ablation_by_category": cat_abl,
    }


def _layer1_aggregated(
    full_states: List[Dict[str, Any]],
    abl_states: List[Dict[str, Any]],
    llm_client: openai.OpenAI,
) -> Dict[str, Any]:
    n_pairs = min(len(full_states), len(abl_states))
    print(f"\n[Layer 1] Computing role spec delta across {n_pairs} run pairs (LLM-as-judge)...")
    results = []
    for i in range(n_pairs):
        r = _layer1_single_pair_llm(
            full_states[i].get("role_spec") or {},
            abl_states[i].get("role_spec") or {},
            llm_client,
        )
        results.append(r)
        print(f"  pair {i+1}/{n_pairs}: unique_to_full={r['unique_to_full']}, unique_to_ablation={r['unique_to_ablation']}")

    if not results:
        return {}

    utf_vals = [r["unique_to_full"] for r in results]
    uta_vals = [r["unique_to_ablation"] for r in results]

    return {
        "n_pairs": n_pairs,
        "unique_to_full_mean": statistics.mean(utf_vals),
        "unique_to_full_std": statistics.stdev(utf_vals) if len(utf_vals) > 1 else 0.0,
        "unique_to_ablation_mean": statistics.mean(uta_vals),
        "unique_to_ablation_std": statistics.stdev(uta_vals) if len(uta_vals) > 1 else 0.0,
        "unique_to_full_by_category": _aggregate_category_counts(
            [r["unique_to_full_by_category"] for r in results]
        ),
        "unique_to_ablation_by_category": _aggregate_category_counts(
            [r["unique_to_ablation_by_category"] for r in results]
        ),
    }


# ---------------------------------------------------------------------------
# Verma et al. (2022) ML occupational skill buckets — Layer 2 ground truth
# Top-5 occupational skills for ML positions (Table 5, 1,700 Indeed.com job ads)
# ---------------------------------------------------------------------------

VERMA_BUCKETS: Dict[str, Dict[str, str]] = {
    "data_mining": {
        "label": "Data Mining",
        "pct": "98%",
        "description": (
            "ML algorithms and modeling techniques: classification, regression, prediction, "
            "forecasting, anomaly detection, clustering, text mining, web mining, stream mining, "
            "knowledge discovery, decision trees, association rules, outlier detection"
        ),
    },
    "decision_making": {
        "label": "Decision Making",
        "pct": "87%",
        "description": (
            "Analytical thinking and insight generation: reporting, analysis, business problem "
            "framing, strategic thinking, synthesizing findings, drawing conclusions, "
            "data-driven recommendations, stakeholder communication"
        ),
    },
    "programming": {
        "label": "Programming",
        "pct": "83%",
        "description": (
            "Software programming skills: Python, R, Scala, Java, C++, BASH, SQL, "
            "software development, coding, scripting, version control, software engineering"
        ),
    },
    "statistics": {
        "label": "Statistics",
        "pct": "59%",
        "description": (
            "Applied statistical methods: probability, hypothesis testing, regression analysis, "
            "experimental design, A/B testing, Bayesian methods, statistical modeling, "
            "SPSS, SAS, MATLAB, pandas, NumPy, SciPy"
        ),
    },
    "big_data": {
        "label": "Big Data",
        "pct": "39%",
        "description": (
            "Big data processing and infrastructure: Hadoop, Spark, MapReduce, Hive, Pig, "
            "Kafka, NoSQL, distributed computing, data pipelines, cloud data platforms, "
            "unstructured data at scale"
        ),
    },
}

VERMA_BUCKET_KEYS: List[str] = list(VERMA_BUCKETS.keys())
VERMA_BUCKET_NONE = "none"


class _BucketLabel(BaseModel):
    bucket: str


class _ClassificationList(BaseModel):
    classifications: List[_BucketLabel]


def _classify_into_verma_buckets(
    texts: List[str],
    llm_client: openai.OpenAI,
) -> List[str]:
    """
    LLM-as-judge: assign each text to exactly one Verma bucket or 'none'.
    Returns a list of bucket keys, same length and order as texts.
    """
    if not texts:
        return []

    bucket_desc = "\n".join(
        f"- {key} ({v['label']}, {v['pct']} of ML jobs): {v['description']}"
        for key, v in VERMA_BUCKETS.items()
    )
    valid_values = ", ".join(VERMA_BUCKET_KEYS + [VERMA_BUCKET_NONE])

    system = (
        "You are a skill classifier for Machine Learning Engineer job requirements, "
        "using the taxonomy from Verma et al. (2022) — an empirical analysis of "
        "1,700 ML job advertisements on Indeed.com.\n\n"
        "Classify each input into EXACTLY ONE of the following categories, "
        "or 'none' if it does not clearly fit any. One label per input. No combining.\n\n"
        f"Categories:\n{bucket_desc}\n\n"
        f"Valid labels: {valid_values}\n\n"
        "Return one classification per input in the same order as the input list."
    )

    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))

    try:
        response = llm_client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": numbered},
            ],
            response_format=_ClassificationList,
            temperature=0,
        )
        raw = response.choices[0].message.parsed.classifications
        result = []
        for item in raw:
            b = item.bucket.lower().strip()
            result.append(b if b in VERMA_BUCKET_KEYS else VERMA_BUCKET_NONE)
        while len(result) < len(texts):
            result.append(VERMA_BUCKET_NONE)
        return result[: len(texts)]
    except Exception as exc:
        print(f"  [Verma judge] failed: {exc}")
        return [VERMA_BUCKET_NONE] * len(texts)


def _verma_role_spec_counts(
    role_spec: Dict[str, Any],
    llm_client: openai.OpenAI,
) -> Dict[str, int]:
    """Classify role_spec requirements into Verma buckets. Returns bucket -> count."""
    reqs = (role_spec or {}).get("requirements") or []
    summaries = [r["req_summary"] for r in reqs if r.get("req_summary")]
    counts: Dict[str, int] = {k: 0 for k in VERMA_BUCKET_KEYS}
    if not summaries:
        return counts
    labels = _classify_into_verma_buckets(summaries, llm_client)
    for label in labels:
        if label in counts:
            counts[label] += 1
    return counts


def _verma_gap_recall_single(
    gap_report: Dict[str, Any],
    absent_buckets: List[str],
    llm_client: openai.OpenAI,
) -> float:
    """
    Recall = fraction of absent Verma buckets detected in gap_report.
    A bucket is detected if at least one gap maps to it.
    """
    if not absent_buckets:
        return 0.0
    gaps = (gap_report or {}).get("gaps") or []
    summaries = [g["summary"] for g in gaps if g.get("summary")]
    if not summaries:
        return 0.0
    labels = _classify_into_verma_buckets(summaries, llm_client)
    detected = set(labels) & set(absent_buckets)
    return len(detected) / len(absent_buckets)


def _verma_aggregated(
    condition_states: List[Dict[str, Any]],
    absent_buckets: List[str],
    llm_client: openai.OpenAI,
    condition_name: str,
) -> Dict[str, Any]:
    """
    Per run: classify role_spec requirements into Verma buckets + compute gap recall.
    Returns aggregated means and stds across all runs.
    """
    role_spec_counts_list: List[Dict[str, int]] = []
    recall_list: List[float] = []

    for i, state in enumerate(condition_states):
        counts = _verma_role_spec_counts(state.get("role_spec") or {}, llm_client)
        role_spec_counts_list.append(counts)

        recall = _verma_gap_recall_single(
            state.get("gap_report") or {}, absent_buckets, llm_client
        )
        recall_list.append(recall)

        print(
            f"  [{condition_name}] run {i + 1}: recall={recall:.2f} | "
            + " ".join(f"{k}={v}" for k, v in counts.items())
        )

    result: Dict[str, Any] = {}

    result["role_spec_bucket_means"] = {}
    result["role_spec_bucket_stds"] = {}
    for k in VERMA_BUCKET_KEYS:
        vals = [c[k] for c in role_spec_counts_list]
        result["role_spec_bucket_means"][k] = statistics.mean(vals)
        result["role_spec_bucket_stds"][k] = statistics.stdev(vals) if len(vals) > 1 else 0.0

    result["gap_recall_mean"] = statistics.mean(recall_list)
    result["gap_recall_std"] = statistics.stdev(recall_list) if len(recall_list) > 1 else 0.0

    return result


def _load_absent_buckets(path: Path) -> List[str]:
    """Load absent Verma bucket keys from the ground truth JSON file."""
    if not path.exists():
        print(f"[Verma] Ground truth file not found at {path}. Recall will be 0.0.")
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [entry["bucket"] for entry in data.get("absent_buckets") or []]


# ---------------------------------------------------------------------------
# Run one condition end-to-end
# ---------------------------------------------------------------------------

def _run_condition_via_api(
    *,
    base: str,
    condition_name: str,
    ablation_mode: str,
    role: str,
    pdf_path: Path,
    constraints: Dict[str, Any],
    stream_timeout: int = 600,
) -> Dict[str, Any]:
    print(f"\n[{condition_name}] Starting session...", end=" ", flush=True)
    token, session_id = _start_session(base)
    print(f"session_id={session_id}")

    print(f"[{condition_name}] Uploading resume...", end=" ", flush=True)
    doc_id = _upload_evidence(base, token, pdf_path)
    print(f"doc_id={doc_id}")

    print(f"[{condition_name}] Creating run (ablation_mode={ablation_mode!r})...", end=" ", flush=True)
    run_id = _create_run(base, token, role, doc_id, ablation_mode, constraints)
    print(f"run_id={run_id}")

    print(f"[{condition_name}] Streaming ", end="", flush=True)
    final_state = _stream_until_done(base, token, run_id, timeout=stream_timeout)
    print(" done.")

    metrics = _collect_metrics(final_state, condition=condition_name)
    return {"metrics": metrics, "final_state": final_state}


def _run_condition_n_times(
    *,
    base: str,
    n: int,
    condition_name: str,
    ablation_mode: str,
    role: str,
    pdf_path: Path,
    constraints: Dict[str, Any],
    stream_timeout: int = 600,
) -> Dict[str, Any]:
    individual_metrics: List[Dict[str, Any]] = []
    individual_final_states: List[Dict[str, Any]] = []

    for i in range(1, n + 1):
        print(f"\n[{condition_name}] -- Run {i}/{n} --")
        try:
            result = _run_condition_via_api(
                base=base,
                condition_name=condition_name,
                ablation_mode=ablation_mode,
                role=role,
                pdf_path=pdf_path,
                constraints=constraints,
                stream_timeout=stream_timeout,
            )
            individual_metrics.append(result["metrics"])
            individual_final_states.append(result["final_state"])
            print(
                f"[{condition_name}] Run {i} complete – "
                f"reqs={result['metrics']['num_requirements']}, "
                f"gaps={result['metrics']['num_gaps']}, "
                f"satisfactory={result['metrics']['critique_satisfactory']}"
            )
        except Exception as exc:
            print(f"[{condition_name}] WARNING: run {i} failed – {exc}. Skipping.")

    if not individual_metrics:
        raise RuntimeError(f"All {n} runs failed for condition '{condition_name}'")

    print(f"\n[{condition_name}] Aggregating {len(individual_metrics)} successful run(s)...")
    aggregated = _aggregate_metrics(individual_metrics, condition=condition_name)
    return {"aggregated": aggregated, "individual_final_states": individual_final_states}


# ---------------------------------------------------------------------------
# Persist results
# ---------------------------------------------------------------------------

def _write_results(out_dir: Path, payload: Dict[str, Any]) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = out_dir / f"ablation1_ml_engineer_{ts}.json"
    csv_path = out_dir / f"ablation1_ml_engineer_{ts}.csv"

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    csv_headers = [
        "condition", "n_runs", "canonical_role_title", "matched_onet_code",
        "num_requirements_mean", "num_requirements_std",
        "num_gaps_mean", "num_gaps_std",
        "num_no_evidence_gaps_mean", "num_no_evidence_gaps_std",
        "critique_satisfactory_rate", "critique_satisfactory_std",
        "critique_iterations_mean", "critique_iterations_std",
        "unique_to_full_mean", "unique_to_full_std",
        "unique_to_ablation_mean", "unique_to_ablation_std",
        "known_gap_recall_mean", "known_gap_recall_std",
        "requirement_categories",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_headers)
        writer.writeheader()
        for agg in payload["aggregated_results"]:
            l1 = payload.get("layer1_metrics") or {}
            cond = agg["condition"]
            writer.writerow({
                "condition": cond,
                "n_runs": agg["n_runs"],
                "canonical_role_title": agg.get("canonical_role_title"),
                "matched_onet_code": agg.get("matched_onet_code"),
                "num_requirements_mean": round(agg["num_requirements"], 3),
                "num_requirements_std": round(agg.get("num_requirements_std", 0), 3),
                "num_gaps_mean": round(agg["num_gaps"], 3),
                "num_gaps_std": round(agg.get("num_gaps_std", 0), 3),
                "num_no_evidence_gaps_mean": round(agg["num_no_evidence_gaps"], 3),
                "num_no_evidence_gaps_std": round(agg.get("num_no_evidence_gaps_std", 0), 3),
                "critique_satisfactory_rate": round(agg["critique_satisfactory"], 3),
                "critique_satisfactory_std": round(agg.get("critique_satisfactory_std", 0), 3),
                "critique_iterations_mean": round(agg["critique_iterations"], 3),
                "critique_iterations_std": round(agg.get("critique_iterations_std", 0), 3),
                "unique_to_full_mean": round(l1.get("unique_to_full_mean", 0), 3) if cond == "full_compass" else "",
                "unique_to_full_std": round(l1.get("unique_to_full_std", 0), 3) if cond == "full_compass" else "",
                "unique_to_ablation_mean": round(l1.get("unique_to_ablation_mean", 0), 3) if cond == "full_compass" else "",
                "unique_to_ablation_std": round(l1.get("unique_to_ablation_std", 0), 3) if cond == "full_compass" else "",
                "known_gap_recall_mean": round(agg.get("known_gap_recall_mean", 0), 3),
                "known_gap_recall_std": round(agg.get("known_gap_recall_std", 0), 3),
                "requirement_categories": "|".join(agg.get("requirement_categories", [])),
            })

    return {"json": json_path, "csv": csv_path}


# ---------------------------------------------------------------------------
# matplotlib comparison chart (4-panel)
# ---------------------------------------------------------------------------

def _condition_label(value: str) -> str:
    return {
        "full_compass": "Full COMPASS",
        "ablation1_llm_only": "Ablation 1 (LLM-only)",
    }.get(value, value)


def _plot(
    aggregated_list: List[Dict[str, Any]],
    layer1: Dict[str, Any],
    verma_full: Dict[str, Any],
    verma_abl1: Dict[str, Any],
    scenario_role: str,
    output_path: Path,
    n_runs: int,
) -> None:
    labeled: Dict[str, Dict[str, Any]] = {
        _condition_label(m["condition"]): m for m in aggregated_list
    }
    conditions = ["Full COMPASS", "Ablation 1 (LLM-only)"]
    colors = ["#1f77b4", "#d62728"]
    ecolor = ["#0d4f8c", "#8b1a1a"]

    fig = plt.figure(figsize=(17, 13), constrained_layout=True)
    grid = fig.add_gridspec(2, 2)
    ax_delta = fig.add_subplot(grid[0, 0])
    ax_cat = fig.add_subplot(grid[0, 1])
    ax_recall = fig.add_subplot(grid[1, 0])
    ax_status = fig.add_subplot(grid[1, 1])

    # ----- Panel 1: Unique coverage delta -----
    delta_labels = ["Unique to\nFull COMPASS", "Unique to\nAblation 1"]
    delta_means = [layer1.get("unique_to_full_mean", 0), layer1.get("unique_to_ablation_mean", 0)]
    delta_stds = [layer1.get("unique_to_full_std", 0), layer1.get("unique_to_ablation_std", 0)]
    delta_colors = [colors[0], colors[1]]
    bars = ax_delta.bar(
        delta_labels, delta_means, color=delta_colors,
        yerr=delta_stds, capsize=6, error_kw={"ecolor": "#333333", "elinewidth": 1.5},
    )
    ax_delta.bar_label(bars, labels=[f"{v:.1f}" for v in delta_means], padding=5, fontsize=11)
    ax_delta.set_title("Unique Coverage Delta", fontsize=14, fontweight="bold")
    ax_delta.set_ylabel(f"Req count  (mean ± SD, N={n_runs})", fontsize=12)
    ax_delta.set_ylim(0, max(delta_means) * 1.5 + 2)
    ax_delta.tick_params(axis="both", labelsize=12)
    ax_delta.text(
        0.01, 0.98,
        "Requirements each condition surfaces\nthat the other does not (LLM-as-judge).",
        transform=ax_delta.transAxes, va="top", fontsize=10,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#cccccc"},
    )

    # ----- Panel 2: Category distribution of delta -----
    all_cats = sorted(
        set(layer1.get("unique_to_full_by_category", {}).keys()) |
        set(layer1.get("unique_to_ablation_by_category", {}).keys())
    )
    if all_cats:
        x = np.arange(len(all_cats))
        width = 0.35
        full_vals = [layer1.get("unique_to_full_by_category", {}).get(c, 0) for c in all_cats]
        abl_vals = [layer1.get("unique_to_ablation_by_category", {}).get(c, 0) for c in all_cats]
        b1 = ax_cat.bar(x - width / 2, full_vals, width, color=colors[0], label="Full COMPASS")
        b2 = ax_cat.bar(x + width / 2, abl_vals, width, color=colors[1], label="Ablation 1")
        ax_cat.bar_label(b1, labels=[f"{v:.1f}" for v in full_vals], padding=3, fontsize=9)
        ax_cat.bar_label(b2, labels=[f"{v:.1f}" for v in abl_vals], padding=3, fontsize=9)
        ax_cat.set_xticks(x, all_cats, rotation=20, ha="right")
        ax_cat.legend(frameon=False, fontsize=10)
    else:
        ax_cat.text(0.5, 0.5, "No unique requirements detected", ha="center", va="center", fontsize=12)
    ax_cat.set_title("Category Distribution of Delta", fontsize=14, fontweight="bold")
    ax_cat.set_ylabel(f"Count  (mean, N={n_runs})", fontsize=12)
    ax_cat.tick_params(axis="both", labelsize=12)
    ax_cat.text(
        0.01, 0.98,
        "Which requirement types each condition\nuniquely surfaces.",
        transform=ax_cat.transAxes, va="top", fontsize=10,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#cccccc"},
    )

    # ----- Panel 3: Verma gap recall -----
    recall_means = [
        verma_full.get("gap_recall_mean", 0),
        verma_abl1.get("gap_recall_mean", 0),
    ]
    recall_stds = [
        verma_full.get("gap_recall_std", 0),
        verma_abl1.get("gap_recall_std", 0),
    ]
    recall_bars = ax_recall.bar(
        conditions, recall_means, color=colors,
        yerr=recall_stds, capsize=6, error_kw={"ecolor": "#333333", "elinewidth": 1.5},
    )
    ax_recall.bar_label(recall_bars, labels=[f"{v*100:.0f}%" for v in recall_means], padding=5, fontsize=11)
    ax_recall.set_ylim(0, 1.35)
    ax_recall.set_yticks(np.arange(0, 1.2, 0.2))
    ax_recall.set_yticklabels([f"{v*100:.0f}%" for v in np.arange(0, 1.2, 0.2)])
    ax_recall.set_title("Gap Recall", fontsize=14, fontweight="bold")
    ax_recall.set_ylabel(f"Recall  (N={n_runs} runs)", fontsize=12)
    ax_recall.tick_params(axis="both", labelsize=12)
    ax_recall.text(
        0.01, 0.98,
        "Fraction of absent skill buckets detected\nin gap_report (statistics, big_data, decision_making).",
        transform=ax_recall.transAxes, va="top", fontsize=10,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#cccccc"},
    )

    # ----- Panel 4: Satisfactory run rate -----
    sat_means = [labeled[c]["critique_satisfactory"] for c in conditions]
    sat_stds = [labeled[c].get("critique_satisfactory_std", 0) for c in conditions]
    sat_bars = ax_status.bar(
        conditions, sat_means, color=colors,
        yerr=sat_stds, capsize=6, error_kw={"ecolor": "#333333", "elinewidth": 1.5},
    )
    ax_status.bar_label(sat_bars, labels=[f"{v*100:.0f}%" for v in sat_means], padding=5, fontsize=11)
    ax_status.set_ylim(0, 1.35)
    ax_status.set_yticks(np.arange(0, 1.2, 0.2))
    ax_status.set_yticklabels([f"{v*100:.0f}%" for v in np.arange(0, 1.2, 0.2)])
    ax_status.set_title("Satisfactory Run Rate", fontsize=14, fontweight="bold")
    ax_status.set_ylabel(f"Fraction satisfactory  (N={n_runs} runs)", fontsize=12)
    ax_status.tick_params(axis="both", labelsize=12)
    ax_status.text(
        0.01, 0.98,
        f"Full COMPASS: {sat_means[0]*100:.0f}% satisfactory\n"
        f"Ablation 1:   {sat_means[1]*100:.0f}% satisfactory",
        transform=ax_status.transAxes, va="top", fontsize=10,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85, "edgecolor": "#cccccc"},
    )

    fig.suptitle(
        f"{n_runs}-Run Average: Ablation 1 (LLM-only) vs Full COMPASS  ·  {scenario_role}\n"
        "Full COMPASS: O*NET-grounded RAG-Fusion + LLM curation  ·  "
        "Ablation 1: LLM parametric knowledge only",
        fontsize=15, fontweight="bold",
    )
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Chart saved -> {output_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run Ablation 1 (LLM-only) vs Full COMPASS N times each via the live API, "
            "average the metrics, and generate a matplotlib comparison chart."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--role", default=SCENARIO_ROLE)
    parser.add_argument("--resume", type=Path, default=DEFAULT_RESUME_PDF)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--n-runs", type=int, default=15)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    if not args.resume.exists():
        print(f"ERROR: Resume PDF not found at {args.resume}", file=sys.stderr)
        sys.exit(1)

    base = args.base_url.rstrip("/")

    try:
        requests.get(f"{base}/health", timeout=5).raise_for_status()
    except Exception as exc:
        print(f"ERROR: API server not reachable at {base} – {exc}", file=sys.stderr)
        sys.exit(1)

    client = openai.OpenAI()
    absent_buckets = _load_absent_buckets(GROUND_TRUTH_PATH)
    if absent_buckets:
        print(f"[Verma] Absent buckets (ground truth): {absent_buckets}")

    print(f"\n{'='*60}")
    print(f"  Ablation 1 Experiment  --  {args.n_runs} runs per condition")
    print(f"  Role: {args.role}")
    print(f"{'='*60}\n")

    print(f"=== Full COMPASS  ({args.n_runs} runs) ===")
    full = _run_condition_n_times(
        base=base, n=args.n_runs, condition_name="full_compass",
        ablation_mode="none", role=args.role, pdf_path=args.resume,
        constraints=DEFAULT_CONSTRAINTS, stream_timeout=args.timeout,
    )

    print(f"\n=== Ablation 1 — LLM-only  ({args.n_runs} runs) ===")
    abl1 = _run_condition_n_times(
        base=base, n=args.n_runs, condition_name="ablation1_llm_only",
        ablation_mode="ablation1_llm_only", role=args.role, pdf_path=args.resume,
        constraints=DEFAULT_CONSTRAINTS, stream_timeout=args.timeout,
    )

    # Layer 1: role spec delta
    layer1 = _layer1_aggregated(
        full["individual_final_states"],
        abl1["individual_final_states"],
        client,
    )

    # Layer 2: Verma bucket coverage — role spec fill + gap recall
    print(f"\n[Verma] Classifying Full COMPASS ({len(full['individual_final_states'])} runs)...")
    full_verma = _verma_aggregated(
        full["individual_final_states"], absent_buckets, client, "full_compass"
    )
    print(f"\n[Verma] Classifying Ablation 1 ({len(abl1['individual_final_states'])} runs)...")
    abl1_verma = _verma_aggregated(
        abl1["individual_final_states"], absent_buckets, client, "ablation1_llm_only"
    )

    full_agg = full["aggregated"]
    abl1_agg = abl1["aggregated"]
    full_agg["verma"] = full_verma
    abl1_agg["verma"] = abl1_verma

    print(f"\n{'='*60}")
    print("  Aggregated Results Summary")
    print(f"{'='*60}")
    for agg in [full_agg, abl1_agg]:
        verma = agg.get("verma") or {}
        print(
            f"  {agg['condition']:40s}"
            f"  reqs={agg['num_requirements']:.1f}+/-{agg.get('num_requirements_std',0):.1f}"
            f"  gaps={agg['num_gaps']:.1f}+/-{agg.get('num_gaps_std',0):.1f}"
            f"  sat={agg['critique_satisfactory']*100:.0f}%"
            f"  verma_recall={verma.get('gap_recall_mean',0)*100:.0f}%"
        )
    print(f"\n  Layer 1 delta (mean over {layer1.get('n_pairs',0)} pairs):")
    print(f"    unique_to_full={layer1.get('unique_to_full_mean',0):.1f}+/-{layer1.get('unique_to_full_std',0):.1f}")
    print(f"    unique_to_ablation={layer1.get('unique_to_ablation_mean',0):.1f}+/-{layer1.get('unique_to_ablation_std',0):.1f}")

    payload = {
        "experiment": "ablation1_llm_only_vs_full_compass",
        "n_runs_per_condition": args.n_runs,
        "scenario": {
            "role": args.role,
            "resume_path": str(args.resume),
            "constraints": DEFAULT_CONSTRAINTS,
        },
        "layer1_metrics": layer1,
        "aggregated_results": [full_agg, abl1_agg],
        "individual_final_states": {
            "full_compass": full["individual_final_states"],
            "ablation1_llm_only": abl1["individual_final_states"],
        },
    }

    paths = _write_results(args.out_dir, payload)
    print(f"\nResults saved -> JSON: {paths['json']}")
    print(f"               CSV:  {paths['csv']}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    png_path = args.out_dir / f"ablation1_ml_engineer_{ts}.png"
    _plot(
        aggregated_list=[full_agg, abl1_agg],
        layer1=layer1,
        verma_full=full_verma,
        verma_abl1=abl1_verma,
        scenario_role=args.role,
        output_path=png_path,
        n_runs=args.n_runs,
    )

    print(f"\nAblation experiment complete ({args.n_runs} runs per condition).")


if __name__ == "__main__":
    main()
