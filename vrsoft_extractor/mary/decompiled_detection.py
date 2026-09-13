"""Detection and direct ingestion of already-decompiled Java sources.

Supports migrating decompiled applications (e.g. VRMaster, VRAdm) or full packages
from Machine 1 to Machine 2 without requiring JVM decompiler toolchains.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .apps_catalog import AppsCatalogStore, UNIDENTIFIED_VERSION, _transaction
from .code_index import (
    CODE_INDEX_SCHEMA_VERSION,
    JavaCodeIndex,
    _code_source_key,
    parse_java_source,
    parse_kotlin_source,
)
from .erp_releases import parse_java_properties, _safe_component
from .jvm_batches import PROCESSING_SCHEMA_VERSION


_PROPERTIES_VERSION_KEYS = ("versao.major", "versao.minor", "versao.release")
_JAVA_EXTENSIONS = {".java", ".kt"}


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
