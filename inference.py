"""
Inference Script — Incident Response Environment
===================================
MANDATORY
- Before submitting, ensure the following variables are defined in your environment configuration:
    API_BASE_URL   The API endpoint for the LLM.
    MODEL_NAME     The model identifier to use for inference.
    HF_TOKEN       Your Hugging Face / API key.

- The inference script must be named `inference.py` and placed in the root directory of the project
- Participants must use OpenAI Client for all LLM calls using above variables

Modes:
    python inference.py             # LLM mode (requires API_BASE_URL, MODEL_NAME, HF_TOKEN)
    python inference.py --expert    # Expert policy (no LLM needed, reproducible scores)
"""

import json
import os
import re
import sys
import textwrap
import time
from typing import Any, Dict, List, Optional

import requests
from openai import OpenAI

# ── Network helpers ──────────────────────────────────────────────────────────

REQUEST_TIMEOUT = 30  # seconds per HTTP call


def wait_for_env(env_url: str, retries: int = 10, delay: float = 3.0) -> bool:
    """Block until the environment server is reachable, or give up."""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(f"{env_url}/health", timeout=10)
            if r.status_code == 200:
                print(f"Environment reachable (attempt {attempt}).")
                return True
        except requests.RequestException:
            pass
        print(f"Waiting for environment ({attempt}/{retries})...")
        time.sleep(delay)
    print("ERROR: Environment not reachable after retries.")
    return False


def safe_post(url: str, **kwargs) -> Optional[requests.Response]:
    """POST with timeout and exception handling. Returns None on failure."""
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    try:
        resp = requests.post(url, **kwargs)
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        print(f"  HTTP error for {url}: {exc}")
        return None

# ── Mandatory environment variables ───────────────────────────────────────────

API_BASE_URL = os.getenv("API_BASE_URL", "<hackathon-llm-endpoint>")
MODEL_NAME = os.getenv("MODEL_NAME", "<hackathon-model-name>")
HF_TOKEN = os.getenv("HF_TOKEN")

# ── Environment config ────────────────────────────────────────────────────────

# Change ENV_URL to the hackathon OpenEnv URL
ENV_URL = os.getenv("ENV_URL", "<hackathon-env-url>")

TASK_IDS = ["easy_db_pool", "medium_cache_cascade", "hard_payment_corruption"]
TEMPERATURE = 0.1
MAX_TOKENS = 600
FALLBACK_ACTION = {"action_type": "check_alerts"}

ACTION_JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = textwrap.dedent("""\
    You are an expert SRE (Site Reliability Engineer) responding to a production incident.
    You must investigate the incident by checking alerts, reading logs, checking metrics,
    and running commands. Then diagnose the root cause and resolve the incident.

    You interact with the environment by outputting a SINGLE JSON object. No explanation, no markdown.

    Available action types:
    - check_alerts: View active alerts. No extra fields needed.
    - read_logs: Read service logs. Requires "service" field.
    - check_metrics: Check service metrics. Requires "service" field.
    - run_command: Run a diagnostic/remediation command. Requires "command" field.
    - escalate: Escalate to a team. Requires "team" field.
    - communicate: Send a status update. Requires "message" field.
    - resolve: Close the incident. Requires "root_cause" and "remediation" fields.

    Examples:
    {"action_type": "check_alerts"}
    {"action_type": "read_logs", "service": "api-gateway"}
    {"action_type": "run_command", "command": "restart api-gateway"}
    {"action_type": "resolve", "root_cause": "connection pool exhausted", "remediation": "rollback to v2.14.2"}

    Reply with exactly ONE JSON action object. Nothing else.
""")

# ── Expert (hardcoded) policies per task ──────────────────────────────────────

