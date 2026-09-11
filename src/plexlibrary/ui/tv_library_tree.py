"""Expandable TV show grids with independent tables per hierarchy level."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from plexlibrary.models.library import LibrarySection
from plexlibrary.models.metadata import TvSeasonMetadata, TvShowMetadata
from plexlibrary.models.tv import (
    PLEX_SECTION_TYPE_SHOW,
    TvEpisodeRecord,
    TvSeasonRecord,
    TvShowSummary,
)
from plexlibrary.models.ui_layout import UiLayoutSettings
from plexlibrary.services.library_db_service import LibraryDbError, LibraryDbService
from plexlibrary.services.metadata_service import MetadataError
from plexlibrary.services.show_metadata_provider import ShowMetadataProvider
from plexlibrary.services.ui_layout_state import (
    bind_header_state_tracking,
    finalize_stretch_column,
    restore_header_state,
)
from plexlibrary.ui.show_metadata_panel import ShowMetadataPanel

_SHOW_HEADERS = ["", "⟳", "Show", "Year", "Seasons", "TMDb Seasons", ""]
_SHOW_REFRESH_COLUMN = 1
_SHOW_NAME_COLUMN = 2
_SHOW_YEAR_COLUMN = 3
_SHOW_SEASON_COUNT_COLUMN = 4
_SHOW_TMDB_SEASON_COLUMN = 5
_SHOW_SPACER_COLUMN = len(_SHOW_HEADERS) - 1
_SEASON_MISMATCH_COLOR = QColor(54, 35, 0)
_SEASON_HEADERS = ["", "Season", "Episodes", "TMDb Episodes"]
_SEASON_EXPAND_COLUMN = 0
_SEASON_NAME_COLUMN = 1
_SEASON_EPISODE_COUNT_COLUMN = 2
_SEASON_TMDB_EPISODE_COLUMN = 3
_EPISODE_MISMATCH_TEXT_COLOR = QColor(255, 140, 0)
_EPISODE_HEADERS = ["Episode #", "Title", "Resolution"]
_TABLE_HORIZONTAL_MARGIN = 20
_HEADER_STYLESHEET = """
QHeaderView::section {
    background-color: #1976D2;
    color: #FFFFFF;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #1565C0;
    border-bottom: 1px solid #1565C0;
    font-weight: bold;
}
QHeaderView::section:hover {
    background-color: #1565C0;
}
"""
_SHOW_TABLE_STYLESHEET = (
    _HEADER_STYLESHEET
    + """
