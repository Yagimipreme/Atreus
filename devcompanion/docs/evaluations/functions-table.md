### sentence

| model | passes | model s p50 / p90 | tokens in / out |
|---|---|---|---|
| qwen2.5-coder:3b | 18/30 | 0.16 / 0.24 | 102 / 18 |
| qwen3-coder:30b | 13/30 | 1.56 / 1.97 | 102 / 16 |
| claude:sonnet/low | 13/30 | 2.07 / 2.35 | 589 / 29 |
| claude:opus/medium | 22/30 | 3.81 / 5.01 | 522 / 167 |
| codex: | 19/30 | 5.73 / 7.06 | 12533 / 175 |

### suspicious

| model | bugs found at the exact line | ±1 line | untouched functions left alone | flags that were right | model s p50 / p90 |
|---|---|---|---|---|---|
| qwen2.5-coder:3b | 4/30 | 6 | 6/10 | 4/31 | 0.11 / 0.2 |
| qwen3-coder:30b | 16/30 | 4 | 1/10 | 16/39 | 2.27 / 3.87 |
| claude:sonnet/low | 24/30 | 1 | 5/10 | 24/35 | 2.04 / 2.72 |
| claude:opus/medium | 29/30 | 0 | 7/10 | 29/32 | 3.31 / 7.22 |
| codex: | 22/30 | 1 | 3/10 | 22/36 | 5.65 / 12.7 |

### culprit

| model | culprit named | of the packets sent | not sent: too large | model s p50 / p90 | tokens in p50 |
|---|---|---|---|---|---|
| qwen2.5-coder:3b | 9/30 | 9/30 | 0 | 0.56 / 1.12 | 1757 |
| qwen3-coder:30b | 21/30 | 21/30 | 0 | 9.03 / 11.58 | 1757 |
| claude:sonnet/low | 28/30 | 28/30 | 0 | 2.47 / 3.04 | 3065 |
| claude:opus/medium | 28/30 | 28/30 | 0 | 3.5 / 5.24 | 2999 |
| codex: | 10/10 | 10/10 | 0 | 13.55 / 26.09 | 41753 |

