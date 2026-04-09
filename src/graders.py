"""Programmatic graders for each task. Score strictly between 0 and 1."""

from __future__ import annotations

from src.models import State

EPS = 1e-4  # ensures score is never exactly 0 or 1 after round(..., 4)


def _safe_score(value: float) -> float:
    """Clamp a raw score to the strictly open interval (0, 1) and round to 4dp.

    Guarantees: 0 < result < 1, i.e. result in {0.0001, 0.0002, ..., 0.9999}.
    This survives any serialisation / JSON round-trip that uses 4 decimal places.
    """
    return round(min(1.0 - EPS, max(EPS, float(value))), 4)


def grade_task(state: State) -> float:
    """Grade the agent's performance on a completed episode.

    Returns a score strictly between 0 and 1 (exclusive).

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

    # Clamp final score to strictly open interval (0, 1).
    # _safe_score applies min/max with EPS=1e-4 then rounds to 4dp,
    # so 0.0 → 0.0001 and 1.0 → 0.9999 — both pass the validator's
    # strict inequality check (0 < score < 1).
    return _safe_score(score)


def _expected_investigation_count(difficulty: str) -> int:
    # hard=3 matches the 3 relevant services (payment-processor, payment-db, message-queue)
    return {"easy": 2, "medium": 3, "hard": 3}.get(difficulty, 2)