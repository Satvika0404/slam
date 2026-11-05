"""Bounded runtime retries using named, locally supplied recovery handlers only."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class RecoveryAction(StrEnum):
    RETRY_PROVIDER = "retry_provider"
    RELOAD_CACHE = "reload_cache"
    REPARSE_SOURCE = "reparse_source"
    RECONSTRUCT_CASE = "reconstruct_case"


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    allowed_actions: tuple[RecoveryAction, ...] = (RecoveryAction.RETRY_PROVIDER,)
    max_attempts: int = 1
    time_budget_seconds: float = 10.0
    token_budget: int = 0

    def __post_init__(self) -> None:
        if any(not isinstance(action, RecoveryAction) for action in self.allowed_actions):
            raise ValueError("allowed_actions must use the RecoveryAction allowlist")
        if not 0 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be between 0 and 3 (at most 3)")
        if self.time_budget_seconds < 0 or self.token_budget < 0:
            raise ValueError("recovery budgets cannot be negative")


@dataclass(frozen=True, slots=True)
class RecoveryAttempt:
    attempt: int
    action: RecoveryAction
    outcome: str
    elapsed_ms: int
    token_units: int


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    succeeded: bool
    blocked: bool
    attempts: tuple[RecoveryAttempt, ...]
    result: object | None = None
    reason: str | None = None


Handler = Callable[[float, int], tuple[bool, object | None, int]]


def run_recovery(
    handlers: dict[RecoveryAction, Handler],
    policy: RecoveryPolicy,
) -> RecoveryResult:
    """Run only provided allowlisted callables; no shell or generated command path."""
    attempts: list[RecoveryAttempt] = []
    started = time.monotonic()
    tokens = 0
    for number, action in enumerate(policy.allowed_actions[: policy.max_attempts], start=1):
        if action not in handlers:
            attempts.append(RecoveryAttempt(number, action, "handler_missing", 0, 0))
            continue
        elapsed = time.monotonic() - started
        if elapsed >= policy.time_budget_seconds:
            return RecoveryResult(False, True, tuple(attempts), reason="time_budget_exhausted")
        ok, value, used = False, None, 0
        attempt_started = time.monotonic()
        try:
            deadline = started + policy.time_budget_seconds
            remaining_tokens = policy.token_budget - tokens
            ok, value, used = handlers[action](deadline, remaining_tokens)
            if used < 0:
                raise ValueError("recovery handler returned a negative token count")
            if tokens + used > policy.token_budget:
                elapsed_ms = int((time.monotonic() - attempt_started) * 1000)
                attempts.append(
                    RecoveryAttempt(number, action, "token_budget_exhausted", elapsed_ms, used)
                )
                return RecoveryResult(False, True, tuple(attempts), reason="token_budget_exhausted")
            tokens += used
            outcome = "recovered" if ok else "not_recovered"
        except Exception as exc:
            # Exception messages may include sensitive inputs; log only the type.
            outcome = f"error:{type(exc).__name__}"
        elapsed_ms = int((time.monotonic() - attempt_started) * 1000)
        if time.monotonic() - started > policy.time_budget_seconds:
            attempts.append(
                RecoveryAttempt(number, action, "time_budget_exhausted", elapsed_ms, used)
            )
            return RecoveryResult(False, True, tuple(attempts), reason="time_budget_exhausted")
        attempts.append(RecoveryAttempt(number, action, outcome, elapsed_ms, used))
        if ok:
            return RecoveryResult(True, False, tuple(attempts), value)
        if time.monotonic() - started > policy.time_budget_seconds:
            return RecoveryResult(False, True, tuple(attempts), reason="time_budget_exhausted")
    return RecoveryResult(False, True, tuple(attempts), reason="recovery_exhausted")
