"""
Lightweight in-memory event bus for streaming agent step progress to the UI.

Each run_id gets an asyncio.Queue. Graph node wrappers call `publish()` after
each step completes; the SSE endpoint reads from the queue and pushes events
to the browser.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

_queues: Dict[str, asyncio.Queue] = {}


def get_queue(run_id: str) -> asyncio.Queue:
    if run_id not in _queues:
        _queues[run_id] = asyncio.Queue()
    return _queues[run_id]


def publish(run_id: str, event: Dict[str, Any]) -> None:
    """Push a step event into the run's queue (safe to call from sync code)."""
    q = get_queue(run_id)
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(q.put_nowait, event)
    except RuntimeError:
        # No running loop (e.g. unit tests) — fire-and-forget
        q.put_nowait(event)


def cleanup(run_id: str) -> None:
    _queues.pop(run_id, None)
