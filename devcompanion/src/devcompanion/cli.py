from __future__ import annotations

import argparse
import json
import queue
import signal
import sys
import threading
import time
from pathlib import Path

from .engine import Engine
from .observe import events as ev
from .observe import fswatch
from .observe.intake import Intake


def _llm_from_args(a) -> dict | None:
    if not a.model:
        return None
    return {"model": a.model, "backend": a.backend, "base_url": a.base_url,
            "cpu_only": a.cpu_only, "keep_alive": a.keep_alive}


def cmd_ingest(a):
    """Emit one event for a path (what the Neovim plugin does) and process it synchronously."""
    eng = Engine(Path(a.root), Path(a.state) if a.state else None, run_tests=not a.no_tests, llm=_llm_from_args(a))
    for p in a.paths:
        eng.handle_event(ev.Event(kind="buffer_saved", path=str(Path(p).resolve()), source="cli"))
    eng.sched.drain(wait=False)
    print(json.dumps(eng.timings))


def cmd_replay(a):
    """Re-run an events log against its snapshot store into a fresh state dir; deterministic."""
    src = Path(a.replay_dir)
    eng = Engine(Path(a.root), Path(a.state), run_tests=not a.no_tests, llm=_llm_from_args(a), replay=True)
    # bring the recorded objects along so content resolves without touching the working tree
    import shutil
    shutil.copytree(src / "snapshots" / "objects", eng.dir / "snapshots" / "objects", dirs_exist_ok=True)
    n = 0
    for e in ev.read(src / "events.jsonl"):
        e.seq = None
        e.source = "replay"
        eng.handle_event(e)
        eng.sched.drain(wait=False)
        n += 1
    print(json.dumps({"events": n, "timings": eng.timings, "stats": eng.sched.stats}))


def _intake_block(intake: Intake) -> dict:
    return {**intake.stats, "offset": intake.offset}


def cmd_watch(a):
    root = Path(a.root).resolve()
    eng = Engine(root, Path(a.state) if a.state else None, run_tests=not a.no_tests, llm=_llm_from_args(a),
                 log=lambda s: print(time.strftime("%H:%M:%S"), s, flush=True))
    q: "queue.Queue[tuple[ev.Event, int | None]]" = queue.Queue()
    fswatch.start(root, q)
    inbox = eng.dir / "inbox.jsonl"
    intake = Intake(eng.dir, inbox, log=eng.log)
    # A fresh intake.json (a new workspace, or one whose state file was lost) means
    # accepted == {}; without this, every event events.jsonl already recorded gets replayed
    # into the engine as new on first contact with any existing workspace. Never overrides a
    # mark intake.json already has -- see Intake.seed and Engine._scan_events_log.
    intake.seed(eng.accepted_editor_seqs)

    last_published_intake = _intake_block(intake)
    eng.intake_stats = last_published_intake
    # Report what we resumed at even before anything new arrives, so the pane can tell
    # "resumed" from "restarted" without waiting for the developer's next keystroke.
    eng.publish()

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda signum, frame: stop.set())  # what any process manager sends

    def tail_inbox():
        for e, offset in intake.follow(stop):
            q.put((e, offset))

    threading.Thread(target=tail_inbox, daemon=True).start()
    threading.Thread(target=eng.sched.serve_forever, args=(stop,), daemon=True).start()
    print(f"watching {root} -> {eng.dir}/board.md  (inbox: {inbox})", flush=True)
    try:
        while not stop.is_set():
            try:
                e, offset = q.get(timeout=1.0)
            except queue.Empty:
                # A restart that only re-reads and declines old events produces no queue
                # traffic at all -- accept() never runs, so without this, skipped_known would
                # stay invisible in engine.json until the developer's next keystroke. Only
                # publish on an actual change: otherwise this rewrites findings.jsonl and
                # engine.json every second forever, idle or not, waking the adapter's mtime
                # watcher into a full re-read and re-render for nothing.
                current = _intake_block(intake)
                if current != last_published_intake:
                    eng.intake_stats = last_published_intake = current
                    eng.publish()
                continue
            eng.handle_event(e)
            if offset is not None:
                # After handling, never before: a crash between the two re-delivers the event
                # on restart instead of silently committing past one that was never taken.
                intake.accept(e, offset)
                eng.intake_stats = last_published_intake = _intake_block(intake)
    except KeyboardInterrupt:
        stop.set()


def cmd_board(a):
    d = (Path(a.state) if a.state else Path(a.root) / ".companion")
    print((d / "board.md").read_text())


def cmd_nvim_plugin(a):
    print(Path(__file__).resolve().parents[2] / "nvim")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="companion")
    ap.add_argument("--root", default=".")
    ap.add_argument("--state", default=None, help="state dir (default <root>/.companion)")
    ap.add_argument("--no-tests", action="store_true")
    ap.add_argument("--model", default=None, help="local model name; omit for deterministic-only")
    ap.add_argument("--backend", default="ollama", choices=["ollama", "openai"])
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--cpu-only", action="store_true")
    ap.add_argument("--keep-alive", default="30m",
                    help="how long the backend keeps the model resident (ollama); 0 to unload immediately")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ingest"); s.add_argument("paths", nargs="+"); s.set_defaults(fn=cmd_ingest)
    s = sub.add_parser("replay"); s.add_argument("replay_dir"); s.set_defaults(fn=cmd_replay)
    s = sub.add_parser("watch"); s.set_defaults(fn=cmd_watch)
    s = sub.add_parser("board"); s.set_defaults(fn=cmd_board)
    s = sub.add_parser("nvim-plugin-path"); s.set_defaults(fn=cmd_nvim_plugin)
    a = ap.parse_args(argv)
    if a.cmd == "replay" and not a.state:
        ap.error("replay requires --state <fresh dir>")
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
