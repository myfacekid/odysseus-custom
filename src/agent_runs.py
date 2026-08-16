"""Detached agent-run manager.

Keeps an agent/chat stream running server-side after the SSE client disconnects
(tab close, navigate away, refresh). The streaming generator is drained by a
background asyncio task into a per-session replay buffer; SSE clients SUBSCRIBE
to that buffer (replay everything so far, then live). Closing the SSE only drops
the subscriber — the drain task keeps going.

Also holds per-run steer queues and coordinates tool-approval cancels on stop.
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

logger = logging.getLogger(__name__)


class _Run:
    __slots__ = (
        "buffer",
        "subscribers",
        "status",
        "task",
        "evict_task",
        "steer_queue",
        "owner",
    )

    def __init__(self) -> None:
        self.buffer: list = []          # ordered SSE event strings (replay log)
        self.subscribers: set = set()   # one asyncio.Queue per connected client
        self.status: str = "running"    # running | done | error | stopped
        self.task: Optional[asyncio.Task] = None
        self.evict_task: Optional[asyncio.Task] = None
        self.steer_queue: List[Dict[str, Any]] = []
        self.owner: Optional[str] = None


_RUNS: Dict[str, _Run] = {}

_EVICT_GRACE_S = 180


def _publish(run: _Run, ev: str) -> None:
    """Append one SSE event and fan it out to every live subscriber."""
    run.buffer.append(ev)
    seq = len(run.buffer) - 1
    for q in list(run.subscribers):
        try:
            q.put_nowait((seq, ev))
        except Exception:
            pass


def _schedule_evict(session_id: str) -> None:
    """(Re)arm a grace-period eviction for a terminal run with no subscribers."""
    run = _RUNS.get(session_id)
    if run is None:
        return
    if run.evict_task and not run.evict_task.done():
        run.evict_task.cancel()

    async def _evict(run_ref: _Run) -> None:
        try:
            await asyncio.sleep(_EVICT_GRACE_S)
        except asyncio.CancelledError:
            return
        cur = _RUNS.get(session_id)
        if cur is run_ref and cur.status != "running" and not cur.subscribers:
            _RUNS.pop(session_id, None)

    run.evict_task = asyncio.create_task(_evict(run))


def is_active(session_id: str) -> bool:
    r = _RUNS.get(session_id)
    return bool(r and r.status == "running")


def get_status(session_id: str) -> Optional[str]:
    r = _RUNS.get(session_id)
    return r.status if r else None


def get_run(session_id: str) -> Optional[_Run]:
    return _RUNS.get(session_id)


def enqueue_steer(
    session_id: str,
    text: str,
    *,
    mode: str = "redirect",
) -> Optional[Dict[str, Any]]:
    """Queue a mid-run steer. Returns the item, or None if no active run."""
    run = _RUNS.get(session_id)
    if not run or run.status != "running":
        return None
    body = (text or "").strip()
    if not body:
        return None
    item = {
        "id": uuid.uuid4().hex,
        "text": body,
        "mode": mode or "redirect",
        "created_at": time.time(),
    }
    run.steer_queue.append(item)
    _publish(
        run,
        f"data: {json.dumps({'type': 'steer_queued', 'id': item['id'], 'text': body, 'pending': len(run.steer_queue)})}\n\n",
    )
    return item


def clear_steer_queue(session_id: str) -> List[Dict[str, Any]]:
    """Drop pending steers; return what was cleared (for restoring to composer)."""
    run = _RUNS.get(session_id)
    if not run:
        return []
    cleared = list(run.steer_queue)
    run.steer_queue.clear()
    return cleared


def pop_steers_coalesced(session_id: str) -> Optional[Dict[str, Any]]:
    """Pop all pending steers as one coalesced item, or None."""
    run = _RUNS.get(session_id)
    if not run or not run.steer_queue:
        return None
    items = list(run.steer_queue)
    run.steer_queue.clear()
    if len(items) == 1:
        return items[0]
    bullets = "\n".join(f"- {it['text']}" for it in items)
    return {
        "id": uuid.uuid4().hex,
        "text": bullets,
        "mode": "redirect",
        "created_at": time.time(),
        "coalesced_ids": [it["id"] for it in items],
    }


async def _drain(session_id: str, agen: AsyncGenerator[str, None],
                 prev_task: Optional[asyncio.Task] = None) -> None:
    """Pull every event from the wrapped generator into the run buffer."""
    run = _RUNS.get(session_id)
    if run is None:
        return
    if prev_task is not None and not prev_task.done():
        try:
            await asyncio.wait({prev_task})
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
    try:
        async for ev in agen:
            _publish(run, ev)
        if run.status == "running":
            run.status = "done"
    except asyncio.CancelledError:
        run.status = "stopped"
        try:
            from src.tool_permissions import get_approval_registry

            await get_approval_registry().cancel_session(session_id)
        except Exception:
            pass
        try:
            await agen.aclose()
        except Exception:
            pass
    except Exception as e:
        logger.error("[agent-run] %s failed: %s", session_id, e, exc_info=True)
        run.status = "error"
        _publish(
            run,
            "event: error\n"
            f"data: {json.dumps({'error': 'Agent run failed before completion.', 'status': 500})}\n\n",
        )
        _publish(run, "data: [DONE]\n\n")
    finally:
        for q in list(run.subscribers):
            try:
                q.put_nowait((None, None))
            except Exception:
                pass
        _schedule_evict(session_id)


def start(
    session_id: str,
    agen: AsyncGenerator[str, None],
    *,
    owner: Optional[str] = None,
) -> _Run:
    """Start a detached run draining `agen` for a session."""
    prev = _RUNS.get(session_id)
    prev_task: Optional[asyncio.Task] = None
    if prev:
        if prev.task and not prev.task.done():
            prev.task.cancel()
            prev_task = prev.task
        if prev.evict_task and not prev.evict_task.done():
            prev.evict_task.cancel()
    run = _Run()
    run.owner = owner
    _RUNS[session_id] = run
    run.task = asyncio.create_task(_drain(session_id, agen, prev_task))
    return run


async def subscribe(session_id: str) -> AsyncGenerator[str, None]:
    """Replay the run's buffer from the start, then stream live until it ends."""
    run = _RUNS.get(session_id)
    if run is None:
        return
    q: asyncio.Queue = asyncio.Queue()
    run.subscribers.add(q)
    if run.evict_task and not run.evict_task.done():
        run.evict_task.cancel()
    try:
        next_seq = 0
        while next_seq < len(run.buffer):
            yield run.buffer[next_seq]
            next_seq += 1
        if run.status != "running":
            return
        while True:
            seq, ev = await q.get()
            if seq is None:
                while next_seq < len(run.buffer):
                    yield run.buffer[next_seq]
                    next_seq += 1
                break
            if seq >= next_seq:
                yield ev
                next_seq = seq + 1
    finally:
        run.subscribers.discard(q)
        if not run.subscribers and run.status != "running":
            _schedule_evict(session_id)


def stop(session_id: str) -> bool:
    """Cancel an in-flight run (the wrapped generator saves its partial)."""
    run = _RUNS.get(session_id)
    if run and run.task and not run.task.done():
        clear_steer_queue(session_id)
        run.task.cancel()
        return True
    return False
