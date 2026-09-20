import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from vrsoft_extractor.mary.apps_catalog import AppsCatalogStore
from vrsoft_extractor.mary.code_index import JavaCodeIndex
from vrsoft_extractor.mary.decompiled_export import (
    export_decompiled_package,
    export_decompiled_source,
)


def _prepare(workspace: Path, records: list[dict], *, catalog=None) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
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
    connection = sqlite3.connect(index.store.database_path)
    try:
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
    finally:
        connection.close()


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
        "version": "4.1.0", "variant_id": "sha-master", "release_id": "release-a",
        "origin_id": "release-a", "artifact_sha256": "sha-master",
        "jar_relative_path": "VRMaster.jar",
        "exported_at": "ignored", "file_count": 1, "total_bytes": len("class Venda {}"),
    }
    assert manifest["application_id"] == "vrmaster"
    assert manifest["version"] == "4.1.0"
    assert manifest["variant_id"] == "sha-master"
    assert manifest["origin_id"] == "release-a"
    assert manifest["artifact_sha256"] == "sha-master"
    assert manifest["jar_relative_path"] == "VRMaster.jar"
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


@pytest.mark.parametrize("source_path", [
    "CON.java", "NUL.kt", "COM1.java", "LPT9.kt", "Foo.", "Foo ",
    "Foo.java.", "Foo.java ", "Bad<Name>.java", "Bad:Name.java", "Bad?.java",
])
def test_export_rejects_windows_incompatible_source_components(tmp_path, source_path):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    _prepare(workspace, [{"output_reference": "", "source_relative_path": source_path}])

    with pytest.raises(ValueError, match="incompatível com Windows"):
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


def test_export_uses_indexed_lf_body_when_physical_source_is_crlf(tmp_path):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    indexed = "package br;\nclass Venda {}\n"
    _prepare(workspace, [{"body": indexed}])
    source = workspace / "sources/master/br/Venda.java"
    source.parent.mkdir(parents=True)
    source.write_bytes(indexed.replace("\n", "\r\n").encode("utf-8"))

    result = _export(workspace, destination)

    assert (Path(result["destination"]) / "br/Venda.java").read_bytes() == indexed.encode("utf-8")


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


@pytest.mark.parametrize("bodies", [
    ("class Foo {}", "class Foo {}"),
    ("class Foo {}", "class foo {}"),
])
def test_export_rejects_case_insensitive_source_path_collisions(tmp_path, bodies):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    _prepare(workspace, [
        {"source_relative_path": "br/Foo.java", "body": bodies[0]},
        {"source_key": "case-collision", "source_relative_path": "br/foo.java", "body": bodies[1]},
    ])

    with pytest.raises(ValueError, match="caminhos incompatíveis com Windows"):
        _export(workspace, destination)

    assert list(destination.iterdir()) == []


def test_export_iterates_index_rows_without_fetchall(tmp_path, monkeypatch):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    records = [
        {
            "source_key": f"bulk-{number}",
            "output_reference": "",
            "source_relative_path": f"bulk/File{number}.java",
            "body": f"class File{number} {{}}",
        }
        for number in range(128)
    ]
    _prepare(workspace, records)

    import vrsoft_extractor.mary.decompiled_export as export_module

    real_connect = export_module.sqlite3.connect

    class CursorGuard:
        def __init__(self, cursor):
            self._cursor = cursor

        def __iter__(self):
            return iter(self._cursor)

        def fetchall(self):
            raise AssertionError("exportação não deve carregar todas as linhas")

    class ConnectionGuard:
        def __init__(self, connection):
            self._connection = connection

        def __enter__(self):
            self._connection.__enter__()
            return self

        def __exit__(self, *args):
            return self._connection.__exit__(*args)

        def __setattr__(self, name, value):
            if name == "_connection":
                object.__setattr__(self, name, value)
            else:
                setattr(self._connection, name, value)

        def execute(self, *args, **kwargs):
            return CursorGuard(self._connection.execute(*args, **kwargs))

        def close(self):
            return self._connection.close()

    def guarded_connect(*args, **kwargs):
        return ConnectionGuard(real_connect(*args, **kwargs))

    monkeypatch.setattr(export_module.sqlite3, "connect", guarded_connect)
    result = _export(workspace, destination)

    assert result["file_count"] == 128
    assert len(list(Path(result["destination"]).glob("bulk/*.java"))) == 128


