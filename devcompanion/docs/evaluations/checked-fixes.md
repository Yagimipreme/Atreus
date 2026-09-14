# Checked fixes on local and subscription models — 2026-09-14

**Can a model propose fixes for type-checker problems that a deterministic checker then vouches
for — and how often is a vouched-for fix still not the one the code meant?**

| Model | ✓ shown | ✓ but not intended | Intended, without the checker | Model time p50 / p90 | Output tokens p50 | API-equivalent cost, 51 calls |
|---|---:|---:|---:|---:|---:|---:|
| `qwen2.5-coder:3b` (local) | 40/51 | 3 | 38/51 | 0.19 s / 0.31 s | 23 | — |
| `qwen3:4b` (local), 2,048 tokens | 0/51 | 0 | 0/51 | 13.6 s / 17.1 s | 1,635 | — |
| `qwen3-coder:30b` (local) | 46/51 | 1 | 48/51 | 3.34 s / 4.96 s | 59 | — |
| Claude Sonnet 5, low effort | 50/51 | 0 | 51/51 | 2.14 s / 2.42 s | 60 | $0.18 |
| Claude Opus 5, medium effort | 49/51 | 0 | 50/51 | 2.94 s / 3.31 s | 58 | $0.53 |
| Codex, `gpt-5.6-luna` medium | 51/51 | 0 | 51/51 | 5.35 s / 8.41 s | 70 | not reported |

**The gate in force notes a new warning instead of refusing** (decided 2026-09-14, implemented in
`fix/check.py`, stored replies rejudged). The table above is under the stricter gate, as first
measured. Under the rule in force:

| Model | ✓ shown | ✓ not intended |
|---|---:|---:|
| 3B | 41/51 | 4 |
| 30B | 48/51 | 1 |
| Sonnet | 51/51 | 0 |
| Opus | 50/51 | 0 |
| Codex | 51/51 | 0 |

[checked-fixes-table.md](checked-fixes-table.md) and the JSON file carry the rule in force.

The checker took 0.44–0.48 s p50 per proposal. Raw prompts, replies, verdicts and timings:
[checked-fixes.json](checked-fixes.json); per-case matrix: [checked-fixes-table.md](checked-fixes-table.md);
escalation chains and the warnings rule: [routing-policies-table.md](routing-policies-table.md).
The subscription calls ran on the user's Claude Max and ChatGPT plans; the cost column is what
Claude Code reports the same calls would cost through the API.

## How it was measured

- **Corpus** — [tests/fixtures/fix-corpus.txt](../../tests/fixtures/fix-corpus.txt): 51 cases over
  15 kinds (argument type 9, missing argument 5, too many arguments 1, unknown keyword 4, optional
  member access 3, optional operand 2, undefined name 5, attribute 5, missing `await` 1, property
  called 1, return type 5, operator 2, assignment 2, possibly unbound 2, syntax 4). Each is a
  working module of a few functions, a mutation that breaks it, and a behaviour check. A case
  counts only if the working code has no errors, the mutation adds a diagnostic, the working code
  passes its check and the broken code fails it (`--check-corpus`: 51/51).
- **Prompt** — [fix/prompt.py](../../src/devcompanion/fix/prompt.py): the problem as the panel
  says it (the sentence and facts from `problems.py`), the checker's messages, and the file. The
  system prompt asks for SEARCH/REPLACE blocks and forbids silencing the checker. ~250 input tokens
  locally; ~800 through Claude Code; ~12,700 through Codex, whose own agent prompt comes with it.
- **Gate** — [fix/check.py](../../src/devcompanion/fix/check.py): the proposal must apply, parse,
  not silence the checker, remove the diagnostics the mutation introduced (matched by rule), and
  add no error (matched by rule and message). Measured first with warnings refused too; the rule in
  force carries a new warning beside the ✓. basedpyright 1.38.0 on a materialised copy.
- **Intent** — the patched code passes the case's behaviour check. One check per case, not human
  judgement; `human_ok` is empty in the raw file for labelling.
- **Local** — Ollama 0.33.3, temperature 0, one sample per case, `num_ctx` 4096, 300 output tokens
  (2,048 for `qwen3:4b`), each model loaded before timing; Ryzen 7 5800X3D, RTX 2080 SUPER 8 GB.
- **Subscription** — [llm/providers.py](../../src/devcompanion/llm/providers.py): `claude -p` with
  no tools, no MCP servers, no settings files and a replaced system prompt; `codex exec` in its
  read-only sandbox. Both in an empty scratch directory, three cases at a time. Both passed the
  tripwire check ([scripts/check-provider-tripwire.py](../../scripts/check-provider-tripwire.py))
  before this run: files unchanged, while the same agents given write access did change them.
  Wall time includes starting the CLI (~1 s for Claude, more for Codex).

Run: `.venv/bin/python scripts/evaluate-fixes.py --model qwen2.5-coder:3b --model qwen3:4b@2048
--model qwen3-coder:30b --output docs/evaluations/checked-fixes.json`, then `--append --jobs 3
--model claude:sonnet/low --model claude:opus/medium --model codex:`.

## What it shows

**The corpus is easy for subscription models.** 50, 49 and 51 of 51 checked, none unintended. It
separates local from subscription models; it cannot separate the subscription models from each
other. Harder, multi-file cases would be needed for that.

**Subscription models are faster than the local 30B for this job.** Sonnet at 2.1 s p50 and Opus at
2.9 s, CLI start included, against 3.3 s for the 30B — which answers with rewritten definitions,
while all three subscription models used the requested blocks. Only the 3B is faster (0.19 s).

