# devcompanion handoff

Status: 2026-09-14, third pass. This is the current pickup document for the passive
development companion. It covers what exists, what was verified, what is only designed, and
the next implementation order.

Read these when taking over:

- [README](../README.md) for the project shape and runnable demos.
- [contract v2](contract.md) for the adapter ↔ engine protocol as implemented.
- [canonical text](text-canon.md) for the hashing rule both halves obey.
- [intake watermark](intake-watermark.md) for the durable read position in the inbox.
- [model routing](model-routing.md) for which model does which work, and why.
- [providers](providers.md) for how each model is reached, and the safety gate on CLI agents.
- [configuration](configuration.md) for config scopes, the content-sharing boundary, and the
  standing decision on porting to Rust.
- [edits and approval](edit-actions.md) for the proposed edit path.
- [skills and modes](skills-and-modes.md) for the skill format, capability negotiation, and
  why a repository may offer a skill but not enable one.
- [workflow report](workflow/index.html) for the current C4 and BPMN diagrams.
- [workflow checks](workflow/test-results.md) for the latest verified run.
- [editor feedback design](editor-feedback-design.md) for the unsaved-buffer loop as designed.
- [proposed workflow diagrams](workflow/proposed/index.html) for the target C4 and BPMN flow.
- [local model and QMD design](local-model-and-context.md) for context budgets, QMD retrieval,
  and model evaluation order.
- [local model results](evaluations/local-model-results.md) for measured Qwen3-Coder and
  fallback behavior.

## User direction

The user wants an MVP that observes Neovim while they code, gives passive feedback in a side
pane, and can use a local model first. The agreed direction is unchanged:

- Test locally with `qwen3-coder:30b` before any hosted API.
- Keep deterministic evidence useful without a model.
- A single Neovim side pane with live fields for each output.
- A provider/profile option, not just raw `--model`, so a local or flagship model can be
  selected deliberately.
- Define exactly what a flagship model receives: a bounded, inspectable context packet, not
  the whole repository.
- Let QMD warm project context on Neovim/project open, but keep QMD local and engine-managed.
  The model receives selected passages with provenance; it does not freely query arbitrary
  personal/global knowledge in the MVP.

## What changed in this pass

Steps 1–7 of the previous implementation order are done. Both previously confirmed gaps are
closed and are now asserted as capabilities.

**The engine analyses unsaved buffers.** This was the whole point of the project and it did
not work: `observe/events.py` rebuilt only its own small field list on intake, so `text`,
`dirty`, `session`, `doc_version` and the rest were dropped and the editor's content never
reached the engine. Protocol v2 keeps them, and keeps unknown fields in `Event.extra` rather
than discarding them.

**Canonical text is defined and pinned.** The adapter hashed lines joined with `\n`; the engine
hashed the bytes on disk. Those differ for any file with a trailing newline, which is all of
them — so every hash comparison would have failed the moment a buffer was saved. The rule is
now [text-canon.md](text-canon.md): the bytes Neovim would write, per `fileformat` and `eol`.
Fixtures in `tests/fixtures/text-canon.json` are checked by both the Python suite and a real
`:write` in a headless Neovim. That check immediately caught a wrong special case for the
empty buffer, which is what it was for.

**Content-view index** (`view/index.py`). Each path has a disk revision and, while a buffer is
dirty, an editor overlay. `effective()` picks the overlay when there is one. `manifest()` is
the analysis manifest — the revision each claim was actually computed from.

**Unsaved edits are judged against the last save**, not against the previous keystroke pause.
Comparing consecutive drafts would split one edit across debounce windows and report it as a
stream of noise.

**Callers are searched over effective revisions.** `rg` reads files, so a call typed a second
ago is invisible to it; dirty paths are added to the candidate set. A related bug turned up
while testing: a file that *newly* mentions a changed callee never re-judged the existing
claim, because staleness only fires for files the claim already depended on. A new or newly
relevant caller file now re-submits the defining file. This was broken for saved files too.

**The engine publishes to the editor.** `findings.jsonl` and `engine.json`, both written
whole and atomically. `engine.json` carries the analysis manifest, so the editor can answer
"is this talking about the code in front of me?" rather than guessing from timestamps.

**One side pane** (`nvim/lua/companion/panel.lua`), replacing the per-surface scratch buffers.
`render.lua` became `findings.lua`, a store with no windows in it. `:CompanionErrors` and
`:CompanionCallers` are the same pane, filtered.

