# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

PlexLibrary is a PySide6 desktop app for browsing a Plex TV library from a local copy of the
`com.plexapp.plugins.library.db` SQLite database. The database can be reached via local path, SMB,
SFTP, or the Plex diagnostics API. Optional TMDb metadata (overview, rating, genres, poster, and
per-season/episode data) is shown when a show is expanded, and a TMDb-vs-Plex season count check
runs for every row in the show grid. TMDb results are cached to disk (`services/metadata_cache_service.py`)
and reused across runs unless a hard refresh is requested.

## Commands

```bash
uv sync              # install dependencies
uv run plexlibrary    # run the app (entry point: src/plexlibrary/__main__.py -> plexlibrary.app.main())
uv run mypy src/plexlibrary   # type-check (the only configured static check; no lint/test suite exists)
```

There is no test suite in this repo currently.

## Configuration

| Item | Location |
|------|----------|
| Settings file | `~/.config/PlexLibrary/settings.json` |
| Passwords / TMDb API key | OS keyring (`PlexLibrary` service) — never written to the plain-text settings file |
| Downloaded DB cache | Path from `download_destination` in settings; reused when < 24h old |
| TMDb metadata cache | `~/.config/PlexLibrary/tmdb_cache.json` — keyed by Plex show id, holds show/season/episode data |
| TMDb poster cache | `~/.config/PlexLibrary/tmdb_posters/<tmdb_id>.img` |

Connection types (`models/connection.py`): `local`, `smb`, `sftp`, `plex_diagnostics`.

- Plex diagnostics endpoint: `GET /diagnostics/databases/?X-Plex-Token=...`
- ZIP member name for DB extract: `databaseBackup.db*` (not `com.plexapp.plugins.library.db`)
- TMDb API key is optional — without it the TV grid still works, the metadata panel just shows an
  error when a show is expanded (see README.md for how a user gets a free key)

## Architecture

Three-layer split: `models/` (pydantic data), `services/` (business logic, no Qt), `ui/` (PySide6
widgets). Services take a `SettingsService` in their constructor rather than reading files/keyring
directly, and every network/disk-bound operation in the UI runs on a `QThread` with a `QObject`
worker (`succeeded`/`failed` signals) — follow this pattern for new background work rather than
blocking the UI thread.

Key files:

| File | Role |
|------|------|
| `services/settings_service.py` | JSON settings load/save + keyring credential/API-key storage |
| `services/database_downloader.py` | Fetches the DB file over local/SMB/SFTP/diagnostics transports |
| `services/library_db_service.py` | Read-only SQLite queries against the downloaded DB, freshness check |
| `services/metadata_service.py` | Raw TMDb HTTP calls via stdlib `urllib` (no HTTP dependency): `fetch_show_summary` (show + season list), `fetch_show_full` (+ per-season episode lists), `fetch_poster_bytes` |
| `services/metadata_cache_service.py` | Reads/writes the on-disk TMDb cache (`tmdb_cache.json` + poster files), keyed by Plex show id |
| `services/show_metadata_provider.py` | Cache-aware facade over the two services above — "use saved data unless refresh requested, else fetch and save"; this is what the UI calls, never `TmdbMetadataService` directly |
| `services/ui_layout_state.py` | Qt geometry/header base64 save-restore helpers |
| `ui/main_window.py` | Library combo, hosts the TV tree, saves layout on close |
| `ui/tv_library_tree.py` | Nested show/season/episode grids — the most complex file, see below |
| `ui/show_metadata_panel.py` | TMDb metadata panel shown above the grid |
| `ui/settings_dialog.py` | Connection type forms + destination + TMDb key |
| `ui/connection_forms.py` | Per-connection-type form widgets implementing `ConnectionFormWidget` |
| `models/connection.py` | `AppSettings` (root persisted settings) + discriminated-union connection models |

### Plex SQLite constants (`models/tv.py`, `models/library.py`)

- `metadata_items.metadata_type`: 2 = show, 3 = season, 4 = episode
- `library_sections.section_type`: 2 = TV library

### TV grid (`ui/tv_library_tree.py`)

Three independent `QTableWidget` levels (show → season → episode), each with its own column
headers, lazy-loaded on expand via a background thread:

