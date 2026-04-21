#!/usr/bin/env python3
"""Baseline inference script for the Incident Response environment.

Supports two modes:
  1. LLM mode (default): Uses OpenAI API to run a model agent.
     OPENAI_API_KEY=sk-... python baseline.py

  2. Expert mode: Uses a hardcoded expert policy (no API key needed).
     python baseline.py --expert
"""

from __future__ import annotations

import json
import os
import sys
import time

import requests

ENV_URL = os.getenv("ENV_URL", "http://localhost:8000")
MODEL = os.getenv("MODEL", "gpt-4o-mini")

TASK_IDS = ["easy_db_pool", "medium_cache_cascade", "hard_payment_corruption"]

SYSTEM_PROMPT = """\
You are an expert SRE (Site Reliability Engineer) responding to a production incident.
You must investigate the incident by checking alerts, reading logs, checking metrics, and running commands.
Then diagnose the root cause and resolve the incident.

You interact with the environment by outputting a JSON action. Available action types:
- check_alerts: View active alerts. No extra fields needed.
- read_logs: Read service logs. Requires "service" field.
- check_metrics: Check service metrics. Requires "service" field.
- run_command: Run a diagnostic/remediation command. Requires "command" field.
- escalate: Escalate to a team. Requires "team" field.
- communicate: Send a status update. Requires "message" field.
- resolve: Attempt to resolve the incident. Requires "root_cause" and "remediation" fields.

IMPORTANT: Respond with ONLY a valid JSON object. No explanation, no markdown, just JSON.

Example actions:
{"action_type": "check_alerts"}
{"action_type": "read_logs", "service": "api-gateway"}
{"action_type": "check_metrics", "service": "database"}
{"action_type": "run_command", "command": "restart api-gateway"}
{"action_type": "escalate", "team": "database"}
{"action_type": "communicate", "message": "Investigating elevated error rates on api-gateway"}
{"action_type": "resolve", "root_cause": "connection pool exhausted due to slow analytics query from v2.14.3 deploy", "remediation": "rollback to v2.14.2 and kill long-running query"}
"""

# ── Expert (hardcoded) policies per task ──────────────────────────────────────

EXPERT_POLICIES = {
    "easy_db_pool": [
        {"action_type": "check_alerts"},
        {"action_type": "read_logs", "service": "api-gateway"},
        {"action_type": "read_logs", "service": "database"},
        {"action_type": "check_metrics", "service": "api-gateway"},
        {"action_type": "run_command", "command": "show connections api-gateway"},
        {"action_type": "communicate", "message": "Investigating api-gateway 500s. Connection pool exhausted — likely caused by slow analytics query in v2.14.3 deploy."},
        {"action_type": "escalate", "team": "database"},
        {"action_type": "run_command", "command": "rollback api-gateway 2.14.2"},
        {"action_type": "resolve", "root_cause": "Connection pool exhaustion caused by slow analytics query introduced in v2.14.3 deploy", "remediation": "Rollback api-gateway to v2.14.2 and kill long-running query"},
    ],
    "medium_cache_cascade": [
        {"action_type": "check_alerts"},
        {"action_type": "read_logs", "service": "redis-cluster"},
        {"action_type": "read_logs", "service": "user-service"},
        {"action_type": "read_logs", "service": "product-service"},
        {"action_type": "read_logs", "service": "database"},
        {"action_type": "check_metrics", "service": "redis-cluster"},
        {"action_type": "run_command", "command": "redis-restart redis-03"},
        {"action_type": "run_command", "command": "enable-rate-limit user-service"},
        {"action_type": "escalate", "team": "infrastructure"},
        {"action_type": "communicate", "message": "Redis-03 OOM caused cluster degradation. Thundering herd to DB. Restarting redis-03 and enabling rate limits."},
        {"action_type": "resolve", "root_cause": "Redis node redis-03 ran OOM causing cache failure and thundering herd to database", "remediation": "Restarted redis-03 with increased memory, enabled rate-limiting on affected services"},
    ],
    "hard_payment_corruption": [
        {"action_type": "check_alerts"},
        {"action_type": "read_logs", "service": "payment-processor"},
        {"action_type": "read_logs", "service": "payment-db"},
        {"action_type": "read_logs", "service": "message-queue"},
        {"action_type": "check_metrics", "service": "payment-processor"},
        {"action_type": "check_metrics", "service": "payment-db"},
        {"action_type": "communicate", "message": "P1: Payment duplication and missing transactions. Schema migration in v3.8.0 did not propagate to replica-2 (disk full). Investigating replication + idempotency failure."},
        {"action_type": "escalate", "team": "payments"},
        {"action_type": "escalate", "team": "finance"},
        {"action_type": "run_command", "command": "pause payment-processor retries"},
        {"action_type": "run_command", "command": "enable-maintenance payment-processor"},
        {"action_type": "run_command", "command": "expand-disk replica-2 500GB"},
        {"action_type": "run_command", "command": "resync-replication replica-2"},
        {"action_type": "run_command", "command": "rollback payment-processor 3.7.9"},
        {"action_type": "run_command", "command": "replay-dlq payment-dlq"},
        {"action_type": "run_command", "command": "run-reconciliation"},
        {"action_type": "run_command", "command": "refund-duplicates"},
        {"action_type": "run_command", "command": "disable-maintenance payment-processor"},
        {"action_type": "resolve", "root_cause": "Schema migration in v3.8.0 failed to propagate to replica-2 (disk full), causing idempotency check failures and duplicate charges", "remediation": "Rollback to v3.7.9, expand disk on replica-2, resync replication, replay DLQ, refund duplicates"},
    ],
}


