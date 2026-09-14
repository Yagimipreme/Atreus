# Providers

Status: design, 2026-09-14. Not implemented.

How a model is reached. [model-routing.md](model-routing.md) decides *which* model does what;
this decides how each one is invoked, and what stops it doing damage.

## Two shapes, not one

**Local inference — an HTTP endpoint.** Ollama today (`llm/client.py`). An endpoint, a model
name, a timeout.

**Subscription — a CLI agent.** Claude Code and Codex are not HTTP APIs with a key; they are
command-line agents with their own authentication, invoked as subprocesses. This is mostly
good news: one abstraction covers them, there is no key management, and availability detection
is `shutil.which`.

| Provider | Shape | Invocation | Status |
|---|---|---|---|
| Ollama | HTTP | existing `llm/client.py` | built |
| Claude Code | CLI | `claude -p --output-format json` | planned |
| Codex CLI | CLI | `codex exec` | planned; output less structured |
| opencode | CLI | `opencode run` | **deferred** |

## The safety gate

A CLI agent is an *agent*. It has file tools and shell access. Pointed at the developer's
repository it can edit code — which is exactly what S10 and vision §5 forbid, and exactly what
the passive path must never be able to do.

So a provider adapter must, per provider:

- disable tools, or force read-only
- run with a working directory **outside** the developer's working tree
- receive its context in the prompt rather than being left to go and find it
- treat everything it returns as text

The flags that achieve this differ per CLI, and getting one wrong fails silently — the agent
edits something and nobody is told. So:

> **A provider is not enabled until an integration test asserts that a spawned agent could not
> modify a tripwire file.**

One test per provider, checked in, run by the harness. It is cheap and it is the only thing
standing between "read-only provider" and a claim.

The exception is deliberate delegation, which is a **separate provider configuration** with
tools enabled, reachable only from an explicit developer action, and sandboxed in a throwaway
git worktree. See [edit-actions.md](edit-actions.md).

## Free tiers are the least private option, not the most

`opencode` pointed at free models costs nothing in money and the most in content exposure:
free tiers commonly reserve the right to retain and train on prompts. Check the terms of the
specific model before enabling it for a project, and classify it accordingly in the project's
content policy — not as "free, therefore harmless".

This is part of why opencode is deferred: the provider shape is easy, the policy question is
not, and there is no reason to answer it before the two subscription providers work.

## What a provider adapter must report

`engine.json`'s `model` block already carries `{name, backend, status}` with `status` in
`ready | loading | unavailable | disabled`. Every provider fills it. An absent CLI is
`unavailable`, which is an ordinary state and not an error — the deterministic board is
unaffected either way.

Failures that must degrade rather than propagate: binary missing, not authenticated, rate
limited, timed out, empty output, unparseable output. Each yields no suggestion and a status
the pane can show. `llm/client.py` already behaves this way and is the model to follow.

## The context packet

What a subscription provider receives is bounded and inspectable, never "the repository":

- a system instruction: summarize evidence, cite sources, invent nothing
- the task kind
- manifest references — the paths, shas, origins and doc versions the claim rests on. The
  analysis manifest already exists (`view.manifest()`), so this is selection, not construction
- tool evidence: caller verdicts, diagnostics, test results, staleness
- selected QMD passages, each with source path, revision, document status and query provenance
- the developer's goal text, if they set one (`goal` events are already accepted)
- a strict output schema: summary, next action, confidence, unknowns, citations

**Nothing remote is enabled until `companion config --effective` can print the exact bytes
that would be sent.** Inspectability is a precondition, not a later refinement.

## Sources

Vision S7, S10, §5; [model-routing.md](model-routing.md);
[configuration.md](configuration.md).
