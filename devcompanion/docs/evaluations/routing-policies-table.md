# Routing policies — computed from stored replies

Local model swaps charged at 3.6 s (3B) and 5.9 s (30B).

## Checked fixes

### The warnings rule, per model

| model | strict: shown | strict: wrong ✓ | qualify: shown | qualify: wrong ✓ | qualify adds, intended |
|---|---:|---:|---:|---:|---:|
| 3B | 40 | 3 | 41 | 4 | 0 of 1 |
| qwen3:4b@2048 | 0 | 0 | 0 | 0 | 0 of 0 |
| 30B | 46 | 1 | 48 | 1 | 2 of 2 |
| claude:sonnet/low | 50 | 0 | 51 | 0 | 1 of 1 |
| claude:opus/medium | 49 | 0 | 50 | 0 | 1 of 1 |
| codex: | 51 | 0 | 51 | 0 | 0 of 0 |

### Escalation chains, strict gate

A chain moves on when the gate refuses; `right` means the behaviour check passed.

| chain | shown | right | shown but wrong | seconds p50 / p90 | local model swaps | cases reaching a subscription model | API-equivalent cost $ |
|---|---:|---:|---:|---:|---:|---:|---:|
| 3B | 40/51 | 37 | 3 | 0.67 / 0.8 | 0 | 0% | 0.0 |
| 30B | 46/51 | 45 | 1 | 3.82 / 5.45 | 0 | 0% | 0.0 |
| claude:sonnet/low | 50/51 | 50 | 0 | 2.63 / 2.92 | 0 | 100% | 0.179 |
| claude:opus/medium | 49/51 | 49 | 0 | 3.42 / 3.79 | 0 | 100% | 0.535 |
| codex: | 51/51 | 51 | 0 | 5.82 / 8.88 | 0 | 100% | 0.0 |
| 3B → 30B | 47/51 | 44 | 3 | 0.76 / 12.27 | 22 | 0% | 0.0 |
| 3B → claude:sonnet/low | 50/51 | 47 | 3 | 0.69 / 3.29 | 0 | 22% | 0.039 |
| 30B → claude:sonnet/low | 50/51 | 49 | 1 | 3.85 / 6.5 | 0 | 10% | 0.017 |
| 3B → 30B → claude:sonnet/low | 50/51 | 47 | 3 | 0.76 / 13.58 | 22 | 8% | 0.014 |
| 3B → claude:opus/medium | 50/51 | 47 | 3 | 0.69 / 4.22 | 0 | 22% | 0.116 |
| 30B → claude:opus/medium | 50/51 | 49 | 1 | 3.85 / 6.74 | 0 | 10% | 0.054 |
| 3B → 30B → claude:opus/medium | 50/51 | 47 | 3 | 0.76 / 14.4 | 22 | 8% | 0.043 |
| 3B → codex: | 51/51 | 48 | 3 | 0.69 / 6.94 | 0 | 22% | 0.0 |
| 30B → codex: | 51/51 | 50 | 1 | 3.85 / 6.74 | 0 | 10% | 0.0 |
| 3B → 30B → codex: | 51/51 | 48 | 3 | 0.76 / 14.4 | 22 | 8% | 0.0 |

### Escalation chains, qualify gate

A chain moves on when the gate refuses; `right` means the behaviour check passed.

