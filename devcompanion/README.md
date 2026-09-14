# devcompanion

A passive development companion. You keep coding; it watches the buffer you are typing in,
snapshots what changed, detects what that change means, runs cheap investigations (callers,
tests), and keeps one side pane current. Nothing pops. Nothing asks for approval.

The distinguishing choice: **it analyses unsaved buffers**. While you are typing, the file on
disk is stale, and the interesting content is the one the file does not have yet. So each path
has a *disk revision* and, while a buffer is dirty, an *editor overlay*; analysis reads the
effective revision and every claim records which one it rested on. A caller you just typed into
a file you have never saved is still found.

Six stages, each inspectable on disk under `<repo>/.companion/`:

| stage | code | on disk |
|---|---|---|
| observe | `observe/` (inotify producer, Neovim producer via `inbox.jsonl`, replay) | `events.jsonl` |
| snapshot | `snapshot/store.py` (content-addressed, origin-tagged; git HEAD as lazy baseline) | `snapshots/{objects,history,freeze}` |
| view | `view/index.py` (disk revision vs editor overlay; effective revision; analysis manifest) | `view.json` |
| schedule | `schedule/detect.py` (tree-sitter signatures) + `schedule/queue.py` (debounce, cancel stale) | scheduler stats on the board |
| investigate | `investigate/callers.py` (rg + overlays + tree-sitter call judgement), `investigate/tests.py` (pytest) | — |
| evidence | `evidence/store.py` (claims with `based_on` shas; stale marking; no re-nag) | `evidence.jsonl`, `state.json` |
| present | `present/board.py`, `present/findings.py`, `present/status.py` | `board.md`, `quickfix.txt`, `findings.jsonl`, `engine.json` |

Optional: `llm/client.py` adds one sentence per breaking record from a local model. Model
unavailable, timeout, or garbage output all degrade to the deterministic board.

## What it will not do

- Claim an unsaved buffer is the file. Findings carry a `revision` per input.
- Present evidence from a tool that could not see your buffer without saying so. pytest reads
  the working tree, so its results are labelled saved-revision-only and are not run for
  buffer-only content.
- Open, focus, or interrupt. The pane opens on `:CompanionPanel` and hands the cursor back.
- Write to your files. Only `.companion/`.

## Try it

    uv sync --extra dev
    ./scripts/demo-phase1.sh /tmp/c1          # scripted saves -> board; leaves a recording
    uv run companion --root /nowhere --state /tmp/c1-replay replay examples/phase1-recording
    ./scripts/demo-live-nvim.sh /tmp/c2       # `companion watch` + headless Neovim save
    ./scripts/bench-llm.sh cpu qwen2.5-coder:3b

Editor: `companion nvim-plugin-path` prints the directory to add to `runtimepath`, then
`:CompanionStart` to observe and `:CompanionPanel` to look. See [nvim/README.md](nvim/README.md).

## Checks

    uv run pytest -q                          # unit suite
    .venv/bin/python scripts/check-workflow.py # real CLI, real engine, real headless Neovim

The second one is the one that matters: it drives the actual plugin against the actual engine
and asserts the things unit tests cannot reach — that both halves hash a buffer identically,
that an unsaved edit produces findings while the file is unchanged, and that the pane draws
what was published. Its latest result is in [docs/workflow/test-results.md](docs/workflow/test-results.md).

## Documents

| | |
|---|---|
| [docs/contract.md](docs/contract.md) | the adapter ↔ engine contract, v2 — the only thing the two halves share |
| [docs/text-canon.md](docs/text-canon.md) | canonical text: why an editor hash and an engine hash are the same number |
| [docs/intake-watermark.md](docs/intake-watermark.md) | the durable read position in the adapter's inbox |
| [docs/model-routing.md](docs/model-routing.md) | which model does which work, and why |
| [docs/providers.md](docs/providers.md) | how each model is reached; the safety gate on CLI agents |
| [docs/configuration.md](docs/configuration.md) | config scopes, the content-sharing boundary, the Rust question |
| [docs/edit-actions.md](docs/edit-actions.md) | the proposed edit and approval path |
| [docs/skills-and-modes.md](docs/skills-and-modes.md) | skill format, capability negotiation, and skill trust |
| [docs/handoff.md](docs/handoff.md) | current state, what is verified, what is next |
| [docs/vision.md](docs/vision.md), [docs/design.md](docs/design.md) | what this is for, and how it is put together |
| [docs/workflow/index.html](docs/workflow/index.html) | C4 and BPMN diagrams |
