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

REQUEST_TIMEOUT = 30


def wait_for_env(env_url: str, retries: int = 10, delay: float = 3.0) -> bool:
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(f"{env_url}/health", timeout=10)
            if r.status_code == 200:
                print(f"Environment reachable (attempt {attempt}).", flush=True)
                return True
        except requests.RequestException:
            pass
        print(f"Waiting for environment ({attempt}/{retries})...", flush=True)
        time.sleep(delay)
    print("ERROR: Environment not reachable after retries.", flush=True)
    return False


def safe_post(url: str, **kwargs) -> Optional[requests.Response]:
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    try:
        resp = requests.post(url, **kwargs)
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        print(f"  HTTP error for {url}: {exc}", flush=True)
        return None


# ── Environment config ────────────────────────────────────────────────────────

ENV_URL = os.getenv("ENV_URL", "http://localhost:7860")
TASK_IDS = ["easy_db_pool", "medium_cache_cascade", "hard_payment_corruption"]
BENCHMARK = "incident-response-env"
TEMPERATURE = 0.1
MAX_TOKENS = 600
FALLBACK_ACTION = {"action_type": "check_alerts"}
ACTION_JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)

EPS = 1e-4


# ── Stdout log helpers (mandatory format) ────────────────────────────────────

def log_start(task: str, model: str) -> None:
    print(f"[START] task={task} env={BENCHMARK} model={model}", flush=True)


def log_step(step: int, action: str, reward: float, done: bool) -> None:
    print(f"[STEP] step={step} action={action} reward={reward:.2f} done={str(done).lower()} error=null", flush=True)


def log_end(success: bool, steps: int, score: float, rewards: List[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(f"[END] success={str(success).lower()} steps={steps} score={score:.4f} rewards={rewards_str}", flush=True)


# ── Safe score ────────────────────────────────────────────────────────────────

def _safe_score(value: float) -> float:
    clamped = min(1.0 - EPS, max(EPS, float(value)))
    return float(f"{clamped:.4f}")

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

# ── Expert policies ───────────────────────────────────────────────────────────

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


# ── Observation helper ────────────────────────────────────────────────────────

def build_observation_text(obs: Dict[str, Any]) -> str:
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

def run_task_expert(task_id: str, model_name: str) -> Dict[str, Any]:
    log_start(task=task_id, model=model_name)

    resp = safe_post(f"{ENV_URL}/reset", json={"task_id": task_id})
    if resp is None:
        score = _safe_score(0)
        log_end(success=False, steps=0, score=score, rewards=[])
        return {"task_id": task_id, "score": score}

    policy = EXPERT_POLICIES.get(task_id, [])
    step_count = 0
    rewards: List[float] = []
    obs = resp.json()

    for action in policy:
        step_count += 1
        action_type = action.get("action_type", "?")
        resp = safe_post(f"{ENV_URL}/step", json={"action": action})
        if resp is None:
            break
        obs = resp.json()
        reward = obs.get("reward", 0.0)
        done = obs.get("done", False)
        rewards.append(reward)
        log_step(step=step_count, action=action_type, reward=reward, done=done)
        if done:
            break

    grade_resp = safe_post(f"{ENV_URL}/grade")
    raw_score = grade_resp.json().get("score", EPS) if grade_resp else EPS
    score = _safe_score(raw_score)

    log_end(success=obs.get("done", False), steps=step_count, score=score, rewards=rewards)
    return {"task_id": task_id, "score": score}


def run_task_llm(client: OpenAI, model_name: str, task_id: str) -> Dict[str, Any]:
    log_start(task=task_id, model=model_name)

    resp = safe_post(f"{ENV_URL}/reset", json={"task_id": task_id})
    if resp is None:
        score = _safe_score(0)
        log_end(success=False, steps=0, score=score, rewards=[])
        return {"task_id": task_id, "score": score}

    obs = resp.json()
    max_steps = obs.get("max_steps", 15)
    obs_text = build_observation_text(obs)
    step_count = 0
    rewards: List[float] = []
    history: List[str] = []

    messages = [
        {"role": "system", "content": [{"type": "text", "text": SYSTEM_PROMPT}]},
        {"role": "user", "content": [{"type": "text", "text": f"INCIDENT ALERT:\n{obs_text}"}]},
    ]

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
            print(f"  Model request failed ({exc}). Using fallback action.", flush=True)
            raw_response = json.dumps(FALLBACK_ACTION)

        action = parse_model_action(raw_response)
        step_count += 1
        action_type = action.get("action_type", "check_alerts")

        resp = safe_post(f"{ENV_URL}/step", json={"action": action})
        if resp is None:
            break
        obs = resp.json()
        reward = obs.get("reward", 0.0)
        done = obs.get("done", False)
        rewards.append(reward)

        log_step(step=step_count, action=action_type, reward=reward, done=done)

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

    log_end(success=obs.get("done", False), steps=step_count, score=score, rewards=rewards)
    return {"task_id": task_id, "score": score}


# ── Results file ──────────────────────────────────────────────────────────────

def _write_results(tasks: list, mode: str, model_name: str) -> None:
    safe_tasks = [{"task_id": t["task_id"], "score": _safe_score(t.get("score", EPS))} for t in tasks]
    avg = _safe_score(sum(t["score"] for t in safe_tasks) / len(safe_tasks) if safe_tasks else EPS)
    payload = {
        "tasks": safe_tasks,
        "average_score": avg,
        "mode": mode,
        "model": model_name if mode != "expert" else "N/A",
    }
    with open("results.json", "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\nresults.json contents:\n{json.dumps(payload, indent=2)}", flush=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    expert_mode = "--expert" in sys.argv
    client: Optional[OpenAI] = None
    model_name = "expert-policy"

    api_base = None
    api_key = None

    if not expert_mode:
        api_base = os.environ.get("API_BASE_URL")
        api_key = os.environ.get("API_KEY") or os.environ.get("HF_TOKEN") or os.environ.get("OPENAI_API_KEY")
        model_name = os.environ.get("MODEL_NAME", "default-hackathon-model")

    if not api_base or not api_key:
        print("ERROR: API_BASE_URL and API_KEY must be set.", flush=True)
        sys.exit(1)
    else:
        client = OpenAI(base_url=api_base, api_key=api_key)
        
    if not wait_for_env(ENV_URL):
        print("WARNING: Environment not reachable. Will attempt tasks anyway.", flush=True)

    results = []
    for task_id in TASK_IDS:
        if expert_mode:
            result = run_task_expert(task_id, model_name)
        else:
            result = run_task_llm(client, model_name, task_id)
        results.append(result)
        time.sleep(1)

    _write_results(results, mode="expert" if expert_mode else "llm", model_name=model_name)


if __name__ == "__main__":
    main()