# Durable intake watermark

Status: implemented, 2026-09-14. See `src/devcompanion/observe/intake.py`,
`tests/test_intake.py`, and the restart checks in `scripts/check-workflow.py`.

## The problem

`companion watch` tails `<workspace>/.companion/inbox.jsonl` from byte 0 every time it starts
(`observe/events.py:tail`, `pos = 0`). Nothing records how far the engine has already read. So
an engine restart re-reads the entire editing history of the session.

This is not merely wasteful. Re-reading replays the past as if it were the present:

    buffer_changed  calc.py = A      (unsaved draft)
    buffer_changed  calc.py = B      (unsaved, finished edit)
    buffer_saved    calc.py = B

On restart the engine processes all three again. The first line stores A as the current
content, schedules an investigation of A, and marks every claim that depended on B stale.
For a moment the board asserts things about a draft the developer left behind minutes ago.
It converges again once B is replayed, but "converges eventually" is exactly the property
this project promises not to rely on. Contract invariant 4 already claims the fix exists:

> Sequence numbers are monotonic per session; the engine tracks a watermark and never
> reprocesses.

It does not. This is that watermark.

## Prerequisite: session ids are not unique

`util.session_id()` is `string.format("%08x", math.random(0, 0xffffffff))`. LuaJIT does not
seed `math.random`, so **every Neovim instance on a machine returns the same id**. Verified:

    $ for i in 1 2 3; do nvim --headless -u NONE \
        -c 'lua io.write(require("companion.util").session_id(), "\n")' -c 'qa!'; done
    cb511a84
    cb511a84
    cb511a84

Every event in every log this project has produced carries `session: "cb511a84"`.

A watermark keyed on `(session, seq)` is only sound if a new editor gets a new session id.
With a constant id, a restarted editor starts its counter at 1 again and the watermark would
reject everything it sends — silently, for the whole session. So this is fixed first, and it
is fixed by construction rather than by better randomness:

```lua
-- Unique per Neovim instance without relying on math.random, which LuaJIT does not seed.
-- Two instances cannot share a pid at the same second, and a reused pid cannot recur within
-- the same second, so (start time, pid) is unique on a machine.
function M.session_id()
  return string.format("%x-%x", os.time(), vim.fn.getpid())
end
```

The contract's description of `session` changes from "random id" to "id unique per Neovim
instance", and the format becomes opaque to the engine — it is compared, never parsed.

## Design

Two mechanisms, used together, because neither is sufficient alone.

**A byte offset** answers *is this new data?* It is cheap and it is what makes restart cost
O(1) rather than O(history). It cannot be trusted alone: the file can be rotated, truncated or
replaced, and an offset into a different file is meaningless.

**An accepted-sequence high-water mark per session** answers *have I already taken this exact
event?* It is what makes a reset offset safe, and it is the property the contract already
claims. It cannot be used alone either: scanning the whole file to check identity is the very
cost the offset exists to avoid.

So: the offset says where to start reading, and the per-session mark filters what is read.
When the offset is trustworthy the mark filters nothing and costs nothing. When the offset has
been reset the mark carries the correctness.

### State file

`<workspace>/.companion/intake.json`, written with the existing
`view.index.write_atomic` (temp file plus rename — readers must never see a partial file):

```json
{
  "schema_version": 1,
  "offset": 40213,
  "source": {"device": 66310, "inode": 1451237, "size": 40213, "head_sha": "9f2a1c4e00b3d7a1"},
  "accepted": {"68c5f1a0-3ac1": 418},
  "updated_ts": 1789382000.4
}
```

- `offset` — byte offset one past the last newline of the last accepted event.
- `source` — identity of the file that offset refers to. `head_sha` is
  `canon.sha(first 4096 bytes)`, which catches a file that was replaced in place with the
  same inode reused.
- `accepted` — session id to the highest `editor_seq` accepted from it. One entry per editor
  the engine has followed in this workspace.
- Absent file means "never read anything": offset 0, no accepted marks. This is also the
  correct behaviour for a brand-new workspace.

### Reading rules

On startup, load `intake.json` and validate `source` against the current `inbox.jsonl`:

| Observation | Meaning | Action |
|---|---|---|
| device, inode and `head_sha` match, `st_size >= offset` | same file, grown or unchanged | resume at `offset` |
| device or inode differs, or `head_sha` differs | file replaced or rotated | resume at 0, keep `accepted` |
| `st_size < offset` | file truncated | resume at 0, keep `accepted` |
| inbox absent | adapter has not started | offset 0, wait |

Keeping `accepted` across a reset is the point: the whole file is re-read, and every event the
engine has already taken is filtered out by its sequence number instead of being reprocessed.

