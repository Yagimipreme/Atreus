"""Debounce + coalesce + stale cancellation. Single worker keeps CPU cost bounded.

Policy: at most one pending task bundle per path. A newer snapshot of the same path replaces
the pending bundle (the old one is *cancelled*, recorded as such). While a task runs it may be
asked `is_stale()`; investigations call it between steps and abandon early.

Other kinds of work (`handlers`, e.g. proposing fixes) share the one worker, so they never run
beside an analysis on the same stores; each kind keeps its own one-pending-per-path slot, and only
an analysis submit moves what `is_stale()` compares against.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Pending:
    path: str
    sha: str
    seq: int
    due: float
    origin: str = "disk"          # where the content came from: disk | git | editor
    cancelled_shas: list[str] = field(default_factory=list)
    kind: str = "analysis"


class Scheduler:
    def __init__(self, run: Callable[[str, str, int, list[str], str], None], debounce_s: float = 0.4,
                 handlers: dict[str, Callable[[str, str, int], None]] | None = None):
        self.run = run
        self.handlers = handlers or {}
        self.debounce_s = debounce_s
        self._pending: "OrderedDict[tuple[str, str], Pending]" = OrderedDict()
        self._latest: dict[str, str] = {}
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self.stats = {"submitted": 0, "coalesced": 0, "ran": 0}

    def submit(self, path: str, sha: str, seq: int, origin: str = "disk", kind: str = "analysis") -> None:
        if kind != "analysis" and kind not in self.handlers:
            raise ValueError(f"no handler for {kind}")
        with self._lock:
            self.stats["submitted"] += 1
            if kind == "analysis":
                self._latest[path] = sha
            prev = self._pending.pop((path, kind), None)
            cancelled = (prev.cancelled_shas + [prev.sha]) if prev and prev.sha != sha else (prev.cancelled_shas if prev else [])
            if cancelled:
                self.stats["coalesced"] += 1
            self._pending[(path, kind)] = Pending(path, sha, seq, time.time() + self.debounce_s, origin, cancelled, kind)
        self._wake.set()

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._pending)

    def is_stale(self, path: str, sha: str) -> bool:
        with self._lock:
            return self._latest.get(path, sha) != sha

    def drain(self, wait: bool = True) -> int:
        """Run everything due. In replay (wait=False) runs immediately, in order."""
        ran = 0
        while True:
            with self._lock:
                if not self._pending:
                    return ran
                p = next(iter(self._pending.values()))
                if wait and p.due > time.time():
                    delay = p.due - time.time()
                else:
                    self._pending.pop((p.path, p.kind))
                    delay = None
            if delay is not None:
                time.sleep(delay)
                continue
            self.stats["ran"] += 1
            if p.kind == "analysis":
                self.run(p.path, p.sha, p.seq, p.cancelled_shas, p.origin)
            else:
                self.handlers[p.kind](p.path, p.sha, p.seq)
            ran += 1

    def serve_forever(self, stop: threading.Event) -> None:
        while not stop.is_set():
            self._wake.wait(timeout=0.5)
            self._wake.clear()
            self.drain(wait=True)
