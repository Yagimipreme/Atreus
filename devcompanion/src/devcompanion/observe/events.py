"""Event schema v2 and JSONL log. Every producer (fswatch, Neovim, replay, CLI) emits these.

v1 said an event only records *that* a path changed, with content resolved from the snapshot
store. That is still true for the filesystem, but it was wrong for the editor: while a buffer
is unsaved, the editor holds the only copy of the content, and v1's decoder rebuilt only its
own small field list, so `text`, `dirty`, `session` and the rest were silently dropped on the
way in. v2 keeps them.

Two rules keep the log honest and small:

  * `text` never reaches events.jsonl. Content goes to the snapshot store and the event keeps
    `content_sha` and `content_origin`, so an event log plus a snapshot store is still a
    complete replayable input — including whether the content was an unsaved buffer.
  * Fields this version does not know about are preserved in `extra` rather than discarded, so
    a newer adapter talking to an older engine loses nothing.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 2

KINDS = {
    "file_changed", "buffer_saved", "buffer_changed", "cursor", "file_deleted", "baseline",
    "diagnostics", "lsp_result", "goal", "dismiss", "request", "session_end",
}

#: Kinds that carry editor-authored content for a path.
CONTENT_KINDS = {"buffer_changed", "buffer_saved"}


@dataclass
class Event:
    kind: str
    path: str = ""
    source: str = "cli"             # fswatch | nvim | cli | replay | git
    ts: float = field(default_factory=time.time)
    content_sha: str | None = None    # filled by the engine after snapshotting
    content_origin: str | None = None # filled by the engine: disk | git | editor
    line: int | None = None
    col: int | None = None
    seq: int | None = None          # monotonic id assigned by the engine
    schema_version: int = SCHEMA_VERSION

    # --- editor content (buffer_changed / buffer_saved) ---
    text: str | None = None         # canonical text; see devcompanion.canon
    text_sha: str | None = None     # adapter's hash of `text`, checked on intake
    doc_version: int | None = None  # vim.b.changedtick
    dirty: bool | None = None       # True while the buffer differs from the file on disk
    fileformat: str | None = None   # unix | dos | mac; part of the canonical form
    eol: bool | None = None         # trailing separator; part of the canonical form
    language: str | None = None     # filetype as the editor sees it

    # --- session identity ---
    workspace: str | None = None
    session: str | None = None      # unique per Neovim instance; opaque, compared not parsed
    editor_seq: int | None = None   # the adapter's own counter, kept beside the engine's

    # --- payloads for the non-content kinds ---
    items: list[dict] | None = None     # diagnostics
    request_id: str | None = None       # lsp_result
    method: str | None = None           # lsp_result
    status: str | None = None           # lsp_result
    what: str | None = None             # request
    finding_id: str | None = None       # dismiss
    scope: str | None = None            # dismiss

    extra: dict = field(default_factory=dict)   # anything a newer producer added

    # `goal` and `request` reuse `text` for their free-form statement; `path` is optional there.

    def as_dict(self) -> dict:
        d = asdict(self)
        extra = d.pop("extra", None) or {}
        return {**extra, **d}

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True)

    def for_log(self) -> str:
        """The log line. `text` is dropped: the bytes live in the snapshot store under
        `content_sha`, and keeping them here would make events.jsonl grow by a whole buffer
        on every keystroke pause."""
        d = self.as_dict()
        d.pop("text", None)
        return json.dumps(d, sort_keys=True)

    @classmethod
    def from_json(cls, line: str) -> "Event":
        d = json.loads(line)
        if not isinstance(d, dict) or "kind" not in d:
            raise ValueError("event must be a JSON object with a kind")
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d and k != "extra"}
        extra = {k: v for k, v in d.items() if k not in cls.__dataclass_fields__}
        if isinstance(d.get("extra"), dict):
            extra.update(d["extra"])
        e = cls(**known)
        e.extra = extra
        return e

    # ---- content helpers -------------------------------------------------
    def content(self) -> bytes | None:
        """The editor's bytes for this event, or None when it carries no text."""
        from ..canon import canonical
        if self.text is None:
            return None
        if isinstance(self.text, list):           # a tolerant producer may send lines
            return canonical(self.text, self.fileformat, True if self.eol is None else self.eol)
        return self.text.encode("utf-8", errors="surrogateescape")

    def content_mismatch(self) -> str | None:
        """Non-None when the adapter's `text_sha` disagrees with `text`: a producer bug, an
        encoding problem, or a truncated line. Reported, never silently trusted."""
        from ..canon import sha
        body = self.content()
        if body is None or not self.text_sha:
            return None
        actual = sha(body)
        return None if actual == self.text_sha else f"{self.text_sha} declared, {actual} actual"


def append(path: Path, ev: Event) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(ev.for_log() + "\n")


def read(path: Path) -> Iterator[Event]:
    if not path.exists():
        return
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                yield Event.from_json(line)


def tail(path: Path, poll_s: float = 0.2) -> Iterator[Event]:
    """Follow a JSONL inbox (what the Neovim plugin appends to). Blocking generator."""
    pos = 0
    while True:
        if path.exists():
            with path.open() as f:
                f.seek(pos)
                while True:
                    line = f.readline()
                    if not line.endswith("\n"):
                        break                       # partial line: wait for the rest
                    pos = f.tell()
                    if line.strip():
                        try:
                            yield Event.from_json(line)
                        except (ValueError, TypeError):
                            continue                # malformed producer line: ignore, keep tailing
        time.sleep(poll_s)
