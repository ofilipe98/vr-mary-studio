from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from vrsoft_extractor.mary import knowledge_transfer as kt
from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.content import sha256_text, write_document
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.models import KnowledgeDocument, ReviewFilters


def _settings(tmp_path: Path, name: str = "vr") -> MarySettings:
    settings = MarySettings(
        app_dir=(tmp_path / "app").resolve(),
        root=(tmp_path / name).resolve(),
        old_root=(tmp_path / "old").resolve(),
    )
    settings.app_dir.mkdir(parents=True, exist_ok=True)
    settings.old_root.mkdir(parents=True, exist_ok=True)
    settings.ensure_dirs()
    return settings


def _asset(settings: MarySettings, origin: str, content: bytes) -> str:
    directory = {
        "vrwiki": settings.assets_dir / "wiki",
        "endoo": settings.assets_dir / "wiki" / "endoo",
        "movidesk": settings.assets_dir / "kb",
    }[origin]
    digest = hashlib.sha256(content).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{digest}.png").write_bytes(content)
    relative = (
        f"assets/wiki/{digest}.png"
        if origin == "vrwiki"
        else f"assets/wiki/endoo/{digest}.png"
        if origin == "endoo"
        else f"assets/kb/{digest}.png"
    )
    return relative


def _seed(
    settings: MarySettings,
    *,
    source: str = "wiki",
    origin: str = "vrwiki",
    source_id: str = "1",
    title: str = "Documento Um",
    module: str = "Fiscal",
    review_status: str = "approved",
    markdown: str = "# Seção\n\nconteúdo original",
    assets: tuple[str, ...] = (),
) -> MaryDatabase:
    database = MaryDatabase(
        settings.database_path, root=settings.root, backup_portable_migration=False
    )
    document = KnowledgeDocument(
        source=source,
        source_origin=origin,
        source_id=source_id,
        title=title,
        url=f"https://example.test/{source_id}",
        markdown=markdown,
        module=module,
        classification_confidence=0.8,
        review_status=review_status,
        content_hash=sha256_text("\n".join([title, markdown])),
        synced_at="2026-01-01T00:00:00+00:00",
        assets=list(assets),
    )
    write_document(settings.root, document)
    database.upsert_document(document)
    return database


def _rewrite_zip(path: Path, mutate) -> None:
    with zipfile.ZipFile(path) as archive:
        items = {
            info.filename: archive.read(info.filename)
            for info in archive.infolist()
            if not info.is_dir()
        }
    items = mutate(items) or items
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in items.items():
            archive.writestr(name, content)


def _manifest_of(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read(kt.KNOWLEDGE_PACKAGE_MANIFEST).decode("utf-8"))


def test_export_import_round_trip_preserves_documents_and_assets(
    tmp_path: Path,
) -> None:
    source_settings = _settings(tmp_path, "source")
    wiki_asset = _asset(source_settings, "vrwiki", b"imagem-um")
    kb_asset = _asset(source_settings, "movidesk", b"anexo-dois")
    source_database = _seed(source_settings, source_id="1", assets=(wiki_asset,))
    _seed(
        source_settings,
        source="kb",
        origin="movidesk",
        source_id="kb-1",
        title="Artigo KB",
        module="PDV",
        assets=(kb_asset,),
    )

    destination = tmp_path / "conhecimento.zip"
    result = kt.export_knowledge_package(source_settings.root, destination)

    assert result["success"] is True
    assert result["document_count"] == 2
    assert result["asset_count"] == 2
    assert result["missing_asset_count"] == 0
    assert destination.is_file()
    with zipfile.ZipFile(destination) as archive:
        names = set(archive.namelist())
    assert kt.KNOWLEDGE_PACKAGE_MANIFEST in names
    assert kt.KNOWLEDGE_RECORDS_FILE in names
    assert any(name.startswith("files/conhecimento/") for name in names)
    assert wiki_asset in names
    assert kb_asset in names

    detection = kt.detect_knowledge_package_archive(destination, database=source_database)
    assert detection["is_valid"] is True
    assert detection["document_count"] == 2
    assert {item["action"] for item in detection["preview"]} == {"update"}

    target_settings = _settings(tmp_path, "target")
    imported = kt.import_knowledge_package_archive(
        target_settings.root, destination, mode="merge"
    )
    assert imported["success"] is True
    assert imported["created"] == 2
    assert imported["error_count"] == 0
    target_database = MaryDatabase(
        target_settings.database_path,
        root=target_settings.root,
        backup_portable_migration=False,
    )
    document = target_database.get_document("wiki", "1")
    assert document is not None
    assert document["module"] == "Fiscal"
    assert (target_settings.root / document["local_path"]).is_file()
    assert (target_settings.root / wiki_asset).is_file()
    assert (target_settings.root / kb_asset).is_file()
    assert (target_settings.index_dir / "catalogo.jsonl").is_file()

    again = kt.import_knowledge_package_archive(
        target_settings.root, destination, mode="merge"
    )
    assert again["unchanged"] == 2
    assert again["created"] == 0


