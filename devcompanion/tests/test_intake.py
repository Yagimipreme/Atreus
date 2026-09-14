"""The durable watermark: a byte offset for cheap resumption, and a per-session high-water mark
for correctness when the offset is reset. See docs/intake-watermark.md.

The adapter's own counter travels on the wire as `seq` (contract.md §1) -- the engine only
renames it to `editor_seq` once `handle_event` has looked at the event, which is *after*
Intake has already read it from the inbox. These fixtures build events the way the real
adapter does (`seq`, not `editor_seq`) so the tests exercise the field Intake actually sees.

`Intake.drain()` never blocks and never mutates `accepted` on its own -- that only happens via
`accept()`, which the consumer calls once it has actually handled an event. These tests drive
`Intake` directly against a real inbox file; they do not need an Engine."""
from devcompanion.observe import events as ev
from devcompanion.observe.intake import Intake


def typed(path, session, seq, **extra):
    e = ev.Event(kind="buffer_changed", path=path, source="nvim", session=session, seq=seq, dirty=True)
    e.extra = extra
    return e


def padded(path, session, seq, pad=6000):
    """An event whose logged line exceeds the 4096 bytes `Source` fingerprints, so a fixture
    can truncate the file's tail without touching the bytes the fingerprint reads."""
    return typed(path, session, seq, pad="x" * pad)


