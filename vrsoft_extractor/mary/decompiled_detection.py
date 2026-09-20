"""Detection and direct ingestion of already-decompiled Java sources.

Supports migrating decompiled applications (e.g. VRMaster, VRAdm) or full packages
from Machine 1 to Machine 2 without requiring JVM decompiler toolchains.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from uuid import uuid4

from .apps_catalog import AppsCatalogStore, UNIDENTIFIED_VERSION, _transaction
from .code_index import (
    CODE_INDEX_SCHEMA_VERSION,
    JavaCodeIndex,
    _code_source_key,
    parse_java_source,
    parse_kotlin_source,
)
from .decompiled_export import (
    PORTABLE_PACKAGE_FORMAT,
    PORTABLE_PACKAGE_MANIFEST,
    PORTABLE_PACKAGE_SCHEMA_VERSION,
    _relative_source_path,
    _require_within,
)
from .erp_releases import parse_java_properties, _safe_component
from .jvm_batches import PROCESSING_SCHEMA_VERSION


_PROPERTIES_VERSION_KEYS = ("versao.major", "versao.minor", "versao.release")
_JAVA_EXTENSIONS = {".java", ".kt"}
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_SYMLINK_FILE_MODE = 0o120000


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_app_display_name(stem: str) -> str:
    s = stem.strip()
    if s.lower().startswith("vr"):
        return "VR" + s[2:].capitalize()
    return s.capitalize()


def detect_decompiled_source(source_dir: str | Path) -> dict[str, Any]:
    """Inspect a directory of decompiled files and extract application identities and versions.

    Detects both single applications (e.g. a decompiled VRMaster folder) and
    bundled multi-application packages.
    """
    root = Path(source_dir).resolve()
    if not root.is_dir():
        return {
            "is_valid": False,
            "error": f"Diretório não encontrado: {root}",
            "applications": [],
            "total_java_files": 0,
        }

    # Find all properties files
    properties_files = [
        p for p in root.rglob("*.properties")
        if p.is_file() and not p.name.startswith(".")
    ]

    detected_apps: list[dict[str, Any]] = []
    processed_dirs: set[Path] = set()

    for prop_file in sorted(properties_files, key=lambda p: len(p.parts)):
        try:
            content = prop_file.read_bytes()
            props = parse_java_properties(content)
        except Exception:
            continue

        has_version = all(props.get(k) for k in _PROPERTIES_VERSION_KEYS)
        if not has_version:
            continue

        app_stem = prop_file.stem
        app_key = _safe_component(app_stem).casefold()
        app_name = _format_app_display_name(app_stem)

        major = props.get("versao.major", "0")
        minor = props.get("versao.minor", "0")
        release = props.get("versao.release", "0")
        build = props.get("versao.build", "0")
        beta = props.get("versao.beta", "0")

        version = f"{major}.{minor}.{release}.{build or '0'}"
        if beta and beta not in {"", "0"}:
            version += f"-beta{beta}"

        app_date = props.get("app.data", "")

        # Determine app source directory (parent of properties file or root)
        app_root = prop_file.parent
        if app_root.name in {"resources", "res", "config"} and app_root != root:
            app_root = app_root.parent

        if app_root in processed_dirs:
            return {"is_valid": False, "error": "Há múltiplos aplicativos na mesma pasta; separe os fontes por aplicativo.", "applications": [], "total_java_files": 0}
        processed_dirs.add(app_root)

        detected_apps.append({
            "app_id": app_key,
            "app_name": app_name,
            "version": version,
            "application_date": app_date,
            "properties_path": str(prop_file),
            "source_dir": str(app_root),
            "java_count": 0,
            "source_files": [],
        })

    # If no .properties found with versions, check for raw java files and deduce app identity
    all_java_files = sorted(
        f for f in root.rglob("*")
        if f.is_file() and f.suffix.casefold() in _JAVA_EXTENSIONS
        and f.resolve().is_relative_to(root)
    )

    inferred_apps: dict[str, dict[str, Any]] = {}
    for source in all_java_files:
        owners = [app for app in detected_apps if source.is_relative_to(Path(app["source_dir"]))]
        if owners:
            app = max(owners, key=lambda item: len(Path(item["source_dir"]).parts))
        else:
            inferred_app = _infer_app_from_java_files([source])
            app = inferred_apps.setdefault(inferred_app, {
                "app_id": _safe_component(inferred_app).casefold(),
                "app_name": inferred_app,
                "version": UNIDENTIFIED_VERSION,
                "application_date": "",
                "properties_path": "",
                "source_dir": str(root),
                "java_count": 0,
                "source_files": [],
                "inferred": True,
            })
        app["source_files"].append(str(source))
        app["java_count"] += 1
    detected_apps = [app for app in detected_apps + list(inferred_apps.values()) if app["java_count"]]
    if len({app["app_id"] for app in detected_apps}) != len(detected_apps):
        return {"is_valid": False, "error": "Há mais de uma versão do mesmo aplicativo; importe cada versão separadamente.", "applications": [], "total_java_files": 0}

    total_java = sum(a["java_count"] for a in detected_apps) or len(all_java_files)
    is_valid = len(detected_apps) > 0 and total_java > 0
    scope = "single_app" if len(detected_apps) == 1 else ("package" if len(detected_apps) > 1 else "none")

    if len(detected_apps) == 1:
        app = detected_apps[0]
        suggested_id = f"decompiled-{app['app_id']}-{app['version']}"
    elif detected_apps:
        dates = [a["application_date"] for a in detected_apps if a["application_date"]]
        latest_date = max(dates).replace("-", ".") if dates else "sem-data"
        suggested_id = f"decompiled-erp-{latest_date}-{len(detected_apps)}apps"
    else:
        suggested_id = f"decompiled-{root.name}"

    return {
        "is_valid": is_valid,
        "scope": scope,
        "source_root": str(root),
        "applications": detected_apps,
        "total_java_files": total_java,
        "suggested_release_id": _safe_component(suggested_id),
        "suggested_name": f"Fontes Descompilados: {detected_apps[0]['app_name'] if len(detected_apps) == 1 else f'{len(detected_apps)} aplicativos'}",
    }


def _infer_app_from_java_files(java_files: list[Path]) -> str:
    """Inspect the first few .java files to guess the application name from package declarations."""
    for jf in java_files[:10]:
        try:
            head = jf.read_text(encoding="utf-8", errors="replace")[:1000]
            match = re.search(r"package\s+vr\.([a-zA-Z0-9_]+)", head)
            if match:
                return _format_app_display_name(match.group(1)) if match.group(1).lower().startswith("vr") else f"VR{match.group(1).capitalize()}"
        except Exception:
            continue
    return "VRApp"


@_transaction
def _import_decompiled_source(
    store: AppsCatalogStore,
    workspace: str | Path,
    source_dir: str | Path,
    *,
    release_id: str = "",
    package_name: str = "",
    apps_store: AppsCatalogStore | None = None,
) -> dict[str, Any]:
    """Ingest already-decompiled Java sources into VRStudio SQLite index and apps catalog.

    Bypasses JVM decompiler toolchains completely.
    """
    ws = Path(workspace).resolve()
    detection = detect_decompiled_source(source_dir)
    if not detection.get("is_valid"):
        raise ValueError(detection.get("error") or "Nenhum arquivo Java válido detectado no diretório.")

    selected_release_id = (release_id or detection["suggested_release_id"]).strip()
    if not selected_release_id or _safe_component(selected_release_id) != selected_release_id:
        raise ValueError("Identificador de release inválido.")
    selected_pkg_name = (package_name or detection["suggested_name"]).strip()

    if store.get_package(selected_release_id):
        raise ValueError("Já existe um pacote com este identificador; use outro identificador.")
    target = (ws / "indice/codigo/decompilation" / selected_release_id).resolve()
    if target.exists():
        raise ValueError("O diretório de destino já existe; use outro identificador.")
    if target.is_relative_to(Path(source_dir).resolve()):
        raise ValueError("A pasta de origem não pode conter o diretório de destino.")
    code_index = JavaCodeIndex(ws)
    code_index.initialize()
    batch_store = code_index.store
    with batch_store.connect() as conn:
        if conn.execute("SELECT 1 FROM code_sources WHERE release_id = ? LIMIT 1", (selected_release_id,)).fetchone() or conn.execute(
            "SELECT 1 FROM decompilation_plans WHERE release_id = ? LIMIT 1", (selected_release_id,)
        ).fetchone():
            raise ValueError("Já existem dados indexados com este identificador; use outro identificador.")

    decomp_root = ws / "indice" / "codigo" / "decompilation" / selected_release_id
    decomp_root.mkdir(parents=True, exist_ok=False)

    artifacts_for_catalog: list[dict[str, Any]] = []
    total_indexed = 0

    now = _utc_now()
    release_hash = hashlib.sha256(selected_release_id.encode("utf-8")).hexdigest()

    try:
        with batch_store.connect() as conn:
            # Record completed decompilation plan
            conn.execute(
                """INSERT INTO decompilation_plans
                   (plan_id, schema_version, release_id, release_hash, state,
                    max_classes, max_bytes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'completed', ?, ?, ?, ?)""",
                (
                    selected_release_id,
                    PROCESSING_SCHEMA_VERSION,
                    selected_release_id,
                    release_hash,
                    detection["total_java_files"],
                    0,
                    now,
                    now,
                ),
            )

            for app in detection["applications"]:
                app_id = app["app_id"]
                app_name = app["app_name"]
                version = app["version"]
                src_dir = Path(app["source_dir"])

                app_target_dir = decomp_root / app_id
                app_target_dir.mkdir(parents=True, exist_ok=True)

                java_files = [Path(name) for name in app["source_files"]]

                class_signatures: dict[str, str] = {}
                app_hash_digest = hashlib.sha256()
                for jf in java_files:
                    app_hash_digest.update(jf.relative_to(src_dir).as_posix().encode("utf-8"))
                    app_hash_digest.update(hashlib.sha256(jf.read_bytes()).digest())
                app_sha256 = app_hash_digest.hexdigest()

                for jf in java_files:
                    rel_path = jf.relative_to(src_dir).as_posix()
                    dest_file = app_target_dir / rel_path
                    dest_file.parent.mkdir(parents=True, exist_ok=True)

                    body = jf.read_text(encoding="utf-8", errors="replace")
                    dest_file.write_text(body, encoding="utf-8")

                    body_bytes = body.encode("utf-8")
                    file_hash = hashlib.sha256(body_bytes).hexdigest()

                    class_key = rel_path.rsplit(".", 1)[0].replace("/", ".")
                    class_signatures[class_key] = file_hash

                    fallback_qualified = rel_path.rsplit(".", 1)[0].replace("/", ".")
                    parser = parse_kotlin_source if jf.suffix.casefold() == ".kt" else parse_java_source
                    parsed = parser(body, fallback_qualified=fallback_qualified)

                    source_key = _code_source_key(
                        release_id=selected_release_id,
                        release_hash=release_hash,
                        artifact_sha256=app_sha256,
                        class_version=52,
                        qualified_name=parsed.qualified_name,
                        content_hashes=[file_hash],
                    )

                    symbols_text = " ".join(
                        dict.fromkeys(
                            [parsed.qualified_name]
                            + [str(item["simple_name"]) for item in parsed.symbols]
                            + [str(item["signature"]) for item in parsed.symbols]
                            + [str(item["target"]) for item in parsed.relations]
                        )
                    )

                    output_ref = f"indice/codigo/decompilation/{selected_release_id}/{app_id}"
                    cursor = conn.execute(
                        """INSERT INTO code_sources
                           (source_key, schema_version, release_id, release_hash,
                            jar_relative_path, artifact_sha256, batch_id,
                            class_version, tool,
                            output_reference, source_relative_path, source_sha256,
                            package_name, primary_type, qualified_name,
                            logical_names_json, content_hashes_json, occurrence_count,
                            parser_kind, syntax_error_count, symbols_text, body, indexed_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            source_key,
                            CODE_INDEX_SCHEMA_VERSION,
                            selected_release_id,
                            release_hash,
                            f"{app_id}.jar",
                            app_sha256,
                            f"batch-{selected_release_id}-{app_id}",
                            52,
                            "decompiled_import",
                            output_ref,
                            rel_path,
                            file_hash,
                            parsed.package_name,
                            parsed.primary_type,
                            parsed.qualified_name,
                            json.dumps([parsed.qualified_name]),
                            json.dumps([file_hash]),
                            1,
                            parsed.parser_kind,
                            parsed.syntax_error_count,
                            symbols_text,
                            body,
                            now,
                        ),
                    )
                    source_id = cursor.lastrowid
                    conn.executemany(
                        """INSERT INTO code_symbols
                           (source_id, kind, simple_name, qualified_name, signature, visibility, line_start)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        [(source_id, item["kind"], item["simple_name"], item["qualified_name"],
                          item["signature"], item["visibility"], item["line_start"])
                         for item in parsed.symbols],
                    )
                    conn.executemany(
                        """INSERT INTO code_relations
                           (source_id, kind, target, source_symbol, confidence, line_start)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        [(source_id, item["kind"], item["target"], item.get("source_symbol", ""),
                          float(item.get("confidence", 0.0)), item["line_start"])
                         for item in parsed.relations],
                    )
                    total_indexed += 1


                app_sha256 = app_hash_digest.hexdigest()
                artifacts_for_catalog.append({
                    "application_key": app_id,
                    "application_name": app_name,
                    "version_detected": version,
                    "sha256": app_sha256,
                    "file_size": sum(f.stat().st_size for f in java_files),
                    "relative_path": f"{app_id}.jar",
                    "class_signatures": class_signatures,
                    "decompiled_classes": len(java_files),
                })

            synthetic_manifest = {
                "release_id": selected_release_id,
                "release_manifest_sha256": release_hash,
                "source_dir": str(source_dir),
                "source_origin_dir": str(source_dir),
                "analysis_scope": detection["scope"],
                "artifacts": artifacts_for_catalog,
                "indexed_at": now,
            }

            registered_pkg = store.register_package(
                synthetic_manifest,
                package_id=selected_release_id,
                package_name=selected_pkg_name,
                source_path=str(source_dir),
            )

            for art in artifacts_for_catalog:
                store.update_variant_state(
                    art["application_key"],
                    art["version_detected"],
                    art["sha256"],
                    "ready",
                    decompilation_state="ready",
                    class_count=art["decompiled_classes"],
                    indexed_classes=art["decompiled_classes"],
                    decompiled_classes=art["decompiled_classes"],
                )
            conn.commit()
    except Exception:
        shutil.rmtree(decomp_root)
        raise

    return {
        "success": True,
        "release_id": selected_release_id,
        "package_name": selected_pkg_name,
        "imported_applications": len(detection["applications"]),
        "total_indexed_sources": total_indexed,
        "package": registered_pkg,
    }


