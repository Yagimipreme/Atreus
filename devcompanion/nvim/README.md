# companion.nvim

The Neovim adapter. It emits events and draws one pane. It runs no models and makes no
decisions. Everything it exchanges with the engine is described in `../docs/contract.md`,
and how it hashes a buffer in `../docs/text-canon.md`.

## Install (lazy.nvim)

```lua
{
  dir = "~/repos/devcompanion/nvim",   -- or a git url once this is published
  event = "VeryLazy",
  opts = {},                            -- see lua/companion/config.lua for defaults
  keys = {
    { "<leader>cc", "<cmd>CompanionPanel<cr>",  desc = "Companion: panel" },
    { "<leader>cs", "<cmd>CompanionStatus<cr>", desc = "Companion: status" },
  },
}
```

`opts` is passed to `require("companion").setup()`. Observation does not start on its own:
run `:CompanionStart` in a workspace, or add an autocmd if you want it always on.

## Commands

| Command | Effect |
|---|---|
| `:CompanionStart` | begin observing the current workspace |
| `:CompanionStop` | stop observing |
| `:CompanionPanel` | toggle the panel |
| `:CompanionErrors` | open the panel, errors only |
| `:CompanionCallers` | open the panel, affected callers only |
| `:CompanionStatus` | adapter counters and engine liveness, as a notification |
| `:CompanionGoal <text>` | record a short goal, optional |

Inside the panel: `<CR>` jumps to the finding, `r` refreshes, `q` closes.

## The panel

One read-only side pane, and the only thing that draws. It opens on command, never on its own,
and hands the cursor straight back to the window you were in.

```
companion · devcompanion

engine    idle · pid 537383 · 1s ago · 0 pending · seq 4
buffer    client.py · saved · analysed as saved file
model     disabled
context   qmd disabled · 0 passage(s)
unsaved   calc.py

CALLERS (2)
 * add(a, b) -> add(a, b, carry)  [buffer]
     client.py:4  missing required 'carry'
     · snapshot: add(1, 2)
```

The `buffer` line answers the only question a status display really has: *is this talking
about the code in front of me?* It compares the buffer's canonical hash with the revision the
engine says it analysed, so "engine is behind this buffer" is a state it can report rather than
a silence. `[buffer]` on a finding means the claim rests on unsaved content — true of what you
are typing, not yet true of any file. A finding whose inputs have moved on renders `[stale]`.

## Module map

| File | Layer | Owns |
|---|---|---|
| `plugin/companion.lua` | entry | user commands only; requires nothing at startup |
| `lua/companion/config.lua` | 0 | defaults, merged with user opts |
| `lua/companion/util.lua` | 0 | debounce, workspace root, position conversion, canonical text and hashing, JSON decoding |
| `lua/companion/collect.lua` | 1 | autocmds → contract events; answers engine LSP requests |
| `lua/companion/transport.lua` | 2 | the only module that knows how the engine is reached |
| `lua/companion/findings.lua` | 3a | the last published finding set, grouped by surface |
| `lua/companion/panel.lua` | 3b | the one pane: header, findings, staleness check, jump |
| `lua/companion/init.lua` | wiring | public API |

## Developing

No build step. Edit a file, then in Neovim:

```vim
:lua package.loaded['companion.panel'] = nil
:CompanionPanel
```

`../scripts/test-plugin.sh` runs the whole adapter headless with a fake language server and a
fake engine, and prints the events emitted and the pane drawn.

`../scripts/check-workflow.py` is the stronger check: it drives this plugin in a real headless
Neovim against a real engine, and asserts that the adapter and the engine hash buffers
identically, that the pane draws what the engine published, and that opening it does not steal
focus.
