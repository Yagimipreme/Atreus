"""Durable read position over the adapter's inbox. See docs/intake-watermark.md for the design.

`events.tail` re-reads from byte 0 on every restart, which replays the developer's editing
history as if it were happening now — a stale unsaved draft briefly becomes "the current code"
again. `Intake` fixes that with two mechanisms used together: a byte offset (cheap, but wrong
the moment the file is rotated or truncated) and a per-session high-water mark on the adapter's
own counter (correct even after the offset is reset, but too slow to use on its own since it
would mean scanning the whole file just to check identity). `events.py` stays a schema module;
this does not extend it.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Iterator

from ..canon import sha as sha_of
from ..view.index import write_atomic
from . import events as ev

SCHEMA_VERSION = 1
HEAD_BYTES = 4096       # cap on how much of the file identity-fingerprinting ever reads


def _adapter_seq(e: ev.Event) -> int | None:
    """The adapter's own per-session counter. On the wire this travels as `seq` -- the engine
    only renames it to `editor_seq` once `handle_event` has looked at it, and Intake reads the
    inbox before that ever happens. Mirrors the same fallback `Engine.handle_event` uses, so an
    event already carrying `editor_seq` (e.g. a replayed one) is honoured too."""
    return e.editor_seq if e.editor_seq is not None else e.seq


@dataclass
class Source:
    """Identity of the file an offset refers to. A byte offset alone can't tell a grown file
    from a replaced one; this is what lets Intake tell the difference.

    `head_sha` covers exactly `head_len` bytes, not a fixed amount: hashing a fixed 4096 bytes
    would report "replaced" for an ordinary append to any file that was shorter than that the
    last time it was fingerprinted (the common case for a workspace's first hour). `head_len` is
    the prefix guaranteed to have existed at both observation times -- see `Intake._fingerprint`.
    """
    device: int
    inode: int
    size: int
    head_len: int
    head_sha: str

    @classmethod
    def of(cls, path: Path, head_len: int) -> "Source | None":
        try:
            st = path.stat()
            with path.open("rb") as f:
                head = f.read(head_len) if head_len else b""
        except (FileNotFoundError, OSError):
            return None
        return cls(st.st_dev, st.st_ino, st.st_size, len(head), sha_of(head))

    def matches(self, other: "Source | None") -> bool:
        """Same file, not merely a file at the same path. `size` plays no part: a file that has
        only grown is still the same file, and that is the common case. `head_len == 0` means
        there was nothing to fingerprint yet (nothing had been read); device and inode alone
        decide, since comparing two empty hashes would otherwise vacuously agree for any file."""
        if other is None or self.device != other.device or self.inode != other.inode:
            return False
        if self.head_len == 0 or other.head_len == 0:
            return True
        return self.head_sha == other.head_sha


class Intake:
    """Durable read position in the adapter's inbox."""

    def __init__(self, state_dir: Path, inbox: Path, log=print):
        self.state_dir = state_dir
        self.inbox = inbox
        self.log = log
        self.path = state_dir / "intake.json"
        self.offset = 0
        # Volatile: how far `_scan` has actually read and yielded. `offset` only moves in
        # `accept()`, driven by the consumer; if `_scan` also seeked to `offset` on every pass,
        # anything read but not yet accepted would be handed out again on the next pass -- the
        # exact history-replay this module exists to prevent, just moved into steady state.
        self._read_pos = 0
        self.source: Source | None = None
        self.accepted: dict[str, int] = {}
        self._stats = {"resumed_at": 0, "skipped_known": 0, "malformed": 0, "resets": 0}
        self._reconciled = False       # reconciliation runs once, lazily, the first time the
                                       # inbox is observed to exist (it may not exist yet at
                                       # construction time if the adapter hasn't started)
        self._replaying_reset = False  # suppresses the regression log while re-reading bytes
                                       # we deliberately chose to see again after a reset
        self._logged_regression: set[str] = set()
        self._load()
        self._read_pos = self.offset      # start reading from wherever the durable mark says

    def seed(self, marks: dict[str, int]) -> None:
        """Fill in per-session marks this Intake has no record of at all -- from
        `events.jsonl`, which the caller (cmd_watch) reads because a fresh `intake.json` (a new
        workspace, or one whose state file was lost) otherwise means `accepted == {}`, and every
        event already durably logged by the engine gets replayed as if it were new. `Intake`
        does not read events.jsonl itself: that would make it depend on Engine, which the design
        explicitly rules out (replay and ingest have no inbox). Never overrides an existing
        mark -- intake.json, when present, is the authority on what has actually been declined
        from *this* inbox, which may disagree with the engine's log after a rotation."""
        for session, seq in marks.items():
            if session not in self.accepted:
                self.accepted[session] = seq

    # ---------- persistence ----------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            d = json.loads(self.path.read_text())
        except (ValueError, OSError):
            return
        if d.get("schema_version") != SCHEMA_VERSION:
            return                      # unrecognised shape: treat as absent, not as a crash
        try:
            self.offset = int(d.get("offset", 0))
            src = d.get("source")
            known = {f.name for f in fields(Source)}
            self.source = Source(**{k: v for k, v in src.items() if k in known}) if src else None
            self.accepted = dict(d.get("accepted", {}))
        except (TypeError, ValueError):
            # A malformed inbox *line* is expected and handled without fuss; a malformed state
            # file of our own making should not take the whole watcher down with it before it
            # even prints "watching". Fall back to "never read anything", same as a fresh one.
            self.offset, self.source, self.accepted = 0, None, {}

    def _persist(self) -> None:
        write_atomic(self.path, json.dumps({
            "schema_version": SCHEMA_VERSION,
            "offset": self.offset,
            "source": asdict(self.source) if self.source else None,
            "accepted": self.accepted,
            "updated_ts": time.time(),
        }, indent=1, sort_keys=True))

    def _refingerprint(self) -> None:
        """Recompute `source` against the inbox as it exists right now, fingerprinting exactly
        `min(HEAD_BYTES, offset)` bytes -- the prefix guaranteed to have existed the last time
        this offset was committed. Cheap (a handful of KB, at most) and correct regardless of
        how the file has grown since."""
        fresh = Source.of(self.inbox, min(HEAD_BYTES, self.offset))
        if fresh is not None:
            self.source = fresh

    # ---------- reconciliation ----------
    def _ensure_reconciled(self) -> None:
        """Validate the stored offset against the inbox as it exists right now. Runs once: the
        contract is "on startup", and settling it more than once would mean re-deciding the
        rotation/truncation question mid-stream, which is not a case this module needs to solve."""
        if self._reconciled:
            return
        # Probe exactly the prefix `offset` already vouches for -- when offset is 0 (a fresh
        # workspace, or right after a reset) that is zero bytes, and `matches()` correctly
        # treats "nothing to compare" as device+inode deciding alone, not as a mismatch.
        current = Source.of(self.inbox, min(HEAD_BYTES, self.offset))
        if current is None:
            return                      # adapter has not started yet; try again next pass
        self._reconciled = True
        if self.source is None:
            self.source = current       # first sight of this workspace: nothing to compare against
        elif not current.matches(self.source) or current.size < self.offset:
            # Replaced/rotated (identity differs) or truncated (same identity, shrunk below
            # our offset). Either way the bytes at `offset` are not the bytes we last read, so
            # the whole file is re-read; `accepted` is what keeps that safe.
            self._stats["resets"] += 1
            self.offset = 0
            self._read_pos = 0
            self.source = current
        else:
            self.source = current
        self._stats["resumed_at"] = self.offset
        self._replaying_reset = self._stats["resets"] > 0
        # Persisted immediately, not left for the next accept(): with no new traffic (the
        # common case right after a clean restart) nothing else would ever write this down,
        # and the same full re-scan -- and the same under-counted `resets` -- would repeat on
        # every subsequent start.
        self._persist()

    # ---------- reading ----------
    def _scan(self) -> Iterator[tuple[ev.Event, int]]:
        """One pass over whatever `_read_pos` has not yet reached. Stops at a partial final
        line or at end of file; never blocks.

        `_read_pos` advances here, for every line consumed -- yielded, skipped or malformed --
        so a line is never handed out twice by `_scan` itself regardless of whether the
        consumer has called `accept()` for it yet. Only `accept()` moves `self.offset`, the
        durable mark, for a *yielded* line: that one needs the consumer's word that it was
        actually handled, since a crash before it runs must re-deliver it on restart. A
        skipped or malformed line needs no such word -- declining a duplicate, or ignoring
        noise, is a decision `Intake` makes and finishes entirely on its own -- so `offset`
        catches up to those immediately, or a restart with no new traffic would silently
        re-earn the same "already known" verdict, and the same full re-scan, forever.

        That auto-advance is only safe while nothing yielded so far -- in this pass or an
        earlier one -- is still waiting on its `accept()`. `_read_pos` can already be ahead of
        `offset` when a pass starts (the tail thread races ahead of the consumer in `cmd_watch`
        by design), and a *later* skip in the byte stream must never let `offset` leapfrog an
        *earlier*, still-unaccepted yield -- that would silently count it as handled. So
        auto-banking only runs while `_read_pos == offset` at the point each line is read, and
        it turns off, for the rest of this pass, the moment anything is yielded."""
        self._ensure_reconciled()
        if not self.inbox.exists():
            return
        can_autobank = self._read_pos == self.offset
        caught_up_to = self._read_pos if can_autobank else None
        try:
            with self.inbox.open() as f:
                f.seek(self._read_pos)
                while True:
                    line = f.readline()
                    if not line.endswith("\n"):
                        break                       # partial line: wait for the rest
                    pos = f.tell()
                    self._read_pos = pos
                    text = line.strip()
                    if not text:
                        if can_autobank:
                            caught_up_to = pos
                        continue
                    try:
                        e = ev.Event.from_json(text)
                    except (ValueError, TypeError):
                        self._stats["malformed"] += 1
                        if can_autobank:
                            caught_up_to = pos
                        continue                    # malformed producer line: skip, keep scanning
                    adapter_seq = _adapter_seq(e)
                    if e.session and adapter_seq is not None:
                        hi = self.accepted.get(e.session)
                        if hi is not None and adapter_seq <= hi:
                            self._stats["skipped_known"] += 1
                            self._log_regression_once(e, adapter_seq, hi)
                            if can_autobank:
                                caught_up_to = pos
                            continue            # already taken, under this offset or a reset one
                    can_autobank = False        # an unaccepted yield now exists; stop banking
                    yield e, pos
        finally:
            # A `finally`, not code after the loop: an abandoned generator (closed mid-yield)
            # must still drop `_replaying_reset` and bank whatever was safely skipped, or the
            # regression log stays suppressed and a no-new-traffic restart's progress is lost.
            self._replaying_reset = False
            if caught_up_to is not None and caught_up_to > self.offset:
                self.offset = caught_up_to
                self._refingerprint()
                self._persist()

    def _log_regression_once(self, e: ev.Event, adapter_seq: int, hi: int) -> None:
        """A skip while replaying after a reset is the whole point of `accepted` and is not
        news. A skip on bytes we are reading for the first time means a session id recurred —
        the guarantee `util.session_id()` exists to provide has broken — and that is worth
        surfacing once, not silently dropping forever."""
        if self._replaying_reset or e.session in self._logged_regression:
            return
        self._logged_regression.add(e.session)
        self.log(f"intake: {e.session} sent seq {adapter_seq} but {hi} was already accepted "
                 f"from it, on bytes never read before — dropping as a duplicate rather than "
                 f"replaying history; session ids should never repeat")

    def follow(self, stop: threading.Event | None = None, poll_s: float = 0.2) -> Iterator[tuple[ev.Event, int]]:
        """Yield (event, offset_after_this_line) forever, starting from the stored offset and
        skipping events already accepted. Blocking."""
        while True:
            yield from self._scan()
            if stop is not None:
                if stop.wait(poll_s):
                    return
            else:
                time.sleep(poll_s)

    def drain(self) -> Iterator[tuple[ev.Event, int]]:
        """Same, but stops at end of file. For tests and for a one-shot catch-up."""
        yield from self._scan()

    def accept(self, event: ev.Event, offset: int) -> None:
        """Record that this event has been handled, and persist. Called by the consumer, after
        it has handled the event — never before, so a crash mid-handling re-delivers the event
        on restart instead of silently losing it.

        `max()` makes this monotonic: `_scan` can hand out events well ahead of the consumer
        (it advances `_read_pos`, not `offset`), so accepts can arrive out of the order they
        were read in (e.g. a debounced/coalesced bundle finishing out of turn). The durable
        mark must never walk backwards because a late accept for an earlier event showed up
        after a later one already advanced it.

        By now `Engine.handle_event` has usually already copied its `seq` into `editor_seq`;
        `_adapter_seq` falls back to `seq` regardless, so this works whether or not the caller
        ran the event through an Engine first."""
        self.offset = max(self.offset, offset)
        adapter_seq = _adapter_seq(event)
        if event.session and adapter_seq is not None:
            hi = self.accepted.get(event.session, -1)
            if adapter_seq > hi:
                self.accepted[event.session] = adapter_seq
        self._refingerprint()
        self._persist()

    @property
    def stats(self) -> dict:
        return dict(self._stats)