While following, for each complete line:

1. Decode. A malformed line is skipped and counted, exactly as today — it must not stop the
   tail or advance identity.
2. If the event has a `session` and a `seq`, and `seq <= accepted[session]`,
   skip it. It has been taken before.
3. Otherwise yield it for processing.

An event with no `session` (a CLI producer writing to the inbox) is governed by the offset
alone. Correction, 2026-09-14: an earlier draft of this brief said the field compared here is
`editor_seq` — wrong. `editor_seq` does not exist on the wire; it is a name the engine gives
`seq` once `handle_event` has looked at the event, which is *after* Intake has already read it
from the inbox. Intake reads the raw envelope field, `seq` (contract.md §1), falling back to
`editor_seq` only for an event that already carries one (e.g. one read back out of
`events.jsonl`, which does have it, post-intake).

**Sequence regression on genuinely new bytes.** If an event arrives past the recorded offset
with `seq <= accepted[session]`, the strict reading is "already taken". With unique
session ids this cannot happen in practice, and treating it as a duplicate is the safe failure:
it drops an event rather than replaying history. Log it once per session at that point
(`last_error`), because it means the session-id guarantee has broken and someone needs to know.
Do not add recovery heuristics for a case that should be impossible; make it visible instead.

### Advancing the mark

The watermark advances **after the engine has handled the event**, never when it is read.
`cmd_watch` currently reads on one thread and handles on another:

```python
def tail_inbox():
    for e in ev.tail(inbox):
        q.put(e)          # a crash here loses the event, and the offset already moved
...
e = q.get()
eng.handle_event(e)
```

So the reader must carry the position with the event, and the handler must commit it. The queue
already mixes filesystem events (which have no offset) with inbox events, so the item becomes a
pair and the filesystem producer supplies `None`.

Committing after `handle_event` returns is safe to repeat: if the engine dies between handling
an event and committing its mark, that one event is processed twice on restart. The second pass
finds the same bytes already the latest snapshot of that path with the same origin, so
`SnapshotStore.put` reports neither `changed` nor `origin_changed` and `handle_event` returns
early. Re-taking the *last* accepted event is a no-op; re-taking arbitrary earlier ones is not,
which is precisely why the mark must never run ahead of the handler.

### Proposed shape

A new module, `src/devcompanion/observe/intake.py`. `events.py` stays a schema module and
keeps `tail` for any other caller; the new code does not extend it.

Correction, 2026-09-14: the sketch below hashes a fixed 4096 bytes. That reports "replaced" for
an ordinary append to any file shorter than that the last time it was fingerprinted — every
workspace, for its first hour or so. The implementation hashes exactly `min(4096, offset)`
bytes instead (`head_len`, stored alongside `head_sha`) — the prefix guaranteed to have existed
at both observation times — and re-fingerprints the live file over that same length on restart.

```python
@dataclass
class Source:
    device: int; inode: int; size: int; head_len: int; head_sha: str
    @classmethod
    def of(cls, path: Path, head_len: int) -> "Source | None": ...
    def matches(self, other: "Source | None") -> bool: ...   # device, inode, head_sha over head_len

class Intake:
    """Durable read position in the adapter's inbox."""
    def __init__(self, state_dir: Path, inbox: Path, log=print): ...
    def follow(self, stop: threading.Event | None = None,
               poll_s: float = 0.2) -> Iterator[tuple[Event, int]]:
        """Yield (event, offset_after_this_line) forever, starting from the stored offset and
        skipping events already accepted. Blocking."""
    def drain(self) -> Iterator[tuple[Event, int]]:
        """Same, but stops at end of file. For tests and for a one-shot catch-up."""
    def accept(self, event: Event, offset: int) -> None:
        """Record that this event has been handled, and persist. Called by the consumer."""
    @property
    def stats(self) -> dict:   # {"resumed_at", "skipped_known", "malformed", "resets"}
```

`stats` is not decoration: "how much did I skip on restart" is the first thing anyone
debugging this will want, and it belongs in `engine.json` beside the other counters.

### Engine and CLI changes

- `Engine` gains no knowledge of the inbox. It already exposes everything needed; the intake
  is wired in `cli.py`. Resist putting the watermark inside `Engine` — replay and ingest have
  no inbox and must not grow a dependency on one.
- `cmd_watch` constructs `Intake(eng.dir, eng.dir / "inbox.jsonl", log=…)`, the tail thread
  puts `(event, offset)` pairs, the filesystem producer puts `(event, None)`, and the main loop
  calls `intake.accept(e, offset)` after `eng.handle_event(e)` when the offset is not None.
