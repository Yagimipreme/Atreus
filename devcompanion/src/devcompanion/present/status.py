"""`engine.json`: is anything running, what is it doing, and can it answer with a model.

The adapter reads this to decide what to say in the panel's header. Every field has a value
even when a subsystem is off, because "unavailable" is an ordinary state here and the pane
should never have to render a blank where an answer belongs.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from .. import __version__
from ..view.index import write_atomic

SCHEMA_VERSION = 1
STARTED_TS = time.time()

#: What "nothing to report" looks like — replay and ingest never see an inbox, and the pane
#: still needs a value to render rather than a gap where one belongs.
NO_INTAKE = {"offset": 0, "resumed_at": 0, "skipped_known": 0, "malformed": 0, "resets": 0}


def snapshot(*, workspace: Path, state: str, last_event_seq: int, pending_tasks: int,
             session: str | None, dirty: list[str], findings: int, model: dict | None,
             revisions: dict | None = None, context: dict | None = None,
             last_error: str | None = None, intake: dict | None = None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "pid": os.getpid(),
        "started_ts": STARTED_TS,
        "heartbeat_ts": time.time(),
        "version": __version__,
        "state": state,                     # idle | working | paused
        "workspace": str(workspace),
        "session": session,                 # the editor instance we are following, if any
        "last_event_seq": last_event_seq,
        "pending_tasks": pending_tasks,
        "dirty_buffers": dirty,             # paths whose analysed content is not on disk yet
        "revisions": revisions or {},        # path -> {sha, origin, dirty}: the analysis manifest,
                                            # so the editor can tell whether we have caught up
                                            # with the buffer in front of the developer
        "findings": findings,
        "model": model or {"name": None, "backend": None, "status": "disabled"},
        "context": context or {"backend": "qmd", "status": "disabled", "passages": 0},
        "last_error": last_error,
        "intake": intake or NO_INTAKE,   # offset, resumed_at, skipped_known, malformed, resets
    }


def write(out_dir: Path, data: dict) -> None:
    import json
    write_atomic(out_dir / "engine.json", json.dumps(data, indent=1, sort_keys=True))
