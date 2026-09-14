"""Protocol v2 intake: the editor's fields have to survive, because they are the only record
of content that exists nowhere else."""
import json

from devcompanion.canon import sha
from devcompanion.observe.events import Event


def encode(**fields):
    return json.dumps({"kind": "buffer_changed", "path": "a.py", **fields})


def test_editor_fields_survive():
    text = "def f(a, b):\n    return a\n"
    e = Event.from_json(encode(text=text, text_sha=sha(text.encode()), dirty=True,
                               doc_version=41, session="ab12", language="python",
                               fileformat="unix", eol=True, workspace="/p"))
    assert (e.dirty, e.doc_version, e.session, e.language) == (True, 41, "ab12", "python")
    assert e.content() == text.encode()
    assert e.content_mismatch() is None


def test_unknown_fields_are_kept_not_dropped():
    """A newer adapter must not lose data by talking to an older engine."""
    e = Event.from_json(encode(text="x\n", invented_later={"a": 1}))
    assert e.extra == {"invented_later": {"a": 1}}
    assert Event.from_json(e.to_json()).extra == {"invented_later": {"a": 1}}


def test_declared_hash_is_checked():
    e = Event.from_json(encode(text="x\n", text_sha="0000000000000000"))
    assert "0000000000000000 declared" in e.content_mismatch()


def test_log_line_drops_the_buffer_but_keeps_its_hash():
    """events.jsonl would grow by a whole buffer per keystroke pause otherwise; the bytes are
    in the snapshot store under content_sha."""
    e = Event.from_json(encode(text="x" * 10_000, dirty=True))
    e.content_sha, e.content_origin = "abc123", "editor"
    logged = json.loads(e.for_log())
    assert "text" not in logged
    assert logged["content_sha"] == "abc123" and logged["content_origin"] == "editor"
    assert logged["dirty"] is True


def test_malformed_line_is_rejected_rather_than_half_decoded():
    for bad in ("[]", '{"no_kind": 1}'):
        try:
            Event.from_json(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should not decode to an event")
