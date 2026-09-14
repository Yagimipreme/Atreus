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
| Roadmap forks | pulled subscription | S5 — the only divergent surface |
| Runtime Compare, scenario probes | **no model** (Tier C) | No model makes this cheap |

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
- **`keep_alive` tuned.** Cold load measured 15.437 s; warm requests ~1.66 s median. Ollama's
  default eviction means every save after a pause would otherwise pay the cold load.
- **Visible degradation.** `model.status` already carries `loading` / `unavailable`; the pane
  must show it rather than appear to be thinking.

## The measurement nobody has taken

The only local data point is `qwen2.5-coder:3b` being "weaker in mixed caller prompts" — and
that was on caller phrasing, which this document has just removed from the catalogue. So the
number that would settle 4B-versus-30B for the passive tier **does not exist**.

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
