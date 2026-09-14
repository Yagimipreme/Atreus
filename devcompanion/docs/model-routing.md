# Model routing

Status: agreed in conversation, 2026-09-14. Providers unbuilt; the tiering is a decision.

Which work a model does, which model does it, and why. The companion is deterministic first —
this document is only about the part that is not.

## The rule

Routing is not decided by model size. It is decided by **who asked, and what a wrong answer
costs**.

| | Passive | Pulled |
|---|---|---|
| Who initiated | the engine, because code changed | the developer, just now |
| Latency budget | background; may be dropped entirely | seconds are fine |
| Cost of being wrong | one ignored line in a pane | an hour of misdirected work |
| May content leave the machine | **no** | only if the project permits it |
| Model | local | local or subscription |

The same rule is the content-sharing policy, which is why it is the right one rather than
merely a tidy one: nothing leaves the machine unless the developer asked for it *in that
moment*. S7 is satisfied without a second mechanism.

## The constraint that shapes everything

S10: *models allocate attention and summarize; they never become the source of a fact, an
edit, or an "actual result".*

So every model function is one of **phrase**, **rank**, **summarize**, or **propose**. Never
*determine*. Anything that determines something is a tool call, or it does not happen. This
cuts the catalogue more than any latency budget does.

Edits do not contradict this; see [edit-actions.md](edit-actions.md) for the reconciliation.

## Catalogue

| Function | Tier | Why there |
|---|---|---|
| Signature diff, caller arity judgement, staleness, test selection and execution, diagnostics | **no model** | Already exact. A model can only subtract. |
| Import-graph blast radius; which tests cover a symbol; recency of the developer's own edits | **no model**, unbuilt | Still deterministic, and the cheapest unbuilt value in the project |
| Rank many findings down to the few that matter now | passive local | Real judgement; a wrong answer is invisible |
| Label edit intent (refactor / bugfix / experiment) | passive local | S4 — secondary, always labelled inference |
| QMD query expansion | passive local | Cheap, and retrieval tolerates noise |
| Explain a diagnostic in terms of this codebase | pulled local | Needs code understanding; developer waiting, not blocked |
| "What did I just break?" across a bundle | pulled local | Summarisation over evidence that already exists |
| Resolve an `unsure` verdict (splat unpacking) | pulled local | The one place a model can improve a deterministic verdict |
| Propose the edit at a breaking call site | pulled local | *Propose.* See [edit-actions.md](edit-actions.md) |
| Multi-file refactor plan | pulled subscription | Quality dominates; explicit act |
| Root-cause a failing test across files | pulled subscription | Same |
| Draft tests for a new function | pulled subscription | Test policy is `draft` by default |
| Architecture discussion over retrieved passages | pulled subscription | The Chat surface |
| Surface documentation for the code in view | **no model**, pulled | Retrieval with a source, not judgement ([code-documentation.md](code-documentation.md)) |
| Write documentation for a selection | pulled subscription | It is explaining code, which the local model does unreliably |
| Roadmap forks | pulled subscription | S5 — the only divergent surface |
| Runtime Compare, scenario probes | **no model** (Tier C) | No model makes this cheap |

## Trust levels

Agreed 2026-09-14. Everything the companion shows carries one of three levels, and the mark is
what makes the routing legible to the developer:

| Level | Mark | Established by | Examples |
|---|---|---|---|
| Fact | ✓ | a tool; no model involved | `renaming sep · 2 callers remain`, `✓ 71 tests` |
| Checked | ✓ | a model proposed it, deterministic tools verified it | `✓ fix checked` ([fix/check.py](../src/devcompanion/fix/check.py)) |
| Advice | ◇ | model reasoning that nothing verified | explanations, change summaries, plans, review |

**◇ never appears unasked.** The passive tier may show only ✓: facts, or model output that passed
a checker. Model output with no verifier is pulled only. This is the passive/pulled rule above
with verifiability added, and it is what keeps the passive tier from becoming unsolicited
opinion.

A checked fix means the code is consistent, not that it is what the developer meant:
`split(3)` → `split("3")` passes the checker. The UI must never word ✓ as "correct";
[evaluations/checked-fixes.md](evaluations/checked-fixes.md) measures how often the two differ.

## The resident specialist and the flagship

Decided 2026-09-14, from [evaluations/chatty-functions.md](evaluations/chatty-functions.md).

The local model is **the fast resident specialist** for a small set of jobs:

