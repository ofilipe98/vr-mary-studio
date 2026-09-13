import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from vrsoft_extractor.mary.apps_catalog import AppsCatalogStore
from vrsoft_extractor.mary.decompiled_detection import (
    detect_decompiled_source,
    import_decompiled_source,
)


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


if __name__ == "__main__":
    unittest.main()
