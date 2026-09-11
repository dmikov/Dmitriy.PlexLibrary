"""Persisted window and table layout state."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UiLayoutSettings(BaseModel):
    """Window geometry and independently saved table header layouts."""

    window_geometry: str = Field(
        default="",
        description="Base64-encoded QMainWindow geometry from saveGeometry().",
    )
    selected_library_id: int | None = Field(
        default=None,
        description="Last selected Plex library section id.",
    )
    show_table_header_state: str = Field(
        default="",
        description="Base64-encoded QHeaderView state for the show grid.",
    )
    season_table_header_state: str = Field(
        default="",
        description="Base64-encoded QHeaderView state for the season grid.",
    )
    episode_table_header_state: str = Field(
        default="",
        description="Base64-encoded QHeaderView state for the episode grid.",
    )
