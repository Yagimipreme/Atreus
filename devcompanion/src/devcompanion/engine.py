"""Wires the stages. `handle_event` is synchronous so replay is deterministic; `watch` adds
producers and a worker thread around it.

Two things changed in v2. Events from the editor now keep their content, so an unsaved buffer
is analysable (`ContentView` decides which bytes count as current for each path). And the
engine publishes what it knows back to the editor — `findings.jsonl` and `engine.json` — so
the adapter has something to render besides the board it cannot read.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

from .evidence.store import Evidence, EvidenceStore
from .investigate import callers, tests as testrun
from .observe import events as ev
from .present import board, findings as findings_out, status as status_out
from .schedule.detect import Task, detect
from .schedule.queue import Scheduler
from .snapshot.store import SnapshotStore
from .view.index import ContentView

#: Events that say something about a path's content rather than about the session.
SESSION_KINDS = {"goal", "dismiss", "request", "lsp_result", "session_end"}


class Engine:
    def __init__(self, root: Path, state_dir: Path | None = None, run_tests: bool = True,
                 llm: dict | None = None, log=print, replay: bool = False):
        self.root = root.resolve()
        self.replay = replay      # replay: never touch disk; content and callers come from snapshots
        self.dir = (state_dir or self.root / ".companion").resolve()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.snap = SnapshotStore(self.dir / "snapshots")
        self.view = ContentView(self.root, self.snap, self.dir, replay=replay)
        self.evid = EvidenceStore(self.dir)
        self.events_log = self.dir / "events.jsonl"
        self.sched = Scheduler(self._run_bundle)
        self.run_tests = run_tests
        self.llm = llm            # {"model","backend","base_url","cpu_only"} or None
        self.log = log
        self.seq, self.accepted_editor_seqs = self._scan_events_log()
        self.timings: list[dict] = []
        self.goal: str | None = None
        self._prefix: str | None = None   # workspace path inside its git repo; see _git_prefix
        self.state = "idle"
        self.last_error: str | None = None
        # Set from outside by cmd_watch, an opaque dict Engine only carries and republishes.
        # Replay and ingest have no inbox and must not grow a dependency on one to work.
        self.intake_stats: dict | None = None
        self.present()

    def _scan_events_log(self) -> tuple[int, dict[str, int]]:
        """One pass over events.jsonl for two things a restart needs: the engine's own next
        `seq`, and the highest `editor_seq` this log has ever recorded per session.

        The second is what `cmd_watch` seeds a fresh `Intake` with (`Intake.seed`): a new
        `intake.json` (a new workspace, or one whose state file was lost) otherwise means
        `accepted == {}`, and every event already durably logged here gets replayed into the
        engine as if it were new -- the exact failure this module exists to prevent, on first
        contact with every existing workspace. `Engine` only ever reads its own log for this;
        it does not know `Intake` exists, so replay and ingest are unaffected."""
        seq, accepted = 0, {}
        for e in ev.read(self.events_log):
            seq = max(seq, e.seq or 0)
            if e.session and e.editor_seq is not None and e.editor_seq > accepted.get(e.session, -1):
                accepted[e.session] = e.editor_seq
        return seq, accepted

    # ---------- observe -> snapshot ----------
    def handle_event(self, e: ev.Event, content: bytes | None = None) -> None:
        """Record the event, resolve its content, schedule detection. Content comes from the
        editor (unsaved buffers), from disk (live), or from the snapshot store (replay)."""
        self.seq += 1
        if e.session is not None and e.editor_seq is None:
            e.editor_seq = e.seq            # keep the adapter's own counter beside ours
        e.seq = self.seq
        if self.view.adopt_session(e.session):
            self.log(f"  editor session {e.session}: following a new Neovim instance")
        if e.kind in SESSION_KINDS:
            self._handle_session_event(e)
            return

        e.path = self.rel(e.path)
        if e.kind == "cursor":
            ev.append(self.events_log, e)
            return
        if e.kind == "diagnostics":
            self.view.record_diagnostics(e.path, e.items or [])
            ev.append(self.events_log, e)
            self.view.persist()
            n = sum(d.get("severity") == "error" for d in (e.items or []))
            self.log(f"  diagnostics: {e.path}: {len(e.items or [])} item(s), {n} error(s)")
            self.publish()
            return

        content, origin = self._resolve_content(e, content)
        if content is None:
            e.kind = "file_deleted"
            self.view.forget(e.path)
            ev.append(self.events_log, e)
            return
        if origin != "editor" and not self.replay and self.snap.latest(e.path) is None:
            self._baseline_from_git(e.path)          # lazy: only for files we first see now
        put = self.snap.put(e.path, content, self.seq, origin=origin)
        e.content_sha, e.content_origin = put.sha, origin
        if origin == "editor":
            self.view.record_editor(e.path, put.sha, dirty=True, doc_version=e.doc_version,
                                    session=e.session, language=e.language)
        else:
            self.view.record_disk(e.path, put.sha)
        self.view.persist()
        ev.append(self.events_log, e)
        if not (put.changed or put.origin_changed):
            return                                   # same bytes, same place: nothing to do
        self.sched.submit(e.path, put.sha, self.seq, origin)
        if not put.changed:
            return                                   # a save of already-analysed bytes
        # A claim about file D that depended on this file goes stale; re-judge D at its
        # current revision so the board converges without the developer touching D again.
        for rec in self.evid.mark_stale(e.path, put.sha):
            self.log(f"  stale: {rec['title']}")
            d = rec["key"].split(":", 2)[1]
            if d != e.path and (d_rev := self.view.effective(d)):
                self.sched.submit(d, d_rev.sha, self.seq, d_rev.origin)
        self._recheck_claims_naming(e.path, content)

    def _recheck_claims_naming(self, path: str, content: bytes) -> None:
        """A file that mentions a changed callee but was not part of the claim about it is a
        call site that did not exist when the claim was made — a caller just written, or one
        typed into a file the engine had never seen.

        Staleness cannot catch this: the claim never depended on this file, so nothing marks it
        stale, and it would go on reporting the call sites that existed at the time. So the
        defining file is re-judged instead, which re-runs the search over current content.
        """
        for rec in self.evid.records():
            if rec["status"] != "fresh" or rec["kind"] not in ("signature_change", "removed_function"):
                continue
            if path in rec["based_on"]:
                continue                      # already part of the claim: staleness handles it
            name = rec["key"].rsplit(":", 1)[-1].split(".")[-1]
            if name == "-" or name.encode() not in content:
                continue
            defining = rec["key"].split(":", 2)[1]
            if (rev := self.view.effective(defining)) is not None:
                self.log(f"  {path} now names {name}: re-judging {rec['title']}")
                self.sched.submit(defining, rev.sha, self.seq, rev.origin)

    def _resolve_content(self, e: ev.Event, content: bytes | None) -> tuple[bytes | None, str]:
        """Where the bytes for this event come from, and what that origin means.

        `editor` content exists only in an unsaved buffer; everything else is also on disk and
        so is visible to tools that shell out. An adapter whose declared hash does not match
        the text it sent is a bug worth surfacing, but the bytes are still usable — we just
        trust what arrived rather than what it claimed.
        """
        if content is not None:
            return content, "disk"
        body = e.content()
        if body is not None:
            if (mismatch := e.content_mismatch()):
                self.last_error = f"{e.path}: text_sha mismatch ({mismatch})"
                self.log(f"  warning: {self.last_error}")
            dirty = bool(e.dirty) and e.kind in ev.CONTENT_KINDS
            return body, "editor" if dirty else "disk"
        if e.content_sha and self.snap.has(e.content_sha):
            # Replay: the log kept the origin, so an unsaved buffer replays as an unsaved
            # buffer rather than quietly becoming a saved file.
            return self.snap.get(e.content_sha), e.content_origin or "disk"
        p = self.abs(e.path)
        if p.exists() and not self.replay:
            return p.read_bytes(), "disk"
        return None, "disk"

    def _handle_session_event(self, e: ev.Event) -> None:
        """Events about the session rather than about a file. Recorded, never analysed."""
        if e.kind == "goal" and e.text:
            self.goal = e.text
            self.log(f"  goal: {e.text}")
        elif e.kind == "dismiss":
            self.log(f"  dismiss: {e.finding_id} ({e.scope or 'finding'}) — not yet honoured")
        elif e.kind == "lsp_result":
            self.log(f"  lsp_result: {e.method} {e.status} ({len(e.items or [])} item(s))")
        elif e.kind == "request":
            self.log(f"  request: {e.what} {e.path or ''}".rstrip())
        elif e.kind == "session_end":
            self._end_session(e)
        ev.append(self.events_log, e)
        self.publish()

    def _end_session(self, e: ev.Event) -> None:
        """The editor closed. Unsaved buffers are gone; fall each path back to the file and
        re-judge it, so the board converges on the code that actually exists."""
        dropped = self.view.end_session(e.session)
        self.view.persist()
        if not dropped:
            return
        self.log(f"  session_end {e.session}: dropped {len(dropped)} unsaved overlay(s)")
        for path in dropped:
            rev = self.view.effective(path)
            if rev is None:
                continue
            self.evid.mark_stale(path, rev.sha)
            self.sched.submit(path, rev.sha, self.seq, rev.origin)

    def _git_prefix(self) -> str:
        """Where the workspace sits inside its git repository, e.g. `devcompanion/`.

        `git show HEAD:<path>` resolves from the repository root, not from the directory `-C`
        points at. A workspace that is a subdirectory of its repo therefore needs this prefix,
        or every baseline lookup silently misses and every file reads as first-seen — which
        means no comparison, no signature change, and a companion that says nothing at all.
        Empty when the workspace is the repo root, or when there is no repo.
        """
        if self._prefix is None:
            try:
                r = subprocess.run(["git", "-C", str(self.root), "rev-parse", "--show-prefix"],
                                   capture_output=True, text=True, timeout=10)
                self._prefix = r.stdout.strip() if r.returncode == 0 else ""
            except (FileNotFoundError, subprocess.TimeoutExpired):
                self._prefix = ""
        return self._prefix

    def _baseline_from_git(self, rel: str) -> None:
        """Follow mode baseline = the committed version. Recorded as a `baseline` event so a
        replay reproduces it. Freeze mode will simply point this at a chosen ref instead of HEAD."""
        try:
            r = subprocess.run(["git", "-C", str(self.root), "show", f"HEAD:{self._git_prefix()}{rel}"],
                               capture_output=True, timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return
        if r.returncode != 0:
            return                                    # untracked file or no commits: first sight is the baseline
        put = self.snap.put(rel, r.stdout, self.seq, origin="git")
        ev.append(self.events_log, ev.Event(kind="baseline", path=rel, source="git",
                                            content_sha=put.sha, seq=self.seq))

    def rel(self, path: str) -> str:
        pp = Path(path)
        if pp.is_absolute():
            try:
                return str(pp.resolve().relative_to(self.root))
            except ValueError:
                return str(pp)
        return path

    def abs(self, rel: str) -> Path:
        return self.root / rel

    # ---------- schedule -> investigate -> evidence ----------
    def _run_bundle(self, path: str, sha: str, seq: int, cancelled: list[str], origin: str = "disk") -> None:
        t0 = time.time()
        self.state = "working"
        for c in cancelled:
            self.evid.add(Evidence(f"cancelled:{path}:-:{c}", "cancelled", f"{Path(path).name}@{c}",
                                   "superseded by a newer save before investigation ran", {path: sha}, seq=seq))
        new_src = self.snap.get(sha)
        prev_sha = self.view.baseline(path, sha, origin)
        old_src = self.snap.get(prev_sha) if prev_sha else None
        tasks = detect(path, old_src, new_src, sha, seq)
        for t in tasks:
            self._investigate(t, origin)
        names = [t.qualname.split(".")[-1] for t in tasks if t.kind in ("signature_change", "removed_function")]
        # pytest imports the working tree, so it can only ever judge saved content. Running it
        # for an unsaved edit would report on code the developer has already moved past.
        if names and self.run_tests and origin != "editor":
            self._run_tests(path, sha, names, seq)
        self.timings.append({"path": path, "sha": sha, "origin": origin,
                             "tasks": [t.kind for t in tasks], "wall_s": round(time.time() - t0, 3)})
        self.state = "idle"
        self.present()

    def _read_current(self, rel: str) -> bytes | None:
        """The effective revision of a path: the unsaved buffer if there is one, else disk."""
        return self.view.read(rel)

    def _candidates(self, name: str) -> list[str]:
        """Files that might call `name`. Live: rg over the working tree, plus any buffer with
        unsaved content — rg reads files, so a call typed a second ago is invisible to it.
        Replay: scan the latest snapshot of every known path."""
        if self.replay:
            return [r for r in self.snap.known_paths() if name.encode() in (self._read_current(r) or b"")]
        found = {self.rel(str(p)) for p in callers.candidates(self.root, name)}
        for rel in self.view.dirty_paths():
            body = self.view.read(rel)
            if body and name.encode() in body:
                found.add(rel)
        return sorted(found)

    def _investigate(self, t: Task, origin: str = "disk") -> None:
        rel = Path(t.path).name
        key = f"{t.kind}:{t.path}:{t.qualname or '-'}"
        if t.kind in ("noop", "unknown_intent"):
            self.evid.state.pop(f"file:{t.path}", None)          # one status record per file
            self.evid.add(Evidence(f"file:{t.path}", t.kind, rel, t.detail, t.based_on, seq=t.seq))
            self.log(f"  {t.kind}: {rel}: {t.detail}")
            return
        if t.kind == "new_function":
            self.evid.add(Evidence(key, t.kind, t.new.render(), "new definition; no callers to check, test generation is a later phase",
                                   t.based_on, seq=t.seq))
            self.log(f"  new_function: {t.new.render()}")
            return
        sig = t.new or t.old
        is_stale = lambda: self.sched.is_stale(t.path, t.based_on[t.path])  # noqa: E731
        sites = callers.investigate(self._candidates(sig.name), sig, t.path, self._read_current, is_stale)
        if sites is None:
            self.evid.add(Evidence(key, "cancelled", t.detail or sig.render(), "input changed while investigating; will re-run",
                                   t.based_on, seq=t.seq))
            self.log(f"  abandoned (stale): {sig.render()}")
            return
        if t.kind == "removed_function":
            for s in sites:
                s.verdict, s.reason = "breaks", "callee no longer exists"
        based = dict(t.based_on)
        for s in sites:
            based[s.path] = s.file_sha
        n_break = sum(s.verdict == "breaks" for s in sites)
        n_unsure = sum(s.verdict == "unsure" for s in sites)
        claim = (f"{len(sites)} call site(s): {n_break} break, {n_unsure} unsure, {len(sites) - n_break - n_unsure} fit"
                 if sites else "no call sites found in repo")
        details = {}
        if origin == "editor":
            details["revision"] = "unsaved buffer; the file on disk still holds the previous version"
        unsaved = [p for p in based if self.view.is_dirty(p)]
        if unsaved and origin != "editor":
            details["unsaved_inputs"] = ", ".join(sorted(unsaved))
        evd = Evidence(key, t.kind, t.detail or sig.render(), claim, based,
                       [asdict(s) for s in sites], details, seq=t.seq)
        # Ask the model only about a claim it has not already answered. Two gates, because one
        # is not enough:
        #
        #   origin != editor  -- an unsaved draft is still being typed, and a sentence about it
        #                        would arrive describing code the developer has moved past.
        #   fingerprint       -- the claim's identity. Re-deriving the same claim reuses the
        #                        sentence instead of re-asking. This is what carries the cost,
        #                        because an editor that writes on a timer turns every pause into
        #                        a save, and the origin gate alone would then buy nothing at all.
        if self.llm and sites and n_break and origin != "editor":
            prior = self.evid.suggestion_for(evd.key, evd.fingerprint)
            evd.suggestion = prior if prior else self._suggest(evd)
        r = self.evid.add(evd)
        self.log(f"  {t.kind} [{r}]: {evd.title}: {claim}")

    def _run_tests(self, path: str, sha: str, names: list[str], seq: int) -> None:
        key = f"test_run:{path}:-"
        based = {path: sha}
        if self.replay:
            self.evid.add(Evidence(key, "test_run", f"tests mentioning {', '.join(names)}",
                                   "skipped: replay never executes code", based, seq=seq))
            return
        tr = testrun.run_for(self.root, names)
        for f in tr.files:
            based[self.rel(f)] = callers.sha_of(Path(f).read_bytes()) if Path(f).exists() else ""
        details = {"revision": "saved files only"}
        unsaved = sorted(p for p in based if self.view.is_dirty(p))
        if unsaved:
            # Said plainly rather than left implicit: a green run here does not vouch for the
            # code the developer is looking at.
            details["revision"] = f"saved files only; unsaved buffers not covered: {', '.join(unsaved)}"
        if tr.status == "failed":
            fails = [l.strip() for l in tr.output_tail.splitlines() if l.startswith("FAILED ")]
            details["failed"] = "; ".join(fails)[:300]
            first = next((l.strip() for l in tr.output_tail.splitlines() if l.startswith("E ")), "")
            details["first_error"] = first[:160]
        self.evid.add(Evidence(key, "test_run", f"tests mentioning {', '.join(names)}", f"{tr.status}: {tr.summary}",
                               based, [], details, seq=seq))
        self.log(f"  test_run: {tr.status}: {tr.summary}")

    def _suggest(self, evd: Evidence) -> str | None:
        from .llm.client import suggest
        text = json.dumps({"change": evd.title, "claim": evd.claim,
                           "sites": [{"where": f"{l['path']}:{l['line']}", "verdict": l["verdict"], "why": l["reason"], "code": l["text"]}
                                     for l in evd.locations][:12]})
        rep = suggest(text, **self.llm)
        self.timings.append({"llm": rep.model, "status": rep.status, "wall_s": round(rep.wall_s, 2),
                             "prompt_tokens": rep.prompt_tokens, "gen_tokens": rep.gen_tokens})
        if rep.status != "ok":
            self.log(f"  llm {rep.status} ({rep.wall_s:.1f}s) — board shows deterministic evidence only")
            return None
        return rep.text

    # ---------- present ----------
    def present(self) -> None:
        board.write(self.root, self.dir, self.evid.records(), self.sched.stats)
        self.publish()

    def publish(self) -> None:
        """The editor-facing half of presentation: the current finding set and our own state.
        Both are rewritten whole and atomically, so a reader never sees a partial view."""
        records = self.evid.records()
        paths = {p for r in records for p in r["based_on"]} | set(self.view.overlay)
        manifest = self.view.manifest(paths)
        items = findings_out.build(records, manifest, self.view.diagnostics)
        findings_out.write(self.dir, items)
        status_out.write(self.dir, status_out.snapshot(
            workspace=self.root,
            state=self.state,
            last_event_seq=self.seq,
            pending_tasks=self.sched.pending,
            session=self.view.session,
            dirty=self.view.dirty_paths(),
            findings=len(items),
            revisions=manifest,
            model=self._model_status(),
            last_error=self.last_error,
            intake=self.intake_stats,
        ))

    def _model_status(self) -> dict:
        if not self.llm:
            return {"name": None, "backend": None, "status": "disabled"}
        return {"name": self.llm.get("model"), "backend": self.llm.get("backend"),
                "status": "ready"}
