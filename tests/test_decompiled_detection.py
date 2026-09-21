import hashlib
import json
import sqlite3
import unittest
import warnings
import zipfile
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_decompiled_export import _prepare_registered_portable_workspace

from vrsoft_extractor.mary.apps_catalog import AppsCatalogStore
from vrsoft_extractor.mary.decompiled_detection import (
    detect_decompiled_package_archive,
    detect_decompiled_source,
    import_decompiled_package_archive,
    import_decompiled_source,
)
from vrsoft_extractor.mary.decompiled_export import export_decompiled_package


_PORTABLE_BODY = b"package br;\nclass App {}\n"
_PORTABLE_SHA = hashlib.sha256(_PORTABLE_BODY).hexdigest()


def _minimal_manifest() -> dict:
    return {
        "format": "vrstudio-decompiled-package",
        "schema_version": 1,
        "package_id": "package-1",
        "package_name": "Pacote 1",
        "package_manifest_sha256": "e" * 64,
        "exported_at": "2026-01-01T00:00:00+00:00",
        "file_count": 1,
        "total_bytes": len(_PORTABLE_BODY),
        "artifacts": [{
            "artifact_index": 1,
            "role": "application",
            "artifact_sha256": "a" * 64,
            "jar_relative_path": "VRApp.jar",
            "size_bytes": len(_PORTABLE_BODY),
            "source_count": 1,
            "application_id": "vrapp",
            "application_name": "VRApp",
            "version": "1.0.0",
            "variant_id": "a" * 64,
            "distribution_id": "dist-1",
            "class_count": 1,
            "sources": [{
                "source_relative_path": "br/App.java",
                "source_sha256": _PORTABLE_SHA,
                "archive_path": "sources/0001/br/App.java",
            }],
        }],
    }


