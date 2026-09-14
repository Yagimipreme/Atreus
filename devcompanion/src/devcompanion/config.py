"""Configuration: machine, project and session scopes; profiles; a routing chain per function.

Design: docs/configuration.md. Three rules carry the weight, and all three are enforced here, at
load, rather than wherever a model happens to be called:

- **A repository may request remote content sharing; only machine config grants it**, keyed by the
  project's path. Profiles are machine scope for the same reason: a project names profiles in its
  routing, it never defines one, so a cloned repository cannot point the companion at an endpoint.
- **`local-only` is the default mode.** Every remote profile leaves every chain, and a function
  whose chain empties is unavailable -- it says what it needs and what the machine offers instead,
  and is never silently served by something else. A passive function never keeps a remote profile,
  in any mode.
- **Functions route to profiles, never to providers.** `flagship` is a role; machine config binds it
  to a providers.py spec, Claude Code or Codex, and nothing else changes.

Every effective value keeps the scope it came from, for `companion config --effective`.
"""
from __future__ import annotations

import os
import shlex
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import urlparse

from devcompanion.llm import providers

MODES = ("local-only", "hybrid")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

DEFAULT_PROFILES: dict[str, dict] = {
    "local-qwen3-coder": {"kind": "ollama", "model": "qwen3-coder:30b", "timeout_s": 60,
                          "max_input_tokens": 3500, "keep_alive": "30m"},
    # On the CPU: it stays loaded beside the 30B instead of evicting it from the 8 GB card.
    "local-fast": {"kind": "ollama", "model": "qwen2.5-coder:3b", "gpu": 0, "timeout_s": 30,
                   "max_input_tokens": 3500, "keep_alive": "30m"},
    "flagship": {"kind": "cli", "provider": "claude:sonnet/low", "timeout_s": 180},
}

# docs/evaluations/function-routing.md. A function whose answer has no gate takes the first answer,
# so `[flagship, local]` means the flagship in hybrid and the local model in local-only.
DEFAULT_ROUTING: dict[str, list[str]] = {
    "passive.fix": ["local-qwen3-coder"],
    "passive.sentence": ["local-fast"],
    "passive.change": ["local-qwen3-coder"],
    "pulled.fix": ["local-qwen3-coder", "flagship"],
    "pulled.summary": ["local-qwen3-coder"],
    "pulled.commit": ["local-qwen3-coder"],
    "pulled.grill": ["flagship", "local-qwen3-coder"],     # a prompt per kind of model; see chatty.system
    "pulled.suspicious": ["flagship", "local-qwen3-coder"],
    "pulled.culprit": ["flagship", "local-qwen3-coder"],
    "pulled.explain": ["flagship"],
    "pulled.plan": ["flagship"],
    "pulled.docs.write": ["flagship"],
    "pulled.architecture": ["flagship"],
    "pulled.roadmap": ["flagship"],
}

# What an unavailable function says, and what the machine can offer without a model.
UNAVAILABLE: dict[str, tuple[str, tuple[str, ...]]] = {
    "pulled.explain": ("Explain needs a reasoning model.", ("symbols", "references", "types", "diagnostics")),
    "pulled.plan": ("Plan needs a reasoning model.", ("symbols", "references", "callers", "diagnostics")),
    "pulled.docs.write": ("Writing documentation needs a reasoning model.", ("docstrings", "project docs")),
    "pulled.architecture": ("Architecture discussion needs a reasoning model.", ("symbols", "references", "project docs")),
    "pulled.roadmap": ("Roadmap discussion needs a reasoning model.", ("project docs",)),
}


def machine_path() -> Path:
    return Path(os.environ.get("COMPANION_CONFIG") or Path.home() / ".config/devcompanion/config.toml")


