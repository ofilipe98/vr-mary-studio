from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from vrsoft_extractor.mary.jvm_toolchain import (
    CfrAdapter,
    DecompileRequest,
    JavaRuntimeResolver,
    JvmToolchain,
    ToolStatus,
    VineflowerAdapter,
    parse_java_version,
)


def test_parse_java_version_handles_legacy_and_modern_formats() -> None:
    assert parse_java_version('openjdk version "17.0.12" 2024-07-16') == (
        "17.0.12",
        17,
    )
    assert parse_java_version('java version "1.8.0_492"') == ("1.8.0_492", 8)
    assert parse_java_version("invalid") == ("", 0)


def test_resolver_prefers_configured_java_without_mutating_environment(
    tmp_path: Path,
) -> None:
    configured = tmp_path / "custom-jre"
    java = configured / "bin" / "java.exe"
    java.parent.mkdir(parents=True)
    java.write_bytes(b"fake")
    environ = {"VR_CODE_JAVA_HOME": str(configured), "JAVA_HOME": "keep-this"}
    expected = ToolStatus(
        name="java",
        available=True,
        path=str(java),
        version="17.0.12",
        source="configured",
    )

    with patch(
        "vrsoft_extractor.mary.jvm_toolchain.inspect_java", return_value=expected
    ) as inspect:
        resolved = JavaRuntimeResolver(tmp_path, environ).resolve()

    assert resolved == expected
    assert environ["JAVA_HOME"] == "keep-this"
    inspect.assert_called_once_with(java, source="configured")


def test_resolver_rejects_java_8_and_reports_controlled_failure(
    tmp_path: Path,
) -> None:
    java = tmp_path / "tools" / "code-analysis" / "java17" / "bin" / "java.exe"
    java.parent.mkdir(parents=True)
    java.write_bytes(b"fake")
    rejected = ToolStatus(
        name="java",
        available=False,
        path=str(java),
        version="1.8.0_492",
        error="Java 17+ necessário; encontrado 1.8.0_492.",
        source="bundled",
    )

    with patch(
        "vrsoft_extractor.mary.jvm_toolchain.inspect_java", return_value=rejected
    ):
        result = JavaRuntimeResolver(tmp_path, {}).resolve()

    assert result.available is False
    assert "Java 17+" in result.error


def test_decompiler_commands_keep_java_and_tools_isolated(tmp_path: Path) -> None:
    java = ToolStatus("java", True, str(tmp_path / "java.exe"), "17.0.12")
    request = DecompileRequest(tmp_path / "ERP.jar", tmp_path / "out")
    vineflower = VineflowerAdapter(java, tmp_path / "vineflower.jar")
    cfr = CfrAdapter(java, tmp_path / "cfr.jar")

    assert vineflower.command(request)[:4] == [
        java.path,
        "-Xmx4096m",
        "-jar",
        str((tmp_path / "vineflower.jar").resolve()),
    ]
    assert "--outputdir" in cfr.command(request)
    assert "JAVA_HOME" not in " ".join(vineflower.command(request))


def test_doctor_requires_java_and_both_pinned_decompilers(tmp_path: Path) -> None:
    report = JvmToolchain(tmp_path, {}).doctor()
    assert report["ready"] is False
    assert report["java"]["available"] is False
    assert report["vineflower"]["version"] == "1.12.0"
    assert report["cfr"]["version"] == "0.152"
    assert report["system_java_unchanged"] is True


def test_decompiler_rejects_unapproved_binary(tmp_path: Path) -> None:
    java = ToolStatus("java", True, str(tmp_path / "java.exe"), "17.0.12")
    jar = tmp_path / "vineflower-1.12.0.jar"
    jar.write_bytes(b"unexpected")

    status = VineflowerAdapter(java, jar).status()

    assert status.available is False
    assert status.checksum_verified is False
    assert "Checksum" in status.error