- `present/status.py` gains an `intake` block in `engine.json` — at minimum
  `{"offset", "skipped_known", "resets"}` — so the pane and any operator can see the engine
  resumed rather than restarted. Add the field to the contract's §4 table.

### Deliberately out of scope

State these in the handoff rather than solving them here:

- **Inbox compaction.** The file still grows without bound; the watermark makes that a
  disk-space question rather than a correctness one. Truncating it races with the adapter's
  appends and needs its own design.
- **Filesystem catch-up.** A file changed on disk while the engine was down is still missed,
  because `fswatch` has no durable position. That is a separate mechanism (a startup rescan
  against the snapshot store), not this one.
- **Pending-work recovery.** An event accepted but whose investigation had not finished when
  the engine died is not re-investigated. The content is snapshotted, so nothing is lost, but
  no claim is derived until that path changes again. Worth doing; different problem.

## Known limits

Recorded rather than fixed, per review 2026-09-14:

- **Rotation or truncation while the engine is running is invisible.** `_ensure_reconciled`
  runs once, lazily, the first time the inbox is seen; after that it latches. If the file is
  replaced or truncated mid-run — nothing in-tree does this, since the adapter only ever opens
  `inbox.jsonl` with `"a"`, but `rm -rf .companion` on a running watcher does, and so would the
  inbox compaction this brief already defers — `_scan` re-seeks `_read_pos` into whatever is now
  at that byte offset in the *new* file. Delivery silently resumes mid-line: `resets` stays 0,
  nothing is logged, and an unbounded run of events between the old EOF and the new content is
  simply never seen.
- **The corollary, if anyone fixes the above by re-checking periodically:** `accept()`'s `max()`
  on `offset` is only safe as long as every `offset` it is ever called with refers to the *same*
  file. A late `accept()` carrying a pre-rotation offset, arriving after reconciliation has
  already reset `_read_pos` and `offset` to 0 for the new file, would push the durable mark past
  the start of content nothing has read yet — wedging every subsequent event behind a `seq` the
  new file will never reach, skipped forever. Any periodic-recheck fix must reset `_read_pos`,
  `offset`, and drain (or discard) the in-flight queue together, under a lock, not as three
  independent writes.

## What "done" means

Every item below is a check that must exist and pass, not a description of intent. The
integration ones belong in `scripts/check-workflow.py`, the rest in `tests/`.

**Unit — `tests/test_intake.py`**

1. A fresh workspace with no `intake.json` starts at offset 0 and accepts everything.
2. `accept()` then reload: the offset and `accepted` marks survive; `drain()` yields nothing.
3. Rotation: replace `inbox.jsonl` with a different file after accepting events; the source
   fingerprint mismatches, offset resets to 0, and the previously accepted events are still
   skipped by sequence — `drain()` yields only the genuinely new ones.
4. Truncation: shrink the file below the offset; same outcome, and `stats["resets"] == 1`.
5. A malformed line between two valid ones is skipped, counted in `stats["malformed"]`, and
   does not stop the iteration or advance `accepted`.
6. Two sessions interleaved in one inbox keep independent marks.
7. A partially written final line (no trailing newline) is not yielded, and the offset does not
   advance past it. Appending its remainder then yields it exactly once.

**Unit — the regression that motivates the feature, `tests/test_engine_unsaved.py` or a new file**

8. Feed `buffer_changed A`, `buffer_changed B`, `buffer_saved B` through an `Intake` into an
   `Engine`. Snapshot `state.json` and `board.md`. Build a second `Engine` and `Intake` over
   the same state directory and drain again. Assert: no event is handled, `events.jsonl` gains
   no line, and evidence is byte-identical. Without the watermark this test fails by asserting
   about draft A.

**Unit — session id**

9. `util.session_id()` returns different values for two processes. Drive it the way the bug was
   found: run two headless Neovim instances and compare. A pure-Lua unit assertion cannot catch
   this, because the failure only appears across processes.

**Integration — `scripts/check-workflow.py`**

10. Start a real `companion watch`, drive a real headless Neovim through an unsaved edit and a
    save, terminate the watcher, restart it against the same workspace, and assert: the line
    count of `events.jsonl` is unchanged by the restart, `state.json` is unchanged, and a
    *new* edit after the restart is still picked up and produces a finding.
11. `engine.json` reports the intake block, and `skipped_known` is greater than zero after the
    restart in check 10 — i.e. the second engine demonstrably saw the old events and declined
    them, rather than never seeing them.

Follow the conventions already in the repo: `check()` for an assertion, real subprocesses over
mocks, and a detail string that states the observed value rather than repeating the check name.
