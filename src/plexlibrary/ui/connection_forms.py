"""Per-connection-type form widgets used by the settings dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from plexlibrary.models.connection import (
    ConnectionSettings,
    LocalConnectionSettings,
    PlexDiagnosticsConnectionSettings,
    SmbConnectionSettings,
)


class ConnectionFormWidget(QWidget):
    """Common interface implemented by every per-connection-type form."""

    def to_settings(self) -> ConnectionSettings:
        raise NotImplementedError

    def set_settings(self, settings: ConnectionSettings) -> None:
        raise NotImplementedError

    def password(self) -> str:
        return ""

    def set_password(self, password: str) -> None:
        return None


class LocalConnectionForm(ConnectionFormWidget):
    """Fields for a database reachable directly on the filesystem (including mounted shares)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._database_path_edit = QLineEdit(self)
        browse_button = QPushButton("Browse…", self)
        browse_button.clicked.connect(self._browse_for_database)

        path_row = QHBoxLayout()
        path_row.addWidget(self._database_path_edit)
        path_row.addWidget(browse_button)
        path_row_widget = QWidget(self)
        path_row_widget.setLayout(path_row)

        layout = QFormLayout(self)
        layout.addRow("Database file:", path_row_widget)

    def _browse_for_database(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Plex database file", self._database_path_edit.text(), "Plex database (*.db);;All files (*)"
        )
        if path:
            self._database_path_edit.setText(path)

    def to_settings(self) -> ConnectionSettings:
        return LocalConnectionSettings(database_path=self._database_path_edit.text().strip())

    def set_settings(self, settings: ConnectionSettings) -> None:
        if isinstance(settings, LocalConnectionSettings):
            self._database_path_edit.setText(settings.database_path)


class SmbConnectionForm(ConnectionFormWidget):
    """Fields for a database reachable over an SMB/CIFS network share."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._server_edit = QLineEdit(self)
        self._port_spin = QSpinBox(self)
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(445)
        self._share_edit = QLineEdit(self)
        self._database_path_edit = QLineEdit(self)
        self._database_path_edit.setPlaceholderText(r"Plug-in Support\Databases\com.plexapp.plugins.library.db")
        self._domain_edit = QLineEdit(self)
        self._username_edit = QLineEdit(self)
        self._password_edit = QLineEdit(self)
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)

        layout = QFormLayout(self)
        layout.addRow("Server:", self._server_edit)
        layout.addRow("Port:", self._port_spin)
        layout.addRow("Share name:", self._share_edit)
        layout.addRow("Path within share:", self._database_path_edit)
        layout.addRow("Domain (optional):", self._domain_edit)
        layout.addRow("Username:", self._username_edit)
        layout.addRow("Password:", self._password_edit)

    def to_settings(self) -> ConnectionSettings:
        return SmbConnectionSettings(
            server=self._server_edit.text().strip(),
            port=self._port_spin.value(),
            share=self._share_edit.text().strip(),
            database_path=self._database_path_edit.text().strip(),
            domain=self._domain_edit.text().strip(),
            username=self._username_edit.text().strip(),
        )

    def set_settings(self, settings: ConnectionSettings) -> None:
        if isinstance(settings, SmbConnectionSettings):
            self._server_edit.setText(settings.server)
            self._port_spin.setValue(settings.port)
            self._share_edit.setText(settings.share)
            self._database_path_edit.setText(settings.database_path)
            self._domain_edit.setText(settings.domain)
            self._username_edit.setText(settings.username)

    def password(self) -> str:
        return self._password_edit.text()

    def set_password(self, password: str) -> None:
        self._password_edit.setText(password)


class PlexDiagnosticsConnectionForm(ConnectionFormWidget):
    """Fields for downloading the library database via the Plex diagnostics API."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._host_edit = QLineEdit(self)
        self._host_edit.setPlaceholderText("192.168.1.10 or 192-168-1-10.xxxxx.plex.direct")
        self._port_spin = QSpinBox(self)
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(32400)
        self._use_https_check = QCheckBox("Use HTTPS", self)
        self._token_edit = QLineEdit(self)
        self._token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._token_edit.setPlaceholderText("X-Plex-Token from Plex Web (View XML on a library item)")

        layout = QFormLayout(self)
        layout.addRow("Plex server host:", self._host_edit)
        layout.addRow("Port:", self._port_spin)
        layout.addRow("", self._use_https_check)
        layout.addRow("X-Plex-Token:", self._token_edit)

    def to_settings(self) -> ConnectionSettings:
        return PlexDiagnosticsConnectionSettings(
            host=self._host_edit.text().strip(),
            port=self._port_spin.value(),
            use_https=self._use_https_check.isChecked(),
        )

    def set_settings(self, settings: ConnectionSettings) -> None:
        if isinstance(settings, PlexDiagnosticsConnectionSettings):
            self._host_edit.setText(settings.host)
            self._port_spin.setValue(settings.port)
            self._use_https_check.setChecked(settings.use_https)

    def password(self) -> str:
        return self._token_edit.text()

    def set_password(self, password: str) -> None:
        self._token_edit.setText(password)
