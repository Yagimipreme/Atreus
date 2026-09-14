"""Evidence records: what the companion claims, on what basis, and whether it is still fresh.

evidence.jsonl  append-only log of every record ever produced (audit / replay comparison)
state.json      current records keyed by record key; stale records stay, marked stale
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Evidence:
    key: str                       # stable identity: kind + path + qualname
    kind: str                      # signature_change | removed_function | new_function | unknown_intent | noop | cancelled
    title: str
    claim: str                     # one line for the board
    based_on: dict[str, str]       # path -> sha the claim depends on
    locations: list[dict] = field(default_factory=list)   # {path,line,col,verdict,text,reason}
    details: dict = field(default_factory=dict)
    status: str = "fresh"          # fresh | stale | superseded
    ts: float = field(default_factory=time.time)
    seq: int | None = None
    suggestion: str | None = None  # optional LLM sentence; None when model unavailable
    fingerprint: str = ""

    def __post_init__(self):
        if not self.fingerprint:
            # `details` counts: "this rests on an unsaved buffer" and "this rests on the saved
            # file" are different claims about the same call sites, and a reader who is not
            # told the difference is being misled by a record that looks unchanged.
            body = json.dumps({"claim": self.claim, "details": self.details,
                               "locs": [(l["path"], l["line"], l["verdict"]) for l in self.locations]},
                              sort_keys=True)
            self.fingerprint = hashlib.sha1(body.encode()).hexdigest()[:12]


class EvidenceStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.log = root / "evidence.jsonl"
        self.state_path = root / "state.json"
        self.state: dict[str, dict] = {}
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text())

    def _persist(self):
        self.state_path.write_text(json.dumps(self.state, indent=1, sort_keys=True))

    def add(self, ev: Evidence) -> str:
        """Returns 'new' | 'unchanged' | 'updated'. Unchanged fingerprints do not re-nag."""
        cur = self.state.get(ev.key)
        if cur and cur["fingerprint"] == ev.fingerprint and cur["status"] == "fresh":
            cur["based_on"] = ev.based_on
            cur["ts"] = ev.ts
            # The fingerprint deliberately excludes the model sentence, so re-deriving the same
            # claim does not re-nag. But a claim first derived while the model was unavailable
            # would then never get its sentence, however many times it is re-derived. Adopt one
            # when we have one and the record has none; never overwrite a sentence with nothing.
            if ev.suggestion and not cur.get("suggestion"):
                cur["suggestion"] = ev.suggestion
            self._persist()
            return "unchanged"
        with self.log.open("a") as f:
            f.write(json.dumps(asdict(ev), sort_keys=True) + "\n")
        self.state[ev.key] = asdict(ev)
        self._persist()
        return "updated" if cur else "new"

    def mark_stale(self, path: str, new_sha: str) -> list[dict]:
        """Any fresh record that depended on `path` at a different sha is now stale.
        Per-file status records (noop/unknown_intent/cancelled) are simply dropped: the new
        observation of that file replaces them. Returns the records that went stale."""
        changed, drop = [], []
        for k, rec in self.state.items():
            dep = rec["based_on"].get(path)
            if rec["status"] == "fresh" and dep is not None and dep != new_sha:
                if rec["kind"] in ("noop", "unknown_intent", "cancelled"):
                    drop.append(k)
                else:
                    rec["status"] = "stale"
                    changed.append(rec)
        for k in drop:
            del self.state[k]
        if changed or drop:
            self._persist()
        return changed

    def records(self) -> list[dict]:
        return sorted(self.state.values(), key=lambda r: (-r["ts"]))
