# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

playwright_datas, playwright_binaries, playwright_hidden = collect_all("playwright")
spellchecker_datas, spellchecker_binaries, spellchecker_hidden = collect_all("spellchecker")
tree_sitter_datas, tree_sitter_binaries, tree_sitter_hidden = collect_all("tree_sitter")
tree_sitter_java_datas, tree_sitter_java_binaries, tree_sitter_java_hidden = collect_all("tree_sitter_java")

a = Analysis(
    ["VRNorteStudio.pyw"],
    pathex=[],
    binaries=(playwright_binaries + spellchecker_binaries + tree_sitter_binaries
              + tree_sitter_java_binaries),
    datas=playwright_datas + spellchecker_datas + tree_sitter_datas + tree_sitter_java_datas + [
        (".env.example", "."),
        ("README.md", "."),
        ("vrsoft_extractor/mary/data/produtos_filas.md", "vrsoft_extractor/mary/data"),
        ("vrsoft_extractor/mary/data/vr-search.ps1", "vrsoft_extractor/mary/data"),
        ("vrsoft_extractor/mary/data/Abrir-VR-no-Codex.cmd", "vrsoft_extractor/mary/data"),
        ("vrsoft_extractor/mary/assets", "vrsoft_extractor/mary/assets"),
        ("vrsoft_extractor/mary/frontend/qml", "vrsoft_extractor/mary/frontend/qml"),
    ],
    hiddenimports=(playwright_hidden + spellchecker_hidden + tree_sitter_hidden
                   + tree_sitter_java_hidden + [
        "pytesseract",
        "PIL.Image",
        "bs4",
        "markdownify",
    ]),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VRNorteStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="vrsoft_extractor/mary/assets/vrnorte-app.ico",
    version="installer/VRNorteStudio.version.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VRNorteStudio",
)
