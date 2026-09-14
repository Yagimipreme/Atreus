"""Exercise the real CLI, the real engine and a real headless Neovim in disposable Git projects.

Run: .venv/bin/python scripts/check-workflow.py
Leaves boards, panel dumps, logs and a Markdown report in the printed temporary
directory. Does not change application code and does not call a model.

Everything here goes through an actual subprocess: `companion ingest`, `companion
watch`, `companion replay`, `pytest`, and `nvim --headless` running the real plugin.
The point is to catch what unit tests cannot — that the two halves agree about
hashes, about which bytes are current, and about what the pane ends up drawing.

`gap()` marks a capability that is known to be missing and is reproduced on purpose;
a GAP CONFIRMED row is not a passing acceptance criterion. There are none at present.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

PROJECT = Path(__file__).resolve().parents[1]
OUT = Path(tempfile.mkdtemp(prefix="devcompanion-check-"))
ENV = dict(os.environ, PYTHONPATH=str(PROJECT / "src"))
ROWS = []
BASE = "def add(a, b):\n    return a + b\n"
BROKEN = "def add(a, b, carry):\n    return a + b + carry\n"
CLIENT = "from calc import add\n\ndef total():\n    return add(1, 2)\n"
TEST = "import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parents[1]))\nfrom calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"


def run(args, cwd=PROJECT):
    p = subprocess.run([str(a) for a in args], cwd=cwd, env=ENV,
                       capture_output=True, text=True, timeout=30)
    if p.returncode:
        raise RuntimeError(f"{args}: {p.stdout}\n{p.stderr}")
    return p.stdout + p.stderr


def fixture(name):
    root = OUT / name
    (root / "tests").mkdir(parents=True)
    (root / "calc.py").write_text(BASE)
    (root / "client.py").write_text(CLIENT)
    (root / "tests/test_calc.py").write_text(TEST)
    run(["git", "init", "-q"], root)
    run(["git", "add", "."], root)
    run(["git", "-c", "user.name=Workflow Test", "-c", "user.email=test@localhost",
         "commit", "-qm", "baseline"], root)
    return root


def command(root, *args):
    return [sys.executable, "-m", "devcompanion.cli", "--root", root, *args]


def ingest(root, tag, *paths):
    log = run(command(root, "ingest", *[root / p for p in paths]))
    (OUT / f"{tag}.log").write_text(log)
    capture(root, tag)
    return json.loads(log.splitlines()[-1])


def capture(root, tag):
    shutil.copyfile(root / ".companion/board.md", OUT / f"{tag}-board.md")
    (OUT / f"{tag}-state.json").write_text(json.dumps(records(root), indent=2))


def records(root):
    path = root / ".companion/state.json"
    return json.loads(path.read_text()) if path.exists() else {}


def check(name, condition, detail):
    ROWS.append(("PASS" if condition else "FAIL", name, detail))
    print(f"{ROWS[-1][0]}: {name} — {detail}", flush=True)


def gap(name, condition, detail):
    ROWS.append(("GAP CONFIRMED" if condition else "OBSERVATION", name, detail))
    print(f"{ROWS[-1][0]}: {name} — {detail}", flush=True)


def poll(fn, timeout=12):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if fn():
                return True
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(.05)
    return False


def signature(root):
    return records(root).get("signature_change:calc.py:add", {})


def run_nvim(tag, body, root=None, env=None, timeout=25):
    """Run one headless Neovim scenario against the real plugin. `body` is Lua; the workspace
    is in vim.env.COMPANION_TEST_ROOT. Fails loudly on a Lua error rather than returning
    something that merely looks empty."""
    lua = OUT / f"{tag}.lua"
    lua.write_text(body)
    args = ["nvim", "--headless", "-u", "NONE", "-n", "-i", "NONE",
            "--cmd", f"set rtp+={PROJECT}/nvim",
            "-c", "runtime plugin/companion.lua", "-c", f"luafile {lua}", "-c", "qa!"]
    p = subprocess.run(args, env=dict(ENV, COMPANION_TEST_ROOT=str(root or ""), **(env or {})),
                       capture_output=True, text=True, timeout=timeout)
    (OUT / f"{tag}.log").write_text(p.stdout + p.stderr)
    if p.returncode or "E5113:" in p.stderr or "E5108:" in p.stderr:
        raise RuntimeError(f"{tag}: {p.stderr}")
    return p.stdout + p.stderr


EDIT = '''local root = vim.env.COMPANION_TEST_ROOT
local c = require("companion")
c.setup({debounce={text=100, diagnostics=100, cursor=100}, transport={poll_ms=100}})
vim.cmd("filetype on")   -- -u NONE starts with detection off; the adapter reports what it sees
vim.cmd("edit " .. vim.fn.fnameescape(root .. "/calc.py"))
c.start(root)
vim.api.nvim_buf_set_lines(0,0,-1,false,{"def add(a, b, carry):", "    return a + b + carry"})
vim.cmd("doautocmd TextChanged")
vim.wait(600, function() return false end)
'''


# Open the panel over whatever the engine has already published, drive it the way a developer
# would, and dump what it drew at each step. It must render from the files alone: this Neovim
# edits nothing.
PANEL = r"""local root = vim.env.COMPANION_TEST_ROOT
local c = require("companion")
c.setup({transport={poll_ms=50}, ui={width=70}})
vim.cmd("filetype on")
vim.cmd("edit " .. vim.fn.fnameescape(root .. "/client.py"))
local code = vim.api.nvim_get_current_win()
local windows_at_start = #vim.api.nvim_tabpage_list_wins(0)
-- Before :CompanionStart the panel must say the workspace is not observed, not that an engine
-- stopped or that there are no problems: nothing in this editor has read what an engine wrote.
vim.cmd("CompanionPanel")
local unobserved = vim.api.nvim_buf_get_lines(vim.fn.bufnr("companion://panel"), 0, -1, false)
vim.cmd("normal q")
c.start(root)
vim.wait(4000, function()
  local store = require("companion.findings")
  return store.count() > 0 and store.engine ~= nil
end, 50)
local panel = require("companion.panel")
local function dump(name)
  local buf = vim.fn.bufnr(name)
  return buf ~= -1 and vim.api.nvim_buf_get_lines(buf, 0, -1, false) or {}
