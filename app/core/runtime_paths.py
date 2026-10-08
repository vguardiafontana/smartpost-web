from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "SmartPost"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """Read-only application/resource root.

    In PyInstaller one-dir builds, sys._MEIPASS points to the bundled resource
    directory. In source/dev mode we use the repository root.
    """
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return Path(__file__).resolve().parents[2]


def data_root() -> Path:
    """Writable per-user application data directory.

    SMARTPOST_DATA_DIR is intentionally supported for tests/portable diagnostics.
    """
    override = os.environ.get("SMARTPOST_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if appdata:
            return (Path(appdata) / APP_NAME).resolve()
    # Development fallback on non-Windows hosts.
    return (bundle_root() / "runtime" / "userdata").resolve()


def resource_path(relative: str | Path) -> Path:
    return (bundle_root() / Path(relative)).resolve()


def user_path(relative: str | Path) -> Path:
    return (data_root() / Path(relative)).resolve()


def ensure_data_dirs() -> Path:
    root = data_root()
    for rel in (
        "logs",
        "work",
        "profiles/epresis",
        "profiles/whatsapp",
        "profiles/denuncias",
        "output/reportes",
        "output/denuncias",
        "output/historico",
        "output/pruebas",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


def configure_bundled_playwright() -> None:
    """Configure the Playwright browser bundle and its Node driver in frozen builds.

    Playwright launches a bundled Node executable before Chromium. PyInstaller may
    otherwise leave the driver outside the path Playwright computes at runtime,
    causing WinError 2 at ``async_playwright().__aenter__``.
    """
    bundled = resource_path("playwright-browsers")
    if bundled.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)

    if os.name == "nt":
        bundled_node = resource_path("playwright/driver/node.exe")
        if bundled_node.exists():
            os.environ["PLAYWRIGHT_NODEJS_PATH"] = str(bundled_node)