def _portable_catalog() -> dict:
    return {
        "schema_version": 1,
        "applications": {
            "vrmaster": {
                "name": "VRMaster",
                "versions": {"4.1.0": {"variants": {"a" * 64: {
                    "variant_id": "a" * 64,
                    "sha256": "a" * 64,
                    "class_count": 1,
                    "size_bytes": 40,
                    "relative_path": "VRMaster.jar",
                    "origin_packages": [{"package_id": "release-a", "relative_path": "VRMaster.jar"}],
                }}}},
            },
            "vradm": {
                "name": "VRAdm",
                "versions": {"3.2.15.0": {"variants": {"c" * 64: {
                    "variant_id": "c" * 64,
                    "sha256": "c" * 64,
                    "class_count": 1,
                    "size_bytes": 40,
                    "relative_path": "VRAdm.jar",
                    "origin_packages": [{"package_id": "release-a", "relative_path": "VRAdm.jar"}],
                }}}},
            },
        },
        "packages": {"release-a": {
            "package_id": "release-a",
            "name": "Pacote A",
            "manifest_sha256": "e" * 64,
            "composition": [
                {"app_id": "vrmaster", "app_name": "VRMaster", "version": "4.1.0",
                 "variant_id": "a" * 64, "distribution_id": "dist-master",
                 "jar_path": "VRMaster.jar", "sha256": "a" * 64},
                {"app_id": "vradm", "app_name": "VRAdm", "version": "3.2.15.0",
                 "variant_id": "c" * 64, "distribution_id": "dist-adm",
                 "jar_path": "VRAdm.jar", "sha256": "c" * 64},
            ],
            "dependencies": [
                {"relative_path": "VRFramework.jar", "sha256": "d" * 64, "size_bytes": 25},
            ],
        }},
    }


def _portable_records() -> list[dict]:
    return [
        {"source_key": "master-java", "artifact_sha256": "a" * 64,
         "jar_relative_path": "VRMaster.jar", "output_reference": "",
         "source_relative_path": "br/com/vr/App.java",
         "body": "package br.com.vr;\npublic class App {}\n"},
        {"source_key": "adm-kt", "artifact_sha256": "c" * 64,
         "jar_relative_path": "VRAdm.jar", "output_reference": "",
         "source_relative_path": "br/com/vr/config/AppConfig.kt",
         "body": "package br.com.vr.config\nclass AppConfig\n"},
        {"source_key": "framework-java", "artifact_sha256": "d" * 64,
         "jar_relative_path": "VRFramework.jar", "output_reference": "",
         "source_relative_path": "br/com/vr/Util.java",
         "body": "package br.com.vr;\npublic class Util {}\n"},
    ]


