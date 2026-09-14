# devcompanion handoff

Status: 2026-09-15, end of pass 7. This is the pickup document for the next session: where the
project stands, what the user decided, what to build next, and what is still open.

**Direction: design and implement.**
- Latency measurement is finished.
- A hit rate is measured only where one is missing, and only on the local instruct/coder model
  (`qwen3-coder:30b`). The flagship is plugged in where that model proves unusable, and is not
  benchmarked.
- Ollama may be used.

## Start here

devcompanion is a passive development companion.
- **The engine** (Python) watches what you type in Neovim, including **unsaved buffers**. It
  snapshots the code, detects signature changes, finds broken call sites, runs tests after saves,
  interprets the language server's diagnostics, proposes checked fixes, and publishes findings.
- **The adapter** (Lua) sends editor events and draws the findings.

The two halves talk only through files under `<workspace>/.companion/` ([contract.md](contract.md)).

### State at handoff

| | |
|---|---|
| Branch | `main` in `~/repos` (that repo tracks only `devcompanion/`), level with `origin/main` at `b5aac42`. No other session has committed since |
| Remote | `https://github.com/Yagimipreme/Atreus.git` — **public**. HTTPS through `gh`; SSH has no key |
| Uncommitted | **passes 5, 6 and 7**: 59 paths. `testing/test.py` is the user's scratch file — leave it. The user commits on request; ask before committing or pushing |
| Unit tests | **191 passed** — `.venv/bin/python -m pytest -q` (~31 s; 188 under `tests/`) |
| Integration | **55 checks passed** — `scripts/check-workflow.py` (~2 min). It configures no model, so it does not exercise checked fixes; `tests/test_engine_fixes.py`, `tests/test_fix_check_project.py` and a tmux run of the panel do |
| Engine | running detached, pid **1355210**, `--model qwen3-coder:30b`, checked fixes on, holding `.companion/engine.lock` |
| Ollama | running (system service, 0.33.3); the user allowed its use |
| Neovim | **the user has not restarted it since the pass 7 Lua changes**: the panel's fix review, merged fixes, and `?` rows for unknown receivers are not yet in their editor |
| Global KB | pages written and linted, **not published** (see *Knowledge base*; `publish.sh` commits and pushes — ask) |

### Read, in this order

1. This file.
2. [evaluations/function-routing.md](evaluations/function-routing.md) — which model does which job
   (hit rates, routing, decisions), and [evaluations/chatty-functions.md](evaluations/chatty-functions.md)
   for the prose functions.
3. [configuration.md](configuration.md) — profiles, routing chains, gates, `local-only`, the machine
   grant. Implemented.
4. [model-routing.md](model-routing.md) — trust levels (✓ fact, ✓ checked, ◇ advice), passive vs
   pulled, the resident specialist against the flagship, the prompt design rule.
5. [nvim/README.md](../nvim/README.md), [contract.md](contract.md), [edit-actions.md](edit-actions.md) —
   the UI, the protocol and how edits are offered.
6. As needed: [code-documentation.md](code-documentation.md), [evaluations/checked-fixes.md](evaluations/checked-fixes.md),
   [providers.md](providers.md), [skills-and-modes.md](skills-and-modes.md), [text-canon.md](text-canon.md),
   [intake-watermark.md](intake-watermark.md), [vision.md](vision.md),
   [local-model-and-context.md](local-model-and-context.md).

## What is built

### Engine (`src/devcompanion/`)

**Analysis:**
- Observes editor events and saves, and snapshots content by hash, with unsaved buffers as overlays.
- Detects signature changes and removed functions.
- Judges call sites over the revisions the editor actually holds.
- Runs tests for saved content, and interprets diagnostics into problems (`present/problems.py`).
- Publishes `findings.jsonl` and `engine.json`.
- The model tier writes one suggestion per breaking claim, still through `llm/client.suggest`.

