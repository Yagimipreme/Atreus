-- Public module. Wires config + collect + transport + findings + panel, and owns nothing else.
-- Everything a user calls goes through here.
local config = require("companion.config")
local util = require("companion.util")
local transport = require("companion.transport")
local collect = require("companion.collect")
local store = require("companion.findings")
local panel = require("companion.panel")

local M = {}

M.active = {} -- root -> true

function M.setup(opts)
  config.setup(opts)
  return M
end

local function current_root()
  local root = util.workspace_root(vim.api.nvim_buf_get_name(0))
  if not root then
    util.notify("no workspace root for this buffer", vim.log.levels.WARN)
  end
  return root
end

function M.start(root)
  root = root or current_root()
  if not root or M.active[root] then
    return
  end
  M.active[root] = true
  local tr = transport.for_workspace(root)
  collect.start(root)

  -- Findings: the engine rewrites the file, we reload and refresh whatever is open.
  tr:watch("findings.jsonl", function(data)
    store.load(data)
    panel.refresh(root)
  end)

  -- Engine liveness. The panel's header is the only consumer, and it must keep rendering when
  -- the file is absent: no engine running is a state to show, not an error.
  tr:watch("engine.json", function(data)
    panel.set_engine(root, util.decode_json(data))
  end)

  -- Requests from the engine: currently only LSP queries.
  local consumed = 0
  tr:watch("outbox.jsonl", function(data)
    local n = 0
    for line in data:gmatch("[^\n]+") do
      n = n + 1
      if n > consumed then
        local req = util.decode_json(line)
        if req and req.kind == "lsp_request" then
          collect.answer_lsp(root, req)
        end
      end
    end
    consumed = n
  end)

  -- The panel's "buffer" line describes wherever the developer is, so it has to follow them.
  -- Only when the pane is open: refreshing a hidden pane on every BufEnter is pure waste,
  -- and opening it later rebuilds it from scratch anyway.
  vim.api.nvim_create_autocmd({ "BufEnter", "BufWritePost" }, {
    group = vim.api.nvim_create_augroup("companion:panel:" .. root, { clear = true }),
    callback = function()
      if panel.is_open() then
        panel.refresh(root)
      end
    end,
  })

  if config.options.engine.autostart then
    vim.system(config.options.engine.cmd, { cwd = root, detach = true })
  end
  util.notify("observing " .. root)
end

function M.stop(root)
  root = root or current_root()
  if not root then
    return
  end
  collect.stop(root)
  transport.for_workspace(root):unwatch_all()
  pcall(vim.api.nvim_del_augroup_by_name, "companion:panel:" .. root)
  M.active[root] = nil
  util.notify("stopped observing " .. root)
end

-- The panel is the surface. `only` filters which finding sections it shows, which is all the
-- older per-surface commands ever were.
function M.panel(only)
  local root = current_root()
  if root then
    panel.open(root, only)
  end
end

function M.toggle(only)
  local root = current_root()
  if root then
    panel.toggle(root, only)
  end
end

function M.open(surface)
  M.panel(surface)
end

function M.goal(text)
  local root = current_root()
  if root and text and text ~= "" then
    transport.for_workspace(root):send({ kind = "goal", text = text })
    util.notify("goal recorded")
  end
end

function M.status()
  local root = current_root()
  if not root then
    return
  end
  local tr = transport.for_workspace(root)
  local engine = tr:read_json("engine.json") or panel.engine
  local counts = {}
  for name, items in pairs(store.findings) do
    if #items > 0 then
      table.insert(counts, name .. "=" .. #items)
    end
  end
  local lines = {
    "workspace: " .. root,
    "observing: " .. tostring(M.active[root] == true),
    "events sent: " .. tr.seq .. " (session " .. tr.session .. ")",
    "findings: " .. (#counts > 0 and table.concat(counts, " ") or "none"),
    "engine: " .. (engine and (engine.state .. " pid=" .. tostring(engine.pid)
      .. " model=" .. ((engine.model or {}).status or "?")) or "not running"),
    "unsaved: " .. (engine and #(engine.dirty_buffers or {}) > 0
      and table.concat(engine.dirty_buffers, " ") or "none"),
  }
  util.notify(table.concat(lines, "\n"))
end

return M
