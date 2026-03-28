"""Pydantic models for the Incident Response environment."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Action Space ──────────────────────────────────────────────────────────────


class ActionType(str, Enum):
    CHECK_ALERTS = "check_alerts"
    READ_LOGS = "read_logs"
    CHECK_METRICS = "check_metrics"
    RUN_COMMAND = "run_command"
    ESCALATE = "escalate"
    COMMUNICATE = "communicate"
    RESOLVE = "resolve"


class Action(BaseModel):
    """An action the agent can take during incident response."""

    action_type: ActionType = Field(description="Type of action to perform")
    service: Optional[str] = Field(
        default=None,
        description="Target service name (for read_logs, check_metrics, run_command)",
    )
    command: Optional[str] = Field(
        default=None,
        description="Command to run (for run_command action)",
    )
    team: Optional[str] = Field(
        default=None,
        description="Team to escalate to (for escalate action)",
    )
    message: Optional[str] = Field(
        default=None,
        description="Status update message (for communicate action)",
    )
    root_cause: Optional[str] = Field(
        default=None,
        description="Identified root cause (for resolve action)",
    )
    remediation: Optional[str] = Field(
        default=None,
        description="Remediation action taken (for resolve action)",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ── Observation Space ─────────────────────────────────────────────────────────


class Alert(BaseModel):
    """A production alert."""

    alert_id: str
    severity: str  # critical, warning, info
    service: str
    message: str
    timestamp: str


class LogEntry(BaseModel):
    """A log line from a service."""

    timestamp: str
    level: str  # ERROR, WARN, INFO, DEBUG
    service: str
    message: str


class MetricPoint(BaseModel):
    """A metric data point."""

    name: str
    value: float
    unit: str
    timestamp: str


class Observation(BaseModel):
    """What the agent observes after taking an action."""

    message: str = Field(description="Human-readable description of what happened")
    alerts: List[Alert] = Field(default_factory=list)
    logs: List[LogEntry] = Field(default_factory=list)
    metrics: List[MetricPoint] = Field(default_factory=list)
    command_output: Optional[str] = None
    done: bool = False
    reward: float = 0.0
    cumulative_reward: float = 0.0
    step_number: int = 0
    max_steps: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ── Reward ────────────────────────────────────────────────────────────────────


class Reward(BaseModel):
    """Reward breakdown for a single step."""

    total: float = Field(default=0.0, description="Total reward for this step")
    investigation_bonus: float = 0.0
    diagnosis_bonus: float = 0.0
    remediation_bonus: float = 0.0
    communication_bonus: float = 0.0
    penalty: float = 0.0
    reason: str = ""


# ── State ─────────────────────────────────────────────────────────────────────


class State(BaseModel):
    """Current internal state of the environment."""

    task_id: str
    task_name: str
    task_difficulty: str
    episode_id: str
    step_count: int
    max_steps: int
    cumulative_reward: float
    done: bool
    investigated_services: List[str]
    escalated_teams: List[str]
    communications_sent: int
    root_cause_identified: bool
    remediation_applied: bool
