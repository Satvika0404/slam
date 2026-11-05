"""Ordered API-key failover.

Keys are tried strictly in the order they were configured and the pool sticks to the first
usable one until it fails or runs out ("finishes"); only then does it move on to the next. A key
that was merely rate limited for a short while comes back after the wait the API asked for.

Secret values live only in this module and are handed to the provider through ``secret()``. Every
report, repr and error uses the label ``key#N`` instead.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from enum import StrEnum


class KeyState(StrEnum):
    ACTIVE = "active"
    COOLING = "cooling"  # short rate limit: usable again after the wait the API reported
    EXHAUSTED = "exhausted"  # quota used up, or the wait is too long to be worth it this run
    REJECTED = "rejected"  # authentication or permission failure


@dataclass(slots=True)
class _Slot:
    label: str
    secret: str = field(repr=False)
    state: KeyState = KeyState.ACTIVE
    cooldown_until: float = 0.0
    strikes: int = 0
    calls: int = 0
    successes: int = 0
    rate_limited: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class KeyReport:
    """What may be shown about a key: never its value."""

    label: str
    state: str
    calls: int
    successes: int
    rate_limited: int
    input_tokens: int
    output_tokens: int


class KeyPool:
    """Thread-safe, clock-injectable failover over an ordered list of API keys."""

    def __init__(
        self,
        keys: Sequence[str],
        *,
        clock: Callable[[], float] = time.monotonic,
        max_wait_seconds: float = 90.0,
        default_cooldown_seconds: float = 20.0,
        max_strikes: int = 3,
    ) -> None:
        unique = tuple(dict.fromkeys(key for key in keys if key))
        if not unique:
            raise ValueError("at least one API key is required")
        self._slots = [_Slot(label=f"key#{n}", secret=key) for n, key in enumerate(unique, 1)]
        self._clock = clock
        self._max_wait = max_wait_seconds
        self._default_cooldown = default_cooldown_seconds
        self._max_strikes = max_strikes
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._slots)

    def __repr__(self) -> str:
        return f"KeyPool({', '.join(f'{r.label}={r.state}' for r in self.reports())})"

    def label(self, index: int) -> str:
        return self._slots[index].label

    def secret(self, index: int) -> str:
        return self._slots[index].secret

    def acquire(self, *, skip: Collection[int] = ()) -> int | None:
        """Index of the first usable key not in ``skip``, or ``None`` if there is none."""

        with self._lock:
            now = self._clock()
            for index, slot in enumerate(self._slots):
                if index in skip:
                    continue
                if slot.state is KeyState.COOLING and now >= slot.cooldown_until:
                    slot.state = KeyState.ACTIVE
                if slot.state is KeyState.ACTIVE:
                    slot.calls += 1
                    return index
            return None

    def seconds_until_available(self, *, skip: Collection[int] = ()) -> float | None:
        """Shortest remaining cooldown among cooling keys, or ``None`` if none is cooling."""

        with self._lock:
            now = self._clock()
            waits = [
                max(0.0, slot.cooldown_until - now)
                for index, slot in enumerate(self._slots)
                if index not in skip and slot.state is KeyState.COOLING
            ]
            return min(waits) if waits else None

    def report_success(self, index: int, *, input_tokens: int = 0, output_tokens: int = 0) -> None:
        with self._lock:
            slot = self._slots[index]
            slot.successes += 1
            slot.strikes = 0
            slot.input_tokens += input_tokens
            slot.output_tokens += output_tokens

    def report_rate_limited(self, index: int, retry_after: float | None) -> None:
        """A 429. A short wait cools the key down; a long or unknown-and-huge one retires it."""

        with self._lock:
            slot = self._slots[index]
            slot.rate_limited += 1
            wait = self._default_cooldown if retry_after is None else max(1.0, retry_after)
            if wait > self._max_wait:
                slot.state = KeyState.EXHAUSTED
                return
            slot.state = KeyState.COOLING
            slot.cooldown_until = self._clock() + wait

    def report_rejected(self, index: int) -> None:
        with self._lock:
            self._slots[index].state = KeyState.REJECTED

    def report_transient_failure(self, index: int) -> None:
        """A timeout / 5xx that survived its retries: after a few in a row the key is dropped."""

        with self._lock:
            slot = self._slots[index]
            slot.strikes += 1
            if slot.strikes >= self._max_strikes:
                slot.state = KeyState.EXHAUSTED

    @property
    def usable(self) -> bool:
        with self._lock:
            return any(slot.state in (KeyState.ACTIVE, KeyState.COOLING) for slot in self._slots)

    def reports(self) -> tuple[KeyReport, ...]:
        with self._lock:
            return tuple(
                KeyReport(
                    label=slot.label,
                    state=slot.state.value,
                    calls=slot.calls,
                    successes=slot.successes,
                    rate_limited=slot.rate_limited,
                    input_tokens=slot.input_tokens,
                    output_tokens=slot.output_tokens,
                )
                for slot in self._slots
            )
