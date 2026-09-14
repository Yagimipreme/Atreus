"""The content-view index: which bytes count as "the code" for each path, right now.

Until now the engine had one answer — whatever is on disk — and that answer is wrong for the
thing this project exists to do. While a developer is typing, the buffer and the file disagree,
and the interesting content is the one the file does not have yet.

So each path has up to two revisions:

    disk     the last content the file itself held (from the filesystem watcher, a save, or
             the committed version used as the first baseline)
    overlay  the editor's unsaved buffer, present only while that buffer is dirty

and one *effective* revision, which is the overlay when there is one and the disk revision
otherwise. Analysis reads the effective revision; tools that shell out (pytest, rg) can only
see the disk revision, so anything derived from them is labelled as saved-revision evidence.

An analysis manifest is the set of effective revisions a claim was computed from. It is what
makes a finding checkable later: same manifest, same answer.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..canon import sha as sha_of
from ..snapshot.store import ON_DISK, SnapshotStore


@dataclass
class Revision:
    """One observed state of one path."""
    sha: str
    origin: str                      # disk | git | editor
    ts: float = field(default_factory=time.time)
    doc_version: int | None = None   # editor only: vim.b.changedtick
    session: str | None = None       # editor only: which Neovim instance
    language: str | None = None

    @property
    def dirty(self) -> bool:
        return self.origin == "editor"


class ContentView:
    def __init__(self, root: Path, snap: SnapshotStore, state_dir: Path, replay: bool = False):
        self.root = root
        self.snap = snap
        self.replay = replay
        self.path = state_dir / "view.json"
        self.overlay: dict[str, Revision] = {}
        self.session: str | None = None
        self.diagnostics: dict[str, list[dict]] = {}
        self._load()

    # ---------- persistence ----------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            d = json.loads(self.path.read_text())
        except (ValueError, OSError):
            return
        self.session = d.get("session")
        self.overlay = {k: Revision(**v) for k, v in d.get("overlay", {}).items()
                        if self.snap.has(v.get("sha", ""))}
        self.diagnostics = d.get("diagnostics", {})

    def persist(self) -> None:
        write_atomic(self.path, json.dumps({
            "session": self.session,
            "overlay": {k: asdict(v) for k, v in self.overlay.items()},
            "diagnostics": self.diagnostics,
        }, indent=1, sort_keys=True))

    # ---------- intake ----------
    def adopt_session(self, session: str | None) -> bool:
        """A different Neovim instance is now the one talking to us. Its predecessor's unsaved
        buffers are gone with it, so those overlays are dropped rather than left to rot."""
        if not session or session == self.session:
            return False
        self.session = session
        self.overlay.clear()
        return True

    def end_session(self, session: str | None) -> list[str]:
        """That editor is gone, and its unsaved buffers went with it. The effective revision
        of each affected path falls back to the file on disk. Returns those paths so the
        caller can re-judge them: claims derived from content that no longer exists anywhere
        must not be left standing."""
        dropped = [p for p, r in self.overlay.items()
                   if session is None or r.session is None or r.session == session]
        for p in dropped:
            del self.overlay[p]
        if session is None or session == self.session:
            self.session = None
        return sorted(dropped)

    def record_disk(self, path: str, sha: str, origin: str = "disk") -> None:
        """The file itself now holds `sha`. Any overlay for it that held the same bytes was
        just saved; an overlay with *different* bytes survives, because the developer may have
        edited on top of a save (or another writer touched the file underneath them)."""
        del origin                    # recorded in the snapshot history, not duplicated here
        ov = self.overlay.get(path)
        if ov is not None and ov.sha == sha:
            del self.overlay[path]

    def record_editor(self, path: str, sha: str, dirty: bool, doc_version: int | None = None,
                      session: str | None = None, language: str | None = None) -> None:
        if not dirty:
            self.overlay.pop(path, None)   # a clean buffer is the file; disk is authoritative
            return
        self.overlay[path] = Revision(sha, "editor", time.time(), doc_version, session, language)

    def record_diagnostics(self, path: str, items: list[dict]) -> None:
        """Empty means "all clear now", which is information, so it is stored, not skipped."""
        self.diagnostics[path] = items

    def forget(self, path: str) -> None:
        self.overlay.pop(path, None)
        self.diagnostics.pop(path, None)

    # ---------- queries ----------
    def disk_revision(self, path: str) -> Revision | None:
        sha = self.snap.latest(path, ON_DISK)
        if sha:
            return Revision(sha, "disk")
        if self.replay:
            return None
        p = self.root / path
        if p.exists():
            try:
                return Revision(sha_of(p.read_bytes()), "disk")
            except OSError:
                return None
        return None

    def effective(self, path: str) -> Revision | None:
        return self.overlay.get(path) or self.disk_revision(path)

    def baseline(self, path: str, sha: str, origin: str) -> str | None:
        """What this state should be compared against.

        For an unsaved buffer that is the last saved content, so the developer sees "what I
        have changed since I saved", not "what I changed since the previous keystroke pause" —
        which would split one edit across several debounce windows and report it as noise.
        For a save it is the previous saved content, as before.
        """
        if origin == "editor":
            disk = self.disk_revision(path)
            return disk.sha if disk and disk.sha != sha else None
        return self.snap.previous(path, sha, ON_DISK)

    def read(self, path: str) -> bytes | None:
        """The effective bytes for a path: overlay first, then disk."""
        rev = self.effective(path)
        if rev is not None:
            body = self.snap.get(rev.sha)
            if body is not None:
                return body
        if self.replay:
            latest = self.snap.latest(path)
            return self.snap.get(latest) if latest else None
        p = self.root / path
        try:
            return p.read_bytes() if p.exists() else None
        except OSError:
            return None

    def dirty_paths(self) -> list[str]:
        return sorted(self.overlay)

    def is_dirty(self, path: str) -> bool:
        rev = self.overlay.get(path)
        if rev is None:
            return False
        disk = self.disk_revision(path)
        return disk is None or disk.sha != rev.sha

    def manifest(self, paths) -> dict[str, dict]:
        """The analysis manifest: for each path, the revision the analysis actually read."""
        out: dict[str, dict] = {}
        for path in sorted(set(paths)):
            rev = self.effective(path)
            if rev is None:
                continue
            out[path] = {"sha": rev.sha, "origin": rev.origin, "dirty": rev.dirty}
            if rev.doc_version is not None:
                out[path]["doc_version"] = rev.doc_version
        return out


def write_atomic(path: Path, data: str) -> None:
    """Write via a sibling temp file and rename. Readers poll these files without locking, so
    they must never observe a half-written one; rename within a directory is atomic.

    The temp name includes the pid and a random suffix: two threads (the scheduler worker and
    a periodic publisher, say) can both be mid-write_atomic on the same `path` at once, and a
    shared fixed temp name means one truncates the other's in-flight file out from under it --
    the loser's `os.replace` then raises `FileNotFoundError` on a name that no longer exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(data)
    os.replace(tmp, path)
