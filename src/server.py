"""FastAPI server exposing the OpenEnv HTTP API."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.environment import IncidentResponseEnv
from src.graders import grade_task
from src.models import Action, Observation, State

app = FastAPI(
    title="Incident Response Environment",
    description=(
        "OpenEnv-compliant environment simulating production incident response. "
        "Agents must triage alerts, investigate services, diagnose root causes, and resolve incidents."
    ),
    version="1.0.0",
)

env = IncidentResponseEnv()


class ResetRequest(BaseModel):
    task_id: str = "easy_db_pool"


class StepRequest(BaseModel):
    action: Action


class GradeResponse(BaseModel):
    score: float
    state: State


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "healthy"}


# ── OpenEnv API ───────────────────────────────────────────────────────────────


@app.post("/reset", response_model=Observation)
def reset(request: ResetRequest):
    """Reset the environment and start a new episode."""
    try:
        return env.reset(task_id=request.task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/step", response_model=Observation)
def step(request: StepRequest):
    """Execute an action and return the observation."""
    return env.step(request.action)


@app.get("/state", response_model=State)
def state():
    """Get the current episode state."""
    return env.state()


@app.post("/grade", response_model=GradeResponse)
def grade():
    """Grade the current episode. Call after the episode is done."""
    current_state = env.state()
    score = grade_task(current_state)
    return GradeResponse(score=score, state=current_state)


# ── Info ──────────────────────────────────────────────────────────────────────


@app.get("/tasks")
def list_tasks():
    """List available tasks."""
    return {
        "tasks": [
            {
                "task_id": "easy_db_pool",
                "name": "Database Connection Pool Exhaustion",
                "difficulty": "easy",
                "max_steps": 15,
                "description": "Single service outage caused by connection pool exhaustion after a bad deploy.",
            },
            {
                "task_id": "medium_cache_cascade",
                "name": "Cascading Cache Failure",
                "difficulty": "medium",
                "max_steps": 20,
                "description": "Multiple services degraded due to Redis cache node OOM causing thundering herd.",
            },
            {
                "task_id": "hard_payment_corruption",
                "name": "Payment Pipeline Corruption",
                "difficulty": "hard",
                "max_steps": 25,
                "description": "Payment processing failures with multiple root causes, red herrings, and data corruption.",
            },
        ]
    }