class TestDecompiledDetection(unittest.TestCase):
    def test_detect_single_app_with_properties(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            app_dir = temp_path / "VRMaster_decompiled"
            app_dir.mkdir()

            prop_content = (
                "app.name=VRMaster\n"
                "versao.major=4\n"
                "versao.minor=4\n"
                "versao.release=102\n"
                "versao.build=0\n"
                "versao.beta=0\n"
                "app.data=2026-08-31\n"
            )
            (app_dir / "vrmaster.properties").write_text(prop_content, encoding="utf-8")

            pkg_dir = app_dir / "vr" / "vrmaster"
            pkg_dir.mkdir(parents=True)
            (pkg_dir / "Main.java").write_text(
                "package vr.vrmaster;\npublic class Main {\n    public static void main(String[] args) {}\n}\n",
                encoding="utf-8",
            )
            (pkg_dir / "Service.java").write_text(
                "package vr.vrmaster;\npublic class Service {\n    public void execute() {}\n}\n",
                encoding="utf-8",
            )

            result = detect_decompiled_source(app_dir)
            self.assertTrue(result["is_valid"])
            self.assertEqual(result["scope"], "single_app")
            self.assertEqual(result["total_java_files"], 2)
            self.assertEqual(len(result["applications"]), 1)

            app = result["applications"][0]
            self.assertEqual(app["app_id"], "vrmaster")
            self.assertEqual(app["app_name"], "VRMaster")
            self.assertEqual(app["version"], "4.4.102.0")
            self.assertEqual(app["application_date"], "2026-08-31")

    def test_detect_multi_app_package(self):
        with TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir) / "all_apps"
            root_dir.mkdir()

            # App 1: VRMaster
            master_dir = root_dir / "VRMaster"
            master_dir.mkdir()
            (master_dir / "vrmaster.properties").write_text(
                "versao.major=4\nversao.minor=4\nversao.release=102\nversao.build=0\n",
                encoding="utf-8",
            )
            (master_dir / "Master.java").write_text("package vr.master;\npublic class Master {}\n", encoding="utf-8")

            # App 2: VRAdm
            adm_dir = root_dir / "VRAdm"
            adm_dir.mkdir()
            (adm_dir / "vradm.properties").write_text(
                "versao.major=3\nversao.minor=2\nversao.release=15\nversao.build=1\n",
                encoding="utf-8",
            )
            (adm_dir / "Adm.java").write_text("package vr.adm;\npublic class Adm {}\n", encoding="utf-8")

            result = detect_decompiled_source(root_dir)
            self.assertTrue(result["is_valid"])
            self.assertEqual(result["scope"], "package")
            self.assertEqual(len(result["applications"]), 2)
            self.assertEqual(result["total_java_files"], 2)

            app_keys = {a["app_id"] for a in result["applications"]}
            self.assertEqual(app_keys, {"vrmaster", "vradm"})

    def test_import_decompiled_source_end_to_end(self):
        with TemporaryDirectory() as ws_dir, TemporaryDirectory() as src_dir:
            ws_path = Path(ws_dir)
            src_path = Path(src_dir)

            # Create decompiled VRMaster
            (src_path / "vrmaster.properties").write_text(
                "app.name=VRMaster\nversao.major=4\nversao.minor=4\nversao.release=102\nversao.build=0\n",
                encoding="utf-8",
            )
            src_pkg = src_path / "vr" / "vrmaster"
            src_pkg.mkdir(parents=True)
            (src_pkg / "VendaService.java").write_text(
                "package vr.vrmaster;\npublic class VendaService {\n    public void processarVenda() {}\n}\n",
                encoding="utf-8",
            )

            # Ingest into workspace
            apps_store = AppsCatalogStore(root=ws_path)
            ingest_result = import_decompiled_source(
                ws_path,
                src_path,
                release_id="test-vrmaster-rel",
                package_name="VRMaster Importado da Maquina 1",
                apps_store=apps_store,
            )

            self.assertTrue(ingest_result["success"])
            self.assertEqual(ingest_result["imported_applications"], 1)
            self.assertEqual(ingest_result["total_indexed_sources"], 1)

            # Verify registered in catalog
            pkg = apps_store.get_package("test-vrmaster-rel")
            self.assertIsNotNone(pkg)
            self.assertEqual(pkg["name"], "VRMaster Importado da Maquina 1")

            versions = apps_store.list_versions("vrmaster")
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0]["version"], "4.4.102.0")
            self.assertEqual(versions[0]["decompilationState"], "ready")

            # Verify indexed in SQLite code_sources
            db_path = ws_path / "indice" / "codigo" / "processing.sqlite"
            self.assertTrue(db_path.is_file())
            conn = sqlite3.connect(db_path)
            try:
                row = conn.execute("SELECT qualified_name, tool, symbols_text FROM code_sources").fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "vr.vrmaster.VendaService")
                self.assertEqual(row[1], "decompiled_import")
                self.assertIn("processarVenda", row[2])
            finally:
                conn.close()

    def test_import_decompiled_source_skips_duplicate_identities(self):
        with TemporaryDirectory() as ws_dir, TemporaryDirectory() as src_dir:
            ws_path = Path(ws_dir)
            src_path = Path(src_dir)
            self._prepare_directory_import(src_path)
            duplicate = src_path / "vr" / "vrmaster" / "backup" / "A.java"
            duplicate.parent.mkdir(parents=True)
            duplicate.write_text(
                "package vr.vrmaster;\npublic class A {}\n", encoding="utf-8"
            )

            result = import_decompiled_source(ws_path, src_path, release_id="dup-rel")

            self.assertTrue(result["success"])
            self.assertEqual(result["total_indexed_sources"], 2)
            self.assertEqual(len(_sources_snapshot(ws_path)), 2)
            self.assertTrue(
                (
                    ws_path / "indice" / "codigo" / "decompilation"
                    / "dup-rel" / "vrmaster" / "vr" / "vrmaster" / "backup" / "A.java"
                ).is_file()
            )

    def _prepare_directory_import(self, src_path: Path) -> None:
        (src_path / "vrmaster.properties").write_text(
            "app.name=VRMaster\nversao.major=4\nversao.minor=4\nversao.release=102\nversao.build=0\n",
            encoding="utf-8",
        )
        src_pkg = src_path / "vr" / "vrmaster"
        src_pkg.mkdir(parents=True)
        (src_pkg / "A.java").write_text(
            "package vr.vrmaster;\npublic class A {}\n", encoding="utf-8"
        )
        (src_pkg / "B.java").write_text(
            "package vr.vrmaster;\npublic class B {}\n", encoding="utf-8"
        )

    def test_import_decompiled_source_reports_progress(self):
        with TemporaryDirectory() as ws_dir, TemporaryDirectory() as src_dir:
            ws_path = Path(ws_dir)
            src_path = Path(src_dir)
            self._prepare_directory_import(src_path)
            events = []

            result = import_decompiled_source(
                ws_path, src_path, release_id="progress-rel", progress=events.append
            )

            self.assertEqual(result["total_indexed_sources"], 2)
            self.assertEqual(events[0], {"current": 0, "total": 2})
            self.assertEqual(events[-1], {"current": 2, "total": 2})
            self.assertTrue(all(event["total"] == 2 for event in events))
            self.assertEqual(
                [event["current"] for event in events],
                sorted(event["current"] for event in events),
            )

    def test_import_decompiled_source_reports_throttled_progress(self):
        with TemporaryDirectory() as ws_dir, TemporaryDirectory() as src_dir:
            ws_path = Path(ws_dir)
            src_path = Path(src_dir)
            self._prepare_directory_import(src_path)
            events = []

            with patch(
                "vrsoft_extractor.mary.decompiled_detection._PROGRESS_REPORT_INTERVAL", 1
            ):
                import_decompiled_source(
                    ws_path, src_path, release_id="progress-steps", progress=events.append
                )

            self.assertEqual(
                [event["current"] for event in events][:3],
                [0, 1, 2],
            )
            self.assertEqual(events[-1], {"current": 2, "total": 2})


