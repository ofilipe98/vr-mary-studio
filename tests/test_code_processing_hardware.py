from vrsoft_extractor.mary.code_processing_hardware import (
    detect_code_processing_hardware,
)
from vrsoft_extractor.mary.cli import (
    CODE_PROCESSING_HARDWARE,
    _parallel_processing_args,
    build_parser,
)


def test_midrange_hardware_uses_memory_safe_parallelism() -> None:
    profile = detect_code_processing_hardware(
        logical_cpu_count=16,
        total_memory_mb=16 * 1024,
        available_memory_mb=6 * 1024,
    )

    assert profile.recommended_cpu_cores == 8
    assert profile.recommended_heap_mb == 2048
    assert profile.recommended_parallel_workers == 4
    assert profile.cpu_options == (1, 2, 4, 8, 16)
    assert profile.parallel_workers_for(16, 4096) == 2


def test_small_hardware_keeps_one_safe_worker() -> None:
    profile = detect_code_processing_hardware(
        logical_cpu_count=2,
        total_memory_mb=4 * 1024,
        available_memory_mb=2 * 1024,
    )

    assert profile.recommended_cpu_cores == 2
    assert profile.recommended_heap_mb == 1024
    assert profile.recommended_parallel_workers == 1
    assert profile.cpu_options == (1, 2)


def test_large_hardware_caps_java_processes_but_exposes_cpu_capacity() -> None:
    profile = detect_code_processing_hardware(
        logical_cpu_count=32,
        total_memory_mb=64 * 1024,
        available_memory_mb=48 * 1024,
    )

    assert profile.recommended_cpu_cores == 16
    assert profile.recommended_heap_mb == 4096
    assert profile.recommended_parallel_workers == 8
    assert profile.cpu_options == (1, 2, 4, 8, 16, 32)


def test_cli_uses_detected_defaults_for_both_processing_commands() -> None:
    parser = build_parser()

    for command in ("run-erp-decompilation", "advance-erp-code-coverage"):
        args = parser.parse_args([command, "plan-or-release"])
        workers, limit, priority = _parallel_processing_args(args)

        assert args.cpu_cores == CODE_PROCESSING_HARDWARE.recommended_cpu_cores
        assert args.heap_mb == CODE_PROCESSING_HARDWARE.recommended_heap_mb
        assert workers == CODE_PROCESSING_HARDWARE.recommended_parallel_workers
        assert limit == workers
        assert priority == ("normal" if workers > 1 else "low")


def test_cli_manual_limits_override_auto_profile() -> None:
    args = build_parser().parse_args(
        [
            "run-erp-decompilation",
            "plan",
            "--cpu-cores",
            "1",
            "--parallel-workers",
            "1",
            "--limit",
            "3",
            "--priority",
            "low",
        ]
    )

    assert _parallel_processing_args(args) == (1, 3, "low")
