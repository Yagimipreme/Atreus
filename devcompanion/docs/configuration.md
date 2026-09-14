# Configuration

Status: design, 2026-09-14. Not implemented.

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
content_policy = "local-only"

[profile.flagship]
kind = "cli"
command = ["claude", "-p", "--output-format", "json"]
timeout_s = 120
content_policy = "remote-allowed"
```

**Routing** — which profile serves which function:

```toml
[routing]
"passive.rank"     = "local-fast"
"passive.intent"   = "local-fast"
"pulled.explain"   = "local-qwen3-coder"
"pulled.plan"      = "flagship"
```

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