def _write_portable_zip(path: Path, manifest: dict, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "vrstudio-package-export.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        for name, content in entries.items():
            archive.writestr(name, content)


def _sources_snapshot(workspace: Path) -> list[tuple[str, str, str]]:
    database = workspace / "indice" / "codigo" / "processing.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        return sorted(
            connection.execute(
                "SELECT source_relative_path, source_sha256, body FROM code_sources"
            ).fetchall()
        )


def _assert_portable_release_absent(test: unittest.TestCase, workspace: Path) -> None:
    test.assertIsNone(AppsCatalogStore(root=workspace).get_package("release-a"))
    database = workspace / "indice" / "codigo" / "processing.sqlite"
    test.assertTrue(database.is_file())
    with closing(sqlite3.connect(database)) as connection:
        test.assertEqual(
            connection.execute("SELECT count(*) FROM code_sources").fetchone()[0], 0
        )
        test.assertEqual(
            connection.execute("SELECT count(*) FROM code_symbols").fetchone()[0], 0
        )
        test.assertEqual(
            connection.execute("SELECT count(*) FROM code_relations").fetchone()[0], 0
        )
        test.assertEqual(
            connection.execute("SELECT count(*) FROM decompilation_plans").fetchone()[0],
            0,
        )
    decompilation = workspace / "indice" / "codigo" / "decompilation"
    test.assertEqual(list(decompilation.glob("release-a")), [])
    test.assertEqual(list(decompilation.glob(".release-a.tmp-*")), [])


