"""Core environment implementing step/reset/state for incident response."""

from __future__ import annotations  # noqa: F401 — enables PEP 604 syntax at runtime on 3.9

import uuid
from typing import Any

from src.models import (
    Action,
    ActionType,
    Alert,
    LogEntry,
    MetricPoint,
    Observation,
    Reward,
    State,
)
from src.scenarios import Scenario, get_scenario


class IncidentResponseEnv:
    """Simulates production incident response for an on-call SRE agent."""

    def __init__(self) -> None:
        self._scenario: Scenario | None = None
        self._episode_id: str = ""
        self._step_count: int = 0
        self._cumulative_reward: float = 0.0
        self._done: bool = True
        self._investigated_services: set[str] = set()
        self._checked_alerts: bool = False
        self._escalated_teams: set[str] = set()
        self._communications: int = 0
        self._root_cause_identified: bool = False
        self._remediation_applied: bool = False
        self._commands_run: set[str] = set()
        self._resolve_attempts: int = 0
        self._task_id: str = ""

    # ── Public API ────────────────────────────────────────────────────────

    def reset(self, task_id: str = "easy_db_pool") -> Observation:
        """Start a new episode for the given task."""
        self._scenario = get_scenario(task_id)
        self._task_id = task_id
        self._episode_id = str(uuid.uuid4())[:8]
        self._step_count = 0
        self._cumulative_reward = 0.0
        self._done = False
        self._investigated_services = set()
        self._checked_alerts = False
        self._escalated_teams = set()
        self._communications = 0
        self._root_cause_identified = False
        self._remediation_applied = False
        self._commands_run = set()
        self._resolve_attempts = 0

        return Observation(
            message=(
                f"INCIDENT RESPONSE INITIATED — Episode {self._episode_id}\n"
                f"Task: {self._scenario.task_name} (Difficulty: {self._scenario.difficulty})\n\n"
                f"{self._scenario.description}\n\n"
                f"You have {self._scenario.max_steps} steps to investigate and resolve this incident.\n"
                "Available actions: check_alerts, read_logs, check_metrics, run_command, escalate, communicate, resolve"
            ),
            alerts=self._scenario.initial_alerts,
            done=False,
            reward=0.0,
            cumulative_reward=0.0,
            step_number=0,
            max_steps=self._scenario.max_steps,
        )

    def step(self, action: Action) -> Observation:
        """Execute an action and return the resulting observation."""
        if self._done:
            return Observation(
                message="Episode is already done. Call reset() to start a new episode.",
                done=True,
                reward=0.0,
                cumulative_reward=self._cumulative_reward,
                step_number=self._step_count,
                max_steps=self._scenario.max_steps if self._scenario else 0,
            )

        self._step_count += 1
        scenario = self._scenario
        assert scenario is not None

        # Check if we've exceeded max steps
        if self._step_count >= scenario.max_steps:
            self._done = True
            reward = self._compute_timeout_reward()
            self._cumulative_reward += reward.total
            return Observation(
                message=f"TIME LIMIT REACHED. Incident unresolved after {scenario.max_steps} steps.",
                done=True,
                reward=reward.total,
                cumulative_reward=self._cumulative_reward,
                step_number=self._step_count,
                max_steps=scenario.max_steps,
                metadata={"reward_breakdown": reward.model_dump()},
            )

        # Dispatch based on action type
        handler = {
            ActionType.CHECK_ALERTS: self._handle_check_alerts,
            ActionType.READ_LOGS: self._handle_read_logs,
            ActionType.CHECK_METRICS: self._handle_check_metrics,
            ActionType.RUN_COMMAND: self._handle_run_command,
            ActionType.ESCALATE: self._handle_escalate,
            ActionType.COMMUNICATE: self._handle_communicate,
            ActionType.RESOLVE: self._handle_resolve,
        }[action.action_type]

        return handler(action)

    def state(self) -> State:
        """Return current episode state."""
        return State(
            task_id=self._task_id,
            task_name=self._scenario.task_name if self._scenario else "",
            task_difficulty=self._scenario.difficulty if self._scenario else "",
            episode_id=self._episode_id,
            step_count=self._step_count,
            max_steps=self._scenario.max_steps if self._scenario else 0,
            cumulative_reward=self._cumulative_reward,
            done=self._done,
            investigated_services=sorted(self._investigated_services),
            escalated_teams=sorted(self._escalated_teams),
            communications_sent=self._communications,
            root_cause_identified=self._root_cause_identified,
            remediation_applied=self._remediation_applied,
        )

    # ── Action Handlers ───────────────────────────────────────────────────

    def _handle_check_alerts(self, action: Action) -> Observation:
        scenario = self._scenario
        reward = Reward(reason="Checked active alerts")

        if not self._checked_alerts:
            self._checked_alerts = True
            reward.investigation_bonus = 0.05
            reward.total = 0.05
            reward.reason = "Good first step: reviewing active alerts"
        else:
            reward.total = 0.0
            reward.reason = "Alerts already checked (no new reward)"

        self._cumulative_reward += reward.total
        return Observation(
            message=f"Active alerts ({len(scenario.initial_alerts)}):",
            alerts=scenario.initial_alerts,
            reward=reward.total,
            cumulative_reward=self._cumulative_reward,
            step_number=self._step_count,
            max_steps=scenario.max_steps,
            metadata={"reward_breakdown": reward.model_dump()},
        )

    def _handle_read_logs(self, action: Action) -> Observation:
        scenario = self._scenario
        service = (action.service or "").strip()
        reward = Reward(reason=f"Read logs for {service}")

        if not service:
            reward.penalty = -0.02
            reward.total = -0.02
            reward.reason = "No service specified for read_logs"
            self._cumulative_reward += reward.total
            return Observation(
                message="ERROR: Must specify a service name. Available services: "
                + ", ".join(sorted(scenario.service_logs.keys())),
                reward=reward.total,
                cumulative_reward=self._cumulative_reward,
                step_number=self._step_count,
                max_steps=scenario.max_steps,
                metadata={"reward_breakdown": reward.model_dump()},
            )

        logs = scenario.service_logs.get(service, [])
        if not logs:
            reward.penalty = -0.01
            reward.total = -0.01
            reward.reason = f"No logs available for unknown service '{service}'"
            self._cumulative_reward += reward.total
            return Observation(
                message=f"Service '{service}' not found. Available: {', '.join(sorted(scenario.service_logs.keys()))}",
                reward=reward.total,
                cumulative_reward=self._cumulative_reward,
                step_number=self._step_count,
                max_steps=scenario.max_steps,
                metadata={"reward_breakdown": reward.model_dump()},
            )

        is_new = service not in self._investigated_services
        self._investigated_services.add(service)

        if is_new:
            if service in scenario.relevant_services:
                reward.investigation_bonus = 0.08
                reward.reason = f"Investigated relevant service: {service}"
            elif service in scenario.red_herring_services:
                reward.investigation_bonus = 0.01
                reward.penalty = -0.02
                reward.reason = f"Investigated red herring service: {service} (low value)"
            else:
                reward.investigation_bonus = 0.02
                reward.reason = f"Investigated service: {service}"
        else:
            reward.investigation_bonus = 0.0
            reward.reason = f"Re-read logs for {service} (no new reward)"

        reward.total = reward.investigation_bonus + reward.penalty
        self._cumulative_reward += reward.total

        return Observation(
            message=f"Logs for {service} ({len(logs)} entries):",
            logs=logs,
            reward=reward.total,
            cumulative_reward=self._cumulative_reward,
            step_number=self._step_count,
            max_steps=scenario.max_steps,
            metadata={"reward_breakdown": reward.model_dump()},
        )

    def _handle_check_metrics(self, action: Action) -> Observation:
        scenario = self._scenario
        service = (action.service or "").strip()
        reward = Reward(reason=f"Checked metrics for {service}")

        if not service:
            reward.penalty = -0.02
            reward.total = -0.02
            reward.reason = "No service specified for check_metrics"
            self._cumulative_reward += reward.total
            return Observation(
                message="ERROR: Must specify a service name.",
                reward=reward.total,
                cumulative_reward=self._cumulative_reward,
                step_number=self._step_count,
                max_steps=scenario.max_steps,
                metadata={"reward_breakdown": reward.model_dump()},
            )

        metrics = scenario.service_metrics.get(service, [])
        if not metrics:
            reward.penalty = -0.01
            reward.total = -0.01
            reward.reason = f"No metrics for unknown service '{service}'"
            self._cumulative_reward += reward.total
            return Observation(
                message=f"No metrics for '{service}'. Available: {', '.join(sorted(scenario.service_metrics.keys()))}",
                reward=reward.total,
                cumulative_reward=self._cumulative_reward,
                step_number=self._step_count,
                max_steps=scenario.max_steps,
                metadata={"reward_breakdown": reward.model_dump()},
            )

        is_new = service not in self._investigated_services
        self._investigated_services.add(service)

        if is_new and service in scenario.relevant_services:
            reward.investigation_bonus = 0.05
            reward.reason = f"Gathered metrics for relevant service: {service}"
        elif is_new:
            reward.investigation_bonus = 0.01

        reward.total = reward.investigation_bonus + reward.penalty
        self._cumulative_reward += reward.total

        return Observation(
            message=f"Metrics for {service}:",
            metrics=metrics,
            reward=reward.total,
            cumulative_reward=self._cumulative_reward,
            step_number=self._step_count,
            max_steps=scenario.max_steps,
            metadata={"reward_breakdown": reward.model_dump()},
        )

    def _handle_run_command(self, action: Action) -> Observation:
        scenario = self._scenario
        command = (action.command or "").strip()
        reward = Reward(reason=f"Ran command: {command}")

        if not command:
            reward.penalty = -0.02
            reward.total = -0.02
            reward.reason = "No command specified"
            self._cumulative_reward += reward.total
            return Observation(
                message="ERROR: Must specify a command. Available commands:\n"
                + "\n".join(f"  - {cmd}" for cmd in sorted(scenario.available_commands.keys())),
                reward=reward.total,
                cumulative_reward=self._cumulative_reward,
                step_number=self._step_count,
                max_steps=scenario.max_steps,
                metadata={"reward_breakdown": reward.model_dump()},
            )

        # Match command (exact or partial)
        output = None
        matched_cmd = None
        for cmd, out in scenario.available_commands.items():
            if command.lower() == cmd.lower() or command.lower().startswith(cmd.lower()):
                output = out
                matched_cmd = cmd
                break

        if output is None:
            reward.penalty = -0.03
            reward.total = -0.03
            reward.reason = f"Unknown command: {command}"
            self._cumulative_reward += reward.total
            return Observation(
                message=f"Command not recognized: '{command}'\nAvailable commands:\n"
                + "\n".join(f"  - {cmd}" for cmd in sorted(scenario.available_commands.keys())),
                reward=reward.total,
                cumulative_reward=self._cumulative_reward,
                step_number=self._step_count,
                max_steps=scenario.max_steps,
                metadata={"reward_breakdown": reward.model_dump()},
            )

        is_new = matched_cmd not in self._commands_run
        self._commands_run.add(matched_cmd)

        # Check if this is a remediation command
        is_remediation = any(
            rem.lower() in matched_cmd.lower() for rem in scenario.valid_remediations
        )

        if is_new and is_remediation:
            reward.remediation_bonus = 0.12
            self._remediation_applied = True
            reward.reason = f"Applied remediation: {matched_cmd}"
        elif is_new:
            reward.investigation_bonus = 0.03
            reward.reason = f"Ran diagnostic command: {matched_cmd}"
        else:
            reward.reason = f"Re-ran command (no new reward): {matched_cmd}"

        reward.total = reward.investigation_bonus + reward.remediation_bonus + reward.penalty
        self._cumulative_reward += reward.total

        return Observation(
            message=f"$ {matched_cmd}\n{output}",
            command_output=output,
            reward=reward.total,
            cumulative_reward=self._cumulative_reward,
            step_number=self._step_count,
            max_steps=scenario.max_steps,
            metadata={"reward_breakdown": reward.model_dump()},
        )

    def _handle_escalate(self, action: Action) -> Observation:
        scenario = self._scenario
        team = (action.team or "").strip().lower()
        reward = Reward(reason=f"Escalated to {team}")

        if not team:
            reward.penalty = -0.02
            reward.total = -0.02
            reward.reason = "No team specified for escalation"
            self._cumulative_reward += reward.total
            return Observation(
                message="ERROR: Must specify a team to escalate to.",
                reward=reward.total,
                cumulative_reward=self._cumulative_reward,
                step_number=self._step_count,
                max_steps=scenario.max_steps,
                metadata={"reward_breakdown": reward.model_dump()},
            )

        is_new = team not in self._escalated_teams
        self._escalated_teams.add(team)

        if is_new and team in [t.lower() for t in scenario.correct_escalation_teams]:
            reward.communication_bonus = 0.06
            reward.reason = f"Correctly escalated to {team} team"
        elif is_new:
            reward.penalty = -0.03
            reward.reason = f"Escalated to irrelevant team: {team}"
        else:
            reward.reason = f"Already escalated to {team}"

        reward.total = reward.communication_bonus + reward.penalty
        self._cumulative_reward += reward.total

        return Observation(
            message=f"Escalation sent to {team} team. They have been paged and will join the incident channel.",
            reward=reward.total,
            cumulative_reward=self._cumulative_reward,
            step_number=self._step_count,
            max_steps=scenario.max_steps,
            metadata={"reward_breakdown": reward.model_dump()},
        )

    def _handle_communicate(self, action: Action) -> Observation:
        scenario = self._scenario
        message = (action.message or "").strip()
        reward = Reward(reason="Sent status update")

        if not message:
            reward.penalty = -0.01
            reward.total = -0.01
            reward.reason = "Empty communication"
            self._cumulative_reward += reward.total
            return Observation(
                message="ERROR: Must provide a message for the status update.",
                reward=reward.total,
                cumulative_reward=self._cumulative_reward,
                step_number=self._step_count,
                max_steps=scenario.max_steps,
                metadata={"reward_breakdown": reward.model_dump()},
            )

        self._communications += 1

        # Reward for first few communications, diminishing returns
        if self._communications <= 3:
            reward.communication_bonus = 0.03
            reward.reason = f"Status update #{self._communications} sent"
        else:
            reward.communication_bonus = 0.0
            reward.reason = "Additional status update (diminishing returns)"

        reward.total = reward.communication_bonus
        self._cumulative_reward += reward.total

        return Observation(
            message=f"Status update posted to #incident-{self._episode_id}:\n> {message}",
            reward=reward.total,
            cumulative_reward=self._cumulative_reward,
            step_number=self._step_count,
            max_steps=scenario.max_steps,
            metadata={"reward_breakdown": reward.model_dump()},
        )

    def _handle_resolve(self, action: Action) -> Observation:
        scenario = self._scenario
        root_cause = (action.root_cause or "").strip().lower()
        remediation = (action.remediation or "").strip().lower()
        reward = Reward(reason="Resolution attempt")

        self._resolve_attempts += 1

        if not root_cause or not remediation:
            reward.penalty = -0.05
            reward.total = -0.05
            reward.reason = "Resolution attempt missing root_cause or remediation"
            self._cumulative_reward += reward.total
            return Observation(
                message="ERROR: Must provide both root_cause and remediation to resolve.",
                reward=reward.total,
                cumulative_reward=self._cumulative_reward,
                step_number=self._step_count,
                max_steps=scenario.max_steps,
                metadata={"reward_breakdown": reward.model_dump()},
            )

        # Check root cause identification
        cause_match = any(
            cause.lower() in root_cause for cause in scenario.root_causes
        )

        # Check remediation
        fix_match = any(
            rem.lower() in remediation for rem in scenario.valid_remediations
        )

        if cause_match:
            self._root_cause_identified = True
            reward.diagnosis_bonus = 0.20
        else:
            reward.diagnosis_bonus = 0.0
            reward.penalty -= 0.05

        if fix_match:
            self._remediation_applied = True
            reward.remediation_bonus = 0.15
        else:
            reward.remediation_bonus = 0.0
            reward.penalty -= 0.05

        # Full resolution bonus
        if cause_match and fix_match:
            reward.total = reward.diagnosis_bonus + reward.remediation_bonus + 0.10  # completion bonus
            self._done = True
            self._cumulative_reward += reward.total

            # Efficiency bonus: fewer steps = higher score
            steps_used = self._step_count
            max_steps = scenario.max_steps
            efficiency = max(0.0, (max_steps - steps_used) / max_steps)
            efficiency_bonus = efficiency * 0.10
            reward.total += efficiency_bonus
            self._cumulative_reward += efficiency_bonus

            msg = (
                f"INCIDENT RESOLVED!\n"
                f"Root cause: {action.root_cause}\n"
                f"Remediation: {action.remediation}\n"
                f"Steps used: {steps_used}/{max_steps}\n"
                f"Efficiency bonus: +{efficiency_bonus:.3f}\n"
                f"Final score: {self._cumulative_reward:.3f}"
            )
        elif cause_match:
            reward.total = reward.diagnosis_bonus + reward.penalty
            self._cumulative_reward += reward.total
            msg = (
                f"Root cause correctly identified, but remediation '{action.remediation}' "
                f"is not effective. Try a different remediation approach."
            )
        elif fix_match:
            reward.total = reward.remediation_bonus + reward.penalty
            self._cumulative_reward += reward.total
            msg = (
                f"Remediation action noted, but the root cause '{action.root_cause}' "
                f"doesn't match the actual issue. Investigate further."
            )
        else:
            reward.total = reward.penalty
            self._cumulative_reward += reward.total
            msg = (
                f"Neither the root cause nor the remediation match. "
                f"Keep investigating — check logs and metrics for clues."
            )

        # Penalize excessive resolve attempts
        if self._resolve_attempts > 3:
            spam_penalty = -0.05
            reward.penalty += spam_penalty
            reward.total += spam_penalty
            self._cumulative_reward += spam_penalty

        return Observation(
            message=msg,
            done=self._done,
            reward=reward.total,
            cumulative_reward=self._cumulative_reward,
            step_number=self._step_count,
            max_steps=scenario.max_steps,
            metadata={"reward_breakdown": reward.model_dump()},
        )

    def _compute_timeout_reward(self) -> Reward:
        """Partial credit when the episode times out."""
        reward = Reward(reason="Episode timed out")

        # Partial credit for investigation
        if self._investigated_services:
            reward.investigation_bonus = 0.02 * len(self._investigated_services)

        # Partial credit for root cause identification
        if self._root_cause_identified:
            reward.diagnosis_bonus = 0.10

        # Partial credit for remediation
        if self._remediation_applied:
            reward.remediation_bonus = 0.05

        # Penalty for not resolving
        reward.penalty = -0.15

        reward.total = (
            reward.investigation_bonus
            + reward.diagnosis_bonus
            + reward.remediation_bonus
            + reward.penalty
        )
        return reward
