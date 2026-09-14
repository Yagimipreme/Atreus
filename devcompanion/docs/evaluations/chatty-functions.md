# Chatty functions on `qwen3-coder:30b` — 2026-09-14

Status: measured and judged. The user set the method (measure the 30B only; plug in the flagship
where it is unusable), agreed the bar before the run, and confirmed the labels. The routing below
follows from them. The flagship was not run on these functions.

## Result

| Function | Good | Fixable | Unusable | Verdict | `local-only` | `hybrid` |
|---|---:|---:|---:|---|---|---|
| Explain the selection | 2 | 1 | 3 | below the bar | unavailable (open) | flagship |
| Grill the selection | 2 | 3 | 1 | usable, as three questions | 30B, three questions | flagship, one richer question per turn |
| Plan a change | 0 | 4 | 2 | below the bar | unavailable (open) | flagship |
| Change summary | 3 | 3 | 0 | usable | 30B | 30B |
| Commit message (constrained prompt) | 4 | 1 | 1 | usable | 30B | 30B |

**The bar:** a function with more than 1 unusable reply in its 6 cases is unusable on the 30B.

**Open:** a chain holding only the flagship is empty under `local-only`, so by the standing rule
([configuration.md](../configuration.md)) explain and plan say they are unavailable there. Keeping
the 30B instead, as a named degradation, is the alternative. The user has not decided.

## Method

- **Functions**: [pulled/chatty.py](../../src/devcompanion/pulled/chatty.py) — one system prompt,
  output budget and packet per function. The judged prompts, by `prompt_id`: explain `a2ac8e71`
  (300 tokens), grill `46db502e` (220), plan `fc9fb5c9` (450), summary `fe1c528a` (250), commit
  `0a339d02` (120). Summary and commit packets lead with deterministic diff statistics; plan
  packets carry the goal.
- **Cases**: [testing/chatty/](../../testing/chatty/), 6 per function, written for this run. Each case
  carries an `# expect:` line the judge checks against. It is never sent to the model.
  - **Explain:** code with one non-obvious point.
  - **Grill:** one planted weakness per case. `clamp` is a control with nothing planted.
  - **Plan:** a goal, including a retry trap. `cart-already-rejects` is a control whose goal is
    already met.
  - **Summary and commit:** six real `git diff`s shared by both functions. They include a default
    changed inside a refactor, a bug fix, two unrelated changes in one diff, a pure rename, a
    tests-only diff and a narrowed `except`.
- **Model**: `qwen3-coder:30b` through Ollama, 4K context, temperature 0, one sample per case. Every
  packet was about 150–390 tokens, far inside the context.
- **Labels**:
  - **good:** usable as it stands.
  - **fixable:** hits the expected point and states nothing false, but needs editing.
  - **unusable:** misses the point, states something false about the code, or invents a problem in
    a control.
- **Who judged**: the agent that wrote the cases proposed the labels, and the user confirmed them.
- **How the rubric was applied**: a false claim about what the code does counts as unusable. A
  garbled extra line whose neighbouring line states the fact correctly counts as fixable.
- **Rows**: [chatty-functions.jsonl](chatty-functions.jsonl) holds 30 runs (with packet and reply)
  and 30 judgments. `scripts/chatty.py replies` prints each reply beside its expectation;
  `scripts/chatty.py report` recomputes the table. A changed prompt changes its id, and its old
  judgments stop counting.

## Per case

**Explain**

| Case | Label | Why |
|---|---|---|
| `late-binding` | good | names the late binding of `i` and `name` |
| `bisect-bucket` | good | boundaries go to the upper bucket |
| `sentinel-default` | unusable | says `default=_MISSING` "creates a new object each time" — false, and in the part the reader is told to watch |
| `generator-exhausted` | fixable | finds the exhausted generator, but says the second use "will fail" (it is silently empty) and never says the width is always 0 |
| `eq-without-hash` | unusable | says `first_visit` "prevents duplicates" and `Point` is unsuitable for sets "without careful handling"; it raises `TypeError` on the first call; leads with invented thread-safety concerns |
| `full-jitter` | unusable | misses that `cap` never applies with the defaults; the pitfalls it offers are noise |

**Grill**

| Case | Label | Why |
|---|---|---|
| `check-then-insert` | fixable | the race is question 3 of 3, behind two vague questions |
| `swallowed-errors` | good | question 1: which exceptions should stop the loop |
| `cache-forever` | unusable | nothing on staleness or unbounded growth; question 1 assumes a failed `fetch` leaves an entry in the cache, which it does not |
| `split-bill` | good | the rounding discrepancy, then `people=0` |
| `naive-now` | fixable | question 1 hits aware against naive; question 3 invents a concurrency problem in a pure function |
| `clamp` (control) | fixable | the NaN question is fair; pads to three with `inf` and precision at the bounds instead of saying there is little to challenge |

**Plan**

| Case | Label | Why |
|---|---|---|
| `timeout-per-call` | unusable | puts the timeout on the constructor, which is per client, missing "per request"; changes `health` and every instantiation for nothing |
| `retry-requests` | unusable | walks into the trap: retries every exception, POST and 4xx included, and never mentions repeated side effects |
| `inject-clock` | fixable | right idea, but the injected clock is used only in `is_expired`, not `__init__`; filler steps |
| `cart-already-rejects` (control) | fixable | says first that the goal is already met, then pads to eight steps of type checks and docs |
| `split-parse-store` | fixable | right extraction; one step updates callers for a signature that does not change |
| `rename-keep-alias` | fixable | callers, deprecation and tests covered, but inverted: `get_user` wraps `fetch_user`, which warns, so every new call warns |

