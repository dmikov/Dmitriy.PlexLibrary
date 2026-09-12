"""Dialog for configuring how to reach the Plex database."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from plexlibrary.models.connection import AppSettings, ConnectionType
from plexlibrary.services.settings_service import SettingsService
from plexlibrary.ui.connection_forms import (
    ConnectionFormWidget,
    LocalConnectionForm,
    PlexDiagnosticsConnectionForm,
    SmbConnectionForm,
)

_TYPE_LABELS: dict[ConnectionType, str] = {
    ConnectionType.LOCAL: "Local / mounted path",
    ConnectionType.SMB: "SMB network share",
    ConnectionType.PLEX_DIAGNOSTICS: "Plex diagnostics (HTTP)",
}


class SettingsDialog(QDialog):
    """Lets the user pick how to reach their Plex database."""

    def __init__(self, settings_service: SettingsService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(520, 420)

        self._settings_service = settings_service

        self._type_combo = QComboBox(self)
        for connection_type in ConnectionType:
            self._type_combo.addItem(_TYPE_LABELS[connection_type], connection_type)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)

        self._local_form = LocalConnectionForm(self)
        self._smb_form = SmbConnectionForm(self)
        self._plex_diagnostics_form = PlexDiagnosticsConnectionForm(self)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._local_form)
        self._stack.addWidget(self._smb_form)
        self._stack.addWidget(self._plex_diagnostics_form)

        self._tmdb_api_key_edit = QLineEdit(self)
        self._tmdb_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._tmdb_api_key_edit.setPlaceholderText("TMDb API key (optional, see README)")

        top_form = QFormLayout()
        top_form.addRow("Connection type:", self._type_combo)

        bottom_form = QFormLayout()
        bottom_form.addRow("TMDb API key:", self._tmdb_api_key_edit)

        self._status_label = QLabel("", self)
        self._status_label.setWordWrap(True)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close, self)
        button_box.accepted.connect(self._save_and_close)
        button_box.rejected.connect(self._close_dialog)

        layout = QVBoxLayout(self)
        layout.addLayout(top_form)
        layout.addWidget(self._stack)
        layout.addLayout(bottom_form)
        layout.addWidget(self._status_label)
        layout.addStretch(1)
        layout.addWidget(button_box)

        self._load_from_settings()

    def _form_for_type(self, connection_type: ConnectionType) -> ConnectionFormWidget:
        return {
            ConnectionType.LOCAL: self._local_form,
            ConnectionType.SMB: self._smb_form,
            ConnectionType.PLEX_DIAGNOSTICS: self._plex_diagnostics_form,
        }[connection_type]

    def _current_form(self) -> ConnectionFormWidget:
        return self._stack.currentWidget()  # type: ignore[return-value]

    def _on_type_changed(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

    def _load_from_settings(self) -> None:
        app_settings = self._settings_service.load()
        self._tmdb_api_key_edit.setText(self._settings_service.load_tmdb_api_key())

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
        existing = self._settings_service.load()
        connection = self._current_form().to_settings()
        return AppSettings(
            connection=connection,
            ui_layout=existing.ui_layout,
        )

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
        tmdb_key_saved = self._settings_service.save_tmdb_api_key(self._tmdb_api_key_edit.text().strip())
        credentials_saved = credentials_saved and tmdb_key_saved

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

    def _close_dialog(self) -> None:
        self._persist_settings()
        self.reject()
