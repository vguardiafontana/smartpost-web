from __future__ import annotations

import os
from pathlib import Path


def excel_installation_path() -> Path | None:
    if os.name != "nt":
        return None
    try:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Excel.Application\CLSID"):
                # COM registration exists even for many Click-to-Run Office installs.
                return Path("excel-com-registered")
        except OSError:
            pass
        locations = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\excel.exe"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe"),
        ]
        for hive, key_name in locations:
            try:
                with winreg.OpenKey(hive, key_name) as key:
                    value, _ = winreg.QueryValueEx(key, None)
                    p = Path(value)
                    if p.exists():
                        return p
            except OSError:
                continue
    except Exception:
        return None
    return None


def has_excel() -> bool:
    return excel_installation_path() is not None