**Caller reachability** (`investigate/callers.py`, pass 7). A call counts only where it can reach the
function:

| Function kind | Where a call counts |
|---|---|
| Nested | inside its enclosing function |
| Module-level | in its own file, or through an import: `from m import f [as g]`, `from m import *`, `import m [as x]`, `from pkg import m`, relative imports |
| Method | `self.`, `cls.` or `Class.`. Any other receiver only in files that import the class, and then as `unsure` (`?`) |

It was built after the user's panel showed 56 rows from one removed nested helper `add`.

**Checked fixes** (`fix/`, wired in pass 7):
- **Trigger:** a saved Python file whose editor diagnostics report errors queues a `fix` job on the
  engine's single worker. It is never run for an unsaved buffer or in replay. At most 3 problems per
  revision; a problem already answered at this revision is not asked again.
- **The fix module** (`fix/`):

  | File | Does |
  |---|---|
  | `prompt.py` | builds the packet |
  | `propose.py` | asks the `passive.fix` routing chain and merges fixes |
  | `patch.py` | turns the reply into an edit |
  | `check.py` | the gate: applies → parses → not suppressed → target gone by rule → no new *error*. A new warning is carried beside the ✓ |
  | `project.py` | the checker runs over a **shadow tree of the whole workspace**, with every other unsaved buffer in place |

  The shadow tree is symlinks, with real directories only along the files that differ. basedpyright
  gives exactly the real project's diagnostics, in ~0.7 s.
- **Several problems, one fix.** Before asking about a problem, every fix already checked is tried
  against its targets. If one removes them too, the model is not asked. Problems resolved by the same
  edits share a `fix_id`, with their lines in `covers`.
- **What is recorded:** `fix_proposal` evidence per problem.
  - A checked fix appears on its `diagnostic_context` as `fix`: `{id, verdict, covers, warnings,
    edits, diff, profile, depends_on}`.
  - A problem the checker does not report is `not_visible`, and is never sent to a model.
  - A proposal no model answered is not recorded, so the next save asks again.
- **Verified live (pass 7):** the 30B's fixes for three problems all checked. One exists only through
  a relative import.

**Configuration and routing** (`config.py`, `llm/route.py`, pass 7):
- **Scopes:** machine `~/.config/devcompanion/config.toml` (or `COMPANION_CONFIG`); project
  `.companion.toml`, which may request and route but never grant, set the mode or define a profile;
  session flags, which only narrow.
- **Mode:** `local-only` is the default; `hybrid` needs a machine grant keyed by the project's path.
  A passive function never keeps a remote profile.
- **Profiles:** `local-qwen3-coder`, `local-fast` (3B on the CPU) and `flagship` (a providers.py spec,
  default `claude:sonnet/low`; `codex:` fills the same role in one line). Remote-ness is derived, never
  declared.
- **The router:** tries the chain, moves on when the packet does not fit, the call fails or the
  function's gate refuses, and names the profile that answered. `system` may be a function of the
  profile, giving each kind of model its own prompt.
- **Unavailable functions** say what they need and what is local:
  `Explain needs a reasoning model. Available locally: symbols · references · types · diagnostics`.
- **`companion config --effective`** prints every value with its scope, and for each reachable remote
  profile the exact command and system prompts.
- **Not yet:** the engine's one-sentence suggestion does not route through this, and `engine.json`
  does not report the routing.

**One engine per workspace** (`instance.py`, pass 7): `watch` takes an exclusive `flock` on
`.companion/engine.lock` before writing anything. A second `watch` exits with
`another engine (pid N) is already watching …`. `ingest` and `replay` take no lock.

**Providers** (`llm/providers.py`, pass 6):
- **One call:** `ask(spec, system, user)` for `ollama:` (`tokens`, `ctx`, `keep`, `gpu=0`,
  `endpoint`), `claude:<alias>[/effort]` and `codex:[model][/effort]`.
