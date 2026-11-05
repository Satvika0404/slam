"""Ordered key failover: sticky, sequential, never leaks a key value."""

from __future__ import annotations

import pytest
from slam.runtime.key_pool import KeyPool


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _keys(count: int = 4) -> list[str]:
    return [f"secret-value-{n}-" + "x" * 12 for n in range(1, count + 1)]


def test_first_usable_key_is_kept_until_it_fails() -> None:
    pool = KeyPool(_keys())
    assert [pool.acquire() for _ in range(3)] == [0, 0, 0]


def test_a_rejected_key_hands_over_to_the_next_in_order() -> None:
    pool = KeyPool(_keys())
    assert pool.acquire() == 0
    pool.report_rejected(0)
    assert pool.acquire() == 1
    pool.report_rejected(1)
    pool.report_rejected(2)
    assert pool.acquire() == 3
    pool.report_rejected(3)
    assert pool.acquire() is None
    assert not pool.usable


def test_short_rate_limit_cools_the_key_and_it_returns_afterwards() -> None:
    clock = Clock()
    pool = KeyPool(_keys(), clock=clock)
    assert pool.acquire() == 0
    pool.report_rate_limited(0, retry_after=30)
    assert pool.acquire() == 1  # key#1 is cooling, key#2 takes over
    assert pool.seconds_until_available(skip={1, 2, 3}) == pytest.approx(30)
    clock.now += 31
    assert pool.acquire() == 0  # earlier keys are preferred again once usable


def test_long_wait_means_the_quota_is_used_up_for_the_run() -> None:
    clock = Clock()
    pool = KeyPool(_keys(2), clock=clock, max_wait_seconds=90)
    pool.acquire()
    pool.report_rate_limited(0, retry_after=3600)  # e.g. a daily token quota
    clock.now += 7200
    assert pool.acquire() == 1
    assert [r.state for r in pool.reports()] == ["exhausted", "active"]


def test_missing_retry_after_uses_a_default_short_cooldown() -> None:
    clock = Clock()
    pool = KeyPool(_keys(1), clock=clock, default_cooldown_seconds=20)
    pool.acquire()
    pool.report_rate_limited(0, retry_after=None)
    assert pool.acquire() is None
    assert pool.seconds_until_available() == pytest.approx(20)


def test_repeated_transient_failures_retire_a_key_but_a_success_resets_the_count() -> None:
    pool = KeyPool(_keys(2), max_strikes=3)
    pool.report_transient_failure(0)
    pool.report_transient_failure(0)
    pool.report_success(0, input_tokens=5, output_tokens=2)
    pool.report_transient_failure(0)
    pool.report_transient_failure(0)
    assert pool.acquire() == 0
    pool.report_transient_failure(0)
    assert pool.acquire() == 1


def test_skip_set_lets_a_call_avoid_keys_that_just_failed() -> None:
    pool = KeyPool(_keys(3))
    assert pool.acquire(skip={0}) == 1
    assert pool.acquire(skip={0, 1, 2}) is None


def test_reports_count_usage_per_key_and_never_contain_the_value() -> None:
    keys = _keys(2)
    pool = KeyPool(keys)
    pool.acquire()
    pool.report_success(0, input_tokens=7, output_tokens=3)
    shown = repr(pool) + repr(pool.reports()) + str(pool.reports())
    assert all(key not in shown for key in keys)
    first = pool.reports()[0]
    assert (first.label, first.successes, first.input_tokens, first.output_tokens) == (
        "key#1",
        1,
        7,
        3,
    )


def test_blank_and_duplicate_keys_are_ignored_and_none_is_an_error() -> None:
    assert len(KeyPool(["a-key", "", "a-key", "b-key"])) == 2
    with pytest.raises(ValueError):
        KeyPool(["", ""])
