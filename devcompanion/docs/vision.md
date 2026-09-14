# Vision — passive development companion

Status: draft agreed in conversation 2026-09-10. Settled items are decisions; defaults are mine
and stand until contradicted; open items need the operator.

## 1. Purpose

A companion that sits beside the developer, not across from them. The developer keeps the design in
their head and hands. The companion keeps the consequences of the last few edits ready: who else is
affected, what just broke, what the docs say about the API just reached for, what the running app now
does. The developer looks when they want to. It never asks to be looked at.

It replaces the interruption of leaving a train of thought to go check something, not the typing.
Every check the developer would do by hand in the next ten minutes is a candidate for having been done
already.

Implementation is part of design. Writing, running and testing code reveals questions the initial idea
did not contain. The companion strengthens that loop and leaves room for understanding to evolve.

## 2. Settled

| # | Decision | Source |
|---|---|---|
| S1 | Editor: Neovim first. The engine is a separate local process; the editor adapter is thin and only exchanges events and findings. | operator |
| S2 | Daily surfaces, in priority order: **Errors linked to recent changes**, **Callers**, **Docs**. | operator |
| S3 | Tests are not a surface the developer opens. They are a background capability, fully outsourced to the companion, governed by a per-project setting (off / draft only / draft and run / incorporate under policy). | operator |
| S4 | Interpretation of *what changed* comes first. Goal inference is secondary and always labelled as inference. | operator |
| S5 | The Roadmap surface is the one place for divergent, creative agent thinking: suggested forks and alternative directions. Everything else is convergent and evidence-bound. | operator |
| S6 | Target projects: whatever is current. Named today: the music server template (Python + JS web extension), agentbench (Python), someRust (Rust, many worktrees). Therefore the engine is **language-agnostic from day one** and leans on language servers, not per-language parsers. | operator |
| S7 | Model backends: the operator chooses fully local or any subscription / API model, per project. Sending project content to a remote backend is an explicit project setting, never a default. | operator |
| S8 | Hardware: must be useful CPU-only on a 10th-gen i7 laptop; GPU on the desktop is optional acceleration. | operator |
| S9 | No idea→approve loops. Background work creates no obligation to review. Empty output and "do nothing" are normal. | operator |
| S10 | Facts come from tools (LSP, compilers, tests, search, runs). Models allocate attention and summarize; they never become the source of a fact, an edit, or an "actual result". | spec |

## 3. What is possible, in three tiers

**Tier A — deterministic, reliable, worth having with no model at all.**
Callers affected by a change (LSP references + signature diff). Diagnostics attributed to the edit that
introduced them. Tests mentioning changed symbols run in isolation. Doc passages for the exact library
version in the lockfile. Mechanical actions with a previewed, freshness-checked diff.

**Tier B — interpretive, plausible with a 2B–4B local observer.**
"You are moving a boundary from str to Path; one caller is still on the old side." Picking which two of
ten cheap investigations to spend CPU on. Drafting test cases from contracts and existing tests. Right
perhaps two thirds of the time, acceptable only because a wrong observation costs an ignored finding,
never an edit. Unvalidated on this workload and these machines.

**Tier C — behavioral, later and expensive.**
A frozen isolated copy of the app running scenarios; function probes with real inputs; Compare between
baseline and candidate. Each stack needs its own build / start / reset / scenario definitions. No model
makes this cheap.

## 4. The experience in Neovim

Feels like a well-configured LSP, not a chat window. A stable set of surfaces reachable by keys;
contents follow the cursor, positions never move. A finding is location + evidence + consequence + next
action, shown in a split or the quickfix list the developer opens. Virtual text and hover only where
they cost nothing. Chat exists and shares the same context; the developer starts it.

Surfaces, first release: Errors, Callers, Docs, Chat. Roadmap once the observer exists. Tests as a
background setting with results surfacing inside Errors. Runtime only in Tier C.

## 5. Principles that decide close calls

- A finding without a location or a consequence is not shown.
- Nothing dismissed reappears without new evidence. Nothing built on code already changed is shown as current.
- Observed, inferred, predicted and outdated are always distinguishable.
- Inference runs on change, never on a timer. A silent laptop while the developer thinks.
- Editor never waits on inference, builds, or app runs.
- Generated artifacts and execution live in companion-owned space; developer files change only through explicit action or a narrowly configured policy.

## 6. Defaults (mine, standing until contradicted)

- Engine in Python, uv-managed, one process per workspace, JSONL event log + content-addressed snapshots as the replayable input. Already exists at Phase-0 level in this repo.
- Language facts via each project's language server (rust-analyzer, basedpyright, a TS server) driven from the Neovim adapter, since Neovim already holds the client. tree-sitter only for cheap structural diffs.
- Observer candidates: Qwen3.5-2B (portable) and 4B (comparison), 4-bit GGUF, llama.cpp, non-thinking, validated on replayed recordings before any live use.
- Main agent: provider-abstracted; Claude via API where the operator enables remote content, local model otherwise.

## 7. Open

- Exact laptop RAM and CPU model; whether the laptop is available for measurement.
- Doc retrieval source of truth per ecosystem (crates.io docs, PyPI, MDN) and offline caching policy.
- Test policy defaults per project and what "incorporate" means for review visibility.
- Roadmap: how forks are stored, expire, and are distinguished from the developer's own decisions.
- Transport between adapter and engine (JSONL files now; socket or MCP later).
- Whether the engine language stays Python once Tier C needs process isolation.

## 8. Not goals

Suggestion counts, generated line counts, accepted-edit rates. Inline completions. Replacing compilers,
language servers, test frameworks, or browser automation. Any claim about hardware suitability or
software quality without a measurement.
