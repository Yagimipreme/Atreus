"""The content view answers "which bytes are the code right now", and the findings publisher
turns evidence into something the editor can render. Both are new in v2 and both are where a
wrong answer would be invisible rather than loud."""
import json
from pathlib import Path

import pytest

from devcompanion.present import findings as findings_out
from devcompanion.snapshot.store import ON_DISK, SnapshotStore
from devcompanion.view.index import ContentView, write_atomic

SAVED = b"def add(a, b):\n    return a + b\n"
TYPED = b"def add(a, b, carry):\n    return a + b + carry\n"


@pytest.fixture
def view(tmp_path):
    snap = SnapshotStore(tmp_path / "snapshots")
    return ContentView(tmp_path, snap, tmp_path), snap


def test_overlay_wins_over_disk(view, tmp_path):
    v, snap = view
    (tmp_path / "calc.py").write_bytes(SAVED)
    disk = snap.put("calc.py", SAVED, origin="disk")
    typed = snap.put("calc.py", TYPED, seq=2, origin="editor")
    v.record_editor("calc.py", typed.sha, dirty=True, doc_version=7, session="s1")

    assert v.effective("calc.py").origin == "editor"
    assert v.read("calc.py") == TYPED
    assert v.disk_revision("calc.py").sha == disk.sha
    assert v.dirty_paths() == ["calc.py"] and v.is_dirty("calc.py")


def test_unsaved_edits_are_judged_against_the_last_save(view):
    """Not against the previous keystroke pause: one edit typed over several debounce windows
    is one change, and comparing consecutive drafts would report it as a stream of noise."""
    v, snap = view
    saved = snap.put("calc.py", SAVED, origin="disk")
    draft1 = snap.put("calc.py", b"def add(a, b, c", seq=2, origin="editor")
    draft2 = snap.put("calc.py", TYPED, seq=3, origin="editor")
    assert v.baseline("calc.py", draft1.sha, "editor") == saved.sha
    assert v.baseline("calc.py", draft2.sha, "editor") == saved.sha


def test_saves_are_judged_against_the_previous_save(view):
    v, snap = view
    first = snap.put("calc.py", SAVED, origin="disk")
    snap.put("calc.py", b"def add(a, b, c", seq=2, origin="editor")
    second = snap.put("calc.py", TYPED, seq=3, origin="disk")
    assert v.baseline("calc.py", second.sha, "disk") == first.sha


def test_saving_the_buffer_retires_the_overlay(view):
    v, snap = view
    typed = snap.put("calc.py", TYPED, origin="editor")
    v.record_editor("calc.py", typed.sha, dirty=True)
    saved = snap.put("calc.py", TYPED, seq=2, origin="disk")
    v.record_disk("calc.py", saved.sha)
    assert v.dirty_paths() == []
    assert saved.changed is False and saved.origin_changed is True   # same bytes, new place


def test_an_edit_on_top_of_a_save_keeps_its_overlay(view):
    """A save of *different* content underneath a live buffer must not silently adopt it."""
    v, snap = view
    typed = snap.put("calc.py", TYPED, origin="editor")
    v.record_editor("calc.py", typed.sha, dirty=True)
    other = snap.put("calc.py", b"# something else\n", seq=2, origin="disk")
    v.record_disk("calc.py", other.sha)
    assert v.dirty_paths() == ["calc.py"] and v.read("calc.py") == TYPED


def test_departing_editor_takes_its_overlays(view):
    v, snap = view
    typed = snap.put("calc.py", TYPED, origin="editor")
    v.adopt_session("s1")
    v.record_editor("calc.py", typed.sha, dirty=True, session="s1")
    assert v.end_session("s1") == ["calc.py"]
    assert v.dirty_paths() == [] and v.session is None


def test_a_new_editor_discards_the_previous_ones_overlays(view):
    v, snap = view
    typed = snap.put("calc.py", TYPED, origin="editor")
    v.adopt_session("s1")
    v.record_editor("calc.py", typed.sha, dirty=True, session="s1")
    assert v.adopt_session("s2") is True
    assert v.dirty_paths() == []