def import_decompiled_source(
    workspace: str | Path,
    source_dir: str | Path,
    *,
    release_id: str = "",
    package_name: str = "",
    apps_store: AppsCatalogStore | None = None,
) -> dict[str, Any]:
    store = apps_store or AppsCatalogStore(root=workspace)
    return _import_decompiled_source(
        store, workspace, source_dir, release_id=release_id, package_name=package_name
    )


def _portable_archive_error(message: str) -> dict[str, Any]:
    return {
        "is_valid": False,
        "portable_package": True,
        "error": message,
        "applications": [],
        "total_java_files": 0,
    }


def _validate_zip_entry_name(name: str, *, label: str = "entrada") -> str:
    """Reject ZIP slip variants before any path is used."""
    raw = str(name or "")
    if not raw:
        raise ValueError(f"O pacote contém uma {label} ZIP sem nome.")
    normalized = raw.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("//") or PurePosixPath(normalized).is_absolute():
        raise ValueError(f"O pacote contém um caminho absoluto: {raw}")
    if PureWindowsPath(raw).is_absolute() or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"O pacote contém um caminho com unidade Windows: {raw}")
    if ".." in PurePosixPath(normalized).parts:
        raise ValueError(f"O pacote contém um caminho com '..': {raw}")
    return normalized


