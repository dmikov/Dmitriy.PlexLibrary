"""Application main window with library selection loaded from the local Plex database."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from plexlibrary.models.library import LibrarySection
from plexlibrary.services.library_db_service import LibraryDbError, LibraryDbService
from plexlibrary.services.metadata_cache_service import MetadataCacheService
from plexlibrary.services.metadata_service import TmdbMetadataService
from plexlibrary.services.settings_service import SettingsService
from plexlibrary.services.show_metadata_provider import ShowMetadataProvider
from plexlibrary.services.ui_layout_state import restore_window_geometry, save_window_geometry
from plexlibrary.ui.settings_dialog import SettingsDialog
from plexlibrary.ui.tv_library_tree import TvLibraryTreeWidget


class _LibraryLoadWorker(QObject):
    """Prepares the local database and reads library sections on a background thread."""

    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(self, library_db_service: LibraryDbService) -> None:
        super().__init__()
        self._library_db_service = library_db_service

    def run(self) -> None:
        try:
            db_path = self._library_db_service.ensure_local_database()
            libraries = self._library_db_service.list_libraries(db_path)
        except LibraryDbError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Unexpected error: {exc}")
        else:
            self.succeeded.emit(libraries)


class MainWindow(QMainWindow):
    """The application's top-level window."""

    def __init__(self, settings_service: SettingsService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings_service = settings_service
        self._library_db_service = LibraryDbService(settings_service)
        self._metadata_service = TmdbMetadataService(settings_service)
        self._metadata_cache_service = MetadataCacheService(settings_service.config_dir)
        self._metadata_provider = ShowMetadataProvider(self._metadata_service, self._metadata_cache_service)
        self._thread: QThread | None = None
        self._worker: _LibraryLoadWorker | None = None
        self._db_path: Path | None = None
        self._libraries: list[LibrarySection] = []

        app_settings = self._settings_service.load()
        self._ui_layout = app_settings.ui_layout

        self.setWindowTitle("Plex Library")
        if not restore_window_geometry(self, self._ui_layout.window_geometry):
            self.resize(1100, 750)

        self._canvas = QWidget(self)
        self._status_label = QLabel("Loading libraries…", self._canvas)
        self._status_label.setWordWrap(True)
        self._library_combo = QComboBox(self._canvas)
        self._library_combo.setEnabled(False)
        self._library_combo.currentIndexChanged.connect(self._on_library_changed)

        self._tv_tree = TvLibraryTreeWidget(
            self._library_db_service,
            self._canvas,
            layout_settings=self._ui_layout,
            metadata_provider=self._metadata_provider,
        )

        form = QFormLayout()
        form.addRow("Library:", self._library_combo)

        layout = QVBoxLayout(self._canvas)
        layout.addLayout(form)
        layout.addWidget(self._status_label)
        layout.addWidget(self._tv_tree, stretch=1)

        self.setCentralWidget(self._canvas)
        self._build_toolbar()
        self.refresh_libraries()

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._save_layout_state()
        super().closeEvent(event)

    def _save_layout_state(self) -> None:
        self._ui_layout.window_geometry = save_window_geometry(self)
        self._tv_tree.save_layout_state()

        selected_library_id: int | None = None
        current_index = self._library_combo.currentIndex()
        if 0 <= current_index < len(self._libraries):
            selected_library_id = self._libraries[current_index].id
        self._ui_layout.selected_library_id = selected_library_id

        settings = self._settings_service.load()
        settings.ui_layout = self._ui_layout
        self._settings_service.save(settings)

    def _restore_selected_library(self) -> None:
        selected_library_id = self._ui_layout.selected_library_id
        if selected_library_id is None:
            self._on_library_changed(self._library_combo.currentIndex())
            return

        for index, library in enumerate(self._libraries):
            if library.id == selected_library_id:
                self._library_combo.blockSignals(True)
                self._library_combo.setCurrentIndex(index)
                self._library_combo.blockSignals(False)
                self._on_library_changed(index)
                return

        self._on_library_changed(self._library_combo.currentIndex())

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        self.addToolBar(toolbar)

        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        settings_action = QAction("⚙", self)
        settings_action.setToolTip("Settings")
        settings_action.triggered.connect(self._open_settings)
        toolbar.addAction(settings_action)

    def refresh_libraries(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return

        self._library_combo.blockSignals(True)
        self._library_combo.setEnabled(False)
        self._library_combo.clear()
        self._library_combo.blockSignals(False)
        self._tv_tree.load_library(None)
        self._status_label.setText("Loading libraries…")

        self._thread = QThread(self)
        self._worker = _LibraryLoadWorker(self._library_db_service)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.succeeded.connect(self._on_libraries_loaded)
        self._worker.failed.connect(self._on_libraries_failed)
        self._worker.succeeded.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)

        self._thread.start()

    def _cleanup_thread(self) -> None:
        if self._thread is not None:
            self._thread.wait()
        self._thread = None
        self._worker = None

    def _on_libraries_loaded(self, libraries: list[LibrarySection]) -> None:
        self._libraries = libraries
        self._db_path = Path(self._settings_service.load().download_destination)
        self._tv_tree.set_database_path(self._db_path)
        self._tv_tree.set_layout_settings(self._ui_layout)

        self._library_combo.blockSignals(True)
        self._library_combo.clear()
        if not libraries:
            self._library_combo.setEnabled(False)
            self._library_combo.blockSignals(False)
            self._status_label.setText("No libraries were found in the downloaded database.")
            self._tv_tree.load_library(None)
            return

        for library in libraries:
            self._library_combo.addItem(library.name, library)

        self._library_combo.setEnabled(True)
        self._library_combo.blockSignals(False)
        self._status_label.setText(
            f"Loaded {len(libraries)} libraries from {self._db_path}. "
            "Using cached copy when it is less than 1 day old."
        )
        self._restore_selected_library()

    def _on_libraries_failed(self, message: str) -> None:
        self._library_combo.clear()
        self._library_combo.setEnabled(False)
        self._status_label.setText(message)
        self._tv_tree.load_library(None)
        QMessageBox.warning(self, "Could not load libraries", message)

    def _on_library_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._libraries):
            self._tv_tree.load_library(None)
            return
        library = self._library_combo.itemData(index)
        if isinstance(library, LibrarySection):
            self._tv_tree.load_library(library)
        else:
            self._tv_tree.load_library(self._libraries[index])

    def _open_settings(self) -> None:
        self._save_layout_state()
        dialog = SettingsDialog(self._settings_service, self)
        dialog.exec()
        self.refresh_libraries()