def test_overlays_persist_across_an_engine_restart(view, tmp_path):
    v, snap = view
    typed = snap.put("calc.py", TYPED, origin="editor")
    v.adopt_session("s1")
    v.record_editor("calc.py", typed.sha, dirty=True, session="s1")
    v.persist()
    again = ContentView(tmp_path, snap, tmp_path)
    assert again.dirty_paths() == ["calc.py"] and again.session == "s1"
    assert again.read("calc.py") == TYPED


def test_manifest_records_where_each_revision_came_from(view, tmp_path):
    v, snap = view
    (tmp_path / "client.py").write_bytes(b"add(1, 2)\n")
    snap.put("client.py", b"add(1, 2)\n", origin="disk")
    typed = snap.put("calc.py", TYPED, origin="editor")
    v.record_editor("calc.py", typed.sha, dirty=True, doc_version=3)
    m = v.manifest(["calc.py", "client.py", "absent.py"])
    assert m["calc.py"] == {"sha": typed.sha, "origin": "editor", "dirty": True, "doc_version": 3}
    assert m["client.py"]["origin"] == "disk" and m["client.py"]["dirty"] is False
    assert "absent.py" not in m


def test_latest_on_disk_ignores_editor_states(view):
    v, snap = view
    saved = snap.put("calc.py", SAVED, origin="disk")
    snap.put("calc.py", TYPED, seq=2, origin="editor")
    assert snap.latest("calc.py") != saved.sha
    assert snap.latest("calc.py", ON_DISK) == saved.sha


# ---------------------------------------------------------------- findings

RECORD = {
    "key": "signature_change:calc.py:add", "kind": "signature_change",
    "title": "add(a, b) -> add(a, b, carry)", "claim": "2 call site(s): 1 break, 1 unsure, 0 fit",
    "based_on": {"calc.py": "aaa", "client.py": "bbb"}, "status": "fresh",
    "fingerprint": "fp1", "ts": 1.0, "suggestion": None,
    "locations": [
        {"path": "client.py", "line": 4, "col": 12, "verdict": "breaks",
         "reason": "missing required 'carry'", "text": "add(1, 2)", "file_sha": "bbb"},
        {"path": "client.py", "line": 9, "col": 5, "verdict": "unsure",
         "reason": "call uses *args/**kwargs unpacking", "text": "add(*xs)", "file_sha": "bbb"},
        {"path": "client.py", "line": 12, "col": 5, "verdict": "ok",
         "reason": "arguments fit the new signature", "text": "add(1, 2, 3)", "file_sha": "bbb"},
    ],
    "details": {},
}
MANIFEST = {"calc.py": {"sha": "aaa", "origin": "editor", "dirty": True},
            "client.py": {"sha": "bbb", "origin": "disk", "dirty": False}}


def test_only_calls_that_no_longer_fit_become_findings():
    out = findings_out.from_record(RECORD, MANIFEST)
    assert [f["location"]["line"] for f in out] == [4, 9]
    assert [f["basis"] for f in out] == ["observed", "inferred"]


def test_findings_carry_where_their_evidence_came_from():
    f = findings_out.from_record(RECORD, MANIFEST)[0]
    assert f["revision"] == {"calc.py": "editor", "client.py": "disk"}
    assert f["depends_on"] == RECORD["based_on"]


def test_ids_are_stable_across_rederivation():
    first = findings_out.from_record(RECORD, MANIFEST)
    again = findings_out.from_record({**RECORD, "ts": 99.0, "claim": "reworded"}, MANIFEST)
    assert [f["id"] for f in first] == [f["id"] for f in again]


def test_stale_records_are_published_as_outdated():
    out = findings_out.from_record({**RECORD, "status": "stale"}, MANIFEST)
    assert {f["basis"] for f in out} == {"outdated"}


def test_test_results_declare_that_they_only_judge_saved_files():
    rec = {"key": "test_run:calc.py:-", "kind": "test_run", "title": "tests mentioning add",
           "claim": "failed: 1 failed", "based_on": {"calc.py": "aaa"}, "status": "fresh",
           "fingerprint": "fp2", "ts": 2.0, "locations": [],
           "details": {"revision": "saved files only", "failed": "FAILED tests/test_calc.py"}}
    f = findings_out.from_record(rec, MANIFEST)[0]
    assert f["saved_revision_only"] is True and f["surface"] == "errors"
    assert f["evidence"][0]["ref"] == "failed"