QTableWidget QHeaderView::section:last {
    background-color: transparent;
    border: none;
}
"""
)
_EXPAND_COLUMN_WIDTH = 28
_DETAIL_MARGINS = (_TABLE_HORIZONTAL_MARGIN, 4, _TABLE_HORIZONTAL_MARGIN, 8)
_DEFAULT_ROW_HEIGHT = 30


def _fit_table_to_contents(table: QTableWidget) -> int:
    """Size a nested table to its rows and return the pixel height it needs."""

    table.resizeRowsToContents()
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    if table.rowCount() == 0:
        height = table.horizontalHeader().height() + table.frameWidth() * 2
    else:
        height = table.horizontalHeader().height() + table.frameWidth() * 2
        for row in range(table.rowCount()):
            height += max(table.rowHeight(row), _DEFAULT_ROW_HEIGHT)

    table.setFixedHeight(height)
    return height


def _detail_container_height(content_height: int) -> int:
    top, _, _, bottom = _DETAIL_MARGINS
    return content_height + top + bottom


def _wrap_detail_widget(parent: QWidget, widget: QWidget) -> tuple[QWidget, int]:
    container = QWidget(parent)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(*_DETAIL_MARGINS)
    layout.setSpacing(0)
    layout.addWidget(widget)
    content_height = widget.height() if widget.height() > 0 else widget.sizeHint().height()
    total_height = _detail_container_height(content_height)
    container.setFixedHeight(total_height)
    return container, total_height


def _expand_icon(expanded: bool) -> str:
    return "▼" if expanded else "▶"


def _configure_material_table(
    table: QTableWidget,
    headers: list[str],
    default_widths: list[int],
    *,
    fixed_expand_column: bool = False,
    extra_fixed_columns: tuple[int, ...] = (),
    stretch_column: int | None = None,
    stretch_column_min_width: int = _TABLE_HORIZONTAL_MARGIN,
    header_state: str = "",
    table_stylesheet: str = _HEADER_STYLESHEET,
) -> None:
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setStyleSheet(table_stylesheet)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.setShowGrid(True)

    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setSectionsMovable(True)
    if stretch_column is not None:
        header.setMinimumSectionSize(stretch_column_min_width)
    else:
        header.setMinimumSectionSize(40)
    header.setDefaultSectionSize(120)
    for column in range(len(headers)):
        if stretch_column is not None and column == stretch_column:
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
            table.setColumnWidth(column, stretch_column_min_width)
        elif fixed_expand_column and column == 0:
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(column, _EXPAND_COLUMN_WIDTH)
        elif column in extra_fixed_columns:
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(column, _EXPAND_COLUMN_WIDTH)
        else:
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
    for column, width in enumerate(default_widths):
        if fixed_expand_column and column == 0:
            continue
        if column in extra_fixed_columns:
            continue
        if stretch_column is not None and column == stretch_column:
            continue
        table.setColumnWidth(column, width)
    restore_header_state(header, header_state)
    if stretch_column is not None:
        finalize_stretch_column(header, stretch_column, stretch_column_min_width)


def _make_blank_spacer_item() -> QTableWidgetItem:
    item = _make_item("", selectable=False)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
    return item


def _make_item(text: str, *, selectable: bool = True) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if not selectable:
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
    return item


def _make_refresh_item() -> QTableWidgetItem:
    item = _make_item("⟳")
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    item.setToolTip("Hard refresh TMDb data for this show")
    return item


def _shift_expanded_rows(expanded_rows: dict[int, int], pivot: int, delta: int) -> None:
    updated: dict[int, int] = {}
    for key, detail_row in expanded_rows.items():
        new_key = key + delta if key > pivot else key
        new_detail = detail_row + delta if detail_row > pivot else detail_row
        updated[new_key] = new_detail
    expanded_rows.clear()
    expanded_rows.update(updated)


class EpisodeTableWidget(QTableWidget):
    """Episode grid with its own three-column header."""

    def __init__(
        self,
        episodes: list[TvEpisodeRecord],
        parent: QWidget | None = None,
        *,
        header_state: str = "",
        on_header_state_changed: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        _configure_material_table(self, _EPISODE_HEADERS, [90, 360, 140], header_state=header_state)
        if on_header_state_changed is not None:
            bind_header_state_tracking(self.horizontalHeader(), on_header_state_changed)
        self.setRowCount(len(episodes))
        for row, episode in enumerate(episodes):
            episode_number = str(episode.episode_number) if episode.episode_number is not None else ""
            self.setItem(row, 0, _make_item(episode_number, selectable=False))
            self.setItem(row, 1, _make_item(episode.title, selectable=False))
            self.setItem(row, 2, _make_item(episode.resolution, selectable=False))
        _fit_table_to_contents(self)


class SeasonTableWidget(QTableWidget):
    """Season grid with expandable episode tables underneath each season."""

    def __init__(
        self,
        seasons: list[TvSeasonRecord],
        parent: QWidget | None = None,
        *,
        on_geometry_changed: Callable[[], None] | None = None,
        header_state: str = "",
        episode_header_state: str = "",
        on_season_header_state_changed: Callable[[str], None] | None = None,
        on_episode_header_state_changed: Callable[[str], None] | None = None,
        tmdb_seasons: dict[int, TvSeasonMetadata] | None = None,
    ) -> None:
        super().__init__(parent)
        self._seasons = seasons
        self._expanded_rows: dict[int, int] = {}
        self._on_geometry_changed = on_geometry_changed
        self._episode_header_state = episode_header_state
        self._on_season_header_state_changed = on_season_header_state_changed
        self._on_episode_header_state_changed = on_episode_header_state_changed
        self._tmdb_seasons = tmdb_seasons
        _configure_material_table(
            self,
            _SEASON_HEADERS,
            [_EXPAND_COLUMN_WIDTH, 220, 90, 130],
            fixed_expand_column=True,
            header_state=header_state,
        )
        if on_season_header_state_changed is not None:
            bind_header_state_tracking(self.horizontalHeader(), on_season_header_state_changed)
        self.cellClicked.connect(self._on_cell_clicked)
        self._populate()
        self.sync_geometry()

    def _populate(self) -> None:
        self.setRowCount(len(self._seasons))
        for row, season in enumerate(self._seasons):
            if season.episodes:
                self.setItem(row, _SEASON_EXPAND_COLUMN, _make_item(_expand_icon(False)))
            else:
                self.setItem(row, _SEASON_EXPAND_COLUMN, _make_item("", selectable=False))
            season_label = (
                f"Season {season.season_number}" if season.season_number is not None else "Season"
            )
            name_item = _make_item(season_label, selectable=False)
            name_item.setData(Qt.ItemDataRole.UserRole, season.id)
            self.setItem(row, _SEASON_NAME_COLUMN, name_item)
            self._apply_row_episode_metadata(row, season)

    def update_tmdb_seasons(self, tmdb_seasons: dict[int, TvSeasonMetadata]) -> None:
        """Refresh the TMDb episode-count column (and mismatch tint) once TMDb data arrives."""
        self._tmdb_seasons = tmdb_seasons
        for season in self._seasons:
            row = self._find_row_for_season(season.id)
            if row is not None:
                self._apply_row_episode_metadata(row, season)

    def _apply_row_episode_metadata(self, row: int, season: TvSeasonRecord) -> None:
        plex_count = len(season.episodes)
        self.setItem(row, _SEASON_EPISODE_COUNT_COLUMN, _make_item(str(plex_count), selectable=False))

        tmdb_season = (
            self._tmdb_seasons.get(season.season_number)
            if self._tmdb_seasons is not None and season.season_number is not None
            else None
        )
        tmdb_item = _make_item("", selectable=False)
        if tmdb_season is not None:
            tmdb_item.setText(str(tmdb_season.episode_count))
        elif self._tmdb_seasons is not None:
            tmdb_item.setText("?")
            tmdb_item.setToolTip("TMDb has no matching season.")
        else:
            tmdb_item.setText("…")
        self.setItem(row, _SEASON_TMDB_EPISODE_COLUMN, tmdb_item)

        mismatch = self._tmdb_seasons is not None and (
            tmdb_season is None or tmdb_season.episode_count != plex_count
        )
        self._set_row_episode_mismatch(row, mismatch)

    def _set_row_episode_mismatch(self, row: int, mismatch: bool) -> None:
        brush = QBrush(_EPISODE_MISMATCH_TEXT_COLOR) if mismatch else QBrush()
        for column in (
            _SEASON_EXPAND_COLUMN,
            _SEASON_NAME_COLUMN,
            _SEASON_EPISODE_COUNT_COLUMN,
            _SEASON_TMDB_EPISODE_COLUMN,
        ):
            item = self.item(row, column)
            if item is not None:
                item.setForeground(brush)

    def _season_for_row(self, row: int) -> TvSeasonRecord | None:
        name_item = self.item(row, _SEASON_NAME_COLUMN)
        if name_item is None:
            return None
        season_id = name_item.data(Qt.ItemDataRole.UserRole)
        if season_id is None:
            return None
        for season in self._seasons:
            if season.id == season_id:
                return season
        return None

    def _find_row_for_season(self, season_id: int) -> int | None:
        for row in range(self.rowCount()):
            name_item = self.item(row, _SEASON_NAME_COLUMN)
            if name_item is None:
                continue
            if name_item.data(Qt.ItemDataRole.UserRole) == season_id:
                return row
        return None

    def _on_cell_clicked(self, row: int, column: int) -> None:
        if column != _SEASON_EXPAND_COLUMN:
            return
        season = self._season_for_row(row)
        if season is None or not season.episodes:
            return
        if row in self._expanded_rows:
            self._collapse_row(row)
        else:
            self._expand_row(row, season)

    def sync_geometry(self) -> None:
        self.resizeRowsToContents()
        for row in range(self.rowCount()):
            if row not in self._expanded_rows.values():
                self.setRowHeight(row, max(self.rowHeight(row), _DEFAULT_ROW_HEIGHT))

        for detail_row in self._expanded_rows.values():
            container = self.cellWidget(detail_row, 0)
            if container is None:
                continue
            episode_table = container.findChild(EpisodeTableWidget)
            if episode_table is not None:
                content_height = _fit_table_to_contents(episode_table)
                total_height = _detail_container_height(content_height)
                container.setFixedHeight(total_height)
                self.setRowHeight(detail_row, total_height)

        total_height = self.horizontalHeader().height() + self.frameWidth() * 2
        for row in range(self.rowCount()):
            total_height += self.rowHeight(row)
        self.setFixedHeight(total_height)

        if self._on_geometry_changed is not None:
            self._on_geometry_changed()

    def _handle_episode_header_changed(self, state: str) -> None:
        self._episode_header_state = state
        if self._on_episode_header_state_changed is not None:
            self._on_episode_header_state_changed(state)

    def _expand_row(self, data_row: int, season: TvSeasonRecord) -> None:
        _shift_expanded_rows(self._expanded_rows, data_row, 1)
        insert_row = data_row + 1
        self.insertRow(insert_row)

        episode_table = EpisodeTableWidget(
            season.episodes,
            self,
            header_state=self._episode_header_state,
            on_header_state_changed=self._handle_episode_header_changed,
        )
        _set_detail_row_widget(self, insert_row, episode_table)

        self._expanded_rows[data_row] = insert_row
        expand_item = self.item(data_row, 0)
        if expand_item is not None:
            expand_item.setText(_expand_icon(True))
        self.sync_geometry()

    def _collapse_row(self, data_row: int) -> None:
        detail_row = self._expanded_rows.pop(data_row)
        self.removeRow(detail_row)
        _shift_expanded_rows(self._expanded_rows, data_row, -1)
        expand_item = self.item(data_row, 0)
        if expand_item is not None:
            expand_item.setText(_expand_icon(False))
        self.sync_geometry()


def _set_detail_row_widget(table: QTableWidget, detail_row: int, widget: QWidget) -> None:
    if isinstance(widget, SeasonTableWidget):
        widget.sync_geometry()
        content_height = widget.height()
    elif isinstance(widget, QTableWidget):
        content_height = _fit_table_to_contents(widget)
    else:
        widget.adjustSize()
        content_height = max(widget.sizeHint().height(), _DEFAULT_ROW_HEIGHT)

    container, total_height = _wrap_detail_widget(table, widget)
    table.setSpan(detail_row, 0, 1, table.columnCount())
    table.setCellWidget(detail_row, 0, container)
    table.setRowHeight(detail_row, total_height)


class _TvShowDetailsWorker(QObject):
    succeeded = Signal(int, list)
    failed = Signal(int, str)

    def __init__(self, library_db_service: LibraryDbService, show_id: int, db_path: Path) -> None:
        super().__init__()
        self._library_db_service = library_db_service
        self._show_id = show_id
        self._db_path = db_path

    def run(self) -> None:
        try:
            seasons = self._library_db_service.get_show_seasons_and_episodes(self._show_id, self._db_path)
        except LibraryDbError as exc:
            self.failed.emit(self._show_id, str(exc))
        except Exception as exc:
            self.failed.emit(self._show_id, f"Unexpected error: {exc}")
        else:
            self.succeeded.emit(self._show_id, seasons)


class _ShowMetadataPanelWorker(QObject):
    """Loads full TMDb metadata (and poster art) for the show detail panel."""

    succeeded = Signal(int, object, object)
    failed = Signal(int, str)

    def __init__(
        self,
        provider: ShowMetadataProvider,
        show: TvShowSummary,
        *,
        force_refresh: bool = False,
    ) -> None:
        super().__init__()
        self._provider = provider
        self._show = show
        self._force_refresh = force_refresh

    def run(self) -> None:
        try:
            metadata = self._provider.get_full_metadata(
                self._show.id, self._show.name, self._show.year, force_refresh=self._force_refresh
            )
        except MetadataError as exc:
            self.failed.emit(self._show.id, str(exc))
            return
        except Exception as exc:
            self.failed.emit(self._show.id, f"Unexpected error: {exc}")
            return

        poster_bytes = self._provider.poster_bytes(metadata, force_refresh=self._force_refresh)
        self.succeeded.emit(self._show.id, metadata, poster_bytes)


class _ShowMetadataFetchWorker(QObject):
    """Fetches (cache-aware) TMDb metadata for the show grid columns.

    Used both for the bulk season-count sweep run after loading a library (`force_refresh=False`,
    many shows) and for a single row's hard refresh (`force_refresh=True`, one show).
    """

    show_ready = Signal(int, object)
    show_failed = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        provider: ShowMetadataProvider,
        shows: list[TvShowSummary],
        *,
        force_refresh: bool = False,
    ) -> None:
        super().__init__()
        self._provider = provider
        self._shows = shows
        self._force_refresh = force_refresh

    def run(self) -> None:
        for show in self._shows:
            try:
                if self._force_refresh:
                    metadata = self._provider.get_full_metadata(
                        show.id, show.name, show.year, force_refresh=True
                    )
                else:
                    metadata = self._provider.get_season_summary(show.id, show.name, show.year)
            except MetadataError as exc:
                self.show_failed.emit(show.id, str(exc))
            except Exception as exc:
                self.show_failed.emit(show.id, f"Unexpected error: {exc}")
            else:
                self.show_ready.emit(show.id, metadata)
        self.finished.emit()


class ShowTableWidget(QTableWidget):
    """Top-level show grid; expanding a row embeds an independent season table."""

    show_expanded = Signal(object)
    show_collapsed = Signal(int)
    show_metadata_refreshed = Signal(int, object)

    def __init__(
        self,
        library_db_service: LibraryDbService,
        db_path: Path,
        parent: QWidget | None = None,
        *,
        show_header_state: str = "",
        season_header_state: str = "",
        episode_header_state: str = "",
        on_layout_changed: Callable[[], None] | None = None,
        metadata_provider: ShowMetadataProvider | None = None,
    ) -> None:
        super().__init__(parent)
        self._library_db_service = library_db_service
        self._db_path = db_path
        self._metadata_provider = metadata_provider
        self._shows: list[TvShowSummary] = []
        self._expanded_rows: dict[int, int] = {}
        self._detail_threads: dict[int, QThread] = {}
        self._detail_workers: dict[int, _TvShowDetailsWorker] = {}
        self._show_metadata: dict[int, TvShowMetadata] = {}
        self._summary_thread: QThread | None = None
        self._summary_worker: _ShowMetadataFetchWorker | None = None
        self._refresh_threads: dict[int, QThread] = {}
        self._refresh_workers: dict[int, _ShowMetadataFetchWorker] = {}
        self._show_header_state = show_header_state
        self._season_header_state = season_header_state
        self._episode_header_state = episode_header_state
        self._on_layout_changed = on_layout_changed
        self._syncing_spacer_column = False
        _configure_material_table(
            self,
            _SHOW_HEADERS,
            [_EXPAND_COLUMN_WIDTH, _EXPAND_COLUMN_WIDTH, 420, 70, 90, 130, _TABLE_HORIZONTAL_MARGIN],
            fixed_expand_column=True,
            extra_fixed_columns=(_SHOW_REFRESH_COLUMN,),
            stretch_column=_SHOW_SPACER_COLUMN,
            header_state=show_header_state,
            table_stylesheet=_SHOW_TABLE_STYLESHEET,
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = self.horizontalHeader()
        header.sectionMoved.connect(self._keep_spacer_column_last)
        bind_header_state_tracking(self.horizontalHeader(), self._handle_show_header_changed)
        self.cellClicked.connect(self._on_cell_clicked)
        self._ensure_spacer_column()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._ensure_spacer_column()

    def _keep_spacer_column_last(
        self,
        logical_index: int,
        old_visual_index: int,
        new_visual_index: int,
    ) -> None:
        del logical_index, old_visual_index, new_visual_index
        self._ensure_spacer_column()

    def _ensure_spacer_column(self) -> None:
        # resizeSection()/moveSection() below can synchronously re-emit sectionResized/sectionMoved,
        # which are wired back into this same method (via _keep_spacer_column_last and header-state
        # tracking); guard against that re-entrancy so a stubborn header can't cascade indefinitely.
        if self._syncing_spacer_column:
            return
        self._syncing_spacer_column = True
        try:
            finalize_stretch_column(
                self.horizontalHeader(),
                _SHOW_SPACER_COLUMN,
                _TABLE_HORIZONTAL_MARGIN,
            )
        finally:
            self._syncing_spacer_column = False

    def show_header_state(self) -> str:
        return self._show_header_state

    def season_header_state(self) -> str:
        return self._season_header_state

    def episode_header_state(self) -> str:
        return self._episode_header_state

    def _notify_layout_changed(self) -> None:
        if self._on_layout_changed is not None:
            self._on_layout_changed()

    def _handle_show_header_changed(self, state: str) -> None:
        self._show_header_state = state
        self._ensure_spacer_column()
        self._notify_layout_changed()

    def _handle_season_header_changed(self, state: str) -> None:
        self._season_header_state = state
        self._notify_layout_changed()

    def _handle_episode_header_changed(self, state: str) -> None:
        self._episode_header_state = state
        self._notify_layout_changed()

    def set_shows(self, shows: list[TvShowSummary]) -> None:
        self.clear_workers()
        self._expanded_rows.clear()
        self._shows = shows
        has_api_key = self._metadata_provider is not None and self._metadata_provider.has_api_key()
        self.setRowCount(len(shows))
        for row, show in enumerate(shows):
            self.setItem(row, 0, _make_item(_expand_icon(False)))
            self.setItem(row, _SHOW_REFRESH_COLUMN, _make_refresh_item())
            name_item = _make_item(show.name, selectable=False)
            name_item.setData(Qt.ItemDataRole.UserRole, show.id)
            self.setItem(row, _SHOW_NAME_COLUMN, name_item)
            year = str(show.year) if show.year is not None else ""
            self.setItem(row, _SHOW_YEAR_COLUMN, _make_item(year, selectable=False))
            self.setItem(row, _SHOW_SEASON_COUNT_COLUMN, _make_item(str(show.season_count), selectable=False))
            placeholder = "…" if has_api_key else "—"
            self.setItem(row, _SHOW_TMDB_SEASON_COLUMN, _make_item(placeholder, selectable=False))
            self.setItem(row, _SHOW_SPACER_COLUMN, _make_blank_spacer_item())
        self._ensure_spacer_column()
        self._start_season_summary_load()

    def _show_for_row(self, row: int) -> TvShowSummary | None:
        name_item = self.item(row, _SHOW_NAME_COLUMN)
        if name_item is None:
            return None
        show_id = name_item.data(Qt.ItemDataRole.UserRole)
        if show_id is None:
            return None
        for show in self._shows:
            if show.id == show_id:
                return show
        return None

    def clear_workers(self) -> None:
        for thread in self._detail_threads.values():
            if thread.isRunning():
                thread.quit()
                thread.wait()
        self._detail_threads.clear()
        self._detail_workers.clear()

        self._stop_summary_thread()

        for thread in self._refresh_threads.values():
            if thread.isRunning():
                thread.quit()
                thread.wait()
        self._refresh_threads.clear()
        self._refresh_workers.clear()

    def _find_row_for_show(self, show_id: int) -> int | None:
        for row in range(self.rowCount()):
            name_item = self.item(row, _SHOW_NAME_COLUMN)
            if name_item is None:
                continue
            if name_item.data(Qt.ItemDataRole.UserRole) == show_id:
                return row
        return None

    def _on_cell_clicked(self, row: int, column: int) -> None:
        if column == _SHOW_REFRESH_COLUMN:
            self._request_hard_refresh(row)
            return
        if column != 0 or self._show_for_row(row) is None:
            return
        if row in self._expanded_rows:
            self._collapse_row(row)
        else:
            self._expand_row(row)

    def _start_season_summary_load(self) -> None:
        self._stop_summary_thread()
        if self._metadata_provider is None or not self._metadata_provider.has_api_key():
            return
        if not self._shows:
            return

        self._summary_thread = QThread(self)
        self._summary_worker = _ShowMetadataFetchWorker(self._metadata_provider, list(self._shows))
        self._summary_worker.moveToThread(self._summary_thread)
        self._summary_thread.started.connect(self._summary_worker.run)
        self._summary_worker.show_ready.connect(self._on_show_metadata_ready)
        self._summary_worker.show_failed.connect(self._on_show_metadata_failed)
        self._summary_worker.finished.connect(self._summary_thread.quit)
        self._summary_thread.finished.connect(self._cleanup_summary_thread)
        self._summary_thread.start()

    def _stop_summary_thread(self) -> None:
        if self._summary_thread is not None and self._summary_thread.isRunning():
            self._summary_thread.quit()
            self._summary_thread.wait()
        self._summary_thread = None
        self._summary_worker = None

    def _cleanup_summary_thread(self) -> None:
        if self._summary_thread is not None:
            self._summary_thread.wait()
        self._summary_thread = None
        self._summary_worker = None

    def _request_hard_refresh(self, row: int) -> None:
        show = self._show_for_row(row)
        if show is None or self._metadata_provider is None:
            return
        existing_thread = self._refresh_threads.get(show.id)
        if existing_thread is not None and existing_thread.isRunning():
            return

        item = self.item(row, _SHOW_TMDB_SEASON_COLUMN)
        if item is not None:
            item.setText("…")
            item.setToolTip("Refreshing from TMDb…")

        thread = QThread(self)
        worker = _ShowMetadataFetchWorker(self._metadata_provider, [show], force_refresh=True)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.show_ready.connect(self._on_show_metadata_ready)
        worker.show_failed.connect(self._on_show_metadata_failed)
        worker.finished.connect(thread.quit)
        thread.finished.connect(lambda show_id=show.id: self._cleanup_refresh_thread(show_id))
        self._refresh_threads[show.id] = thread
        self._refresh_workers[show.id] = worker
        thread.start()

    def _cleanup_refresh_thread(self, show_id: int) -> None:
        thread = self._refresh_threads.pop(show_id, None)
        self._refresh_workers.pop(show_id, None)
        if thread is not None:
            thread.wait()

    def _on_show_metadata_ready(self, show_id: int, metadata: TvShowMetadata) -> None:
        self.update_show_metadata(show_id, metadata)
        self.show_metadata_refreshed.emit(show_id, metadata)

    def update_show_metadata(self, show_id: int, metadata: TvShowMetadata) -> None:
        """Apply freshly fetched TMDb metadata to the show row and, if expanded, its season grid."""
        self._show_metadata[show_id] = metadata
        self._apply_tmdb_season_metadata(show_id, metadata)
        season_table = self._season_table_for_show(show_id)
        if season_table is not None:
            tmdb_seasons = {
                season.season_number: season for season in metadata.seasons if season.season_number is not None
            }
            season_table.update_tmdb_seasons(tmdb_seasons)

    def _season_table_for_show(self, show_id: int) -> SeasonTableWidget | None:
        data_row = self._find_row_for_show(show_id)
        if data_row is None:
            return None
        detail_row = self._expanded_rows.get(data_row)
        if detail_row is None:
            return None
        container = self.cellWidget(detail_row, 0)
        if container is None:
            return None
        return container.findChild(SeasonTableWidget)

    def _on_show_metadata_failed(self, show_id: int, message: str) -> None:
        row = self._find_row_for_show(show_id)
        if row is None:
            return
        item = self.item(row, _SHOW_TMDB_SEASON_COLUMN)
        if item is not None:
            item.setText("?")
            item.setToolTip(message)

    def _apply_tmdb_season_metadata(self, show_id: int, metadata: TvShowMetadata) -> None:
        row = self._find_row_for_show(show_id)
        if row is None:
            return
        show = self._show_for_row(row)

        item = self.item(row, _SHOW_TMDB_SEASON_COLUMN)
        if item is None:
            item = _make_item("", selectable=False)
            self.setItem(row, _SHOW_TMDB_SEASON_COLUMN, item)
        tmdb_count = metadata.number_of_seasons
        item.setText(str(tmdb_count) if tmdb_count is not None else "?")
        season_numbers = metadata.season_numbers
        item.setToolTip(
            "TMDb seasons: " + ", ".join(str(number) for number in season_numbers) if season_numbers else ""
        )

        mismatch = show is not None and tmdb_count is not None and tmdb_count != show.season_count
        self._set_row_mismatch_tint(row, mismatch)

    def _set_row_mismatch_tint(self, row: int, mismatch: bool) -> None:
        brush = QBrush(_SEASON_MISMATCH_COLOR) if mismatch else QBrush()
        for column in range(self.columnCount()):
            item = self.item(row, column)
            if item is not None:
                item.setBackground(brush)

    def _expand_row(self, data_row: int) -> None:
        show = self._show_for_row(data_row)
        if show is None:
            return
        _shift_expanded_rows(self._expanded_rows, data_row, 1)
        insert_row = data_row + 1
        self.insertRow(insert_row)

        loading_label = QLabel("Loading seasons…", self)
        loading_label.setContentsMargins(8, 8, 8, 8)
        _set_detail_row_widget(self, insert_row, loading_label)

        self._expanded_rows[data_row] = insert_row
        expand_item = self.item(data_row, 0)
        if expand_item is not None:
            expand_item.setText(_expand_icon(True))

        self.show_expanded.emit(show)

        if show.id in self._detail_threads and self._detail_threads[show.id].isRunning():
            return

        thread = QThread(self)
        worker = _TvShowDetailsWorker(self._library_db_service, show.id, self._db_path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_show_details_loaded)
        worker.failed.connect(self._on_show_details_failed)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(lambda show_id=show.id: self._cleanup_detail_thread(show_id))
        self._detail_threads[show.id] = thread
        self._detail_workers[show.id] = worker
        thread.start()

    def _collapse_row(self, data_row: int) -> None:
        show = self._show_for_row(data_row)
        if show is None:
            return
        detail_row = self._expanded_rows.pop(data_row)
        self.removeRow(detail_row)
        _shift_expanded_rows(self._expanded_rows, data_row, -1)
        expand_item = self.item(data_row, 0)
        if expand_item is not None:
            expand_item.setText(_expand_icon(False))

        thread = self._detail_threads.pop(show.id, None)
        self._detail_workers.pop(show.id, None)
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait()

        self.show_collapsed.emit(show.id)

    def _replace_detail_widget(self, data_row: int, widget: QWidget) -> None:
        detail_row = self._expanded_rows.get(data_row)
        if detail_row is None:
            return

        _set_detail_row_widget(self, detail_row, widget)
        self._sync_detail_row(data_row)

    def _sync_detail_row(self, data_row: int) -> None:
        detail_row = self._expanded_rows.get(data_row)
        if detail_row is None:
            return

        container = self.cellWidget(detail_row, 0)
        if container is None:
            return

        nested_table = container.findChild(QTableWidget)
        if nested_table is not None:
            content_height = nested_table.height()
        else:
            content_height = container.sizeHint().height()

        total_height = _detail_container_height(content_height)
        container.setFixedHeight(total_height)
        self.setRowHeight(detail_row, total_height)

    def _on_show_details_loaded(self, show_id: int, seasons: list[TvSeasonRecord]) -> None:
        data_row = self._find_row_for_show(show_id)
        if data_row is None or data_row not in self._expanded_rows:
            return
        if seasons:
            show_metadata = self._show_metadata.get(show_id)
            tmdb_seasons = (
                {
                    season.season_number: season
                    for season in show_metadata.seasons
                    if season.season_number is not None
                }
                if show_metadata is not None
                else None
            )
            season_table = SeasonTableWidget(
                seasons,
                self,
                on_geometry_changed=lambda row=data_row: self._sync_detail_row(row),
                header_state=self._season_header_state,
                episode_header_state=self._episode_header_state,
                on_season_header_state_changed=self._handle_season_header_changed,
                on_episode_header_state_changed=self._handle_episode_header_changed,
                tmdb_seasons=tmdb_seasons,
            )
            self._replace_detail_widget(data_row, season_table)
        else:
            self._replace_detail_widget(data_row, QLabel("No seasons found.", self))

    def _on_show_details_failed(self, show_id: int, message: str) -> None:
        data_row = self._find_row_for_show(show_id)
        if data_row is None or data_row not in self._expanded_rows:
            return
        self._replace_detail_widget(data_row, QLabel(message, self))

    def _cleanup_detail_thread(self, show_id: int) -> None:
        thread = self._detail_threads.pop(show_id, None)
        self._detail_workers.pop(show_id, None)
        if thread is not None:
            thread.wait()


class _TvShowLoadWorker(QObject):
    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        library_db_service: LibraryDbService,
        library_section_id: int,
        db_path: Path,
        sort_by: str,
        sort_desc: bool,
    ) -> None:
        super().__init__()
        self._library_db_service = library_db_service
        self._library_section_id = library_section_id
        self._db_path = db_path
        self._sort_by = sort_by
        self._sort_desc = sort_desc

    def run(self) -> None:
        try:
            shows = self._library_db_service.list_tv_shows(
                self._library_section_id,
                self._db_path,
                sort_by=self._sort_by,
                sort_desc=self._sort_desc,
            )
        except LibraryDbError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Unexpected error: {exc}")
        else:
            self.succeeded.emit(shows)


class TvLibraryTreeWidget(QWidget):
    """TV library view with independently columned tables for shows, seasons, and episodes."""

    _SORT_COLUMNS = {
        _SHOW_NAME_COLUMN: "name",
        _SHOW_YEAR_COLUMN: "year",
        _SHOW_SEASON_COUNT_COLUMN: "seasons",
    }

    def __init__(
        self,
        library_db_service: LibraryDbService,
        parent: QWidget | None = None,
        *,
        layout_settings: UiLayoutSettings | None = None,
        metadata_provider: ShowMetadataProvider | None = None,
    ) -> None:
        super().__init__(parent)
        self._library_db_service = library_db_service
        self._metadata_provider = metadata_provider
        self._layout_settings = layout_settings or UiLayoutSettings()
        self._db_path: Path | None = None
        self._current_library: LibrarySection | None = None
        self._sort_by = "name"
        self._sort_desc = False
        self._show_thread: QThread | None = None
        self._show_worker: _TvShowLoadWorker | None = None
        self._show_table: ShowTableWidget | None = None
        self._metadata_thread: QThread | None = None
        self._metadata_worker: _ShowMetadataPanelWorker | None = None
        self._metadata_show_id: int | None = None

        self._placeholder = QLabel("Select a TV Shows library to view series.", self)
        self._metadata_panel = ShowMetadataPanel(self)
        self._metadata_panel.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._placeholder)
        layout.addWidget(self._metadata_panel)

    def set_layout_settings(self, layout_settings: UiLayoutSettings) -> None:
        self._layout_settings = layout_settings

    def _sync_layout_to_settings(self) -> None:
        if self._show_table is None:
            return
        self._layout_settings.show_table_header_state = self._show_table.show_header_state()
        self._layout_settings.season_table_header_state = self._show_table.season_header_state()
        self._layout_settings.episode_table_header_state = self._show_table.episode_header_state()

    def save_layout_state(self) -> None:
        self._sync_layout_to_settings()

    def set_database_path(self, db_path: Path) -> None:
        self._db_path = db_path

    def load_library(self, library: LibrarySection | None) -> None:
        self._current_library = library
        self._destroy_show_table()

        if library is None or not self._is_tv_library(library) or self._db_path is None:
            self._placeholder.setText("Select a TV Shows library to view series.")
            self._placeholder.show()
            return

        self._placeholder.setText("Loading TV shows…")
        self._placeholder.show()
        self._start_show_load()

    def _is_tv_library(self, library: LibrarySection) -> bool:
        return library.section_type == PLEX_SECTION_TYPE_SHOW

    def _destroy_show_table(self) -> None:
        self._stop_metadata_thread()
        self._metadata_panel.hide()
        self._metadata_show_id = None
        if self._show_table is not None:
            self._show_table.clear_workers()
            self._show_table.hide()
            self._show_table.deleteLater()
            self._show_table = None

    def _ensure_show_table(self) -> ShowTableWidget:
        if self._db_path is None:
            raise LibraryDbError("Database path is not configured.")
        if self._show_table is None:
            self._show_table = ShowTableWidget(
                self._library_db_service,
                self._db_path,
                self,
                show_header_state=self._layout_settings.show_table_header_state,
                season_header_state=self._layout_settings.season_table_header_state,
                episode_header_state=self._layout_settings.episode_table_header_state,
                on_layout_changed=self._sync_layout_to_settings,
                metadata_provider=self._metadata_provider,
            )
            self._show_table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
            self._show_table.show_expanded.connect(self._on_show_expanded)
            self._show_table.show_collapsed.connect(self._on_show_collapsed)
            self._show_table.show_metadata_refreshed.connect(self._on_show_metadata_refreshed)
            self.layout().addWidget(self._show_table)
        return self._show_table

    def _on_show_expanded(self, show: TvShowSummary) -> None:
        self._metadata_show_id = show.id
        self._metadata_panel.set_loading()
        self._metadata_panel.show()

        if self._metadata_provider is None:
            self._metadata_panel.set_error("No metadata service configured.")
            return

        self._stop_metadata_thread()
        self._metadata_thread = QThread(self)
        self._metadata_worker = _ShowMetadataPanelWorker(self._metadata_provider, show)
        self._metadata_worker.moveToThread(self._metadata_thread)
        self._metadata_thread.started.connect(self._metadata_worker.run)
        self._metadata_worker.succeeded.connect(self._on_metadata_loaded)
        self._metadata_worker.failed.connect(self._on_metadata_failed)
        self._metadata_worker.succeeded.connect(self._metadata_thread.quit)
        self._metadata_worker.failed.connect(self._metadata_thread.quit)
        self._metadata_thread.finished.connect(self._cleanup_metadata_thread)
        self._metadata_thread.start()

    def _on_show_collapsed(self, show_id: int) -> None:
        if show_id == self._metadata_show_id:
            self._stop_metadata_thread()
            self._metadata_panel.hide()
            self._metadata_show_id = None

    def _on_metadata_loaded(self, show_id: int, metadata: TvShowMetadata, poster_bytes: bytes | None) -> None:
        if self._show_table is not None:
            self._show_table.update_show_metadata(show_id, metadata)
        if show_id != self._metadata_show_id:
            return
        self._metadata_panel.set_metadata(metadata, poster_bytes)

    def _on_metadata_failed(self, show_id: int, message: str) -> None:
        if show_id != self._metadata_show_id:
            return
        self._metadata_panel.set_error(message)

    def _on_show_metadata_refreshed(self, show_id: int, metadata: TvShowMetadata) -> None:
        """Reflect a grid-triggered fetch (bulk load or hard refresh) in the open detail panel."""
        if show_id != self._metadata_show_id:
            return
        poster_bytes = None
        if self._metadata_provider is not None:
            poster_bytes = self._metadata_provider.cached_poster_bytes(metadata)
        self._metadata_panel.set_metadata(metadata, poster_bytes)

    def _stop_metadata_thread(self) -> None:
        if self._metadata_thread is not None and self._metadata_thread.isRunning():
            self._metadata_thread.quit()
            self._metadata_thread.wait()

    def _cleanup_metadata_thread(self) -> None:
        if self._metadata_thread is not None:
            self._metadata_thread.wait()
        self._metadata_thread = None
        self._metadata_worker = None

    def _start_show_load(self) -> None:
        if self._current_library is None or self._db_path is None:
            return
        if self._show_thread is not None and self._show_thread.isRunning():
            return

        self._show_thread = QThread(self)
        self._show_worker = _TvShowLoadWorker(
            self._library_db_service,
            self._current_library.id,
            self._db_path,
            self._sort_by,
            self._sort_desc,
        )
        self._show_worker.moveToThread(self._show_thread)
        self._show_thread.started.connect(self._show_worker.run)
        self._show_worker.succeeded.connect(self._on_shows_loaded)
        self._show_worker.failed.connect(self._on_shows_failed)
        self._show_worker.succeeded.connect(self._show_thread.quit)
        self._show_worker.failed.connect(self._show_thread.quit)
        self._show_thread.finished.connect(self._cleanup_show_thread)
        self._show_thread.start()

    def _cleanup_show_thread(self) -> None:
        if self._show_thread is not None:
            self._show_thread.wait()
        self._show_thread = None
        self._show_worker = None

    def _on_shows_loaded(self, shows: list[TvShowSummary]) -> None:
        if not shows:
            self._destroy_show_table()
            self._placeholder.setText("No TV shows were found in this library.")
            self._placeholder.show()
            return

        show_table = self._ensure_show_table()
        show_table.set_shows(shows)
        self._placeholder.hide()
        show_table.show()

    def _on_shows_failed(self, message: str) -> None:
        self._destroy_show_table()
        self._placeholder.setText(message)
        self._placeholder.show()

    def _on_header_clicked(self, section: int) -> None:
        if section == 0:
            return
        sort_key = self._SORT_COLUMNS.get(section)
        if sort_key is None:
            return
        if self._sort_by == sort_key:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_by = sort_key
            self._sort_desc = False
        self._start_show_load()