@dataclass(frozen=True)
class Profile:
    name: str
    kind: str                          # ollama | cli
    model: str = ""                    # ollama: the model tag
    provider: str = ""                 # cli: a providers.py spec, e.g. claude:sonnet/low or codex:
    endpoint: str = ""                 # ollama: empty means the local default
    timeout_s: float = 60
    max_input_tokens: int | None = None
    keep_alive: str = "30m"
    gpu: int | None = None
    ctx: int = 4096
    scope: str = "default"

    @property
    def remote(self) -> bool:
        """Derived, never declared: a profile cannot call itself local while reaching elsewhere."""
        if self.kind != "ollama":
            return True
        return bool(self.endpoint) and (urlparse(self.endpoint).hostname or "") not in LOCAL_HOSTS

    def spec(self, tokens: int) -> providers.Spec:
        if self.kind == "ollama":
            return providers.Spec("ollama", self.model, tokens=tokens, ctx=self.ctx, keep_alive=self.keep_alive,
                                  gpu=self.gpu, endpoint=self.endpoint or None)
        return replace(providers.parse(self.provider), tokens=tokens)

    def describe(self) -> str:
        if self.kind == "ollama":
            where = self.endpoint or "local"
            return f"ollama {self.model}" + (" on the CPU" if self.gpu == 0 else "") + f" · {where}"
        return f"cli {self.provider} · remote"


