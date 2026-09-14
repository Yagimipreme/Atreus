# Passive development companion — design notes (2026-09-09)

## Core purpose (fixed)
The developer keeps developing and thinking; the companion prepares evidence, tests and
investigations quietly. No idea→approve→idea loop. Results are pulled, never pushed.

## Established requirements (from the brief)
- Engine is editor-independent; Neovim is the first editor.
- Useful on CPU only (10th-gen i7 laptop). Desktop (Ryzen 7 / RTX 2080 Super / 48 GB) for comparison.
- Observation, scheduling, snapshots, evidence, presentation are distinct and inspectable.
- A replayable input exists before any model is judged.
- Unknown intent, no useful action, stale results and model unavailability are ordinary cases.
- Test generation and Follow/Freeze/Compare stay in the architecture; Phase 1 ships first.

## Proposed defaults (implemented, changeable)
- Event = "path changed at sha"; content lives in the snapshot store. Recording = `events.jsonl` + `snapshots/`.
- Producers: inotify (watchdog) for any editor; a 40-line Neovim plugin for save + cursor events.
- Baseline for Follow mode is `git show HEAD:<path>`, fetched lazily on first sight, recorded as a `baseline` event.
  Freeze = the same call against a chosen ref; Compare = evidence keyed by two snapshot sets. Not built yet.
- Detection with tree-sitter only; a file with parse errors yields `unknown_intent`, never a claim.
- Debounce 0.4 s, one pending bundle per path, newer save cancels older, investigations abandon when input goes stale.
- Evidence records carry `based_on: {path: sha}`; a change to any dependency marks them stale and re-schedules the defining file.
- Identical fingerprints are not re-emitted (the awatch delta idea).
- Tests: pytest `-x` on files mentioning the changed names; one `test_run` record per save. Never executed in replay.
- LLM tier: one sentence per breaking record; Ollama native API or any OpenAI-compatible server; `--cpu-only` maps to `num_gpu=0`.

## Unresolved decisions
- Which model, if any, earns its place. See measurements. The deterministic slice already answers Phase 1 without one.
- Update interval for continuous (unsaved) buffer observation; currently save-driven only.
- Snapshot growth on large repos (pyERP-scale): one object per distinct file state; no GC yet.
- Cross-language: detection and judgement are Python-only. tree-sitter grammars make TS/Rust additive.
- Presentation beyond a markdown split: hover/virtual text, a tool row, chat. Board + quickfix is the minimum.
- Sandboxing investigations (agentos executor) before running tests in untrusted checkouts.
- Pre-building/running the app "DLSS-style" and the on-hover roadmap: architecture leaves room (Freeze + Compare +
  a runner stage), nothing designed yet.

## What works (demonstrated, reproducible)
- `scripts/demo-phase1.sh`: baseline → signature change (`add(a,b)->add(a,b,carry)`, `memo->note`) → mid-edit
  unparsable save → caller fix. Board shows breaking sites with file:line, test failure, unknown-intent record,
  stale-then-rejudged claims. 0.8 s wall for the whole script.
- `companion replay` of the recording into a fresh state dir with the source root absent reproduces the same
  evidence keys and fingerprints (checked).
- `scripts/demo-live-nvim.sh`: `companion watch` + headless Neovim; git baseline, three duplicate producer events
  collapse to one investigation, board updated ~1 s after save.
- Unit tests: signature kinds, method self-binding, mid-edit, removal, call judgement (5 tests).

## Measured (desktop, Ryzen 7 5800X3D, `ollama ps` confirmed 100% CPU; the i7 laptop will be slower)
Per suggestion call on the Phase 1 recording, ~175 prompt tokens, first call includes model load:

| model | CPU-only wall s (4 calls) | output |
|---|---|---|
| qwen3:0.6b | 2.9, 0.6, 0.5, 0.5 | vague ("check the memo keyword…"), not actionable |
| qwen2.5-coder:3b | 4.6, 2.2, 1.7, 1.2 | correct and actionable ("use 'note' instead of 'memo'") |
| qwen3:4b | 9.5, 6.5, 6.2, 5.5 | reasons in the answer despite think=false, hits 60-token cap, unusable as prompted |
| qwen2.5:7b | 9.7, 4.8, 4.0, 2.3 | correct, no better than 3b |
| (any, not pulled) | 0.01 | `unavailable`; board shows deterministic evidence only |

GPU runs of the same models on the RTX 2080 Super changed wall time by <1 s here; not investigated further.

## Remains a proposal
Freeze/Compare, test generation on `new_function`, continuous buffer observation, non-Python grammars, the
tool row / hover UI, sandboxed runners, model selection under a break-even rule (agentbench `breakeven.py`).