- **Tool-less:** the CLIs run in an empty scratch directory; `argv()` is the one command builder.
- **Tripwire passed for both** (`scripts/check-provider-tripwire.py`).

**Prose functions** (`pulled/chatty.py`):
- The judged prompts for explain, grill, plan, change summary and commit message; `FLAGSHIP` prompts
  where the flagship gets its own (grill); `shape_commit` enforces the commit format in code;
  `diff_stats`.
- **No surface calls them yet.**

### Editor (`nvim/`)

- **From pass 4:** panel, statusline count, pinned mode, `:CompanionInfo`. Per-buffer debounce
  (pass 5).
- **Checked fixes** (pass 7, verified in a real Neovim in tmux):
  - **The panel:** `✓ fix checked` at a problem's right edge; `✓ I can fix N of these · f review`
    under the count; the fix, its problem count and new warnings in the opened problem.
  - **`f`** opens `review.lua`'s float: the problem sentences a fix resolves, then the diff. Keys:
    `a` apply, `r` reject, `n` next (only when there are several fixes), `q` close.
  - **`a`** re-checks `depends_on` against the live buffer's canonical hash, applies the edits
    bottom-up as one undo step, leaves the buffer unsaved, and sends `action_result`
    (`applied` / `refused_stale` / `declined`). The engine logs it and never acts on it.
  - A fix is offered, applied and declined once, however many problems it resolves. Declines last for
    the Neovim session only.
  - `A` (delegate to an agent) is not bound: delegation does not exist.

### Evaluation tooling (hit rates only; no Codex; no flagship benchmarking)

| Script | Measures |
|---|---|
| `scripts/evaluate-fixes.py` | checked fixes on the hand-written corpus; `--rejudge` re-checks stored replies without a model |
| `scripts/build-function-corpus.py` | builds `tests/fixtures/function-corpus.json` (sentences, planted bugs, controls) |
| `scripts/evaluate-functions.py` | sentence, suspicious-line and culprit hit rates; `--rescore` without a model |
| `scripts/route-policies.py` | escalation chains, the warnings rule and model pairs, replayed from stored rows |
| `scripts/check-provider-tripwire.py` | the provider safety gate |
| `scripts/chatty.py` | prose functions on the 30B, judged by hand: `run`, `replies`, `judge`, `report`. Cases are in `testing/chatty/`; `:luafile testing/chatty/chatty.lua` asks them from Neovim. Only runs under the prompts in force count |

The tmux driver that verified the panel in pass 7 lived in a session scratchpad and is gone. If UI
checks recur, rebuild it under `scripts/`. It was a workspace built by the real engine with a
stand-in model, an `engine.json` heartbeat keeper, `nvim -n -u <minimal init>`, and
`tmux send-keys` / `capture-pane`.

## What the user decided

### Pass 7 (2026-09-14 to 15)

**Prompts and model roles**
- **Design rule for local prompts: ask for one thing and a stop, not a format to fill.** Facts go
  before the sentence; code enforces what code can.
  - **Measured:** it fixes format, not selection. The commit schema held.
  - **But:** asked for the single strongest grill question, the 30B picked wrong (4 of 6 unusable)
    and never used the stop word.
- **The 30B is the resident specialist.** It observes, compresses, summarises diffs, challenges a
  selection with three questions, and generates candidate fixes. **The flagship** understands,
  explains, plans, designs and discusses. `flagship` is a configuration role (Claude Code or Codex),
  never a provider named in code, and must stay provider-agnostic.
- **Grill goes to the flagship:** one richer question per turn (question, why it matters, what
  settles it), one-shot until the Chat surface exists. The judged three-question prompt stays on the
  30B as the `local-only` fallback.
- **Commit message** keeps the constrained prompt on the 30B: `subject:` / `body:`, observable
  changes only, no motive. Code strips the period and reports a subject over 60 characters without
  cutting it, since cutting can hide a change. Result: 4 good, 1 fixable, 1 unusable.
