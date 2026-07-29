# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

playwright_datas, playwright_binaries, playwright_hidden = collect_all("playwright")

a = Analysis(
    ["VRMaryStudio.pyw"],
    pathex=[],
    binaries=playwright_binaries,
    datas=playwright_datas + [
        (".env.example", "."),
        ("README.md", "."),
        ("vrsoft_extractor/mary/data/produtos_filas.md", "vrsoft_extractor/mary/data"),
    ],
    hiddenimports=playwright_hidden + [
        "pytesseract",
        "PIL.Image",
        "bs4",
        "markdownify",
    ],
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
    name="VRMaryStudio",
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VRMaryStudio",
)
