# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from importlib.util import find_spec

# Optional local semantic runtime. Public model weights are prepared explicitly
# in the managed project directory and are never fetched by the packaged app.
semantic_datas, semantic_binaries, semantic_hidden = [], [], []
for module in ("numpy", "onnxruntime", "tokenizers"):
    if find_spec(module) is not None:
        data, binaries, hidden = collect_all(module)
        semantic_datas.extend(data)
        semantic_binaries.extend(binaries)
        semantic_hidden.extend(hidden)

playwright_datas, playwright_binaries, playwright_hidden = collect_all("playwright")
spellchecker_datas, spellchecker_binaries, spellchecker_hidden = collect_all("spellchecker")
tree_sitter_datas, tree_sitter_binaries, tree_sitter_hidden = collect_all("tree_sitter")
tree_sitter_java_datas, tree_sitter_java_binaries, tree_sitter_java_hidden = collect_all("tree_sitter_java")

a = Analysis(
    ["VRNorteStudio.pyw"],
    pathex=[],
    binaries=(playwright_binaries + spellchecker_binaries + tree_sitter_binaries
              + tree_sitter_java_binaries + semantic_binaries),
    datas=playwright_datas + spellchecker_datas + tree_sitter_datas + tree_sitter_java_datas + semantic_datas + [
        (".env.example", "."),
        ("README.md", "."),
        ("vrsoft_extractor/mary/data/produtos_filas.md", "vrsoft_extractor/mary/data"),
        ("vrsoft_extractor/mary/data/t3_themes.json", "vrsoft_extractor/mary/data"),
        ("vrsoft_extractor/mary/data/t3_themes.LICENSE", "vrsoft_extractor/mary/data"),
        ("vrsoft_extractor/mary/data/vr-search.ps1", "vrsoft_extractor/mary/data"),
        ("vrsoft_extractor/mary/data/antigravity-browser-noop.ps1", "vrsoft_extractor/mary/data"),
        ("vrsoft_extractor/mary/data/Abrir-VR-no-Codex.cmd", "vrsoft_extractor/mary/data"),
        ("vrsoft_extractor/mary/assets", "vrsoft_extractor/mary/assets"),
        ("vrsoft_extractor/mary/frontend/qml", "vrsoft_extractor/mary/frontend/qml"),
    ],
    hiddenimports=(playwright_hidden + spellchecker_hidden + tree_sitter_hidden
                   + tree_sitter_java_hidden + semantic_hidden + [
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
