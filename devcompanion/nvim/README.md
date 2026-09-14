# companion.nvim

The Neovim adapter. It emits events, keeps the last findings the engine published, and draws
them. It runs no models and makes no decisions. Everything it exchanges with the engine is
described in `../docs/contract.md`, and how it hashes a buffer in `../docs/text-canon.md`.

## Install (lazy.nvim)

```lua
{
  dir = "~/repos/devcompanion/nvim",   -- or a git url once this is published
  lazy = false,                         -- plugin/ only registers commands; modules load on use
  opts = {},                            -- see lua/companion/config.lua for defaults
  keys = {
    { "<leader>aa", "<cmd>CompanionPanel<cr>", desc = "Companion" },
    { "<leader>as", "<cmd>CompanionInfo<cr>",  desc = "Companion: engine info" },
  },
}
```

`opts` is passed to `require("companion").setup()`. Observation does not start on its own:
run `:CompanionStart` in a workspace, or add an autocmd if you want it always on.

## Three levels of attention

The companion competes for space with the file tree, the editor and the terminal, so by
default it takes none.

### At rest: a count in the statusline

`require("companion").statusline()` returns

| | |
|---|---|
| `◉ 5` | five problems |
| `◉` | nothing to act on |
| `◉ 5 …` | the engine is still catching up with what is in front of you |
| `◌` | observing, but no engine is answering |
| (empty) | not observing |

and `require("companion").statusline_hl()` the highlight group to colour it with. For lualine,
as a LazyVim spec:

```lua
{
  "nvim-lualine/lualine.nvim",
  optional = true,
  opts = function(_, opts)
    table.insert(opts.sections.lualine_x, 1, {
      function() return require("companion").statusline() end,
      cond = function() return package.loaded["companion"] ~= nil end,
      color = function()
        local hl = vim.api.nvim_get_hl(0, { name = require("companion").statusline_hl(), link = false })
        return { fg = hl.fg and string.format("#%06x", hl.fg) or nil }
      end,
    })
  end,
}
```

### Asked: the panel

`:CompanionPanel` opens a float at the right edge of the editor. It does not split the layout.

**One problem is two lines, one inspected problem at a time, raw diagnostics only on request.**

```
╭ companion 📌 ────────────────────────────────╮
│ 3 problems · 5 diagnostics        ✓ 71 tests │
│                                              │
│ ▸ C  client.py:4                     unsaved │
│      missing required 'carry'                │
│                                              │
│ ▼ E  test.py:8                               │
│      split() expects str | None, got int     │
│                                              │
│      test_string.split(3)                    │
│                        ^                     │
│                                              │
│      got        int                          │
│      expected   str | None                   │
│      parameter  sep                          │
│                                              │
│   E  test.py:12                              │
│      possible None used with +               │
╰─────────────────── ↵ go to  d raw  q close ╯
```

A problem is not a diagnostic. basedpyright reports `test_string.split(3)` twice, once as "No
overloads for split" and once as "Argument of type Literal[3] cannot be assigned to parameter
sep". The engine groups messages about one mistake into one problem and says it as a sentence
(`../src/devcompanion/present/problems.py`); the header's dimmed `· 5 diagnostics` says how many
machine messages the count stands for.

A collapsed problem is always two lines: where, and one sentence, cut with `…` in the rare case
it does not fit. Everything else belongs to the opened problem.

**What the code has against what it needs.** An opened problem shows a small block in one
vocabulary, so it reads the same for every kind of mistake:

| label | colour | means |
|---|---|---|
| `got` `found` `returned` `missing` | red | what the code has |
| `expected` `required` | green | what it needs |
| `operator` `with` `left` `right` `parameter` `argument` `module` `defined in` | plain | where |
| `function` | function | the name involved |

```
got        int                 found      None
expected   str | None          operator   +
parameter  sep                 with       int
```

Colour is spent where the eye should go, not on whole lines: in the sentence, the symbol in
function colour, what the code has in red, what it needs in green. The code excerpt is
syntax-highlighted by Tree-sitter when its parser is installed, with the problem's own range —
the `3` in `split(3)` — in red on top. Provenance is dimmed and only shown on `d`.

| | |
|---|---|
| `T` | a failing test run |
| `C` | a call site that no longer fits a changed signature |
| `E` | an error from the language server |
| `?` | inferred: the parser could not settle it, so treat it as a question |
| `unsaved` | the claim rests on a buffer, not on any file yet |
| `stale` | the code moved since the claim was made; dimmed, or hidden with `ui.stale = "hide"` |

Problems are ordered fresh before stale, then failing tests, breaking calls, errors, and
inferred last. A green test run is not a problem; it is `✓ 71 tests` in the header.

| key | |
|---|---|
| `↵` | inspect: the code, the block above, what changed, a likely fix when a model offered one. On the inspected problem, go to it |
| `d` | raw: source, every diagnostic in the language server's own words, basis, buffer |
| `j` `k` | next and previous problem |
| `p` | pin or unpin |
| `r` | redraw |
| `<Esc>` | put the inspected problem away, or close |
| `q` | close |

The footer shows only the keys that do something where the cursor is. There is no `f fix`
until the engine can propose one.

The selected problem has a quiet background and a `▸` (`▼` when opened), and the terminal cursor
is hidden while the panel has focus, so the selection is the only thing marking where you are.