def test_routine_records_are_not_news():
    for kind in ("noop", "unknown_intent", "new_function", "cancelled"):
        assert findings_out.from_record({**RECORD, "kind": kind}, MANIFEST) == []


def test_only_errors_are_echoed_back_from_diagnostics():
    diags = {"calc.py": [
        {"line": 2, "col": 1, "severity": "error", "message": "undefined name", "code": "F821"},
        {"line": 3, "col": 1, "severity": "warn", "message": "unused import"},
    ]}
    out = findings_out.from_diagnostics(diags, MANIFEST)
    assert len(out) == 1 and out[0]["title"] == "undefined name"


def test_the_published_file_is_replaced_whole_and_atomically(tmp_path):
    findings_out.write(tmp_path, findings_out.from_record(RECORD, MANIFEST))
    assert len((tmp_path / "findings.jsonl").read_text().splitlines()) == 2
    findings_out.write(tmp_path, [])
    assert (tmp_path / "findings.jsonl").read_text() == ""
    assert list(tmp_path.glob("findings.jsonl.*.tmp")) == [], "write_atomic must not leak its temp file"
    findings_out.write(tmp_path, findings_out.from_record(RECORD, MANIFEST))
    assert all(json.loads(l)["kind"] == "caller_affected"
               for l in (tmp_path / "findings.jsonl").read_text().splitlines())


def test_concurrent_writers_to_the_same_path_never_collide(tmp_path):
    """A fixed temp name means two threads writing the same path at once can truncate each
    other's in-flight temp file, so the loser's `os.replace` raises `FileNotFoundError` on a
    name that no longer exists -- exactly what a 1Hz heartbeat publisher racing the scheduler's
    worker thread does to engine.json. Neither writer may ever fail, and the file must always
    hold one writer's complete content, never a mix or a torn read."""
    import threading

    path = tmp_path / "engine.json"
    errors = []

    def hammer(payload):
        for _ in range(200):
            try:
                write_atomic(path, payload * 50)
            except Exception as exc:                # noqa: BLE001 -- the failure mode is "raises at all"
                errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(tag,)) for tag in ("A", "B", "C")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"write_atomic raised under concurrency: {errors}"
    content = path.read_text()
    assert content == content[0] * len(content), "the file must hold one writer's content whole, not a mix"
    assert list(tmp_path.glob("engine.json.*.tmp")) == []


# ---------------------------------------------------------------- single-line fields

MULTILINE = ('No overloads for "split" match the provided arguments\n'
             '  Argument of type "Literal[3]" cannot be assigned to parameter "sep"\n'
             '    "Literal[3]" is not assignable to "str | None"\n')


def test_no_published_field_ever_contains_a_newline():
    """Neovim refuses to set a buffer line containing a newline, so a multi-line field does not
    render badly — it raises and takes the pane down. Found in live use: basedpyright sends a
    four-line message and the panel died on every republish."""
    diags = {"calc.py": [{"line": 8, "col": 5, "severity": "error",
                          "message": MULTILINE, "code": "reportCallIssue", "source": "basedpyright"}]}
    rec = {**RECORD, "suggestion": "Add the parameter.\n\nThen update both call sites.",
           "kind": "test_run", "claim": "failed: 1 failed",
           "details": {"failed": "FAILED a.py::test_one\nFAILED b.py::test_two",
                       "first_error": "E   TypeError: bad\n    during handling"}}
    published = (findings_out.from_record(RECORD | {"suggestion": rec["suggestion"]}, MANIFEST)
                 + findings_out.from_record(rec, MANIFEST)
                 + findings_out.from_diagnostics(diags, MANIFEST))
    assert published, "nothing published, so the assertion would be vacuous"
    for f in published:
        for key, value in f.items():
            for text in ([value] if isinstance(value, str) else
                         [e.get("detail", "") for e in value] if key == "evidence" else []):
                assert "\n" not in text and "\r" not in text, f"{f['kind']}.{key}: {text!r}"


def test_flattening_keeps_the_content_readable():
    assert findings_out.line(MULTILINE).startswith('No overloads for "split" match')
    assert "Argument of type" in findings_out.line(MULTILINE)
    assert findings_out.line("  spaced   out \n\n text ") == "spaced out text"
    assert findings_out.line(None) == ""
    assert len(findings_out.line("x" * 500)) == 300