**Saved-test distinction.** pytest reads the working tree, so it is not run for buffer-only
content at all, and its evidence is labelled saved-revision-only — including the names of
unsaved buffers it could not speak for. The published finding carries `saved_revision_only`.

**Buffers open before start are announced.** `collect.start()` only registered autocmds, so a
buffer that was already open — possibly with unsaved work already in it — was invisible to the
engine until the next keystroke. It now sends each loaded buffer of this workspace once.

**Session end.** An editor that quits takes its unsaved buffers with it. `VimLeavePre` sends
`session_end` (synchronously — the event loop stops before an async write would land), and the
engine drops that session's overlays and re-judges the affected paths. Without it the engine
would go on reporting content that exists nowhere.

Two smaller fixes found on the way: the adapter never set `source`, so every event was logged
as `cli`; and `vim.json.decode` turns JSON `null` into `vim.NIL`, a userdata sentinel, which
threw on the first `engine.model.name or "none"`. All adapter JSON now goes through
`util.decode_json`.

## What changed in the third pass

The intake watermark, the local model tier, and the first live session. Three commits:
`devcompanion: passive development companion` (initial), `model tier: keep resident, call per
save…`, `findings: a published field is a line…`, `engine: a heartbeat that stops while idle…`.

**The intake watermark is done** ([intake-watermark.md](intake-watermark.md)). `companion watch`
resumes where it left off instead of replaying the editing history on every restart. Two
mechanisms together: a byte offset for cost, and a per-session accepted-sequence mark for
correctness when the offset has to be reset. Session ids are now unique per Neovim instance —
`math.random` is unseeded in LuaJIT, so every instance had been returning the same id.

**The local model is wired and in use.** `qwen3-coder:30b` through Ollama, called per save and
only when breaking call sites exist, with `keep_alive` so the model stays resident. A claim is
asked about once: re-deriving an unchanged claim reuses the stored sentence.

**Six defects came out of running it**, none from the test suite. They are listed under
*Verified behavior* below because each is now covered. The pattern is recorded globally in
`global-lessons` — a green suite is a regression net, not a discovery instrument.

## Current implementation

Two halves communicate through files under `<workspace>/.companion/`.

```text
Neovim Lua adapter              .companion/ files             Python engine
------------------              -----------------             -------------
collect.lua sends events  ->     inbox.jsonl             ->    watch/tail
findings.lua holds state  <-     findings.jsonl          <-    present/findings.py
panel.lua draws           <-     engine.json             <-    present/status.py
adapter may answer LSP    <-     outbox.jsonl            <-    not produced yet
                                  board.md, quickfix.txt
                                  events.jsonl, evidence.jsonl, state.json
                                  view.json, snapshots/
```

`outbox.jsonl` is the one contract file the engine still does not write. That is correct for
now: it has no LSP question to ask. The adapter already tails it.

## Verified behavior

The harness is [scripts/check-workflow.py](../scripts/check-workflow.py). It uses real CLI
execution, the real engine, real pytest, and real headless Neovim.

Latest documented result: **44 checks passed; 0 failed; 0 gaps.** Plus 89 unit tests.

```bash
uv run pytest -q
.venv/bin/python scripts/check-workflow.py
```

Beyond the previously passing saved-file workflow, the harness now establishes:

- Canonical text hashes identically in the adapter, the engine, and the file Neovim writes,
  across every fixture case.
- An unsaved signature change produces caller findings while the file on disk is unchanged.
- The adapter's `text_sha`, the engine's `content_sha`, and the sha a finding depends on are
  one value.
- Protocol v2 fields survive intake; buffer text does not enter the event log.
- `findings.jsonl` and `engine.json` are written, with per-input revision origins.
- The pane draws the header and findings, does not steal focus, and toggles closed.
- Saving retires the overlay; the same bytes moving from buffer to disk re-runs the tools that
  read files.
- Quitting the editor drops its overlays.
- Buffers already open when `:CompanionStart` runs are announced immediately, including an
  already-modified one, rather than waiting for the next keystroke.
- `companion watch` resumes at its recorded position and re-reads nothing, on both a clean
  restart and after the inbox is rotated or truncated.
- The local model is asked once per claim, never while typing, and its sentence reaches the
  pane. Tested against a real HTTP server on a loopback port, not a mock, because what is worth
  asserting is the request body and the call count.
