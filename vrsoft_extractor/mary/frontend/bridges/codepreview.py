from __future__ import annotations

import logging
import threading
from typing import Any
from urllib.parse import unquote

from ...code_index import JavaCodeIndex
from ...code_references import JavaCodeReference
from ..code_links import parse_code_reference

LOGGER = logging.getLogger(__name__)


class CodePreviewDomain:
    """Domain operations for decompiled code preview."""

    def __init__(self, owner: Any) -> None:
        object.__setattr__(self, "_owner", owner)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._owner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._owner, name, value)

    def openDecompiledReference(self, value: str) -> None:  # noqa: N802
        """Resolve a decompiled Java code reference and request its preview."""
        if getattr(self, "_closed", False):
            return

        raw_str = str(value or "").strip()
        if not raw_str:
            return

        ref_target: str | JavaCodeReference
        if raw_str.startswith("vr-code:"):
            parsed = parse_code_reference(raw_str)
            if parsed is not None:
                ref_target = parsed
            else:
                ref_target = unquote(raw_str[len("vr-code:") :]).strip()
        else:
            ref_target = raw_str

        with self._decompiled_preview_lock:
            self._decompiled_preview_generation += 1
            generation = self._decompiled_preview_generation

        workspace = (self._project_scope or self._settings.root).resolve(strict=False)
        release_id = str(getattr(self, "_code_analysis_release", "current") or "current")

        def worker() -> None:
            current_thread = threading.current_thread()
            with self._decompiled_preview_lock:
                self._decompiled_preview_threads.add(current_thread)
            try:
                try:
                    index = JavaCodeIndex(workspace)
                    payload = index.resolve_decompiled_reference(
                        ref_target, release_id=release_id
                    )
                except Exception as exc:
                    LOGGER.exception(
                        "Falha ao resolver referência de código descompilado '%s'",
                        ref_target,
                    )
                    payload = {
                        "state": "error",
                        "reference": (
                            ref_target.raw
                            if isinstance(ref_target, JavaCodeReference)
                            else str(ref_target)
                        ),
                        "release_id": release_id,
                        "title": "",
                        "package_name": "",
                        "qualified_name": "",
                        "target_symbol": "",
                        "target_kind": "",
                        "target_signature": "",
                        "tool": "",
                        "clean_status": "error",
                        "clean_reason": str(exc),
                        "raw_target_line": 0,
                        "clean_target_line": 0,
                        "overload_count": 0,
                        "truncated": False,
                        "body": "",
                        "clean_body": "",
                        "candidates": [],
                        "jar_relative_path": "",
                        "message": f"Erro inesperado ao resolver referência: {exc}",
                    }

                if getattr(self, "_closed", False):
                    return

                with self._decompiled_preview_lock:
                    if generation != self._decompiled_preview_generation:
                        return
                    self._decompiled_preview_payload = payload

                try:
                    self.decompiledPreviewRequested.emit(payload)
                except RuntimeError:
                    pass
            finally:
                with self._decompiled_preview_lock:
                    self._decompiled_preview_threads.discard(current_thread)

        thread = threading.Thread(
            target=worker,
            daemon=True,
            name=f"vr-code-preview-{generation}",
        )
        thread.start()
