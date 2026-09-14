"""The optional model tier: when it is called, when it is not, and what it sends.

A real HTTP server on a loopback port stands in for Ollama. Not a mock — the engine builds a
genuine request and this reads it — because the things worth asserting here are the request
body and the call count, and a mock would only prove that the test's own assumptions agree
with themselves.
"""
import json
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from devcompanion.canon import sha
from devcompanion.engine import Engine
from devcompanion.observe.events import Event

SAVED = "def add(a, b):\n    return a + b\n"
TYPED = "def add(a, b, carry):\n    return a + b + carry\n"
CLIENT = "from calc import add\n\ndef total():\n    return add(1, 2)\n"


class Recorder(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(body)
        payload = json.dumps({"message": {"content": self.server.reply},
                              "prompt_eval_count": 40, "eval_count": 12}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


def serve(port=0):
    """A recorder on a loopback port. `shutdown` alone leaves the socket bound, so a later
    rebind of the same port fails and a request to it hangs until the timeout rather than
    being refused; `server_close` is what actually frees it."""
    srv = HTTPServer(("127.0.0.1", port), Recorder)
    srv.requests, srv.reply = [], "Update both call sites to pass carry."
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def stop(srv):
    srv.shutdown()
    srv.server_close()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def fake_ollama():
    srv = serve()
    yield srv
    stop(srv)


@pytest.fixture
def project(tmp_path, fake_ollama):
    (tmp_path / "calc.py").write_text(SAVED)
    (tmp_path / "client.py").write_text(CLIENT)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    llm = {"model": "test-model", "backend": "ollama",
           "base_url": f"http://127.0.0.1:{fake_ollama.server_port}",
           "cpu_only": False, "keep_alive": "30m"}
    eng = Engine(tmp_path, run_tests=False, llm=llm, log=lambda _: None)
    for name in ("calc.py", "client.py"):
        eng.handle_event(Event(kind="buffer_saved", path=name))
    eng.sched.drain(wait=False)
    return eng, tmp_path, fake_ollama


def typed(path, text):
    return Event(kind="buffer_changed", path=path, source="nvim", session="s1", text=text,
                 text_sha=sha(text.encode()), dirty=True, fileformat="unix", eol=True)


def test_typing_does_not_call_the_model(project):
    """A warm request is ~1.66 s against a 400 ms debounce. Calling per keystroke pause would
    queue requests that land describing drafts the developer has already moved past."""
    eng, _, srv = project
    for draft in ("def add(a, b, c", TYPED, TYPED.replace("carry", "carry_in")):
        eng.handle_event(typed("calc.py", draft))
        eng.sched.drain(wait=False)
    assert srv.requests == []
    assert eng.evid.state["signature_change:calc.py:add"]["claim"].startswith("1 call site")


def test_saving_calls_the_model_once_and_the_sentence_reaches_the_finding(project):
    eng, root, srv = project
    (root / "calc.py").write_text(TYPED)
    eng.handle_event(Event(kind="buffer_saved", path="calc.py", source="nvim", session="s1",
                           text=TYPED, text_sha=sha(TYPED.encode()), dirty=False))
    eng.sched.drain(wait=False)
    assert len(srv.requests) == 1
    rec = eng.evid.state["signature_change:calc.py:add"]
    assert rec["suggestion"] == "Update both call sites to pass carry."
    published = [json.loads(l) for l in (root / ".companion/findings.jsonl").read_text().splitlines()]
    model_evidence = [e for f in published for e in f["evidence"] if e["kind"] == "model"]
    assert model_evidence and model_evidence[0]["detail"] == "Update both call sites to pass carry."


def test_the_request_keeps_the_model_resident(project):
    """Without this the developer pays a 15.4 s cold load on most saves after a pause."""
    eng, root, srv = project
    (root / "calc.py").write_text(TYPED)
    eng.handle_event(Event(kind="buffer_saved", path="calc.py"))
    eng.sched.drain(wait=False)
    assert srv.requests[0]["keep_alive"] == "30m"
    assert srv.requests[0]["options"]["num_ctx"] == 4096


def test_only_breaking_sites_reach_the_model(project):
    """Sites that still fit are not evidence of a problem, and spending context on them is
    what made the 3B answers worse in the earlier evaluation."""
    eng, root, srv = project
    fixed = CLIENT.replace("add(1, 2)", "add(1, 2, 0)")
    (root / "client.py").write_text(fixed)
    eng.handle_event(Event(kind="buffer_saved", path="client.py"))
    (root / "calc.py").write_text(TYPED)
    eng.handle_event(Event(kind="buffer_saved", path="calc.py"))
    eng.sched.drain(wait=False)
    assert srv.requests == [], "no breaking site left, so nothing to ask about"


def test_a_transient_model_failure_does_not_suppress_the_sentence_forever(project):
    """The fingerprint excludes the sentence so re-deriving a claim does not re-nag. A claim
    first derived while the model was down must still be able to acquire one later."""
    eng, root, srv = project
    stop(srv)                            # nothing listening: refused at once, not a 30 s timeout
    (root / "calc.py").write_text(TYPED)
    eng.handle_event(Event(kind="buffer_saved", path="calc.py"))
    eng.sched.drain(wait=False)
    assert eng.evid.state["signature_change:calc.py:add"]["suggestion"] is None

    revived = serve(srv.server_port)
    revived.reply = "Pass carry at both call sites."
    try:
        # A file that merely *names* the callee re-judges the claim without altering it: the
        # recheck triggers on a plain substring, while the caller search needs an actual call.
        # So this is a re-derivation with an identical fingerprint, which is exactly the path
        # that used to drop the sentence on the floor.
        (root / "notes.py").write_text("# add is fine as it stands\n")
        eng.handle_event(Event(kind="buffer_saved", path="notes.py"))
        eng.sched.drain(wait=False)
        rec = eng.evid.state["signature_change:calc.py:add"]
        assert rec["claim"].startswith("1 call site"), "the claim itself must be unchanged"
        assert rec["suggestion"] == "Pass carry at both call sites."
    finally:
        stop(revived)


def test_re_deriving_the_same_claim_does_not_re_ask_the_model(project):
    """An editor that writes on a timer turns every keystroke pause into a save. Gating on
    saves alone would then call the model once a second; the claim's fingerprint is what
    actually bounds the cost."""
    eng, root, srv = project
    (root / "calc.py").write_text(TYPED)
    eng.handle_event(Event(kind="buffer_saved", path="calc.py"))
    eng.sched.drain(wait=False)
    assert len(srv.requests) == 1
    sentence = eng.evid.state["signature_change:calc.py:add"]["suggestion"]

    for _ in range(5):                       # five more saves, same claim every time
        (root / "notes.py").write_text(f"# add is fine {_}\n")
        eng.handle_event(Event(kind="buffer_saved", path="notes.py"))
        eng.sched.drain(wait=False)

    assert len(srv.requests) == 1, "the claim never changed, so there was nothing new to ask"
    assert eng.evid.state["signature_change:calc.py:add"]["suggestion"] == sentence


def test_a_changed_claim_does_ask_again(project):
    eng, root, srv = project
    (root / "calc.py").write_text(TYPED)
    eng.handle_event(Event(kind="buffer_saved", path="calc.py"))
    eng.sched.drain(wait=False)
    srv.reply = "Now only one site is left."
    (root / "client.py").write_text(CLIENT.replace("add(1, 2)", "add(1, 2, 0)\n    add(3, 4)"))
    eng.handle_event(Event(kind="buffer_saved", path="client.py"))
    eng.sched.drain(wait=False)
    assert len(srv.requests) == 2, "the call sites changed, so the claim did too"
