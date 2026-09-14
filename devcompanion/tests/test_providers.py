"""How the subscription CLIs are invoked, against stand-in `claude` and `codex` executables that
record what they were given. The flags are the safety property: a provider that is not asked to
run without tools could edit the developer's files, and nothing would say so. Whether the real
CLIs honour them is scripts/check-provider-tripwire.py's job."""
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from devcompanion.llm import providers
from devcompanion.llm.providers import Spec, parse

FAKE = """#!{python}
import json, os, sys
from pathlib import Path
Path(os.environ["RECORD"]).write_text(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(), "stdin": sys.stdin.read()}}))
if Path(sys.argv[0]).name == "claude":
    print(json.dumps({{"type": "result", "is_error": False, "result": "answer", "duration_api_ms": 900,
                      "total_cost_usd": 0.002, "usage": {{"input_tokens": 400, "cache_read_input_tokens": 100,
                      "output_tokens": 7}}, "modelUsage": {{"claude-sonnet-5": {{}}}}}}))
else:
    out = sys.argv[sys.argv.index("--output-last-message") + 1]
    Path(out).write_text("answer\\n")
    print(json.dumps({{"type": "turn.completed", "usage": {{"input_tokens": 12000, "output_tokens": 5,
                      "reasoning_output_tokens": 20}}}}))
"""


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("claude", "codex"):
        exe = bin_dir / name
        exe.write_text(FAKE.format(python=sys.executable))
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    record = tmp_path / "record.json"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("RECORD", str(record))
    return lambda: json.loads(record.read_text())


def test_specs_name_a_backend_and_its_options():
    assert parse("qwen3-coder:30b") == Spec("ollama", "qwen3-coder:30b")
    assert parse("ollama:qwen3:4b@2048") == Spec("ollama", "qwen3:4b", tokens=2048)
    assert parse("qwen3-coder:30b@ctx=16384,tokens=500") == Spec("ollama", "qwen3-coder:30b", tokens=500, ctx=16384)
    assert parse("qwen2.5-coder:3b@gpu=0") == Spec("ollama", "qwen2.5-coder:3b", gpu=0)
    assert parse("claude:opus/medium") == Spec("claude", "opus", "medium")
    assert parse("codex:") == Spec("codex", "")
    assert parse("claude:sonnet").remote and not parse("qwen2.5-coder:3b").remote


def test_claude_runs_without_tools_settings_or_mcp_in_an_empty_directory(fake_cli):
    reply = providers.ask("claude:sonnet/low", "the instruction", "the context")
    seen = fake_cli()
    argv = seen["argv"]
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in argv and "--no-session-persistence" in argv
    assert "--mcp-config" not in argv and "--dangerously-skip-permissions" not in argv
    assert argv[argv.index("--system-prompt") + 1] == "the instruction"
    assert (argv[argv.index("--model") + 1], argv[argv.index("--effort") + 1]) == ("sonnet", "low")
    assert seen["stdin"] == "the context"
    assert Path(seen["cwd"]).name.startswith("companion-provider-")
    assert not Path(seen["cwd"]).is_relative_to(Path(__file__).resolve().parents[1])
    assert not Path(seen["cwd"]).exists(), "the scratch directory is removed after the call"
    assert (reply.text, reply.status, reply.prompt_tokens, reply.gen_tokens) == ("answer", "ok", 500, 7)
    assert reply.remote and reply.cost_usd == 0.002 and reply.model == "claude-sonnet-5"


def test_codex_runs_read_only_in_an_empty_directory(fake_cli):
    reply = providers.ask("codex:/low", "the instruction", "the context")
    seen = fake_cli()
    argv = seen["argv"]
    assert argv[:2] == ["exec", "--skip-git-repo-check"]
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in argv and "--ignore-rules" in argv
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv and "--add-dir" not in argv
    assert argv[argv.index("--cd") + 1] == seen["cwd"]
    assert 'model_reasoning_effort="low"' in argv and "--model" not in argv
    assert seen["stdin"] == "the instruction\n\nthe context"
    assert (reply.text, reply.status, reply.gen_tokens) == ("answer", "ok", 25)


def test_a_missing_cli_is_unavailable_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert providers.ask("claude:sonnet", "s", "u").status == "unavailable"