def _profile(name: str, raw: dict) -> Profile:
    kind = raw.get("kind")
    if kind == "ollama":
        if not raw.get("model"):
            raise ValueError(f"profile {name}: an ollama profile needs a model")
    elif kind == "cli":
        if not providers.parse(str(raw.get("provider", ""))).remote:
            raise ValueError(f"profile {name}: a cli profile needs a provider such as claude:sonnet or codex:")
    else:
        raise ValueError(f"profile {name}: kind must be ollama or cli, not {kind!r}")
    known = {f for f in Profile.__dataclass_fields__ if f != "name"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(f"profile {name}: unknown keys {', '.join(unknown)}")
    return Profile(name=name, **raw)


@dataclass(frozen=True)
class Step:
    profile: str
    removed: str = ""                  # why this profile is not in the effective chain


@dataclass
class Route:
    function: str
    steps: list[Step]
    scope: str

    @property
    def chain(self) -> list[str]:
        return [s.profile for s in self.steps if not s.removed]

    @property
    def available(self) -> bool:
        return bool(self.chain)

    @property
    def message(self) -> str:
        """What the function says where it would have appeared, when its chain is empty."""
        if self.available:
            return ""
        needs, local = UNAVAILABLE.get(self.function, (f"{self.function} has no model this machine may use.", ()))
        return needs + (f"\nAvailable locally: {' · '.join(local)}" if local else "")


@dataclass
class Config:
    root: Path
    mode: str
    mode_scope: str
    remote_allowed: bool
    remote_reason: str
    requested_remote: bool
    profiles: dict[str, Profile]
    routes: dict[str, Route]
    problems: list[str] = field(default_factory=list)

    def route(self, function: str) -> Route:
        if function not in self.routes:
            raise KeyError(f"no such function: {function}")
        return self.routes[function]


def _read(path: Path, problems: list[str]) -> dict:
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as error:
        problems.append(f"{path}: {error}; ignored")
        return {}


def load(root: Path, machine: Path | None = None, session: dict | None = None) -> Config:
    """`session` is what the developer said on the command line: `local_only` (it can only narrow
    the mode) and `models` ({profile: model}, for a local profile's model)."""
    root = root.resolve()
    problems: list[str] = []
    m = _read(machine or machine_path(), problems)
    p = _read(root / ".companion.toml", problems)
    s = session or {}

    for table in ("machine", "grant", "profile"):
        if table in p:
            problems.append(f".companion.toml: [{table}] is machine scope; ignored")

    mode, mode_scope = "local-only", "default"
    if "mode" in m.get("machine", {}):
        mode, mode_scope = m["machine"]["mode"], "machine"
    if mode not in MODES:
        problems.append(f"machine mode {mode!r} is not one of {', '.join(MODES)}; using local-only")
        mode, mode_scope = "local-only", "default"
    if s.get("local_only"):
        mode, mode_scope = "local-only", "session"

    granted = bool(m.get("grant", {}).get(str(root), {}).get("remote"))
    requested = bool(p.get("request", {}).get("remote"))
    if mode == "local-only":
        remote_allowed, reason = False, f"mode is local-only ({mode_scope})"
    elif not granted:
        remote_allowed = False
        reason = f"machine config grants no remote sharing to {root}" + ("; the project requests it" if requested else "")
    else:
        remote_allowed, reason = True, f"granted to {root} in machine config"

    raw = {name: {**v, "scope": "default"} for name, v in DEFAULT_PROFILES.items()}
    for name, v in m.get("profile", {}).items():
        raw[name] = {**raw.get(name, {}), **v, "scope": "machine"}
    for name, model in (s.get("models") or {}).items():
        if name in raw and raw[name].get("kind") == "ollama":
            raw[name] = {**raw[name], "model": model, "scope": "session"}
        else:
            problems.append(f"session model for {name}: not a local profile; ignored")
    profiles: dict[str, Profile] = {}
    for name, v in raw.items():
        try:
            profiles[name] = _profile(name, v)
        except (TypeError, ValueError) as error:
            problems.append(str(error))

    chains = {f: (list(chain), "default") for f, chain in DEFAULT_ROUTING.items()}
    for scope, table in (("machine", m.get("routing", {})), ("project", p.get("routing", {}))):
        for function, chain in table.items():
            if function not in DEFAULT_ROUTING:
                problems.append(f"{scope} routing: unknown function {function}; ignored")
            elif not (isinstance(chain, list) and all(isinstance(x, str) for x in chain)):
                problems.append(f"{scope} routing: {function} must be a list of profile names; ignored")
            else:
                chains[function] = (chain, scope)

    routes: dict[str, Route] = {}
    for function, (chain, scope) in chains.items():
        steps = []
        for name in chain:
            profile = profiles.get(name)
            if profile is None:
                steps.append(Step(name, "no such profile"))
            elif profile.remote and function.startswith("passive."):
                steps.append(Step(name, "a passive function never leaves the machine"))
            elif profile.remote and not remote_allowed:
                steps.append(Step(name, reason))
            else:
                steps.append(Step(name))
        routes[function] = Route(function, steps, scope)
    return Config(root, mode, mode_scope, remote_allowed, reason, requested, profiles, routes, problems)


def effective(config: Config, prompts: dict[str, str] | None = None) -> str:
    """The resolved configuration, each value with its scope, and -- for every remote profile a
    function may reach -- the command it would run and the system prompt it would receive. The user
    packet is what the function builds from the developer's selection at the time of asking."""
    out = [f"project   {config.root}",
           f"mode      {config.mode}  ({config.mode_scope})",
           f"remote    {'allowed' if config.remote_allowed else 'not allowed'}: {config.remote_reason}", "",
           "profiles"]
    for p in config.profiles.values():
        out.append(f"  {p.name:<20} {p.describe():<44} ({p.scope})")
    out += ["", "routing"]
    for r in config.routes.values():
        head = f"  {r.function:<20} "
        if r.available:
            line = head + " → ".join(r.chain)
        else:
            line = head + "unavailable: " + r.message.replace("\n", " ")
        removed = [f"{s.profile}: {s.removed}" for s in r.steps if s.removed]
        out.append(f"{line}  ({r.scope})" + (f"  [removed {'; '.join(removed)}]" if removed else ""))
    out += ["", "what leaves this machine"]
    reachable = {name for r in config.routes.values() for name in r.chain if config.profiles[name].remote}
    if not reachable:
        out.append(f"  nothing: no remote profile is reachable ({config.remote_reason})")
    for name in sorted(reachable):
        profile = config.profiles[name]
        spec = profile.spec(tokens=0)
        functions = [r.function for r in config.routes.values() if name in r.chain]
        out.append(f"  {name}: {profile.provider}, for {', '.join(functions)}")
        out.append(f"    runs     {shlex.join(providers.argv(spec, '<system prompt>'))}")
        out.append("    in       an empty scratch directory, with no tools")
        for function in functions:
            prompt = (prompts or {}).get(function)
            out.append(f"    {function} system prompt: " + (repr(prompt) if prompt else "not built yet"))
        out.append("    stdin    the packet the function builds from what the developer selected")
    if config.problems:
        out += ["", "problems"] + [f"  {p}" for p in config.problems]
    return "\n".join(out)
