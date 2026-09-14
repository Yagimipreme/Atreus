"""devcompanion: six inspectable stages.

observe   -> events (JSONL, editor-independent, replayable)
snapshot  -> content-addressed file states (basis for Freeze/Compare)
view      -> effective revision per path: unsaved buffer when there is one, else the file
schedule  -> detect tasks from revision diffs, debounce, cancel stale
investigate -> run cheap tools, produce evidence records
present   -> board.md + quickfix + findings.jsonl + engine.json, nothing pops up
"""

__version__ = "0.2.0"
