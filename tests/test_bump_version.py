"""Cobertura do versionador canônico scripts/bump_version.py e do hook de commit."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
VERSION_FILES = (
    "pyproject.toml",
    "vrsoft_extractor/__init__.py",
    "installer/VRNorteStudio.iss",
    "installer/VRNorteStudio.version.txt",
)


def _load_bump_module():
    spec = importlib.util.spec_from_file_location(
        "bump_version", ROOT / "scripts" / "bump_version.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bump_version = _load_bump_module()


def _copy_version_files(target: Path) -> None:
    for relative in VERSION_FILES:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())


def test_build_and_release_semantics():
    assert bump_version.next_build("0.6.7-1") == "0.6.7-2"
    assert bump_version.next_build("0.6.7") == "0.6.7-1"
    assert bump_version.next_release("0.6.7-9") == "0.6.8-1"
    assert bump_version.next_release("0.6.7") == "0.6.8-1"
    with pytest.raises(bump_version.VersionError):
        bump_version.next_build("0.6.7-beta")


def test_repo_version_files_are_synchronized():
    version = bump_version.verify_version(ROOT)
    assert bump_version.read_version(ROOT) == version


def test_set_version_keeps_every_file_in_sync(tmp_path):
    _copy_version_files(tmp_path)
    bump_version.set_version(tmp_path, "1.2.3-7")
    assert bump_version.verify_version(tmp_path) == "1.2.3-7"


def test_main_commit_increments_and_main_promote_resets_build(tmp_path, capsys):
    _copy_version_files(tmp_path)
    current = bump_version.verify_version(tmp_path)

    assert bump_version.main(["--commit", "--root", str(tmp_path)]) == 0
    assert bump_version.verify_version(tmp_path) == bump_version.next_build(current)
    assert current in capsys.readouterr().out

    assert bump_version.main(["--promote", "--root", str(tmp_path)]) == 0
    assert bump_version.verify_version(tmp_path) == bump_version.next_release(current)

    assert bump_version.main(["--set", "9.9.9-4", "--root", str(tmp_path)]) == 0
    assert bump_version.verify_version(tmp_path) == "9.9.9-4"


def test_main_reports_invalid_explicit_version(tmp_path, capsys):
    _copy_version_files(tmp_path)
    assert bump_version.main(["--set", "not-a-version", "--root", str(tmp_path)]) == 1
    assert "bump_version:" in capsys.readouterr().err


def test_pre_commit_hook_bumps_and_stages_version_files():
    hook = (ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    assert "scripts/bump_version.py" in hook
    assert "--commit" in hook
    assert "--promote" not in hook
    assert "SKIP_VERSION_BUMP" in hook
    assert 'git add "$file"' in hook
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert ".githooks" in attributes and "eol=lf" in attributes
