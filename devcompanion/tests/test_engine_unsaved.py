"""The v2 headline: the engine analyses code that exists only in a buffer, and says so.

These drive the real Engine against a temporary working tree. They are fast because nothing
here runs pytest or a model; scripts/check-workflow.py covers the same ground through an
actual Neovim and an actual CLI.
"""
import json

import pytest

from devcompanion.canon import sha
from devcompanion.engine import Engine
from devcompanion.observe.events import Event
from devcompanion.observe.intake import Intake

SAVED = "def add(a, b):\n    return a + b\n"
TYPED = "def add(a, b, carry):\n    return a + b + carry\n"
CLIENT = "from calc import add\n\ndef total():\n    return add(1, 2)\n"


@pytest.fixture
def project(tmp_path):
    (tmp_path / "calc.py").write_text(SAVED)
    (tmp_path / "client.py").write_text(CLIENT)
    eng = Engine(tmp_path, run_tests=False, log=lambda _: None)
    for name in ("calc.py", "client.py"):
        eng.handle_event(Event(kind="buffer_saved", path=name))
    eng.sched.drain(wait=False)
    return eng, tmp_path


def typed(path, text, **kw):
    return Event(kind="buffer_changed", path=path, source="nvim", session="s1", text=text,
                 text_sha=sha(text.encode()), dirty=True, fileformat="unix", eol=True, **kw)


def record(eng, key="signature_change:calc.py:add"):
    return eng.evid.state.get(key, {})


def test_unsaved_edit_produces_a_finding_without_touching_disk(project):
    eng, root = project
    eng.handle_event(typed("calc.py", TYPED, doc_version=9, language="python"))
    eng.sched.drain(wait=False)

    assert (root / "calc.py").read_text() == SAVED, "the engine must not write the developer's files"
    rec = record(eng)
    assert rec["claim"].startswith("1 call site(s): 1 break")
    assert "unsaved buffer" in rec["details"]["revision"]
    assert eng.view.dirty_paths() == ["calc.py"]


def test_a_caller_typed_but_never_saved_is_still_judged(project):
    """rg reads files, so an unsaved caller is invisible to it; the overlay is what makes this
    work, and it is the case the whole feature exists for."""
    eng, _ = project
    eng.handle_event(typed("calc.py", TYPED))
    eng.sched.drain(wait=False)
    assert record(eng)["claim"].startswith("1 call site(s): 1 break")

    eng.handle_event(typed("client.py", CLIENT.replace("add(1, 2)", "add(1, 2, 0)")))
    eng.sched.drain(wait=False)
    rec = record(eng)
    assert rec["status"] == "fresh"
    assert rec["claim"].startswith("1 call site(s): 0 break"), "the fix is in a buffer, not a file"


def test_a_new_caller_file_that_was_never_saved_is_found(project):
    eng, root = project
    eng.handle_event(typed("calc.py", TYPED))
    eng.sched.drain(wait=False)
    eng.handle_event(typed("scratch.py", "from calc import add\nadd(1, 2)\n"))
    eng.sched.drain(wait=False)
    assert not (root / "scratch.py").exists()
    sites = {l["path"] for l in record(eng)["locations"]}
    assert sites == {"client.py", "scratch.py"}


def test_saving_the_same_bytes_re_runs_the_tools_that_read_files(project):
    """The content was already analysed as a buffer, but pytest could not see it until now."""
    eng, root = project
    eng.handle_event(typed("calc.py", TYPED))
    eng.sched.drain(wait=False)
    before = eng.sched.stats["ran"]

    (root / "calc.py").write_text(TYPED)
    eng.handle_event(Event(kind="buffer_saved", path="calc.py", source="nvim", session="s1",
                           text=TYPED, text_sha=sha(TYPED.encode()), dirty=False))
    eng.sched.drain(wait=False)
    assert eng.sched.stats["ran"] == before + 1
    assert eng.view.dirty_paths() == []
    assert "revision" not in record(eng)["details"]


def test_closing_the_editor_falls_back_to_the_file(project):
    eng, _ = project
    eng.handle_event(typed("calc.py", TYPED))
    eng.sched.drain(wait=False)
    assert record(eng)["claim"].startswith("1 call site(s): 1 break")

    eng.handle_event(Event(kind="session_end", source="nvim", session="s1"))
    eng.sched.drain(wait=False)
    assert eng.view.dirty_paths() == []
    assert record(eng, "file:calc.py")["kind"] == "noop", "back to the saved file, which is unchanged"


