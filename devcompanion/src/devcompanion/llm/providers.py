"""One call shape for every model the companion can reach.

  <model> | ollama:<model>[@key=value,...]   local Ollama over HTTP (client.py); keys: tokens,
                                             ctx, keep. `name@2048` means `name@tokens=2048`
  claude:<alias>[/<effort>]                  Claude Code (`claude -p`), subscription
  codex:[<model>][/<effort>]                 Codex CLI (`codex exec`), subscription

A CLI provider is an agent with file and shell tools. Every call here runs it without them --
Claude with `--tools ""`, no MCP servers, no settings files and no session file; Codex in its
read-only sandbox with no rules and no session file -- in a fresh empty directory outside every
working tree, with the whole context in the prompt. scripts/check-provider-tripwire.py shows that
an agent spawned this way cannot modify files; per providers.md no CLI provider is used before it
passes. What comes back is text, and nothing else.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from devcompanion.llm.client import Reply, chat

BACKENDS = ("ollama", "claude", "codex")

CLAUDE = ["claude", "-p", "--output-format", "json", "--tools", "", "--strict-mcp-config",
          "--setting-sources", "", "--disable-slash-commands", "--no-session-persistence",
          "--permission-mode", "dontAsk"]
CODEX = ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-rules",
         "--sandbox", "read-only", "--json"]


@dataclass(frozen=True)
class Spec:
    backend: str
    model: str = ""          # "" means the CLI's configured default
    effort: str = ""
    tokens: int = 300        # output budget; Ollama only -- the CLIs expose no such limit
    ctx: int = 4096          # Ollama only
    keep_alive: str = "30m"  # Ollama only
    gpu: int | None = None   # Ollama only; 0 keeps the model on the CPU, where it does not evict
                             # the model holding the 8 GB card
    endpoint: str | None = None  # Ollama only; None is the local default

    @property
    def remote(self) -> bool:
        return self.backend != "ollama"


def parse(text: str) -> Spec:
    backend, colon, rest = text.partition(":")
    if not colon or backend not in BACKENDS:
        backend, rest = "ollama", text
    name, _, options = rest.partition("@")
    effort = ""
    if backend != "ollama":
        name, _, effort = name.partition("/")
    values: dict[str, str] = {}
    for item in filter(None, options.split(",")):
        key, eq, value = item.partition("=")
        values["tokens" if not eq else key] = key if not eq else value
    return Spec(backend, name, effort, int(values.get("tokens", 300)), int(values.get("ctx", 4096)),
                values.get("keep", "30m"), int(values["gpu"]) if "gpu" in values else None)


def _run(argv: list[str], stdin: str, cwd: Path, timeout_s: float):
    started = time.time()
    try:
        proc = subprocess.run(argv, input=stdin, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout_s)
    except FileNotFoundError:
        return None, "unavailable", time.time() - started
    except subprocess.TimeoutExpired:
        return None, "timeout", time.time() - started
    return proc, "ok", time.time() - started


def argv(spec: Spec, system: str, workdir: Path | str = "<scratch dir>", last: Path | str = "<reply file>") -> list[str]:
    """The command a CLI provider runs. `ask` runs it; `companion config --effective` prints it, so
    what is shown is what runs. Codex has no system-prompt flag: its instruction leads stdin."""
    if spec.backend == "claude":
        out = [*CLAUDE, "--system-prompt", system]
        if spec.model:
            out += ["--model", spec.model]
        if spec.effort:
            out += ["--effort", spec.effort]
        return out
    out = [*CODEX, "--cd", str(workdir), "--output-last-message", str(last)]
    if spec.model:
        out += ["--model", spec.model]
    if spec.effort:
        out += ["-c", f'model_reasoning_effort="{spec.effort}"']
    return [*out, "-"]


def _claude(spec: Spec, system: str, user: str, workdir: Path, timeout_s: float) -> Reply:
    label = f"claude:{spec.model or 'default'}"
    proc, status, wall = _run(argv(spec, system), user, workdir, timeout_s)
    if proc is None:
        return Reply(None, status, wall, model=label, remote=True)
    try:
        d = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return Reply(None, f"error: {(proc.stderr.strip() or 'no output')[:120]}", wall, model=label, remote=True)
    if d.get("is_error"):
        return Reply(None, f"error: {str(d.get('result'))[:120]}", wall, model=label, remote=True)
    usage = d.get("usage") or {}
    prompt = sum(usage.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    served = "+".join((d.get("modelUsage") or {}).keys()) or label
    return Reply(d.get("result"), "ok", wall, prompt, usage.get("output_tokens"), None,
                 (d.get("duration_api_ms") or 0) / 1000 or None, served,
                 cost_usd=d.get("total_cost_usd"), remote=True)


def _codex(spec: Spec, system: str, user: str, workdir: Path, timeout_s: float) -> Reply:
    label = f"codex:{spec.model or 'default'}"
    with tempfile.TemporaryDirectory(prefix="companion-codex-out-") as out:
        last = Path(out) / "last.txt"
        proc, status, wall = _run(argv(spec, system, workdir, last), f"{system}\n\n{user}", workdir, timeout_s)
        if proc is None:
            return Reply(None, status, wall, model=label, remote=True)
        text = last.read_text().strip() if last.exists() else ""
    usage: dict = {}
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed":
            usage = event.get("usage") or {}
    if proc.returncode or not text:
        return Reply(None, f"error: {(proc.stderr.strip() or 'no output')[-120:]}", wall, model=label, remote=True)
    generated = (usage.get("output_tokens") or 0) + (usage.get("reasoning_output_tokens") or 0)
    return Reply(text, "ok", wall, usage.get("input_tokens"), generated or None, model=label, remote=True)


def ask(spec: Spec | str, system: str, user: str, timeout_s: float = 180,
        workdir: Path | None = None) -> Reply:
    """`workdir` exists for the tripwire check, which must plant files where the agent runs; the
    companion itself never passes one."""
    spec = parse(spec) if isinstance(spec, str) else spec
    if spec.backend == "ollama":
        return chat(system, user, spec.model, base_url=spec.endpoint, timeout_s=timeout_s, num_ctx=spec.ctx,
                    num_predict=spec.tokens, cpu_only=spec.gpu == 0, keep_alive=spec.keep_alive)
    call = _claude if spec.backend == "claude" else _codex
    if workdir is not None:
        return call(spec, system, user, workdir, timeout_s)
    with tempfile.TemporaryDirectory(prefix="companion-provider-") as tmp:
        return call(spec, system, user, Path(tmp), timeout_s)