- A published finding field never contains a newline. Neovim refuses to set a buffer line
  containing one, so a multi-line language-server message did not render badly — it raised and
  killed the pane on every republish.
- Liveness and findings are published on different cadences: `engine.json` every five seconds
  while idle, `findings.jsonl` only on change.
- A workspace nested inside its git repository still gets committed-version baselines. Found
  by running the engine on this project after it was committed into `~/repos`: `git show
  HEAD:<path>` resolves from the repo root, so every file read as first-seen and the companion
  said nothing at all. Every harness fixture is its own repo rooted at the workspace, which is
  why nothing caught it.

## Model state

Unchanged from the previous pass; no hosted API call has been made.

`qwen3-coder:30b` is wired and running. Measured through the engine's own request path on
2026-09-14: **cold load 25.4 s, warm 0.87 s** (5.5 GB resident in VRAM of 19.2 GB, partial
offload on the 8 GB card). This supersedes the earlier 15.437 s / 1.66 s figures from the
standalone evaluation harness. `qwen2.5-coder:3b` remains the fast fallback at ~0.15–0.21 s but
was weaker on mixed caller prompts; `qwen3:4b`, the size the vision actually named for the
passive tier, is installed and has never been measured on this workload.

The model is called **per save only**, never per keystroke pause, and only when breaking call
sites exist. `keep_alive` defaults to 30m (`--keep-alive`), without which most saves after a
pause pay the cold load.

Use `qwen3-coder:30b` as the primary local candidate for optional background suggestions. Keep
deterministic findings immediate and append model text when it arrives. Continue to pass only
breaking sites to the model.

Evaluation artifacts: [Qwen3-Coder raw](evaluations/qwen3-coder-30b.json),
[3B baseline raw](evaluations/qwen25-coder-3b.json),
[summary](evaluations/local-model-results.md).

## QMD and context

Unchanged and still designed, not built. `engine.json` already carries a `context` field
reporting `qmd disabled`, and the pane renders it, so wiring retrieval in is additive.

QMD keyword retrieval was smoke-tested against an isolated temp collection of copied project
docs: three queries at ~0.112–0.117 s. That proves local retrieval, not semantic quality or
end-to-end RAG quality. It returned both proposal and historical documents, so provenance is
mandatory: the context builder must know whether a passage is current implementation, accepted
decision, proposal, historical note, or external reference.

For the MVP:

- QMD may run during project/session warmup after Neovim starts the companion.
- Warmup is asynchronous and visible in the pane as `warming`, `ready`, or `unavailable`.
- QMD indexes a project-scoped curated collection, not arbitrary global notes.
- Unsaved code and live saved code do not belong in the documentation index. They come from
  editor overlays and the analysis manifest.
- A hosted or flagship model receives only selected passages with source path, hash/revision,
  status, and query provenance.
- Do not automatically call a remote flagship model on open. Retrieval warmup is fine; remote
  generation depends on explicit provider/profile and content-sharing policy.

## Provider/profile design

Still designed, not built. The CLI has `--model`; the user asked for something like `-p` for a
flagship subscription/API model. Prefer a profile abstraction so flags stay clear and policy
lives in config.

```bash
uv run companion --root . watch --profile local-qwen3-coder
uv run companion --root . watch --profile local-fast
uv run companion --root . watch --profile flagship
```

- `local-qwen3-coder`: Ollama `qwen3-coder:30b`, 4K starting context, local content only.
- `local-fast`: Ollama `qwen2.5-coder:3b`, fallback or latency comparison.
- `flagship`: authenticated provider endpoint, only if project policy permits remote content.

Per-profile settings: endpoint, model id, timeout, max input budget, content-sharing policy.
Avoid letting `-p` mean both provider and profile unless the CLI help is explicit.

What a flagship model receives:

- A system/task instruction: summarize evidence, cite sources, invent nothing.
- The task kind: one-sentence caller suggestion, diagnostic explanation, investigation advice,
  architecture discussion.
- Manifest references: relevant snippets, hashes, document versions, saved/unsaved status,
  generation id. The analysis manifest already exists (`view.manifest()`), so this is now a
  matter of selection rather than construction.
- Tool evidence: caller verdicts, diagnostics, test results, stale/current status.
- Selected QMD passages only when needed, each with source path, hash/revision, document
  status, and query provenance.
- Optional user goal text. The engine already accepts and records `goal` events.
- A strict output schema: summary, next action, confidence, unknowns, citations.

