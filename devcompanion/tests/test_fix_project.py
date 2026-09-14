from pathlib import Path

import pytest

from devcompanion.fix.project import Project, materialise


@pytest.fixture
def root(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "pkg").mkdir(parents=True)
    (project / "pkg/__init__.py").write_text("")
    (project / "pkg/models.py").write_text("class User: ...\n")
    (project / "pkg/views.py").write_text("from .models import User\n")
    (project / "README.md").write_text("readme\n")
    (project / ".companion").mkdir()
    (project / ".companion/state.json").write_text("{}")
    return project


def test_the_scratch_reads_as_the_project_with_the_file_in_place_and_the_project_untouched(root):
    with materialise(Project(root), {"pkg/views.py": "changed\n"}) as scratch:
        assert (scratch / "pkg/views.py").read_text() == "changed\n" and not (scratch / "pkg/views.py").is_symlink()
        assert (scratch / "pkg/models.py").is_symlink() and (scratch / "pkg/models.py").read_text() == "class User: ...\n"
        assert (scratch / "README.md").is_symlink() and not (scratch / ".companion").exists()
        (scratch / "pkg/views.py").write_text("written in scratch\n")
    assert (root / "pkg/views.py").read_text() == "from .models import User\n"
    assert not scratch.exists()


def test_unsaved_buffers_are_in_place_and_the_proposed_file_wins_over_its_own_buffer(root):
    project = Project(root, overlay={"pkg/models.py": "class User:\n    name: str\n", "pkg/views.py": "buffer\n"})
    with materialise(project, {"pkg/views.py": "proposal\n"}) as scratch:
        assert (scratch / "pkg/models.py").read_text() == "class User:\n    name: str\n"
        assert (scratch / "pkg/views.py").read_text() == "proposal\n"
    assert (root / "pkg/models.py").read_text() == "class User: ...\n"


def test_a_file_that_exists_only_as_a_buffer_gets_its_directories(root):
    with materialise(Project(root), {"pkg/sub/new.py": "x = 1\n"}) as scratch:
        assert (scratch / "pkg/sub/new.py").read_text() == "x = 1\n"
    assert not (root / "pkg/sub").exists()


@pytest.mark.parametrize("rel", ["../outside.py", "/etc/passwd", ".companion/state.json"])
def test_a_path_outside_the_project_is_refused(root, rel):
    with pytest.raises(ValueError), materialise(Project(root), {rel: "x"}):
        pass


def test_the_projects_interpreter_is_found_in_its_virtualenv(root):
    assert Project(root).python is None
    (root / ".venv/bin").mkdir(parents=True)
    (root / ".venv/bin/python").write_text("")
    assert Project(root).python == str(root / ".venv/bin/python")