end
local unasked = #vim.api.nvim_tabpage_list_wins(0) == windows_at_start

vim.cmd("CompanionPanel")
local win = vim.api.nvim_get_current_win()
local opened = { open = panel.is_open(), focused = win ~= code,
                 float = vim.api.nvim_win_get_config(win).relative ~= "" }
vim.fn.writefile(dump("companion://panel"), vim.env.PANEL_OUT)
local statusline = c.statusline()
vim.cmd([[execute "normal \<CR>"]])
vim.fn.writefile(dump("companion://panel"), vim.env.PANEL_DETAIL)
vim.cmd("normal d")
vim.fn.writefile(dump("companion://panel"), vim.env.PANEL_RAW)
vim.cmd("normal q")
local closed = { closed = not panel.is_open(), back = vim.api.nvim_get_current_win() == code }
vim.cmd("CompanionPanel")
vim.cmd("CompanionPanel")
closed.toggled = not panel.is_open()
vim.cmd("CompanionInfo")
vim.fn.writefile(dump("companion://info"), vim.env.PANEL_INFO)
require("companion.info").close()

-- Pinned: opened from the code window without taking the cursor, entered on request, and still
-- there after the cursor leaves it and after a jump.
vim.api.nvim_set_current_win(code)
vim.cmd("CompanionPanelPin")
local pinned = { opened = panel.is_open(), stayed_in_code = vim.api.nvim_get_current_win() == code }
vim.cmd("CompanionPanel")
pinned.entered = vim.api.nvim_get_current_win() ~= code
-- From inside the panel the current buffer is companion://panel. It once resolved to a workspace
-- called "companion:/", which :CompanionStart then observed instead of the real one.
vim.cmd("CompanionStart")
pinned.no_pseudo_root = #vim.tbl_filter(function(r) return r ~= root end, vim.tbl_keys(c.active)) == 0
vim.api.nvim_set_current_win(code)
vim.wait(100, function() return false end)   -- the scheduled WinLeave handler runs here
pinned.survived_leaving = panel.is_open()
vim.cmd("CompanionPanel")
panel.jump()
vim.wait(100, function() return false end)
pinned.survived_jump = panel.is_open() and vim.api.nvim_get_current_win() ~= vim.fn.win_getid(vim.fn.bufwinnr("companion://panel"))
-- Linked to the code. client.py:4 is still open from the ↵ above. With the panel pinned and the
-- cursor in the code, the problem on the cursor's line -- tests/test_calc.py:7 -- opens in the
-- panel while the cursor stays put, and moving off puts back what was open before. Called
-- directly: a cursor moved by a script raises no CursorMoved.
local client = vim.fn.bufnr(root .. "/client.py")
local tests = vim.fn.bufadd(root .. "/tests/test_calc.py")
vim.fn.bufload(tests)
local function panel_has(text)
  return table.concat(dump("companion://panel"), "\n"):find(text, 1, true) ~= nil
end
panel.follow(root, tests, 7)
pinned.follow_opened = panel_has("assert add(1, 2) == 3") and not panel_has("return add(1, 2)")
  and vim.api.nvim_buf_get_name(0):sub(-9) == "client.py"
panel.follow(root, tests, 1)
pinned.follow_closed = not panel_has("assert add(1, 2) == 3") and panel_has("return add(1, 2)")
-- The other way: the problem selected in the panel is marked in the code, the cursor is hidden
-- while the panel has focus, and leaving the panel clears the mark and restores the cursor.
local guicursor = vim.o.guicursor
local source_ns = vim.api.nvim_get_namespaces()["companion.source"]
vim.cmd("CompanionPanel")
pinned.source_marked = #vim.api.nvim_buf_get_extmarks(client, source_ns, 0, -1, {}) > 0
pinned.cursor_hidden = vim.o.guicursor:find("CompanionHiddenCursor", 1, true) ~= nil
vim.api.nvim_set_current_win(code)
vim.wait(100, function() return false end)
pinned.source_cleared = #vim.api.nvim_buf_get_extmarks(client, source_ns, 0, -1, {}) == 0
pinned.cursor_restored = vim.o.guicursor == guicursor
vim.cmd("CompanionPanelPin")
pinned.unstick_closed = not panel.is_open()