def test_export_excludes_endoo_unless_explicitly_selected(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings, origin="vrwiki", source_id="publico")
    _seed(settings, origin="endoo", source_id="endoo-9", title="Artigo Endoo")

    default_export = tmp_path / "padrao.zip"
    result = kt.export_knowledge_package(settings.root, default_export)
    assert result["document_count"] == 1
    detection = kt.detect_knowledge_package_archive(default_export)
    assert [(item["source"], item["source_origin"]) for item in detection["origins"]] == [
        ("wiki", "vrwiki")
    ]

    endoo_export = tmp_path / "endoo.zip"
    result = kt.export_knowledge_package(
        settings.root,
        endoo_export,
        origins=(("wiki", "vrwiki"), ("wiki", "endoo")),
    )
    assert result["document_count"] == 2
    detection = kt.detect_knowledge_package_archive(endoo_export)
    assert {item["source_origin"] for item in detection["origins"]} == {
        "vrwiki",
        "endoo",
    }


def test_export_filters_by_module(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings, source_id="fiscal", module="Fiscal")
    _seed(settings, source_id="pdv", title="Documento PDV", module="PDV")

    destination = tmp_path / "fiscal.zip"
    result = kt.export_knowledge_package(
        settings.root, destination, module="Fiscal"
    )

    assert result["document_count"] == 1
    detection = kt.detect_knowledge_package_archive(destination)
    assert detection["modules"] == ["Fiscal"]

    with pytest.raises(ValueError):
        kt.export_knowledge_package(settings.root, tmp_path / "vazio.zip", module="Outro")


def test_export_reports_missing_assets_without_aborting(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings, source_id="sem-anexo", assets=("assets/wiki/inexistente.png",))

    destination = tmp_path / "sem-anexo.zip"
    result = kt.export_knowledge_package(settings.root, destination)

    assert result["missing_asset_count"] == 1
    assert result["asset_count"] == 0
    detection = kt.detect_knowledge_package_archive(destination)
    assert detection["is_valid"] is True
    assert detection["missing_asset_count"] == 1


def test_export_destination_is_non_destructive(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings)
    first = kt.export_knowledge_package(settings.root, tmp_path / "base.zip")
    second = kt.export_knowledge_package(settings.root, tmp_path / "base.zip")

    assert first["destination"].endswith("base.zip")
    assert second["destination"].endswith("base-2.zip")
    assert Path(second["destination"]).is_file()


def test_detect_rejects_modified_records_payload(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings)
    destination = tmp_path / "pacote.zip"
    kt.export_knowledge_package(settings.root, destination)

    _rewrite_zip(
        destination,
        lambda items: {
            **items,
            kt.KNOWLEDGE_RECORDS_FILE: items[kt.KNOWLEDGE_RECORDS_FILE] + b"\n",
        },
    )

    detection = kt.detect_knowledge_package_archive(destination)
    assert detection["is_valid"] is False
    assert "corrompida" in detection["error"]
    with pytest.raises(ValueError):
        kt.import_knowledge_package_archive(_settings(tmp_path, "target").root, destination)


def test_import_rejects_corrupted_asset_before_writing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    asset = _asset(settings, "vrwiki", b"conteudo-original")
    _seed(settings, assets=(asset,))
    destination = tmp_path / "pacote.zip"
    kt.export_knowledge_package(settings.root, destination)

    def corrupt(items):
        items[asset] = b"X" * len(items[asset])
        return items

    _rewrite_zip(destination, corrupt)
    target = _settings(tmp_path, "target")

    with pytest.raises(ValueError, match="anexo"):
        kt.import_knowledge_package_archive(target.root, destination)

    assert not (target.root / asset).exists()
    target_database = MaryDatabase(
        target.database_path, root=target.root, backup_portable_migration=False
    )
    assert target_database.get_document("wiki", "1") is None


