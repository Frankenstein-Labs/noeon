from __future__ import annotations

from pathlib import Path

import yaml

from noeon.skills import SkillRegistry, build_universe

DEFAULT_BODY = """# {title}

## When to use

Use this when the task matches {title}. It is a test fixture.

## Workflow

1. Read the repository.
2. Apply the change.
3. Run the tests.

## Verification

Run the project test suite.
"""


def skill_text(name: str, description: str, *, body: str | None = None, **frontmatter) -> str:
    payload = {"name": name, "description": description, **frontmatter}
    rendered = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    return f"---\n{rendered}---\n\n" + (body or DEFAULT_BODY.format(title=name))


def write_skill(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class StubClient:
    """Network test double: returns pinned content and records fetched paths."""

    def __init__(self, files: dict[tuple[str, str, str], str]) -> None:
        self.files = files
        self.fetched: list[str] = []

    def raw(self, repository: str, commit: str, path: str, *, max_bytes: int = 512 * 1024) -> str:
        self.fetched.append(path)
        try:
            return self.files[(repository, commit, path)]
        except KeyError as exc:
            from noeon.skills import SourceFetchError

            raise SourceFetchError(f"missing fixture content: {path}") from exc


def make_universe(tmp_path: Path):
    return build_universe(
        registry_path=tmp_path / "skills.sqlite3",
        workspace=tmp_path,
        skills_root=tmp_path / "skills",
    )


def new_registry(tmp_path: Path) -> SkillRegistry:
    return SkillRegistry(tmp_path / "skills.sqlite3")