vim.fn.writefile({ vim.json.encode({
  unasked = unasked, opened = opened, closed = closed, statusline = statusline, pinned = pinned,
  unobserved = unobserved,
}) }, vim.env.PANEL_STATE)
c.stop(root)
"""

# Start, edit, then quit the way a developer quits: without saving and without stopping first.
SESSION_END = r"""local root = vim.env.COMPANION_TEST_ROOT
local c = require("companion")
c.setup({debounce={text=100}, transport={poll_ms=100}})
vim.cmd("filetype on")
vim.cmd("edit " .. vim.fn.fnameescape(root .. "/client.py"))
c.start(root)
vim.api.nvim_buf_set_lines(0, 0, 0, false, {"# scratch"})
vim.cmd("doautocmd TextChanged")
vim.wait(600, function() return false end)
"""


# A buffer that was already open — and already modified — when observation started must reach
# the engine without waiting for the next keystroke.
ANNOUNCE = r"""local root = vim.env.COMPANION_TEST_ROOT
local c = require("companion")
c.setup({debounce={text=100}, transport={poll_ms=100}})
vim.cmd("filetype on")
vim.cmd("edit " .. vim.fn.fnameescape(root .. "/calc.py"))
vim.api.nvim_buf_set_lines(0, 0, -1, false, {"def add(a, b, carry):", "    return a + b + carry"})
vim.cmd("split " .. vim.fn.fnameescape(root .. "/client.py"))
vim.cmd("edit /tmp")                       -- a directory buffer, which must be ignored
c.start(root)                              -- only now does the adapter begin observing
vim.wait(900, function() return false end)
c.stop(root)
"""


# Driven after the watcher has been stopped and restarted against the same workspace, to prove
# the restart is a resume and not a re-observation gap: a keystroke that happens after the
# engine comes back up must still reach it.
RESTART_EDIT = r"""local root = vim.env.COMPANION_TEST_ROOT
local c = require("companion")
c.setup({debounce={text=100}, transport={poll_ms=100}})
vim.cmd("filetype on")
vim.cmd("edit " .. vim.fn.fnameescape(root .. "/calc.py"))
c.start(root)
vim.api.nvim_buf_set_lines(0,0,-1,false,{"def add(a, b, carry, extra):", "    return a + b + carry + extra"})
vim.cmd("doautocmd TextChanged")
vim.wait(600, function() return false end)
vim.cmd("write")
vim.wait(700, function() return false end)
c.stop(root)
"""


def check_announce_on_start(root):
    run_nvim("nvim-announce", ANNOUNCE, root)
    inbox = [json.loads(l) for l in (root / ".companion/inbox.jsonl").read_text().splitlines()]
    announced = {e["path"]: e for e in inbox}
    check("Buffers open before :CompanionStart are announced",
          announced.get("calc.py", {}).get("dirty") is True
          and announced.get("client.py", {}).get("dirty") is False
          and not any(p.startswith("/") for p in announced),
          f"announced {sorted(announced)}; the modified one is sent as an unsaved buffer, the "
          f"clean one seeds the baseline, and buffers outside the workspace are skipped")


# A language server message is routinely several lines. Neovim refuses to set a buffer line
# containing a newline, so an unflattened field does not render badly -- it raises inside the
# transport callback and the pane dies on every republish. This is that case, end to end.
MULTILINE_DIAG = r"""local root = vim.env.COMPANION_TEST_ROOT
local c = require("companion")
c.setup({debounce={text=100, diagnostics=100}, transport={poll_ms=50}})
vim.cmd("filetype on")
vim.cmd("edit " .. vim.fn.fnameescape(root .. "/client.py"))
c.start(root)
local ns = vim.api.nvim_create_namespace("fake-lsp")
-- One mistake, reported twice, the way basedpyright reports `add(1, 2)` against a changed add():
-- a call-level message several lines long, and an argument-level one inside its range.
vim.diagnostic.set(ns, 0, { {
  lnum = 3, col = 10, end_lnum = 3, end_col = 19,
  severity = vim.diagnostic.severity.ERROR,
  message = 'No overloads for "add" match the provided arguments\n'
         .. '  Argument of type "Literal[2]" cannot be assigned to parameter "carry"\n'
         .. '    "Literal[2]" is not assignable to "str | None"',
  code = "reportCallIssue", source = "basedpyright",
}, {
  lnum = 3, col = 17, end_lnum = 3, end_col = 18,
  severity = vim.diagnostic.severity.ERROR,
  message = 'Argument of type "Literal[2]" cannot be assigned to parameter "carry" of type '
         .. '"str | None" in function "add"',
  code = "reportArgumentType", source = "basedpyright",
} })
vim.wait(6000, function()
  for _, f in ipairs(require("companion.findings").findings.errors or {}) do
    if f.kind == "diagnostic_context" then return true end
  end
  return false
end, 50)
vim.cmd("CompanionPanel")
local buf = vim.fn.bufnr("companion://panel")
vim.fn.writefile(vim.api.nvim_buf_get_lines(buf, 0, -1, false), vim.env.PANEL_OUT)
"""


def check_panel_survives_multiline_diagnostics(root):
    """Two basedpyright messages about one call, one of them several lines long: drawn without
    raising, as one problem, said as one sentence."""
    out = OUT / "panel-multiline.txt"
    log = run_nvim("nvim-panel-multiline", MULTILINE_DIAG, root, env={"PANEL_OUT": str(out)})
    broke = "nvim_buf_set_lines" in log or "stack traceback" in log
    lines = out.read_text().splitlines() if out.exists() else []
    shown = next((l for l in lines if "add() expects" in l), "")
    check("Panel survives a multi-line diagnostic", not broke and bool(shown),
          shown.strip()[:96] if shown else "panel did not render the diagnostic"
          + (" (nvim_buf_set_lines raised)" if broke else ""))
    check("One mistake reported twice is one problem",
          bool(lines) and "2 diagnostics" in lines[0]
          and sum("add() expects" in l for l in lines) == 1
          and not any("No overloads" in l or "Argument of type" in l for l in lines),
          f"{lines[0].strip() if lines else ''!r}, and the row reads {shown.strip()!r}; the "
          "language server's wording stays behind `d`")


def check_panel(root):
    """The quick-help panel: one line per problem, the problem on ↵, its paperwork on d, engine
    metadata elsewhere. It opens only on request; having been asked for, it takes focus, because
    its keys act inside it, and gives the cursor back when it closes."""
    paths = {k: OUT / f"panel-{k}.txt" for k in ("compact", "detail", "raw", "info")}
    state_file = OUT / "panel-state.json"
    run_nvim("nvim-panel", PANEL, root,
             env={"PANEL_OUT": str(paths["compact"]), "PANEL_DETAIL": str(paths["detail"]),
                  "PANEL_RAW": str(paths["raw"]), "PANEL_INFO": str(paths["info"]),
                  "PANEL_STATE": str(state_file)})
    lines = paths["compact"].read_text().splitlines()
    detail = paths["detail"].read_text().splitlines()
    raw = paths["raw"].read_text().splitlines()
    info = [l.strip() for l in paths["info"].read_text().splitlines()]
    state = json.loads(state_file.read_text())

    first = lines[0].strip() if lines else ""
    metadata = [l for l in lines if any(m in l for m in ("pid ", "seq ", "qmd", "passage(s)"))]
    check("Panel leads with a count, not engine metadata",
          first.split(" ")[0].isdigit() and not metadata,
          f"first line {first!r}; engine fields drawn: {len(metadata)}")
    caller = next((l for l in lines if "client.py:4" in l), "")
    check("Panel shows the unsaved caller finding", "unsaved" in caller,
          " ".join(caller.split()) or "no caller row drawn")
    excerpt = next((l for l in detail if "return add(1, 2)" in l), "")
    check("Inspecting opens one problem", len(detail) > len(lines) and bool(excerpt),
          f"↵ grew the panel from {len(lines)} to {len(detail)} lines, "
          f"showing the call site's code {excerpt.strip()!r}")
    labels = ("source", "basis", "buffer")
    check("Provenance only on request",
          not any(l.strip().startswith(labels) for l in lines + detail)
          and all(any(l.strip().startswith(k) for l in raw) for k in labels),
          "absent from the list and the inspected problem; d adds source, basis and buffer")
    fields = {k: any(l.startswith(k) for l in info)
              for k in ("engine", "buffer", "model", "context", "unsaved")}
    check("Engine metadata lives in :CompanionInfo", all(fields.values()),
          "fields drawn: " + ", ".join(sorted(k for k, v in fields.items() if v)))
    opened, closed = state["opened"], state["closed"]
    check("Panel opens only when asked, as a focused float",
          state["unasked"] and opened["open"] and opened["float"] and opened["focused"],
          "no window appeared while findings arrived; :CompanionPanel opened a float and "
          "moved the cursor into it")
    check("Closing the panel gives the cursor back",
          closed["closed"] and closed["back"] and closed["toggled"],
          "q closed it and returned to the code window; :CompanionPanel twice toggles it")
    unobserved = state["unobserved"]
    check("Before :CompanionStart the panel says it is not observing",
          any("not observing" in l for l in unobserved)
          and not any("engine" in l or "problem" in l for l in unobserved),
          " / ".join(l.strip() for l in unobserved if l.strip()))
    pinned = state["pinned"]
    check("A pinned panel stays in view",
          all(pinned.get(k) for k in ("opened", "stayed_in_code", "entered", "no_pseudo_root",
                                      "survived_leaving", "survived_jump", "unstick_closed")),
          ":CompanionPanelPin opened it without taking the cursor; it survived leaving and a "
          "jump; unpinning closed it — " + json.dumps(pinned))
    linked = ("follow_opened", "follow_closed", "source_marked", "source_cleared")
    check("Pinned panel and code are linked", all(pinned.get(k) for k in linked),
          "the problem on the code cursor's line opened in the panel with the cursor left in the "
          "code, and moving off restored the problem that had been open before; the problem "
          "selected in the panel was marked in the code until the panel lost focus — "
          + json.dumps({k: pinned.get(k) for k in linked}))
    check("The cursor hides inside the panel",
          pinned.get("cursor_hidden") and pinned.get("cursor_restored"),
          "guicursor carries the hidden-cursor highlight while the panel has focus, and is "
          "restored exactly when it loses it")
    check("Statusline carries the count",
          state["statusline"].startswith("◉") and any(ch.isdigit() for ch in state["statusline"]),
          repr(state["statusline"]))


def nvim(root, save):
    run_nvim("nvim-save" if save else "nvim-unsaved",
             EDIT + ('vim.cmd("write")\n' if save else "")
             + 'vim.wait(700, function() return false end)\nc.stop(root)\n', root)


CANON_LUA = r'''local util = require("companion.util")
local fixtures = vim.json.decode(table.concat(vim.fn.readfile(vim.env.CANON_FIXTURES), "\n"))
local out = {}
for _, c in ipairs(fixtures.cases) do
  vim.cmd("enew!")
  local buf = vim.api.nvim_get_current_buf()
  vim.bo[buf].fileformat = c.fileformat
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, c.lines)
  vim.bo[buf].eol = c.eol
  vim.bo[buf].fixeol = c.eol
  local text = util.canonical_text(buf)
  local path = vim.env.CANON_OUT .. "/" .. c.name
  vim.cmd("write! " .. vim.fn.fnameescape(path))
  table.insert(out, { name = c.name, sha = util.text_sha(text), size = #text })
end
vim.fn.writefile({ vim.json.encode(out) }, vim.env.CANON_RESULT)
'''


def check_canonical_text():
    """The adapter and the engine must hash the same buffer to the same value, or every
    freshness check downstream is decoration. Verified three ways at once: the Lua hash, the
    Python hash, and the bytes Neovim actually writes to disk."""
    from devcompanion import canon
    fixtures = json.loads((PROJECT / "tests/fixtures/text-canon.json").read_text())
    written, result = OUT / "canon-files", OUT / "canon-result.json"
    written.mkdir(exist_ok=True)
    run_nvim("canon", CANON_LUA, env={"CANON_FIXTURES": str(PROJECT / "tests/fixtures/text-canon.json"),
                                      "CANON_OUT": str(written), "CANON_RESULT": str(result)})
    lua = {r["name"]: r for r in json.loads(result.read_text())}
    agree, disagree = [], []
    for case in fixtures["cases"]:
        name = case["name"]
        py = canon.sha(canon.canonical(case["lines"], case["fileformat"], case["eol"]))
        disk = canon.sha((written / name).read_bytes())
        row = (name, case["sha"], py, lua.get(name, {}).get("sha"), disk)
        (agree if len({case["sha"], py, row[3], disk}) == 1 else disagree).append(row)
    (OUT / "canon-comparison.json").write_text(json.dumps(
        {"agree": agree, "disagree": disagree}, indent=2))
    check("Canonical text agrees across Lua, Python and disk", not disagree,
          f"{len(agree)}/{len(fixtures['cases'])} fixture cases hash identically in the adapter, "
          f"the engine, and the file Neovim writes"
          + (f"; mismatches: {disagree}" if disagree else ""))


def main():
    print(f"Artifacts: {OUT}", flush=True)
    root = fixture("saved")
    unit = run([sys.executable, "-m", "pytest", "-q", "tests"])
    (OUT / "unit-tests.log").write_text(unit)
    check("Existing unit suite", "passed" in unit and "failed" not in unit,
          unit.strip().splitlines()[-1])
    check_canonical_text()
    ingest(root, "01-baseline", "calc.py", "client.py", "tests/test_calc.py")
    check("Baseline", all(r["kind"] == "noop" for r in records(root).values()), "No breaking finding for unchanged committed files")

    (root / "calc.py").write_text(BROKEN)
    ingest(root, "02-breaking", "calc.py")
    rec = signature(root)
    check("Breaking signature", sum(l["verdict"] == "breaks" for l in rec.get("locations", [])) == 2,
          rec.get("claim", "No signature record"))
    check("Tests detect breakage", records(root)["test_run:calc.py:-"]["claim"].startswith("failed:"),
          records(root)["test_run:calc.py:-"]["claim"])
    check("Quickfix", len((root / ".companion/quickfix.txt").read_text().splitlines()) == 2,
          "Two breaking caller locations expected")

    unchanged = ingest(root, "03-unchanged", "calc.py")
    check("Unchanged save", unchanged == [], "No task bundle ran")

    (root / "client.py").write_text(CLIENT.replace("add(1, 2)", "add(1, 2, 0)"))
    ingest(root, "04-one-fixed", "client.py")
    rec = signature(root)
    check("Fix one caller", sum(l["verdict"] == "breaks" for l in rec.get("locations", [])) == 1,
          rec.get("claim", "No record"))
    (root / "tests/test_calc.py").write_text(TEST.replace("add(1, 2)", "add(1, 2, 0)"))
    ingest(root, "05-all-fixed", "tests/test_calc.py")
    rec = signature(root)
    check("Fix all callers", rec.get("status") == "fresh" and all(l["verdict"] == "ok" for l in rec.get("locations", [])), rec.get("claim", "No record"))
    check("Tests recover", records(root)["test_run:calc.py:-"]["claim"].startswith("passed:"), records(root)["test_run:calc.py:-"]["claim"])
    check("Quickfix clears", (root / ".companion/quickfix.txt").read_text() == "", "No remaining caller warnings")

    replay = OUT / "replayed"
    log = run(command(OUT / "absent-source", "--state", replay, "replay", root / ".companion"))
    (OUT / "06-replay.log").write_text(log)
    replay_state = json.loads((replay / "state.json").read_text())
    live_fp = {k: r["fingerprint"] for k,r in records(root).items() if r["kind"] != "test_run"}
    replay_fp = {k: r["fingerprint"] for k,r in replay_state.items() if r["kind"] != "test_run"}
    check("Replay without working tree", live_fp == replay_fp, "Non-test evidence fingerprints match live final state")
    check("Replay skips execution", replay_state["test_run:calc.py:-"]["claim"].startswith("skipped:"), replay_state["test_run:calc.py:-"]["claim"])

    (root / "scratch.py").write_text("def broken(\n")
    ingest(root, "07-invalid", "scratch.py")
    check("Invalid Python", records(root)["file:scratch.py"]["kind"] == "unknown_intent", "Parse error produces unknown_intent")

    removed = fixture("removed")
    ingest(removed, "08-removal-baseline", "calc.py")
    (removed / "calc.py").write_text("# function removed\n")
    ingest(removed, "09-removed", "calc.py")
    rr = records(removed).get("removed_function:calc.py:add", {})
    check("Removed function", len(rr.get("locations", [])) == 2 and all(l["reason"] == "callee no longer exists" for l in rr["locations"]), rr.get("claim", "No removal record"))

    # Direct engine calls make rapid submissions deterministic instead of relying on OS timing.
    from devcompanion.engine import Engine
    from devcompanion.observe.events import Event
    rapid = fixture("rapid")
    eng = Engine(rapid, run_tests=False, log=lambda _: None)
    eng.handle_event(Event(kind="buffer_saved", path="calc.py"))
    eng.sched.drain(wait=False)
    for src in (BROKEN, BROKEN.replace("carry):", "carry, extra=0):")):
        (rapid / "calc.py").write_text(src)
        eng.handle_event(Event(kind="buffer_saved", path="calc.py"))
    before = eng.sched.stats["ran"]
    eng.sched.drain(wait=False)
    check("Rapid submissions coalesce", eng.sched.stats["coalesced"] == 1 and eng.sched.stats["ran"] == before+1, json.dumps(eng.sched.stats))

    check_announce_on_start(fixture("nvim-announce"))

    live = fixture("nvim-live")
    ingest(live, "10-live-baseline", "calc.py", "client.py", "tests/test_calc.py")
    with (OUT / "watch.log").open("w") as log_file:
        watcher = subprocess.Popen(command(live, "watch"), env=ENV, stdout=log_file, stderr=subprocess.STDOUT)
        try:
            if not poll(lambda: "watching " in (OUT / "watch.log").read_text()):
                raise RuntimeError("Watcher did not start")
            nvim(live, save=False)
            poll(lambda: '"kind": "buffer_changed"' in (live / ".companion/events.jsonl").read_text())
            inbox = [json.loads(l) for l in (live / ".companion/inbox.jsonl").read_text().splitlines()]
            check("Lua emits unsaved text", any(e.get("kind") == "buffer_changed" and "carry" in e.get("text", "") for e in inbox), "Actual Neovim TextChanged event contains edited text")

            # The point of the whole exercise: a finding about code that exists only in a buffer.
            found = poll(lambda: signature(live).get("claim", "").startswith("2 call site"))
            rec = signature(live)
            check("Unsaved ingestion", found and (live / "calc.py").read_text() == BASE,
                  f"{rec.get('claim', 'no record')} — while calc.py on disk still holds the "
                  f"original signature")
            check("Unsaved analysis says so", "unsaved buffer" in rec.get("details", {}).get("revision", ""),
                  rec.get("details", {}).get("revision", "no revision detail"))
            check("Unsaved edit runs no tests", "test_run:calc.py:-" not in records(live),
                  "pytest reads the working tree, so it is not run for buffer-only content")

            # The adapter's own hash of the buffer has to be the hash the engine recorded,
            # or the editor cannot tell a fresh finding from a stale one.
            changed = [e for e in inbox if e.get("kind") == "buffer_changed"][-1]
            events = [json.loads(l) for l in (live / ".companion/events.jsonl").read_text().splitlines()]
            ingested = [e for e in events if e.get("kind") == "buffer_changed"][-1]
            check("Adapter and engine agree on the buffer hash",
                  changed["text_sha"] == ingested["content_sha"] == rec["based_on"]["calc.py"],
                  f"adapter {changed['text_sha']}, engine {ingested['content_sha']}, "
                  f"finding depends on {rec['based_on']['calc.py']}")
            check("Protocol v2 fields survive intake",
                  ingested.get("dirty") is True and ingested.get("session")
                  and ingested.get("doc_version") and ingested.get("language") == "python"
                  and ingested.get("content_origin") == "editor"
                  and ingested.get("source") == "nvim" and "text" not in ingested,
                  f"dirty={ingested.get('dirty')} session={ingested.get('session')} "
                  f"doc_version={ingested.get('doc_version')} language={ingested.get('language')!r} "
                  f"origin={ingested.get('content_origin')} source={ingested.get('source')}; "
                  f"buffer text stays in the snapshot store, not the event log")

            engine_state = json.loads((live / ".companion/engine.json").read_text())
            check("Engine reports the unsaved buffer", engine_state["dirty_buffers"] == ["calc.py"]
                  and engine_state["revisions"]["calc.py"]["origin"] == "editor",
                  json.dumps({k: engine_state[k] for k in ("state", "dirty_buffers", "findings")}))
            published = [json.loads(l) for l in (live / ".companion/findings.jsonl").read_text().splitlines()]
            callers_now = [f for f in published if f["kind"] == "caller_affected"]
            check("Findings published for the unsaved edit",
                  len(callers_now) == 2 and all(f["revision"]["calc.py"] == "editor" for f in callers_now),
                  f"{len(callers_now)} caller_affected finding(s), each marked as resting on "
                  f"buffer content")
            check_panel(live)
            check_panel_survives_multiline_diagnostics(live)

            nvim(live, save=True)
            ready = poll(lambda: signature(live).get("claim", "").startswith("2 call site") and records(live).get("test_run:calc.py:-", {}).get("claim", "").startswith("failed:"))
            check("Real Neovim :write → watch → evidence", ready, "Both breaking callers and a failed pytest result appear")
            capture(live, "11-nvim-saved")
            events = [json.loads(l) for l in (live / ".companion/events.jsonl").read_text().splitlines()]
            check("Lua save reaches engine", any(e["kind"] == "buffer_saved" for e in events), "Not relying solely on filesystem watcher")

            check("Editor return files", all((live / ".companion" / f).exists()
                                             for f in ("findings.jsonl", "engine.json")),
                  "findings.jsonl and engine.json are written by the engine; outbox.jsonl "
                  "waits for the engine to have an LSP question to ask")
            saved_state = json.loads((live / ".companion/engine.json").read_text())
            check("Save clears the unsaved overlay", saved_state["dirty_buffers"] == []
                  and saved_state["revisions"]["calc.py"]["origin"] == "disk",
                  f"after :write the same content is attributed to the file, not the buffer "
                  f"(dirty_buffers={saved_state['dirty_buffers']})")
            test_rec = records(live)["test_run:calc.py:-"]
            check("Saved tests are labelled as saved-revision evidence",
                  test_rec["details"]["revision"].startswith("saved files only"),
                  test_rec["details"]["revision"])
            published = [json.loads(l) for l in (live / ".companion/findings.jsonl").read_text().splitlines()]
            test_finding = next((f for f in published if f["kind"] == "test_result"), None)
            check("Test findings declare their revision limit",
                  bool(test_finding) and test_finding["saved_revision_only"] is True
                  and all(o == "disk" for o in test_finding["revision"].values()),
                  test_finding["consequence"] if test_finding else "no test finding published")

            # Quitting takes the unsaved buffers with it; nothing may go on claiming otherwise.
            run_nvim("nvim-session-end", SESSION_END, live)
            ended = poll(lambda: json.loads((live / ".companion/engine.json").read_text())["session"] is None)
            final = json.loads((live / ".companion/engine.json").read_text())
            check("Editor departure drops its overlays", ended and final["dirty_buffers"] == [],
                  "an editor that quits stops being credited with unsaved content")
            # session_end re-judges the paths it dropped overlays for; let that settle before
            # treating events.jsonl/state.json as quiescent, or the async catch-up (unrelated
            # to the watermark) races the restart snapshots below.
            poll(lambda: json.loads((live / ".companion/engine.json").read_text())["pending_tasks"] == 0)

            # --- the watermark: restart must resume, not re-observe ---
            def stop_watcher():
                watcher.terminate()
                try:
                    watcher.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    watcher.kill()
                    watcher.wait()

            def start_watcher(tag):
                nonlocal watcher
                with (OUT / f"{tag}.log").open("w") as log_file:
                    watcher = subprocess.Popen(command(live, "watch"), env=ENV, stdout=log_file, stderr=subprocess.STDOUT)
                if not poll(lambda: "watching " in (OUT / f"{tag}.log").read_text()):
                    raise RuntimeError(f"{tag}: watcher did not start")

            def intake_of(root):
                return json.loads((root / ".companion/engine.json").read_text())["intake"]

            # This is the restart path every real use of `companion watch` takes: the inbox is
            # untouched, so the offset alone should carry it -- no reset, nothing re-read or
            # declined. check-workflow previously only ever restarted after rotating the inbox
            # (below), which exercises the *reset* path exclusively; a fingerprinting bug that
            # broke only the clean-resume path (min(HEAD_BYTES, offset) vs. a fixed 4096, see
            # docs/intake-watermark.md) passed every check here until this one was added.
            events_before_clean_restart = (live / ".companion/events.jsonl").read_text()
            state_before_clean_restart = (live / ".companion/state.json").read_text()
            stop_watcher()
            start_watcher("watch-restart-clean")
            # A correct clean restart produces no event to poll for; give the heartbeat (cli
            # cmd_watch, 1s) one cycle to publish what reconciliation already decided.
            time.sleep(1.5)
            clean_intake = intake_of(live)
            check("A clean restart resumes at the offset: no reset, nothing re-read",
                  clean_intake["resets"] == 0 and clean_intake["resumed_at"] > 0 and clean_intake["skipped_known"] == 0,
                  json.dumps(clean_intake))
            check("A clean restart does not touch events.jsonl or state.json",
                  (live / ".companion/events.jsonl").read_text() == events_before_clean_restart
                  and (live / ".companion/state.json").read_text() == state_before_clean_restart,
                  f"{len(events_before_clean_restart.splitlines())} line(s) in events.jsonl before and after")

            events_before_restart = (live / ".companion/events.jsonl").read_text()
            state_before_restart = (live / ".companion/state.json").read_text()
            prior_calc_sha = signature(live).get("based_on", {}).get("calc.py")

            # Rotate inbox.jsonl in place: identical bytes, a new inode -- exactly what a real
            # log rotation does, and precisely the case an offset alone cannot survive. Every
            # event in it was already accepted, so the restarted engine must recognise that
            # from the per-session marks rather than reprocessing the whole file.
            stop_watcher()
            inbox_path = live / ".companion" / "inbox.jsonl"
            rotated = inbox_path.with_name("inbox.jsonl.rotated")
            rotated.write_bytes(inbox_path.read_bytes())
            os.replace(rotated, inbox_path)

            start_watcher("watch-restart")
            # Nothing to poll for on a correct restart -- it produces no event. Poll instead
            # for the engine's own report of what it declined, which only needs its 1s
            # no-traffic heartbeat (see cli.cmd_watch) to catch up.
            declined = poll(lambda: intake_of(live)["skipped_known"] > 0, timeout=5)
            check("The restarted engine's intake block updates without any new event",
                  declined, json.dumps(intake_of(live)))

            check("Restart does not reprocess events.jsonl or state.json",
                  (live / ".companion/events.jsonl").read_text() == events_before_restart
                  and (live / ".companion/state.json").read_text() == state_before_restart,
                  f"{len(events_before_restart.splitlines())} line(s) in events.jsonl before and "
                  f"after the restart, evidence unchanged")

            restarted_state = json.loads((live / ".companion/engine.json").read_text())
            check("engine.json reports the intake block", "intake" in restarted_state
                  and {"offset", "resumed_at", "skipped_known", "malformed", "resets"} <= restarted_state["intake"].keys(),
                  json.dumps(restarted_state.get("intake")))
            check("The restarted engine saw the rotated file's old events and declined them",
                  restarted_state["intake"]["skipped_known"] > 0 and restarted_state["intake"]["resets"] >= 1,
                  f"skipped_known={restarted_state['intake']['skipped_known']}, "
                  f"resets={restarted_state['intake']['resets']} — re-read, not re-observed for the first time")

            run_nvim("nvim-after-restart", RESTART_EDIT, live)
            picked_up = poll(lambda: signature(live).get("based_on", {}).get("calc.py") not in (None, prior_calc_sha))
            rec = signature(live)
            check("A new edit after the restart is still picked up and produces a finding",
                  picked_up and rec.get("locations"),
                  rec.get("claim", "no record"))
        finally:
            watcher.terminate()
            try:
                watcher.wait(timeout=5)
            except subprocess.TimeoutExpired:
                watcher.kill()
                watcher.wait()


if __name__ == "__main__":
    # Allow invocation by path without requiring an editable install.
    sys.path.insert(0, str(PROJECT / "src"))
    try:
        main()
    except Exception as error:
        check("Harness completion", False, f"{type(error).__name__}: {error}")
    report = ["# devcompanion workflow check", "", f"Artifacts: `{OUT}`", "",
              "Actual CLI, pytest and headless Neovim; disposable local Git fixtures; no model configured.", "",
              "| Result | Scenario | Observation |", "|---|---|---|"]
    for status, name, detail in ROWS:
        report.append(f"| {status} | {name} | {detail.replace(chr(10), ' ').replace('|', '/')} |")
    report.extend(["", "Board snapshots and command logs are alongside this report. Replay state is under `replayed/`.",
                   "Rapid coalescing uses direct engine submissions; the Neovim case exercises actual file transport and watchdog.",
                   "GAP CONFIRMED identifies an observed missing capability, not a passing product acceptance criterion.", ""])
    (OUT / "report.md").write_text("\n".join(report))
    print(f"Report: {OUT / 'report.md'}")
    sys.exit(1 if any(row[0] == "FAIL" for row in ROWS) else 0)
