"""
Reuse a grounded answer when the exact same question meets the exact same
calculation.

explain_decision() is a function of its arguments: the formatted result,
the question, the selected node, the node list, and the topic scope. When
all of those match an answer already given, the earlier answer is the
answer, already verified -- so it's returned without another model call.
That is common in practice: everyone viewing the demo clicks the same
chips against the same figures.

Only grounded model answers are kept. A deterministic fallback is cheap to
rebuild and may have been caused by a passing outage; caching it would keep
serving the fallback after the model is back.

In memory, per process, bounded, and short-lived -- like the rest of Fork's
per-process state.
"""

import hashlib
import json
import threading
import time
from collections import OrderedDict

MAX_ENTRIES = 512
TTL_SECONDS = 6 * 60 * 60

_entries: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()
_lock = threading.Lock()


def key_for(**parts) -> str:
    blob = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def get(key: str) -> dict | None:
    now = time.monotonic()
    with _lock:
        hit = _entries.get(key)
        if hit is None:
            return None
        stored_at, value = hit
        if now - stored_at > TTL_SECONDS:
            del _entries[key]
            return None
        _entries.move_to_end(key)
        return value


def put(key: str, value: dict) -> None:
    with _lock:
        _entries[key] = (time.monotonic(), value)
        _entries.move_to_end(key)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)


def clear() -> None:
    with _lock:
        _entries.clear()