def _archive_entry_is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == _SYMLINK_FILE_MODE


def _read_validated_archive_source(
    archive: zipfile.ZipFile,
    entries: dict[str, zipfile.ZipInfo],
    archive_path: str,
    expected_hash: str,
) -> bytes:
    normalized = str(archive_path or "").replace("\\", "/")
    info = entries.get(normalized)
    if info is None:
        raise ValueError(f"O pacote não contém a fonte referenciada: {archive_path}")
    content = archive.read(info.filename)
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise ValueError(f"A fonte do pacote está corrompida: {archive_path}")
    return content


def detect_decompiled_package_archive(source_archive: str | Path) -> dict[str, Any]:
    """Validate a portable decompiled package ZIP without mutating anything."""
    archive_path = Path(source_archive).expanduser()
    try:
        resolved = archive_path.resolve(strict=True)
    except OSError:
        return _portable_archive_error(f"Arquivo não encontrado: {archive_path}")
    if not resolved.is_file() or resolved.suffix.casefold() != ".zip":
        return _portable_archive_error("Selecione um arquivo ZIP de pacote descompilado.")
    if not zipfile.is_zipfile(resolved):
        return _portable_archive_error("O arquivo selecionado não é um ZIP válido.")
    try:
        with zipfile.ZipFile(resolved) as archive:
            entries: dict[str, zipfile.ZipInfo] = {}
            for info in archive.infolist():
                normalized = _validate_zip_entry_name(info.filename)
                if _archive_entry_is_symlink(info):
                    raise ValueError("O pacote contém uma entrada simbólica não suportada.")
                entries[normalized] = info
            if sum(1 for name in entries if name == PORTABLE_PACKAGE_MANIFEST) != 1:
                raise ValueError("O pacote não contém o manifesto de exportação na raiz.")
            try:
                manifest = json.loads(
                    archive.read(PORTABLE_PACKAGE_MANIFEST).decode("utf-8")
                )
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("O manifesto do pacote é inválido.") from exc
            if not isinstance(manifest, dict):
                raise ValueError("O manifesto do pacote é inválido.")
            if manifest.get("format") != PORTABLE_PACKAGE_FORMAT:
                raise ValueError("O arquivo não é um pacote portátil do VRStudio.")
            if int(manifest.get("schema_version") or 0) != PORTABLE_PACKAGE_SCHEMA_VERSION:
                raise ValueError("Versão do manifesto de pacote não suportada.")
            package_id = str(manifest.get("package_id") or "").strip()
            if not package_id:
                raise ValueError("O manifesto do pacote não possui identificador.")
            artifacts = manifest.get("artifacts")
            if not isinstance(artifacts, list):
                raise ValueError("O manifesto do pacote não possui artefatos.")

            applications: list[dict[str, Any]] = []
            verified_paths: dict[str, str] = {}
            total_sources = 0
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    raise ValueError("O manifesto do pacote contém um artefato inválido.")
                role = str(artifact.get("role") or "")
                if role not in {"application", "dependency"}:
                    raise ValueError("O manifesto do pacote contém um papel de artefato inválido.")
                try:
                    artifact_index = int(artifact.get("artifact_index"))
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        "O manifesto do pacote contém um índice de artefato inválido."
                    ) from exc
                if artifact_index < 1:
                    raise ValueError(
                        "O manifesto do pacote contém um índice de artefato inválido."
                    )
                artifact_sha = str(artifact.get("artifact_sha256") or "")
                if not artifact_sha:
                    raise ValueError("O manifesto do pacote contém um artefato sem SHA-256.")
                _validate_zip_entry_name(
                    str(artifact.get("jar_relative_path") or ""), label="origem"
                )
                sources = artifact.get("sources")
                if not isinstance(sources, list):
                    raise ValueError("O manifesto do pacote contém uma lista de fontes inválida.")
                source_count = 0
                for source in sources:
                    if not isinstance(source, dict):
                        raise ValueError("O manifesto do pacote contém uma fonte inválida.")
                    relative = _relative_source_path(
                        str(source.get("source_relative_path") or "")
                    )
                    expected_hash = str(source.get("source_sha256") or "").strip().casefold()
                    if not _HEX64_RE.fullmatch(expected_hash):
                        raise ValueError(
                            "O manifesto do pacote contém hash inválido para: "
                            f"{relative.as_posix()}"
                        )
                    archive_entry = _validate_zip_entry_name(
                        str(source.get("archive_path") or ""), label="fonte"
                    )
                    previous_hash = verified_paths.get(archive_entry)
                    if previous_hash is not None:
                        if previous_hash != expected_hash:
                            raise ValueError(
                                "O pacote referencia a mesma fonte com conteúdos conflitantes."
                            )
                    else:
                        content = archive.read(entries[archive_entry].filename)
                        if hashlib.sha256(content).hexdigest() != expected_hash:
                            raise ValueError(
                                f"A fonte do pacote está corrompida: {archive_entry}"
                            )
                        verified_paths[archive_entry] = expected_hash
                    source_count += 1
                if int(artifact.get("source_count") or 0) != source_count:
                    raise ValueError(
                        "O manifesto do pacote contém contagens de fontes inconsistentes."
                    )
                if role == "application":
                    application_id = str(artifact.get("application_id") or "").strip()
                    version = str(artifact.get("version") or "").strip()
                    if not application_id or not version:
                        raise ValueError("O manifesto do pacote contém um aplicativo incompleto.")
                    applications.append({
                        "app_id": application_id,
                        "app_name": str(artifact.get("application_name") or application_id),
                        "version": version,
                        "variant_id": str(artifact.get("variant_id") or ""),
                        "sha256": artifact_sha,
                        "source_count": source_count,
                    })
                total_sources += source_count
            if int(manifest.get("file_count") or 0) != total_sources:
                raise ValueError(
                    "O manifesto do pacote contém um total de arquivos inconsistente."
                )
    except ValueError as exc:
        return _portable_archive_error(str(exc))
    except (OSError, zipfile.BadZipFile) as exc:
        return _portable_archive_error(str(exc) or "Falha ao ler o pacote portátil.")

    return {
        "is_valid": True,
        "portable_package": True,
        "scope": "package",
        "source_archive": str(resolved),
        "suggested_release_id": package_id,
        "suggested_name": str(manifest.get("package_name") or package_id),
        "applications": applications,
        "total_java_files": total_sources,
        "manifest": manifest,
    }


