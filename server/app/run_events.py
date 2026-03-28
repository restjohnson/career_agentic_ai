"""
Lightweight in-memory event bus for streaming agent step progress to the UI.

Each run_id gets an asyncio.Queue. Graph node wrappers call `publish()` after
each step completes; the SSE endpoint reads from the queue and pushes events
to the browser.
"""
from __future__ import annotations

import asyncio
import queue
from typing import Any, Dict

_queues: Dict[str, queue.Queue] = {}


def get_queue(run_id: str) -> queue.Queue:
    if run_id not in _queues:
        _queues[run_id] = queue.Queue()
    return _queues[run_id]


def publish(run_id: str, event: Dict[str, Any]) -> None:
    """Push a step event into the run's queue (thread-safe)."""
    q = get_queue(run_id)
    q.put(event)


def cleanup(run_id: str) -> None:
    _queues.pop(run_id, None)
