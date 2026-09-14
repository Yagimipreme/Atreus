-- Layer 0: configuration. One table, deep-merged with whatever the user passes to setup().
-- Kept separate so that no other module owns a default. Read it, never mutate it.
local M = {}

M.defaults = {
  -- Which buffers are observed. An empty list means "every buffer with a real file path".
  filetypes = {},

  -- Debounce windows in milliseconds. These are the adapter's only rate limits; the engine
  -- has its own. Text is the expensive one, so it waits longest.
  debounce = {
    text = 900,        -- after typing stops, before sending buffer_changed
    diagnostics = 400, -- after DiagnosticChanged settles
    cursor = 2000,     -- CursorHold is already debounced by 'updatetime'; this is a floor
  },

  -- How the engine is reached. v1: files under <workspace>/.companion.
  transport = {
    kind = "files",
    dir = ".companion",
    poll_ms = 1000, -- how often to check findings.jsonl for changes
  },

  -- Whether :CompanionStart should spawn the engine, and with what command. `watch` is the
  -- engine's actual long-running subcommand; there is no `serve`.
  engine = {
    autostart = false,
    cmd = { "companion", "--root", ".", "watch" },
  },

  -- Presentation. Nothing here may cause a window to open on its own.
  ui = {
    stale = "dim",     -- "dim" | "hide"
    max_findings = 12, -- per surface; the engine also caps, this is the last word
    split = "right",   -- where a surface opens when the user asks for it
    width = 60,
  },
}

M.options = vim.deepcopy(M.defaults)

function M.setup(opts)
  M.options = vim.tbl_deep_extend("force", vim.deepcopy(M.defaults), opts or {})
  return M.options
end

return M
