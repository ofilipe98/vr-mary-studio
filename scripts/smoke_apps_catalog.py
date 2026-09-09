"""Compile tiny JARs and exercise real variant processing in an isolated workspace."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import time
import zipfile
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from vrsoft_extractor.mary.code_index import JavaCodeIndex  # noqa: E402
from vrsoft_extractor.mary.config import MarySettings  # noqa: E402
from vrsoft_extractor.mary.db import MaryDatabase  # noqa: E402
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog  # noqa: E402
from vrsoft_extractor.mary.frontend.bridges import codeadmin  # noqa: E402
from vrsoft_extractor.mary.frontend.chat import ChatBridge  # noqa: E402
from vrsoft_extractor.mary.jvm_toolchain import JvmToolchain  # noqa: E402


def wait_until(predicate, timeout=90):
    deadline = time.monotonic() + timeout
    while not predicate():
        QApplication.processEvents()
        if time.monotonic() > deadline:
            raise RuntimeError("Smoke timeout")
        time.sleep(0.01)


def main():
    repo = Path(__file__).resolve().parents[1]
    out = repo / ".test-tmp" / f"apps-real-smoke-{uuid4().hex[:8]}"
    out.mkdir(parents=True)
    compiler = shutil.which("javac")
    if not compiler:
        raise RuntimeError("javac is required for this smoke")
    toolchain = JvmToolchain(repo / "VRProject", app_dir=repo)
    doctor = toolchain.doctor()
    if not doctor["ready"]:
        raise RuntimeError("Verified local decompilers and Java 17 are required")
    app = QApplication.instance() or QApplication([])
    settings = MarySettings(app_dir=out, root=out / "workspace", old_root=out / "old")
    db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
    chat = ChatBridge(settings, db, QSettings(str(out / "prefs.ini"), QSettings.IniFormat))
    catalog = ErpReleaseCatalog(settings.root, expected_jar_count=2, storage_budget_multiplier=10)
    artifacts = {}
    for name, value in (("VRApp", 1), ("VRApp", 2), ("VROther", 1), ("VROther", 2)):
        build = out / f"compile-{name}-{value}"
        build.mkdir()
        source = build / f"{name}.java"
        source.write_text(f"public class {name} {{ public int value() {{ return {value}; }} }}", encoding="utf-8")
        subprocess.run([compiler, "-d", str(build), str(source)], check=True, capture_output=True)
        target = build / f"{name}.jar"
        with zipfile.ZipFile(target, "w") as jar:
            jar.write(build / f"{name}.class", f"{name}.class")
            jar.writestr("META-INF/MANIFEST.MF", f"Manifest-Version: 1.0\nMain-Class: {name}\n")
            jar.writestr(f"{name.lower()}.properties", f"versao.major={value}\nversao.minor=0\nversao.release=0\nversao.build=0\nversao.beta=0\n")
            # A stored resource gives the fixture a realistic storage budget.
            jar.writestr("fixture-resource.bin", bytes(1024 * 1024))
        artifacts[name, value] = target
    for package, app_version, other_version in (("one", 1, 1), ("two", 1, 2), ("three", 2, 2)):
        source = out / package
        source.mkdir()
        shutil.copy2(artifacts["VRApp", app_version], source / "VRApp.jar")
        shutil.copy2(artifacts["VROther", other_version], source / "VROther.jar")
        catalog.import_release(package, source)
    results = []
    try:
        chat._code_processing_disk_multiplier = 10
        with patch.object(codeadmin, "JvmToolchain", lambda *args, **kwargs: toolchain):
            for package, version in (("one", "1.0.0.0"), ("two", "1.0.0.0"), ("three", "2.0.0.0")):
                chat.refreshCodeAnalysisReleases()
                wait_until(lambda: chat._apps_catalog_thread is None)
                chat.selectApplication("vrapp")
                chat.selectAppVersion(version)
                chat.selectAppOrigin(package)
                started = time.monotonic()
                assert chat.startVariantProcessing("vrapp", version, chat.selectedAppVariantId), chat.codeProcessingStatus
                wait_until(lambda: not chat.codeProcessingRunning)
                wait_until(lambda: chat._apps_catalog_thread is None)
                coverage = JavaCodeIndex(settings.root).coverage(package)
                assert coverage["covered_jars"] == ["VRApp.jar"], (chat.codeProcessingStatus, coverage)
                assert coverage["remaining_jars"] == ["VROther.jar"]
                results.append({"package": package, "elapsed_seconds": round(time.monotonic() - started, 3),
                                "coverage": coverage, "telemetry": chat.codeProcessingTelemetry})
                print(f"Processed VRApp in {package}; VROther remains pending", flush=True)
        assert chat.addSelectedApplicationContext()
        assert chat.ultraApplicationContextsReady
        chat.setCodeAnalysisEnabled(True)
        assert chat.codeAnalysisEnabled
        assert chat.loadApplicationSources("", 0, "")
        wait_until(lambda: chat._app_sources_thread is None)
        assert chat.applicationSources.get("sources"), chat.applicationSources
        assert chat.loadApplicationSources("", 0, chat.applicationSources["sources"][0]["source_key"])
        wait_until(lambda: chat._app_sources_thread is None)
        assert "return 2" in chat.applicationSources.get("body", ""), chat.applicationSources
        from vrsoft_extractor.mary.code_context import freeze_application_contexts
        context = freeze_application_contexts(settings.root, chat._ultra_application_contexts)[0]
        scoped_results = JavaCodeIndex(settings.root).search("value", release_id=context["package_id"],
            artifacts=context["artifacts"], manifest_hash=context["manifest_sha256"])
        assert scoped_results and all(r["jar_relative_path"] == "VRApp.jar" for r in scoped_results)
        print("Explicit Ultra context and indexed source browser passed", flush=True)
        assert len(catalog.list_versions("vrapp")) == 2
        assert len(catalog.get_version("vrapp", "1.0.0.0")["origin_packages"]) == 2
        chat.compareAppVersions("vrapp", "1.0.0.0", "2.0.0.0")
        wait_until(lambda: chat._app_comparison_thread is None)
        comparison = chat.versionComparisonResult
        assert comparison.get("isComplete"), comparison
        assert comparison["summary"]["modified"] == 1, comparison
        (out / "results.json").write_text(json.dumps({"doctor": doctor, "processing": results,
            "comparison": comparison, "application_context": context, "source_browser": "passed", "status": "passed"}, indent=2), encoding="utf-8")
        print(out / "results.json", flush=True)
    finally:
        chat.close()
        app.processEvents()


if __name__ == "__main__":
    main()
