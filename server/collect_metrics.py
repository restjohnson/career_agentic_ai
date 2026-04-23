#!/usr/bin/env python3
"""
Collect metrics from multiple runs of the same scenario across conditions.
Calls the FastAPI HTTP API instead of invoking graphs directly.

Usage:
    python collect_metrics.py \\
        --scenario "scenario_3_backend" \\
        --desired-role "Backend Software Engineer" \\
        --resume-file "path/to/resume.txt" \\
        --condition "full" \\
        --runs 5

Requirements:
    - FastAPI server must be running: python -m uvicorn app.main:app --reload
"""

import argparse
import csv
import json
import sys
import requests
import uuid
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import time

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app.state import AgentState
from metrics import extract_metrics_from_state, get_csv_header, metrics_to_csv_row


def run_scenario_via_api(
    desired_role: str,
    resume_text: str,
    condition: str,
    scenario_id: str,
    api_url: str = "http://localhost:8000",
) -> Optional[AgentState]:
    """
    Run a scenario via the FastAPI HTTP API.

    Args:
        desired_role: Student's target role
        resume_text: Raw resume content
        condition: "full" or "ablation3"
        scenario_id: Identifier for this scenario
        api_url: Base URL of the FastAPI server

    Returns:
        Final AgentState after run completes, or None if failed
    """
    # Step 1: Initialize session
    try:
        print(f"  POST /session/start")
        session_response = requests.post(
            f"{api_url}/session/start",
            timeout=10
        )
        session_response.raise_for_status()
        session_data = session_response.json()
        print(f"  Session response: {session_data}")
        session_token = session_data.get("session_token")
        session_id = session_data.get("session_id")
        print(f"  Session created: {session_id}")

    except Exception as e:
        print(f"  [FAIL] Failed to start session: {type(e).__name__}: {e}")
        return None

    # Step 2: Upload resume as evidence document
    evidence_document_ids = []
    try:
        print(f"  POST /evidence (uploading resume)")
        files = {"file": ("resume.txt", resume_text.encode("utf-8"), "text/plain")}
        data = {"source_type": "resume"}
        evidence_response = requests.post(
            f"{api_url}/evidence",
            files=files,
            data=data,
            headers={"Authorization": f"Bearer {session_token}"},
            timeout=30
        )
        evidence_response.raise_for_status()
        evidence_data = evidence_response.json()
        doc_id = evidence_data.get("document_id")
        if doc_id:
            evidence_document_ids.append(doc_id)
            print(f"  Document uploaded: {doc_id}")
        else:
            print(f"  [WARN] No document ID returned")

    except requests.exceptions.HTTPError as e:
        print(f"  [WARN] Failed to upload evidence: {e}")
        if hasattr(e.response, 'text'):
            print(f"     Response: {e.response.text}")
    except Exception as e:
        print(f"  [WARN] Failed to upload evidence: {type(e).__name__}: {e}")

    # Step 3: Create run with Authorization header
    payload = {
        "desired_role": desired_role,
        "raw_user_text": resume_text,
        "evidence_document_ids": evidence_document_ids,
        "student_constraints": {
            "academic_level": "junior",
            "hours_per_week": 15,
            "target_goal": "first_internship",
            "preferred_learning_mode": "project_based",
        },
        "condition": condition,
    }

    headers = {"Authorization": f"Bearer {session_token}"}

    try:
        print(f"  POST /runs")
        response = requests.post(
            f"{api_url}/runs",
            json=payload,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        run_response = response.json()
        run_id = run_response["run_id"]
        print(f"  Created run: {run_id}")

    except requests.exceptions.HTTPError as e:
        print(f"  [FAIL] Failed to create run: {e}")
        if hasattr(e.response, 'text'):
            print(f"     Response: {e.response.text}")
        return None
    except Exception as e:
        print(f"  [FAIL] Failed to create run: {type(e).__name__}: {e}")
        return None

    # Connect to SSE stream and wait for completion
    try:
        print(f"  Listening to SSE stream...")
        stream_url = f"{api_url}/runs/{run_id}/stream"
        stream_response = requests.get(
            stream_url,
            params={"session_id": session_id, "token": session_token},
            headers={"Accept": "text/event-stream"},
            stream=True,
            timeout=300
        )
        if stream_response.status_code != 200:
            print(f"  Stream error response: {stream_response.text}")
        stream_response.raise_for_status()

        final_state = None
        for line in stream_response.iter_lines():
            if not line:
                continue

            line = line.decode("utf-8") if isinstance(line, bytes) else line

            # SSE format: "data: {...}"
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    event_type = event.get("type")

                    if event_type == "done":
                        # Final state received
                        final_state_dict = event.get("final_state")
                        if final_state_dict:
                            final_state = AgentState.model_validate(final_state_dict)
                        print(f"  [OK] Run completed")
                        break

                    elif event_type == "error":
                        print(f"  [ERROR] {event.get('detail')}")

                    elif event_type == "step":
                        step = event.get("step")
                        status = event.get("status")
                        print(f"    - {step}: {status}")

                except json.JSONDecodeError:
                    pass

        return final_state

    except requests.Timeout:
        print(f"  [FAIL] Request timeout (run took too long)")
        return None
    except Exception as e:
        print(f"  [FAIL] Failed to stream results: {type(e).__name__}: {e}")
        return None


def collect_condition_runs(
    scenario_id: str,
    desired_role: str,
    resume_text: str,
    condition: str,
    num_runs: int,
    output_csv: Path,
    api_url: str = "http://localhost:8000",
) -> None:
    """
    Run the same scenario multiple times for a single condition via API.
    Append results to output CSV.

    Args:
        scenario_id: Identifier for this test scenario
        desired_role: Student's target role
        resume_text: Raw resume content
        condition: "full" or "ablation3"
        num_runs: Number of times to run this scenario
        output_csv: Path to CSV file to write/append to
        api_url: Base URL of the FastAPI server
    """
    # Initialize CSV if it doesn't exist
    csv_exists = output_csv.exists()
    mode = 'a' if csv_exists else 'w'

    with open(output_csv, mode, newline='') as f:
        writer = csv.writer(f)

        # Write header if new file
        if not csv_exists:
            writer.writerow(get_csv_header())

        # Run scenario N times
        for attempt in range(1, num_runs + 1):
            print(
                f"\n[{condition.upper()}] Running scenario '{scenario_id}' "
                f"(attempt {attempt}/{num_runs})..."
            )

            try:
                final_state = run_scenario_via_api(
                    desired_role=desired_role,
                    resume_text=resume_text,
                    condition=condition,
                    scenario_id=scenario_id,
                    api_url=api_url,
                )

                if final_state is None:
                    print(f"  [FAIL] Run {attempt} returned no state")
                    continue

                # Extract metrics from final state
                metrics = extract_metrics_from_state(
                    state=final_state,
                    resume_text=resume_text,
                    condition=condition,
                    scenario=scenario_id,
                    attempt=attempt,
                )

                # Write to CSV
                row = metrics_to_csv_row(metrics)
                writer.writerow(row)

                print(f"  [OK] Run {attempt} metrics collected")
                if metrics['has_errors']:
                    print(f"    [WARN] {metrics['error_count']} error(s) logged")

            except Exception as e:
                print(f"  [FAIL] Run {attempt} failed: {type(e).__name__}: {e}")
                # Write error row
                error_metrics = {
                    'timestamp': datetime.now().isoformat(),
                    'run_id': f"{scenario_id}_{condition}_{attempt}_ERROR",
                    'condition': condition,
                    'scenario': scenario_id,
                    'attempt': attempt,
                    'has_errors': True,
                    'error_count': 1,
                }
                error_row = metrics_to_csv_row(error_metrics)
                writer.writerow(error_row)


def main():
    parser = argparse.ArgumentParser(
        description="Collect metrics from multi-run ablation study via HTTP API"
    )
    parser.add_argument(
        "--scenario",
        required=True,
        help="Scenario identifier (e.g., 'scenario_3_backend')",
    )
    parser.add_argument(
        "--desired-role",
        required=True,
        help="Student's target role",
    )
    parser.add_argument(
        "--resume-file",
        type=Path,
        required=True,
        help="Path to resume text file",
    )
    parser.add_argument(
        "--condition",
        required=True,
        choices=["full", "ablation3"],
        help="Which condition to run",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        help="Number of times to run each condition (default: 5)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ablation_metrics.csv"),
        help="Output CSV file (default: ablation_metrics.csv)",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL of FastAPI server (default: http://localhost:8000)",
    )

    args = parser.parse_args()

    # Load resume text
    if not args.resume_file.exists():
        print(f"Error: Resume file not found: {args.resume_file}")
        sys.exit(1)

    resume_text = args.resume_file.read_text()

    print(f"\n{'='*70}")
    print(f"Ablation Study Metrics Collection (via HTTP API)")
    print(f"{'='*70}")
    print(f"Scenario:    {args.scenario}")
    print(f"Role:        {args.desired_role}")
    print(f"Resume:      {args.resume_file}")
    print(f"Condition:   {args.condition}")
    print(f"Runs:        {args.runs}")
    print(f"Output CSV:  {args.output}")
    print(f"API URL:     {args.api_url}")
    print(f"{'='*70}\n")

    # Verify API is reachable
    try:
        requests.get(f"{args.api_url}/session/start", timeout=15)
    except requests.exceptions.ConnectionError:
        print(f"Error: Cannot reach API at {args.api_url}")
        print(f"Make sure the server is running:")
        print(f"  cd server")
        print(f"  python -m uvicorn app.main:app --reload")
        sys.exit(1)

    # Run the scenario collection
    collect_condition_runs(
        scenario_id=args.scenario,
        desired_role=args.desired_role,
        resume_text=resume_text,
        condition=args.condition,
        num_runs=args.runs,
        output_csv=args.output,
        api_url=args.api_url,
    )

    print(f"\n[DONE] Complete! Results saved to {args.output}")


if __name__ == "__main__":
    main()
