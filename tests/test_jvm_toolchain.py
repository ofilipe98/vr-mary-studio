from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

from vrsoft_extractor.mary.jvm_toolchain import (
    CfrAdapter,
    DecompilerAdapter,
    DecompileRequest,
    JavaRuntimeResolver,
    JvmToolchain,
    ToolStatus,
    VineflowerAdapter,
    parse_java_version,
)


class _PythonProcessAdapter(DecompilerAdapter):
    name = "python-test"

    def command(self, request: DecompileRequest) -> list[str]:
        script = (
            "import pathlib,time; "
            "data=bytearray(8*1024*1024); "
            f"path=pathlib.Path({str(request.output_dir / 'Result.java')!r}); "
            "path.parent.mkdir(parents=True,exist_ok=True); "
            "path.write_text('class Result {}',encoding='utf-8'); "
            "time.sleep(0.2); print(len(data))"
        )
        return [sys.executable, "-c", script]


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


def test_toolchain_finds_portable_tools_next_to_app_directory(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "analyst-workspace"
    app_dir = tmp_path / "portable" / "App"
    tools = tmp_path / "portable" / "VRProject" / "tools" / "code-analysis"
    java = tools / "java17" / "jdk-17" / "bin" / "java.exe"
    vineflower = tools / "decompilers" / "vineflower-1.12.0.jar"
    cfr = tools / "decompilers" / "cfr-0.152.jar"
    for path in (java, vineflower, cfr):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"tool")
    available_java = ToolStatus(
        name="java",
        available=True,
        path=str(java),
        version="17-test",
        source="bundled-archive",
    )

    toolchain = JvmToolchain(workspace, {}, app_dir=app_dir)
    with patch(
        "vrsoft_extractor.mary.jvm_toolchain.inspect_java",
        return_value=available_java,
    ), patch.object(VineflowerAdapter, "expected_sha256", ""), patch.object(
        CfrAdapter, "expected_sha256", ""
    ):
        report = toolchain.doctor()

    assert report["ready"] is True
    assert report["java"]["path"] == str(java)
    assert report["vineflower"]["path"] == str(vineflower.resolve())
    assert report["cfr"]["path"] == str(cfr.resolve())


def test_toolchain_finds_tools_inside_source_checkout_vrproject(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "vr-mary-studio"
    tools = checkout / "VRProject" / "tools" / "code-analysis"
    java = tools / "java17" / "jdk-17" / "bin" / "java.exe"
    vineflower = tools / "decompilers" / "vineflower-1.12.0.jar"
    cfr = tools / "decompilers" / "cfr-0.152.jar"
    for path in (java, vineflower, cfr):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"tool")
    available_java = ToolStatus(
        name="java",
        available=True,
        path=str(java),
        version="17-test",
        source="bundled-archive",
    )

    toolchain = JvmToolchain(checkout, {}, app_dir=checkout)
    with patch(
        "vrsoft_extractor.mary.jvm_toolchain.inspect_java",
        return_value=available_java,
    ), patch.object(VineflowerAdapter, "expected_sha256", ""), patch.object(
        CfrAdapter, "expected_sha256", ""
    ):
        report = toolchain.doctor()

    assert report["ready"] is True
    assert report["java"]["path"] == str(java)
    assert report["vineflower"]["path"] == str(vineflower.resolve())
    assert report["cfr"]["path"] == str(cfr.resolve())


def test_decompiler_rejects_unapproved_binary(tmp_path: Path) -> None:
    java = ToolStatus("java", True, str(tmp_path / "java.exe"), "17.0.12")
    jar = tmp_path / "vineflower-1.12.0.jar"
    jar.write_bytes(b"unexpected")

    status = VineflowerAdapter(java, jar).status()

    assert status.available is False
    assert status.checksum_verified is False
    assert "Checksum" in status.error


def test_decompiler_records_local_process_memory_cpu_and_disk(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jar"
    input_path.write_bytes(b"input-bytecode")
    tool_path = tmp_path / "tool.jar"
    tool_path.write_bytes(b"test-tool")
    adapter = _PythonProcessAdapter(
        ToolStatus("java", True, sys.executable, "17-test"),
        tool_path,
    )

    result = adapter.decompile(
        DecompileRequest(input_path, tmp_path / "out", timeout_seconds=5)
    )

    assert result.status == "completed"
    assert result.input_bytes == len(b"input-bytecode")
    assert result.output_bytes >= len("class Result {}")
    assert result.duration_ms >= 100
    assert result.timed_out is False
    if os.name == "nt":
        assert result.metrics_available is True
        assert result.peak_rss_bytes > 0
        assert result.cpu_user_ms + result.cpu_kernel_ms >= 0
        assert result.cpu_limit_applied is True