def test_export_decompiled_package_contains_all_release_sources_and_manifest(tmp_path):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    _prepare(workspace, _portable_records(), catalog=_portable_catalog())

    result = export_decompiled_package(
        workspace, destination / "Pacote-decompiled.zip", package_id="release-a"
    )

    exported = Path(result["destination"])
    assert exported.name == "Pacote-decompiled.zip"
    assert result["artifact_count"] == 3
    with zipfile.ZipFile(exported) as archive:
        names = archive.namelist()
        assert names.count("vrstudio-package-export.json") == 1
        manifest = json.loads(
            archive.read("vrstudio-package-export.json").decode("utf-8")
        )
        assert manifest["format"] == "vrstudio-decompiled-package"
        assert manifest["schema_version"] == 1
        assert manifest["package_id"] == "release-a"
        assert manifest["package_name"] == "Pacote A"
        assert manifest["package_manifest_sha256"] == "e" * 64
        expected_bytes = sum(
            len(str(record["body"]).encode("utf-8")) for record in _portable_records()
        )
        assert manifest["file_count"] == 3
        assert manifest["total_bytes"] == expected_bytes
        assert result["file_count"] == 3
        assert result["total_bytes"] == expected_bytes

        artifacts = manifest["artifacts"]
        assert [item["role"] for item in artifacts].count("application") == 2
        assert [item["role"] for item in artifacts].count("dependency") == 1
        applications = {item["application_id"]: item for item in artifacts
                        if item["role"] == "application"}
        assert set(applications) == {"vrmaster", "vradm"}
        assert applications["vrmaster"]["application_name"] == "VRMaster"
        assert applications["vrmaster"]["version"] == "4.1.0"
        dependency = next(item for item in artifacts if item["role"] == "dependency")
        assert dependency["jar_relative_path"] == "VRFramework.jar"
        assert dependency["artifact_sha256"] == "d" * 64

        exported_paths = []
        for item in artifacts:
            assert item["source_count"] == len(item["sources"]) >= 1
            for source in item["sources"]:
                assert source["archive_path"] == (
                    f"sources/{item['artifact_index']:04d}/"
                    f"{source['source_relative_path']}"
                )
                content = archive.read(source["archive_path"])
                assert hashlib.sha256(content).hexdigest() == source["source_sha256"]
                exported_paths.append(source["archive_path"])
        assert sorted(exported_paths) == sorted(names[:0] + [
            name for name in names if name != "vrstudio-package-export.json"
        ])
        assert str(workspace) not in json.dumps(manifest)
        assert all(
            not name.startswith("/") and ":" not in name and ".." not in name.split("/")
            for name in names
        )


def test_export_decompiled_package_is_non_destructive(tmp_path):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    _prepare(workspace, _portable_records(), catalog=_portable_catalog())

    first = export_decompiled_package(
        workspace, destination / "Pacote.zip", package_id="release-a"
    )
    second = export_decompiled_package(
        workspace, destination / "Pacote.zip", package_id="release-a"
    )
    third = export_decompiled_package(
        workspace, destination / "Pacote.zip", package_id="release-a"
    )

    assert Path(first["destination"]).name == "Pacote.zip"
    assert Path(second["destination"]).name == "Pacote-2.zip"
    assert Path(third["destination"]).name == "Pacote-3.zip"
    assert sorted(path.name for path in destination.iterdir()) == [
        "Pacote-2.zip", "Pacote-3.zip", "Pacote.zip",
    ]


def test_export_decompiled_package_removes_partial_zip_on_failure(tmp_path):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    records = _portable_records()
    records.append({
        "source_key": "broken", "artifact_sha256": "d" * 64,
        "jar_relative_path": "VRFramework.jar", "output_reference": "",
        "source_relative_path": "br/com/vr/Broken.java", "body": "",
        "source_sha256": "0" * 64,
    })
    _prepare(workspace, records, catalog=_portable_catalog())

    with pytest.raises(ValueError, match="alterada|inconsistente"):
        export_decompiled_package(
            workspace, destination / "Pacote.zip", package_id="release-a"
        )

    assert list(destination.iterdir()) == []


def test_export_decompiled_package_rejects_conflicting_duplicate_source(tmp_path):
    workspace, destination = tmp_path / "workspace", tmp_path / "exports"
    destination.mkdir()
    _prepare(workspace, [
        {"source_key": "one", "artifact_sha256": "a" * 64,
         "jar_relative_path": "VRMaster.jar", "output_reference": "",
         "source_relative_path": "br/com/vr/App.java", "body": "class App {}"},
        {"source_key": "two", "artifact_sha256": "a" * 64,
         "jar_relative_path": "VRMaster.jar", "output_reference": "",
         "source_relative_path": "br/com/vr/App.java",
         "body": "class App { int changed; }"},
    ], catalog=_portable_catalog())

    with pytest.raises(ValueError, match="conflitantes"):
        export_decompiled_package(
            workspace, destination / "Pacote.zip", package_id="release-a"
        )

    assert list(destination.iterdir()) == []