Having been asked for, the panel takes focus, because its keys act inside it. It closes on `q`,
a jump, or leaving its window, and hands the cursor back to the window it was opened from. It
never opens on its own. One line under the count appears only when it changes what the list
means: `engine not running`, `engine stopped · showing its last results`, `engine error`, or
`analysing…`. On a workspace that is not being observed it shows no list at all, only `not
observing this workspace · :CompanionStart`, because nothing in the editor has read that
workspace's findings.

**Pinned.** With `ui.pinned = true`, or `:CompanionPanelPin` / `p` for the session, the panel
stays open when the cursor leaves it and after a jump, and its title carries a 📌. Pinning a
closed panel opens it without taking the cursor. `:CompanionPanel` from the code window then
moves into it, and from inside it closes it. Unpinning a panel the cursor is not in closes it.

**Linked to the code.** While the panel is pinned and you are coding, moving the cursor onto a
line with a problem opens that problem in the panel; moving off puts it away. While the panel
has focus, the selected problem's range is highlighted in the code. Neither moves your cursor;
only `↵` does.

Commands take their workspace from the current file. From the panel, a terminal or a file tree
they use the panel's workspace or the one already observed, never the buffer's name.

`:CompanionErrors` and `:CompanionCallers` are the same panel, filtered.

### Debugging the companion: `:CompanionInfo`

Engine process and heartbeat, whether it has analysed this buffer (by canonical hash), unsaved
overlays, model, retrieval context, intake counters, and the adapter's own counters, in a
centred float. This was the panel's header; it is useful to whoever is working on the
companion and noise to whoever is coding.

### Not built: deep work and proposed changes

Plan, grill and review belong in a larger temporary workspace of their own, not in the panel.
A proposed fix belongs in a diff view (`accept`, `reject`, `next`), with the panel saying only
that a fix exists. Neither exists yet: the first needs the Chat surface and the second the
outbox writer and edit actions (`../docs/handoff.md`, `../docs/edit-actions.md`). Model-written
sentences for diagnostics are also not built: today's sentences come from rules, and a message
no rule knows keeps its first line.

## Commands

| Command | Effect |
|---|---|
| `:CompanionStart` | begin observing the current workspace |
| `:CompanionStop` | stop observing |
| `:CompanionPanel` | open the panel, move into it, or close it from inside |
| `:CompanionPanelPin` | pin or unpin the panel |
| `:CompanionErrors` | open the panel, errors only |
| `:CompanionCallers` | open the panel, affected callers only |
| `:CompanionInfo` | engine and adapter internals |
| `:CompanionStatus` | same as `:CompanionInfo` |
| `:CompanionGoal <text>` | record a short goal, optional |

## Highlights

All but one are `default` links, so a colourscheme can override any of them:

| group | links to | used for |
|---|---|---|
| `CompanionTitle` | FloatTitle | the problem count |
| `CompanionError` | DiagnosticError | `E`, `C`, `T` |
| `CompanionWarn` | DiagnosticWarn | `?`, engine notices |
| `CompanionOk` | DiagnosticOk | `✓ tests`, `no problems` |
| `CompanionSymbol` | Function | the function or name a problem is about |
| `CompanionGot` | DiagnosticError | what the code has, its range in the excerpt, the caret |
| `CompanionExpected` | DiagnosticOk | what the code needs |
| `CompanionLocation` | Directory | `test.py:8` |
| `CompanionMuted` | Comment | labels, tags, the diagnostic count, provenance |
| `CompanionKey` | Special | the selection marker, footer keys |
| `CompanionSelected` | CursorLine | the selected problem's two-line head |
| `CompanionSource` | Visual | the selected problem's range in the code |
| `CompanionIndex` | LineNr | reserved |
| `CompanionHiddenCursor` | (`blend=100`) | hides the terminal cursor inside the panel |

## Module map

| File | Layer | Owns |
|---|---|---|
| `plugin/companion.lua` | entry | user commands only; requires nothing at startup |
| `lua/companion/config.lua` | 0 | defaults, merged with user opts |
| `lua/companion/util.lua` | 0 | debounce, workspace root, position conversion, canonical text and hashing, JSON decoding |
| `lua/companion/collect.lua` | 1 | autocmds → contract events; answers engine LSP requests |
| `lua/companion/transport.lua` | 2 | the only module that knows how the engine is reached |
| `lua/companion/findings.lua` | 3a | the last published findings and engine status; what counts as a problem, ordering, staleness, liveness |
| `lua/companion/float.lua` | 3 | highlight groups, lines with highlights, width-aware cutting and wrapping, floats |
| `lua/companion/panel.lua` | 3b | the panel, and its link to the code |
| `lua/companion/info.lua` | 3c | `:CompanionInfo` |
| `lua/companion/init.lua` | wiring | public API, statusline |

## Developing

No build step. Edit a file, then in Neovim:

```vim
:lua package.loaded['companion.panel'] = nil
:CompanionPanel
```

`../scripts/test-plugin.sh` runs the whole adapter headless with a fake language server and a
fake engine, and prints the events emitted and the panel drawn.

`../scripts/check-workflow.py` is the stronger check: it drives this plugin in a real headless
Neovim against a real engine, and asserts that the adapter and the engine hash buffers
identically, that two messages about one mistake draw as one problem, that the panel leads with
a count and keeps engine metadata out, that ↵ inspects and d adds provenance, that it opens only
on request and gives the cursor back, that a pinned panel stays and is linked to the code both
ways, that the cursor hides inside it, and that the statusline carries the count.
