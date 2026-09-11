"""Dialog for configuring where the Plex database lives and pulling a local copy of it."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from plexlibrary.models.connection import AppSettings, ConnectionSettings, ConnectionType
from plexlibrary.services.database_downloader import DatabaseDownloadError, create_downloader
from plexlibrary.services.settings_service import SettingsService
from plexlibrary.ui.connection_forms import (
    ConnectionFormWidget,
    LocalConnectionForm,
    PlexDiagnosticsConnectionForm,
    SftpConnectionForm,
    SmbConnectionForm,
)

_TYPE_LABELS: dict[ConnectionType, str] = {
    ConnectionType.LOCAL: "Local / mounted path",
    ConnectionType.SMB: "SMB network share",
    ConnectionType.SFTP: "SFTP / SSH",
    ConnectionType.PLEX_DIAGNOSTICS: "Plex diagnostics (HTTP)",
}


class _DownloadWorker(QObject):
    """Runs a `DatabaseDownloader` on a background thread."""

    succeeded = Signal(Path)
    failed = Signal(str)

    def __init__(self, connection: ConnectionSettings, password: str, destination: Path) -> None:
        super().__init__()
        self._connection = connection
        self._password = password
        self._destination = destination

    def run(self) -> None:
        try:
            downloader = create_downloader(self._connection, self._password)
            result = downloader.download(self._destination)
        except DatabaseDownloadError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # unexpected transport/library failure
            self.failed.emit(f"Unexpected error: {exc}")
        else:
            self.succeeded.emit(result)


class SettingsDialog(QDialog):
    """Lets the user pick how to reach their Plex database and fetch a local copy."""

    def __init__(self, settings_service: SettingsService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(520, 420)

        self._settings_service = settings_service
        self._thread: QThread | None = None
        self._worker: _DownloadWorker | None = None

        self._type_combo = QComboBox(self)
        for connection_type in ConnectionType:
            self._type_combo.addItem(_TYPE_LABELS[connection_type], connection_type)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)

        self._local_form = LocalConnectionForm(self)
        self._smb_form = SmbConnectionForm(self)
        self._sftp_form = SftpConnectionForm(self)
        self._plex_diagnostics_form = PlexDiagnosticsConnectionForm(self)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._local_form)
        self._stack.addWidget(self._smb_form)
        self._stack.addWidget(self._sftp_form)
        self._stack.addWidget(self._plex_diagnostics_form)

        self._destination_edit = QLineEdit(self)
        destination_browse = QPushButton("Browse…", self)
        destination_browse.clicked.connect(self._browse_for_destination)
        destination_row = QHBoxLayout()
        destination_row.addWidget(self._destination_edit)
        destination_row.addWidget(destination_browse)
        destination_row_widget = QWidget(self)
        destination_row_widget.setLayout(destination_row)

        top_form = QFormLayout()
        top_form.addRow("Connection type:", self._type_combo)

        bottom_form = QFormLayout()
        bottom_form.addRow("Save downloaded copy to:", destination_row_widget)

        self._status_label = QLabel("", self)
        self._status_label.setWordWrap(True)

        self._download_button = QPushButton("Download Now", self)
        self._download_button.clicked.connect(self._download_now)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close, self)
        button_box.accepted.connect(self._save_and_close)
        button_box.rejected.connect(self._close_dialog)

        layout = QVBoxLayout(self)
        layout.addLayout(top_form)
        layout.addWidget(self._stack)
        layout.addLayout(bottom_form)
        layout.addWidget(self._download_button)
        layout.addWidget(self._status_label)
        layout.addStretch(1)
        layout.addWidget(button_box)

        self._load_from_settings()

    def _form_for_type(self, connection_type: ConnectionType) -> ConnectionFormWidget:
        return {
            ConnectionType.LOCAL: self._local_form,
            ConnectionType.SMB: self._smb_form,
            ConnectionType.SFTP: self._sftp_form,
            ConnectionType.PLEX_DIAGNOSTICS: self._plex_diagnostics_form,
        }[connection_type]

    def _current_form(self) -> ConnectionFormWidget:
        return self._stack.currentWidget()  # type: ignore[return-value]

    def _on_type_changed(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

    def _browse_for_destination(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Choose local destination", self._destination_edit.text(), "Plex database (*.db);;All files (*)"
        )
        if path:
            self._destination_edit.setText(path)

    def _load_from_settings(self) -> None:
        app_settings = self._settings_service.load()
        self._destination_edit.setText(app_settings.download_destination)

        connection = app_settings.connection
        if connection is None:
            self._type_combo.setCurrentIndex(0)
            return

        index = self._type_combo.findData(connection.type)
        self._type_combo.setCurrentIndex(max(index, 0))
        form = self._form_for_type(connection.type)
        form.set_settings(connection)
        form.set_password(self._settings_service.load_password(connection))

    def _build_app_settings(self) -> AppSettings:
        connection = self._current_form().to_settings()
        return AppSettings(connection=connection, download_destination=self._destination_edit.text().strip())

    def _persist_settings(self, *, show_status: bool = False) -> bool:
        try:
            app_settings = self._build_app_settings()
        except Exception as exc:
            if show_status:
                self._status_label.setText(f"Could not save settings: {exc}")
            return False

        try:
            self._settings_service.save(app_settings)
        except OSError as exc:
            if show_status:
                self._status_label.setText(f"Could not write settings file: {exc}")
            return False

        credentials_saved = True
        if app_settings.connection is not None:
            credentials_saved = self._settings_service.save_credentials(
                app_settings.connection,
                self._current_form().password(),
            )

        if show_status:
            config_file = self._settings_service.config_file
            if credentials_saved:
                self._status_label.setText(f"Settings saved to {config_file}")
            else:
                self._status_label.setText(
                    f"Settings saved to {config_file}, but credentials could not be stored in the OS keyring."
                )
        return True

    def _save_and_close(self) -> None:
        if not self._persist_settings():
            QMessageBox.warning(self, "Could not save settings", self._status_label.text())
            return
        self.accept()

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._persist_settings()
        super().closeEvent(event)

    def _download_now(self) -> None:
        try:
            app_settings = self._build_app_settings()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid settings", str(exc))
            return

        if app_settings.connection is None:
            QMessageBox.warning(self, "Invalid settings", "No connection is configured.")
            return

        if not app_settings.download_destination:
            QMessageBox.warning(self, "Invalid settings", "Choose a local destination for the downloaded database.")
            return

        self._persist_settings()

        self._download_button.setEnabled(False)
        self._status_label.setText("Downloading…")

        destination = Path(app_settings.download_destination)
        password = self._current_form().password()

        self._thread = QThread(self)
        self._worker = _DownloadWorker(app_settings.connection, password, destination)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.succeeded.connect(self._on_download_succeeded)
        self._worker.failed.connect(self._on_download_failed)
        self._worker.succeeded.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)

        self._thread.start()

    def _close_dialog(self) -> None:
        self._persist_settings()
        self.reject()

    def _cleanup_thread(self) -> None:
        self._download_button.setEnabled(True)
        if self._thread is not None:
            self._thread.wait()
        self._thread = None
        self._worker = None

    def _on_download_succeeded(self, destination: Path) -> None:
        self._status_label.setText(f"Downloaded successfully to {destination}")

    def _on_download_failed(self, message: str) -> None:
        self._status_label.setText(f"Download failed: {message}")
        QMessageBox.critical(self, "Download failed", message)
