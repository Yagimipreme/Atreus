# Edits and approval

Status: design, 2026-09-14. Not implemented. Scope agreed in conversation; the shape below is
a proposal.

The companion may now propose edits: new or changed tests, documentation, a fix in the file
being edited, or a change in another file that does not exist yet. This document is how that
happens without the companion ever becoming the author of a change that lands.

## This does not break S10

S10 says a model never becomes the source of a fact, an edit, or an "actual result". Vision §5
already carried the escape hatch — *developer files change only through explicit action or a
narrowly configured policy* — and nobody had exercised it. The reconciliation is precise:

> The model proposes. The developer approves. **The approval is the source of the edit**, and
> the engine applies it deterministically, or refuses.

The model authors a *candidate*, never a change. Nothing auto-applies, ever, at any tier.

## The invariant

> **The engine never writes a developer file. Every edit is applied to a buffer, by the
> adapter, unsaved.**

One rule covers every case, and it buys more than a policy would:

| Case | How |
|---|---|
| The file being edited | adapter applies to the live buffer with `nvim_buf_set_text` |
| Another file, already open | same, in its buffer |
| Another file, not open | adapter `bufadd` + `bufload`, then apply; buffer left unsaved |
| A file that does not exist | adapter creates the buffer; nothing touches disk |
| A new test | identical, gated by the test policy tier |

Why through the buffer rather than the filesystem: if the engine wrote to disk under a dirty
buffer, Neovim would either prompt about the file changing underneath or the developer would
lose work. Going through the buffer means the edit is **undoable with `u`** — a better safety
net than any approval dialog, because it is the one the developer already trusts.

"Approve" means *put it in front of me*. It does not mean *commit it*.

## Freshness refusal is the part that must exist first

A proposed edit is computed from a revision. Between proposing and approving, the buffer moves.
**Applying a stale patch is the worst thing this system could do.** Every failure mode until
now cost an ignored line; this one corrupts code.

The machinery already exists. Every action carries the analysis manifest it was derived from
(`view.manifest()`). On approval the engine re-checks each input's current effective revision:

- all inputs unchanged → apply
- anything moved → **refuse**, name what moved, offer to recompute

Never best-effort, never partial. This is why the content view and the intake watermark had to
land first, and why the refusal path ships before the first edit rather than after it.

## Delegation is a different animal

"Approve sending the agent for an edit in another file" is not a patch. It is a CLI agent with
tools enabled doing multi-file work — the exact thing [providers.md](providers.md) says must
never happen. Here it is intentional, so it gets its own containment:

> **The agent runs in a throwaway git worktree, never the working tree.**

It edits freely in the sandbox. The **diff** comes back as an ordinary finding. Approving the
diff applies it to buffers by the invariant above.

That gives the agent real freedom, leaves the working tree untouchable, and turns an agent run
into a review surface that already exists. The worktree habit is established on this machine
already (pyERP uses `gwq`; hive is pull-only).

## Contract changes

Additive. v2 preserves unknown fields, so no version bump is required.

- `action` gains a shape: `{id, label, kind, manifest}`. It stops being `null` everywhere.
- **`outbox.jsonl` finally gets its writer.** `lsp_request` gains siblings `edit` and `create`.
- New adapter event `action_result`: `applied` | `refused_stale` | `declined`.
- Pane: `[a]` applies a local patch, `[A]` delegates to an agent. Different keys, because the
  cost and the blast radius are different and the developer should never confuse them.

## Documentation edits carry a longer tail

Docs are where a confidently wrong model output survives longest: a bad suggestion is ignored
in seconds, a bad document is cited for months. This machine's own KB rules already require
frontmatter and cited sources.

So documentation edits are **pull-only, subscription-tier, and must cite the manifest they were
derived from**. A doc edit that cannot say what evidence produced it is not offered.

## Build order

1. Outbox writer, adapter buffer-apply, **freshness refusal** — proves the invariant
2. Current-file edit from a caller finding — the first thing worth judging in live use
3. Other and not-yet-existing files — same path, different target
4. Test drafting (`draft` tier)
5. Documentation updates
6. Agent delegation in a worktree — last, and not before its tripwire test

Step 2 is the minimum that makes the whole loop judgeable. Everything after it is the same
machinery aimed somewhere else.

## Open

- Whether a proposed edit is worth having before it can be applied — deferred until the
  paragraphs have been seen in live use.
- What `incorporate` means for review visibility (S3, still open in the vision).
- Multi-hunk and multi-file patches in one action, versus one action per hunk.

## Sources

Vision S3, S10, §5; [contract v2](contract.md); [providers.md](providers.md);
conversation 2026-09-14.
