"""Strongly typed models describing how to reach a Plex database file."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from plexlibrary.models.ui_layout import UiLayoutSettings


class ConnectionType(StrEnum):
    """The transport used to reach the Plex database file."""

    LOCAL = "local"
    SMB = "smb"
    SFTP = "sftp"
    PLEX_DIAGNOSTICS = "plex_diagnostics"


class LocalConnectionSettings(BaseModel):
    """A database reachable through the local filesystem (including an already-mounted network share)."""

    type: Literal[ConnectionType.LOCAL] = ConnectionType.LOCAL
    database_path: str = Field(
        default="",
        description="Path to the Plex database file, e.g. a mounted network share or local disk path.",
    )


class SmbConnectionSettings(BaseModel):
    """A database reachable over an SMB/CIFS network share."""

    type: Literal[ConnectionType.SMB] = ConnectionType.SMB
    server: str = Field(default="", description="SMB server hostname or IP address.")
    share: str = Field(default="", description="Name of the shared folder.")
    database_path: str = Field(
        default="",
        description="Path to the database file relative to the root of the share.",
    )
    username: str = ""
    domain: str = ""
    port: int = 445

    @property
    def credential_key(self) -> str:
        return f"smb:{self.username}@{self.server}:{self.port}/{self.share}"


class SftpConnectionSettings(BaseModel):
    """A database reachable over SFTP/SSH."""

    type: Literal[ConnectionType.SFTP] = ConnectionType.SFTP
    host: str = ""
    port: int = 22
    username: str = ""
    remote_database_path: str = Field(
        default="",
        description="Absolute path to the database file on the remote host.",
    )

    @property
    def credential_key(self) -> str:
        return f"sftp:{self.username}@{self.host}:{self.port}"


class PlexDiagnosticsConnectionSettings(BaseModel):
    """A database downloaded from the Plex Media Server diagnostics API."""

    type: Literal[ConnectionType.PLEX_DIAGNOSTICS] = ConnectionType.PLEX_DIAGNOSTICS
    host: str = Field(default="", description="Plex server hostname, IP address, or plex.direct host.")
    port: int = 32400
    use_https: bool = False

    @property
    def credential_key(self) -> str:
        scheme = "https" if self.use_https else "http"
        return f"plex-diagnostics:{scheme}://{self.host}:{self.port}"

    @property
    def base_url(self) -> str:
        scheme = "https" if self.use_https else "http"
        return f"{scheme}://{self.host}:{self.port}"


ConnectionSettings = Annotated[
    Union[
        LocalConnectionSettings,
        SmbConnectionSettings,
        SftpConnectionSettings,
        PlexDiagnosticsConnectionSettings,
    ],
    Field(discriminator="type"),
]
"""Any of the supported connection settings, discriminated by their `type` field."""


class AppSettings(BaseModel):
    """Everything persisted between runs of the application."""

    connection: ConnectionSettings | None = None
    download_destination: str = Field(
        default_factory=lambda: str(Path.home() / "PlexLibrary" / "downloaded" / "com.plexapp.plugins.library.db")
    )
    ui_layout: UiLayoutSettings = Field(default_factory=UiLayoutSettings)