The model does not receive the whole repository by default, and does not decide freshness. The
coordinator accepts a model result only if its parent manifest is still current.

## Standing decisions (conversation, 2026-09-14)

These were settled in conversation and are recorded so they are not relitigated. Each has a
document; this is the index.

| Decision | Where |
|---|---|
| Routing is decided by who asked (passive vs pulled), not by model size | [model-routing.md](model-routing.md) |
| S8, the laptop constraint, is **backlogged not retired**; target is the current host | [model-routing.md](model-routing.md) |
| Subscription providers are CLI agents (Claude Code, Codex), not HTTP APIs | [providers.md](providers.md) |
| opencode is **deferred** | [providers.md](providers.md) |
| A provider is not enabled until a tripwire test proves it cannot edit files | [providers.md](providers.md) |
| A repo file may request remote content sharing; only machine config may grant it | [configuration.md](configuration.md) |
| Routing lives in configuration as data, not in `if` statements | [configuration.md](configuration.md) |
| Test policy default is `draft` | [configuration.md](configuration.md) |
| Do not port the engine to Rust; extract a component, and not while the design is moving | [configuration.md](configuration.md) |
| Edits are in scope; the engine never writes a developer file — the adapter applies to a buffer | [edit-actions.md](edit-actions.md) |
| Agent delegation runs in a throwaway worktree and returns a diff | [edit-actions.md](edit-actions.md) |
| Modes and skills are different things; modes are pulled-tier only and never escalate permissions | [skills-and-modes.md](skills-and-modes.md) |
| Skills use the portable `SKILL.md` subset; everything else is namespaced under `devcompanion/` | [skills-and-modes.md](skills-and-modes.md) |
| Capability negotiation checks tools **and** context budget, not tools alone | [skills-and-modes.md](skills-and-modes.md) |
| A repository may offer a skill; only machine config may enable one. Modes are machine-scope only | [skills-and-modes.md](skills-and-modes.md) |
| `qwen3-coder` is the reference implementation — the floor a skill must clear, not the ceiling | [skills-and-modes.md](skills-and-modes.md) |

Open, pending a live coding test: whether a *proposed edit* is worth having at all, judged
once the model's paragraphs have been seen in real use.

## Next implementation order

1. **The live coding test is running and unfinished.** The engine is wired, the model answers,
   the pane renders. What is missing is a judgement: are the sentences worth having? That
   answer gates whether proposed edits ([edit-actions.md](edit-actions.md)) get built at all,
   and it is the only item here that cannot be worked around.

   Two observations already on the table from the first minutes of use:

   - The panel echoes editor diagnostics the developer can already see in their sign column and
     virtual text — four of five entries in the first real session. Warnings were excluded for
     exactly that reason and errors were republished anyway, which does not hold up. Candidate
     rule: show what the editor cannot already say, or restrict the echo to files that are not
     open.
   - A diagnostic finding repeats its title verbatim in its evidence line. Small, and a defect.

2. **Provider abstraction.** The Ollama path is built; the two CLI providers (Claude Code,
   Codex) are not, and neither is the tripwire test that must gate each one. opencode is
   deferred. See [providers.md](providers.md).

3. **Configuration loading** — three scopes, the routing table, `companion config --effective`.
   Nothing remote is enabled until `--effective` can print the bytes that would be sent.
   Includes skill discovery and capability negotiation
   ([skills-and-modes.md](skills-and-modes.md)); author the passive tier's own prompts as
   skills to exercise it before any chat surface exists.

4. **Edit actions**, in the order in [edit-actions.md](edit-actions.md) — outbox writer,
   adapter buffer-apply and freshness refusal first, because refusal must exist before the
   first edit ships. Gated on item 1.

5. **QMD project warmup and provenance-filtered retrieval**, through the existing `context`
   field.

6. **Snapshot store read costs.** `history()` re-parses a whole JSONL file per call and
   `latest()`/`previous()` call it repeatedly; `known_paths()` reads every history file. This
   is what will hurt on a many-worktree repository, and it is algorithmic — fix it before
   anyone reaches for a faster language.

7. **Dismiss.** Logged and ignored. Honouring one needs a suppression record keyed to the
   evidence, so it expires when the evidence changes.

8. **The Chat surface**, and only then modes. Modes are a routing key and a prompt prefix — the
   cheap half. The conversation they need does not exist.

