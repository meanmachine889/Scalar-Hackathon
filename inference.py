"""
Inference Script — Incident Response Environment

===================================
MANDATORY
- Before submitting, ensure the following variables are defined in your environment configuration:
    API_BASE_URL   The API endpoint for the LLM.
    MODEL_NAME     The model identifier to use for inference.
    API_KEY / HF_TOKEN  The hackathon-injected API key.

- The inference script must be named `inference.py` and placed in the root directory of the project
- Participants must use OpenAI Client for all LLM calls using above variables

Modes:
    python inference.py           # LLM mode (requires API_BASE_URL, MODEL_NAME, API_KEY)
    python inference.py --expert  # Expert policy (no LLM needed, reproducible scores)
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


# ── Environment config ────────────────────────────────────────────────────────

ENV_URL = os.getenv("ENV_URL", "http://localhost:7860")
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
        {"action_type": "communicate", "message": "Investigating api-gateway 500s. Connection pool exhausted."},
        {"action_type": "escalate", "team": "database"},
        {"action_type": "run_command", "command": "rollback api-gateway 2.14.2"},
        {"action_type": "resolve", "root_cause": "Connection pool exhaustion", "remediation": "Rollback api-gateway"},
    ],
    "medium_cache_cascade": [
        {"action_type": "check_alerts"},
        {"action_type": "read_logs", "service": "redis-cluster"},
        {"action_type": "check_metrics", "service": "redis-cluster"},
        {"action_type": "run_command", "command": "redis-restart redis-03"},
        {"action_type": "run_command", "command": "enable-rate-limit user-service"},
        {"action_type": "escalate", "team": "infrastructure"},
        {"action_type": "resolve", "root_cause": "Redis node OOM", "remediation": "Restarted redis-03, enabled rate limits"},
    ],
    "hard_payment_corruption": [
        {"action_type": "check_alerts"},
        {"action_type": "read_logs", "service": "payment-processor"},
        {"action_type": "run_command", "command": "pause payment-processor retries"},
        {"action_type": "run_command", "command": "enable-maintenance payment-processor"},
        {"action_type": "run_command", "command": "expand-disk replica-2 500GB"},
        {"action_type": "run_command", "command": "resync-replication replica-2"},
        {"action_type": "run_command", "command": "rollback payment-processor 3.7.9"},
        {"action_type": "run_command", "command": "replay-dlq payment-dlq"},
        {"action_type": "run_command", "command": "run-reconciliation"},
        {"action_type": "run_command", "command": "refund-duplicates"},
        {"action_type": "run_command", "command": "disable-maintenance payment-processor"},
        {"action_type": "resolve", "root_cause": "Schema migration failed", "remediation": "Rollback, expand disk, resync, refund"},
    ],
}

# ── Helpers ───────────────────────────────────────────────────────────────────

EPS = 1e-4


def _safe_score(value: float) -> float:
    """Clamp to strictly open (0, 1) and round to 4dp."""
    return round(min(1.0 - EPS, max(EPS, float(value))), 4)


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
    text = response_text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "action_type" in obj:
            return obj
    except json.JSONDecodeError:
        pass
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
    print(f"\n[START] task={task_id} mode=expert", flush=True)

    resp = safe_post(f"{ENV_URL}/reset", json={"task_id": task_id})
    if resp is None:
        return {"task_id": task_id, "score": _safe_score(0)}

    obs = resp.json()
    policy = EXPERT_POLICIES.get(task_id, [])
    step_count = 0

    for action in policy:
        step_count += 1
        action_type = action.get("action_type", "?")
        resp = safe_post(f"{ENV_URL}/step", json={"action": action})
        if resp is None:
            break
        obs = resp.json()
        reward = obs.get("reward", 0)
        print(f"[STEP] step={step_count} action={action_type} reward={round(reward, 4)} done={obs.get('done', False)}", flush=True)
        if obs.get("done", False):
            break

    grade_resp = safe_post(f"{ENV_URL}/grade")
    raw_score = grade_resp.json().get("score", EPS) if grade_resp else EPS
    score = _safe_score(raw_score)

    print(f"[GRADE] task={task_id} score={score}", flush=True)
    return {"task_id": task_id, "score": score}


def run_task_llm(client: OpenAI, model_name: str, task_id: str) -> Dict[str, Any]:
    """Run a task using an LLM agent via the OpenAI client."""
    print(f"\n[START] task={task_id} mode=llm model={model_name}", flush=True)

    resp = safe_post(f"{ENV_URL}/reset", json={"task_id": task_id})
    if resp is None:
        return {"task_id": task_id, "score": _safe_score(0)}

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
        raw_response = None
        try:
            completion = client.chat.completions.create(
                model=model_name,
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

        resp = safe_post(f"{ENV_URL}/step", json={"action": action})
        if resp is None:
            break
        obs = resp.json()
        reward = obs.get("reward", 0)
        print(f"[STEP] step={step_count} action={action_type} reward={round(reward, 4)} done={obs.get('done', False)}", flush=True)

        obs_text = build_observation_text(obs)
        history.append(f"Step {step_count}: {action_type} -> reward {reward:+.3f}")
        messages.append({"role": "assistant", "content": [{"type": "text", "text": raw_response}]})
        messages.append({"role": "user", "content": [{"type": "text", "text": (
            f"Observation (step {step_count}/{max_steps}, reward: {reward:.3f}):\n{obs_text}\n\n"
            f"Previous steps:\n" + "\n".join(history[-4:]) + "\n\n"
            f"Reply with your next action as a single JSON object."
        )}]})

    grade_resp = safe_post(f"{ENV_URL}/grade")
    raw_score = grade_resp.json().get("score", EPS) if grade_resp else EPS
    score = _safe_score(raw_score)

    print(f"[GRADE] task={task_id} score={score}", flush=True)
    return {"task_id": task_id, "score": score}


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    expert_mode = "--expert" in sys.argv
    client: Optional[OpenAI] = None
    model_name = ""

    if expert_mode:
        print("Inference Script — EXPERT MODE (no LLM, reproducible baseline)")
    else:
        api_base = os.environ.get("API_BASE_URL")
        api_key = os.environ.get("API_KEY") or os.environ.get("HF_TOKEN") or os.environ.get("OPENAI_API_KEY")
        model_name = os.environ.get("MODEL_NAME", "default-hackathon-model")

        if not api_base or not api_key:
            print("ERROR: API_BASE_URL and an API_KEY (or HF_TOKEN) must be set.")
            # Write a safe fallback results.json before exiting so the validator
            # never reads a stale committed file with out-of-range scores.
            _write_results(
                [{"task_id": tid, "score": _safe_score(0)} for tid in TASK_IDS],
                mode="llm",
                model_name=model_name,
            )
            sys.exit(1)

        client = OpenAI(base_url=api_base, api_key=api_key)
        print("Inference Script — Incident Response Environment")
        print(f"API Base URL: {api_base}")
        print(f"Model: {model_name}")

    if not wait_for_env(ENV_URL):
        print("WARNING: Environment not reachable. Will attempt tasks anyway.")

    results = []
    for task_id in TASK_IDS:
        if expert_mode:
            result = run_task_expert(task_id)
        else:
            result = run_task_llm(client, model_name, task_id)
        results.append(result)
        time.sleep(1)

    # ── Summary ───────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    mode_label = "expert" if expert_mode else model_name
    print(f"{'Task':<30} {'Score':>8}")
    print("-" * 40)
    for r in results:
        print(f"{r['task_id']:<30} {r['score']:>8.4f}")
    avg_score = sum(r["score"] for r in results) / len(results)
    print("-" * 40)
    print(f"{'Average (' + mode_label + ')':<30} {avg_score:>8.4f}")

    _write_results(results, mode="expert" if expert_mode else "llm", model_name=model_name)


def _write_results(
    tasks: list,
    mode: str,
    model_name: str,
) -> None:
    """Write results.json. Each task dict contains ONLY task_id and score
    (a float strictly between 0 and 1) so the validator cannot trip over
    any other numeric field such as cumulative_reward or step counts."""
    avg_score = sum(t["score"] for t in tasks) / len(tasks) if tasks else EPS
    payload = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "model": model_name if mode != "expert" else "N/A",
        "environment": ENV_URL,
        "tasks": tasks,          # each task: {"task_id": str, "score": float}
        "average_score": avg_score,
        "test_status": "PASSED" if avg_score > 0.3 else "FAILED",
    }
    results_file = "results.json"
    with open(results_file, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\nResults saved to {results_file}")


if __name__ == "__main__":
    main()