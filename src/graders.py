"""Programmatic graders for each task. Score 0.0–1.0."""

from __future__ import annotations

from src.models import State


def grade_task(state: State) -> float:
    """Grade the agent's performance on a completed episode.

    Returns a score between 0.0 and 1.0.

    Scoring breakdown:
    - Investigation thoroughness: 0.0–0.25
    - Root cause identification: 0.0–0.25
    - Remediation effectiveness: 0.0–0.25
    - Communication & process: 0.0–0.10
    - Efficiency (steps used): 0.0–0.15
    """
    score = 0.0

    # ── Investigation (0.25) ──────────────────────────────────────────
    expected_services = _expected_investigation_count(state.task_difficulty)
    investigated = len(state.investigated_services)
    investigation_ratio = min(1.0, investigated / max(1, expected_services))
    score += 0.25 * investigation_ratio

    # ── Root cause (0.25) ─────────────────────────────────────────────
    if state.root_cause_identified:
        score += 0.25

    # ── Remediation (0.25) ────────────────────────────────────────────
    if state.remediation_applied:
        score += 0.25

    # ── Communication & escalation (0.10) ─────────────────────────────
    comm_score = 0.0
    if state.communications_sent >= 1:
        comm_score += 0.04
    if state.communications_sent >= 2:
        comm_score += 0.02
    if len(state.escalated_teams) >= 1:
        comm_score += 0.04
    score += min(0.10, comm_score)

    # ── Efficiency (0.15) ─────────────────────────────────────────────
    if state.done and state.root_cause_identified and state.remediation_applied:
        steps_ratio = state.step_count / max(1, state.max_steps)
        efficiency = max(0.0, 1.0 - steps_ratio)
        score += 0.15 * efficiency

    return round(min(1.0, max(0.0, score)), 4)


def _expected_investigation_count(difficulty: str) -> int:
    # hard=3 matches the 3 relevant services (payment-processor, payment-db, message-queue)
    return {"easy": 2, "medium": 3, "hard": 3}.get(difficulty, 2)