## Known risks and edges

- The intake watermark is implemented ([intake-watermark.md](intake-watermark.md)) but the
  inbox still grows without bound: the watermark makes restart cost O(1), which turns growth
  into a disk-space question rather than a correctness one. Compaction races with the adapter's
  appends and needs its own design.
- A file changed on disk while the engine was down is still missed. `fswatch` has no durable
  position; a startup rescan against the snapshot store is a separate mechanism.
- An event accepted but whose investigation had not finished when the engine died is not
  re-investigated. The content is snapshotted so nothing is lost, but no claim is derived until
  that path changes again.
- Tests on unsaved code need a separate materialized runner. The MVP analyses unsaved code and
  runs tests only after saves, and says so; running them against a materialized overlay is a
  later decision, not an oversight.
- Multiple active Neovim sessions for one workspace are deferred. The engine follows one
  session at a time: a new `session` id clears the previous one's overlays, which is correct
  for handoff between editors and wrong for two editors at once. Conflict reporting is unbuilt.
- A file written by something other than the editor while a buffer is dirty keeps its overlay,
  by design. The pane shows both the unsaved buffer and the file's revision, but there is no
  explicit conflict state yet.
- QMD warmup and Ollama model loading may compete for RAM/GPU. Measure them together before
  enabling broad retrieval by default.
- 16 hex characters of sha256 is an equality check on developer-authored content, not a defence
  against a chosen-prefix attack. A collision surfaces as one stale finding.
- Rotation or truncation of the inbox **while the engine is running** is not detected and
  silently drops events. Nothing in-tree triggers it, and the trap for whoever fixes it is
  recorded in [intake-watermark.md](intake-watermark.md)'s Known limits.
- The engine has only ever been run against Python. Detection and caller judgement are
  Python-specific despite S6 calling for language-agnosticism through language servers.

## What was promoted to the global knowledge base

Durable, cross-project conclusions from this work live in `~/knowledge-global`, not here, per
its rule that repo-specific layout stays in the repo. Searchable with a bare `qmd query`:

| Page | Domain |
|---|---|
| `models/qwen3-coder-30b` — sub-second warm, 25 s cold, usable only while resident | `global-ai-models` |
| `gotchas/neovim-plugin-api-traps` — vim.NIL, unseeded math.random, buffer lines reject newlines, VimLeavePre | `global-lessons` |
| `failures/tests-cover-only-the-staged-path` — staging the interesting case leaves the ordinary one untested | `global-lessons` |
| `wisdom/run-it-before-believing-the-suite` — six defects, all from running, none from the suite | `global-lessons` |
| `patterns/cross-language-content-hash` — fixtures verified against what the storage side writes | `global-engineering` |
| `patterns/implement-review-run` — three verification layers catching disjoint defect classes | `global-agent-patterns` |

## The live session

A watcher is running against this repository with the model attached:

```bash
uv run companion --root . --model qwen3-coder:30b --keep-alive 30m watch
```

The Neovim side is registered as a lazy.nvim plugin, so `:CompanionStart` and
`:CompanionPanel` are available without touching `runtimepath` by hand.

**The operator's autosave is disabled for the duration** (both `InsertLeave`/`TextChanged` and
`CursorHold` write autocmds, commented in their `init.lua` with a restore note and a backup).
This matters more than it sounds: writing on `InsertLeave` means the buffer is saved the moment
insert mode ends, so the unsaved-buffer window — the thing this project exists to observe —
only existed while actively typing. With autosave on, a live test measures the saved-file path
that already worked.

## Useful commands

```bash
uv sync --extra dev
uv run pytest -q
.venv/bin/python scripts/check-workflow.py
./scripts/test-plugin.sh /tmp/smoke            # adapter alone, no engine
./scripts/demo-phase1.sh /tmp/c1
./scripts/demo-live-nvim.sh /tmp/c2
uv run python scripts/evaluate-local-model.py --model qwen3-coder:30b
uv run companion --root <dir> watch
uv run companion --root <dir> ingest <paths>
uv run companion --root <dir> --state <state-dir> replay examples/phase1-recording
```

## Current working tree note

This project directory sits inside a broader Git repository rooted at `/home/iqqe/repos`. Many
sibling paths appear as untracked from Git's point of view. Do not clean or reset them. Keep
edits scoped to `/home/iqqe/repos/devcompanion` unless the user asks otherwise.
