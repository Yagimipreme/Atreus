# Function routing — which model does which job — 2026-09-14

Status: measured hit rates and the routing in force. The user decided the warnings rule and the lane
for checked fixes, closed latency measurement, excluded Codex from further testing, and set the
method for the chatty functions: measure `qwen3-coder:30b`, plug in the flagship only where it is
unusable. Measured since: explain and plan fall below the bar and go to the flagship; grill, change
summary and commit message stay on the 30B ([chatty-functions.md](chatty-functions.md)). Timings below are context only: the local function timings were taken while a game used
the CPU. The mechanism — per-function chains, gates, a `local-only` mode — is in
[configuration.md](../configuration.md).

## Routing

| Function | Mark | `local-only` | `hybrid` | Status · hit rate |
|---|---|---|---|---|
| Checked fix, unasked | ✓ checked (· N new warnings) | 30B | 30B (passive never leaves the machine) | **decided** · 48/51 shown, 1 wrong |
| Checked fix, on `f` | ✓ checked (· N new warnings) | 30B | 30B → flagship when the gate refuses | **decided** · 50/51 shown with Sonnet as the flagship, 1 wrong |
| Diagnostic sentence where the rules run out | ✓ sentence check | 3B on the CPU | same | **decided** · 18/30 pass the check |
| Change-awareness sentence | ✓ nothing beyond the engine's facts | 30B | 30B | **decided design** · unbuilt; to measure |
| Change summary | ◇ | 30B | 30B | **decided** · 0 of 6 unusable |
| Commit message | ◇ | 30B; `subject:` / `body:`, period and length handled by code | 30B | **decided** · constrained prompt: 4 good, 1 fixable, 1 unusable |
| Grill | ◇ | 30B, three questions | flagship, one richer question per turn (one-shot until Chat) | **decided** · 30B: 1 of 6 unusable as three questions, 4 of 6 as one |
| Surface documentation for the code in view | ✓ fact, cited | deterministic and QMD | adds remote doc search, on request | **decided scope** · unbuilt ([code-documentation.md](../code-documentation.md)) |
| Most suspicious line | ◇ | 30B | flagship | proposed · 16/30 exact (20 within a line) against 29/30 for Opus |
| Failing test → culprit function | ◇ | 30B | flagship | proposed · 21/30 against 28/30 for Sonnet and Opus |
| Explain a selection, plan a change | ◇ | unavailable; names what is local | flagship | **decided** · the 30B unusable on 3 and 2 of 6 |
| Write documentation; architecture and roadmap discussion | ◇ | unavailable | flagship | **decided** · not measured; unbuilt |
| Completion | — | outside the companion | outside | decided |

`flagship` is a configuration role that machine config binds to Claude Code or Codex
([configuration.md](../configuration.md)); Sonnet and Opus name what filled it when it was measured.

The principles behind it, each backed below: **put the most precise model first wherever a ✓ is
shown**, because escalation never recovers a wrong ✓; **keep the flagship off jobs a local model
already does**; and **on this 8 GB card, one GPU model at a time** — the small model runs on the CPU.

## What was measured

Local models: `qwen2.5-coder:3b` and `qwen3-coder:30b` through Ollama, temperature 0. Subscription:
Claude Sonnet 5 (low effort), Claude Opus 5 (medium) and Codex `gpt-5.6-luna`, through
[llm/providers.py](../../src/devcompanion/llm/providers.py), tool-less, after the tripwire check
passed. One sample per case. Codex is recorded here and not tested further.

| Job | Cases | 3B | 30B | Sonnet | Opus | Codex |
|---|---|---:|---:|---:|---:|---:|
| **Checked fix** — ✓ shown / of them wrong | 51 hand-written | 40 / 3 | 46 / 1 | 50 / 0 | 49 / 0 | 51 / 0 |
| — warnings noted instead of refused | | 41 / 4 | 48 / 1 | 51 / 0 | 50 / 0 | 51 / 0 |
| **Sentence** — passes the check | 30 real messages | 18 | 13 | 13 | 22 | 19 |
| **Suspicious line** — bug at the exact line | 30 planted bugs | 4 | 16 | 24 | 29 | 22 |
| — within one line | | 10 | 20 | 25 | 29 | 23 |
| — untouched functions flagged | 10 | 4 | 9 | 5 | 3 | 7 |
| **Culprit** — function named | 30 | 9 | 21 | 28 | 28 | 10 of 10 run |

- **Fixes**: [checked-fixes.md](checked-fixes.md) — hand-written single-file cases with behaviour
  checks for intent.
