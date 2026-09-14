# devcompanion workflow check — 2026-09-14

**36 checks passed; 0 failed; 0 integration gaps reproduced.**

Rerun from the project root: `.venv/bin/python scripts/check-workflow.py`.
The harness creates fresh disposable Git projects and stops its watcher on exit.
No local or remote model was called.

Everything below goes through a real subprocess: `companion ingest`, `companion watch`,
`companion replay`, `pytest`, and `nvim --headless` running the actual plugin. Neovim runs
without swap or ShaDa persistence.

This run supersedes the 2026-09-14 run that recorded 18 passes and two confirmed gaps
(*Unsaved ingestion*, *Editor return files*). Both gaps are closed and are now asserted as
capabilities rather than reproduced as absences; the rows that replaced them are named below.

Artifacts: `/tmp/devcompanion-check-3j1b7ej8`

| Result | Scenario | Observation |
|---|---|---|
| PASS | Existing unit suite | 60 passed in 0.13s |
| PASS | Canonical text agrees across Lua, Python and disk | 11/11 fixture cases hash identically in the adapter, the engine, and the file Neovim writes |
| PASS | Baseline | No breaking finding for unchanged committed files |
| PASS | Breaking signature | 2 call site(s): 2 break, 0 unsure, 0 fit |
| PASS | Tests detect breakage | failed: 1 failed in 0.01s |
| PASS | Quickfix | Two breaking caller locations expected |
| PASS | Unchanged save | No task bundle ran |
| PASS | Fix one caller | 2 call site(s): 1 break, 0 unsure, 1 fit |
| PASS | Fix all callers | 2 call site(s): 0 break, 0 unsure, 2 fit |
| PASS | Tests recover | passed: 1 passed in 0.00s |
| PASS | Quickfix clears | No remaining caller warnings |
| PASS | Replay without working tree | Non-test evidence fingerprints match live final state |
| PASS | Replay skips execution | skipped: replay never executes code |
| PASS | Invalid Python | Parse error produces unknown_intent |
| PASS | Removed function | 2 call site(s): 2 break, 0 unsure, 0 fit |
| PASS | Rapid submissions coalesce | {"submitted": 3, "coalesced": 1, "ran": 2} |
| PASS | Buffers open before :CompanionStart are announced | announced ['calc.py', 'client.py']; the modified one is sent as an unsaved buffer, the clean one seeds the baseline, and buffers outside the workspace are skipped |
| PASS | Lua emits unsaved text | Actual Neovim TextChanged event contains edited text |
| PASS | Unsaved ingestion | 2 call site(s): 2 break, 0 unsure, 0 fit — while calc.py on disk still holds the original signature |
| PASS | Unsaved analysis says so | unsaved buffer; the file on disk still holds the previous version |
| PASS | Unsaved edit runs no tests | pytest reads the working tree, so it is not run for buffer-only content |
| PASS | Adapter and engine agree on the buffer hash | adapter 349c879ed44bc4be, engine 349c879ed44bc4be, finding depends on 349c879ed44bc4be |
| PASS | Protocol v2 fields survive intake | dirty=True session=cb511a84 doc_version=5 language='python' origin=editor source=nvim; buffer text stays in the snapshot store, not the event log |
| PASS | Engine reports the unsaved buffer | {"state": "idle", "dirty_buffers": ["calc.py"], "findings": 2} |
| PASS | Findings published for the unsaved edit | 2 caller_affected finding(s), each marked as resting on buffer content |
| PASS | Panel renders engine state | header fields drawn: buffer, context, engine, model, unsaved |
| PASS | Panel shows the unsaved caller finding | client.py:4  missing required 'carry' |
| PASS | Panel opens without stealing focus | 2 windows open; the cursor stayed in the code window |
| PASS | Panel toggles closed | :CompanionPanel a second time closes it |
| PASS | Real Neovim :write → watch → evidence | Both breaking callers and a failed pytest result appear |
| PASS | Lua save reaches engine | Not relying solely on filesystem watcher |
| PASS | Editor return files | findings.jsonl and engine.json are written by the engine; outbox.jsonl waits for the engine to have an LSP question to ask |
| PASS | Save clears the unsaved overlay | after :write the same content is attributed to the file, not the buffer (dirty_buffers=[]) |
| PASS | Saved tests are labelled as saved-revision evidence | saved files only |
| PASS | Test findings declare their revision limit | failed: 1 failed in 0.01s |
| PASS | Editor departure drops its overlays | an editor that quits stops being credited with unsaved content |

## What the new rows establish

- **Canonical text agrees across Lua, Python and disk** — every case in
  `tests/fixtures/text-canon.json` is loaded into a real buffer, hashed by the adapter's own
  function, written with `:write`, and compared against the engine's hash and the bytes on
  disk. This check found and killed a wrong special case for the empty buffer.
- **Unsaved ingestion** (was GAP CONFIRMED) — a signature change typed into a buffer produces
  caller findings while the file on disk still holds the original.
- **Adapter and engine agree on the buffer hash** — the adapter's `text_sha`, the engine's
  recorded `content_sha` and the sha a finding depends on are one value. Without this,
  staleness is decoration.
- **Protocol v2 fields survive intake** — `dirty`, `session`, `doc_version`, `language`,
  `source` and the resolved origin all reach the engine's own log; the buffer text does not,
  because it belongs in the snapshot store.
- **Editor return files** (was GAP CONFIRMED) — `findings.jsonl` and `engine.json` are
  written. `outbox.jsonl` is still absent, correctly: the engine has no LSP question to ask yet.
- **Panel rows** — the pane is opened by command over files the engine wrote, draws the
  header fields and the caller findings, hands the cursor straight back, and toggles closed.
- **Saved-test rows** — pytest evidence is labelled as saved-revision-only, and the published
  finding carries `saved_revision_only` so the editor cannot present it as speaking for a buffer.
- **Editor departure drops its overlays** — quitting Neovim without saving stops the engine
  crediting it with unsaved content.
- **Buffers open before `:CompanionStart` are announced** — a buffer that was already open, and
  already modified, reaches the engine at once instead of waiting for the next keystroke.
  Buffers outside the workspace are skipped.

Board snapshots, panel dumps and command logs are alongside the report in the artifacts
directory. Replay state is under `replayed/`. Canonical-text comparisons are in
`canon-comparison.json`.
