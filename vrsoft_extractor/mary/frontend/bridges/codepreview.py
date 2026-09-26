from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from ...code_index import JavaCodeIndex
from ..code_links import parse_code_reference

LOGGER = logging.getLogger(__name__)


class CodePreviewDomain:
    def __init__(self, owner: Any) -> None:
        object.__setattr__(self, "_owner", owner)

    def open_decompiled_reference(self, value: str) -> None:
        owner = self._owner
        if owner._closed:
            return
        reference = parse_code_reference(value)
        if reference is None:
            return
        reference_canonical = reference.canonical
        if not isinstance(reference_canonical, str) or not reference_canonical:
            return

        with owner._decompiled_preview_threads_lock:
            owner._decompiled_preview_generation += 1
            generation = owner._decompiled_preview_generation

        workspace = owner._settings.root
        release_id = owner._code_analysis_release
        owner.decompiledSourcePreviewRequested.emit(
            {
                "state": "loading",
                "reference": reference_canonical,
                "release_id": release_id,
            }
        )
        if owner._closed:
            return

        def worker() -> None:
            current_thread = threading.current_thread()
            try:
                try:
                    index = JavaCodeIndex(workspace)
                    result = index.resolve_decompiled_reference(
                        reference_canonical,
                        release_id=release_id,
                    )
                except Exception as exc:
                    LOGGER.exception(
                        "Falha ao resolver referência de código descompilado '%s'",
                        reference_canonical,
                    )
                    result = {
                        "state": "error",
                        "reference": reference_canonical,
                        "release_id": release_id,
                        "message": f"Erro inesperado ao resolver referência: {exc}",
                    }
                if not owner._closed:
                    owner._decompiledSourceResolved.emit(
                        (generation, workspace, result)
                    )
            finally:
                with owner._decompiled_preview_threads_lock:
                    owner._decompiled_preview_threads.discard(current_thread)

        thread = threading.Thread(
            target=worker,
            daemon=True,
            name="vr-code-preview",
        )
        with owner._decompiled_preview_threads_lock:
            owner._decompiled_preview_threads.add(thread)
        thread.start()

    def handle_resolved(self, payload: object) -> None:
        if (
            not isinstance(payload, tuple)
            or len(payload) != 3
            or not isinstance(payload[0], int)
            or not isinstance(payload[1], Path)
            or not isinstance(payload[2], dict)
        ):
            return
        generation, workspace, result = payload
        owner = self._owner
        if owner._closed:
            return
        with owner._decompiled_preview_threads_lock:
            if generation != owner._decompiled_preview_generation:
                return
        if workspace != owner._settings.root:
            return
        owner.decompiledSourcePreviewRequested.emit(result)

    def close(self) -> None:
        owner = self._owner
        with owner._decompiled_preview_threads_lock:
            owner._decompiled_preview_generation += 1
            threads = tuple(owner._decompiled_preview_threads)
        current_thread = threading.current_thread()
        for thread in threads:
            if thread is not current_thread and thread.is_alive():
                thread.join(timeout=1.0)
