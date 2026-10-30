from __future__ import annotations

import sys

from app.core.runtime_paths import configure_bundled_playwright, ensure_data_dirs, resource_path


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from app.core.self_test import run_self_test
        return run_self_test(sys.argv[2])
    from app.core.config import ensure_user_config
    configure_bundled_playwright()
    ensure_data_dirs()
    ensure_user_config()

    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('SmartPost.Desktop')

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from app.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("SmartPost")
    app.setOrganizationName("SmartPost")
    icon = resource_path("assets/smartpost.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