def write_inbox(path, event):
    """What the adapter does: append the full event, `text` included. `events.append` is for
    the engine's own log, which drops `text` on purpose -- using it here would silently make
    every fixture event contentless."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(event.to_json() + "\n")


def drain_and_accept(intake):
    got = list(intake.drain())
    for e, offset in got:
        intake.accept(e, offset)
    return got


def test_a_fresh_workspace_starts_at_offset_zero_and_accepts_everything(tmp_path):
    inbox = tmp_path / "inbox.jsonl"
    write_inbox(inbox, typed("a.py", "s1", 1))
    write_inbox(inbox, typed("b.py", "s1", 2))

    intake = Intake(tmp_path, inbox)
    got = list(intake.drain())

    assert [e.path for e, _ in got] == ["a.py", "b.py"]
    assert intake.stats["resumed_at"] == 0
    assert intake.stats["resets"] == 0


def test_accepted_offset_and_marks_survive_a_reload(tmp_path):
    inbox = tmp_path / "inbox.jsonl"
    write_inbox(inbox, typed("a.py", "s1", 1))
    write_inbox(inbox, typed("a.py", "s1", 2))

    first = Intake(tmp_path, inbox)
    drain_and_accept(first)

    again = Intake(tmp_path, inbox)
    assert again.offset == first.offset
    assert again.accepted == {"s1": 2}
    assert list(again.drain()) == []
    assert again.stats["resumed_at"] == first.offset


def test_replacing_the_inbox_resets_the_offset_but_keeps_accepted_marks(tmp_path):
    inbox = tmp_path / "inbox.jsonl"
    write_inbox(inbox, typed("a.py", "s1", 1))

    first = Intake(tmp_path, inbox)
    drain_and_accept(first)
    assert first.accepted == {"s1": 1}

    inbox.unlink()                               # a different file, e.g. the adapter rotated it
    write_inbox(inbox, typed("a.py", "s1", 1))   # replayed by the new file
    write_inbox(inbox, typed("a.py", "s1", 2))   # genuinely new

    again = Intake(tmp_path, inbox)
    got = list(again.drain())

    assert [e.seq for e, _ in got] == [2]
    assert again.stats["resets"] == 1


def test_truncating_the_inbox_below_the_offset_resets_it(tmp_path):
    inbox = tmp_path / "inbox.jsonl"
    write_inbox(inbox, padded("a.py", "s1", 1))
    write_inbox(inbox, typed("a.py", "s1", 2))

    first = Intake(tmp_path, inbox)
    drain_and_accept(first)

    full = inbox.read_bytes()
    line1_end = full.index(b"\n") + 1
    inbox.write_bytes(full[:line1_end])          # drop the second line; head untouched, size shrinks

    again = Intake(tmp_path, inbox)
    assert list(again.drain()) == [], "the surviving line was already accepted"
    assert again.stats["resets"] == 1

    write_inbox(inbox, typed("a.py", "s1", 2))   # replayed
    write_inbox(inbox, typed("a.py", "s1", 3))   # genuinely new
    got = list(again.drain())
    assert [e.seq for e, _ in got] == [3]


def test_a_malformed_line_between_valid_ones_is_skipped_and_counted(tmp_path):
    inbox = tmp_path / "inbox.jsonl"
    write_inbox(inbox, typed("a.py", "s1", 1))
    with inbox.open("a") as f:
        f.write("not json at all\n")
    write_inbox(inbox, typed("a.py", "s1", 2))

    intake = Intake(tmp_path, inbox)
    got = drain_and_accept(intake)

    assert [e.seq for e, _ in got] == [1, 2]
    assert intake.stats["malformed"] == 1
    assert intake.accepted == {"s1": 2}, "the malformed line never had an identity to record"


def test_two_sessions_interleaved_keep_independent_marks(tmp_path):
    inbox = tmp_path / "inbox.jsonl"
    write_inbox(inbox, typed("a.py", "s1", 1))
    write_inbox(inbox, typed("a.py", "s2", 1))
    write_inbox(inbox, typed("a.py", "s1", 2))

    intake = Intake(tmp_path, inbox)
    drain_and_accept(intake)
    assert intake.accepted == {"s1": 2, "s2": 1}

    write_inbox(inbox, typed("a.py", "s2", 1))   # duplicate for s2 only
    write_inbox(inbox, typed("a.py", "s2", 2))   # genuinely new for s2
    got = list(intake.drain())
    assert [(e.session, e.seq) for e, _ in got] == [("s2", 2)]


def test_a_partial_final_line_is_not_yielded_until_completed(tmp_path):
    inbox = tmp_path / "inbox.jsonl"
    write_inbox(inbox, typed("a.py", "s1", 1))

    intake = Intake(tmp_path, inbox)
    drain_and_accept(intake)
    before = intake.offset

    line = typed("a.py", "s1", 2).to_json() + "\n"
    half = len(line) // 2
    with inbox.open("a") as f:
        f.write(line[:half])                     # a write in progress: no trailing newline yet

    assert list(intake.drain()) == []
    assert intake.offset == before

    with inbox.open("a") as f:
        f.write(line[half:])
    got = drain_and_accept(intake)
    assert [e.seq for e, _ in got] == [2]


def test_events_read_but_not_yet_accepted_are_not_redelivered(tmp_path):
    """`_scan` can hand out events well ahead of the consumer accepting them (in `cmd_watch`,
    the tail thread reads onto a queue while the main loop handles and accepts one at a time).
    `offset` (durable, accept-only) and the scan cursor are different things; if `_scan` re-seeked
    to `offset` on every pass, anything read but not yet accepted would be yielded again on the
    next pass -- the exact history-replay this module exists to prevent, just moved from
    restart-time into steady state."""
    inbox = tmp_path / "inbox.jsonl"
    write_inbox(inbox, typed("calc.py", "s1", 1))
    write_inbox(inbox, typed("calc.py", "s1", 2))
    write_inbox(inbox, typed("calc.py", "s1", 3))

    intake = Intake(tmp_path, inbox)
    got = list(intake.drain())
    assert [e.seq for e, _ in got] == [1, 2, 3]

    intake.accept(*got[0])                     # the consumer has handled only event 1 so far
    assert list(intake.drain()) == [], "2 and 3 were already read; re-yielding them is the bug"


def test_reader_and_consumer_stepped_separately_each_event_handled_exactly_once(tmp_path):
    """No threads: drives the reader (`drain`) and the consumer (`accept`) explicitly, the way
    `cmd_watch`'s tail thread and main loop interact, so the interleaving is deterministic
    rather than a race. Every event must be handled exactly once, in order, regardless of how
    far the reader gets ahead of the consumer."""
    inbox = tmp_path / "inbox.jsonl"
    for seq in (1, 2, 3):
        write_inbox(inbox, typed("calc.py", "s1", seq))

    intake = Intake(tmp_path, inbox)
    handled = []

    batch = list(intake.drain())               # the reader races ahead and sees all three
    assert [e.seq for e, _ in batch] == [1, 2, 3]

    e, offset = batch[0]                       # the consumer handles and accepts one at a time
    handled.append(e.seq)
    intake.accept(e, offset)

    # the reader wakes again before the consumer has caught up with the rest of the batch
    assert list(intake.drain()) == [], "already-read events must not be handed out twice"

    for e, offset in batch[1:]:
        handled.append(e.seq)
        intake.accept(e, offset)

    assert handled == [1, 2, 3]
    assert list(intake.drain()) == []
    assert intake.offset == batch[-1][1]


def test_an_event_that_already_carries_editor_seq_is_honoured_over_seq(tmp_path):
    """A replayed or hand-built event may already have `editor_seq` set (the engine's own
    intake does this before an event ever reaches events.jsonl); Intake must prefer it over the
    envelope's `seq`, exactly like `Engine.handle_event`'s own fallback."""
    inbox = tmp_path / "inbox.jsonl"
    e = typed("a.py", "s1", seq=99)
    e.editor_seq = 1
    write_inbox(inbox, e)

    intake = Intake(tmp_path, inbox)
    drain_and_accept(intake)
    assert intake.accepted == {"s1": 1}, "editor_seq (1), not the unrelated seq (99), is the mark"

    dup = typed("a.py", "s1", seq=100)
    dup.editor_seq = 1
    write_inbox(inbox, dup)
    assert list(intake.drain()) == []
