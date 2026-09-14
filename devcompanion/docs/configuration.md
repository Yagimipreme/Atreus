# Configuration

Status: design, 2026-09-14.

**Implemented** in [config.py](../src/devcompanion/config.py) and
[llm/route.py](../src/devcompanion/llm/route.py):
- scopes and profiles
- routing chains, with the measured table as defaults
- `local-only`
- the machine grant
- `companion config --effective`

**Not yet:** the engine routing its model calls through it, and `engine.json` reporting the routing.

## Three scopes, one of which is a security boundary

| Scope | Location | Owns |
|---|---|---|
| machine | `~/.config/devcompanion/config.toml` | providers, endpoints, profiles, **and which projects may send content where** |
| project | `<repo>/.companion.toml` | observation, analysis, test policy, requested profile |
| session | CLI flags, `:CompanionProfile` | override for right now |

Later scopes override earlier ones, with one exception, and the exception is the point:

> **A file inside the repository may *request* remote content sharing. It may never *grant*
> it.** Granting lives in machine config, keyed by project path.

Without that rule a `git pull` can change whether your code leaves the machine, and a
committed `.companion.toml` becomes an attack surface on every contributor of every repository
you open. The project file says "this project would like the `flagship` profile"; the machine
file is what decides whether that project is allowed one.

## What is configurable

**Observation** — filetypes, debounce windows, ignore globs, maximum buffer size.

**Analysis** — test policy tier, test timeout, runner selection, whether tests run at all.
The tiers are S3's: `off`, `draft`, `draft-and-run`, `incorporate`. **Default is `draft`.**

**Profiles** — a name bound to a way of reaching a model:

```toml
[profile.local-qwen3-coder]
kind = "ollama"
model = "qwen3-coder:30b"
endpoint = "http://localhost:11434"
timeout_s = 20
max_input_tokens = 3500
keep_alive = "30m"

[profile.flagship]
kind = "cli"
provider = "claude:sonnet/low"   # an llm/providers.py spec; "codex:" fills the same role
timeout_s = 120
```

A profile never declares whether it is remote; that is derived, so it cannot be wrong. A `cli`
profile is remote, and an `ollama` profile is remote when its `endpoint` is not this machine.

**Functions route to profiles, never to providers.** `flagship` is a role, and machine config binds
it to Claude Code or Codex — swapping one for the other is one line, and no function, gate or
prompt changes. A prompt that only works on one provider is a defect, as it is for skills
([skills-and-modes.md](skills-and-modes.md)). Both CLIs run tool-less through
[llm/providers.py](../src/devcompanion/llm/providers.py) and passed the tripwire.

**Routing** — which profiles serve which function, **per function**, as an ordered chain:

```toml
[routing]
"passive.fix"       = ["local-qwen3-coder"]
"passive.sentence"  = ["local-fast"]
"pulled.fix"        = ["local-qwen3-coder", "flagship"]    # the flagship when the gate refuses
"pulled.grill"      = ["flagship", "local-qwen3-coder"]    # a prompt per kind of model
"pulled.culprit"    = ["flagship", "local-qwen3-coder"]    # no gate: first answer wins
"pulled.explain"    = ["flagship"]
```