| chain | shown | right | shown but wrong | seconds p50 / p90 | local model swaps | cases reaching a subscription model | API-equivalent cost $ |
|---|---:|---:|---:|---:|---:|---:|---:|
| 3B | 41/51 | 37 | 4 | 0.67 / 0.8 | 0 | 0% | 0.0 |
| 30B | 48/51 | 47 | 1 | 3.82 / 5.45 | 0 | 0% | 0.0 |
| claude:sonnet/low | 51/51 | 51 | 0 | 2.63 / 2.92 | 0 | 100% | 0.179 |
| claude:opus/medium | 50/51 | 50 | 0 | 3.42 / 3.79 | 0 | 100% | 0.535 |
| codex: | 51/51 | 51 | 0 | 5.82 / 8.88 | 0 | 100% | 0.0 |
| 3B → 30B | 49/51 | 45 | 4 | 0.74 / 11.31 | 20 | 0% | 0.0 |
| 3B → claude:sonnet/low | 51/51 | 47 | 4 | 0.68 / 3.27 | 0 | 20% | 0.035 |
| 30B → claude:sonnet/low | 51/51 | 50 | 1 | 3.84 / 5.8 | 0 | 6% | 0.01 |
| 3B → 30B → claude:sonnet/low | 51/51 | 47 | 4 | 0.74 / 12.27 | 20 | 4% | 0.007 |
| 3B → claude:opus/medium | 51/51 | 47 | 4 | 0.68 / 4.17 | 0 | 20% | 0.106 |
| 30B → claude:opus/medium | 51/51 | 50 | 1 | 3.84 / 5.8 | 0 | 6% | 0.032 |
| 3B → 30B → claude:opus/medium | 51/51 | 47 | 4 | 0.74 / 12.27 | 20 | 4% | 0.022 |
| 3B → codex: | 51/51 | 47 | 4 | 0.68 / 6.59 | 0 | 20% | 0.0 |
| 30B → codex: | 51/51 | 50 | 1 | 3.84 / 5.8 | 0 | 6% | 0.0 |
| 3B → 30B → codex: | 51/51 | 47 | 4 | 0.74 / 12.27 | 20 | 4% | 0.0 |

## Functions

### Sentences where the rules run out

The gate is the sentence check itself; see the docstring.

| chain | shown | pass | shown but wrong | seconds p50 / p90 | local model swaps | cases reaching a subscription model | API-equivalent cost $ |
|---|---:|---:|---:|---:|---:|---:|---:|
| 3B | 18/30 | 18 | 0 | 0.16 / 0.24 | 0 | 0% | 0.0 |
| 30B | 13/30 | 13 | 0 | 1.56 / 1.97 | 0 | 0% | 0.0 |
| claude:sonnet/low | 13/30 | 13 | 0 | 2.07 / 2.35 | 0 | 100% | 0.075 |
| claude:opus/medium | 22/30 | 22 | 0 | 3.81 / 5.01 | 0 | 100% | 0.285 |
| codex: | 19/30 | 19 | 0 | 5.73 / 7.06 | 0 | 100% | 0.0 |
| 3B → 30B | 24/30 | 24 | 0 | 3.73 / 11.19 | 24 | 0% | 0.0 |
| 3B → claude:sonnet/low | 21/30 | 21 | 0 | 0.2 / 2.33 | 0 | 40% | 0.03 |
| 30B → claude:sonnet/low | 19/30 | 19 | 0 | 3.31 / 4.17 | 0 | 57% | 0.043 |
| 3B → 30B → claude:sonnet/low | 25/30 | 25 | 0 | 3.73 / 11.19 | 24 | 20% | 0.015 |
| 3B → claude:opus/medium | 29/30 | 29 | 0 | 0.2 / 4.62 | 0 | 40% | 0.113 |
| 30B → claude:opus/medium | 25/30 | 25 | 0 | 4.28 / 6.66 | 0 | 57% | 0.174 |
| 3B → 30B → claude:opus/medium | 29/30 | 29 | 0 | 3.73 / 11.83 | 24 | 20% | 0.062 |
| 3B → codex: | 25/30 | 25 | 0 | 0.2 / 6.85 | 0 | 40% | 0.0 |
| 30B → codex: | 21/30 | 21 | 0 | 6.51 / 8.02 | 0 | 57% | 0.0 |
| 3B → 30B → codex: | 26/30 | 26 | 0 | 3.73 / 13.48 | 24 | 20% | 0.0 |

