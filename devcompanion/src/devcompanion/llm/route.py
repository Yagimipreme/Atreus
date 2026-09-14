"""Run a function through its routing chain (config.py).

Each profile is tried in order. The chain moves on when the packet does not fit the profile, when
the call does not return an answer, or when the function's gate refuses the reply; the first
accepted answer ends it. The gate is the function's, passed in by the caller -- the fix checker
for fixes, the sentence check for sentences -- because it is what makes the answer trustworthy,
and configuration must not be able to swap it out. A function with no gate takes the first answer.

The answer names the profile that gave it and whether that profile is remote, so the pane can say
which model answered; every attempt is kept.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from devcompanion.config import Config, Profile
from devcompanion.llm import providers


@dataclass(frozen=True)
class Attempt:
    profile: str
    outcome: str                       # ok | refused | too_large | the reply's status


@dataclass
class Answer:
    function: str
    text: str | None = None
    profile: str | None = None
    remote: bool = False
    attempts: list[Attempt] = field(default_factory=list)
    unavailable: str = ""              # the function's own message, when its chain is empty

    @property
    def ok(self) -> bool:
        return self.text is not None


def estimated_tokens(system: str, user: str) -> int:
    """The estimate the evaluation scripts use to keep a packet inside a local context."""
    return round((len(system) + len(user)) / 3.2)


def run(config: Config, function: str, system: str | Callable[[Profile], str], user: str, tokens: int,
        gate: Callable[[str], bool] | None = None, ask=providers.ask) -> Answer:
    """`system` may depend on the profile: a job the local model and the flagship measured differently
    at gets a prompt per kind of model (pulled/chatty.py `system`)."""
    route = config.route(function)
    answer = Answer(function)
    if not route.available:
        answer.unavailable = route.message
        return answer
    for name in route.chain:
        profile = config.profiles[name]
        prompt = system(profile) if callable(system) else system
        if profile.max_input_tokens and estimated_tokens(prompt, user) > profile.max_input_tokens:
            answer.attempts.append(Attempt(name, "too_large"))
            continue
        reply = ask(profile.spec(tokens), prompt, user, timeout_s=profile.timeout_s)
        if reply.status != "ok" or reply.text is None:
            answer.attempts.append(Attempt(name, reply.status))
            continue
        if gate is not None and not gate(reply.text):
            answer.attempts.append(Attempt(name, "refused"))
            continue
        answer.attempts.append(Attempt(name, "ok"))
        answer.text, answer.profile, answer.remote = reply.text, name, profile.remote
        return answer
    return answer