EXPERT_POLICIES: Dict[str, List[Dict[str, Any]]] = {
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

# ── Helpers ───────────────────────────────────────────────────────────────────


def build_observation_text(obs: Dict[str, Any]) -> str:
    """Convert an environment observation dict into a text summary for the LLM."""
    parts = [obs.get("message", "")]

    if obs.get("alerts"):
        parts.append("\nAlerts:")
        for a in obs["alerts"]:
            parts.append(f"  [{a['severity'].upper()}] {a['service']}: {a['message']}")

    if obs.get("logs"):
        parts.append("\nLogs:")
        for l in obs["logs"]:
            parts.append(f"  [{l['level']}] {l['service']} {l['timestamp']}: {l['message']}")

    if obs.get("metrics"):
        parts.append("\nMetrics:")
        for m in obs["metrics"]:
            parts.append(f"  {m['name']}: {m['value']} {m['unit']}")

    if obs.get("command_output"):
        parts.append(f"\nCommand output: {obs['command_output']}")

    return "\n".join(parts)


def parse_model_action(response_text: str) -> Dict[str, Any]:
    """Extract a JSON action dict from the LLM response."""
    if not response_text:
        return FALLBACK_ACTION

    # Strip markdown code fences
    text = response_text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    # Try direct parse
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "action_type" in obj:
            return obj
    except json.JSONDecodeError:
        pass

    # Search for JSON object in response
    match = ACTION_JSON_RE.search(response_text)
    if match:
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, dict) and "action_type" in obj:
                return obj
        except json.JSONDecodeError:
            pass

    return FALLBACK_ACTION


# ── Task runners ──────────────────────────────────────────────────────────────


def run_task_expert(task_id: str) -> Dict[str, Any]:
    """Run a task using the hardcoded expert policy (no LLM)."""
    print(f"\nSTART {json.dumps({'task_id': task_id, 'mode': 'expert'})}")

    resp = safe_post(f"{ENV_URL}/reset", json={"task_id": task_id})
    if resp is None:
        print(f"  Skipping task {task_id}: could not reset environment.")
        result = {"task_id": task_id, "steps": 0, "cumulative_reward": 0, "grade": 0.0, "done": False}
        print(f"END {json.dumps(result)}")
        return result
    obs = resp.json()

    policy = EXPERT_POLICIES[task_id]
    step_count = 0

    for action in policy:
        step_count += 1
        action_type = action.get("action_type", "?")

        resp = safe_post(f"{ENV_URL}/step", json={"action": action})
        if resp is None:
            print(f"STEP {json.dumps({'step': step_count, 'action': action_type, 'error': 'request_failed'})}")
            break
        obs = resp.json()

        reward = obs.get("reward", 0)
        print(f"STEP {json.dumps({'step': step_count, 'action': action_type, 'reward': round(reward, 4), 'cumulative_reward': round(obs.get('cumulative_reward', 0), 4), 'done': obs.get('done', False)})}")

        if obs.get("done", False):
            break

    grade_resp = safe_post(f"{ENV_URL}/grade")
    grade_score = 0.0
    if grade_resp is not None:
        grade_score = grade_resp.json().get("score", 0.0)

    result = {
        "task_id": task_id,
        "steps": step_count,
        "cumulative_reward": round(obs.get("cumulative_reward", 0), 4),
        "grade": round(grade_score, 4),
        "done": obs.get("done", False),
    }
    print(f"END {json.dumps(result)}")
    return result