These are defaults in `config.py` (`DEFAULT_ROUTING`); a machine or project `[routing]` table
replaces a function's chain. A function with no gate takes the first answer. So `["flagship",
"local-qwen3-coder"]` means the flagship in `hybrid`, and the local model in `local-only`, where the
flagship is removed. A profile a project names must exist in machine config.

A function may give each kind of model its own prompt, where the two measured differently at the same
job. Grill asks the flagship one richer question per turn, and asks the local model its three-question
prompt ([evaluations/chatty-functions.md](evaluations/chatty-functions.md)). The router hands each
profile its prompt (`llm/route.py`); the chain decides only which profile answers.

A chain tries its profiles in order and moves on only when the function's **gate** refuses the
answer. The gate belongs to the function, not to the configuration, because it is what makes the
answer trustworthy: the fix checker for fixes, the facts-kept check for sentences, "the packet
fits the context" for culprit questions. A function with no gate takes the first answer. The pane
names the profile that answered. The values above are the shape; the measured defaults and their
trade-offs are in [evaluations/function-routing.md](evaluations/function-routing.md).

**Local only** — a machine-level switch, and the default:

```toml
[machine]
mode = "local-only"      # or "hybrid"
```

In `local-only` every remote profile is removed from every chain when the configuration loads. A
function whose chain becomes empty is **unavailable**, and says so where it would have appeared;
it is never silently served by something else. It says what it needs and what the machine can give
instead:

```
Explain needs a reasoning model.
Available locally: symbols · references · types · diagnostics
```

A local best effort may be offered as an explicit, labelled choice, never as the default: a local
explanation measured wrong on half its cases would present bad output as intelligence
([evaluations/chatty-functions.md](evaluations/chatty-functions.md)). `hybrid` still requires the per-project grant
below before any content leaves the machine. Vision S7 makes fully local a first-class choice, not
a degraded one, so every function that has a local chain must work without a subscription.

The grant, in machine config, keyed by the project's path; and the request, in the repository:

```toml
# ~/.config/devcompanion/config.toml
[grant."/home/me/work/project"]
remote = true
```

```toml
# <repo>/.companion.toml -- asks, and is shown in --effective; grants nothing
[request]
remote = true
```

A passive function never keeps a remote profile, in any mode. The command line can narrow the mode
(`--local-only`), never widen it.

**Context** — QMD collections, maximum passages, provenance filter.

**Presentation** — pane width, maximum findings, stale handling.

## Why routing is data and not code

The tiering in [model-routing.md](model-routing.md) could be `if` statements in `engine.py`.
As a table it instead becomes:

- **inspectable** — the pane can name which profile produced a given finding
- **testable** — two profiles can serve the same function over the same recording, and replay
  is deterministic, so the comparison is real
- **policy-checkable** — "does any passive function route to a remote-allowed profile?" is a
  question you can answer by reading a table, and a rule the engine can enforce at load

That last one matters most. The passive/pulled split is a safety property, and a safety
property buried in control flow is one nobody can audit.

## Defaults

Everything local. Nothing remote. Tests `draft`. One profile. A workspace with no
configuration at all behaves exactly as the engine does today.

## Inspectability

`companion config --effective` prints the resolved configuration — every value, and which
scope it came from — plus, for each remote-capable profile, the exact bytes that would be sent
to it. Nothing remote is enabled before this exists; see [providers.md](providers.md).

`engine.json` reports the active profile and routing so the pane can show what is in force
without reading any config file itself.

## When to port the engine to Rust

Recorded here because it is a configuration-of-the-project decision, and because it keeps
coming up.

**Don't port. Extract, and not yet.**

The engine is ~1,600 lines of glue. Its hot path is hashing, tree-sitter, `rg` and `pytest` —
already C or subprocesses. Nothing measured puts Python on the critical path.

The scaling problem that will actually bite is **algorithmic, not linguistic**:
`SnapshotStore.history()` re-reads and re-parses a whole JSONL file on every call, and
`latest()` / `previous()` call it repeatedly; `known_paths()` reads every history file. Point
that at someRust's ~50 worktrees and it hurts long before interpreter overhead does. Porting
it would buy a fast implementation of the wrong algorithm.

Port a **component** when any two of these hold:

1. A measured passive-path regression that profiles to Python, not to `rg`/`pytest`/tree-sitter
2. One long-lived daemon across many worktrees where memory or startup is the constraint
3. Distribution to another machine or person becomes a goal — a single binary beats `uv` plus
   wheels
4. Tier C needs sandboxing with resource limits that Python supervision cannot express

The architecture already supports extraction: stages communicate through files and JSONL, so
the snapshot/index layer could become a separate binary without touching the rest — the same
discipline the adapter↔engine contract already uses. The Lua adapter stays Lua regardless, and
QMD is already its own binary.

**The anti-trigger, which outranks the triggers: do not port while the feature set is still
moving.** Protocol v2, the content view and the intake watermark were each found to be wrong
by running them. Rewriting a design that is still being discovered freezes the mistakes in a
language that makes them expensive to change.

## Sources

Vision S3, S7, S8, §7 (engine language, open); conversation 2026-09-14.
