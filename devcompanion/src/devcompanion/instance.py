"""One engine per workspace state directory.

Two `watch` processes on one workspace both tail the inbox, both rewrite findings.jsonl and
engine.json, and each reports the other's work as its own. It happened twice on 2026-09-14, both
times from a restart whose kill failed silently (docs/handoff.md). The guard is an exclusive
advisory lock on `<state>/engine.lock`, taken before the engine writes anything and held for the
life of the process. The kernel releases it when the process exits or dies, so a crash never
leaves a stale lock behind, and a reused pid cannot fool it the way a pid file can.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import IO


class AlreadyRunning(RuntimeError):
    def __init__(self, holder: str):
        self.holder = holder
        super().__init__(f"another engine (pid {holder}) holds this workspace")


def claim(state_dir: Path) -> IO[str]:
    """Take the workspace. Returns the open lock file; the lock lasts exactly as long as that file
    stays open, so the caller keeps a reference for as long as it runs."""
    state_dir.mkdir(parents=True, exist_ok=True)
    handle = open(state_dir / "engine.lock", "a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.seek(0)
        holder = handle.read().strip() or "unknown"
        handle.close()
        raise AlreadyRunning(holder) from None
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle
