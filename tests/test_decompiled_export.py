import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from vrsoft_extractor.mary.apps_catalog import AppsCatalogStore
from vrsoft_extractor.mary.code_index import JavaCodeIndex
from vrsoft_extractor.mary.decompiled_export import export_decompiled_source


def _prepare(workspace: Path, records: list[dict], *, catalog=None) -> None:
    workspace.mkdir()
    default_catalog = {
        "schema_version": 1,
        "applications": {
            "vrmaster": {
                "name": "VRMaster",
                "versions": {
                    "4.1.0": {"variants": {
                        "sha-master": {
                            "variant_id": "sha-master", "sha256": "sha-master",
                            "relative_path": "VRMaster.jar",
                            "origin_packages": [
                                {"package_id": "release-a", "relative_path": "VRMaster.jar"},
                                {"package_id": "release-b", "relative_path": "VRMaster.jar"},
                            ],
                        }
                    }}
                },
            },
            "vradm": {
                "name": "VRAdm",
                "versions": {"3.7.2": {"variants": {"sha-adm": {
                    "variant_id": "sha-adm", "sha256": "sha-adm", "relative_path": "VRAdm.jar",
                    "origin_packages": [{"package_id": "release-a", "relative_path": "VRAdm.jar"}],
                }}}},
            },
        },
        "packages": {"release-a": {}, "release-b": {}},
    }
    AppsCatalogStore(workspace).save_catalog(catalog or default_catalog)
    index = JavaCodeIndex(workspace)
    index.initialize()
    with sqlite3.connect(index.store.database_path) as connection:
        for number, record in enumerate(records):
            values = {
                "source_key": f"key-{number}", "schema_version": 1,
                "release_id": "release-a", "release_hash": "rh",
                "jar_relative_path": "VRMaster.jar", "artifact_sha256": "sha-master",
                "batch_id": "batch", "class_version": 52, "tool": "test",
                "output_reference": "sources/master", "source_relative_path": "br/Venda.java",
                "source_sha256": "hash", "package_name": "br", "primary_type": "Venda",
                "qualified_name": f"br.Venda{number}", "logical_names_json": "[]",
                "content_hashes_json": "[]", "occurrence_count": 1,
                "parser_kind": "test", "syntax_error_count": 0, "symbols_text": "",
                "body": "class Venda {}", "indexed_at": "2026-01-01T00:00:00Z",
            }
            values.update(record)
            if "source_sha256" not in record:
                values["source_sha256"] = hashlib.sha256(
                    str(values["body"]).encode("utf-8")
                ).hexdigest()
            columns = ", ".join(values)
            placeholders = ", ".join("?" for _ in values)
            connection.execute(
                f"INSERT INTO code_sources ({columns}) VALUES ({placeholders})",  # noqa: S608
                tuple(values.values()),
            )
        connection.commit()


def _export(workspace: Path, destination: Path, **overrides):
    arguments = {
        "application_id": "vrmaster", "version": "4.1.0",
        "variant_id": "sha-master", "origin_id": "release-a",
    }
    arguments.update(overrides)
    return export_decompiled_source(workspace, destination, **arguments)


def test_export_preserves_tree_filters_selection_deduplicates_and_writes_manifest(tmp_path):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    _prepare(workspace, [
        {},
        {"source_key": "duplicate", "qualified_name": "br.VendaDuplicate"},
        {"release_id": "release-b", "source_key": "other-origin",
         "output_reference": "sources/other", "source_relative_path": "Other.kt"},
        {"jar_relative_path": "VRAdm.jar", "artifact_sha256": "sha-adm",
         "source_key": "other-app", "output_reference": "sources/adm",
         "source_relative_path": "Adm.java"},
    ])
    (workspace / "sources/master/br").mkdir(parents=True)
    (workspace / "sources/master/br/Venda.java").write_text("class Venda {}", encoding="utf-8")
    (workspace / "sources/other").mkdir(parents=True)
    (workspace / "sources/other/Other.kt").write_text("class Other", encoding="utf-8")
    (workspace / "sources/adm").mkdir(parents=True)
    (workspace / "sources/adm/Adm.java").write_text("class Adm {}", encoding="utf-8")

    result = _export(workspace, destination)

    exported = Path(result["destination"])
    assert (exported / "br/Venda.java").read_text(encoding="utf-8") == "class Venda {}"
    assert not (exported / "Other.kt").exists()
    assert not (exported / "Adm.java").exists()
    assert result["file_count"] == 1
    manifest = json.loads((exported / "vrstudio-export.json").read_text(encoding="utf-8"))
    assert manifest | {"exported_at": "ignored"} == {
        "schema_version": 1, "application": "VRMaster", "application_id": "vrmaster",
        "version": "4.1.0", "release_id": "release-a", "origin_id": "release-a",
        "exported_at": "ignored", "file_count": 1, "total_bytes": len("class Venda {}"),
    }
    assert str(workspace) not in json.dumps(manifest)