**Change summary**

| Case | Label | Why |
|---|---|---|
| `hidden-default-change` | fixable | the 30 s → 5 s drop is bullet 1; says `fetch` previously used a hardcoded timeout (it had a parameter); misses that `timeout=` callers break |
| `page-off-by-one` | fixable | fix and `ValueError` right; bullet 4 contradicts them: "No functional change … only correction of off-by-one error" |
| `mixed-concerns` | good | both changes, one bullet each |
| `pure-rename` | good | says behaviour does not change |
| `tests-only` | good | all four tests, nothing else claimed |
| `narrower-except` | fixable | propagation right; bullet 2 opens with "This changes the behavior when files don't exist" — the one case that did not change |

**Commit message**

| Case | Label | Why |
|---|---|---|
| `hidden-default-change` | unusable | "Simplify HTTP fetching with default timeout" hides the 30 s → 5 s drop; claims a default timeout parameter was introduced (one existed) |
| `page-off-by-one` | good | "Fix page indexing to be 1-based and add validation" |
| `mixed-concerns` | fixable | both changes, truthfully; subject 72 characters; the body does not say they are unrelated |
| `pure-rename` | fixable | subject 77 characters; invents a motive ("better clarity") |
| `tests-only` | good | subject 61 characters and a five-line bulleted body, but accurate |
| `narrower-except` | fixable | accurate; subject 67 characters; the body is one long paragraph |

## What it taught

- **The 30B fills every "at most N" to exactly N.**
  - All 6 plans had 8 steps, all 6 grills had 3 questions, and all 6 summaries had 4 bullets.
  - 5 of 6 commit subjects ran past 60 characters.
  - Most invented concerns and self-contradictions sit in that filler. The summary prompt's "say so
    plainly when behaviour does not change" came back as a "no behaviour change" bullet even in
    diffs that change behaviour.
  - A prompt that asks for a stopping point rather than a ceiling is the obvious fix. It is untested.
- **Explain and plan fail on substance, not length.** Their unusable replies misstate what the code
  does or plan the wrong change. A shorter reply would not fix that.
- **Reading a diff is the 30B's strongest prose job.** Summaries caught the default changed inside a
  refactor, both halves of the mixed diff, and the narrowed `except`. The commit message for the
  same hidden default missed it, because compressing to one subject line dropped the change that
  mattered.
- **Controls:** plan recognised a goal already met, then padded anyway. Grill did not say "little to
  challenge" and padded instead.

## Close calls

Three labels decide verdicts. The user confirmed each as below.

- **grill / `clamp`:** fixable. As unusable, grill has 2 unusable and falls below the bar.
- **commit / `mixed-concerns`:** fixable. Missing "these are unrelated" counts as editing, not a
  missed point. Counted as a miss, commit falls below the bar.
- **summary, three self-contradicting filler lines:** fixable, under the rubric reading above. Read
  strictly ("any false sentence"), summary has 3 unusable and falls below the bar.

## Revision: one question per turn, and a constrained commit prompt

Same night, same cases, same bar. The prompts followed the user's design rule: ask for one thing and a
way to stop, and let code enforce the format. The agent proposed the labels; the user routed from them
without flipping any.

**Grill, asked for one question per turn.**
- **The prompt:** reply `NO CHALLENGE` when nothing is left. Each case was asked twice, the second
  time with the first question answered by "Fair point, I'll handle that."
- **Turn 1:** 2 good, 0 fixable, 4 unusable.
- **Turn 2:** 0 good, 1 fixable, 5 unusable.

That is below the bar in both turns, and worse than the three-question prompt (1 unusable).
- **The stop word was never used** in 12 replies, the control included.
- **Choosing one question, the 30B mostly chose the wrong one:**
  - a `find_user` failure after the insert, not the race
  - "what happens to the `orders` list"
  - `low == high` in the control, which the code handles
- **Turn 2** repeated a question just answered and ran past the token limit.

**Commit message, constrained:**
- **The prompt:** `subject:` / `body:`, observable changes only, no motive; code strips the period.
- **Result:** 4 good, 1 fixable, 1 unusable, where the old prompt got 2 / 3 / 1.
- **Better:** every subject is within 60 characters (5 of 6 were over), and no motive is invented.
- **Still unusable:** the hidden 30 s → 5 s default, now under "Update HTTP fetch functions with
  configurable timeout".

**Routing decided from it:**
- **Grill** goes to the flagship: one richer question per turn (the question, why it matters, what
  settles it), one-shot until the Chat surface exists.
- **The three-question grill** stays on the 30B for `local-only`.
- **Commit** keeps the constrained prompt on the 30B.

Every run stays in [chatty-functions.jsonl](chatty-functions.jsonl) under its own prompt id.
`scripts/chatty.py report` counts only the prompts in force, which puts the three-question grill back
in the table above.

## Limits

- Six cases per function, one sample each: directional, not a benchmark.
- Synthetic snippets written by the agent that proposed the labels. They are not the developer's own
  code, and the expectations are that agent's.
- The flagship was not measured, so "the flagship does explain and plan acceptably" is assumed
  from its other hit rates ([function-routing.md](function-routing.md)), not shown.
- Grill is single-turn here; the design calls it a mode with one question at a time
  ([skills-and-modes.md](../skills-and-modes.md)), which needs the unbuilt Chat surface.
- Packets are the snippet alone. A real explain or plan call would carry surrounding context, which
  could help or distract.
