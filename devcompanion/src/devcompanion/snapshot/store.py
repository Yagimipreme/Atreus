"""Content-addressed snapshot store.

objects/<sha>          raw file bytes
history/<path-key>     JSONL: {"sha","ts","seq","origin"} per observed state of a path
freeze/<name>          JSON map path -> sha (a named, frozen codebase view; Compare works
                       against these; Follow == "latest")
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

#: Where a state came from. Content that is also on disk (`disk`, `git`) is what tools such as
#: pytest and rg actually see; `editor` content exists only in an unsaved buffer. Keeping the
#: distinction in the history is what lets the engine answer "what was last saved?" later.
ON_DISK = ("disk", "git")


@dataclass
class Put:
    sha: str
    previous: str | None
    changed: bool          # content differs from the previous observed state
    origin_changed: bool   # same bytes, but they moved between editor and disk (i.e. a save)


def sha_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


class SnapshotStore:
    def __init__(self, root: Path):
        self.root = root
        (root / "objects").mkdir(parents=True, exist_ok=True)
        (root / "history").mkdir(exist_ok=True)
        (root / "freeze").mkdir(exist_ok=True)

    def _hist(self, path: str) -> Path:
        return self.root / "history" / (hashlib.sha1(path.encode()).hexdigest()[:20] + ".jsonl")

    def put(self, path: str, data: bytes, seq: int | None = None, origin: str = "disk") -> Put:
        """Store current content and record the state. A save that changes nothing still
        records a state, because moving the same bytes from the editor onto disk is news:
        tools that read the working tree can run against it now."""
        sha = sha_of(data)
        obj = self.root / "objects" / sha
        if not obj.exists():
            obj.write_bytes(data)
        hist = self.history(path)
        last = hist[-1] if hist else None
        prev = last["sha"] if last else None
        changed = prev != sha
        origin_changed = bool(last) and not changed and last.get("origin", "disk") != origin
        if changed or origin_changed:
            with self._hist(path).open("a") as f:
                f.write(json.dumps({"sha": sha, "ts": time.time(), "seq": seq,
                                    "path": path, "origin": origin}) + "\n")
        return Put(sha, prev, changed, origin_changed)

    def get(self, sha: str) -> bytes | None:
        obj = self.root / "objects" / sha
        return obj.read_bytes() if obj.exists() else None

    def has(self, sha: str) -> bool:
        return (self.root / "objects" / sha).exists()

    def history(self, path: str) -> list[dict]:
        h = self._hist(path)
        if not h.exists():
            return []
        return [json.loads(l) for l in h.read_text().splitlines() if l.strip()]

    def known_paths(self) -> list[str]:
        out = []
        for h in (self.root / "history").glob("*.jsonl"):
            first = h.read_text().splitlines()[0]
            out.append(json.loads(first)["path"])
        return sorted(out)

    def latest(self, path: str, origin: tuple[str, ...] | None = None) -> str | None:
        """Most recent observed sha, optionally restricted to states of a given origin —
        `latest(p, ON_DISK)` is "what the file on disk last held"."""
        for h in reversed(self.history(path)):
            if origin is None or h.get("origin", "disk") in origin:
                return h["sha"]
        return None

    def previous(self, path: str, sha: str, origin: tuple[str, ...] | None = None) -> str | None:
        """The sha observed just before `sha` for this path (None on first sight). With
        `origin`, the previous state *of that origin* with different content, which is the
        baseline a saved change should be judged against."""
        hist = self.history(path)
        idx = next((i for i in range(len(hist) - 1, -1, -1) if hist[i]["sha"] == sha), None)
        if idx is None:
            return None
        for h in reversed(hist[:idx]):
            if origin is not None and h.get("origin", "disk") not in origin:
                continue
            if h["sha"] != sha:
                return h["sha"]
        return None

    # --- Freeze / Follow / Compare (kept in architecture; minimal now) ---
    def freeze(self, name: str, paths: dict[str, str]) -> None:
        (self.root / "freeze" / f"{name}.json").write_text(json.dumps(paths, indent=1, sort_keys=True))

    def frozen(self, name: str) -> dict[str, str] | None:
        p = self.root / "freeze" / f"{name}.json"
        return json.loads(p.read_text()) if p.exists() else None