def test_export_uses_non_destructive_numbered_destination(tmp_path):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    _prepare(workspace, [{}])
    (workspace / "sources/master/br").mkdir(parents=True)
    (workspace / "sources/master/br/Venda.java").write_text("class Venda {}", encoding="utf-8")
    existing = destination / "VRMaster-4.1.0-decompiled"
    existing.mkdir()
    (existing / "keep.txt").write_text("keep", encoding="utf-8")

    result = _export(workspace, destination)

    assert Path(result["destination"]).name == "VRMaster-4.1.0-decompiled-2"
    assert (existing / "keep.txt").read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("field,value", [
    ("source_relative_path", "../../outside.java"),
    ("output_reference", "../../outside"),
    ("output_reference", "C:/outside"),
])
def test_export_rejects_path_traversal_and_leaves_no_partial_folder(tmp_path, field, value):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    _prepare(workspace, [{field: value}])

    with pytest.raises(ValueError, match="inválid|fora do workspace"):
        _export(workspace, destination)

    assert list(destination.iterdir()) == []


def test_export_missing_indexed_file_without_valid_body_is_controlled_and_atomic(tmp_path):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    _prepare(workspace, [{}, {"source_key": "second", "source_relative_path": "Missing.kt",
                             "body": "", "source_sha256": "0" * 64}])
    (workspace / "sources/master/br").mkdir(parents=True)
    (workspace / "sources/master/br/Venda.java").write_text("class Venda {}", encoding="utf-8")

    with pytest.raises(ValueError, match="alterada|inconsistente"):
        _export(workspace, destination)

    assert list(destination.iterdir()) == []


def test_export_does_not_mix_versions(tmp_path):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    catalog = {
        "schema_version": 1, "packages": {"release-a": {}}, "applications": {"vrmaster": {
            "name": "VRMaster", "versions": {
                "4.1.0": {"variants": {"sha-master": {"sha256": "sha-master",
                    "origin_packages": [{"package_id": "release-a", "relative_path": "VRMaster.jar"}]}}},
                "4.2.0": {"variants": {"sha-new": {"sha256": "sha-new",
                    "origin_packages": [{"package_id": "release-a", "relative_path": "VRMaster.jar"}]}}},
            }
        }}
    }
    _prepare(workspace, [
        {}, {"source_key": "new", "artifact_sha256": "sha-new",
             "output_reference": "sources/new", "source_relative_path": "New.java"},
    ], catalog=catalog)
    (workspace / "sources/master/br").mkdir(parents=True)
    (workspace / "sources/master/br/Venda.java").write_text("class Venda {}", encoding="utf-8")
    (workspace / "sources/new").mkdir(parents=True)
    (workspace / "sources/new/New.java").write_text("new", encoding="utf-8")

    result = _export(workspace, destination)
    assert not (Path(result["destination"]) / "New.java").exists()


def test_export_validates_physical_source_hash_when_body_is_also_present(tmp_path):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    body = "class Venda { int valor; }"
    _prepare(workspace, [{"body": body}])
    source = workspace / "sources/master/br/Venda.java"
    source.parent.mkdir(parents=True)
    source.write_text(body, encoding="utf-8")

    result = _export(workspace, destination)

    assert (Path(result["destination"]) / "br/Venda.java").read_text(encoding="utf-8") == body


def test_export_falls_back_to_index_body_when_physical_source_changed(tmp_path):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    indexed = "class Venda { int original; }"
    _prepare(workspace, [{"body": indexed}])
    source = workspace / "sources/master/br/Venda.java"
    source.parent.mkdir(parents=True)
    source.write_text("class Venda { int changed; }", encoding="utf-8")

    result = _export(workspace, destination)

    assert (Path(result["destination"]) / "br/Venda.java").read_text(encoding="utf-8") == indexed


def test_export_rejects_changed_physical_source_without_valid_body(tmp_path):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    indexed_hash = hashlib.sha256(b"class Original {}").hexdigest()
    _prepare(workspace, [{"body": "", "source_sha256": indexed_hash}])
    source = workspace / "sources/master/br/Venda.java"
    source.parent.mkdir(parents=True)
    source.write_text("class Changed {}", encoding="utf-8")

    with pytest.raises(ValueError, match="alterada|inconsistente"):
        _export(workspace, destination)

    assert list(destination.iterdir()) == []


def test_export_materializes_imported_vridx_body_without_physical_file(tmp_path):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    body = "package br;\nclass Importada {}\n"
    _prepare(workspace, [{
        "tool": "imported", "output_reference": "", "body": body,
        "source_relative_path": "br/Importada.java",
    }])

    result = _export(workspace, destination)

    assert (Path(result["destination"]) / "br/Importada.java").read_text(encoding="utf-8") == body


def test_export_rejects_invalid_body_hash_and_removes_staging(tmp_path):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    _prepare(workspace, [{
        "output_reference": "", "body": "class Invalid {}", "source_sha256": "0" * 64,
    }])

    with pytest.raises(ValueError, match="alterada|inconsistente"):
        _export(workspace, destination)

    assert list(destination.iterdir()) == []


def test_export_rejects_conflicting_contents_for_same_relative_path(tmp_path):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    _prepare(workspace, [
        {"output_reference": "", "body": "class Venda {}"},
        {"source_key": "conflict", "output_reference": "", "body": "class Venda { int x; }"},
    ])

    with pytest.raises(ValueError, match="conflitantes"):
        _export(workspace, destination)

    assert list(destination.iterdir()) == []
