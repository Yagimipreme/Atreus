| model | load s | ✓ shown | ✓ intended | ✓ not intended | intended but refused | ✓ with a new warning (intended) | intended, no checker | model s p50 / p90 | check s p50 | tokens in / out |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| qwen2.5-coder:3b | 2.92 | 41/51 | 37 | 4 | 1 | 1 (0) | 38/51 | 0.19 / 0.31 | 0.48 | 250 / 23 |
| qwen3:4b@2048 | 1.68 | 0/51 | 0 | 0 | 0 | 0 (0) | 0/51 | 13.6 / 17.07 | 0.47 | 252 / 1635 |
| qwen3-coder:30b | 5.46 | 48/51 | 47 | 1 | 1 | 2 (2) | 48/51 | 3.34 / 4.96 | 0.48 | 250 / 59 |
| claude:sonnet/low | — | 51/51 | 51 | 0 | 0 | 1 (1) | 51/51 | 2.14 / 2.42 | 0.48 | 838 / 60 |
| claude:opus/medium | — | 50/51 | 50 | 0 | 0 | 1 (1) | 50/51 | 2.94 / 3.31 | 0.48 | 769 / 58 |
| codex: | — | 51/51 | 51 | 0 | 0 | 0 (0) | 51/51 | 5.35 / 8.41 | 0.48 | 12681 / 70 |

`✓` checked and intended · `!` checked, not intended · `○` refused, would have been right · `·` refused, wrong

| case | kind | qwen2.5-coder:3b | qwen3:4b@2048 | qwen3-coder:30b | claude:sonnet/low | claude:opus/medium | codex: |
|---|---|---|---|---|---|---|---|
| split-separator | argument-type | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| round-places | argument-type | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| parse-count | argument-type | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| join-numbers | argument-type | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| byte-order | argument-type | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| timedelta-days | argument-type | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| path-join-year | argument-type | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| len-of-number | argument-type | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| sum-strings | argument-type | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| missing-carry | missing-argument | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| missing-timeout | missing-argument | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| missing-note | missing-argument | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| strptime-format | missing-argument | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| method-on-class | missing-argument | · unresolved | · no_patch | · no_patch | ✓ | ✓ | ✓ |
| extra-middle | too-many-arguments | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| keyword-renamed | unknown-keyword | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| dataclass-field | unknown-keyword | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| sorted-key | unknown-keyword | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| splitlines-keepends | unknown-keyword | · unresolved | · no_patch | ✓ | ✓ | ✓ | ✓ |
| regex-no-match | optional-member-access | · new_diagnostics | · no_patch | ✓ | ✓ | ✓ | ✓ |
| next-default | optional-member-access | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| xml-find | optional-member-access | ○ unresolved | · no_patch | ○ unresolved | ✓ | ✓ | ✓ |
| dict-get-default | optional-operand | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| optional-greeting | optional-operand | ! | · no_patch | ✓ | ✓ | ✓ | ✓ |
| import-path | undefined-name | ✓ | · unresolved | ✓ | ✓ | ✓ | ✓ |
| import-defaultdict | undefined-name | ✓ | · unresolved | ✓ | ✓ | ✓ | ✓ |
| import-field | undefined-name | ! | · no_patch | · unresolved | ✓ | ✓ | ✓ |
| typo-total | undefined-name | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| renamed-helper | undefined-name | · no_patch | · unresolved | ✓ | ✓ | ✓ | ✓ |
| startswith-typo | attribute | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| list-push | attribute | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| dict-iteritems | attribute | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| enum-member-typo | attribute | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| self-attribute-typo | attribute | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| missing-await | async | · unresolved | · no_patch | ✓ | ✓ | ✓ | ✓ |
| property-called | call | · unresolved | · no_patch | ✓ | ✓ | ✓ | ✓ |
| returns-list-not-count | return-type | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| returns-optional | return-type | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| missing-return | return-type | · no_patch | · no_patch | ✓ | ✓ | ✓ | ✓ |
| returns-set | return-type | ! | · no_patch | ✓ | ✓ | · no_patch | ✓ |
| price-times | return-type | ✓ | · no_patch | ! | ✓ | ✓ | ✓ |
| str-plus-int | operator | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| text-sum | operator | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| tuple-unpack | assignment | · suppressed | · no_patch | ✓ | ✓ | ✓ | ✓ |
| annotated-assignment | assignment | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| possibly-unbound-else | possibly-unbound | · unresolved | · no_patch | ✓ | ✓ | ✓ | ✓ |
| unbound-after-except | possibly-unbound | ! | · no_patch | ✓ | ✓ | ✓ | ✓ |
| missing-colon | syntax | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| unclosed-paren | syntax | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| from-without-import | syntax | ✓ | · no_patch | ✓ | ✓ | ✓ | ✓ |
| dict-missing-comma | syntax | ✓ | · unparsable | ✓ | ✓ | ✓ | ✓ |
