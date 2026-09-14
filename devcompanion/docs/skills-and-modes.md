# Skills and modes

Status: agreed in conversation, 2026-09-14. Format decided; modes deferred until a chat
surface exists.

## The distinction

A **skill** is specialist knowledge for a task: *when reviewing architecture, investigate
component ownership, boundaries, dependency direction, failure behaviour.* Portable, static,
about the subject matter.

A **mode** is how the agent interacts: *do not solve it; interrogate the reasoning, one
question at a time, challenge unstated assumptions.* About the conversation, not the subject.

Conflating them is a category error, and it shows up as instructions that a model has to
"discover" a personality it was supposed to be given. So they are separate, and they compose:

```
:Companion grill architecture
  → mode grill · skill architecture · permissions read-only · context repository
```

Modes can load skills. Skills can declare a default mode. Neither is the other.

## Two boundaries that make this safe

**Modes are pulled-tier only.** Everything the companion does today is passive: the engine
decided, nobody typed anything. A mode is by definition selected by the developer, so modes
live entirely on the pulled side of [model-routing.md](model-routing.md). Passive functions
have a *task* and no mode, because there is no conversation to have a personality in. This is
what makes modes safe to add — they cannot disturb any background behaviour.

**A mode never escalates permissions.** `grill` and `plan` are read-only by construction.
Reaching an edit means going through the approval path in
[edit-actions.md](edit-actions.md), never through a mode switch.

## Format

Skills use the portable `SKILL.md` subset — `name` and `description` at the top level, and
nothing else. Everything specific to this runtime is namespaced:

```markdown
---
name: architecture-review
description: Review software architecture and challenge design decisions.
metadata:
  devcompanion/mode: discuss
  devcompanion/permissions: read-only
  devcompanion/requires: [repo.read, repo.search]
  devcompanion/optional: [git.history, lsp.references]
  devcompanion/budget:
    context_tokens: 16000
    structured_output: false
---

# Architecture Review
...
```

Namespacing everything beyond `name` and `description` is deliberate, even for concepts as
general-sounding as `requires`. An unnamespaced key that some future standard defines
differently is not a crash — it is a **silent misinterpretation of instructions**, which for a
file whose whole purpose is steering a model is the worst available failure. Migrate to a
common key when one actually exists.

Other runtimes ignore what they do not recognise, which is the point.

## Capabilities are not just tools

A capability check that only tests for tool presence gives the wrong answer for the case that
matters:

```
repo.read   ✓
repo.search ✓
→ Qwen can run architecture-review
```

Qwen at 4K context passes that and then falls over on eight files. The runtime says "usable",
the developer gets slop, and it reads as a bad model rather than a bad match.

So negotiation is **three** checks — tools, budget, output shape:

| Declared | Checked against |
|---|---|
| `requires` | provider capability set |
| `budget.context_tokens` | provider `context_window` |
| `budget.structured_output` | provider `capabilities.structured_output` |

Initial capability vocabulary: `repo.read`, `repo.search`, `repo.write`, `git.history`,
`lsp.references`, `lsp.definition`, `lsp.hover`, `lsp.symbols`, `tests.run`, `kb.search`,
`shell`, `web`.

Skills declare capabilities, never models. `requires: claude` is never valid; if a skill
genuinely depends on model-specific behaviour that is a defect in the skill.

**`context: repository` means retrieval scope, not payload.** What enters the model's context
is selected passages plus the analysis manifest — the same bounded, cited packet specified in
[providers.md](providers.md). Naming the repository says where to search, never what to send.

## Discovery, and why project skills are untrusted

Read from, in precedence order:

1. `~/.config/devcompanion/skills/` — machine scope, trusted
2. `<repo>/.agents/skills/` — canonical project location
3. `<repo>/.claude/skills/`, `<repo>/.opencode/skills/` — compatibility

A skill is instructions that steer a model, and locations 2–4 are **files in the repository**.
Auto-loading them means a cloned repo can inject instructions into your agent.

This is the rule already settled for content sharing in
[configuration.md](configuration.md), applied unchanged:

> **A repository may offer a skill. Only machine config may enable one.**

Project-local skills are listed and visible but never auto-enabled — most of all any declaring
`shell` or `repo.write`. On a name collision the machine-scope skill wins and the collision is
reported; a project skill never silently shadows one you wrote.

This matters more here than for a chat agent, because this engine runs passively. A skill that
silently informs background behaviour is a real vector. `:Companion grill architecture` is an
explicit act and is fine.

**Modes are machine-scope only.** A repository cannot change how the agent talks to you, so
`modes/` has no project location at all.

## Reference implementation, not ceiling

`qwen3-coder` locally is the reference: a skill that does not work there is not finished. That
is what stops `Use your Claude Code Task tool to spawn…` leaking into a skill and destroying
portability.

The inverse failure is just as real — if the reference defines what a skill may assume, skills
get written down to it and subscription models never do anything it could not. `optional:` is
the mechanism that prevents this:

> A skill must work on the reference, and may get **better** with optional capabilities.

Make degradation testable rather than aspirational: run each skill against the reference and
against a subscription profile over the **same replayed recording**, and diff. Replay is
deterministic and verified, so this is the same harness the routing evaluation in
[model-routing.md](model-routing.md) needs — one piece of machinery, two questions.

## Integration with what already exists

- A mode is a **routing key**: `routing["pulled.grill"] = "flagship"`. No new machinery; see
  [configuration.md](configuration.md).
- `permissions` enforces at the same point as the provider tripwire gate in
  [providers.md](providers.md).
- Command namespace stays `:Companion…`, not a second `:Agent…` prefix.

## Sequencing

**Adopt the format and capability negotiation now. Defer modes until Chat exists.**

The format is cheap to decide and expensive to change, so decide it early. It can be exercised
immediately without any new surface: the passive tier's prompts — rank, intent, explain — are
authored as skills, which tests discovery, negotiation and budget checking against a real
consumer before there is a chat window to argue about.

Modes imply a conversation, and there is none. The adapter is collect, transport, panel; Chat
is in the vision (§4) and unbuilt — session state, turn history, context carried across turns.
The mode abstraction is the easy half.

**Start with two modes and two skills, not a matrix.** `discuss` and `grill` earn their place;
`concise` is a sentence in a system prompt and `teach` is speculative. `review-code` and
`architecture` have obvious use; `explain-code` overlaps what the panel already does
deterministically. Five modes times five skills is twenty-five combinations one person will
mostly never type. Let the set grow from use, not from symmetry.

## Sources

Vision §4 (Chat), S10; conversation 2026-09-14; the open Agent Skills `SKILL.md` subset.
