"""Pulled functions that answer in prose: explain a selection, grill it, plan a change to it,
summarise a diff, draft its commit message.

Every reply is ◇ advice -- nothing checks it -- so it appears only because the developer asked
(model-routing.md). A function is a system prompt, an output budget and a packet. scripts/chatty.py
has these exact prompts judged on qwen3-coder:30b, so what is judged is what ships; changing a
prompt changes its `prompt_id`, and judgments of the old prompt stop counting.

A function may have a second prompt for the flagship (`FLAGSHIP`, picked by `system`), because the
two kinds of model measured differently at the same job (docs/evaluations/chatty-functions.md):
- **Grill on the flagship:** one richer challenge per turn, with a way to stop.
- **Grill on the 30B:** the three-question prompt, the `local-only` fallback. Asked for a single
  question, the 30B mostly chose the wrong one and never used the stop word.

What code can enforce, code enforces: `shape_commit`.
"""
from __future__ import annotations

import hashlib

FUNCTIONS = ("explain", "grill", "plan", "summary", "commit")

NO_CHALLENGE = "NO CHALLENGE"
COMMIT_SUBJECT_MAX = 60

SYSTEM = {
    "explain": ("You explain code a developer selected in their editor. Say what it does and why it is "
                "written this way, then anything a careful reader could still get wrong about it. Plain "
                "prose, at most 120 words, names in backticks. Do not walk through it line by line and do "
                "not suggest changes."),
    "grill": ("You grill code a developer selected: do not fix it and do not explain it. Ask the questions "
              "most likely to expose a wrong assumption, a missing case or a design weakness -- at most "
              "three, most important first, as a numbered list. Each question is one sentence and names, "
              "in backticks, the code it is about. If there is nothing real to challenge, say so in one "
              "sentence rather than inventing a problem."),
    "plan": ("A developer wants to change the code below toward the stated goal. Write the plan, not the "
             "code: numbered steps in the order to do them, at most 8, each naming the function, class or "
             "call site it touches, including every caller that must change and the test that shows the "
             "goal is met. If the goal is already met, or cannot be met as stated without a risk the "
             "developer should decide on, say that first in one sentence."),
    "summary": ("You summarise a code change for the developer who made it, from its unified diff. Say what "
                "changed in behaviour, not which lines moved: at most 4 bullet points, most important first, "
                "names in backticks. Point out any behaviour change inside what looks like a refactor, and "
                "say so plainly when behaviour does not change. State nothing the diff does not show."),
    "commit": ("From the unified diff below, describe only the observable changes. Do not infer motivation "
               "or benefits. Reply in exactly this form and nothing else:\n"
               f"subject: <imperative mood, at most {COMMIT_SUBJECT_MAX} characters>\n"
               "body: <leave empty when the subject says it all; otherwise short lines naming the changes "
               "the subject leaves out, and saying so when the diff mixes unrelated changes>"),
}

TOKENS = {"explain": 300, "grill": 220, "plan": 450, "summary": 250, "commit": 100}

# Prompts for the flagship where they differ from the local one. The flagship is not benchmarked on
# these functions (docs/handoff.md); it gets what the local model could not do.
FLAGSHIP = {
    "grill": ("You grill code a developer selected, one challenge per turn. Find the single strongest "
              "challenge to it: the wrong assumption, missing case, race or design weakness that would cost "
              "the most if nobody examined it. Reply in exactly this form:\n"
              "question: <one sentence, naming in backticks the code it is about>\n"
              "why it matters: <one or two sentences: the concrete failure, cost or risk if the answer is wrong>\n"
              "to settle it: <one sentence: what the developer's answer has to establish>\n"
              "Do not fix the code and do not explain it. Questions already asked, with the developer's "
              "answers, may follow the code: challenge something they leave open, or press on an answer that "
              f"does not settle its question. If nothing meaningful is left to challenge, reply exactly: "
              f"{NO_CHALLENGE}."),
}


def system(function: str, remote: bool = False) -> str:
    """The system prompt for a function on this kind of model: the flagship's own where it has one."""
    return FLAGSHIP.get(function, SYSTEM[function]) if remote else SYSTEM[function]


def prompt_id(function: str) -> str:
    return hashlib.sha256(f"{SYSTEM[function]}\0{TOKENS[function]}".encode()).hexdigest()[:8]


def diff_stats(diff: str) -> str:
    """The deterministic part of a change summary: which files, how many lines each way."""
    files: list[str] = []
    added = removed = 0
    old = ""
    in_hunk = False
    for line in diff.splitlines():
        if line.startswith("diff "):
            in_hunk = False
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk:
            if line.startswith("+"):
                added += 1
            elif line.startswith("-"):
                removed += 1
        elif line.startswith("--- "):
            old = line[4:].split("\t")[0].removeprefix("a/")
        elif line.startswith("+++ "):
            new = line[4:].split("\t")[0].removeprefix("b/")
            files.append(old if new == "/dev/null" else new)
    return f"{len(files)} file{'s' * (len(files) != 1)} changed, +{added} -{removed}: {', '.join(files)}"


def packet(function: str, text: str, path: str = "", goal: str = "",
           history: list[tuple[str, str]] | tuple = ()) -> str:
    """`history` is grill's conversation so far: (question asked, developer's answer) pairs."""
    if function in ("summary", "commit"):
        return f"Diff statistics: {diff_stats(text)}\n\n{text}"
    head = f"File: {path}\n" if path else ""
    if function == "plan":
        head += f"Goal: {goal}\n"
    body = f"{head}\n{text}" if head else text
    if history:
        body += "\n\nAlready asked:\n" + "\n".join(f"Q: {q}\nA: {a}" for q, a in history)
    return body


def no_challenge(reply: str | None) -> bool:
    return (reply or "").strip().strip(".`*").upper() == NO_CHALLENGE


def shape_commit(reply: str) -> dict:
    """Read the `subject:` / `body:` reply, and enforce what needs no model: no trailing period, no
    placeholder body. A subject over the limit is reported, not cut -- cutting "…and add customer
    blocking check" hides a behaviour change, which is worse than a long subject."""
    subject, body, in_body = "", [], False
    for line in reply.strip().strip("`").splitlines():
        key, colon, rest = line.partition(":")
        if colon and key.strip().lower() == "subject" and not subject:
            subject, in_body = rest.strip(), False
        elif colon and key.strip().lower() == "body":
            in_body = True
            if rest.strip():
                body.append(rest.strip())
        elif in_body and line.strip():
            body.append(line.strip())
    subject = subject.strip("\"'` ").rstrip(".").rstrip()
    body = [] if [b.lower().strip("().") for b in body] in (["empty"], ["none"], ["nothing"]) else body
    problems = []
    if not subject:
        problems.append("no subject")
    elif len(subject) > COMMIT_SUBJECT_MAX:
        problems.append(f"subject {len(subject)} characters")
    return {"subject": subject, "body": body, "problems": problems}


def estimated_tokens(system: str, user: str) -> int:
    """The same estimate scripts/evaluate-functions.py uses to keep a packet inside a local context."""
    return round((len(system) + len(user)) / 3.2)
