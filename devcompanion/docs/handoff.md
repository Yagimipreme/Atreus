# devcompanion handoff

Status: 2026-09-14, second pass. This is the current pickup document for the passive
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

Latest documented result: **36 checks passed; 0 failed; 0 gaps.** Plus 60 unit tests.

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

1. **Model profiles and the provider abstraction.** Wire `local-qwen3-coder` first, then the
   two CLI providers with their tripwire tests. Keep model output optional and delayed; the
   `model` block in `engine.json` and the pane's model line already exist, so this is additive.
   See [providers.md](providers.md) and [configuration.md](configuration.md).
2. **Configuration loading** — three scopes, the routing table, `companion config --effective`.
   Nothing remote is enabled until `--effective` can print the bytes that would be sent.
   Includes skill discovery and capability negotiation
   ([skills-and-modes.md](skills-and-modes.md)): adopt the format now and author the passive
   tier's own prompts as skills, which exercises it against a real consumer before any chat
   surface exists.
3. **The live coding test.** Steps 1 and 2 are what make it possible: the 30B on per-save
   breaking sites, its paragraph in the pane with provenance. This is the gate on whether
   proposed edits get built at all.
4. **Edit actions**, in the order given in [edit-actions.md](edit-actions.md) — outbox writer,
   adapter buffer-apply and freshness refusal first, because refusal must exist before the
   first edit ships.
5. **QMD project warmup and provenance-filtered retrieval**, reported through the existing
   `context` field.
6. **Snapshot store read costs.** `history()` re-parses a whole JSONL file per call and
   `latest()`/`previous()` call it repeatedly; `known_paths()` reads every history file. This
   is the thing that will hurt on a many-worktree repository, and it is algorithmic — fix it
   before anyone reaches for a faster language.
7. **Dismiss.** The engine logs `dismiss` events and does nothing with them. Honouring one
   needs a suppression record keyed to the evidence, so it expires when the evidence changes.
8. **The Chat surface**, and only then modes. Modes are a routing key and a prompt prefix —
   the cheap half. The conversation they need (session state, turn history, context carried
   across turns) does not exist; the adapter is collect, transport, panel.

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
