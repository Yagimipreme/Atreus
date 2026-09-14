# devcompanion workflow check — 2026-09-14

**51 checks passed; 0 failed; 0 integration gaps reproduced.**

Rerun from the project root: `.venv/bin/python scripts/check-workflow.py`.
The harness creates fresh disposable Git projects and stops its watcher on exit.
No local or remote model was called.

Everything below goes through a real subprocess: `companion ingest`, `companion watch`,
`companion replay`, `pytest`, and `nvim --headless` running the actual plugin. Neovim runs
without swap or ShaDa persistence.

This run supersedes the earlier 2026-09-14 run that recorded 36 passes. The four panel rows of
that run (*Panel renders engine state*, *Panel shows the unsaved caller finding*, *Panel opens
without stealing focus*, *Panel toggles closed*) asserted the pane that the UI pass replaced;
the rows that replace them are named below. Pipes inside an observation are written `/` so the
table stays a table: `str / None` is `str | None`.

Artifacts: `/tmp/devcompanion-check-91ivji5q`

| Result | Scenario | Observation |
|---|---|---|
| PASS | Existing unit suite | 99 passed in 4.44s |
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
| PASS | Protocol v2 fields survive intake | dirty=True session=6aa7faad-b628f doc_version=5 language='python' origin=editor source=nvim; buffer text stays in the snapshot store, not the event log |
| PASS | Engine reports the unsaved buffer | {"state": "idle", "dirty_buffers": ["calc.py"], "findings": 2} |
| PASS | Findings published for the unsaved edit | 2 caller_affected finding(s), each marked as resting on buffer content |
| PASS | Panel leads with a count, not engine metadata | first line '2 problems'; engine fields drawn: 0 |
| PASS | Panel shows the unsaved caller finding | C client.py:4 unsaved |
| PASS | Inspecting opens one problem | ↵ grew the panel from 7 to 12 lines, showing the call site's code 'return add(1, 2)' |
| PASS | Provenance only on request | absent from the list and the inspected problem; d adds source, basis and buffer |
| PASS | Engine metadata lives in :CompanionInfo | fields drawn: buffer, context, engine, model, unsaved |
| PASS | Panel opens only when asked, as a focused float | no window appeared while findings arrived; :CompanionPanel opened a float and moved the cursor into it |
| PASS | Closing the panel gives the cursor back | q closed it and returned to the code window; :CompanionPanel twice toggles it |
| PASS | Before :CompanionStart the panel says it is not observing | not observing this workspace / :CompanionStart to begin |
| PASS | A sticky panel stays in view | :CompanionPanelStick opened it without taking the cursor; it survived leaving and a jump; unsticking closed it — {"survived_leaving": true, "survived_jump": true, "opened": true, "unstick_closed": true, "stayed_in_code": true, "entered": true, "no_pseudo_root": true} |
| PASS | Statusline carries the count | '◉ 2' |
| PASS | Panel survives a multi-line diagnostic | add() expects str / None, got int |
| PASS | One mistake reported twice is one problem | '3 problems · 2 diagnostics', and the row reads 'add() expects str / None, got int'; the language server's wording stays behind `d` |
| PASS | Real Neovim :write → watch → evidence | Both breaking callers and a failed pytest result appear |
| PASS | Lua save reaches engine | Not relying solely on filesystem watcher |
| PASS | Editor return files | findings.jsonl and engine.json are written by the engine; outbox.jsonl waits for the engine to have an LSP question to ask |
| PASS | Save clears the unsaved overlay | after :write the same content is attributed to the file, not the buffer (dirty_buffers=[]) |
| PASS | Saved tests are labelled as saved-revision evidence | saved files only |
| PASS | Test findings declare their revision limit | failed: 1 failed in 0.01s |
| PASS | Editor departure drops its overlays | an editor that quits stops being credited with unsaved content |
| PASS | A clean restart resumes at the offset: no reset, nothing re-read | {"malformed": 0, "offset": 4571, "resets": 0, "resumed_at": 4571, "skipped_known": 0} |
| PASS | A clean restart does not touch events.jsonl or state.json | 20 line(s) in events.jsonl before and after |
| PASS | The restarted engine's intake block updates without any new event | {"malformed": 0, "offset": 4571, "resets": 1, "resumed_at": 0, "skipped_known": 12} |
| PASS | Restart does not reprocess events.jsonl or state.json | 20 line(s) in events.jsonl before and after the restart, evidence unchanged |
| PASS | engine.json reports the intake block | {"malformed": 0, "offset": 4571, "resets": 1, "resumed_at": 0, "skipped_known": 12} |
| PASS | The restarted engine saw the rotated file's old events and declined them | skipped_known=12, resets=1 — re-read, not re-observed for the first time |
| PASS | A new edit after the restart is still picked up and produces a finding | 2 call site(s): 2 break, 0 unsure, 0 fit |

## What the panel rows establish

- **Panel leads with a count, not engine metadata** — the first line is a problem count; no
  pid, sequence number, model or retrieval field is drawn in the list.
- **Panel shows the unsaved caller finding** — one row per problem, marked `unsaved` when the
  claim rests on a buffer rather than a file.
- **Inspecting opens one problem** — `↵` expands the problem under the cursor with the line of
  code it points at, read from the live buffer.
- **Provenance only on request** — source, basis and buffer are absent from the list and from
  the inspected problem, and present after `d`.
- **Engine metadata lives in :CompanionInfo** — the fields the old header carried are drawn in
  the info view instead.
- **Panel opens only when asked, as a focused float** — no window appears while findings
  arrive; `:CompanionPanel` opens a float and moves the cursor into it, because its keys act
  there.
- **Closing the panel gives the cursor back** — `q` returns to the code window, and
  `:CompanionPanel` from inside the panel closes it.
- **Before :CompanionStart the panel says it is not observing** — no problem count and no
  engine notice over a store nothing has filled.
- **A sticky panel stays in view** — `:CompanionPanelStick` opens it without taking the cursor;
  `:CompanionStart` run from inside it observes the real workspace, not `companion:/`; it
  survives the cursor leaving and a jump; unsticking an unfocused panel closes it.
- **Statusline carries the count** — `statusline()` returns `◉ N` while an engine is answering.
- **One mistake reported twice is one problem** — two basedpyright messages about one call, one
  of them several lines long, draw as a single row reading `add() expects str | None, got int`,
  with the header saying how many diagnostics it stands for and neither raw message in the list.

## Rows carried over

The canonical-text, unsaved-ingestion, hash-agreement, protocol-v2, return-file, saved-test,
editor-departure, announce-on-start and restart rows are unchanged in meaning from the previous
run; see `docs/handoff.md` for what each established when it was added.

Board snapshots, panel dumps (`panel-compact.txt`, `panel-detail.txt`, `panel-raw.txt`,
`panel-info.txt`, `panel-multiline.txt`) and command logs are alongside the report in the
artifacts directory. Replay state is under `replayed/`.
