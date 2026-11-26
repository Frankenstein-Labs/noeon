"""Read-only repository inventory. Prints a JSON report on stdout."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

SKIP_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
             ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build"}
LANGUAGES = {
    ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript",
    ".jsx": "JavaScript", ".rs": "Rust", ".go": "Go", ".java": "Java", ".rb": "Ruby",
    ".php": "PHP", ".cs": "C#", ".c": "C", ".cpp": "C++", ".h": "C/C++ header",
    ".swift": "Swift", ".kt": "Kotlin", ".sh": "Shell", ".sql": "SQL",
}


def walk(root: Path):
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in SKIP_DIRS:
                    stack.append(entry)
            elif entry.is_file():
                yield entry


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory a repository")
    parser.add_argument("--path", default=".")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(json.dumps({"error": f"not a directory: {root}"}))
        return 2

    files = list(walk(root))
    extensions = Counter()
    directories = Counter()
    languages = Counter()
    sizes: list[tuple[int, str]] = []
    for path in files:
        suffix = path.suffix.lower() or "(none)"
        extensions[suffix] += 1
        if suffix in LANGUAGES:
            languages[LANGUAGES[suffix]] += 1
        relative = path.relative_to(root)
        directories[relative.parts[0] if len(relative.parts) > 1 else "."] += 1
        try:
            sizes.append((path.stat().st_size, str(relative)))
        except OSError:
            continue

    sizes.sort(reverse=True)
    report = {
        "root": str(root),
        "file_count": len(files),
        "by_extension": dict(extensions.most_common(args.limit)),
        "by_directory": dict(directories.most_common(args.limit)),
        "languages": dict(languages.most_common()),
        "largest": [{"bytes": size, "path": name} for size, name in sizes[: args.limit]],
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
