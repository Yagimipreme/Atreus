from pathlib import Path

import pytest

from devcompanion import config
from devcompanion.llm import route
from devcompanion.llm.client import Reply


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


def machine(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "machine.toml"
    path.write_text(text)
    return path


def granted(tmp_path: Path, root: Path, extra: str = "") -> Path:
    return machine(tmp_path, f'[machine]\nmode = "hybrid"\n[grant."{root.resolve()}"]\nremote = true\n{extra}')


def test_with_no_configuration_everything_is_local_and_explain_says_what_it_needs(tmp_path, project):
    cfg = config.load(project, machine=tmp_path / "absent.toml")
    assert cfg.mode == "local-only" and not cfg.remote_allowed
    assert cfg.route("pulled.fix").chain == ["local-qwen3-coder"]
    assert "local-only" in next(s.removed for s in cfg.route("pulled.fix").steps if s.profile == "flagship")
    explain = cfg.route("pulled.explain")
    assert not explain.available
    assert explain.message == ("Explain needs a reasoning model.\n"
                               "Available locally: symbols · references · types · diagnostics")


def test_hybrid_without_a_grant_keeps_everything_local_and_notes_the_projects_request(tmp_path, project):
    (project / ".companion.toml").write_text("[request]\nremote = true\n")
    cfg = config.load(project, machine=machine(tmp_path, '[machine]\nmode = "hybrid"\n'))
    assert not cfg.remote_allowed and cfg.requested_remote
    assert "grants no remote sharing" in cfg.remote_reason and "the project requests it" in cfg.remote_reason
    assert not cfg.route("pulled.plan").available


def test_hybrid_with_a_grant_routes_the_flagship_but_never_a_passive_function(tmp_path, project):
    cfg = config.load(project, machine=granted(tmp_path, project, '[routing]\n"passive.fix" = ["flagship", "local-qwen3-coder"]\n'))
    assert cfg.remote_allowed
    assert cfg.route("pulled.explain").chain == ["flagship"]
    assert cfg.route("pulled.suspicious").chain == ["flagship", "local-qwen3-coder"]
    assert cfg.route("pulled.fix").chain == ["local-qwen3-coder", "flagship"]
    passive = cfg.route("passive.fix")
    assert passive.chain == ["local-qwen3-coder"] and passive.scope == "machine"
    assert passive.steps[0].removed == "a passive function never leaves the machine"


def test_a_project_file_cannot_set_the_mode_grant_sharing_or_define_a_profile(tmp_path, project):
    (project / ".companion.toml").write_text(
        f'[machine]\nmode = "hybrid"\n[grant."{project.resolve()}"]\nremote = true\n'
        '[profile.flagship]\nkind = "cli"\nprovider = "codex:"\n')
    cfg = config.load(project, machine=tmp_path / "absent.toml")
    assert cfg.mode == "local-only" and not cfg.remote_allowed
    assert cfg.profiles["flagship"].provider == "claude:sonnet/low"
    assert len([p for p in cfg.problems if "machine scope" in p]) == 3


def test_a_project_may_route_between_profiles_the_machine_defines(tmp_path, project):
    (project / ".companion.toml").write_text('[routing]\n"pulled.grill" = ["local-fast"]\n"pulled.nonsense" = []\n')
    cfg = config.load(project, machine=tmp_path / "absent.toml")
    assert cfg.route("pulled.grill").chain == ["local-fast"] and cfg.route("pulled.grill").scope == "project"
    assert any("unknown function pulled.nonsense" in p for p in cfg.problems)


def test_the_flagship_is_a_role_rebound_to_codex_in_one_line(tmp_path, project):
    cfg = config.load(project, machine=granted(tmp_path, project, '[profile.flagship]\nprovider = "codex:"\n'))
    assert cfg.profiles["flagship"].spec(tokens=100).backend == "codex"
    assert cfg.profiles["flagship"].scope == "machine"
    assert cfg.route("pulled.explain").chain == ["flagship"]


def test_an_ollama_profile_on_another_host_is_remote(tmp_path, project):
    cfg = config.load(project, machine=machine(tmp_path, '[profile.local-qwen3-coder]\nendpoint = "http://gpu-box:11434"\n'))
    assert cfg.profiles["local-qwen3-coder"].remote
    assert not cfg.route("passive.fix").available
    assert not config.load(project, machine=tmp_path / "absent.toml").profiles["local-qwen3-coder"].remote


def test_the_session_can_narrow_the_mode_and_pick_a_local_model_but_not_widen(tmp_path, project):
    cfg = config.load(project, machine=granted(tmp_path, project),
                      session={"local_only": True, "models": {"local-qwen3-coder": "qwen3-coder:30b-q8", "flagship": "x"}})
    assert cfg.mode == "local-only" and cfg.mode_scope == "session" and not cfg.remote_allowed
    assert cfg.profiles["local-qwen3-coder"].model == "qwen3-coder:30b-q8"
    assert any("session model for flagship" in p for p in cfg.problems)


def test_a_broken_profile_is_reported_and_left_out(tmp_path, project):
    cfg = config.load(project, machine=machine(tmp_path, '[profile.odd]\nkind = "cli"\nprovider = "qwen3-coder:30b"\n'))
    assert "odd" not in cfg.profiles
    assert any("profile odd" in p for p in cfg.problems)


def fake(replies: dict[str, Reply]):
    asked = []

    def ask(spec, system, user, timeout_s):
        asked.append(spec.model or spec.backend)
        return replies[spec.model or spec.backend]
    return ask, asked


def test_the_router_moves_on_when_the_gate_refuses_and_names_who_answered(tmp_path, project):
    cfg = config.load(project, machine=granted(tmp_path, project))
    ask, asked = fake({"qwen3-coder:30b": Reply("bad patch", "ok"), "sonnet": Reply("good patch", "ok")})
    answer = route.run(cfg, "pulled.fix", "system", "user", tokens=300, gate=lambda t: t == "good patch", ask=ask)
    assert answer.text == "good patch" and answer.profile == "flagship" and answer.remote
    assert [(a.profile, a.outcome) for a in answer.attempts] == [("local-qwen3-coder", "refused"), ("flagship", "ok")]
    assert asked == ["qwen3-coder:30b", "sonnet"]


def test_the_router_skips_a_profile_the_packet_does_not_fit_and_reports_unavailable(tmp_path, project):
    cfg = config.load(project, machine=tmp_path / "absent.toml")
    ask, asked = fake({})
    answer = route.run(cfg, "pulled.grill", "s", "x" * 20000, tokens=80, ask=ask)
    assert not answer.ok and answer.attempts == [route.Attempt("local-qwen3-coder", "too_large")] and asked == []
    unavailable = route.run(cfg, "pulled.explain", "s", "u", tokens=300, ask=ask)
    assert unavailable.unavailable.startswith("Explain needs a reasoning model.")


def test_grill_goes_to_the_flagship_and_to_the_local_model_in_local_only(tmp_path, project):
    assert config.load(project, machine=tmp_path / "absent.toml").route("pulled.grill").chain == ["local-qwen3-coder"]
    assert config.load(project, machine=granted(tmp_path, project)).route("pulled.grill").chain == \
        ["flagship", "local-qwen3-coder"]


def test_the_router_hands_each_profile_its_own_prompt(tmp_path, project):
    cfg = config.load(project, machine=granted(tmp_path, project))
    seen = []

    def ask(spec, system, user, timeout_s):
        seen.append((spec.backend, system))
        return Reply(None, "unavailable") if spec.remote else Reply("1. a question", "ok")

    answer = route.run(cfg, "pulled.grill", lambda p: "flagship prompt" if p.remote else "local prompt", "code",
                       tokens=220, ask=ask)
    assert seen == [("claude", "flagship prompt"), ("ollama", "local prompt")]
    assert answer.profile == "local-qwen3-coder" and answer.attempts[0].outcome == "unavailable"


def test_effective_says_nothing_leaves_in_local_only_and_shows_the_command_in_hybrid(tmp_path, project):
    local = config.effective(config.load(project, machine=tmp_path / "absent.toml"))
    assert "nothing: no remote profile is reachable" in local
    hybrid = config.effective(config.load(project, machine=granted(tmp_path, project)),
                              prompts={"pulled.explain": "You explain code."})
    assert "claude -p --output-format json --tools " in hybrid
    assert "pulled.explain system prompt: 'You explain code.'" in hybrid