def test_merge_preserves_local_approved_module_and_queues_review(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    _seed(settings, module="Fiscal", markdown="# Seção\n\nconteúdo do pacote")
    destination = tmp_path / "pacote.zip"
    kt.export_knowledge_package(settings.root, destination)

    target = _settings(tmp_path, "target")
    _seed(
        target,
        module="PDV",
        review_status="approved",
        markdown="# Seção\n\nconteúdo local",
    )
    imported = kt.import_knowledge_package_archive(target.root, destination, mode="merge")

    assert imported["updated"] == 1
    assert imported["review_queued"] == 1
    database = MaryDatabase(
        target.database_path, root=target.root, backup_portable_migration=False
    )
    document = database.get_document("wiki", "1")
    assert document is not None
    assert document["module"] == "PDV"
    assert document["review_status"] == "pending"
    assert "conteúdo do pacote" in document["markdown"]
    reviews = database.query_reviews(ReviewFilters(status="pending"))
    assert reviews.total == 1


def test_restore_overwrites_local_review_decisions(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed(settings, module="Fiscal", markdown="# Seção\n\nconteúdo do pacote")
    destination = tmp_path / "pacote.zip"
    kt.export_knowledge_package(settings.root, destination)

    target = _settings(tmp_path, "target")
    _seed(
        target,
        module="PDV",
        review_status="approved",
        markdown="# Seção\n\nconteúdo local",
    )
    imported = kt.import_knowledge_package_archive(
        target.root, destination, mode="restore"
    )

    assert imported["updated"] == 1
    assert imported["review_queued"] == 0
    database = MaryDatabase(
        target.database_path, root=target.root, backup_portable_migration=False
    )
    document = database.get_document("wiki", "1")
    assert document is not None
    assert document["module"] == "Fiscal"
    assert document["review_status"] == "approved"


def test_progress_contract_reports_start_intervals_and_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(kt, "_PROGRESS_REPORT_INTERVAL", 2)
    settings = _settings(tmp_path)
    _seed(settings, source_id="1")
    _seed(settings, source_id="2", title="Documento Dois")
    _seed(settings, source_id="3", title="Documento Três")

    events: list[dict[str, int]] = []
    destination = tmp_path / "progresso.zip"
    kt.export_knowledge_package(settings.root, destination, progress=events.append)

    assert events[0] == {"current": 0, "total": 3}
    assert events[-1] == {"current": 3, "total": 3}
    assert events[1]["current"] == 2
    assert all(event["current"] <= event["total"] for event in events)

    target = _settings(tmp_path, "target")
    imported_events: list[dict[str, int]] = []
    kt.import_knowledge_package_archive(
        target.root, destination, progress=imported_events.append
    )
    assert imported_events[0] == {"current": 0, "total": 3}
    assert imported_events[-1] == {"current": 3, "total": 3}


def test_manual_package_with_invalid_module_is_rejected(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = MaryDatabase(
        settings.database_path, root=settings.root, backup_portable_migration=False
    )
    markdown = "# Seção\n\nconteúdo"
    title = "Documento"
    record = {
        "source": "wiki",
        "source_origin": "vrwiki",
        "source_id": "1",
        "title": title,
        "url": "",
        "module": "ModuloInexistente",
        "classification_confidence": 0.0,
        "review_status": "approved",
        "status": "active",
        "created_at": "",
        "updated_at": "",
        "synced_at": "",
        "revision": "",
        "content_hash": sha256_text("\n".join([title, markdown])),
        "category": "",
        "product": "",
        "markdown": markdown,
        "document_path": "files/conhecimento/Fiscal/Wiki/documento--1.md",
        "assets": [],
    }
    payload = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    manifest = {
        "format": kt.KNOWLEDGE_PACKAGE_FORMAT,
        "schema_version": kt.KNOWLEDGE_PACKAGE_SCHEMA_VERSION,
        "package_id": "knowledge-test",
        "exported_at": "2026-01-01T00:00:00+00:00",
        "origins": [],
        "modules": [],
        "document_count": 1,
        "asset_count": 0,
        "missing_asset_count": 0,
        "file_count": 1,
        "document_bytes": 0,
        "asset_bytes": 0,
        "total_bytes": 0,
        "records_sha256": hashlib.sha256(payload).hexdigest(),
    }
    destination = tmp_path / "invalido.zip"
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(kt.KNOWLEDGE_RECORDS_FILE, payload)
        archive.writestr(
            kt.KNOWLEDGE_PACKAGE_MANIFEST,
            json.dumps(manifest, ensure_ascii=False),
        )

    detection = kt.detect_knowledge_package_archive(destination, database=database)
    assert detection["is_valid"] is False
    assert "módulo" in detection["error"].casefold()