def test_diagnostics_reach_the_published_findings(project):
    eng, root = project
    eng.handle_event(Event(kind="diagnostics", path="calc.py", source="nvim", session="s1", items=[
        {"line": 2, "col": 12, "severity": "error", "message": "undefined name 'carry'",
         "code": "F821", "source": "ruff"},
        {"line": 1, "col": 1, "severity": "hint", "message": "unused"},
    ]))
    published = [json.loads(l) for l in
                 (root / ".companion/findings.jsonl").read_text().splitlines()]
    diags = [f for f in published if f["kind"] == "diagnostic_context"]
    assert len(diags) == 1 and diags[0]["title"] == "undefined name 'carry'"


def test_engine_json_describes_what_it_is_working_from(project):
    eng, root = project
    eng.handle_event(typed("calc.py", TYPED, doc_version=9))
    eng.sched.drain(wait=False)
    state = json.loads((root / ".companion/engine.json").read_text())
    assert state["session"] == "s1" and state["dirty_buffers"] == ["calc.py"]
    assert state["revisions"]["calc.py"]["origin"] == "editor"
    assert state["revisions"]["calc.py"]["doc_version"] == 9
    assert state["model"]["status"] == "disabled" and state["state"] == "idle"


def test_a_lying_hash_is_reported_and_the_real_bytes_are_used(project):
    eng, _ = project
    e = typed("calc.py", TYPED)
    e.text_sha = "0" * 16
    eng.handle_event(e)
    eng.sched.drain(wait=False)
    assert "text_sha mismatch" in eng.last_error
    assert record(eng)["based_on"]["calc.py"] == sha(TYPED.encode())


def test_restarting_the_engine_does_not_replay_a_finished_edit(tmp_path):
    """The regression the watermark exists for. `buffer_changed A` is an unsaved draft the
    developer already abandoned in favour of B; without a durable read position, a restart
    re-reads inbox.jsonl from byte 0 and the engine briefly asserts things about A again. It
    converges back to the same board eventually, but "eventually" is exactly what contract
    invariant 4 says never has to happen. Drive an Intake into an Engine, then build a second
    Engine and Intake over the same state directory and drain again: nothing should move."""
    root = tmp_path
    (root / "calc.py").write_text(SAVED)
    state = root / ".companion"
    inbox = state / "inbox.jsonl"

    eng = Engine(root, state, run_tests=False, log=lambda _: None)
    eng.handle_event(Event(kind="buffer_saved", path="calc.py"))
    eng.sched.drain(wait=False)

    def write_inbox(event):
        # What the adapter does: the full event, `text` included. `events.append` is the
        # engine's own log and drops `text` on purpose; using it here would send the engine a
        # buffer_changed with no buffer, which is not the scenario under test.
        with inbox.open("a") as f:
            f.write(event.to_json() + "\n")

    draft_a = "def add(a, b, extra):\n    return a + b\n"           # abandoned, never saved
    inbox.parent.mkdir(parents=True, exist_ok=True)
    write_inbox(typed("calc.py", draft_a, seq=1))
    write_inbox(typed("calc.py", TYPED, seq=2))               # the edit that stuck
    write_inbox(Event(kind="buffer_saved", path="calc.py", source="nvim", session="s1",
                      text=TYPED, text_sha=sha(TYPED.encode()), dirty=False, seq=3))

    intake = Intake(state, inbox, log=lambda _: None)
    for e, offset in intake.drain():
        eng.handle_event(e)
        eng.sched.drain(wait=False)
        intake.accept(e, offset)

    rec = record(eng)
    assert rec["based_on"]["calc.py"] == sha(TYPED.encode()), "should have converged on B, not A"
    events_before = (state / "events.jsonl").read_text()
    evidence_before = (state / "state.json").read_text()

    Engine(root, state, run_tests=False, log=lambda _: None)     # a fresh process, same state dir
    replayed = list(Intake(state, inbox, log=lambda _: None).drain())

    assert replayed == [], f"the restart re-read {len(replayed)} already-taken event(s)"
    assert (state / "events.jsonl").read_text() == events_before, "events.jsonl gained a line"
    assert (state / "state.json").read_text() == evidence_before, "evidence moved on a no-op restart"


