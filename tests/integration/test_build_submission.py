"""code.zip must follow AGENTS.md section 6.9: runnable solution, no dataset, no secrets."""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "build_submission", ROOT / "scripts" / "build_submission.py"
)
assert _spec and _spec.loader
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)


def test_package_never_contains_dataset_envs_caches_archives_or_credentials() -> None:
    rels = [p.relative_to(ROOT).as_posix() for p in builder.files()]
    assert "code/main.py" in rels and "README.md" in rels
    names = [r.split("/")[-1] for r in rels]
    assert not [r for r in rels if r.startswith(("dataset/", ".venv/")) or "__pycache__" in r]
    assert not {".env", "output.csv", "log.txt"} & set(names)  # .env.example is a template: fine
    assert not [r for r in rels if r.endswith((".zip", ".tar", ".gz", ".sqlite", ".db"))]
    assert not [r for r in rels if "packs/" in r]  # nested archives from team_handoff


def test_verify_flags_a_dataset_folder_and_a_leaked_key(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    leaked = "sk-" + "a" * 24  # built at runtime so the repo's own secret scan stays quiet
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("README.md", "x")
        zf.writestr("dataset/user_identities.csv", "id")
        zf.writestr("code/config.py", f"KEY = '{leaked}'")
    problems = builder.verify(bad)
    assert any("dataset" in p for p in problems) and any("secret" in p for p in problems)
