# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
import playwright

ROOT = Path(SPECPATH).resolve().parent
BROWSERS = ROOT / "build" / "playwright-browsers"
PLAYWRIGHT_PKG = Path(playwright.__file__).resolve().parent
PLAYWRIGHT_DRIVER = PLAYWRIGHT_PKG / "driver"

if not BROWSERS.exists():
    raise SystemExit(
        "Falta build/playwright-browsers. Ejecutá packaging/build_windows.ps1; "
        "ese script descarga Chromium antes de PyInstaller."
    )

datas = [
    (str(ROOT / "assets" / "TEMPLATE_REPORTE.xlsx"), "assets"),
    (str(ROOT / "assets" / "PROMPT_MAESTRO.md"), "assets"),
    (str(ROOT / "assets" / "smartpost.ico"), "assets"),
    (str(ROOT / "config.default.yaml"), "."),
    (str(BROWSERS), "playwright-browsers"),
]
# Playwright needs its Node driver at runtime. collect_data_files() does not reliably
# preserve node.exe in a frozen Windows app, so bundle it explicitly.
datas += collect_data_files("playwright")
if (PLAYWRIGHT_DRIVER / "package").exists():
    datas.append((str(PLAYWRIGHT_DRIVER / "package"), "playwright/driver/package"))

binaries = []
node_name = "node.exe" if __import__("sys").platform == "win32" else "node"
node_path = PLAYWRIGHT_DRIVER / node_name
if node_path.exists():
    binaries.append((str(node_path), "playwright/driver"))
else:
    raise SystemExit(f"Falta el driver Node de Playwright: {node_path}")

hiddenimports = []
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += [
    "pythoncom",
    "pywintypes",
    "win32com",
    "win32com.client",
    "win32com.server",
]

a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "polars", "openpyxl"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SmartPost",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "smartpost.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SmartPost",
)
