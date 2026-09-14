-- Hand-judging harness for the chatty functions on qwen3-coder:30b. Test tooling, not the plugin:
-- the functions have no product surface yet, so nothing under nvim/ registers these commands.
--
--   :luafile ~/repos/devcompanion/testing/chatty/chatty.lua
--   :Chatty [explain|grill|plan|summary|commit]   the case under the cursor, or a visual range
--   :ChattyReport                                 judgments so far, against the bar
--
-- In a case file the function comes from the file name; changes.diff needs `summary` or `commit`.
-- In the reply float: g good · f fixable · u unusable (each asks for an optional note; <Esc> there
-- cancels the judgment) · q close without judging.
local here = vim.fn.fnamemodify(debug.getinfo(1, "S").source:sub(2), ":p:h")
local root = vim.fn.fnamemodify(here, ":h:h")
local python = root .. "/.venv/bin/python"
local script = root .. "/scripts/chatty.py"

local FUNCTIONS = { "explain", "grill", "plan", "summary", "commit" }
local BY_FILE = { ["explain.py"] = "explain", ["grill.py"] = "grill", ["plan.py"] = "plan" }
local ns = vim.api.nvim_create_namespace("chatty")

-- A case runs from its `# %% <id>` line to the next one. Returns id, first and last body row (1-based).
local function case_at(lines, row)
  local start
  for i = row, 1, -1 do
    if lines[i]:match("^# %%%%") then
      start = i
      break
    end
  end
  if not start then
    return nil
  end
  local stop = #lines
  for i = start + 1, #lines do
    if lines[i]:match("^# %%%%") then
      stop = i - 1
      break
    end
  end
  return lines[start]:match("^# %%%%%s*(%S+)"), start + 1, stop
end

local function show(run)
  local expect = run.expect or {}
  local width = math.min(96, vim.o.columns - 8)
  local lines = {}
  if run.status ~= "ok" then
    table.insert(lines, "status: " .. run.status)
  end
  vim.list_extend(lines, vim.split(run.reply or "", "\n", { plain = true }))
  if run.truncated then
    vim.list_extend(lines, { "", "[cut at the token limit]" })
  end
  local first_expect
  if #expect > 0 then
    vim.list_extend(lines, { "", string.rep("─", width) })
    first_expect = #lines
    for _, e in ipairs(expect) do
      table.insert(lines, "expected: " .. e)
    end
  end

  local buf = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
  vim.bo[buf].filetype = "markdown"
  vim.bo[buf].bufhidden = "wipe"
  vim.bo[buf].modifiable = false
  if first_expect then
    for row = first_expect - 1, #lines - 1 do
      vim.api.nvim_buf_set_extmark(buf, ns, row, 0, { end_row = row + 1, hl_group = "Comment" })
    end
  end

  local rows = 0
  for _, l in ipairs(lines) do
    rows = rows + math.max(1, math.ceil(vim.fn.strdisplaywidth(l) / width))
  end
  local height = math.min(rows, vim.o.lines - 6)
  local judgeable = run.status == "ok"
  local win = vim.api.nvim_open_win(buf, true, {
    relative = "editor",
    width = width,
    height = height,
    row = math.floor((vim.o.lines - height) / 2) - 1,
    col = math.floor((vim.o.columns - width) / 2),
    style = "minimal",
    border = "rounded",
    title = (" ◇ %s · %s "):format(run["function"], run.case),
    title_pos = "center",
    footer = judgeable and " g good · f fixable · u unusable · q close " or " q close ",
    footer_pos = "center",
  })
  vim.wo[win].wrap = true
  vim.wo[win].linebreak = true

  local function close()
    if vim.api.nvim_win_is_valid(win) then
      vim.api.nvim_win_close(win, true)
    end
  end
  local map = function(key, fn)
    vim.keymap.set("n", key, fn, { buffer = buf, nowait = true })
  end
  map("q", close)
  map("<Esc>", close)
  if not judgeable then
    return
  end
  for key, label in pairs({ g = "good", f = "fixable", u = "unusable" }) do
    map(key, function()
      vim.ui.input({ prompt = label .. " · note (optional): " }, function(note)
        if note == nil then
          return
        end
        close()
        vim.system({ python, script, "judge", run.id, label, note }, { cwd = root, text = true }, function(res)
          vim.schedule(function()
            if res.code == 0 then
              vim.notify(("judged %s · %s"):format(run.case, label))
            else
              vim.notify("Chatty: judgment not recorded: " .. (res.stderr or ""), vim.log.levels.ERROR)
            end
          end)
        end)
      end)
    end)
  end
end

-- scripts/chatty.py parses the case (`# expect:`, `# goal:`, `# path:`), so the format has one reader.
local function send(item)
  vim.notify(("asking qwen3-coder:30b · %s · %s"):format(item["function"], item.case))
  vim.system({ python, script, "ask" }, { cwd = root, stdin = vim.json.encode(item), text = true }, function(res)
    vim.schedule(function()
      local ok, run = pcall(vim.json.decode, res.stdout or "")
      if res.code ~= 0 or not ok then
        vim.notify("Chatty failed: " .. (res.stderr or ""), vim.log.levels.ERROR)
        return
      end
      show(run)
    end)
  end)
end

vim.api.nvim_create_user_command("Chatty", function(opts)
  local buf = vim.api.nvim_get_current_buf()
  local file = vim.api.nvim_buf_get_name(buf)
  local fn = opts.args ~= "" and opts.args or BY_FILE[vim.fn.fnamemodify(file, ":t")]
  if not vim.tbl_contains(FUNCTIONS, fn or "") then
    vim.notify("Chatty: name a function: " .. table.concat(FUNCTIONS, ", "), vim.log.levels.WARN)
    return
  end

  local lines, case
  if opts.range > 0 then
    lines = vim.api.nvim_buf_get_lines(buf, opts.line1 - 1, opts.line2, false)
    case = "adhoc"
  else
    local all = vim.api.nvim_buf_get_lines(buf, 0, -1, false)
    local id, from, to = case_at(all, vim.api.nvim_win_get_cursor(0)[1])
    if not id then
      vim.notify("Chatty: no `# %%` case above the cursor; select code instead", vim.log.levels.WARN)
      return
    end
    lines = vim.list_slice(all, from, to)
    case = vim.fn.fnamemodify(file, ":t:r") .. "/" .. id
  end

  local item = {
    ["function"] = fn,
    case = case,
    lines = lines,
    path = case == "adhoc" and vim.fn.fnamemodify(file, ":.") or "",
  }
  local has_goal = vim.iter(lines):any(function(l)
    return l:match("^#%s*goal:") ~= nil
  end)
  if fn == "plan" and not has_goal then
    vim.ui.input({ prompt = "goal: " }, function(goal)
      if goal and goal ~= "" then
        item.goal = goal
        send(item)
      end
    end)
    return
  end
  send(item)
end, {
  nargs = "?",
  range = true,
  complete = function()
    return FUNCTIONS
  end,
  desc = "Ask qwen3-coder:30b a chatty function and judge the reply",
})

vim.api.nvim_create_user_command("ChattyReport", function()
  local res = vim.system({ python, script, "report" }, { cwd = root, text = true }):wait()
  vim.notify(res.code == 0 and res.stdout or res.stderr)
end, { desc = "Chatty-function judgments against the bar" })
