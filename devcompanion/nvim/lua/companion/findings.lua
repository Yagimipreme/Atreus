-- Layer 3a: the findings store. Holds the last complete set the engine published, grouped by
-- surface, and the engine's last status. No windows: the panel, the info view and the
-- statusline all read from here.
--
-- findings.jsonl is rewritten whole by the engine, so loading is a replacement, never a merge:
-- a finding that stops being published has stopped being true.
--
-- What *is* decided here is what a finding means to someone coding, because every surface has
-- to agree on it: a failing test or a breaking call site is something to act on; a green test
-- run is a count, not an item.
local util = require("companion.util")
local config = require("companion.config")

local M = {}

M.SURFACES = { "callers", "errors", "docs", "roadmap" }

-- A heartbeat older than this means no engine is answering. The engine beats about once a
-- second while idle; this leaves room for a loaded machine without calling a dead engine alive
-- for long.
M.HEARTBEAT_S = 10

local function empty()
  local t = {}
  for _, name in ipairs(M.SURFACES) do
    t[name] = {}
  end
  return t
end

M.findings = empty()
M.engine = nil   -- latest engine.json, or nil when none has been read
M.observed = {}  -- root -> true while :CompanionStart is in effect; init.lua writes it

-- Without observation nothing here was read from that workspace's engine, so every surface has
-- to say "not observing" rather than describe an empty store as a state of the code.
function M.observing(root)
  return root ~= nil and M.observed[root] == true
end

-- Replace everything from one findings.jsonl payload. A malformed line is skipped rather than
-- allowed to discard the rest: half a file is still worth showing, and the engine rewrites
-- atomically so this should not happen at all.
function M.load(data)
  local by_surface = empty()
  for line in data:gmatch("[^\n]+") do
    local f = util.decode_json(line)
    if type(f) == "table" and f.surface and by_surface[f.surface] then
      table.insert(by_surface[f.surface], f)
    end
  end
  M.findings = by_surface
  return by_surface
end

function M.set_engine(data)
  M.engine = data
end

function M.count()
  local n = 0
  for _, items in pairs(M.findings) do
    n = n + #items
  end
  return n
end

function M.clear()
  M.findings = empty()
end

-- Stale means: this claim was derived from bytes that are no longer what the buffer holds.
-- Recomputed live rather than trusted from the file, because the buffer moves on between
-- engine writes and a claim shown as current when it is not is the one failure that matters.
-- An `outdated` basis is the engine saying the same about inputs it has already seen change.
function M.is_stale(root, finding)
  if finding.basis == "outdated" then
    return true
  end
  for rel, sha in pairs(finding.depends_on or {}) do
    local buf = vim.fn.bufnr(root .. "/" .. rel)
    if buf ~= -1 and vim.api.nvim_buf_is_loaded(buf) and util.buffer_sha(buf) ~= sha then
      return true
    end
  end
  return false
end

-- A test run's status. Findings published before `outcome` existed carry it only in prose.
local function test_status(f)
  return (f.outcome or {}).status or (f.consequence or ""):match("^(%w+):")
end

local function passed_count(f)
  local counts = (f.outcome or {}).counts
  if counts then
    return counts.passed or 0
  end
  return tonumber((f.consequence or ""):match("(%d+) passed")) or 0
end

local function actionable(f)
  return f.kind ~= "test_result" or test_status(f) == "failed"
end

-- How directly a finding says the code is wrong. Lower sorts first.
local function rank(f)
  if f.basis == "inferred" then
    return 4
  end
  return ({ test_result = 1, caller_affected = 2, diagnostic_context = 3 })[f.kind] or 5
end

-- The rows worth showing, most useful first: fresh before stale, then by rank, then by place in
-- the code so the order does not shuffle between redraws. Each entry is { finding, stale }.
function M.issues(root, only)
  local out = {}
  for _, name in ipairs(M.SURFACES) do
    if only == nil or only == name then
      for _, f in ipairs(M.findings[name] or {}) do
        if actionable(f) then
          local stale = M.is_stale(root, f)
          if not (stale and config.options.ui.stale == "hide") then
            table.insert(out, { finding = f, stale = stale })
          end
        end
      end
    end
  end
  table.sort(out, function(a, b)
    if a.stale ~= b.stale then
      return not a.stale
    end
    local ra, rb = rank(a.finding), rank(b.finding)
    if ra ~= rb then
      return ra < rb
    end
    local la, lb = a.finding.location or {}, b.finding.location or {}
    if (la.path or "") ~= (lb.path or "") then
      return (la.path or "") < (lb.path or "")
    end
    if (la.line or 0) ~= (lb.line or 0) then
      return (la.line or 0) < (lb.line or 0)
    end
    return (a.finding.id or "") < (b.finding.id or "")
  end)
  return out
end

-- Test runs that are not failing, as one summary: { passed = n, other = status|nil, stale },
-- or nil when there were none.
function M.tests(root)
  local summary
  for _, f in ipairs(M.findings.errors or {}) do
    if f.kind == "test_result" and not actionable(f) then
      summary = summary or { passed = 0, stale = false }
      if test_status(f) == "passed" then
        summary.passed = summary.passed + passed_count(f)
      else
        summary.other = summary.other or test_status(f)
      end
      summary.stale = summary.stale or M.is_stale(root, f)
    end
  end
  return summary
end

-- Is an engine answering? No engine.json and a heartbeat that stopped are the same answer.
function M.engine_alive()
  local e = M.engine
  return e ~= nil and e.heartbeat_ts ~= nil and os.time() - e.heartbeat_ts < M.HEARTBEAT_S
end

-- Has the engine read the content in this buffer? "current", "behind", or nil when it holds no
-- opinion about the path at all -- not every file is in the analysis manifest, and that is fine.
function M.sync(root, buf)
  local e = M.engine
  if not e or not vim.api.nvim_buf_is_valid(buf) or vim.bo[buf].buftype ~= "" then
    return nil
  end
  local name = vim.api.nvim_buf_get_name(buf)
  local rev = name ~= "" and (e.revisions or {})[util.relative(root, name)] or nil
  if not rev then
    return nil
  end
  return rev.sha == util.buffer_sha(buf) and "current" or "behind"
end

-- Still working on something the developer would be waiting for.
function M.busy(root, buf)
  if not M.engine_alive() then
    return false
  end
  local e = M.engine
  return e.state == "working" or (e.pending_tasks or 0) > 0 or M.sync(root, buf) == "behind"
end

return M
