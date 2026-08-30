import hashlib
import warnings
import zipfile
from pathlib import Path

import pytest

from vrsoft_extractor.mary.classpath import (
    ClasspathAnalyzer,
    ClasspathError,
    ClasspathPolicyStore,
    ClasspathResolver,
    ClasspathStore,
)
from vrsoft_extractor.mary.erp_releases import ErpReleaseCatalog


def _jar(path: Path, versions: tuple[bytes, ...], *, class_path: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = "Manifest-Version: 1.0\r\nMain-Class: br.vr.App\r\n"
    if class_path:
        manifest += f"Class-Path: {class_path}\r\n"
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name:.*")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("META-INF/MANIFEST.MF", manifest + "\r\n")
            for bytecode in versions:
                archive.writestr("br/vr/App.class", bytecode)


def _project(tmp_path: Path) -> tuple[ErpReleaseCatalog, dict[str, str]]:
    source = tmp_path / "ERP" / "releases" / "r1" / "jars"
    _jar(source / "A.jar", (b"version-a1", b"version-a2"), class_path="B.jar")
    _jar(source / "B.jar", (b"version-b",))
    catalog = ErpReleaseCatalog(tmp_path, expected_jar_count=2)
    catalog.import_release("r1")
    return catalog, {
        "a1": hashlib.sha256(b"version-a1").hexdigest(),
        "a2": hashlib.sha256(b"version-a2").hexdigest(),
        "b": hashlib.sha256(b"version-b").hexdigest(),
    }


def test_analyzer_persists_java_effective_entry_and_cross_jar_conflicts(
    tmp_path: Path,
) -> None:
    catalog, hashes = _project(tmp_path)
    store = ClasspathStore(tmp_path)

    report = ClasspathAnalyzer(tmp_path, catalog=catalog, store=store).analyze("r1")

    assert report["runtime_entry_selection"] == "last_central_directory_entry"
    assert report["internal_duplicate_class_count"] == 1
    assert report["internal_conflicting_class_count"] == 1
    assert report["cross_jar_duplicate_class_count"] == 1
    assert report["cross_jar_conflicting_class_count"] == 1
    assert report["manifest_profiles"][0]["ordered_jars"] == ["A.jar", "B.jar"]
    assert report["manifest_profiles"][0]["complete"] is False

    manifest = catalog.load_manifest("r1")
    artifact = next(item for item in manifest["artifacts"] if item["relative_path"] == "A.jar")
    with store.connect() as connection:
        selected = connection.execute(
            """SELECT * FROM artifact_effective_classes
               WHERE artifact_sha256 = ? AND logical_name = 'br.vr.App'""",
            (artifact["sha256"],),
        ).fetchone()
    assert selected["central_entry_count"] == 2
    assert selected["physical_entry_count"] == 2
    assert selected["variant_count"] == 2
    assert selected["effective_entry_index"] == 2
    assert selected["effective_content_sha256"] == hashes["a2"]

    cached = ClasspathAnalyzer(tmp_path, catalog=catalog, store=store).analyze("r1")
    assert cached["analyzed_artifact_count"] == 0
    assert cached["reused_artifact_count"] == 2


def test_policy_requires_approval_and_resolver_never_hides_ambiguity(
    tmp_path: Path,
) -> None:
    catalog, hashes = _project(tmp_path)
    unready = ClasspathPolicyStore(tmp_path, catalog=catalog)
    with pytest.raises(ClasspathError, match="Analise todos os JARs"):
        unready.set_profile(
            "r1",
            "app",
            ("A.jar", "B.jar"),
            complete=True,
            approved=True,
        )
    analyzer = ClasspathAnalyzer(tmp_path, catalog=catalog)
    analyzer.analyze("r1")
    policies = ClasspathPolicyStore(tmp_path, catalog=catalog, analyzer=analyzer)

    with pytest.raises(ClasspathError, match="aprovação explícita"):
        policies.set_profile("r1", "app", ("A.jar", "B.jar"), complete=True)

    base = {
        "release_id": "r1",
        "jar_relative_path": "A.jar",
        "qualified_name": "br.vr.App",
        "logical_names_json": '["br.vr.App"]',
        "content_hashes_json": f'["{hashes["a2"]}"]',
        "class_version": 0,
    }
    resolver = ClasspathResolver(tmp_path, catalog=catalog, policies=policies)
    ambiguous = resolver.annotate(dict(base))
    assert ambiguous["classpath_resolution"] == "ambiguous"
    assert ambiguous["classpath_selected"] is None
    assert "divergentes" in ambiguous["classpath_warning"]

    policies.set_profile(
        "r1",
        "partial-app",
        ("A.jar", "B.jar"),
        complete=False,
        approved=True,
    )
    still_ambiguous = resolver.annotate(dict(base), "partial-app")
    assert still_ambiguous["classpath_resolution"] == "ambiguous"

    status = policies.set_profile(
        "r1",
        "app",
        ("A.jar", "B.jar"),
        complete=True,
        approved=True,
    )
    assert status["classpath_status"] == "resolved"
    assert status["classpath_order_known"] is True

    resolved = resolver.annotate(dict(base), "app")
    assert resolved["classpath_resolution"] == "resolved"
    assert resolved["classpath_selected"] is True

    shadowed = resolver.annotate(
        {
            **base,
            "jar_relative_path": "B.jar",
            "content_hashes_json": f'["{hashes["b"]}"]',
        },
        "app",
    )
    assert shadowed["classpath_resolution"] == "shadowed"
    assert shadowed["classpath_selected"] is False