def run_task_llm(client: OpenAI, task_id: str) -> Dict[str, Any]:
    """Run a task using an LLM agent via the OpenAI client."""
    print(f"\nSTART {json.dumps({'task_id': task_id, 'mode': 'llm', 'model': MODEL_NAME})}")

    resp = safe_post(f"{ENV_URL}/reset", json={"task_id": task_id})
    if resp is None:
        print(f"  Skipping task {task_id}: could not reset environment.")
        result = {"task_id": task_id, "steps": 0, "cumulative_reward": 0, "grade": 0.0, "done": False}
        print(f"END {json.dumps(result)}")
        return result
    obs = resp.json()
    max_steps = obs.get("max_steps", 15)

    obs_text = build_observation_text(obs)
    messages = [
        {"role": "system", "content": [{"type": "text", "text": SYSTEM_PROMPT}]},
        {"role": "user", "content": [{"type": "text", "text": f"INCIDENT ALERT:\n{obs_text}"}]},
    ]

    step_count = 0
    history: List[str] = []

    while not obs.get("done", False) and step_count < max_steps:
        # Call the LLM
        raw_response = None
        try:
            completion = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                stream=False,
            )
            raw_response = completion.choices[0].message.content or ""
        except Exception as exc:
            print(f"  Model request failed ({exc}). Using fallback action.")
            raw_response = json.dumps(FALLBACK_ACTION)

        action = parse_model_action(raw_response)

        step_count += 1
        action_type = action.get("action_type", "check_alerts")

        # Execute action
        resp = safe_post(f"{ENV_URL}/step", json={"action": action})
        if resp is None:
            print(f"STEP {json.dumps({'step': step_count, 'action': action_type, 'error': 'request_failed'})}")
            break
        obs = resp.json()

        reward = obs.get("reward", 0)
        print(f"STEP {json.dumps({'step': step_count, 'action': action_type, 'reward': round(reward, 4), 'cumulative_reward': round(obs.get('cumulative_reward', 0), 4), 'done': obs.get('done', False)})}")

        # Update conversation for LLM
        obs_text = build_observation_text(obs)
        history_line = f"Step {step_count}: {action_type} -> reward {reward:+.3f}"
        history.append(history_line)

        messages.append({"role": "assistant", "content": [{"type": "text", "text": raw_response}]})
        messages.append({"role": "user", "content": [{"type": "text", "text": (
            f"Observation (step {step_count}/{max_steps}, reward: {reward:.3f}):\n{obs_text}\n\n"
            f"Previous steps:\n" + "\n".join(history[-4:]) + "\n\n"
            f"Reply with your next action as a single JSON object."
        )}]})

        if obs.get("done", False):
            break
    else:
        if not obs.get("done", False):
            print(f"  Reached max steps ({max_steps}).")

    grade_resp = safe_post(f"{ENV_URL}/grade")
    grade_score = 0.0
    if grade_resp is not None:
        grade_score = grade_resp.json().get("score", 0.0)

    result = {
        "task_id": task_id,
        "steps": step_count,
        "cumulative_reward": round(obs.get("cumulative_reward", 0), 4),
        "grade": round(grade_score, 4),
        "done": obs.get("done", False),
    }
    print(f"END {json.dumps(result)}")
    return result


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    expert_mode = "--expert" in sys.argv

    client: Optional[OpenAI] = None

    if expert_mode:
        print("Inference Script — EXPERT MODE (no LLM, reproducible baseline)")
        print(f"Environment: {ENV_URL}")
    else:
        if not HF_TOKEN:
            print("ERROR: Set HF_TOKEN environment variable, or use --expert mode")
            sys.exit(1)

        client = OpenAI(base_url=API_BASE_URL, api_key=HF_TOKEN)

        print("Inference Script — Incident Response Environment")
        print(f"API Base URL: {API_BASE_URL}")
        print(f"Model: {MODEL_NAME}")
        print(f"Environment: {ENV_URL}")

    # Wait for the environment server to be ready before running tasks
    if not wait_for_env(ENV_URL):
        print("WARNING: Environment not reachable. Will attempt tasks anyway.")

    results = []
    for task_id in TASK_IDS:
        if expert_mode:
            result = run_task_expert(task_id)
        else:
            result = run_task_llm(client, task_id)
        results.append(result)
        time.sleep(1)

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    mode_label = "expert" if expert_mode else MODEL_NAME
    print(f"{'Task':<30} {'Grade':>8} {'Steps':>8} {'Reward':>10}")
    print("-" * 60)
    for r in results:
        print(f"{r['task_id']:<30} {r['grade']:>8.4f} {r['steps']:>8} {r['cumulative_reward']:>10.3f}")

    avg_grade = sum(r["grade"] for r in results) / len(results)
    print("-" * 60)
    print(f"{'Average (' + mode_label + ')':<30} {avg_grade:>8.4f}")


if __name__ == "__main__":
    main()