- observe
- compress
- summarise diffs
- challenge a selection (three questions; picking the single strongest is the flagship's job)
- generate candidate fixes

The flagship handles the jobs whose answer is a semantic judgement nothing checks:

- understand and explain
- plan
- design, discuss and reconsider

`flagship` is a role in configuration, bound to Claude Code or Codex per machine, never a
provider named in code ([configuration.md](configuration.md)).

The split follows what failed. The 30B's explanations and plans were wrong on substance:
- a crashing function explained as working
- a retry plan that repeats POSTs

A shorter reply would not have saved them. Its strongest prose job was reading a diff. And a wrong
fix can be rejected by the gate, where a wrong explanation is just wrong. That is why **checked
fixes are the local model's most valuable job**: proposal generation by a borderline-reliable model
plus deterministic acceptance.

**The design rule for local prompts: never ask the model to fill a format; ask it to stop when it
has nothing useful left to say.** Every "at most N" in the measured prompts came back as exactly N.
The filler is where invented concerns and self-contradictions lived. So:

- **One thing and a stop, not a count.** "Identify the single most important concern. If there is
  none, say NO CONCERN. Do not add secondary concerns to fill space." Measured the same night, the
  rule fixed format but not selection. The commit schema held: every subject within the limit, no
  invented motive. But asked for the single strongest grill question, the 30B never used the stop
  word and mostly picked the wrong question (4 of 6 unusable, against 1 of 6 for three ranked
  questions). So the local grill keeps three questions, and the one-question conversation goes to
  the flagship.
- **Facts first, then one sentence.** The engine establishes the facts: changed files, symbols,
  call sites, diagnostic changes, diff statistics. The model expresses the most important one and
  introduces nothing not in the packet.
- **Code enforces what code can.** A commit reply is `subject:` / `body:`; code strips the trailing
  period and checks the length, rather than a second model call. The prompt describes observable
  changes only and forbids motive.

## Local and flagship, job by job

| | `qwen3-coder:30b` (local) | Flagship (Claude Code / Codex CLI) |
|---|---|---|
| Latency | 0.87 s warm, 25.4 s cold (~170-token prompt) | unmeasured |
| Context | 4K configured, 262K native — kept small on purpose: it forces selection | large |
| Content leaves the machine | never | only when asked, and only if the project permits |
| May run unasked | yes | no |
| Invocation | HTTP, built | CLI subprocess, unbuilt, gated on the tripwire test ([providers.md](providers.md)) |

| Job | Deterministic part | Local | Flagship | Mark |
|---|---|---|---|---|
| `renaming sep · 2 callers remain` | all of it, already computed | — | — | ✓ |
| Fix for one problem | applies, parses, not suppressed, target gone, nothing new | proposes the patch | only when asked | ✓ checked |
| Fixes at call sites after a signature change | the list of callers | one patch per site | — | ✓ checked |
| `defined in` / import for an undefined name | a symbol index resolves it | ranks candidates | — | ✓ |
| Sentence where the rules run out | grouping and facts | rewrites the sentence | — | ◇ |
| Docstring drift after a return-type change | annotation against docstring type | phrases prose drift | — | ✓ / ◇ |
| Grill this selection | — | three questions, in `local-only` | one richer question per turn | ◇ |
| "What is suspicious here" | — | yes; the developer chose the scope | when asked for a better answer | ◇ |
| Explain a selection | symbols, references, types, diagnostics — all `local-only` offers | no: measured unusable | yes | ◇ |
| Change summary, commit message | diff statistics; changed symbols and callers; subject period and length | one sentence / `subject:` `body:` | — | ◇, pulled |
| Failing test → likely cause | the changed symbols the test reaches | phrases it | when the cause spans files | ✓ / ◇ |
| Refactor plan, architecture, drafting tests, roadmap, plan/grill | — | — | yes | ◇ |
| Inline completion | — | — | — | outside the companion |

**Completion stays outside the companion.** Qwen documents fill-in-the-middle for every
Qwen3-Coder version, so the model could do it, but the Ollama `qwen3-coder:30b` tag advertises no
`insert` capability and its template has no suffix slot, so it would need raw prompts. The real
reason is the budget: completion wants 100–300 ms per keystroke, with cancellation, on the same
8 GB card that serves the companion's ~1 s requests. That is an inference scheduler, not a
feature. An external completion plugin owns it; reconsider only if a scheduler exists.

## Deliberately not built

**Model-phrased findings.** A template already produces *"`add()` now requires `carry`; this
call passes 2 of 3"* at zero latency with no way to lie. A model there adds a failure mode and
nothing else. Use a model where the answer is not already known, not to reword one that is.

**A small-model tier as a product concept.** Either a task needs a model or it does not; a
worse model doing the same job is a quality floor, not a tier. A small model is only ever the
*degradation* of a task under hardware pressure, and the pane names which one ran.

**Anything inline.** The vision is explicit: feels like a well-configured LSP, not a chat
window; the editor never waits on inference; inline completion is a non-goal.

## Hardware

S8 (useful CPU-only on a 10th-gen i7 laptop) is **backlogged, not retired**. The target is the
current host: Ryzen 7 5800X3D, 46 GiB RAM, RTX 2080 SUPER 8 GiB.

That admits `qwen3-coder:30b` to the passive tier, which the laptop constraint would not have.
It is still gated, for reasons that have nothing to do with the laptop:

- **Per-save, not per keystroke pause**, and only when breaking sites exist.
- **`keep_alive` tuned.** Ollama's default five-minute eviction means every save after a pause
  would otherwise pay the cold load. Measured on this host through the engine's own request,
  2026-09-14:

  | | measured |
  |---|---|
  | cold load | 25.4 s |
  | warm | 0.87 s (three consecutive, 0.87 / 0.88 / 0.89) |
  | resident | 5.5 GB in VRAM of 19.2 GB — partial offload on the 8 GB card |

  This supersedes the earlier 15.437 s / 1.66 s figures, which came from a different harness
  and a larger prompt. Warm is comfortably inside a per-save budget. Cold is worse than
  previously recorded and close enough to the 30 s request timeout that the first suggestion
  after an eviction can be lost — which is why a claim derived while the model was unavailable
  must still be able to acquire a sentence later.
- **Visible degradation.** `model.status` already carries `loading` / `unavailable`; the pane
  must show it rather than appear to be thinking.

## Measured: checked fixes on three local models

2026-09-14, [evaluations/checked-fixes.md](evaluations/checked-fixes.md). 51 hand-written
single-mistake cases, each with a behaviour check that separates the intended fix from one that
merely satisfies the type checker; temperature 0, one sample per case, 4K context.

| | ✓ shown | ✓ but not intended | intended, without the checker | model time p50 |
|---|---:|---:|---:|---:|
| `qwen2.5-coder:3b` | 40/51 | 3 | 38/51 | 0.19 s |
| `qwen3:4b` (300 or 2,048 output tokens) | 0/51 | 0 | 0/51 | 2.5 s / 13.6 s |
| `qwen3-coder:30b` | 46/51 | 1 | 48/51 | 3.3 s |

What it settles, for now:

- **The checker earns its place on both usable models.** Shown unfiltered, 13 of the 3B's 51
  replies would have been wrong or unusable; with the checker, 3 of the 40 it shows are wrong
  (37/40 intended). For the 30B, 3 of 51 becomes 1 of 46 (45/46).
- **Every wrong ✓ was type-correct and unintended**: `name or ""` for `name or "world"`, a
  shared `list()` default for `field(default_factory=list)`, `list(names)` for
  `sorted(set(names))`, a parameter retyped so the error moves to the callers. Only a behaviour
  test catches that class. ✓ must never be worded as "correct".
- **The 30B's quality costs latency.** It answers fixes with rewritten definitions, not the
  requested blocks: ~60 output tokens and 3.3 s p50 before a ~0.45 s check — far outside the
  ~1 s budget that the 0.87 s one-sentence figure suggested. The 3B, with ~23 tokens, is ~0.65 s
  including the check.
- **`qwen3:4b` as installed is unusable for this:** it reasons in its visible reply despite
  `think: false` and never produced an applicable patch, at 300 or at 2,048 tokens.

## The measurement still not taken

The numbers above come from hand-written cases, with the intent stated in docstrings. The number
that would settle 3B-versus-30B on real work — this developer's own recorded sessions —
**does not exist** yet.

Replay is now verified deterministic, which is exactly the "validated on replayed recordings
before any live use" the vision asked for. The machinery exists and has never been pointed at
this question:

1. Record one real session (`companion watch` leaves the recording).
2. Replay it against each candidate profile.
3. Score the outputs on the tasks in the catalogue, not on phrasing.

Because routing lives in configuration rather than in code
([configuration.md](configuration.md)), two profiles can serve the same function on the same
recording and be compared directly.

## Sources

Vision S4, S5, S7, S8, S10; [handoff](handoff.md) model measurements;
[local model and context design](local-model-and-context.md).
