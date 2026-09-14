"""Checked fixes: a model proposes a patch, deterministic tools decide whether it may be shown.

The model is never trusted with the verdict. A proposal becomes `✓ fix checked` only after it
applies to the text it was proposed against, still parses, does not silence the checker, removes
the diagnostics it was asked to remove, and adds none. That says the code is consistent, not that
it does what the developer meant; see docs/model-routing.md for the trust levels and
docs/evaluations/checked-fixes.md for how often the two differ.
"""
