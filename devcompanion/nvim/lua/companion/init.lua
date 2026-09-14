-- Public module. Wires config + collect + transport + findings + the views, and owns nothing
-- else. Everything a user calls goes through here.
local config = require("companion.config")
local util = require("companion.util")
local transport = require("companion.transport")
local collect = require("companion.collect")
local store = require("companion.findings")
local panel = require("companion.panel")

local M = {}

M.active = store.observed -- root -> true; shared, so the views can tell observed from empty

function M.setup(opts)
  config.setup(opts)
  return M
end

-- The workspace a command is about. A real file names it. Anything else -- the panel itself, a
-- terminal, a file tree -- does not, and with a pinned panel the cursor is often in one; then the
-- panel's own workspace, or the one already observed, stands in.
local function current_root()
  local buf = vim.api.nvim_get_current_buf()
  local root = vim.bo[buf].buftype == "" and util.workspace_root(vim.api.nvim_buf_get_name(buf)) or nil
  root = root or panel.root() or next(M.active)
  if not root then
    util.notify("open a file in the workspace first", vim.log.levels.WARN)
  end
  return root
end

-- The store changed. The statusline and an open panel describe it; neither opens anything.
local function changed(root)
  panel.refresh(root)
  vim.cmd("redrawstatus")
end

function M.start(root)
  root = root or current_root()
  if not root or M.active[root] then
    return
  end
  M.active[root] = true
  local tr = transport.for_workspace(root)
  collect.start(root)

  -- Findings: the engine rewrites the file, we reload and redraw whatever shows them.
  tr:watch("findings.jsonl", function(data)
    store.load(data)
    changed(root)
  end)

  -- Engine liveness. Absent is a state to show, not an error.
  tr:watch("engine.json", function(data)
    store.set_engine(util.decode_json(data))
    changed(root)
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

  -- An open panel follows the developer: a save can retire a stale mark, a pinned panel's notice
  -- is about whichever buffer they moved to, and a resize moves its right edge. Free when closed.
  local group = vim.api.nvim_create_augroup("companion:panel:" .. root, { clear = true })
  vim.api.nvim_create_autocmd({ "BufEnter", "BufWritePost", "VimResized" }, {
    group = group,
    callback = function()
      panel.refresh(root)
    end,
  })
  -- A pinned panel opens the problem on the line the cursor is on. The panel does nothing unless
  -- it is open and the cursor is elsewhere, so this costs one check per move while coding.
  vim.api.nvim_create_autocmd("CursorMoved", {
    group = group,
    callback = function(a)
      if panel.is_open() then
        panel.follow(root, a.buf, vim.api.nvim_win_get_cursor(0)[1])
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
  vim.cmd("redrawstatus")
  util.notify("stopped observing " .. root)
end

-- The panel. `only` filters it to one surface, which is all :CompanionErrors and
-- :CompanionCallers are.
function M.panel(only)
  local root = current_root()
  if root then
    panel.open(root, only)
  end
end

-- Open, move into, or close the panel. An open panel already knows its workspace, which matters
-- because from inside it the current buffer is the panel and has no workspace at all.
function M.toggle(only)
  if panel.is_open() then
    return panel.toggle(nil, only)
  end
  local root = current_root()
  if root then
    panel.open(root, only)
  end
end

function M.pin()
  if panel.is_open() then
    return panel.set_pinned()
  end
  local root = current_root()
  if root then
    panel.set_pinned(nil, root)
  end
end

function M.goal(text)
  local root = current_root()
  if root and text and text ~= "" then
    transport.for_workspace(root):send({ kind = "goal", text = text })
    util.notify("goal recorded")
  end
end

-- Engine and adapter internals, on request. Read fresh: this is the view someone opens when
-- they suspect the cached picture is wrong.
function M.info()
  local root = current_root()
  if not root then
    return
  end
  local tr = transport.for_workspace(root)
  local fresh = tr:read_json("engine.json")
  if fresh then
    store.set_engine(fresh)
  end
  require("companion.info").open(root, {
    observing = M.active[root] == true, seq = tr.seq, session = tr.session,
  })
end

-- ---------------------------------------------------------------- statusline

-- For a statusline component. Empty when nothing is observed, so it can be left in a
-- statusline permanently at no cost:
--   ◉ 5    five things to act on        ◉      nothing to act on
--   ◉ 5 …  the engine is still catching up with what is in front of you
--   ◌      observing, but no engine is answering
function M.statusline()
  local root = next(M.active)
  if not root then
    return ""
  end
  if not store.engine_alive() then
    return "◌"
  end
  local n = #store.issues(root)
  local text = n > 0 and ("◉ " .. n) or "◉"
  if store.busy(root, vim.api.nvim_get_current_buf()) then
    text = text .. " …"
  end
  return text
end

-- The highlight group that goes with statusline(), for a component's colour.
function M.statusline_hl()
  local root = next(M.active)
  if not root or not store.engine_alive() then
    return "CompanionMuted"
  end
  return #store.issues(root) > 0 and "CompanionError" or "CompanionOk"
end

return M
