"""Application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from platformdirs import user_config_dir
from PySide6.QtWidgets import QApplication

from plexlibrary.services.settings_service import SettingsService
from plexlibrary.ui.main_window import MainWindow

APP_NAME = "PlexLibrary"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Dmitriy")

    settings_service = SettingsService(config_dir=Path(user_config_dir(APP_NAME, appauthor=False)))
    window = MainWindow(settings_service)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
