-- Layer 2 (written before layer 1 because both collect and the panel depend on it):
-- the ONLY module that knows how the engine is reached. Swapping files for a socket
-- means rewriting this file and nothing else.
--
-- Responsibilities:
--   send(event)          append one JSON line to inbox.jsonl, never blocking the UI
--   watch(name, cb)      call cb(lines) whenever a file the engine writes changes
--   read_json(name)      read one JSON object file (engine.json), or nil
local util = require("companion.util")
local config = require("companion.config")

local M = {}

-- One transport instance per workspace root.
local instances = {}

local Transport = {}
Transport.__index = Transport

function M.for_workspace(root)
  if instances[root] then
    return instances[root]
  end
  local self = setmetatable({
    root = root,
    dir = root .. "/" .. config.options.transport.dir,
    seq = 0,
    session = util.session_id(),
    watchers = {},   -- name -> { handle, callback, last_mtime }
    queue = {},      -- pending outgoing lines, flushed asynchronously
    flushing = false,
  }, Transport)
  vim.fn.mkdir(self.dir, "p")
  instances[root] = self
  return self
end

-- Fill in the envelope fields the contract requires on every event.
function Transport:stamp(event)
  self.seq = self.seq + 1
  event.schema_version = 2
  event.seq = self.seq
  local sec, usec = vim.uv.gettimeofday()
  event.ts = sec + usec / 1e6 -- unix seconds, per the contract (hrtime is since boot)
  event.workspace = self.root
  event.session = self.session
  event.source = "nvim"   -- who produced it; the log is read by people, not only by the engine
  return event
end

function Transport:send(event)
  self:stamp(event)
  table.insert(self.queue, vim.json.encode(event))
  self:flush()
  return event.seq
end

-- Asynchronous append. vim.uv.fs_open/fs_write take callbacks, so the UI thread never waits
-- on the filesystem. Lines are written in order because we only ever have one write in flight.
function Transport:flush()
  if self.flushing or #self.queue == 0 then
    return
  end
  self.flushing = true
  local chunk = table.concat(self.queue, "\n") .. "\n"
  self.queue = {}
  local path = self.dir .. "/inbox.jsonl"
  vim.uv.fs_open(path, "a", 420, function(err, fd) -- 420 = 0644
    if err or not fd then
      self.flushing = false
      return
    end
    vim.uv.fs_write(fd, chunk, -1, function()
      vim.uv.fs_close(fd, function()
        self.flushing = false
        if #self.queue > 0 then
          vim.schedule(function()
            self:flush()
          end)
        end
      end)
    end)
  end)
end

-- The exception to the "never block the UI thread" rule, and the only one: on VimLeavePre the
-- event loop stops before any libuv callback would run, so an async write is simply lost.
function Transport:send_sync(event)
  self:stamp(event)
  local f = io.open(self.dir .. "/inbox.jsonl", "a")
  if not f then
    return nil
  end
  f:write(vim.json.encode(event) .. "\n")
  f:close()
  return event.seq
end

-- Watch a file the engine rewrites. Polling by mtime is deliberate: fs_event on a renamed
-- file is unreliable across filesystems, and once a second is cheap.
function Transport:watch(name, callback)
  if self.watchers[name] then
    return
  end
  local path = self.dir .. "/" .. name
  local timer = vim.uv.new_timer()
  local last = 0
  timer:start(0, config.options.transport.poll_ms, function()
    vim.uv.fs_stat(path, function(err, stat)
      if err or not stat then
        return
      end
      local mtime = stat.mtime.sec * 1e9 + stat.mtime.nsec
      if mtime == last then
        return
      end
      last = mtime
      vim.uv.fs_open(path, "r", 420, function(e2, fd)
        if e2 or not fd then
          return
        end
        vim.uv.fs_read(fd, stat.size, 0, function(e3, data)
          vim.uv.fs_close(fd, function() end)
          if e3 or not data then
            return
          end
          vim.schedule(function()
            callback(data)
          end)
        end)
      end)
    end)
  end)
  self.watchers[name] = timer
end

function Transport:unwatch_all()
  for name, timer in pairs(self.watchers) do
    timer:stop()
    timer:close()
    self.watchers[name] = nil
  end
end

-- Synchronous small read, used only for engine.json on an explicit :CompanionStatus.
function Transport:read_json(name)
  local path = self.dir .. "/" .. name
  local f = io.open(path, "r")
  if not f then
    return nil
  end
  local data = f:read("*a")
  f:close()
  return util.decode_json(data)
end

return M
