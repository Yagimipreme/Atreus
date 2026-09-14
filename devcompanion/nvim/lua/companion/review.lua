-- Deep work for checked fixes: one fix's diff in a float of its own, and the decision.
--
-- A fix was checked against exact bytes (`fix.depends_on`). Applying compares them with the
-- buffer as it is now and refuses when anything moved: a patch applied to code it was not checked
-- against is the one thing here that could corrupt code. Applying edits the buffer, never the
-- file -- the developer saves, and `u` undoes it (docs/edit-actions.md). The engine hears what
-- happened as an `action_result` and never writes a developer file.
--
-- `a` apply · `r` reject · `n` next · `q` close. No key for handing the fix to an agent: that
-- does not exist yet.
local util = require("companion.util")
local float = require("companion.float")
local store = require("companion.findings")
local transport = require("companion.transport")

local M = {}

local state = { buf = nil, win = nil, root = nil, list = {}, index = 1, origin = nil }

local function buffer_for(root, rel)
  local abs = root .. "/" .. rel
  local buf = vim.fn.bufnr(abs)
  if buf == -1 then
    buf = vim.fn.bufadd(abs)
  end
  if not vim.api.nvim_buf_is_loaded(buf) then
    vim.fn.bufload(buf)
  end
  return buf
end

-- Whether every input still holds the bytes the fix was checked on; if not, the path that moved.
function M.fresh(root, fix)
  for rel, sha in pairs(fix.depends_on or {}) do
    if util.buffer_sha(buffer_for(root, rel)) ~= sha then
      return false, rel
    end
  end
  return true
end

