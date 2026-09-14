"""Editor-independent producer: inotify (via watchdog) -> Event queue."""
from __future__ import annotations

import queue
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .events import Event

IGNORE_DIRS = {".git", ".companion", "__pycache__", ".venv", "node_modules", ".mypy_cache", ".pytest_cache"}


def _ignored(p: Path) -> bool:
    return any(part in IGNORE_DIRS for part in p.parts)


class _Handler(FileSystemEventHandler):
    # Paired with None: this producer has no byte offset into an inbox, so it carries nothing
    # for Intake.accept() to commit. cmd_watch tells the two producers apart by this alone.
    def __init__(self, q: "queue.Queue[tuple[Event, None]]", suffixes: tuple[str, ...]):
        self.q, self.suffixes = q, suffixes

    def _emit(self, kind: str, src: str) -> None:
        p = Path(src)
        if p.suffix in self.suffixes and not _ignored(p):
            self.q.put((Event(kind=kind, path=str(p), source="fswatch"), None))

    def on_modified(self, e):  # noqa: D102
        if not e.is_directory:
            self._emit("file_changed", e.src_path)

    def on_created(self, e):  # noqa: D102
        if not e.is_directory:
            self._emit("file_changed", e.src_path)

    def on_moved(self, e):  # noqa: D102
        if not e.is_directory:
            self._emit("file_changed", e.dest_path)

    def on_deleted(self, e):  # noqa: D102
        if not e.is_directory:
            self._emit("file_deleted", e.src_path)


def start(root: Path, q: "queue.Queue[tuple[Event, None]]", suffixes: tuple[str, ...] = (".py",)) -> Observer:
    obs = Observer()
    obs.schedule(_Handler(q, suffixes), str(root), recursive=True)
    obs.daemon = True
    obs.start()
    return obs