**The checker earns its place on both usable local models.** Shown unfiltered, 13 of the 3B's 51
replies would have been wrong or unusable; with the gate, 37 of the 40 it shows are the intended fix
(92.5%, against 74.5% unfiltered). The 30B goes from 48/51 (94.1%) to 45/46 (97.8%).

**Every wrong ✓ was type-correct and unintended.** This is the class the gate cannot see:

| Model | Case | Intended | Proposed |
|---|---|---|---|
| 3B | optional-greeting | `"Hello, " + (name or "world")` | `"Hello, " + (name or "")` |
| 3B | import-field | `items: list[str] = field(default_factory=list)` | `items: list[str] = list()` — one list shared by every instance |
| 3B | returns-set | `return sorted(set(names))` | `return list(names)` |
| 30B | price-times | `len(items) * float(price)` | parameter retyped to `price: float` — the error moves to every caller |

Only a behaviour test catches these. The mark must read "checked", never "correct"; a stronger
mark (`✓ checked · 3 related tests`) needs tests that reach the changed code.

**Escalation recovers refusals, never wrong ✓.** A chain moves to the next model only when the gate
refuses, and a type-correct but unintended fix is accepted. So `3B → Sonnet` shows 50/51 at 0.66 s
p50 with 22% of cases reaching the subscription — but keeps the 3B's 3 wrong ✓. `30B → Sonnet` keeps
1. Starting cheap buys latency and privacy at the price of the first model's false ✓ rate.

| Chain (strict gate) | ✓ shown | wrong ✓ | seconds p50 / p90 | cases reaching a subscription |
|---|---:|---:|---:|---:|
| 3B | 40/51 | 3 | 0.63 / 0.75 | 0% |
| 3B → 30B | 47/51 | 3 | 0.66 / 5.07 | 0% |
| 30B | 46/51 | 1 | 3.79 / 5.40 | 0% |
| 3B → Sonnet | 50/51 | 3 | 0.66 / 3.28 | 22% |
| 30B → Sonnet | 50/51 | 1 | 3.81 / 6.45 | 10% |
| 3B → 30B → Sonnet | 50/51 | 3 | 0.66 / 6.33 | 8% |
| Sonnet | 50/51 | 0 | 2.63 / 2.90 | 100% |

Seconds include the ~0.45 s check per attempt and assume both local models resident.

**The warnings rule, measured.** Refusing a fix for a new *warning* (strict) against only noting it
(qualify):

| Model | strict: ✓ / wrong | qualify: ✓ / wrong | what qualify adds |
|---|---:|---:|---|
| 3B | 40 / 3 | 41 / 4 | 1 fix, unintended |
| 30B | 46 / 1 | 48 / 1 | 2 fixes, both intended |
| Sonnet | 50 / 0 | 51 / 0 | 1, intended |
| Opus | 49 / 0 | 50 / 0 | 1, intended |
| Codex | 51 / 0 | 51 / 0 | — |

Four of the five models tripped over the same case, `unbound-after-except`: the intended fix returns
a value basedpyright calls partially unknown, and the broken code, whose variable might be unbound,
did not get that warning. Checking against the broken code penalises warnings that come with the
correct fix. Qualify recovered 4 intended fixes and added 1 wrong one, from the 3B.

**Intended fixes the gate refused**, beyond the warnings: `xml-find` for both local models — returns
`title.text` after checking only `title`, right at runtime, still `str | None` against `str`. A fair
refusal. Opus sent no code once (`returns-set`).

**`qwen3:4b` as installed is unusable here.** It keeps reasoning in its visible reply despite
`think: false`. At 300 tokens (a first run, stopped) every reply was cut off mid-reasoning at
~2.5 s. At 2,048 tokens, 19/51 still used the whole budget; 32 reached `</think>`, and the answers
after it wrote `SEARCH` / `REPLACE` without the block markers.

**All three local models failed `method-on-class`** (`Parser.parse(text)` for `Parser().parse(text)`);
every subscription model fixed it.

## What models actually send

The harness was revised four times after reading local replies. Each revision is a general rule
with a unit test in [test_fix_patch.py](../../tests/test_fix_patch.py), each would be needed by the
product too, and every local number above comes from re-judging the **same stored replies**
(`--rejudge`). The subscription runs came after the revisions.

| Revision | Why |
|---|---|
| Blocks copied without indentation are shifted into place (marked `loose`) | 30 of the 3B's 46 block patches matched only when indentation was ignored; applied literally, a correct fix moved a `return` out of its function |
| A fenced rewrite is accepted when there are no blocks | the 30B answered 42 of 51 with rewritten definitions, 8 with blocks — and its rewrites were the cheaper form (median 54 tokens, 3.1 s, against 99 tokens, 4.7 s) |
| A rewrite with every unit of the file replaces the file; `from` imports merge | the correct whole-module answer to `from math hypot` kept the broken line; an added name produced a duplicate import |
| Only text after `</think>` is the answer; "still present" is matched by rule | code drafted while reasoning was being applied; `split(4)` for `split(3)` read as resolved plus new |

Before the last two revisions the same local replies scored 39/51 (3B) and 45/51 (30B) checked.

## What it does not establish

- **Real problems.** The cases are hand-written, single-file, a few functions long, one mistake
  each, with intent stated in docstrings — all of which flatter every model. The corpus and the
  harness were written in the same session, by the same author. Subscription models score at the
  ceiling, so the corpus says nothing about differences among them.
- **Project context.** The gate checks a lone file; imports across a project, and so the
  materialised-runner question from the handoff, are untouched.
- **Variance.** One sample per case; the local runs at temperature 0, the subscription CLIs at
  their defaults.
- **Tests as a tier.** The behaviour check stands in for "related tests"; no project test
  selection was exercised.

The measurement that would settle the lane for this project is the same harness over problems
collected from real sessions (`.companion/view.json`), with `human_ok` labelled.
