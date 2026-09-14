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

**One line per problem, one inspected problem at a time, raw diagnostics only on request.**

```
╭ companion ───────────────────────────────────╮
│ 3 problems · 4 diagnostics        ✓ 71 tests │
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
│      got       int                           │
│      expected  str | None                    │
│      parameter sep                           │
│                                              │
│   E  test.py:10                              │
│      incomplete import statement             │
╰─────────────────── ↵ go to  d raw  q close ╯
```

A problem is not a diagnostic. basedpyright reports `test_string.split(3)` twice, once as "No
overloads for split" and once as "Argument of type Literal[3] cannot be assigned to parameter
sep", and an unfinished `from` import twice more. The engine groups those four messages into two
problems and says each as a sentence (`../src/devcompanion/present/problems.py`); the header
says how many messages the count stands for. Sentences wrap; nothing is cut off.

Colour is spent where the eye should go, not on whole lines: the symbol in function colour, what
was there instead (`int`) in red, what would have fitted (`str | None`) in green, the place in
directory colour, the code excerpt through Tree-sitter when its parser is installed. The rest
is plain, and provenance is dimmed.

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
| `↵` | inspect: the code with a caret, got and expected, what changed, a likely fix when a model offered one. On the inspected problem, go to it |
| `d` | raw: source, every diagnostic in the language server's own words, basis, buffer |
| `j` `k` | next and previous problem |
| `s` | stick or unstick |
| `r` | redraw |
| `<Esc>` | put the inspected problem away, or close |
| `q` | close |

The footer shows only the keys that do something where the cursor is. There is no `f fix`
until the engine can propose one.

Having been asked for, the panel takes focus, because its keys act inside it. It closes on `q`,
a jump, or leaving its window, and hands the cursor back to the window it was opened from. It
never opens on its own. One line under the count appears only when it changes what the list
means: `engine not running`, `engine stopped · showing its last results`, `engine error`, or
`analysing…`. On a workspace that is not being observed it shows no list at all, only `not
observing this workspace · :CompanionStart`, because nothing in the editor has read that
workspace's findings.

Commands take their workspace from the current file. From the panel, a terminal or a file tree
they use the panel's workspace or the one already observed, never the buffer's name.

**Sticky.** With `ui.sticky = true`, or `:CompanionPanelStick` / `s` for the session, the panel
stays open when the cursor leaves it and after a jump, and its title says `· sticky`. Sticking a
closed panel opens it without taking the cursor. `:CompanionPanel` from the code window then
moves into it, and from inside it closes it. Unsticking a panel the cursor is not in closes it.

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
| `:CompanionPanelStick` | toggle whether the panel stays open |
| `:CompanionErrors` | open the panel, errors only |
| `:CompanionCallers` | open the panel, affected callers only |
| `:CompanionInfo` | engine and adapter internals |
| `:CompanionStatus` | same as `:CompanionInfo` |
| `:CompanionGoal <text>` | record a short goal, optional |

## Highlights

All are `default` links, so a colourscheme can override any of them:

| group | links to | used for |
|---|---|---|
| `CompanionTitle` | FloatTitle | the problem count |
| `CompanionError` | DiagnosticError | `E`, `C`, `T` |
| `CompanionWarn` | DiagnosticWarn | `?`, engine notices |
| `CompanionOk` | DiagnosticOk | `✓ tests`, `no problems` |
| `CompanionSymbol` | Function | the function or name a problem is about |
| `CompanionGot` | DiagnosticError | what was there instead, and the caret |
| `CompanionExpected` | DiagnosticOk | what would have fitted |
| `CompanionLocation` | Directory | `test.py:8` |
| `CompanionMuted` | Comment | tags, labels, provenance |
| `CompanionKey` | Special | the selection marker, footer keys |
| `CompanionIndex` | LineNr | reserved |

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
| `lua/companion/panel.lua` | 3b | the panel |
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
on request and gives the cursor back, that a sticky panel stays, and that the statusline carries
the count.