local function lines_of(text, buf)
  local out = vim.split(text, "\n", { plain = true })
  if out[#out] == "" then
    table.remove(out)
  end
  if vim.bo[buf].fileformat == "dos" then
    for i, l in ipairs(out) do
      out[i] = (l:gsub("\r$", ""))
    end
  end
  return out
end

local function report(root, finding, status, path)
  transport.for_workspace(root):send({ kind = "action_result", action = "fix", finding_id = finding.id,
                                       fix_id = (finding.fix or {}).id, status = status, path = path })
end

-- Apply a finding's fix to its buffer: freshness first, then the edits bottom-up, so earlier line
-- numbers stay valid, as one undo step. Returns whether it applied, and the path.
function M.apply(root, finding)
  local fix = finding.fix
  local ok, moved = M.fresh(root, fix)
  if not ok then
    report(root, finding, "refused_stale", moved)
    return false, moved
  end
  local rel = next(fix.depends_on) -- a fix edits one file; the gate checked it against the whole project
  local buf = buffer_for(root, rel)
  local edits = vim.deepcopy(fix.edits)
  table.sort(edits, function(a, b) return a.line > b.line end)
  for i, e in ipairs(edits) do
    if i > 1 then
      vim.api.nvim_buf_call(buf, function() pcall(vim.cmd, "undojoin") end)
    end
    vim.api.nvim_buf_set_lines(buf, e.line - 1, e.end_line - 1, true, lines_of(e.text, buf))
  end
  report(root, finding, "applied", rel)
  return true, rel
end

-- ---------------------------------------------------------------- the float

local function close()
  local win = state.win
  state.win = nil
  if win and vim.api.nvim_win_is_valid(win) then
    vim.api.nvim_win_close(win, true)
  end
  if state.origin and vim.api.nvim_win_is_valid(state.origin) then
    vim.api.nvim_set_current_win(state.origin)
  end
end

local function after(root)
  require("companion.panel").refresh(root)
  vim.cmd("redrawstatus")
end

local function chunks_width(chunks)
  local n = 0
  for _, part in ipairs(chunks) do
    n = n + float.width(part[1])
  end
  return n
end

local function draw()
  local f = state.list[state.index]
  local fix, loc = f.fix, f.location or {}
  local c = float.canvas()
  local resolved = store.resolved_by(state.root, f)
  for _, g in ipairs(#resolved > 0 and resolved or { f }) do
    local line = (g.location or {}).line
    c:add({ { " " }, { line and (line .. "  ") or "", "CompanionLocation" }, { g.title or "" } })
  end
  for _, w in ipairs(fix.warnings or {}) do
    c:add({ { " " }, { "new warning  ", "CompanionWarn" }, { w, "CompanionMuted" } })
  end
  c:gap()
  for _, l in ipairs(vim.split(fix.diff or "", "\n", { plain = true })) do
    if l:match("^@@") then
      c:add({ { " " }, { l, "CompanionMuted" } })
    elseif l:match("^%+%+%+ ") or l:match("^%-%-%- ") or l == "" then
      -- the file is named in the title
    elseif l:sub(1, 1) == "+" then
      c:add({ { " " }, { l, "CompanionExpected" } })
    elseif l:sub(1, 1) == "-" then
      c:add({ { " " }, { l, "CompanionGot" } })
    else
      c:add({ { " " }, { l } })
    end
  end
  c:trim()

  local warned = #(fix.warnings or {})
  local title = { { " ✓", "CompanionOk" }, { " fix checked", "CompanionTitle" } }
  if warned > 0 then
    table.insert(title, { " · " .. warned .. (warned == 1 and " new warning" or " new warnings"), "CompanionWarn" })
  end
  local covers = fix.covers or {}
  if #covers > 1 then
    table.insert(title, { " · " .. #covers .. " problems", "CompanionMuted" })
  end
  local lines = #covers > 1 and table.concat(covers, ", ") or (loc.line and tostring(loc.line) or nil)
  local where = vim.fn.fnamemodify(loc.path or "", ":t") .. (lines and (":" .. lines) or "")
  table.insert(title, { " · " .. where .. " ", "CompanionMuted" })
  local keys = { { "a", "apply" }, { "r", "reject" } }
  if #state.list > 1 then
    table.insert(keys, { "n", "next" })
  end
  table.insert(keys, { "q", "close" })
  local footer = {}
  for _, k in ipairs(keys) do
    table.insert(footer, { " " .. k[1], "CompanionKey" })
    table.insert(footer, { " " .. k[2] .. " ", "CompanionMuted" })
  end

  local width = math.max(chunks_width(title), chunks_width(footer)) + 2
  for _, l in ipairs(c.lines) do
    width = math.max(width, float.width(l) + 1)
  end
  width = math.min(width, vim.o.columns - 8)
  local height = math.max(1, math.min(#c.lines, vim.o.lines - vim.o.cmdheight - 6))
  float.draw(state.buf, c)
  local cfg = {
    relative = "editor",
    row = math.max(0, math.floor((vim.o.lines - height) / 2) - 1),
    col = math.max(0, math.floor((vim.o.columns - width) / 2)),
    width = width,
    height = height,
    title = title,
    title_pos = "left",
    footer = footer,
    footer_pos = "right",
  }
  if state.win and vim.api.nvim_win_is_valid(state.win) then
    vim.api.nvim_win_set_config(state.win, cfg)
  else
    state.win = float.open(state.buf, cfg)
    vim.wo[state.win].winhighlight = "FloatBorder:CompanionBorderActive"
  end
  vim.api.nvim_win_set_cursor(state.win, { 1, 0 })
end

function M.accept()
  local f, root = state.list[state.index], state.root
  close()
  local ok, path = M.apply(root, f)
  local name = vim.fn.fnamemodify(path or "", ":t")
  if ok then
    util.notify("fix applied to " .. name .. " · unsaved · u undoes it")
  else
    util.notify(name .. " changed since the fix was checked · not applied", vim.log.levels.WARN)
  end
  after(root)
end

function M.reject()
  local f, root = state.list[state.index], state.root
  store.decline(f)
  report(root, f, "declined", next(f.fix.depends_on or {}))
  table.remove(state.list, state.index)
  if #state.list == 0 then
    close()
  else
    state.index = math.min(state.index, #state.list)
    draw()
  end
  after(root)
end

function M.next()
  if #state.list > 1 then
    state.index = state.index % #state.list + 1
    draw()
  end
end

local function ensure_buffer()
  if state.buf and vim.api.nvim_buf_is_valid(state.buf) then
    return state.buf
  end
  state.buf = float.scratch("companion://fix")
  local function map(lhs, fn, desc)
    vim.keymap.set("n", lhs, fn, { buffer = state.buf, nowait = true, desc = "companion: " .. desc })
  end
  map("a", M.accept, "apply the fix to the buffer")
  map("r", M.reject, "reject the fix")
  map("n", M.next, "next fix")
  map("q", close, "close")
  map("<Esc>", close, "close")
  return state.buf
end

-- Open on `list[index]`. `origin` is the code window the cursor returns to.
function M.open(root, list, index, origin)
  if #list == 0 then
    return
  end
  state.root, state.list = root, list
  state.index = math.max(1, math.min(index or 1, #list))
  state.origin = origin or vim.api.nvim_get_current_win()
  ensure_buffer()
  draw()
end

return M