- **Explain and plan under `local-only`** say they need a reasoning model and list what is local. A
  labelled best effort may be offered, never by default.
- **Diagnostic sentences** stay on the 3B on the CPU.
- **Change summary becomes change awareness.** The engine's facts (changed files, symbols, call
  sites, diagnostic changes, diff statistics) are expressed as one sentence that adds nothing beyond
  them. Agreed; unbuilt.

**Fixes**
- **Checked fixes are the local model's most valuable job:** a borderline model proposes,
  deterministic tools accept.
- **A new warning is noted beside the ✓, not refused**; a new error refuses.
- **One fix that resolves several problems is one fix** (`✓ fix checked · 2 problems`).
- **The fix hit rate is done.** The hand-written corpus stands; no real-problem labelling.

**Engine and documentation**
- **One engine per workspace**, enforced by the engine.
- **Documentation for the code in view: both halves.** Surfacing existing docs is local; writing docs
  goes to the flagship ([code-documentation.md](code-documentation.md)).

### Earlier, still binding

- **Pass 6.** Per-function model selection as data. `local-only` is a first-class mode and the
  default. No flagship testing on jobs a small model does. The 30B proposes unasked fixes, and the 3B
  stays out of fixes. Codex is not tested further.
- **Chatty bar.** More than 1 unusable reply in 6 hand-judged cases routes a function to the
  flagship. Explain (3) and plan (2) went there. The labels are proposed by the agent and confirmed by
  the user.
- **Pass 5.** Two lanes: passive (automatic, tiny, verifiable) and pulled (user-invoked, may advise).
  Trust marks ✓ fact / ✓ checked / ◇ advice, and **◇ never appears unasked**. Deterministic analysis
  discovers facts; a model compresses or connects them. Change awareness speaks in the editor's
  voice. Completion stays outside the companion. The roadmap comes later, as repo-backed Markdown
  epics.
- **Pass 4, UI.** Polish, not redesign. Three levels of attention: statusline count → compact panel
  → deep-work float. One line per problem. Interpret, don't echo. Semantic, scarce colour. No engine
  metadata while coding. Nothing opens on its own. No key for a capability that does not exist.
- **Designs from the user, not yet built:** `plan` and `grill` floats (`<leader>ap`, `<leader>ag`,
  `<leader>ar`; `<leader>ai` is taken by `claude_agent.lua`), model-normalised sentences where the
  rules run out, and `defined in` for undefined names.

## Routing in force

| Function | `local-only` | `hybrid` | Basis |
|---|---|---|---|
| Checked fix, unasked | 30B | 30B (passive stays local) | decided · 48/51 ✓, 1 wrong |
| Checked fix, on `f` | 30B | 30B → flagship when the gate refuses | decided |
| Diagnostic sentence where the rules run out | 3B on the CPU, behind the sentence check | same | decided · 18/30 |
| Change-awareness sentence | 30B, behind a nothing-beyond-the-facts check | same | decided design · unbuilt |
| Change summary | 30B | 30B | decided · 0 of 6 unusable |
| Commit message | 30B, constrained prompt | 30B | decided · 4 / 1 / 1 |
| Grill | 30B, three questions | flagship, one richer question; the 30B when it does not answer | decided |
| Surface documentation for the code in view | deterministic and QMD | adds remote doc search on request | decided scope · unbuilt |
| Most suspicious line | 30B | flagship | proposed · 16/30 against 29/30 |
| Failing test → culprit | 30B | flagship | proposed · 21/30 against 28/30 |
| Explain, plan, write docs, architecture, roadmap | unavailable; names what is local | flagship | decided |
| Completion | outside the companion | outside | decided |

These are the defaults in `config.py` (`DEFAULT_ROUTING`). Sonnet and Opus name what filled the
flagship role when measured.

## Next steps — build