@_transaction
def _import_decompiled_package_archive(
    store: AppsCatalogStore,
    workspace: str | Path,
    source_archive: str | Path,
    *,
    release_id: str = "",
    package_name: str = "",
) -> dict[str, Any]:
    """Ingest a validated portable ZIP into a fresh catalog/workspace."""
    ws = Path(workspace).resolve()
    detection = detect_decompiled_package_archive(source_archive)
    if not detection.get("is_valid"):
        raise ValueError(detection.get("error") or "Pacote portátil inválido.")

    selected_release_id = (
        str(release_id or "").strip() or detection["suggested_release_id"]
    ).strip()
    if not selected_release_id or _safe_component(selected_release_id) != selected_release_id:
        raise ValueError("Identificador de release inválido.")
    selected_pkg_name = (
        str(package_name or "").strip()
        or str(detection.get("suggested_name") or "").strip()
        or selected_release_id
    )

    if store.get_package(selected_release_id):
        raise ValueError("Já existe um pacote com este identificador; use outro identificador.")
    decomp_root = (ws / "indice" / "codigo" / "decompilation" / selected_release_id)
    if decomp_root.resolve().exists():
        raise ValueError("O diretório de destino já existe; use outro identificador.")
    code_index = JavaCodeIndex(ws)
    code_index.initialize()
    batch_store = code_index.store
    with batch_store.connect() as conn:
        if conn.execute(
            "SELECT 1 FROM code_sources WHERE release_id = ? LIMIT 1",
            (selected_release_id,),
        ).fetchone() or conn.execute(
            "SELECT 1 FROM decompilation_plans WHERE release_id = ? LIMIT 1",
            (selected_release_id,),
        ).fetchone():
            raise ValueError("Já existem dados indexados com este identificador; use outro identificador.")

    manifest = detection["manifest"]
    artifacts = manifest["artifacts"]
    release_hash = hashlib.sha256(selected_release_id.encode("utf-8")).hexdigest()
    portable_manifest_hash = str(manifest.get("package_manifest_sha256") or "").strip()
    now = _utc_now()
    relative_root = f"indice/codigo/decompilation/{selected_release_id}"
    decomp_root.parent.mkdir(parents=True, exist_ok=True)
    staging = decomp_root.parent / f".{selected_release_id}.tmp-{uuid4().hex}"
    total_indexed = 0
    catalog_artifacts: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(detection["source_archive"]) as archive:
            entries = {
                info.filename.replace("\\", "/"): info
                for info in archive.infolist()
            }
            with batch_store.connect() as conn:
                conn.execute(
                    """INSERT INTO decompilation_plans
                       (plan_id, schema_version, release_id, release_hash, state,
                        max_classes, max_bytes, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 'completed', ?, ?, ?, ?)""",
                    (
                        selected_release_id,
                        PROCESSING_SCHEMA_VERSION,
                        selected_release_id,
                        release_hash,
                        int(manifest.get("file_count") or 0),
                        0,
                        now,
                        now,
                    ),
                )
                for artifact in artifacts:
                    artifact_index = int(artifact["artifact_index"])
                    role = str(artifact["role"])
                    artifact_sha = str(artifact["artifact_sha256"])
                    jar_path = _validate_zip_entry_name(
                        str(artifact.get("jar_relative_path") or ""), label="origem"
                    )
                    artifact_dir = f"artifacts/{artifact_index:04d}"
                    output_ref = f"{relative_root}/{artifact_dir}"
                    if role == "application":
                        catalog_artifacts.append({
                            "artifact_role": "application",
                            "application": str(
                                artifact.get("application_name")
                                or artifact.get("application_id")
                                or ""
                            ),
                            "application_key": str(artifact.get("application_id") or ""),
                            "application_name": str(artifact.get("application_name") or ""),
                            "version_detected": str(artifact.get("version") or ""),
                            "sha256": artifact_sha,
                            "size_bytes": int(artifact.get("size_bytes") or 0),
                            "relative_path": jar_path,
                            "class_count": int(artifact.get("class_count") or 0)
                                or int(artifact.get("source_count") or 0),
                            "decompiled_classes": int(artifact.get("source_count") or 0),
                        })
                    else:
                        catalog_artifacts.append({
                            "artifact_role": "library",
                            "relative_path": jar_path,
                            "sha256": artifact_sha,
                            "size_bytes": int(artifact.get("size_bytes") or 0),
                        })

                    for source in artifact["sources"]:
                        relative = _relative_source_path(
                            str(source["source_relative_path"])
                        )
                        expected_hash = str(source["source_sha256"]).strip().casefold()
                        content = _read_validated_archive_source(
                            archive,
                            entries,
                            str(source["archive_path"]),
                            expected_hash,
                        )
                        body = content.decode("utf-8")
                        target_file = _require_within(
                            staging / artifact_dir / relative,
                            staging,
                            "O pacote contém um caminho de fonte inválido.",
                        )
                        target_file.parent.mkdir(parents=True, exist_ok=True)
                        target_file.write_bytes(content)
                        file_hash = hashlib.sha256(content).hexdigest()
                        fallback_qualified = relative.as_posix().rsplit(".", 1)[0].replace("/", ".")
                        parser = (
                            parse_kotlin_source
                            if relative.suffix.casefold() == ".kt"
                            else parse_java_source
                        )
                        parsed = parser(body, fallback_qualified=fallback_qualified)
                        source_key = _code_source_key(
                            release_id=selected_release_id,
                            release_hash=release_hash,
                            artifact_sha256=artifact_sha,
                            class_version=52,
                            qualified_name=parsed.qualified_name,
                            content_hashes=[file_hash],
                        )
                        symbols_text = " ".join(
                            dict.fromkeys(
                                [parsed.qualified_name]
                                + [str(item["simple_name"]) for item in parsed.symbols]
                                + [str(item["signature"]) for item in parsed.symbols]
                                + [str(item["target"]) for item in parsed.relations]
                            )
                        )
                        cursor = conn.execute(
                            """INSERT INTO code_sources
                               (source_key, schema_version, release_id, release_hash,
                                jar_relative_path, artifact_sha256, batch_id,
                                class_version, tool,
                                output_reference, source_relative_path, source_sha256,
                                package_name, primary_type, qualified_name,
                                logical_names_json, content_hashes_json, occurrence_count,
                                parser_kind, syntax_error_count, symbols_text, body, indexed_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                source_key,
                                CODE_INDEX_SCHEMA_VERSION,
                                selected_release_id,
                                release_hash,
                                jar_path,
                                artifact_sha,
                                f"batch-{selected_release_id}-package-{artifact_index:04d}",
                                52,
                                "decompiled_package_import",
                                output_ref,
                                relative.as_posix(),
                                file_hash,
                                parsed.package_name,
                                parsed.primary_type,
                                parsed.qualified_name,
                                json.dumps([parsed.qualified_name]),
                                json.dumps([file_hash]),
                                1,
                                parsed.parser_kind,
                                parsed.syntax_error_count,
                                symbols_text,
                                body,
                                now,
                            ),
                        )
                        source_id = cursor.lastrowid
                        conn.executemany(
                            """INSERT INTO code_symbols
                               (source_id, kind, simple_name, qualified_name, signature, visibility, line_start)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            [(source_id, item["kind"], item["simple_name"], item["qualified_name"],
                              item["signature"], item["visibility"], item["line_start"])
                             for item in parsed.symbols],
                        )
                        conn.executemany(
                            """INSERT INTO code_relations
                               (source_id, kind, target, source_symbol, confidence, line_start)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            [(source_id, item["kind"], item["target"], item.get("source_symbol", ""),
                              float(item.get("confidence", 0.0)), item["line_start"])
                             for item in parsed.relations],
                        )
                        total_indexed += 1

                synthetic_manifest = {
                    "release_id": selected_release_id,
                    "release_manifest_sha256": portable_manifest_hash or release_hash,
                    "source_dir": relative_root,
                    "source_origin_dir": relative_root,
                    "analysis_scope": "package",
                    "artifacts": catalog_artifacts,
                    "indexed_at": now,
                }
                registered_pkg = store.register_package(
                    synthetic_manifest,
                    package_id=selected_release_id,
                    package_name=selected_pkg_name,
                    source_path=relative_root,
                )
                for artifact in catalog_artifacts:
                    if artifact.get("artifact_role") != "application":
                        continue
                    source_total = int(artifact.get("decompiled_classes") or 0)
                    store.update_variant_state(
                        str(artifact["application_key"]),
                        str(artifact["version_detected"]),
                        str(artifact["sha256"]),
                        "ready",
                        decompilation_state="ready",
                        class_count=int(artifact.get("class_count") or 0) or source_total,
                        indexed_classes=source_total,
                        decompiled_classes=source_total,
                    )
                conn.commit()
        staging.replace(decomp_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if decomp_root.is_dir():
            shutil.rmtree(decomp_root, ignore_errors=True)
        raise

    return {
        "success": True,
        "release_id": selected_release_id,
        "package_name": selected_pkg_name,
        "imported_applications": sum(
            1 for artifact in artifacts if str(artifact.get("role")) == "application"
        ),
        "total_indexed_sources": total_indexed,
        "package": registered_pkg,
    }


def import_decompiled_package_archive(
    workspace: str | Path,
    source_archive: str | Path,
    *,
    release_id: str = "",
    package_name: str = "",
    apps_store: AppsCatalogStore | None = None,
) -> dict[str, Any]:
    store = apps_store or AppsCatalogStore(root=workspace)
    return _import_decompiled_package_archive(
        store, workspace, source_archive, release_id=release_id, package_name=package_name
    )

