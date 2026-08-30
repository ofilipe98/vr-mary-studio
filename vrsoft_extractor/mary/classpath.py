"""Release-scoped classpath analysis and explicit runtime resolution policies."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import warnings
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, Sequence
from urllib.parse import unquote, urlparse
from uuid import uuid4

from .erp_releases import (
    ErpReleaseCatalog,
    ErpReleaseError,
    normalize_class_entry,
    validate_release_id,
)


CLASSPATH_ANALYSIS_SCHEMA_VERSION = 2
CLASSPATH_POLICY_SCHEMA_VERSION = 1
RUNTIME_ENTRY_SELECTION = "last_central_directory_entry"


class ClasspathError(RuntimeError):
    """Controlled failure while analyzing or configuring classpath resolution."""


class ClasspathStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.code_index = self.root / "indice" / "codigo"
        self.database_path = self.code_index / "classpath.sqlite"

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.code_index.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS artifact_classpath_analysis (
                    artifact_sha256 TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL,
                    analyzed_at TEXT NOT NULL,
                    class_entry_count INTEGER NOT NULL,
                    unique_class_count INTEGER NOT NULL,
                    duplicate_class_count INTEGER NOT NULL,
                    physical_alias_count INTEGER NOT NULL,
                    multiple_header_count INTEGER NOT NULL,
                    conflicting_class_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifact_effective_classes (
                    artifact_sha256 TEXT NOT NULL,
                    logical_name TEXT NOT NULL,
                    class_version INTEGER NOT NULL,
                    central_entry_count INTEGER NOT NULL,
                    physical_entry_count INTEGER NOT NULL,
                    variant_count INTEGER NOT NULL,
                    effective_entry_index INTEGER NOT NULL,
                    effective_crc INTEGER NOT NULL,
                    effective_size INTEGER NOT NULL,
                    effective_content_sha256 TEXT NOT NULL,
                    PRIMARY KEY (artifact_sha256, logical_name, class_version)
                );
                CREATE INDEX IF NOT EXISTS idx_effective_class_name
                    ON artifact_effective_classes(logical_name, class_version);
                """
            )
            connection.commit()
            yield connection
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def artifact_is_current(self, artifact_sha256: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT schema_version FROM artifact_classpath_analysis
                   WHERE artifact_sha256 = ?""",
                (artifact_sha256,),
            ).fetchone()
        return bool(
            row
            and int(row["schema_version"]) == CLASSPATH_ANALYSIS_SCHEMA_VERSION
        )

    def replace_artifact(
        self,
        artifact_sha256: str,
        summary: dict[str, int],
        rows: Sequence[tuple[Any, ...]],
    ) -> None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM artifact_effective_classes WHERE artifact_sha256 = ?",
                (artifact_sha256,),
            )
            connection.executemany(
                """INSERT INTO artifact_effective_classes
                   (artifact_sha256, logical_name, class_version,
                    central_entry_count, physical_entry_count, variant_count,
                    effective_entry_index, effective_crc, effective_size,
                    effective_content_sha256)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            connection.execute(
                """INSERT INTO artifact_classpath_analysis
                   (artifact_sha256, schema_version, analyzed_at,
                    class_entry_count, unique_class_count, duplicate_class_count,
                    physical_alias_count, multiple_header_count,
                    conflicting_class_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(artifact_sha256) DO UPDATE SET
                     schema_version=excluded.schema_version,
                     analyzed_at=excluded.analyzed_at,
                     class_entry_count=excluded.class_entry_count,
                     unique_class_count=excluded.unique_class_count,
                     duplicate_class_count=excluded.duplicate_class_count,
                     physical_alias_count=excluded.physical_alias_count,
                     multiple_header_count=excluded.multiple_header_count,
                     conflicting_class_count=excluded.conflicting_class_count""",
                (
                    artifact_sha256,
                    CLASSPATH_ANALYSIS_SCHEMA_VERSION,
                    _utc_now(),
                    summary["class_entry_count"],
                    summary["unique_class_count"],
                    summary["duplicate_class_count"],
                    summary["physical_alias_count"],
                    summary["multiple_header_count"],
                    summary["conflicting_class_count"],
                ),
            )
            connection.commit()

    def artifact_summary(self, artifact_sha256: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT * FROM artifact_classpath_analysis
                   WHERE artifact_sha256 = ?""",
                (artifact_sha256,),
            ).fetchone()
        return dict(row) if row else {}


class ClasspathAnalyzer:
    def __init__(
        self,
        root: str | Path,
        *,
        catalog: ErpReleaseCatalog | None = None,
        store: ClasspathStore | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.catalog = catalog or ErpReleaseCatalog(self.root)
        self.store = store or ClasspathStore(self.root)

    def analyze(
        self,
        release_id: str,
        relative_jars: Iterable[str] = (),
    ) -> dict[str, Any]:
        release_id = validate_release_id(release_id)
        manifest = self.catalog.load_manifest(release_id)
        status = self.catalog.status(release_id)
        if status.get("freshness") != "fresh":
            raise ClasspathError("A release mudou; reimporte-a antes da análise.")
        source = self._source_path(manifest)
        artifacts = {
            str(item.get("relative_path") or ""): item
            for item in manifest.get("artifacts", [])
            if isinstance(item, dict) and item.get("relative_path")
        }
        requested = tuple(
            dict.fromkeys(str(item).replace("\\", "/") for item in relative_jars)
        )
        selected = requested or tuple(sorted(artifacts, key=str.casefold))
        missing = [item for item in selected if item not in artifacts]
        if missing:
            raise ClasspathError("JARs ausentes do manifesto: " + ", ".join(missing))

        per_jar: list[dict[str, Any]] = []
        analyzed = 0
        reused = 0
        errors: list[dict[str, str]] = []
        for relative_path in selected:
            artifact = artifacts[relative_path]
            artifact_sha256 = str(artifact.get("sha256") or "")
            if self.store.artifact_is_current(artifact_sha256):
                reused += 1
            else:
                try:
                    self._analyze_artifact(
                        source / PurePosixPath(relative_path), artifact_sha256
                    )
                except (OSError, RuntimeError, zipfile.BadZipFile, KeyError) as exc:
                    errors.append(
                        {"jar": relative_path, "error": f"{type(exc).__name__}: {exc}"}
                    )
                    continue
                analyzed += 1
            summary = self.store.artifact_summary(artifact_sha256)
            per_jar.append(
                {
                    "jar": relative_path,
                    "artifact_sha256": artifact_sha256,
                    **{
                        key: summary.get(key, 0)
                        for key in (
                            "class_entry_count",
                            "unique_class_count",
                            "duplicate_class_count",
                            "physical_alias_count",
                            "multiple_header_count",
                            "conflicting_class_count",
                        )
                    },
                }
            )

        cross = self._cross_jar_status(artifacts, selected)
        report = {
            "schema_version": CLASSPATH_ANALYSIS_SCHEMA_VERSION,
            "release_id": release_id,
            "release_manifest_sha256": manifest.get("release_manifest_sha256", ""),
            "analyzed_at": _utc_now(),
            "runtime_entry_selection": RUNTIME_ENTRY_SELECTION,
            "runtime_probe": "scripts/JarEntryProbe.java",
            "selected_jar_count": len(selected),
            "analyzed_artifact_count": analyzed,
            "reused_artifact_count": reused,
            "internal_duplicate_class_count": sum(
                int(item["duplicate_class_count"]) for item in per_jar
            ),
            "internal_conflicting_class_count": sum(
                int(item["conflicting_class_count"]) for item in per_jar
            ),
            **cross,
            "manifest_profiles": _manifest_profiles(manifest, set(artifacts)),
            "errors": errors,
            "per_jar": per_jar,
        }
        _atomic_json(self._analysis_path(release_id), report)
        return report

    def load(self, release_id: str) -> dict[str, Any]:
        release_id = validate_release_id(release_id)
        path = self._analysis_path(release_id)
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ClasspathError("Relatório de classpath inválido.") from exc
        manifest = self.catalog.load_manifest(release_id)
        if payload.get("release_manifest_sha256") != manifest.get(
            "release_manifest_sha256"
        ):
            return {}
        return payload

    def _analysis_path(self, release_id: str) -> Path:
        return self.catalog.paths.index_for(release_id) / "classpath-analysis.json"

    def _source_path(self, manifest: dict[str, Any]) -> Path:
        value = Path(str(manifest.get("source_dir") or ""))
        return (value if value.is_absolute() else self.root / value).resolve()

    def _analyze_artifact(self, jar_path: Path, artifact_sha256: str) -> None:
        groups: dict[tuple[str, int], list[tuple[int, zipfile.ZipInfo]]] = {}
        with zipfile.ZipFile(jar_path) as archive:
            for entry_index, info in enumerate(archive.infolist()):
                normalized = normalize_class_entry(info.filename)
                if normalized is None or info.is_dir():
                    continue
                groups.setdefault(normalized, []).append((entry_index, info))

            rows: list[tuple[Any, ...]] = []
            class_entries = 0
            duplicate_classes = 0
            physical_aliases = 0
            multiple_headers = 0
            conflicting_classes = 0
            for (logical_name, class_version), entries in groups.items():
                class_entries += len(entries)
                duplicate_classes += int(len(entries) > 1)
                headers = {int(info.header_offset) for _, info in entries}
                physical_aliases += int(len(entries) > 1 and len(headers) == 1)
                multiple_headers += int(len(headers) > 1)

                by_header: dict[int, tuple[int, zipfile.ZipInfo]] = {}
                for entry in entries:
                    by_header[int(entry[1].header_offset)] = entry
                physical = list(by_header.values())
                variant_hashes: set[str] = set()
                if len(physical) > 1:
                    for _, info in physical:
                        variant_hashes.add(_zip_entry_sha256(archive, info))
                else:
                    variant_hashes.add(_zip_entry_sha256(archive, entries[-1][1]))
                conflicting_classes += int(len(variant_hashes) > 1)

                effective_index, effective = entries[-1]
                effective_hash = _zip_entry_sha256(archive, effective)
                rows.append(
                    (
                        artifact_sha256,
                        logical_name,
                        class_version,
                        len(entries),
                        len(headers),
                        len(variant_hashes),
                        effective_index,
                        int(effective.CRC),
                        int(effective.file_size),
                        effective_hash,
                    )
                )

        self.store.replace_artifact(
            artifact_sha256,
            {
                "class_entry_count": class_entries,
                "unique_class_count": len(groups),
                "duplicate_class_count": duplicate_classes,
                "physical_alias_count": physical_aliases,
                "multiple_header_count": multiple_headers,
                "conflicting_class_count": conflicting_classes,
            },
            rows,
        )

    def _cross_jar_status(
        self,
        artifacts: dict[str, dict[str, Any]],
        selected: Sequence[str],
    ) -> dict[str, Any]:
        hashes = [str(artifacts[item].get("sha256") or "") for item in selected]
        if not hashes:
            return {
                "cross_jar_duplicate_class_count": 0,
                "cross_jar_conflicting_class_count": 0,
                "cross_jar_conflict_samples": [],
            }
        placeholders = ",".join("?" for _ in hashes)
        with self.store.connect() as connection:
            rows = connection.execute(
                f"""SELECT logical_name, class_version,
                            count(DISTINCT artifact_sha256) AS owners,
                            count(DISTINCT effective_content_sha256) AS variants
                     FROM artifact_effective_classes
                     WHERE artifact_sha256 IN ({placeholders})
                     GROUP BY logical_name, class_version
                     HAVING owners > 1""",
                hashes,
            ).fetchall()
            samples = connection.execute(
                f"""SELECT logical_name, class_version,
                            count(DISTINCT artifact_sha256) AS owners,
                            count(DISTINCT effective_content_sha256) AS variants
                     FROM artifact_effective_classes
                     WHERE artifact_sha256 IN ({placeholders})
                     GROUP BY logical_name, class_version
                     HAVING variants > 1
                     ORDER BY logical_name COLLATE NOCASE, class_version
                     LIMIT 200""",
                hashes,
            ).fetchall()
        return {
            "cross_jar_duplicate_class_count": len(rows),
            "cross_jar_conflicting_class_count": sum(
                1 for row in rows if int(row["variants"]) > 1
            ),
            "cross_jar_conflict_samples": [dict(row) for row in samples],
        }


class ClasspathPolicyStore:
    def __init__(
        self,
        root: str | Path,
        *,
        catalog: ErpReleaseCatalog | None = None,
        analyzer: ClasspathAnalyzer | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.catalog = catalog or ErpReleaseCatalog(self.root)
        self.analyzer = analyzer or ClasspathAnalyzer(self.root, catalog=self.catalog)

    def status(self, release_id: str, profile_id: str = "") -> dict[str, Any]:
        release_id = validate_release_id(release_id)
        manifest = self.catalog.load_manifest(release_id)
        analysis = self.analyzer.load(release_id)
        policy = self._load_policy(release_id, manifest)
        profiles = list(policy.get("profiles") or [])
        has_manifest_declarations = bool(manifest.get("classpath_declarations"))
        selected = next(
            (item for item in profiles if item.get("profile_id") == profile_id),
            None,
        ) if profile_id else None
        selected_ready = bool(
            selected
            and selected.get("complete")
            and self._profile_analysis_ready(
                manifest, selected.get("ordered_jars") or []
            )
        )
        return {
            "schema_version": CLASSPATH_POLICY_SCHEMA_VERSION,
            "release_id": release_id,
            "release_manifest_sha256": manifest.get("release_manifest_sha256", ""),
            "analysis_available": bool(analysis),
            "analysis": {
                key: analysis.get(key)
                for key in (
                    "analyzed_at",
                    "selected_jar_count",
                    "internal_duplicate_class_count",
                    "internal_conflicting_class_count",
                    "cross_jar_duplicate_class_count",
                    "cross_jar_conflicting_class_count",
                )
                if analysis
            },
            "runtime_entry_selection": RUNTIME_ENTRY_SELECTION,
            "configured_profile_count": len(profiles),
            "profiles": profiles,
            "selected_profile": selected,
            "manifest_profiles": analysis.get("manifest_profiles", []) if analysis else [],
            "classpath_order_known": selected_ready,
            "classpath_status": (
                "resolved"
                if selected_ready
                else "partial"
                if analysis or profiles or has_manifest_declarations
                else "unknown"
            ),
        }

    def set_profile(
        self,
        release_id: str,
        profile_id: str,
        ordered_jars: Iterable[str],
        *,
        complete: bool = False,
        approved: bool = False,
    ) -> dict[str, Any]:
        if not approved:
            raise ClasspathError("A configuração do classpath exige aprovação explícita.")
        release_id = validate_release_id(release_id)
        normalized_profile = str(profile_id or "").strip()
        if not normalized_profile or len(normalized_profile) > 100:
            raise ClasspathError("Informe um identificador de perfil válido.")
        manifest = self.catalog.load_manifest(release_id)
        if self.catalog.status(release_id).get("freshness") != "fresh":
            raise ClasspathError("A release mudou; reimporte-a antes de configurar.")
        available = {
            str(item.get("relative_path") or "")
            for item in manifest.get("artifacts", [])
            if isinstance(item, dict) and item.get("relative_path")
        }
        order = list(dict.fromkeys(str(item).replace("\\", "/") for item in ordered_jars))
        if not order:
            raise ClasspathError("Informe ao menos um JAR na ordem do perfil.")
        missing = [item for item in order if item not in available]
        if missing:
            raise ClasspathError("JARs ausentes do manifesto: " + ", ".join(missing))
        if complete and not self._profile_analysis_ready(manifest, order):
            raise ClasspathError(
                "Analise todos os JARs do perfil antes de marcá-lo como completo."
            )

        policy = self._load_policy(release_id, manifest)
        profiles = [
            item
            for item in policy.get("profiles") or []
            if item.get("profile_id") != normalized_profile
        ]
        profiles.append(
            {
                "profile_id": normalized_profile,
                "ordered_jars": order,
                "complete": bool(complete),
                "source": "manual",
                "updated_at": _utc_now(),
            }
        )
        policy.update(
            {
                "schema_version": CLASSPATH_POLICY_SCHEMA_VERSION,
                "release_id": release_id,
                "release_manifest_sha256": manifest.get(
                    "release_manifest_sha256", ""
                ),
                "updated_at": _utc_now(),
                "profiles": sorted(profiles, key=lambda item: item["profile_id"].casefold()),
            }
        )
        _atomic_json(self._policy_path(release_id), policy)
        return self.status(release_id, normalized_profile)

    def profile_order(self, release_id: str, profile_id: str) -> list[str]:
        if not profile_id:
            return []
        status = self.status(release_id, profile_id)
        if not status.get("classpath_order_known"):
            return []
        selected = status.get("selected_profile") or {}
        return list(selected.get("ordered_jars") or [])

    def _policy_path(self, release_id: str) -> Path:
        return self.catalog.paths.index_for(release_id) / "classpath-policy.json"

    def _load_policy(
        self, release_id: str, manifest: dict[str, Any]
    ) -> dict[str, Any]:
        path = self._policy_path(release_id)
        if not path.is_file():
            return {"profiles": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ClasspathError("Política de classpath inválida.") from exc
        if payload.get("release_manifest_sha256") != manifest.get(
            "release_manifest_sha256"
        ):
            return {"profiles": []}
        return payload

    def _profile_analysis_ready(
        self, manifest: dict[str, Any], ordered_jars: Iterable[str]
    ) -> bool:
        artifacts = {
            str(item.get("relative_path") or ""): str(item.get("sha256") or "")
            for item in manifest.get("artifacts", [])
            if isinstance(item, dict) and item.get("relative_path")
        }
        hashes = [artifacts.get(str(jar), "") for jar in ordered_jars]
        return bool(hashes) and all(
            artifact_sha256
            and self.analyzer.store.artifact_is_current(artifact_sha256)
            for artifact_sha256 in hashes
        )


class ClasspathResolver:
    def __init__(
        self,
        root: str | Path,
        *,
        catalog: ErpReleaseCatalog | None = None,
        store: ClasspathStore | None = None,
        policies: ClasspathPolicyStore | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.catalog = catalog or ErpReleaseCatalog(self.root)
        self.store = store or ClasspathStore(self.root)
        self.policies = policies or ClasspathPolicyStore(
            self.root, catalog=self.catalog
        )

    def annotate(self, item: dict[str, Any], profile_id: str = "") -> dict[str, Any]:
        release_id = str(item.get("release_id") or "")
        manifest = self.catalog.load_manifest(release_id)
        artifact_paths: dict[str, list[str]] = {}
        for value in manifest.get("artifacts", []):
            if not isinstance(value, dict):
                continue
            artifact_sha256 = str(value.get("sha256") or "")
            relative_path = str(value.get("relative_path") or "")
            if artifact_sha256 and relative_path:
                artifact_paths.setdefault(artifact_sha256, []).append(relative_path)
        logical_names = _json_strings(item.get("logical_names_json"))
        source_hashes = set(_json_strings(item.get("content_hashes_json")))
        if not logical_names:
            logical_names = [str(item.get("qualified_name") or "")]
        candidates = self._candidates(
            artifact_paths,
            logical_names,
            int(item.get("class_version") or 0),
        )
        if not candidates:
            item["classpath_resolution"] = "unknown"
            item["classpath_selected"] = None
            item["classpath_profile"] = profile_id
            item["classpath_candidates"] = []
            item["classpath_warning"] = (
                "A análise de classpath ainda não cobre esta classe/release."
            )
            return item

        order = self.policies.profile_order(release_id, profile_id)
        rank = {jar: index for index, jar in enumerate(order)}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for candidate in candidates:
            grouped.setdefault(candidate["logical_name"], []).append(candidate)

        ambiguous = False
        shadowed = False
        selected_hashes: set[str] = set()
        selected_jars: set[str] = set()
        internal_resolution = False
        for values in grouped.values():
            effective_hashes = {value["effective_content_sha256"] for value in values}
            internal_resolution |= any(int(value["variant_count"]) > 1 for value in values)
            if len(effective_hashes) == 1:
                selected = values[0]
            elif order:
                ordered = [value for value in values if value["jar_relative_path"] in rank]
                if not ordered:
                    ambiguous = True
                    continue
                selected = min(ordered, key=lambda value: rank[value["jar_relative_path"]])
            else:
                ambiguous = True
                continue
            selected_hashes.add(str(selected["effective_content_sha256"]))
            selected_jars.add(str(selected["jar_relative_path"]))

        current_jar = str(item.get("jar_relative_path") or "")
        if selected_hashes and not source_hashes.intersection(selected_hashes):
            shadowed = True
        if selected_jars and current_jar not in selected_jars:
            shadowed = True

        if ambiguous:
            resolution = "ambiguous"
            selected_flag: bool | None = None
            warning = (
                "Há bytecodes divergentes e nenhuma ordem de classpath completa "
                "foi selecionada para esta consulta."
            )
        elif shadowed:
            resolution = "shadowed"
            selected_flag = False
            warning = (
                "Este fonte é uma variante sombreada pela seleção efetiva do runtime."
            )
        elif order or internal_resolution:
            resolution = "resolved"
            selected_flag = True
            warning = ""
        else:
            resolution = "unique"
            selected_flag = True
            warning = ""

        item["classpath_resolution"] = resolution
        item["classpath_selected"] = selected_flag
        item["classpath_profile"] = profile_id
        item["classpath_candidates"] = candidates[:50]
        item["classpath_warning"] = warning
        return item

    def _candidates(
        self,
        artifact_paths: dict[str, list[str]],
        logical_names: Sequence[str],
        class_version: int,
    ) -> list[dict[str, Any]]:
        if not artifact_paths or not logical_names:
            return []
        artifact_hashes = list(artifact_paths)
        artifact_placeholders = ",".join("?" for _ in artifact_hashes)
        name_placeholders = ",".join("?" for _ in logical_names)
        with self.store.connect() as connection:
            rows = connection.execute(
                f"""SELECT * FROM artifact_effective_classes
                     WHERE artifact_sha256 IN ({artifact_placeholders})
                       AND logical_name IN ({name_placeholders})
                       AND class_version = ?
                     ORDER BY logical_name COLLATE NOCASE, artifact_sha256""",
                [*artifact_hashes, *logical_names, class_version],
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            artifact_sha256 = str(row["artifact_sha256"])
            for relative_path in artifact_paths.get(artifact_sha256, []):
                results.append(
                    {
                        "logical_name": str(row["logical_name"]),
                        "class_version": int(row["class_version"]),
                        "jar_relative_path": relative_path,
                        "artifact_sha256": artifact_sha256,
                        "effective_content_sha256": str(
                            row["effective_content_sha256"]
                        ),
                        "effective_entry_index": int(row["effective_entry_index"]),
                        "central_entry_count": int(row["central_entry_count"]),
                        "physical_entry_count": int(row["physical_entry_count"]),
                        "variant_count": int(row["variant_count"]),
                        "selection": RUNTIME_ENTRY_SELECTION,
                    }
                )
        return results


def _manifest_profiles(
    manifest: dict[str, Any], available: set[str]
) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for declaration in manifest.get("classpath_declarations") or []:
        if not isinstance(declaration, dict):
            continue
        jar = str(declaration.get("jar") or "")
        resolved: list[str] = []
        unresolved: list[str] = []
        for raw_entry in declaration.get("entries") or []:
            entry = str(raw_entry or "")
            parsed = urlparse(entry)
            if parsed.scheme not in {"", "file"} or parsed.netloc:
                unresolved.append(entry)
                continue
            relative = unquote(parsed.path or entry).replace("\\", "/")
            candidate = (PurePosixPath(jar).parent / relative).as_posix()
            while candidate.startswith("./"):
                candidate = candidate[2:]
            if candidate in available:
                resolved.append(candidate)
            else:
                unresolved.append(entry)
        profiles.append(
            {
                "profile_id": jar,
                "source": "manifest_class_path",
                "ordered_jars": list(dict.fromkeys([jar, *resolved])),
                "unresolved_entries": unresolved,
                "complete": False,
                "warning": (
                    "Declaração do manifesto é candidata; argumentos do launcher "
                    "e a ordem efetiva ainda não foram confirmados."
                ),
            }
        )
    return profiles


def _zip_entry_sha256(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=r"Overlapped entries: .*possible zip bomb.*", category=UserWarning
        )
        with archive.open(info) as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def _json_strings(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    try:
        payload = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in payload if str(item)] if isinstance(payload, list) else []


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
