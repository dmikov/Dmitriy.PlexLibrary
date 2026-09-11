"""Models representing Plex libraries read from the local database file."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LibrarySection(BaseModel):
    """One Plex library section stored in the downloaded database."""

    id: int
    name: str = Field(description="Display name of the library.")
    section_type: int | None = Field(
        default=None,
        description="Plex section type identifier, when present in the database schema.",
    )
