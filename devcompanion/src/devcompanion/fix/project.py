"""The project as the checker should see it: a scratch directory that reads as the workspace, with
the proposed file and any unsaved buffers in place of what is on disk.

Checking a copy of one file alone left everything it imported unresolved, so a problem that exists
only through another module could not be checked at all, and a fix could not be vouched for against
the code it calls. Copying the project for every check would cost seconds and, with a virtualenv
inside, gigabytes. So the scratch directory is a shadow tree:
- a symlink to each of the workspace's own entries
- real directories only along the paths of the files that differ

The checker follows the links. Imports (relative ones included), the project's type-checker
configuration and its virtualenv then resolve as they do in the editor, and nothing under the
workspace is ever written.

Measured on basedpyright 1.38 (pass 7): a shadow tree gives exactly the real project's diagnostics
for a file with a relative import; the same file checked alone loses them to unresolved imports.
"""
from __future__ import annotations

import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

SKIP = {".companion"}   # the engine's own state; nothing a checker should read


@dataclass(frozen=True)
class Project:
    root: Path
    overlay: dict[str, str] = field(default_factory=dict)   # unsaved buffers: relative path -> text

    @property
    def python(self) -> str | None:
        """The project's own interpreter, so the checker sees the packages the project installs."""
        for venv in (".venv", "venv"):
            candidate = self.root / venv / "bin" / "python"
            if candidate.exists():
                return str(candidate)
        return None


@contextmanager
def materialise(project: Project, files: dict[str, str]) -> Iterator[Path]:
    """A scratch directory reading as the project, with the overlay and then `files` (relative path ->
    text) in place. Removed on exit."""
    root = project.root.resolve()
    with tempfile.TemporaryDirectory(prefix="companion-project-") as tmp:
        scratch = Path(tmp).resolve()
        for entry in root.iterdir():
            if entry.name not in SKIP:
                (scratch / entry.name).symlink_to(entry)
        for rel, text in {**project.overlay, **files}.items():
            _place(scratch, root, rel, text)
        yield scratch


def _place(scratch: Path, root: Path, rel: str, text: str) -> None:
    parts = Path(rel).parts
    if not parts or Path(rel).is_absolute() or ".." in parts or parts[0] in SKIP:
        raise ValueError(f"not a path inside the project: {rel}")
    here, source = scratch, root
    for part in parts[:-1]:
        here, source = here / part, source / part
        if here.is_symlink():
            # A linked directory on the way to a file that differs: make it real, linking its
            # children, so the file can be replaced without writing through the link.
            here.unlink()
            here.mkdir()
            if source.is_dir():
                for child in source.iterdir():
                    (here / child.name).symlink_to(child)
        elif not here.exists():
            here.mkdir()
    target = here / parts[-1]
    if target.is_symlink() or target.exists():
        target.unlink()             # removes the link, never what it points to
    target.write_text(text)
