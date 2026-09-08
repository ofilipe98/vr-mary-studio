"""Import boundaries and QML lint checks that fail when their tools fail."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_backend_imports_do_not_load_qt():
    # A fresh process catches transitive imports even when the main test process
    # has already loaded Qt for UI tests. Source-string checks miss that case.
    probe = """
import importlib
import sys

attempted = []
class BlockQt:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'PySide6', 'PyQt6', 'PyQt5'}:
            attempted.append(fullname)
            raise ImportError('Backend attempted to import ' + fullname)

sys.meta_path.insert(0, BlockQt())
for module in sys.argv[1:]:
    importlib.import_module(module)
assert not attempted, attempted
"""
    result = subprocess.run(
        [sys.executable, "-c", probe,
         "vrsoft_extractor.mary.providers", "vrsoft_extractor.mary.antigravity",
         "vrsoft_extractor.mary.execution.runner", "vrsoft_extractor.mary.retrieval.service",
         "vrsoft_extractor.mary.orchestrator", "vrsoft_extractor.mary.db"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.qml
def test_chat_preview_qmllint_warnings_below_threshold():
    import PySide6

    qml_root = ROOT / "vrsoft_extractor/mary/frontend/qml"
    suffix = ".exe" if sys.platform == "win32" else ""
    executable = Path(PySide6.__file__).resolve().parent / ("qmllint" + suffix)
    assert executable.is_file(), f"qmllint missing from the active PySide6 installation: {executable}"
    result = subprocess.run(
        [str(executable), "-I", str(qml_root), str(qml_root / "pages/ChatPreview.qml")],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    warnings = [line for line in output.splitlines() if "Warning:" in line]
    assert len(warnings) < 50, output
