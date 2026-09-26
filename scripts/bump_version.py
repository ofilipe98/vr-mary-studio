"""Sincroniza a versão do VRStudio nos quatro arquivos canônicos.

Uso:
    python scripts/bump_version.py --commit      # 0.6.7-1 -> 0.6.7-2 (build + 1)
    python scripts/bump_version.py --promote     # 0.6.7-N -> 0.6.8-1 (promoção dev->main)
    python scripts/bump_version.py --set 0.6.8-1 # define a versão explicitamente
    python scripts/bump_version.py --show        # apenas exibe a versão atual

O hook `.githooks/pre-commit` chama `--commit` a cada commit; a promoção é um
comando manual executado antes do PR de dev para main.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VERSION_FILES = (
    "pyproject.toml",
    "vrsoft_extractor/__init__.py",
    "installer/VRNorteStudio.iss",
    "installer/VRNorteStudio.version.txt",
)

_VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-(\d+))?")

_REPLACEMENTS: dict[str, list[tuple[re.Pattern[str], str]]] = {
    "pyproject.toml": [
        (re.compile(r'(?m)^version\s*=\s*"[^"]*"'), 'version = "{version}"'),
    ],
    "vrsoft_extractor/__init__.py": [
        (re.compile(r'(?m)^__version__\s*=\s*"[^"]*"'), '__version__ = "{version}"'),
    ],
    "installer/VRNorteStudio.iss": [
        (re.compile(r'(?m)^#define\s+MyAppVersion\s+"[^"]*"'), '#define MyAppVersion "{version}"'),
    ],
    "installer/VRNorteStudio.version.txt": [
        (re.compile(r"StringStruct\('FileVersion', '[^']*'\)"), "StringStruct('FileVersion', '{version}')"),
        (re.compile(r"StringStruct\('ProductVersion', '[^']*'\)"), "StringStruct('ProductVersion', '{version}')"),
        (re.compile(r"filevers=\([^)]*\)"), "filevers=({major}, {minor}, {patch}, {build})"),
        (re.compile(r"prodvers=\([^)]*\)"), "prodvers=({major}, {minor}, {patch}, {build})"),
    ],
}

_READERS: dict[str, re.Pattern[str]] = {
    "pyproject.toml": re.compile(r'(?m)^version\s*=\s*"([^"]*)"'),
    "vrsoft_extractor/__init__.py": re.compile(r'(?m)^__version__\s*=\s*"([^"]*)"'),
    "installer/VRNorteStudio.iss": re.compile(r'(?m)^#define\s+MyAppVersion\s+"([^"]*)"'),
    "installer/VRNorteStudio.version.txt": re.compile(r"StringStruct\('FileVersion', '([^']*)'\)"),
}


class VersionError(RuntimeError):
    """Versão inválida ou arquivos de versão fora de sincronia."""


def _parse(version: str) -> tuple[int, int, int, int]:
    match = _VERSION_PATTERN.fullmatch(version)
    if not match:
        raise VersionError(f"versao invalida: {version!r} (esperado X.Y.Z ou X.Y.Z-N)")
    major, minor, patch, build = match.groups()
    return int(major), int(minor), int(patch), int(build or 0)


def next_build(version: str) -> str:
    major, minor, patch, build = _parse(version)
    return f"{major}.{minor}.{patch}-{build + 1}"


def next_release(version: str) -> str:
    major, minor, patch, _ = _parse(version)
    return f"{major}.{minor}.{patch + 1}-1"


def _read(root: Path, relative: str) -> str:
    return (root / relative).read_bytes().decode("utf-8")


def read_version(root: Path) -> str:
    """Lê a versão canônica (`pyproject.toml`)."""
    match = _READERS["pyproject.toml"].search(_read(root, "pyproject.toml"))
    if not match:
        raise VersionError("versao nao encontrada em pyproject.toml")
    return match.group(1)


def verify_version(root: Path) -> str:
    """Confere que os quatro arquivos declaram a mesma versão."""
    found: dict[str, str] = {}
    for relative, reader in _READERS.items():
        match = reader.search(_read(root, relative))
        if not match:
            raise VersionError(f"versao nao encontrada em {relative}")
        found[relative] = match.group(1)
    versions = set(found.values())
    if len(versions) != 1:
        raise VersionError(f"arquivos de versao fora de sincronia: {sorted(versions)}")
    version = versions.pop()
    major, minor, patch, build = _parse(version)
    expected = f"({major}, {minor}, {patch}, {build})"
    version_txt = _read(root, "installer/VRNorteStudio.version.txt")
    for key in ("filevers", "prodvers"):
        match = re.search(rf"{key}=\(([^)]*)\)", version_txt)
        if not match:
            raise VersionError(f"{key} ausente em installer/VRNorteStudio.version.txt")
        tuple_value = f"({', '.join(part.strip() for part in match.group(1).split(','))})"
        if tuple_value != expected:
            raise VersionError(f"{key}={tuple_value} diverge de {expected}")
    return version


def set_version(root: Path, version: str) -> None:
    """Aplica `version` aos quatro arquivos e valida o resultado."""
    major, minor, patch, build = _parse(version)
    values = {
        "version": version,
        "major": str(major),
        "minor": str(minor),
        "patch": str(patch),
        "build": str(build),
    }
    for relative, replacements in _REPLACEMENTS.items():
        path = root / relative
        content = _read(root, relative)
        for pattern, template in replacements:
            content, count = pattern.subn(template.format(**values), content, count=1)
            if count != 1:
                raise VersionError(f"padrao nao encontrado em {relative}: {pattern.pattern}")
        path.write_bytes(content.encode("utf-8"))
    applied = verify_version(root)
    if applied != version:
        raise VersionError(f"versao aplicada {applied} difere de {version}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Versiona o VRStudio nos arquivos canônicos.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--commit", action="store_true", help="incrementa o build (padrão)")
    group.add_argument("--promote", action="store_true", help="incrementa o patch e zera o build")
    group.add_argument("--set", dest="set_version", metavar="VERSION", help="define a versão")
    group.add_argument("--show", action="store_true", help="apenas exibe a versão atual")
    parser.add_argument("--root", metavar="DIR", help="raiz do repositório (para testes)")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    try:
        current = verify_version(root)
        if args.show:
            print(current)
            return 0
        if args.promote:
            target = next_release(current)
        elif args.set_version:
            target = args.set_version
        else:
            target = next_build(current)
        set_version(root, target)
    except (VersionError, OSError) as exc:
        print(f"bump_version: {exc}", file=sys.stderr)
        return 1
    print(f"{current} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