Build steps 1–5 are done (configuration and routing, the warnings rule, checked fixes in the engine,
review and apply in the panel, the whole-project gate). In order from here:

6. **Diagnostic sentences where the rules run out.**
   - **Route:** the 3B on the CPU through `passive.sentence`, behind the sentence check (names kept, at
     most 14 words, nothing invented, not an echo; `scripts/evaluate-functions.py` holds the check).
   - **Fallback:** the raw first line when the check fails.
   - **Engine side:** `present/problems.py` keeps grouping and facts; the model only rewrites the
     sentence.
   - **Open:** confirm the CPU-only 3B's hit rate once.
7. **Change-awareness lines.**
   - **Deterministic first:** `renaming sep · 2 callers remain` from signature and caller findings (✓
     fact).
   - **Then the one-sentence version:** a facts packet goes to the 30B, behind a check that the
     sentence names nothing beyond the facts. Measure its hit rate once built.
8. **Pulled actions as ◇, through their chains.**
   - **Most suspicious line, and failing test → culprit.**
   - **The prose functions**, with the judged prompts in `pulled/chatty.py`:
     - grill: the flagship prompt in hybrid, three questions locally
     - commit message and change summary on the 30B
     - explain and plan on the flagship
   - **The UI:** `plan` and `grill` floats with the user's keys. A prompt change means re-running and
     re-judging its cases.
9. **Route the engine's model calls through the configuration.** The one-sentence suggestion still
   calls `client.suggest`. Also `engine.json` reports the active routing.
10. **Documentation surfacing** ([code-documentation.md](code-documentation.md)).
    - **Engine:** needs an `outbox.jsonl` writer (the engine has never sent an `lsp_request`).
    - **Adapter:** already answers `hover`, `definition`, `references` and `document_symbols`.
    - **Recommended order:** docstrings through hover, then QMD.
11. **Later:**
    - **The Chat surface.** Still open: the flagship is reachable one function at a time, with no
      conversation state. Grill's one-question-per-turn needs it, and so do modes.
    - **Tests over the shadow tree**, so ✓ can mean more than type-consistent.
    - **Edits to other files, and agent delegation in a worktree.**
    - **Roadmap epics.**

**Working rules for UI changes:**
- After engine or Lua changes, restart the engine (see *Live setup*) and tell the user to restart
  Neovim.
- Rerun the harness, and look at a real terminal before calling a UI change done.

## Hit rates still missing

Hit rates only: no timing, no Codex, no flagship runs.

1. **The CPU-only 3B sentence hit rate**: the same weights as the measured run; confirm once.
2. **The change-awareness sentence**, once built.

## Findings that shape the design

Numbers: [evaluations/function-routing.md](evaluations/function-routing.md),
[evaluations/chatty-functions.md](evaluations/chatty-functions.md).

**Hit rates**

| Job | 3B | 30B | Sonnet | Opus |
|---|---|---|---|---|
| Fixes (✓ shown / wrong), warnings noted | 41/4 | 48/1 | 51/0 | 50/0 |
| Sentences | 18/30 | 13/30 | | |
| Suspicious line, exact | 4/30 | 16/30 | 24/30 | 29/30 |
| Culprit | 9/30 | 21/30 | 28/30 | 28/30 |

**Routing and gates**
- **Escalation recovers refusals, never a wrong ✓.** The most precise model goes first wherever a ✓
  is shown.
- **A gate must be computable at run time.** Fixes and sentences have one; suspicious-line and
  culprit answers do not.
- **Two models agreeing buys precision:** 30B ∧ Sonnet flags 15/30 bugs with no false flags.

**Local hardware and models**
- **On the 8 GB card, the 3B and the 30B evict each other.** A CPU-only 3B coexists with the 30B.
- **The 30B:**
  - **Invents facts in unchecked sentences.**
  - **Pads every "at most N" to N.**
  - **Can't pick the single most important point.**
  - **Explains and plans wrongly on substance.**
  - **Reads diffs well.**
  - **Fixes the whole file** when asked about one problem.
