"""Opt-in execution telemetry; shared engine signatures and decisions stay unchanged."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

Observer = Callable[[str, dict[str, Any]], None]
_observer: ContextVar[Observer | None] = ContextVar("slam_execution_observer", default=None)


@contextmanager
def observe(observer: Observer) -> Iterator[None]:
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


def emit(event: str, **payload: Any) -> None:
    observer = _observer.get()
    if observer is not None:
        observer(event, payload)