| Level | Columns |
|-------|---------|
| Show | ▶, ⟳, Show, Year, Seasons, TMDb Seasons, *(blank stretch spacer)* |
| Season | ▶, Season |
| Episode | Episode #, Title, Resolution |

Show table column indices are named constants (`_SHOW_REFRESH_COLUMN`, `_SHOW_NAME_COLUMN`,
`_SHOW_YEAR_COLUMN`, `_SHOW_SEASON_COUNT_COLUMN`, `_SHOW_TMDB_SEASON_COLUMN`, `_SHOW_SPACER_COLUMN`)
— use those rather than hardcoding column numbers if you touch `ShowTableWidget`.

- Expand column fixed at 28px; other columns interactive/movable; expand state uses manual ▶/▼
  text icons, not `QTreeWidgetItem` indicators
- Nested detail rows use `setSpan` + `cellWidget`; since `QTableWidget` doesn't auto-size embedded
  widgets, row height is computed manually via `_fit_table_to_contents` / `sync_geometry` —
  be careful here when changing detail-row content, this is the most fragile part of the file
- Detail row margins: 20px left/right (`_TABLE_HORIZONTAL_MARGIN`)
- Show table's trailing blank column is a stretch spacer (min 20px); `finalize_stretch_column()`
  must be re-applied after `restoreState()` or a saved column layout will remove the stretch
- `ShowTableWidget.show_expanded`/`show_collapsed` signals drive the TMDb metadata panel in
  `TvLibraryTreeWidget` — only the most recently expanded show's metadata is shown

### TMDb season-count column and hard refresh (`ui/tv_library_tree.py`)

- On `set_shows()`, a background `_ShowMetadataFetchWorker` (via `ShowMetadataProvider`) fetches
  each show's TMDb season summary (cache-first) and fills the **TMDb Seasons** column as results
  stream in; skipped entirely when no TMDb API key is configured (`has_api_key()`)
- A row is tinted `_SEASON_MISMATCH_COLOR` (all cells, via `_set_row_mismatch_tint`) when
  `metadata.number_of_seasons != show.season_count`; reset with a bare `QBrush()` so alternating
  row colors resume — don't compare anything other than these two displayed numbers
- Clicking the **⟳** cell (`_SHOW_REFRESH_COLUMN`) calls `_request_hard_refresh`, which re-runs the
  same worker with `force_refresh=True` — this bypasses the cache for that one show only and also
  emits `show_metadata_refreshed`, which `TvLibraryTreeWidget` uses to live-update the detail panel
  if that show is currently expanded (using `ShowMetadataProvider.cached_poster_bytes`, a disk-only
  read — never call `poster_bytes()` from a signal handler running on the GUI thread, it can hit
  the network)
- `_ensure_spacer_column()` is guarded by `self._syncing_spacer_column` against re-entrant calls:
  `resizeSection`/`moveSection` inside `finalize_stretch_column()` can synchronously re-emit
  `sectionResized`/`sectionMoved`, which are wired back into this same method by both
  `_keep_spacer_column_last` and header-state tracking (`bind_header_state_tracking`) — without the
  guard this can cascade deep enough to blow the recursion limit, especially with a stale saved
  header state from before the column count changed

### UI layout persistence

Persisted in `settings.json` under `ui_layout` (`models/ui_layout.py`): window geometry, selected
library id, and three independent `QHeaderView` states (show/season/episode), each base64-encoded
via Qt's `saveGeometry()`/`saveState()`.

- Saved on main window close and before opening Settings (so a Settings save never overwrites
  in-memory layout — `_build_app_settings()` explicitly preserves `existing.ui_layout`)
- Header resize/reorder events update shared state live via `bind_header_state_tracking()`, so
  newly expanded shows/seasons use the current-session layout, not just the layout from startup

### PySide6 gotchas encountered in this codebase

- `QTableWidgetItem.setData()` requires three args: `(column, role, value)`
- `self.layout()` is typed `QLayout | None` by PySide6 stubs even when a layout was just set —
  existing code doesn't guard this everywhere (pre-existing mypy findings, not a pattern to copy)
