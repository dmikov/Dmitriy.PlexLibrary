"""Loads and saves application settings, keeping credentials out of plain-text config."""

from __future__ import annotations

import json
from pathlib import Path

import keyring

from plexlibrary.models.connection import (
    AppSettings,
    ConnectionSettings,
    ConnectionType,
)

APP_NAME = "PlexLibrary"
KEYRING_SERVICE = "PlexLibrary"


class SettingsService:
    """Persists `AppSettings` to a per-user config file and passwords to the OS keyring."""

    def __init__(self, config_dir: Path) -> None:
        self._config_file = config_dir / "settings.json"

    @property
    def config_file(self) -> Path:
        return self._config_file

    def load(self) -> AppSettings:
        if not self._config_file.exists():
            return AppSettings()
        data = json.loads(self._config_file.read_text(encoding="utf-8"))
        return AppSettings.model_validate(data)

    def save(self, settings: AppSettings) -> None:
        self._config_file.parent.mkdir(parents=True, exist_ok=True)
        payload = settings.model_dump_json(indent=2)
        temp_file = self._config_file.with_suffix(".json.tmp")
        temp_file.write_text(payload, encoding="utf-8")
        temp_file.replace(self._config_file)

    def save_credentials(self, connection: ConnectionSettings, secret: str) -> bool:
        """Store connection secrets in the OS keyring. Returns False if keyring storage failed."""
        if connection.type == ConnectionType.LOCAL:
            return True
        try:
            if secret:
                keyring.set_password(KEYRING_SERVICE, connection.credential_key, secret)
            else:
                keyring.delete_password(KEYRING_SERVICE, connection.credential_key)
        except keyring.errors.KeyringError:
            return False
        return True

    def load_password(self, connection: ConnectionSettings) -> str:
        if connection.type == ConnectionType.LOCAL:
            return ""
        try:
            return keyring.get_password(KEYRING_SERVICE, connection.credential_key) or ""
        except keyring.errors.KeyringError:
            return ""

    def save_password(self, connection: ConnectionSettings, password: str) -> None:
        self.save_credentials(connection, password)
