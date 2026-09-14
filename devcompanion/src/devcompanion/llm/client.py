"""Optional local model tier. Unavailable model is an ordinary outcome, never an error.

Backends: ollama native /api/chat (reports prompt vs generation time, pattern from
agentbench/providers/ollama.py) and any OpenAI-compatible /v1/chat/completions (llama-server).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class Reply:
    text: str | None
    status: str              # ok | unavailable | timeout | error
    wall_s: float = 0.0
    prompt_tokens: int | None = None
    gen_tokens: int | None = None
    prompt_s: float | None = None
    gen_s: float | None = None
    model: str = ""


SYSTEM = ("You are a quiet coding companion. Given evidence about a code change, write ONE sentence "
          "(max 25 words) telling the developer the single most useful next action. No preamble.")


def suggest(evidence_text: str, model: str, backend: str = "ollama", base_url: str | None = None,
            timeout_s: float = 30, num_ctx: int = 4096, cpu_only: bool = False,
            keep_alive: str = "30m") -> Reply:
    t0 = time.time()
    try:
        if backend == "ollama":
            url = (base_url or "http://127.0.0.1:11434") + "/api/chat"
            opts = {"num_ctx": num_ctx, "temperature": 0, "num_predict": 60}
            if cpu_only:
                opts["num_gpu"] = 0
            # Ollama evicts after five minutes by default. Measured on this host, a cold load of
            # qwen3-coder:30b is 15.437 s against ~1.66 s warm, so with the default the developer
            # pays the cold load on most saves after a pause -- which is the difference between a
            # companion and an interruption. llama-server keeps the model resident already, so
            # this is an ollama-only concern.
            body = {"model": model, "stream": False, "think": False, "options": opts,
                    "keep_alive": keep_alive,
                    "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": evidence_text}]}
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout_s) as r:
                d = json.loads(r.read())
            return Reply(d["message"]["content"].strip(), "ok", time.time() - t0,
                         d.get("prompt_eval_count"), d.get("eval_count"),
                         (d.get("prompt_eval_duration") or 0) / 1e9, (d.get("eval_duration") or 0) / 1e9, model)
        else:
            url = (base_url or "http://127.0.0.1:8080") + "/v1/chat/completions"
            body = {"model": model, "temperature": 0, "max_tokens": 60,
                    "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": evidence_text}]}
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout_s) as r:
                d = json.loads(r.read())
            u = d.get("usage", {})
            tm = d.get("timings", {})
            return Reply(d["choices"][0]["message"]["content"].strip(), "ok", time.time() - t0,
                         u.get("prompt_tokens"), u.get("completion_tokens"),
                         (tm.get("prompt_ms") or 0) / 1e3 or None, (tm.get("predicted_ms") or 0) / 1e3 or None, model)
    except urllib.error.URLError as e:
        st = "timeout" if "timed out" in str(e).lower() else "unavailable"
        return Reply(None, st, time.time() - t0, model=model)
    except TimeoutError:
        return Reply(None, "timeout", time.time() - t0, model=model)
    except Exception as e:  # noqa: BLE001
        return Reply(None, f"error: {type(e).__name__}", time.time() - t0, model=model)