def test_a_lost_or_never_created_intake_state_is_seeded_from_the_events_log(tmp_path):
    """`intake.json` absent means `accepted == {}` by construction (a fresh workspace, or one
    whose state file was lost). Without seeding, that replays every event `events.jsonl` has
    already recorded as if it were new -- on first contact with *every* existing workspace, the
    day this ships. `events.jsonl` already carries `editor_seq` on everything the engine has
    taken (`handle_event` fills it in before logging), so `Engine._scan_events_log` -- the same
    pass that already finds `seq` -- collects the high-water mark per session too, and
    `cmd_watch` seeds a fresh `Intake` with it before reading anything."""
    root = tmp_path
    (root / "calc.py").write_text(SAVED)
    state = root / ".companion"
    inbox = state / "inbox.jsonl"

    eng = Engine(root, state, run_tests=False, log=lambda _: None)
    eng.handle_event(Event(kind="buffer_saved", path="calc.py"))
    eng.sched.drain(wait=False)

    def write_inbox(event):
        with inbox.open("a") as f:
            f.write(event.to_json() + "\n")

    draft_a = "def add(a, b, extra):\n    return a + b\n"
    write_inbox(typed("calc.py", draft_a, seq=1))
    write_inbox(typed("calc.py", TYPED, seq=2))
    write_inbox(Event(kind="buffer_saved", path="calc.py", source="nvim", session="s1",
                      text=TYPED, text_sha=sha(TYPED.encode()), dirty=False, seq=3))

    intake = Intake(state, inbox, log=lambda _: None)
    for e, offset in intake.drain():
        eng.handle_event(e)
        eng.sched.drain(wait=False)
        intake.accept(e, offset)
    events_before = (state / "events.jsonl").read_text()
    evidence_before = (state / "state.json").read_text()

    # Simulate the state file being lost, or never having existed: a fresh Engine (which
    # reads events.jsonl, unaffected) paired with a fresh Intake (which has nothing of its
    # own) that is seeded before it ever reads the inbox -- exactly what cmd_watch does.
    # `accepted_editor_seqs` is a snapshot taken at construction, from what's durably logged
    # by then -- it is read from the *second* Engine, not livened on the first.
    (state / "intake.json").unlink()
    eng2 = Engine(root, state, run_tests=False, log=lambda _: None)
    assert eng2.accepted_editor_seqs == {"s1": 3}
    intake2 = Intake(state, inbox, log=lambda _: None)
    assert intake2.accepted == {}, "a lost state file starts with no marks of its own"
    intake2.seed(eng2.accepted_editor_seqs)

    replayed = list(intake2.drain())
    assert replayed == [], f"the lost state file caused {len(replayed)} event(s) to replay"
    assert (state / "events.jsonl").read_text() == events_before
    assert (state / "state.json").read_text() == evidence_before


def test_a_clean_restart_still_picks_up_further_typing(tmp_path):
    """The counterpart to the no-new-traffic restart tests: after a normal resume (intake.json
    present, nothing rotated), a further keystroke must still reach the engine exactly once."""
    root = tmp_path
    (root / "calc.py").write_text(SAVED)
    state = root / ".companion"
    inbox = state / "inbox.jsonl"

    (root / "client.py").write_text(CLIENT)
    eng = Engine(root, state, run_tests=False, log=lambda _: None)
    for name in ("calc.py", "client.py"):
        eng.handle_event(Event(kind="buffer_saved", path=name))
    eng.sched.drain(wait=False)

    def write_inbox(event):
        with inbox.open("a") as f:
            f.write(event.to_json() + "\n")

    write_inbox(typed("calc.py", TYPED, seq=1))
    intake = Intake(state, inbox, log=lambda _: None)
    for e, offset in intake.drain():
        eng.handle_event(e)
        eng.sched.drain(wait=False)
        intake.accept(e, offset)
    assert record(eng)["claim"].startswith("1 call site(s): 1 break")

    # A fresh process, same state dir and inbox -- a clean restart, nothing rotated.
    eng2 = Engine(root, state, run_tests=False, log=lambda _: None)
    intake2 = Intake(state, inbox, log=lambda _: None)
    assert list(intake2.drain()) == [], "resuming at the offset should find nothing unread yet"
    assert intake2.stats["resets"] == 0 and intake2.stats["resumed_at"] > 0

    further = "def add(a, b, carry, extra):\n    return a + b + carry + extra\n"
    write_inbox(typed("calc.py", further, seq=2))
    handled = list(intake2.drain())
    assert len(handled) == 1, "the further edit must be delivered exactly once"
    e, offset = handled[0]
    eng2.handle_event(e)
    eng2.sched.drain(wait=False)
    intake2.accept(e, offset)

    rec = record(eng2)
    assert rec["based_on"]["calc.py"] == sha(further.encode())
    assert list(intake2.drain()) == []