- **The other three** come from this project's own committed code
  ([function-corpus.json](../../tests/fixtures/function-corpus.json), built by
  [build-function-corpus.py](../../scripts/build-function-corpus.py)): 30 basedpyright messages no
  normalisation rule covers; 30 bugs planted by mutation that the unit suite catches and the type
  checker cannot see, plus 10 untouched functions; for culprit, the failing test's output, the
  functions its traceback passes through, and about five recently changed functions of which one is
  the culprit (chance ≈ 5/30). The sentence check: the names and types quoted in the message kept,
  at most 14 words, nothing put in backticks that is not in the message or code, and not an echo of
  the message.
- Raw rows: [functions.json](functions.json), [checked-fixes.json](checked-fixes.json); chains and
  pairs: [routing-policies-table.md](routing-policies-table.md), from
  [route-policies.py](../../scripts/route-policies.py), which replays stored replies without calling a model.

## Decisions taken

**1. A new warning is noted next to the ✓** (`✓ fix checked · 1 new warning`); a new error still
refuses.

| | refuse on a new warning: ✓ / wrong | note it: ✓ / wrong |
|---|---:|---:|
| 3B | 40 / 3 | 41 / 4 |
| 30B | 46 / 1 | 48 / 1 |
| Sonnet | 50 / 0 | 51 / 0 |
| Opus | 49 / 0 | 50 / 0 |

Noting recovered 4 intended fixes across the 30B and the subscription models. Four of five models
tripped over one case where the *correct* fix carries a warning the broken code did not have — the
gate compares against the broken code, so such warnings look new. The only fix noting added for the
3B was wrong, which is one reason the 3B does not propose fixes. Implemented in `fix/check.py`
(`Verdict.warnings`); rejudging the stored replies reproduces the right-hand column.

**2. `qwen3-coder:30b` proposes unasked fixes.**

| Option | For | Against |
|---|---|---|
| 3B proposes unasked | Fast; small | 3 wrong ✓ in 40 (7.5%) against 1 in 46 (2%); on the GPU it evicts the 30B the engine keeps loaded, and each switch back costs a reload |
| **30B proposes unasked** (chosen) | Most precise local model; already loaded for the engine; per-save background work is not waited on | Heavier on the CPU while the developer works |
| 3B → 30B chain | Covers the 3B's refusals | Keeps the 3B's wrong ✓ — escalation only recovers refusals — and swaps models on every escalation |
| On request only (`f`) | Nothing unasked | Loses the passive "I can fix 3 of these" that the user designed |

**3. Chatty functions: the 30B is measured, the flagship is the fallback.** For each of explain,
grill, change summary, commit message and plan: define a scorable proxy (or label a small set) and
the bar below which the function is unusable, measure `qwen3-coder:30b`, and route to the flagship
only where it falls below. The flagship is not benchmarked on them.

Result ([chatty-functions.md](chatty-functions.md)), six hand-judged cases per function, bar at most
one unusable: explain (3 unusable) and plan (2) go to the flagship; grill (1), change summary (0) and
commit message (1) stay on the 30B.

## What the chains taught

- **Escalation recovers refusals, never wrong answers that pass the gate.** `3B → Sonnet` shows
  50/51 fixes but keeps all 3 of the 3B's wrong ✓; `30B → Sonnet` keeps 1. The first model's
  false-✓ rate is the chain's.
- **A gate must be computable at run time.** Fixes have one (the checker), sentences have one (the
  check). Suspicious-line and culprit answers have none, so no chain can decide to escalate — those
  are single-model choices, or "ask a better model" as an explicit user action.
- **Context size never forced a handover**: every culprit packet (≈900–3,500 tokens) fit the local
  4K context.
- **Two models agreeing buys precision.** Flag a suspicious line only where the 30B and Sonnet name
  the same one: 15/30 found, 0 of 10 untouched functions flagged (the 30B alone flags 9 of 10).
- **On this card the 3B and 30B evict each other**; a CPU-only 3B stays loaded beside the 30B.
  Measured in the global KB, `hardware/rtx-2080-super-8gb`.
- **Sentences**: the 3B fails by echoing the message (7 of its 12 failures), the 30B by dropping
  names or adding facts not in the message (`dict[str, Any]` as an "expected" type it invented). The
  check is what keeps either from putting an invented fact in front of the developer unasked.

## Limits

- Fix cases are hand-written; the other corpora are one project's own public code, which the
  subscription models may have seen. One author wrote corpus and harness.
- The sentence check is also the score, so a passing sentence is fact-preserving and short — not
  proven good.
- Untouched "controls" can contain real issues; a flag there is not certainly false.
- Codex's culprit run stopped at 10 of 30 when the machine ran short of memory; Codex is not tested
  further.

## Hit rates still missing

Hit rates only — no timing, no Codex, no flagship runs on these:

1. **The change-awareness sentence**, once built, behind its check.
2. **The CPU-only 3B's sentence hit rate** — the same weights as the measured GPU run, so expected
   equal, but unconfirmed.

The fix hit rate is settled on the hand-written corpus; the user did not ask for real-problem labelling.
