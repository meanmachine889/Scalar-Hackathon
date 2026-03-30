# Incident Response Environment

An OpenEnv-compliant environment that simulates **production incident response** for SRE/DevOps AI agents. Agents must triage alerts, investigate service logs and metrics, diagnose root causes, and apply remediations — just like a real on-call engineer.

## Motivation

Incident response is one of the most high-stakes, time-pressured tasks in software engineering. On-call engineers must rapidly correlate signals across multiple services, distinguish real issues from noise, and take decisive action under uncertainty. This environment provides a realistic training and evaluation ground for AI agents in this domain.

## Action Space

| Action Type | Required Fields | Description |
|-------------|----------------|-------------|
| `check_alerts` | — | View all active production alerts |
| `read_logs` | `service` | Read log entries for a specific service |
| `check_metrics` | `service` | Check metrics/dashboards for a service |
| `run_command` | `command` | Execute a diagnostic or remediation command |
| `escalate` | `team` | Page/escalate to a specific team |
| `communicate` | `message` | Post a status update to the incident channel |
| `resolve` | `root_cause`, `remediation` | Attempt to close the incident with diagnosis + fix |

## Observation Space

Each observation includes:
- **message**: Human-readable description of what happened
- **alerts**: List of active alerts (id, severity, service, message, timestamp)
- **logs**: Log entries (timestamp, level, service, message)
- **metrics**: Metric data points (name, value, unit, timestamp)
- **command_output**: Output from executed commands
- **reward / cumulative_reward**: Current and total reward
- **step_number / max_steps**: Progress tracking
- **done**: Whether the episode has ended

## Tasks

### Easy: Database Connection Pool Exhaustion
**Max steps**: 15 | **Expected score**: 0.7–0.9

Single service (`api-gateway`) returning HTTP 500s. Logs clearly show connection pool exhaustion caused by a slow analytics query introduced in a recent deploy. Fix by rolling back, killing the query, or restarting. Includes a red herring notification service to test triage skills.

### Medium: Cascading Cache Failure
**Max steps**: 20 | **Expected score**: 0.5–0.7

Multiple services degraded. Root cause is a Redis cache node that OOM'd and failed over unsuccessfully, causing a thundering herd of database queries. Requires correlating logs across 4+ services and applying multiple remediations.

### Hard: Payment Pipeline Corruption
**Max steps**: 25 | **Expected score**: 0.3–0.5

P1 incident with duplicate charges and missing transactions. **Multiple root causes** across 3 categories: (1) schema migration that didn't propagate to a database replica, (2) disk full on replica-2 stalling replication, (3) idempotency check failures causing duplicate charges. Red herring alerts from analytics and CDN. Agent must identify root causes from **at least 2 of 3 categories** for full diagnosis credit.

## Reward Design

Rewards provide **continuous signal** throughout the episode:

| Signal | Reward |
|--------|--------|
| First alert check | +0.05 |
| Investigating a relevant service | +0.05 to +0.08 |
| Investigating a red herring | +0.01 (slight penalty) |
| Running a remediation command | +0.12 |
| Correct escalation | +0.06 |
| Status communication (first 3) | +0.03 each |
| Correct root cause in resolve | +0.20 |
| Correct remediation in resolve | +0.15 |
| Full resolution bonus | +0.10 |
| Efficiency bonus (fewer steps) | up to +0.10 |
| Invalid/empty actions | -0.01 to -0.05 |
| Timeout without resolution | -0.15 |

## Grader Scoring (0.0–1.0)

| Component | Weight | Criteria |
|-----------|--------|----------|
| Investigation | 25% | Proportion of relevant services investigated |
| Root cause | 25% | Correctly identified the root cause |
| Remediation | 25% | Applied effective remediation |
| Communication | 10% | Sent status updates and escalated appropriately |
| Efficiency | 15% | Fewer steps = higher score (only if resolved) |

### Root Cause & Remediation Validation

The graders use **deterministic keyword matching** on the `root_cause` and `remediation` fields in the `resolve` action:

- **Root cause validation**: Agent's root cause string is checked for case-insensitive substring matches against predefined keywords
  - Example (easy task): agent responds "connection pool exhausted due to slow query" → matches keyword "pool exhaustion" ✅
  - **Result**: Sets `root_cause_identified` flag and awards +0.20 reward
  - **Hard task**: Uses **multi-category matching** — root causes are grouped into 3 categories (deploy/schema, replication/disk, idempotency). Agent must match keywords from at least 2 categories for full credit. Matching only 1 category gives partial credit (+0.08 instead of +0.20).

- **Remediation validation**: Agent's remediation string is checked for case-insensitive substring matches against valid remediation keywords
  - Example (easy task): agent responds "restart api-gateway to reset connections" → matches keyword "restart" ✅
  - **Result**: Sets `remediation_applied` flag and awards +0.15 reward

### Anti-Gaming Measures

- **Length limit**: `root_cause` and `remediation` must each be under 500 characters. Excessively long text (keyword stuffing) is penalized and rejected.
- **Investigation prerequisite**: Agent must have checked alerts AND investigated at least one relevant service before `resolve` can succeed. Premature resolve attempts are penalized.
- **Resolve spam penalty**: More than 3 failed resolve attempts incur increasing penalties.

This approach ensures **reproducibility** and **fairness** across all evaluations. Root cause/remediation keywords are defined per-task in `src/scenarios.py`.

## Setup & Usage

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn src.server:app --host 0.0.0.0 --port 8000

# Server is now at http://localhost:8000
# API docs at http://localhost:8000/docs
```

### Docker

```bash
docker build -t incident-response-env .
docker run -p 8000:8000 incident-response-env
```

### Running the Baseline

```bash
# Set your API key
export OPENAI_API_KEY=sk-...

# Optional: specify model (default: gpt-4o-mini)
export MODEL=gpt-4o

# Run baseline against all 3 tasks
python baseline.py
```

### API Examples

```bash
# Reset to easy task
curl -X POST http://localhost:8000/reset -H "Content-Type: application/json" -d '{"task_id": "easy_db_pool"}'

# Take an action
curl -X POST http://localhost:8000/step -H "Content-Type: application/json" -d '{"action": {"action_type": "read_logs", "service": "api-gateway"}}'

# Check state
curl http://localhost:8000/state

# Grade the episode
curl -X POST http://localhost:8000/grade

# List available tasks
curl http://localhost:8000/tasks
```

## Baseline Scores

### Published Baseline (gpt-4o-mini)

| Task | Model | Grade | Steps |
|------|-------|-------|-------|
| easy_db_pool | gpt-4o-mini | ~0.72 | 8 |
| medium_cache_cascade | gpt-4o-mini | ~0.55 | 14 |
| hard_payment_corruption | gpt-4o-mini | ~0.35 | 20 |

### Current Baseline (Expert Hardcoded Policy)

| Task | Model | Grade | Steps |
|------|-------|-------|-------|
| easy_db_pool | expert | **0.8900** | **9** |
| medium_cache_cascade | expert | **0.8975** | **11** |
| hard_payment_corruption | expert | **0.8660** | **19** |
| **Average** | **expert** | **0.8845** | — |

The expert baseline demonstrates strong performance across all difficulty levels. Run `python baseline.py --expert` or `python inference.py --expert` to reproduce these scores locally.

## Hugging Face Space

Deploy as a Hugging Face Space tagged with `openenv`:

```bash
# The Dockerfile handles everything
# Push to HF Spaces with the openenv tag
```

## Project Structure

```
incident-response-env/
├── openenv.yaml          # Environment manifest
├── Dockerfile            # Container definition
├── requirements.txt      # Dependencies
├── pyproject.toml        # Project config
├── baseline.py           # Baseline inference script
├── README.md             # This file
└── src/
    ├── __init__.py
    ├── models.py         # Pydantic Action/Observation/Reward/State models
    ├── scenarios.py      # 3 task scenarios (easy/medium/hard)
    ├── environment.py    # Core environment (step/reset/state)
    ├── graders.py        # Programmatic graders (0.0–1.0)
    └── server.py         # FastAPI server
```
