"""Hardware-aware defaults for local ERP code indexing."""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class CodeProcessingHardwareProfile:
    logical_cpu_count: int
    total_memory_mb: int
    available_memory_mb: int
    recommended_cpu_cores: int
    recommended_heap_mb: int
    recommended_parallel_workers: int
    cpu_options: tuple[int, ...]

    def parallel_workers_for(self, cpu_cores: int, heap_mb: int) -> int:
        cpu_workers = max(1, min(int(cpu_cores), self.logical_cpu_count) // 2)
        if self.total_memory_mb <= 0:
            return min(cpu_workers, 8)
        reserve_mb = max(2048, self.total_memory_mb // 4)
        usable_mb = max(int(heap_mb) + 512, self.total_memory_mb - reserve_mb)
        memory_workers = max(1, usable_mb // (max(512, int(heap_mb)) + 512))
        return max(1, min(cpu_workers, memory_workers, 8))

    @property
    def summary(self) -> str:
        memory = (
            f"{self.total_memory_mb / 1024:.1f} GB RAM"
            if self.total_memory_mb > 0
            else "RAM não detectada"
        )
        return (
            f"Hardware detectado: {self.logical_cpu_count} processadores lógicos, "
            f"{memory} · recomendado: {self.recommended_cpu_cores} CPUs e "
            f"{self.recommended_parallel_workers} processos Java paralelos."
        )


def detect_code_processing_hardware(
    *,
    logical_cpu_count: int | None = None,
    total_memory_mb: int | None = None,
    available_memory_mb: int | None = None,
) -> CodeProcessingHardwareProfile:
    logical = max(1, int(logical_cpu_count or _logical_cpu_count()))
    detected_total, detected_available = _memory_mb()
    total = max(0, int(detected_total if total_memory_mb is None else total_memory_mb))
    available = max(
        0,
        int(
            detected_available
            if available_memory_mb is None
            else available_memory_mb
        ),
    )
    heap_mb = 1024 if 0 < total < 8192 else 4096 if total >= 32768 else 2048
    cpu_target = max(1, logical - (2 if logical >= 8 else 1 if logical >= 4 else 0))

    provisional = CodeProcessingHardwareProfile(
        logical_cpu_count=logical,
        total_memory_mb=total,
        available_memory_mb=available,
        recommended_cpu_cores=1,
        recommended_heap_mb=heap_mb,
        recommended_parallel_workers=1,
        cpu_options=(),
    )
    workers = provisional.parallel_workers_for(cpu_target, heap_mb)
    recommended_cpu = min(logical, max(1, workers * 2))
    options = _cpu_options(logical, recommended_cpu)
    return CodeProcessingHardwareProfile(
        logical_cpu_count=logical,
        total_memory_mb=total,
        available_memory_mb=available,
        recommended_cpu_cores=recommended_cpu,
        recommended_heap_mb=heap_mb,
        recommended_parallel_workers=workers,
        cpu_options=options,
    )


def _logical_cpu_count() -> int:
    process_cpu_count = getattr(os, "process_cpu_count", None)
    if callable(process_cpu_count):
        detected = process_cpu_count()
        if detected:
            return int(detected)
    get_affinity = getattr(os, "sched_getaffinity", None)
    if callable(get_affinity):
        try:
            return max(1, len(get_affinity(0)))
        except OSError:
            pass
    return max(1, int(os.cpu_count() or 1))


def _cpu_options(logical: int, recommended: int) -> tuple[int, ...]:
    values = {1, logical, recommended}
    value = 2
    while value <= logical:
        values.add(value)
        value *= 2
    return tuple(sorted(item for item in values if 1 <= item <= logical))


def _memory_mb() -> tuple[int, int]:
    if os.name == "nt":
        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.length = ctypes.sizeof(status)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                divisor = 1024 * 1024
                return (
                    int(status.total_physical // divisor),
                    int(status.available_physical // divisor),
                )
        except (AttributeError, OSError):
            pass
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        total_pages = int(os.sysconf("SC_PHYS_PAGES"))
        available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
        divisor = 1024 * 1024
        return (
            page_size * total_pages // divisor,
            page_size * available_pages // divisor,
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return 0, 0