class TestPortableDecompiledPackage(unittest.TestCase):
    def test_detect_portable_decompiled_package_archive(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace-a"
            _prepare_registered_portable_workspace(workspace)
            archive = root / "Pacote-decompiled.zip"
            export_decompiled_package(workspace, archive, package_id="release-a")

            result = detect_decompiled_package_archive(archive)

            self.assertTrue(result["is_valid"])
            self.assertTrue(result["portable_package"])
            self.assertEqual(result["scope"], "package")
            self.assertEqual(result["source_archive"], str(archive.resolve()))
            self.assertEqual(result["suggested_release_id"], "release-a")
            self.assertEqual(result["suggested_name"], "Pacote A")
            self.assertEqual(result["total_java_files"], 3)
            self.assertEqual(
                {app["app_id"] for app in result["applications"]},
                {"vrmaster", "vradm"},
            )

    def test_detect_portable_decompiled_package_rejects_invalid_archives(self):
        cases = (
            "missing_manifest", "bad_schema", "bad_hash", "traversal",
            "absolute", "drive", "source_traversal", "symlink",
        )
        for case in cases:
            with self.subTest(case=case):
                with TemporaryDirectory() as temp_dir:
                    archive = Path(temp_dir) / f"{case}.zip"
                    manifest = _minimal_manifest()
                    entries = {"sources/0001/br/App.java": _PORTABLE_BODY}
                    if case == "bad_schema":
                        manifest["schema_version"] = 2
                    elif case == "bad_hash":
                        manifest["artifacts"][0]["sources"][0]["source_sha256"] = "0" * 64
                    elif case == "traversal":
                        manifest["artifacts"][0]["sources"][0]["archive_path"] = "../evil.java"
                        entries = {"../evil.java": _PORTABLE_BODY}
                    elif case == "absolute":
                        manifest["artifacts"][0]["sources"][0]["archive_path"] = "/evil.java"
                        entries = {"/evil.java": _PORTABLE_BODY}
                    elif case == "drive":
                        manifest["artifacts"][0]["sources"][0]["archive_path"] = "C:/evil.java"
                        entries = {"C:/evil.java": _PORTABLE_BODY}
                    elif case == "source_traversal":
                        manifest["artifacts"][0]["sources"][0]["source_relative_path"] = \
                            "../../evil.java"
                    if case == "missing_manifest":
                        with zipfile.ZipFile(archive, "w") as package:
                            package.writestr("sources/0001/br/App.java", _PORTABLE_BODY)
                    elif case == "symlink":
                        with zipfile.ZipFile(archive, "w") as package:
                            package.writestr(
                                "vrstudio-package-export.json", json.dumps(manifest)
                            )
                            package.writestr("sources/0001/br/App.java", _PORTABLE_BODY)
                            info = zipfile.ZipInfo("evil-link")
                            info.external_attr = (0o120777 << 16) | 0o777
                            package.writestr(info, "br/App.java")
                    else:
                        _write_portable_zip(archive, manifest, entries)

                    result = detect_decompiled_package_archive(archive)

                    self.assertFalse(result["is_valid"], case)
                    self.assertTrue(result["portable_package"])
                    self.assertTrue(result["error"], case)
                    self.assertEqual(result["applications"], [])
                    self.assertEqual(result["total_java_files"], 0)

    def test_portable_decompiled_package_round_trip_to_fresh_workspace(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace_a = root / "workspace-a"
            _prepare_registered_portable_workspace(workspace_a)
            archive = root / "Pacote-decompiled.zip"
            export_decompiled_package(workspace_a, archive, package_id="release-a")

            workspace_b = root / "workspace-b"
            workspace_b.mkdir()
            result = import_decompiled_package_archive(workspace_b, archive)

            self.assertTrue(result["success"])
            self.assertEqual(result["release_id"], "release-a")
            self.assertEqual(result["package_name"], "Pacote A")
            self.assertEqual(result["imported_applications"], 2)
            self.assertEqual(result["total_indexed_sources"], 3)

            store_a = AppsCatalogStore(root=workspace_a)
            store_b = AppsCatalogStore(root=workspace_b)
            package_a = store_a.get_package("release-a")
            package_b = store_b.get_package("release-a")
            self.assertIsNotNone(package_b)
            self.assertEqual(package_b["name"], package_a["name"])
            self.assertEqual(
                sorted(package_b["composition"], key=lambda item: item["app_id"]),
                sorted(package_a["composition"], key=lambda item: item["app_id"]),
            )
            self.assertEqual(
                sorted(package_b["dependencies"], key=lambda item: item["relative_path"]),
                sorted(package_a["dependencies"], key=lambda item: item["relative_path"]),
            )

            apps_a = {app["appId"]: app["name"] for app in store_a.list_applications()}
            apps_b = {app["appId"]: app["name"] for app in store_b.list_applications()}
            self.assertEqual(apps_b, apps_a)
            for app_id, version in (("vrmaster", "4.1.0"), ("vradm", "3.2.15.0")):
                variants_a = store_a.get_version(app_id, version)["variants"]
                variants_b = store_b.get_version(app_id, version)["variants"]
                self.assertEqual(sorted(variants_a), sorted(variants_b))
                self.assertEqual(
                    sorted(item["sha256"] for item in variants_a.values()),
                    sorted(item["sha256"] for item in variants_b.values()),
                )
            for app_id in ("vrmaster", "vradm"):
                version = store_b.list_versions(app_id)[0]
                self.assertEqual(version["indexState"], "ready")
                self.assertEqual(version["decompilationState"], "ready")

            self.assertEqual(_sources_snapshot(workspace_b), _sources_snapshot(workspace_a))

            database = workspace_b / "indice" / "codigo" / "processing.sqlite"
            with closing(sqlite3.connect(database)) as connection:
                references = "\n".join(
                    f"{row[0]}|{row[1]}"
                    for row in connection.execute(
                        "SELECT output_reference, body FROM code_sources"
                    )
                )
                self.assertTrue(
                    all(
                        row[0] == "decompiled_package_import"
                        for row in connection.execute("SELECT tool FROM code_sources")
                    )
                )
            catalog_text = json.dumps(store_b.load_catalog(), ensure_ascii=False)
            self.assertNotIn(str(workspace_a), catalog_text)
            self.assertNotIn(str(workspace_a), references)

    def test_portable_decompiled_package_import_reports_progress(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace_a = root / "workspace-a"
            _prepare_registered_portable_workspace(workspace_a)
            archive = root / "Pacote-decompiled.zip"
            export_decompiled_package(workspace_a, archive, package_id="release-a")

            workspace_b = root / "workspace-b"
            workspace_b.mkdir()
            events = []

            result = import_decompiled_package_archive(
                workspace_b, archive, progress=events.append
            )

            self.assertEqual(result["total_indexed_sources"], 3)
            self.assertEqual(events[0], {"current": 0, "total": 3})
            self.assertEqual(events[-1], {"current": 3, "total": 3})
            self.assertTrue(all(event["total"] == 3 for event in events))
            self.assertEqual(
                [event["current"] for event in events],
                sorted(event["current"] for event in events),
            )

    def test_portable_import_skips_duplicate_source_identities(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "duplicado.zip"
            manifest = _minimal_manifest()
            artifact = manifest["artifacts"][0]
            artifact["sources"].append({
                "source_relative_path": "1/0/br/App.java",
                "source_sha256": _PORTABLE_SHA,
                "archive_path": "sources/0001/1/0/br/App.java",
            })
            artifact["source_count"] = 2
            manifest["file_count"] = 2
            manifest["total_bytes"] = 2 * len(_PORTABLE_BODY)
            _write_portable_zip(archive, manifest, {
                "sources/0001/br/App.java": _PORTABLE_BODY,
                "sources/0001/1/0/br/App.java": _PORTABLE_BODY,
            })
            workspace = root / "workspace"
            workspace.mkdir()

            result = import_decompiled_package_archive(workspace, archive)

            self.assertTrue(result["success"])
            self.assertEqual(result["total_indexed_sources"], 1)
            self.assertEqual(len(_sources_snapshot(workspace)), 1)
            self.assertTrue(
                (
                    workspace / "indice" / "codigo" / "decompilation"
                    / "package-1" / "artifacts" / "0001" / "1" / "0" / "br" / "App.java"
                ).is_file()
            )

    def test_portable_import_rejects_existing_release_without_partial_state(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace_a = root / "workspace-a"
            _prepare_registered_portable_workspace(workspace_a)
            archive = root / "Pacote-decompiled.zip"
            export_decompiled_package(workspace_a, archive, package_id="release-a")

            workspace_b = root / "workspace-b"
            _prepare_registered_portable_workspace(workspace_b)
            before_catalog = json.dumps(
                AppsCatalogStore(root=workspace_b).load_catalog(), sort_keys=True
            )
            database = workspace_b / "indice" / "codigo" / "processing.sqlite"
            with closing(sqlite3.connect(database)) as connection:
                before_sources = connection.execute(
                    "SELECT count(*) FROM code_sources"
                ).fetchone()[0]

            with self.assertRaises(ValueError):
                import_decompiled_package_archive(workspace_b, archive)

            self.assertEqual(
                json.dumps(AppsCatalogStore(root=workspace_b).load_catalog(), sort_keys=True),
                before_catalog,
            )
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(
                    connection.execute("SELECT count(*) FROM code_sources").fetchone()[0],
                    before_sources,
                )
            decompilation = workspace_b / "indice" / "codigo" / "decompilation"
            self.assertEqual(
                list(decompilation.glob("release-a")) if decompilation.is_dir() else [], []
            )
            self.assertEqual(
                list(decompilation.glob(".release-a.tmp-*")) if decompilation.is_dir() else [],
                [],
            )

    def test_detect_portable_decompiled_package_rejects_structural_corruption(self):
        for case in (
            "duplicate_manifest", "duplicate_entry", "missing_source",
            "foreign_archive_path", "bad_total_bytes", "duplicate_index",
        ):
            with self.subTest(case=case):
                with TemporaryDirectory() as temp_dir:
                    archive = Path(temp_dir) / f"{case}.zip"
                    manifest = _minimal_manifest()
                    entries = {"sources/0001/br/App.java": _PORTABLE_BODY}
                    if case == "duplicate_entry":
                        entries["sources\\0001\\br\\App.java"] = _PORTABLE_BODY
                    elif case == "missing_source":
                        manifest["artifacts"][0]["sources"][0]["archive_path"] = (
                            "sources/0001/br/Missing.java"
                        )
                    elif case == "foreign_archive_path":
                        manifest["artifacts"][0]["sources"][0]["archive_path"] = (
                            "sources/0002/br/App.java"
                        )
                        entries = {"sources/0002/br/App.java": _PORTABLE_BODY}
                    elif case == "bad_total_bytes":
                        manifest["total_bytes"] = len(_PORTABLE_BODY) + 5
                    elif case == "duplicate_index":
                        manifest["artifacts"].append({
                            "artifact_index": 1,
                            "role": "dependency",
                            "artifact_sha256": "b" * 64,
                            "jar_relative_path": "VRDep.jar",
                            "size_bytes": 1,
                            "source_count": 0,
                            "sources": [],
                        })
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", UserWarning)
                        if case == "duplicate_manifest":
                            with zipfile.ZipFile(archive, "w") as package:
                                package.writestr(
                                    "vrstudio-package-export.json", json.dumps(manifest)
                                )
                                package.writestr(
                                    "vrstudio-package-export.json", json.dumps(manifest)
                                )
                                package.writestr(
                                    "sources/0001/br/App.java", _PORTABLE_BODY
                                )
                        else:
                            _write_portable_zip(archive, manifest, entries)

                    result = detect_decompiled_package_archive(archive)

                    self.assertFalse(result["is_valid"], case)
                    self.assertTrue(result["portable_package"], case)
                    self.assertTrue(result["error"], case)
                    self.assertEqual(result["applications"], [])
                    self.assertEqual(result["total_java_files"], 0)

    def test_portable_import_is_atomic_when_publication_fails(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace_a = root / "workspace-a"
            _prepare_registered_portable_workspace(workspace_a)
            archive = root / "Pacote-decompiled.zip"
            export_decompiled_package(workspace_a, archive, package_id="release-a")

            workspace_b = root / "workspace-b"
            workspace_b.mkdir()
            real_replace = Path.replace

            def failing_replace(self, target):
                if Path(target).name == "release-a":
                    raise OSError("falha simulada na publicação")
                return real_replace(self, target)

            with patch.object(Path, "replace", failing_replace):
                with self.assertRaises(OSError):
                    import_decompiled_package_archive(workspace_b, archive)

            _assert_portable_release_absent(self, workspace_b)

    def test_portable_import_compensates_when_catalog_publication_fails(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace_a = root / "workspace-a"
            _prepare_registered_portable_workspace(workspace_a)
            archive = root / "Pacote-decompiled.zip"
            export_decompiled_package(workspace_a, archive, package_id="release-a")

            workspace_b = root / "workspace-b"
            workspace_b.mkdir()
            with patch.object(
                AppsCatalogStore,
                "register_package",
                side_effect=RuntimeError("falha simulada no catálogo"),
            ):
                with self.assertRaises(RuntimeError):
                    import_decompiled_package_archive(workspace_b, archive)

            _assert_portable_release_absent(self, workspace_b)


if __name__ == "__main__":
    unittest.main()