### Failing test → culprit function

A chain moves on only when the packet does not fit the model (or the call failed).

| chain | shown | named | shown but wrong | seconds p50 / p90 | local model swaps | cases reaching a subscription model | API-equivalent cost $ |
|---|---:|---:|---:|---:|---:|---:|---:|
| 3B | 30/30 | 9 | 21 | 0.56 / 1.12 | 0 | 0% | 0.0 |
| 30B | 30/30 | 21 | 9 | 9.03 / 11.58 | 0 | 0% | 0.0 |
| claude:sonnet/low | 30/30 | 28 | 2 | 2.47 / 3.04 | 0 | 100% | 0.484 |
| claude:opus/medium | 30/30 | 28 | 2 | 3.5 / 5.24 | 0 | 100% | 1.118 |
| 3B → 30B | 30/30 | 9 | 21 | 0.56 / 1.12 | 0 | 0% | 0.0 |
| 3B → claude:sonnet/low | 30/30 | 9 | 21 | 0.56 / 1.12 | 0 | 0% | 0.0 |
| 30B → claude:sonnet/low | 30/30 | 21 | 9 | 9.03 / 11.58 | 0 | 0% | 0.0 |
| 3B → 30B → claude:sonnet/low | 30/30 | 9 | 21 | 0.56 / 1.12 | 0 | 0% | 0.0 |
| 3B → claude:opus/medium | 30/30 | 9 | 21 | 0.56 / 1.12 | 0 | 0% | 0.0 |
| 30B → claude:opus/medium | 30/30 | 21 | 9 | 9.03 / 11.58 | 0 | 0% | 0.0 |
| 3B → 30B → claude:opus/medium | 30/30 | 9 | 21 | 0.56 / 1.12 | 0 | 0% | 0.0 |
| 3B → codex: | 30/30 | 9 | 21 | 0.56 / 1.12 | 0 | 0% | 0.0 |
| 30B → codex: | 30/30 | 21 | 9 | 9.03 / 11.58 | 0 | 0% | 0.0 |
| 3B → 30B → codex: | 30/30 | 9 | 21 | 0.56 / 1.12 | 0 | 0% | 0.0 |

### Most suspicious line

A pair flags a line only when both models name the same one. Within one line counts the statement a broken condition guards, which is where the 30B tends to point.

| models | bugs found at the exact line | within one line | untouched functions flagged | seconds p50 |
|---|---:|---:|---:|---:|
| 3B | 4/30 | 10/30 | 4/10 | 0.11 |
| 30B | 16/30 | 20/30 | 9/10 | 2.27 |
| claude:sonnet/low | 24/30 | 25/30 | 5/10 | 2.04 |
| claude:opus/medium | 29/30 | 29/30 | 3/10 | 3.31 |
| codex: | 22/30 | 23/30 | 7/10 | 5.65 |
| 3B ∧ 30B | 2/30 | 4/30 | 0/10 | 11.85 |
| 3B ∧ claude:sonnet/low | 3/30 | 3/30 | 1/10 | 2.16 |
| 3B ∧ claude:opus/medium | 4/30 | 4/30 | 1/10 | 3.41 |
| 3B ∧ codex: | 3/30 | 3/30 | 1/10 | 5.74 |
| 30B ∧ claude:sonnet/low | 15/30 | 15/30 | 0/10 | 4.41 |
| 30B ∧ claude:opus/medium | 16/30 | 16/30 | 0/10 | 5.74 |
| 30B ∧ codex: | 15/30 | 15/30 | 1/10 | 8.35 |
| claude:sonnet/low ∧ claude:opus/medium | 23/30 | 23/30 | 1/10 | 5.42 |
| claude:sonnet/low ∧ codex: | 21/30 | 22/30 | 2/10 | 7.68 |
| claude:opus/medium ∧ codex: | 22/30 | 22/30 | 1/10 | 9.36 |

