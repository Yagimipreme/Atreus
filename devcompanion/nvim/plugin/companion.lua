-- Entry point. Neovim runs every file under plugin/ once at startup, before your config's
-- own code. Keep this file tiny: it only registers the user commands, so that requiring the
-- real modules is deferred until something is actually used (startup stays fast).
--
-- The guard below is the standard idiom: sourcing this file twice must be harmless.
if vim.g.loaded_companion then
  return
end
vim.g.loaded_companion = true

-- `vim.api.nvim_create_user_command(name, fn, opts)` defines :CompanionStart etc.
-- `require("companion")` is lazy here: the module is only loaded when a command runs.
local function cmd(name, fn, opts)
  vim.api.nvim_create_user_command(name, fn, opts or {})
end

cmd("CompanionStart", function()
  require("companion").start()
end, { desc = "Start observing this workspace" })

cmd("CompanionStop", function()
  require("companion").stop()
end, { desc = "Stop observing" })

-- One panel, opened on request and never on its own. The filtered commands are the same panel
-- with one surface shown, so there is only ever one place to look.
cmd("CompanionPanel", function()
  require("companion").toggle()
end, { desc = "Toggle the companion panel" })

-- Pinned: the panel stays open when the cursor leaves it and after a jump, and follows the code.
cmd("CompanionPanelPin", function()
  require("companion").pin()
end, { desc = "Pin or unpin the companion panel" })

cmd("CompanionErrors", function()
  require("companion").panel("errors")
end, { desc = "Open the panel, errors only" })

cmd("CompanionCallers", function()
  require("companion").panel("callers")
end, { desc = "Open the panel, affected callers only" })

-- Engine and adapter internals. Kept out of the panel on purpose.
cmd("CompanionInfo", function()
  require("companion").info()
end, { desc = "Show engine and adapter internals" })

cmd("CompanionStatus", function()
  require("companion").info()
end, { desc = "Same as :CompanionInfo" })

cmd("CompanionGoal", function(args)
  require("companion").goal(args.args)
end, { nargs = "*", desc = "State a short goal for the current work" })