def run_task_expert(task_id: str) -> dict:
    """Run a task using the hardcoded expert policy."""
    print(f"\n{'='*60}")
    print(f"TASK: {task_id} (expert policy)")
    print(f"{'='*60}")

    resp = requests.post(f"{ENV_URL}/reset", json={"task_id": task_id})
    resp.raise_for_status()
    obs = resp.json()
    print(f"\nInitial observation:\n{obs['message'][:200]}...")

    policy = EXPERT_POLICIES[task_id]
    step_count = 0

    for action in policy:
        step_count += 1
        action_type = action.get("action_type", "?")
        print(f"  Step {step_count}: {action_type}", end="")
        if "service" in action:
            print(f" ({action['service']})", end="")
        if "command" in action:
            print(f" ({action['command']})", end="")
        print()

        resp = requests.post(f"{ENV_URL}/step", json={"action": action})
        resp.raise_for_status()
        obs = resp.json()

        if obs.get("done", False):
            break

    grade_resp = requests.post(f"{ENV_URL}/grade")
    grade_resp.raise_for_status()
    grade = grade_resp.json()

    
    return {
        "task_id": task_id,
        "steps": step_count,
        "cumulative_reward": obs.get("cumulative_reward", 0),
        "grade": grade["score"],
        "done": obs.get("done", False),
    }


def run_task_llm(client, task_id: str) -> dict:
    """Run a single task using an LLM agent."""
    
    resp = requests.post(f"{ENV_URL}/reset", json={"task_id": task_id})
    resp.raise_for_status()
    obs = resp.json()

    print(f"\nInitial observation:\n{obs['message'][:200]}...")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"INCIDENT ALERT:\n{obs['message']}\n\nAlerts: {json.dumps(obs.get('alerts', []), indent=2)}"},
    ]

    step_count = 0
    max_steps = obs.get("max_steps", 15)

    while not obs.get("done", False) and step_count < max_steps:
        raw_response = None
        try:
            completion = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.0,
                max_tokens=500,
            )
            raw_response = completion.choices[0].message.content.strip()

            action_text = raw_response
            if "```" in action_text:
                action_text = action_text.split("```")[1]
                if action_text.startswith("json"):
                    action_text = action_text[4:]
                action_text = action_text.strip()

            action = json.loads(action_text)
        except (json.JSONDecodeError, Exception) as e:
            print(f"  Step {step_count + 1}: Failed to parse action: {e}")
            action = {"action_type": "check_alerts"}
            if raw_response is None:
                raw_response = json.dumps(action)

        step_count += 1
        action_type = action.get("action_type", "check_alerts")
        print(f"  Step {step_count}: {action_type}", end="")
        if "service" in action:
            print(f" ({action['service']})", end="")
        if "command" in action:
            print(f" ({action['command']})", end="")
        print()

        resp = requests.post(f"{ENV_URL}/step", json={"action": action})
        resp.raise_for_status()
        obs = resp.json()

        obs_summary = obs["message"]
        if obs.get("logs"):
            obs_summary += "\n\nLogs:\n" + "\n".join(
                f"  [{l['level']}] {l['timestamp']} {l['message']}" for l in obs["logs"]
            )
        if obs.get("metrics"):
            obs_summary += "\n\nMetrics:\n" + "\n".join(
                f"  {m['name']}: {m['value']} {m['unit']}" for m in obs["metrics"]
            )
        if obs.get("command_output"):
            obs_summary += f"\n\nCommand output: {obs['command_output']}"

        messages.append({"role": "assistant", "content": raw_response})
        messages.append({"role": "user", "content": f"Observation (step {step_count}, reward: {obs.get('reward', 0):.3f}, cumulative: {obs.get('cumulative_reward', 0):.3f}):\n{obs_summary}"})

    grade_resp = requests.post(f"{ENV_URL}/grade")
    grade_resp.raise_for_status()
    grade = grade_resp.json()

    

    return {
        "task_id": task_id,
        "steps": step_count,
        "cumulative_reward": obs.get("cumulative_reward", 0),
        "grade": grade["score"],
        "done": obs.get("done", False),
    }


def main():
    expert_mode = "--expert" in sys.argv

    if expert_mode:
        print("Baseline Inference Script — EXPERT MODE (no LLM)")
        print(f"Environment: {ENV_URL}")
    else:
        from openai import OpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("ERROR: Set OPENAI_API_KEY environment variable, or use --expert mode")
            sys.exit(1)

        base_url = os.getenv("OPENAI_BASE_URL")
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        client = OpenAI(**client_kwargs)

        print("Baseline Inference Script — Incident Response Environment")
        print(f"Model: {MODEL}")
        print(f"Environment: {ENV_URL}")

    results = []
    for task_id in TASK_IDS:
        if expert_mode:
            result = run_task_expert(task_id)
        else:
            result = run_task_llm(client, task_id)
        results.append(result)
        time.sleep(1)

    # Summary
    mode_label = "EXPERT" if expert_mode else MODEL

    avg_grade = sum(r["grade"] for r in results) / len(results)
    print("-" * 60)
    print(f"{'Average (' + mode_label + ')':<30} {avg_grade:>8.4f}")

    # Save results to file for reproducibility and CI/CD integration
    results_file = "results.json"
    with open(results_file, "w") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "expert" if expert_mode else "llm",
            "model": MODEL if not expert_mode else "N/A",
            "environment": ENV_URL,
            "tasks": results,
            "average_grade": avg_grade,
            "test_status": "PASSED" if avg_grade > 0.3 else "FAILED"
        }, f, indent=2)
    print(f"\nResults saved to {results_file}")

    return results


if __name__ == "__main__":
    main()
