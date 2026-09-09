"""Regression cases found while auditing the application catalog integration."""
import hashlib
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from vrsoft_extractor.mary.apps_catalog import AppsCatalogError, AppsCatalogStore
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog


def artifact(version="1.0", digest=None, **extra):
    return {"application": "VRApp", "application_key": "vrapp",
            "application_version": version, "version_detected": True,
            "relative_path": "VRApp.jar", "class_count": 1,
            "sha256": digest or hashlib.sha256(version.encode()).hexdigest(), **extra}


def register(store, package, version="1.0", **extra):
    return store.register_package({"release_id": package, "artifacts": [artifact(version, **extra)]})


def test_override_survives_reimport_and_sync(tmp_path):
    store = AppsCatalogStore(tmp_path)
    register(store, "one")
    store.override_version("vrapp", "1.0", "1.1")
    register(store, "one")
    register(store, "two")
    assert [v["version"] for v in store.list_versions("vrapp")] == ["1.1"]
    version = store.get_version("vrapp", "1.1")
    assert version["original_version"] == "1.0"
    assert version["manual_override"]
    assert len(version["origin_packages"]) == 2
    assert store.get_package("two")["composition"][0]["version"] == "1.1"


def test_distinct_full_hashes_do_not_merge_and_replacement_drops_old_origin(tmp_path):
    store = AppsCatalogStore(tmp_path)
    first, second = "a" * 64, "a" * 12 + "b" * 52
    register(store, "one", digest=first)
    register(store, "two", digest=second)
    assert len(store.list_variants("vrapp", "1.0")) == 2
    register(store, "one", "2.0", digest=first)
    variants = store.list_variants("vrapp", "1.0")
    assert all(o["package_id"] != "one" for v in variants for o in v["origin_packages"])


def test_parallel_imports_preserve_all_origins(tmp_path):
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: register(AppsCatalogStore(tmp_path), f"pkg{n}"), range(12)))
    store = AppsCatalogStore(tmp_path)
    assert len(store.list_packages()) == 12
    assert len(store.list_variants("vrapp", "1.0")[0]["origin_packages"]) == 12


def test_legacy_migration_is_atomic_and_recovers_missing_packages(tmp_path):
    store = AppsCatalogStore(tmp_path)
    index = tmp_path / "indice/codigo/releases"
    for name in ("one", "two"):
        path = index / name / "manifest.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"release_id": name, "artifacts": [artifact()]}), encoding="utf-8")
    (index / "two/manifest.json").write_text("broken", encoding="utf-8")
    with pytest.raises(AppsCatalogError):
        store.sync_legacy_releases()
    assert not store.catalog_file.exists()
    (index / "two/manifest.json").write_text(json.dumps({"release_id": "two", "artifacts": [artifact()]}), encoding="utf-8")
    register(store, "one")
    ErpReleaseCatalog(tmp_path).ensure_apps_catalog_synced()
    assert len(store.list_packages()) == 2
    before = store.catalog_file.read_bytes()
    assert store.sync_legacy_releases() == 0
    assert store.catalog_file.read_bytes() == before
    store.unlink_package("one")
    store.sync_legacy_releases()
    assert store.get_package("one") is None


def test_comparison_rejects_ambiguous_or_invalid_variant(tmp_path):
    store = AppsCatalogStore(tmp_path)
    register(store, "one")
    register(store, "two", digest="b" * 64)
    register(store, "three", "2.0")
    for selected in ("", "does-not-exist"):
        with pytest.raises(AppsCatalogError):
            store.compare_versions("vrapp", "1.0", "2.0", base_variant_id=selected)


def test_comparison_reads_manifest_source_and_verifies_hash(tmp_path):
    catalog = ErpReleaseCatalog(tmp_path, expected_jar_count=1)
    for name, content in (("one", b"one"), ("two", b"two")):
        source = tmp_path / "external" / name
        source.mkdir(parents=True)
        with zipfile.ZipFile(source / "VRApp.jar", "w") as jar:
            jar.writestr("App.class", content)
            jar.writestr("META-INF/MANIFEST.MF", "Main-Class: App\n")
        manifest = catalog.import_release(name, source)
        catalog.apps_store.override_version("vrapp", "Versão não identificada", name)
        catalog.apps_store.update_variant_state("vrapp", name, manifest["artifacts"][0]["sha256"], "ready")
    result = catalog.compare_versions("vrapp", "one", "two")
    assert result["isComplete"]
    assert result["summary"]["modified"] == 1
    (tmp_path / "external/two/VRApp.jar").write_bytes(b"changed after import")
    result = catalog.compare_versions("vrapp", "one", "two")
    assert not result["isComplete"]
    assert result["summary"]["removed"] == 0


def test_pending_base_does_not_report_false_additions(tmp_path):
    store = AppsCatalogStore(tmp_path)
    register(store, "one", class_signatures={"A": "a"})
    register(store, "two", "2.0", class_signatures={"A": "a", "B": "b"})
    store.update_variant_state("vrapp", "2.0", artifact("2.0")["sha256"], "ready")
    result = store.compare_versions("vrapp", "1.0", "2.0")
    assert result["summary"]["added"] == 0
    assert "B" in result["pendingVerificationClasses"]


def test_verified_empty_jar_is_distinct_from_missing_inventory(tmp_path):
    store = AppsCatalogStore(tmp_path)
    register(store, "one", class_signatures={}, class_count=0)
    register(store, "two", "2.0", class_signatures={}, class_count=0)
    for version in ("1.0", "2.0"):
        store.update_variant_state("vrapp", version, artifact(version)["sha256"], "ready",
                                   class_signatures={})
    assert store.compare_versions("vrapp", "1.0", "2.0")["isComplete"]


def test_standalone_jar_without_main_or_version_is_not_lost(tmp_path):
    store = AppsCatalogStore(tmp_path)
    store.register_single_jar({"relative_path": "custom.jar", "sha256": "c" * 64})
    assert store.list_applications()[0]["appId"] == "custom"
    assert store.list_versions("custom")[0]["version"] == "Versão não identificada"
