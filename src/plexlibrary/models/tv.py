"""Models for TV show metadata read from a Plex library database."""

from __future__ import annotations

from pydantic import BaseModel, Field

PLEX_SECTION_TYPE_SHOW = 2
PLEX_SECTION_TYPE_SHOW = 2
PLEX_METADATA_TYPE_SHOW = 2
PLEX_METADATA_TYPE_SEASON = 3
PLEX_METADATA_TYPE_EPISODE = 4


class TvShowSummary(BaseModel):
    """Top-level TV series row shown in the library grid."""

    id: int
    name: str
    year: int | None = None
    season_count: int = 0


class TvEpisodeRecord(BaseModel):
    """One episode under a season."""

    id: int
    episode_number: int | None = None
    title: str = ""
    resolution: str = ""


class TvSeasonRecord(BaseModel):
    """One season and its episodes."""

    id: int
    season_number: int | None = None
    episodes: list[TvEpisodeRecord] = Field(default_factory=list)
