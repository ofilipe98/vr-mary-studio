import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from vrsoft_extractor.mary.apps_catalog import (
    UNIDENTIFIED_VERSION,
    AppsCatalogStore,
    compute_distribution_id,
    is_application_artifact,
)


class TestAppsCatalog(unittest.TestCase):
    def test_application_detection_vs_library(self):
        self.assertTrue(is_application_artifact({"relative_path": "vrpdv.jar", "manifest_main_class": "br.com.vrsoft.vrpdv.Main"}))
        self.assertTrue(is_application_artifact("VRGestao.jar"))
        self.assertTrue(is_application_artifact("vr-sync.jar"))
        self.assertFalse(is_application_artifact("commons-io-2.6.jar"))
        self.assertFalse(is_application_artifact("log4j-core.jar"))
        self.assertFalse(is_application_artifact("spring-core-5.3.jar"))

    def test_compute_distribution_id(self):
        base_hash = "abc123"
        dep_hashes = ["dep1_hash", "dep2_hash"]
        dist_id = compute_distribution_id(base_hash, dep_hashes)
        self.assertIsInstance(dist_id, str)
        self.assertEqual(len(dist_id), 17)
        # Same inputs produce same distribution id
        self.assertEqual(dist_id, compute_distribution_id(base_hash, ["dep2_hash", "dep1_hash"]))
        # Different dependency produces different distribution id
        self.assertNotEqual(dist_id, compute_distribution_id(base_hash, ["dep1_hash"]))

    def test_package_a_and_b_reuse_same_version(self):
        """
        Pacote A: VRPdv 4.5.0 e VRGestao 4.6.0.
        Pacote B: VRPdv 4.5.0 e VRGestao 4.6.1.
        Resultado:
        - VRPdv: uma versão 4.5.0 vinculada a ambos os pacotes (mesmo hash).
        - VRGestao: versões 4.6.0 e 4.6.1.
        """
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            store = AppsCatalogStore(root=temp_path, catalog_file=temp_path / "apps_catalog.json")

            hash_vrpdv_450 = hashlib.sha256(b"vrpdv 4.5.0 bytecode").hexdigest()
            hash_vrgestao_460 = hashlib.sha256(b"vrgestao 4.6.0 bytecode").hexdigest()
            hash_vrgestao_461 = hashlib.sha256(b"vrgestao 4.6.1 bytecode").hexdigest()

            # Import Package A
            store.register_package(
                manifest={
                    "release_id": "pacote_a",
                    "artifacts": [
                        {
                            "application_key": "vrpdv",
                            "application_name": "VRPdv",
                            "version_detected": "4.5.0",
                            "sha256": hash_vrpdv_450,
                            "file_size": 1000,
                            "relative_path": "vrpdv.jar",
                            "manifest_main_class": "br.com.vr.Main",
                            "dependency_hashes": ["dep_a"],
                            "class_signatures": {"br/com/vr/Main.class": "sig_main_450", "br/com/vr/Util.class": "sig_util"},
                        },
                        {
                            "application_key": "vrgestao",
                            "application_name": "VRGestao",
                            "version_detected": "4.6.0",
                            "sha256": hash_vrgestao_460,
                            "file_size": 2000,
                            "relative_path": "VRGestao.jar",
                            "manifest_main_class": "br.com.vrgestao.Main",
                            "dependency_hashes": ["dep_b"],
                            "class_signatures": {"br/com/vrgestao/Main.class": "sig_gestao_460"},
                        },
                    ],
                },
                package_id="pacote_a",
                package_name="Pacote A 2026.1",
            )

            # Import Package B
            store.register_package(
                manifest={
                    "release_id": "pacote_b",
                    "artifacts": [
                        {
                            "application_key": "vrpdv",
                            "application_name": "VRPdv",
                            "version_detected": "4.5.0",
                            "sha256": hash_vrpdv_450,  # identical hash
                            "file_size": 1000,
                            "relative_path": "vrpdv.jar",
                            "manifest_main_class": "br.com.vr.Main",
                            "dependency_hashes": ["dep_a"],
                            "class_signatures": {"br/com/vr/Main.class": "sig_main_450", "br/com/vr/Util.class": "sig_util"},
                        },
                        {
                            "application_key": "vrgestao",
                            "application_name": "VRGestao",
                            "version_detected": "4.6.1",
                            "sha256": hash_vrgestao_461,
                            "file_size": 2100,
                            "relative_path": "VRGestao.jar",
                            "manifest_main_class": "br.com.vrgestao.Main",
                            "dependency_hashes": ["dep_b"],
                            "class_signatures": {"br/com/vrgestao/Main.class": "sig_gestao_461", "br/com/vrgestao/New.class": "sig_new"},
                        },
                    ],
                },
                package_id="pacote_b",
                package_name="Pacote B 2026.2",
            )

            apps = store.list_applications()
            self.assertEqual(len(apps), 2)
            app_ids = {a["appId"] for a in apps}
            self.assertEqual(app_ids, {"vrpdv", "vrgestao"})

            # VRPdv: 1 version, linked to both pacote_a and pacote_b
            vrpdv_versions = store.list_versions("vrpdv")
            self.assertEqual(len(vrpdv_versions), 1)
            self.assertEqual(vrpdv_versions[0]["version"], "4.5.0")
            self.assertEqual(vrpdv_versions[0]["originCount"], 2)
            self.assertEqual(vrpdv_versions[0]["variantCount"], 1)

            vrpdv_details = store.get_version("vrpdv", "4.5.0")
            origins = [o["package_id"] for o in vrpdv_details["origin_packages"]]
            self.assertIn("pacote_a", origins)
            self.assertIn("pacote_b", origins)

            # VRGestao: 2 versions (4.6.0 and 4.6.1)
            vrgestao_versions = store.list_versions("vrgestao")
            self.assertEqual(len(vrgestao_versions), 2)
            gestao_ver_nums = {v["version"] for v in vrgestao_versions}
            self.assertEqual(gestao_ver_nums, {"4.6.0", "4.6.1"})

    def test_same_version_different_hashes_creates_distinct_variants(self):
        """
        Mesma aplicação e mesma versão declarada, mas com hashes divergentes:
        cria variantes distintas sem sobrescrita silenciosa.
        """
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            store = AppsCatalogStore(root=temp_path, catalog_file=temp_path / "apps_catalog.json")

            hash_build_1 = hashlib.sha256(b"vrpdv 4.5.0 hotfix 1").hexdigest()
            hash_build_2 = hashlib.sha256(b"vrpdv 4.5.0 hotfix 2").hexdigest()

            store.register_package(
                manifest={
                    "release_id": "pacote_build1",
                    "artifacts": [{
                        "application_key": "vrpdv",
                        "version_detected": "4.5.0",
                        "sha256": hash_build_1,
                        "file_size": 1000,
                        "relative_path": "vrpdv.jar",
                    }],
                },
                package_id="pacote_build1",
            )

            store.register_package(
                manifest={
                    "release_id": "pacote_build2",
                    "artifacts": [{
                        "application_key": "vrpdv",
                        "version_detected": "4.5.0",
                        "sha256": hash_build_2,
                        "file_size": 1020,
                        "relative_path": "vrpdv.jar",
                    }],
                },
                package_id="pacote_build2",
            )

            versions = store.list_versions("vrpdv")
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0]["variantCount"], 2)
            self.assertTrue(versions[0]["hasVariants"])

            variants = store.list_variants("vrpdv", "4.5.0")
            self.assertEqual(len(variants), 2)
            variant_hashes = {v["sha256"] for v in variants}
            self.assertEqual(variant_hashes, {hash_build_1, hash_build_2})

    def test_distinct_apps_same_version_isolated(self):
        """
        Aplicativos distintos com o mesmo número de versão (ex: 4.5.0)
        permanecem isolados sem fusão errônea de históricos ou metadados.
        """
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            store = AppsCatalogStore(root=temp_path, catalog_file=temp_path / "apps_catalog.json")

            store.register_package(
                manifest={
                    "release_id": "bundle_1",
                    "artifacts": [
                        {
                            "application_key": "app_one",
                            "application_name": "App One",
                            "version_detected": "1.0.0",
                            "sha256": "hash_app_1",
                            "file_size": 100,
                        },
                        {
                            "application_key": "app_two",
                            "application_name": "App Two",
                            "version_detected": "1.0.0",
                            "sha256": "hash_app_2",
                            "file_size": 200,
                        },
                    ],
                },
                package_id="bundle_1",
            )

            apps = store.list_applications()
            self.assertEqual(len(apps), 2)
            self.assertIsNotNone(store.get_version("app_one", "1.0.0"))
            self.assertIsNotNone(store.get_version("app_two", "1.0.0"))
            # Verifying they have their respective variants and metadata
            v1 = store.get_version("app_one", "1.0.0")
            v2 = store.get_version("app_two", "1.0.0")
            self.assertIn("hash_app_1"[:12], v1["variants"])
            self.assertIn("hash_app_2"[:12], v2["variants"])

    def test_same_jar_different_dependencies_distinct_distributions(self):
        """
        Mesmo JAR principal incluído em pacotes com dependências distintas:
        gera contextos de distribuição (distribution_id) diferentes na mesma variante.
        """
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            store = AppsCatalogStore(root=temp_path, catalog_file=temp_path / "apps_catalog.json")

            jar_hash = hashlib.sha256(b"same jar content").hexdigest()

            # Package 1 has dep_1
            store.register_package(
                manifest={
                    "release_id": "pkg_dist1",
                    "artifacts": [
                        {"application_key": "vrpdv", "version_detected": "4.5.0", "sha256": jar_hash, "file_size": 500},
                        {"relative_path": "lib1.jar", "sha256": "dep1_hash", "size_bytes": 10},
                    ],
                },
                package_id="pkg_dist1",
            )

            # Package 2 has dep_2
            store.register_package(
                manifest={
                    "release_id": "pkg_dist2",
                    "artifacts": [
                        {"application_key": "vrpdv", "version_detected": "4.5.0", "sha256": jar_hash, "file_size": 500},
                        {"relative_path": "lib2.jar", "sha256": "dep2_hash", "size_bytes": 20},
                    ],
                },
                package_id="pkg_dist2",
            )

            variants = store.list_variants("vrpdv", "4.5.0")
            self.assertEqual(len(variants), 1)  # Single variant reused
            dist_contexts = variants[0]["distribution_contexts"]
            self.assertEqual(len(dist_contexts), 2)  # Two distinct distribution IDs tracked
            dist_ids = list(dist_contexts.keys())
            self.assertNotEqual(dist_ids[0], dist_ids[1])
            # Check each distribution context contains the respective dependencies
            dep_names_1 = [d["relative_path"] for d in dist_contexts[dist_ids[0]]["dependencies"]]
            dep_names_2 = [d["relative_path"] for d in dist_contexts[dist_ids[1]]["dependencies"]]
            self.assertNotEqual(dep_names_1, dep_names_2)

    def test_unidentified_version_and_manual_override(self):
        """
        JAR avulso sem identificação de versão inicia com UNIDENTIFIED_VERSION
        e é corrigido via override_version.
        """
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            store = AppsCatalogStore(root=temp_path, catalog_file=temp_path / "apps_catalog.json")

            jar_hash = hashlib.sha256(b"standalone jar").hexdigest()
            store.register_package(
                manifest={
                    "release_id": "standalone_1",
                    "artifacts": [{
                        "application_key": "vrcustom",
                        "application_name": "VRCustom",
                        "version_detected": "",
                        "sha256": jar_hash,
                        "file_size": 500,
                        "relative_path": "custom.jar",
                    }],
                },
                package_id="standalone_1",
                package_name="JAR Avulso",
            )

            app = store.get_application("vrcustom")
            self.assertTrue(app["hasUnidentified"])

            versions = store.list_versions("vrcustom")
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0]["version"], UNIDENTIFIED_VERSION)
            self.assertFalse(versions[0]["isIdentified"])

            # Manual override
            success = store.override_version("vrcustom", UNIDENTIFIED_VERSION, "1.2.3")
            self.assertTrue(success)

            versions_after = store.list_versions("vrcustom")
            self.assertEqual(len(versions_after), 1)
            self.assertEqual(versions_after[0]["version"], "1.2.3")
            self.assertTrue(versions_after[0]["isIdentified"])
            self.assertTrue(versions_after[0]["manualOverride"])

    def test_reimport_and_repeated_migration_idempotent(self):
        """
        Reimportação do mesmo pacote deve ser idempotente,
        preservando dados e overrides manuais sem duplicação.
        """
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            store = AppsCatalogStore(root=temp_path, catalog_file=temp_path / "apps_catalog.json")

            jar_hash = "idem_hash_123"
            manifest = {
                "release_id": "pkg_idem",
                "artifacts": [{
                    "application_key": "vrpdv",
                    "version_detected": "4.5.0",
                    "sha256": jar_hash,
                    "file_size": 1000,
                }],
            }

            store.register_package(manifest, package_id="pkg_idem")
            self.assertEqual(len(store.list_versions("vrpdv")), 1)

            # Reimport identical package
            store.register_package(manifest, package_id="pkg_idem")
            self.assertEqual(len(store.list_versions("vrpdv")), 1)
            self.assertEqual(store.list_versions("vrpdv")[0]["originCount"], 1)

    def test_sync_legacy_releases_preserves_links(self):
        """
        Migração de releases legadas indexadas no disco cria as entradas
        correspondentes no catálogo de aplicativos preservando release_id.
        """
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            store = AppsCatalogStore(root=temp_path, catalog_file=temp_path / "apps_catalog.json")

            # Create legacy release manifest on disk
            rel_dir = temp_path / "indice" / "codigo" / "releases" / "legacy_rel_01"
            rel_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "release_id": "legacy_rel_01",
                "artifacts": [{
                    "application_key": "vrgestao",
                    "application_name": "VRGestao",
                    "version_detected": "3.9.0",
                    "sha256": "legacy_hash_abc",
                    "file_size": 5000,
                    "relative_path": "VRGestao.jar",
                }],
            }
            (rel_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            migrated = store.sync_legacy_releases()
            self.assertEqual(migrated, 1)

            app = store.get_application("vrgestao")
            self.assertIsNotNone(app)
            versions = store.list_versions("vrgestao")
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0]["version"], "3.9.0")
            pkg = store.get_package("legacy_rel_01")
            self.assertIsNotNone(pkg)

    def test_unlink_package_preserves_shared_variants(self):
        """
        Desvincular um pacote que compartilhava versão com outro não apaga a versão.
        """
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            store = AppsCatalogStore(root=temp_path, catalog_file=temp_path / "apps_catalog.json")

            shared_hash = hashlib.sha256(b"shared app bytecode").hexdigest()

            store.register_package(
                manifest={
                    "release_id": "pkg1",
                    "artifacts": [{
                        "application_key": "vrpdv",
                        "version_detected": "4.5.0",
                        "sha256": shared_hash,
                        "file_size": 100,
                    }],
                },
                package_id="pkg1",
            )
            store.register_package(
                manifest={
                    "release_id": "pkg2",
                    "artifacts": [{
                        "application_key": "vrpdv",
                        "version_detected": "4.5.0",
                        "sha256": shared_hash,
                        "file_size": 100,
                    }],
                },
                package_id="pkg2",
            )

            # Unlink pkg1
            store.unlink_package("pkg1")
            vrpdv_versions = store.list_versions("vrpdv")
            self.assertEqual(len(vrpdv_versions), 1)
            self.assertEqual(vrpdv_versions[0]["originCount"], 1)

            # Unlink pkg2
            store.unlink_package("pkg2")
            vrpdv_versions_after = store.list_versions("vrpdv")
            self.assertEqual(len(vrpdv_versions_after), 0)

    def test_complete_version_comparison(self):
        """
        Comparação completa entre duas versões concluídas (ready):
        identifica corretamente adicionadas, removidas, modificadas e inalteradas.
        """
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            store = AppsCatalogStore(root=temp_path, catalog_file=temp_path / "apps_catalog.json")

            hash_v1 = "hash_comp_v1"
            hash_v2 = "hash_comp_v2"

            store.register_package(
                manifest={
                    "release_id": "pkg_v1",
                    "artifacts": [{
                        "application_key": "vrapp",
                        "version_detected": "1.0.0",
                        "sha256": hash_v1,
                        "file_size": 1000,
                        "class_signatures": {
                            "com/test/Unchanged.class": "same_hash",
                            "com/test/Modified.class": "hash_v1_mod",
                            "com/test/Removed.class": "hash_rem",
                        },
                    }],
                },
                package_id="pkg_v1",
            )
            store.update_variant_state("vrapp", "1.0.0", hash_v1, "ready")

            store.register_package(
                manifest={
                    "release_id": "pkg_v2",
                    "artifacts": [{
                        "application_key": "vrapp",
                        "version_detected": "2.0.0",
                        "sha256": hash_v2,
                        "file_size": 1000,
                        "class_signatures": {
                            "com/test/Unchanged.class": "same_hash",
                            "com/test/Modified.class": "hash_v2_mod",
                            "com/test/Added.class": "hash_add",
                        },
                    }],
                },
                package_id="pkg_v2",
            )
            store.update_variant_state("vrapp", "2.0.0", hash_v2, "ready")

            comparison = store.compare_versions("vrapp", "1.0.0", "2.0.0")
            summary = comparison["summary"]
            self.assertEqual(summary["added"], 1)
            self.assertEqual(summary["removed"], 1)
            self.assertEqual(summary["modified"], 1)
            self.assertEqual(summary["unchanged"], 1)
            self.assertEqual(comparison["comparisonState"], "complete")

    def test_compare_versions_with_safeguard_for_pending_state(self):
        """
        Comparação entre versões:
        - Base: ready
        - Target: pending_processing
        Classes ausentes no destino incompleto NÃO podem ser marcadas como removidas!
        """
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            store = AppsCatalogStore(root=temp_path, catalog_file=temp_path / "apps_catalog.json")

            hash_v1 = "hash_v1"
            hash_v2 = "hash_v2"

            store.register_package(
                manifest={
                    "release_id": "pkg_v1",
                    "artifacts": [{
                        "application_key": "vrapp",
                        "version_detected": "1.0.0",
                        "sha256": hash_v1,
                        "file_size": 1000,
                        "class_signatures": {
                            "com/test/A.class": "sig_a",
                            "com/test/B.class": "sig_b",
                            "com/test/C.class": "sig_c",
                        },
                    }],
                },
                package_id="pkg_v1",
            )
            store.update_variant_state("vrapp", "1.0.0", hash_v1, "ready", class_count=3, indexed_classes=3)

            # v2 is pending processing (only partially has class signatures)
            store.register_package(
                manifest={
                    "release_id": "pkg_v2",
                    "artifacts": [{
                        "application_key": "vrapp",
                        "version_detected": "2.0.0",
                        "sha256": hash_v2,
                        "file_size": 1000,
                        "class_signatures": {
                            "com/test/A.class": "sig_a_modified",
                            "com/test/D.class": "sig_d_new",
                        },
                    }],
                },
                package_id="pkg_v2",
            )
            store.update_variant_state("vrapp", "2.0.0", hash_v2, "pending_processing", class_count=3, indexed_classes=1)

            comparison = store.compare_versions("vrapp", "1.0.0", "2.0.0")
            summary = comparison["summary"]
            self.assertEqual(summary["added"], 1)      # D.class
            self.assertEqual(summary["modified"], 1)   # A.class
            # Crucial safeguard: B and C must NOT be marked as removed because v2 is incomplete!
            self.assertEqual(summary["removed"], 0)
            self.assertIn("pendingVerificationClasses", comparison)
            self.assertEqual(len(comparison["pendingVerificationClasses"]), 2)  # B and C
            self.assertIn("pendingNote", comparison)
            self.assertTrue(len(comparison["pendingNote"]) > 0)


if __name__ == "__main__":
    unittest.main()
