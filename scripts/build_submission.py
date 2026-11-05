"""Build ``code.zip`` for submission and verify it against the rules in AGENTS.md section 6.9.

    python scripts/build_submission.py            # writes code.zip at the repository root
    python scripts/build_submission.py --check    # only verify an existing code.zip

Included: runnable solution, prompts/config, README, tests, the ``evaluation/`` reports.
Never included: ``dataset/``, virtual environments, caches, nested archives, ``.env`` files,
credentials, ``output.csv`` and ``log.txt`` (those are submitted separately).
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INCLUDE = (
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "Dockerfile",
    "docker-compose.yml",
    ".dockerignore",
    ".env.example",
    "code",
    "contracts",
    "docker",
    "db",
    "evaluation",
    "scripts",
    "tests",
    "docs",
)
SKIP_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",
    ".venv",
    "venv",
    "node_modules",
    "dataset",
    "packs",
    "img",
    ".git",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".zip", ".tar", ".gz", ".7z", ".rar", ".sqlite", ".db"}
SKIP_NAMES = {".env", "output.csv", "log.txt"}
REQUIRED = (
    "README.md",
    "code/main.py",
    "code/evaluation/evaluation_report.md",
    "code/evaluation/usage_report.md",
    "evaluation/evaluation_report.md",
    "evaluation/usage_report.md",
    "pyproject.toml",
)
# A real-looking API key: the project's own CI scan flags the same shape.
SECRET = re.compile(r"sk-[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}")


def files() -> list[Path]:
    found: list[Path] = []
    for entry in INCLUDE:
        base = ROOT / entry
        if base.is_file():
            found.append(base)
        elif base.is_dir():
            for path in sorted(base.rglob("*")):
                rel = path.relative_to(ROOT)
                if (
                    not path.is_file()
                    or SKIP_DIRS & set(rel.parts)
                    or path.name in SKIP_NAMES
                    or path.suffix.lower() in SKIP_SUFFIXES
                ):
                    continue
                found.append(path)
    return found


def verify(archive: Path) -> list[str]:
    problems: list[str] = []
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        for need in REQUIRED:
            if need not in names:
                problems.append(f"missing required file: {need}")
        for name in names:
            parts = set(Path(name).parts)
            if parts & {"dataset", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache"}:
                problems.append(f"forbidden folder in archive: {name}")
            if Path(name).name in SKIP_NAMES or Path(name).suffix.lower() in SKIP_SUFFIXES:
                problems.append(f"forbidden file in archive: {name}")
            textual = name.endswith(
                (".py", ".md", ".toml", ".yml", ".yaml", ".json", ".txt", ".sh")
            )
            if textual and SECRET.search(zf.read(name).decode("utf-8", errors="ignore")):
                problems.append(f"possible secret in {name}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify an existing code.zip only")
    parser.add_argument("--output", type=Path, default=ROOT / "code.zip")
    args = parser.parse_args()
    if not args.check:
        with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in files():
                zf.write(path, path.relative_to(ROOT).as_posix())
    problems = verify(args.output)
    with zipfile.ZipFile(args.output) as zf:
        size = args.output.stat().st_size // 1024
        print(f"{args.output.name}: {len(zf.namelist())} files, {size} KiB")
    for problem in problems:
        print("PROBLEM:", problem)
    print("SUBMISSION PACKAGE", "FAILED" if problems else "OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