- **`qwen3:4b` as installed is unusable:** it reasons in its reply despite `think: false`.

## Live setup on this machine

**Engine.** Start it detached from the repo directory:

```bash
cd ~/repos/devcompanion
setsid nohup env PYTHONPATH=src .venv/bin/python -m devcompanion.cli \
  --root /home/iqqe/repos/devcompanion --model qwen3-coder:30b --keep-alive 30m watch \
  >> .companion/watch.log 2>&1 < /dev/null &
```

**Restart it whenever engine code changes:**
1. Find it with the **anchored** pattern `pgrep -f '^\.venv/bin/python -m devcompanion.cli'`. An
   unanchored pattern also matches the calling shell.
2. Kill the **literal pid**. The Bash tool's shell is zsh, which does not split an unquoted `$var`:
   `for p in $pids` hands `kill` one word and the kill fails. It happened in pass 7.
3. Wait for it to exit: `tail --pid=<pid> -f /dev/null`.
4. Start it, then confirm `engine.json`'s `pid` is the new live process and `pgrep` lists exactly one
   engine.

If the kill failed anyway, the guard now makes the new engine exit with
`another engine (pid N) is already watching …` in `watch.log`.

**Rejudging live claims.** To re-derive fresh caller claims with changed caller code, stop the
engine, then rebuild each claim's task from the snapshot store: `detect(path, snap.get(baseline),
snap.get(sha))`, then `Engine._investigate`. Take `instance.claim` first. The pass 7 script was
scratch; rewrite it if needed.

**Neovim.** `~/.config/nvim/lua/plugins/devcompanion.lua` loads the plugin: `<leader>aa` panel,
`<leader>as` info, and the lualine count. Run `:CompanionStart` from a real file buffer. Lua changes
need a Neovim restart. Autosave is on everywhere except in workspaces the companion observes.

**Models and tools.**
- **Ollama** 0.33.3, as a system service. `systemctl start ollama` works through polkit; `sudo`
  needs a password.
- **Installed models:** `qwen3-coder:30b` (~17 GB RAM while loaded), `qwen2.5-coder:3b`, `qwen3:4b`
  and others.
- **Memory:** the machine ran out once, with the 30B, a CPU-only 3B, three Codex processes and a game
  at once.
- **basedpyright** 1.38.0 comes from Mason (`~/.local/share/nvim/mason/bin/basedpyright`), not
  `PATH`.
- **Subscription CLIs**, only through `llm/providers.py`: `claude` 2.1.270 (Claude Max; `--bare`
  needs an API key) and `codex` 0.153.4 (not tested further).

## Standing decisions

Settled in conversation; do not relitigate without the user.

| Decision | Where |
|---|---|
| Latency measurement is finished; evaluation measures hit rate only, on the 30B, where missing | this file |
| No flagship benchmarking on the prose functions or on jobs a small model does; Codex not tested further | this file |
| Chatty bar: more than 1 unusable of 6 → flagship | [chatty-functions.md](evaluations/chatty-functions.md) |
| Explain, plan, write docs → flagship; `local-only` says what is local instead | [function-routing.md](evaluations/function-routing.md) |
| Grill: flagship one richer question per turn; the 30B's three-question prompt in `local-only` | [chatty-functions.md](evaluations/chatty-functions.md) |
| Commit message: constrained `subject:` / `body:` prompt on the 30B; long subjects reported, not cut | [pulled/chatty.py](../src/devcompanion/pulled/chatty.py) |
| Local prompts: one thing and a stop, not a format; but the 30B does not rank, so give it a short list where the job is choosing | [model-routing.md](model-routing.md) |
| The 30B is the resident specialist; the flagship is a provider-agnostic configuration role | [model-routing.md](model-routing.md), [configuration.md](configuration.md) |
| A new warning is noted beside the ✓; a new error refuses | [fix/check.py](../src/devcompanion/fix/check.py) |
| The 30B proposes unasked fixes; the 3B stays out of fixes; diagnostic sentences on the 3B on the CPU | [function-routing.md](evaluations/function-routing.md) |
| One fix resolving several problems is one fix | [contract.md](contract.md) |
| A fix is checked against the whole project, and applied only to the bytes it was checked on | [fix/project.py](../src/devcompanion/fix/project.py), [edit-actions.md](edit-actions.md) |
| A call site counts only where the function is reachable | [investigate/callers.py](../src/devcompanion/investigate/callers.py) |
| One engine per workspace, enforced by a lock | [instance.py](../src/devcompanion/instance.py) |
| Documentation: surfacing is local, writing is the flagship's | [code-documentation.md](code-documentation.md) |
| Routing is decided by who asked (passive vs pulled), not by model size | [model-routing.md](model-routing.md) |
| Trust levels ✓ fact, ✓ checked, ◇ advice; ◇ never appears unasked | [model-routing.md](model-routing.md) |
| Routing is per function, as ordered chains; the gate belongs to the function | [configuration.md](configuration.md) |
| `local-only` is the default; an empty chain is unavailable, never silently rerouted | [configuration.md](configuration.md) |
| A repo file may request remote sharing; only machine config grants it | [configuration.md](configuration.md) |
| ✓ means checked, never "correct" | [fix/check.py](../src/devcompanion/fix/check.py) |
| Deterministic tools discover facts; a model compresses or connects them | [model-routing.md](model-routing.md) |
| Completion stays outside the companion | [model-routing.md](model-routing.md) |
| Providers are CLI agents invoked tool-less, after a tripwire test proves they cannot edit files | [providers.md](providers.md) |
| The engine never writes a developer file; the adapter applies edits to a buffer, unsaved | [edit-actions.md](edit-actions.md) |
| Agent delegation runs in a throwaway worktree and returns a diff | [edit-actions.md](edit-actions.md) |
| Modes and skills differ; modes are pulled-tier only, never escalate permissions, and wait for Chat | [skills-and-modes.md](skills-and-modes.md) |
| Diagnostic interpretation is engine-side and deterministic; a model may rewrite sentences, never grouping or facts | [problems.py](../src/devcompanion/present/problems.py) |
| Nothing opens or takes focus on its own; no key or UI for a capability that does not exist | [nvim/README.md](../nvim/README.md) |
| Do not port the engine to Rust while the design is moving | [configuration.md](configuration.md) |

## Known risks and edges

**Operations**
- **Restarts:** engine code changes need an engine restart; Lua changes need a Neovim restart.
- **Unlocked commands:** `ingest` and `replay` take no lock; never run them against a watched
  workspace's state directory.
- **Model status hides bugs:** the model client maps every exception to a status, so a programming
  error looks like an unavailable model.
- **Memory:** the 30B plus other loads can exhaust RAM.
- **Orphaned children:** a killed wrapper shell may not kill its Python child; check with an anchored
  `pgrep` before resuming anything that writes shared files.
- **Harness timeouts:** the harness gives the unit suite 300 s and every other command 30 s. A slower
  command needs its own timeout (`run(..., timeout=)`).

**Checking and fixes**
- **Caller reachability matches imports syntactically.** Two modules with the same dotted tail are not
  told apart. A method on a receiver of unknown type is `unsure`, never `breaks`.
- **The gate checks types, not behaviour.** A checked fix can still be the wrong fix.
- **At most 3 problems per revision get a fix**, and declined fixes are forgotten when Neovim restarts.
- **The flagship grill prompt has never been run**, by design (not benchmarked), and nothing calls it
  yet.

**Coverage gaps**
- The inbox grows without bound.
- A file changed while the engine was down is missed until it changes again.
- Tests never run on unsaved code.
- One Neovim session per workspace; Python only.

## History, compressed

- **Passes 1–3** (2026-09-09…): engine skeleton, unsaved-buffer analysis, canonical text, intake
  watermark, local model tier.
- **Pass 4** (`90c0a98`…`b5aac42`): the panel redesign and its polish.
- **Pass 5** (uncommitted):
  - scoped the plugin's side effects (autosave, per-buffer debounce)
  - trust levels and local-model scope
  - the checked-fix gate and its corpus; three local models measured
- **Pass 6** (uncommitted):
  - the provider layer for Claude Code and Codex, and its tripwire
  - fixes on the subscription models
  - a function corpus from the project's own code, and hit rates for sentences, suspicious lines and
    culprits
  - routing chains replayed from stored rows
  - the five prose functions judged on the 30B: explain and plan to the flagship
- **Pass 7** (uncommitted):
  - **Design:**
    - the prompt design rule
    - the resident specialist against the flagship
    - `config.py` and `llm/route.py`
    - the documentation-function design
  - **Fixes:**
    - the warnings rule, rejudged
    - checked fixes proposed by the engine, and reviewed and applied from the panel
    - the whole-project gate (step 5)
    - merged fixes
  - **Fixes to the engine:**
    - the one-engine guard, after two engines ran on one workspace
    - caller reachability, after 56 bogus rows in the user's panel; plus a dropped call on a removed
      function's old `def` line
  - **Measured** (the user started Ollama again): live 30B fixes; grill and commit re-measured, which
    split grill between the flagship and the 30B
- **Harness artifacts, not product bugs:**
  - a stale swap file ate the tmux keystrokes
  - the harness's 30 s unit-suite timeout became too short

## Knowledge base

`~/knowledge-global`, searchable with a bare `qmd query`. Last published at `b9a475d`. Unpublished,
all linted:

| Page | Collection |
|---|---|
| `patterns/checked-model-fixes` — the gate, its effect, what models actually send | `global-agent-patterns` |
| `patterns/stop-conditions-not-formats` — ask a local model for one thing and a stop; it fixes format, not selection (draft) | `global-agent-patterns` |
| `models/qwen3-coder-30b` — latency, fixes, prose: pads formats, cannot pick one point, fixes whole files | `global-ai-models` |
| `models/qwen3-4b` — reasons in its reply despite `think: false` | `global-ai-models` |
| `hardware/rtx-2080-super-8gb` — the 3B and 30B evict each other; CPU-only coexists | `global-ai-models` |
| `gotchas/catch-all-hides-bugs-as-unavailability` | `global-lessons` |
| `gotchas/zsh-does-not-split-unquoted-variables` — the restart that left two engines | `global-lessons` |

Plus index and log entries in all three domains. Publish with `~/knowledge-global/publish.sh
"message"`, never by hand, and only when the user asks.

## Useful commands

```bash
uv sync --extra dev
.venv/bin/python -m pytest -q                                   # ~31 s
.venv/bin/python scripts/check-workflow.py                      # ~2 min
PYTHONPATH=src .venv/bin/python -m devcompanion.cli --root . config --effective
.venv/bin/python scripts/chatty.py report                       # prose functions against the bar
.venv/bin/python scripts/evaluate-fixes.py --rejudge docs/evaluations/checked-fixes.json
.venv/bin/python scripts/route-policies.py                      # replays stored rows, no model
.venv/bin/python scripts/check-provider-tripwire.py claude:sonnet
pgrep -af '^\.venv/bin/python -m devcompanion.cli'              # exactly one line
tail -f .companion/watch.log
```

## Working tree

`~/repos` is a git repository that tracks only `devcompanion/` and a `.gitignore`. Sibling
directories are untracked — do not clean or reset them. Commit and push only when the user asks.
Other agent sessions have committed to this `main` before, so do not switch branches.
