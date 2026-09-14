# Local model evaluation — 2026-09-14

**Qwen3-Coder 30B runs successfully on this desktop at 4K context.** Downloaded and loaded as requested; no hosted API calls were made. Ollama keeps the model resident temporarily and may unload it after its idle timeout; the downloaded model remains installed.

Hardware: Ryzen 7 5800X3D, 46 GiB physical RAM, RTX 2080 SUPER 8 GiB. Before loading: 38 GiB available RAM and 94 GiB free disk. GPU inspection required access outside the sandbox. Qwen3-Coder reports approximately 19 GB resident size and a 70% CPU / 30% GPU split; this is partial offload, not full GPU residency.

| Measurement | Qwen3-Coder 30B | qwen2.5-coder 3B |
|---|---:|---:|
| Quantization | Q4_K_M | Q4_K_M |
| Context setting | 4,096 | 4,096 |
| Initial load request wall time | 15.437 s | 3.727 s |
| Requests | 12 (3 repeats × 2 cases × 2 variants) | 40 (10 repeats × 2 cases × 2 variants) |
| Breaking-only median latency | 1.661 s | 0.150 s |
| Breaking-only maximum latency | 1.740 s | 0.179 s |
| Mixed-sites median latency | 1.853 s | 0.199 s |
| Mixed-sites maximum latency | 2.384 s | 0.214 s |

The smaller model was unloaded before loading Qwen3-Coder. Model IDs, runtime version, raw request payloads, all responses, token counts and residency details are captured in [Qwen3-Coder raw results](qwen3-coder-30b.json) and [3B baseline raw results](qwen25-coder-3b.json).

## What the outputs show

Two narrow scenarios: a newly required `carry` argument and a keyword rename from `memo` to `note`. Mixed-site prompts also contain an already-correct caller; breaking-only prompts exclude it. The harness uses the existing suggestion client, temperature zero, 60 output tokens and a 30-second deadline. Load time is measured separately. Repetition and prompt interleaving check local consistency, not statistical independence.

Qwen3-Coder gave the correct location and repair in all 12 observed replies, including mixed-site prompts. Example:

> Update the call site in tests/test_calc.py:7 to include the required 'carry' parameter.

One keyword response retained escaped quote characters in its prose, so formatting still needs validation. No response exceeded 25 whitespace-delimited words or timed out.

The 3B model was much faster. With mixed sites, it repeatedly suggested editing both the broken file and an already-correct file. Breaking-only prompts removed passing-file mentions, but the required-argument wording remained imprecise: “Update the function to include the 'carry' parameter in the call site.” Thus passing the narrow token checks is not equivalent to a fully correct, well-written answer.

## Decision for the next local evaluation

Use **qwen3-coder:30b** as the requested primary local evaluation model at 4K context. Its approximately 1.7-second breaking-only latency is plausible for an optional background explanation. Keep deterministic findings immediate and append model text when ready. Retain **qwen2.5-coder:3b** as the fast comparison/fallback candidate. No project-wide default or application implementation was changed.

Continue to filter to breaking sites even though Qwen3-Coder handled these mixed inputs: it reduces irrelevant context and makes the evidence boundary clearer. The small smoke test does not establish correctness on arbitrary edits, larger contexts, unsaved integration, multiple model loads or CPU-only laptops. The design's larger ten-repeat evaluation remains follow-up work for Qwen3-Coder; the present result is a load/latency/behavior smoke test.

## Knowledge retrieval smoke check

An isolated QMD collection indexed copies of five project Markdown documents. Three keyword queries (`unsaved`, `watermark`, `model`) each completed in 0.112–0.117 s. [Raw results](qmd-keyword-smoke.json). This did not modify the user's existing QMD collection or generate embeddings.

Both proposed behavior and historical documents appear in results. Therefore source status, revision and scope must be checked before passages enter a model prompt. No hybrid/reranker timing, retrieval-quality benchmark or retrieval-augmented generation evaluation was performed.

See [the context and QMD design](../local-model-and-context.md) for input budgets and the staged experiment.
