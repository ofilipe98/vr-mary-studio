from __future__ import annotations

from pathlib import Path


def off_direct_source_roots(root: str | Path) -> tuple[tuple[str, Path], ...]:
    base = Path(root)
    return (
        ("documentacao", (base / "conhecimento").resolve(strict=False)),
        ("schema", (base / "SchemaVR").resolve(strict=False)),
        ("codigo", (base / "indice" / "codigo" / "decompilation").resolve(strict=False)),
    )


def existing_off_direct_source_roots(root: str | Path) -> tuple[tuple[str, Path], ...]:
    return tuple(
        (name, path)
        for name, path in off_direct_source_roots(root)
        if path.is_dir()
    )
