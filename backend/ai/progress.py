"""
Where an Ask Fork answer is, while the student waits.

The AI layer reports real stages here -- understanding the question,
writing the explanation, checking its numbers, rewriting after a failed
check -- and a streaming endpoint forwards them to the browser. Nothing is
inferred from elapsed time: a stage is shown because the code reached it.

A context variable carries the listener, so the existing synchronous
functions report progress without growing a callback parameter, and code
that runs with no listener (tests, the JSON endpoints) pays nothing.

Also records how long each model call took, for the Server-Timing header
and the logs.
"""

import contextvars
import time
from collections.abc import Callable

UNDERSTANDING = "understanding"
WRITING = "writing"
CHECKING = "checking"
REWRITING = "rewriting"

_listener: contextvars.ContextVar[Callable[[str], None] | None] = contextvars.ContextVar(
    "fork_progress_listener", default=None
)
_partial: contextvars.ContextVar[Callable[[dict], None] | None] = contextvars.ContextVar(
    "fork_partial_listener", default=None
)
_timings: contextvars.ContextVar[list[tuple[str, float]] | None] = contextvars.ContextVar(
    "fork_ai_timings", default=None
)


def report(stage: str) -> None:
    listener = _listener.get()
    if listener is not None:
        listener(stage)


def listen(callback: Callable[[str], None]) -> contextvars.Token:
    return _listener.set(callback)


def listen_partial(callback: Callable[[dict], None]) -> contextvars.Token:
    """Receive an early, already-checked part of an answer -- currently the
    one-line direct answer -- before the rest is written."""
    return _partial.set(callback)


def partial_listener() -> Callable[[dict], None] | None:
    return _partial.get()


def start_timing() -> contextvars.Token:
    return _timings.set([])


def record(name: str, seconds: float) -> None:
    timings = _timings.get()
    if timings is not None:
        timings.append((name, seconds))


def timings() -> list[tuple[str, float]]:
    return list(_timings.get() or [])


class timed:
    """`with timed("intent"): ...` records the block's duration."""

    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        record(self.name, time.perf_counter() - self.start)
        return False


def server_timing_header(entries: list[tuple[str, float]]) -> str:
    """`intent;dur=2140, explain;dur=9310` -- visible in browser dev tools."""
    counts: dict[str, int] = {}
    parts = []
    for name, seconds in entries:
        counts[name] = counts.get(name, 0) + 1
        label = name if counts[name] == 1 else f"{name}-{counts[name]}"
        parts.append(f"{label};dur={seconds * 1000:.0f}")
    return ", ".join(parts)
