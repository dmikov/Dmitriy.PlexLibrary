"""Expandable TV show grid backed by the local Plex database."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from plexlibrary.models.library import LibrarySection
from plexlibrary.models.tv import PLEX_SECTION_TYPE_SHOW, TvSeasonRecord, TvShowSummary
from plexlibrary.services.library_db_service import LibraryDbError, LibraryDbService

ROLE_ITEM_KIND = Qt.ItemDataRole.UserRole
ROLE_SHOW_ID = Qt.ItemDataRole.UserRole + 1
ROLE_DETAILS_LOADED = Qt.ItemDataRole.UserRole + 2
_DATA_COLUMN = 0


class _TreeItemKind(StrEnum):
    SHOW = "show"
    SEASON = "season"
    EPISODE = "episode"
    HEADER = "header"


_SHOW_HEADERS = ["Show", "Year", "Seasons"]
_SEASON_HEADERS = ["Season", "", ""]
_EPISODE_HEADERS = ["Episode #", "Title", "Resolution"]
_HEADER_BACKGROUND = QColor("#1976D2")  # Material Blue 700
_HEADER_FOREGROUND = QColor("#FFFFFF")
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


class TvLibraryTreeWidget(QWidget):
    """Tree grid of TV shows with expandable seasons and episodes."""

    _SORT_COLUMNS = {
        0: "name",
        1: "year",
        2: "seasons",
    }

    def __init__(self, library_db_service: LibraryDbService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._library_db_service = library_db_service
        self._db_path: Path | None = None
        self._current_library: LibrarySection | None = None
        self._sort_by = "name"
        self._sort_desc = False
        self._show_thread: QThread | None = None
        self._show_worker: _TvShowLoadWorker | None = None
        self._detail_threads: dict[int, QThread] = {}
        self._detail_workers: dict[int, _TvShowDetailsWorker] = {}

        self._placeholder = QLabel("Select a TV Shows library to view series.", self)
        self._tree = QTreeWidget(self)
        self._tree.setColumnCount(len(_SHOW_HEADERS))
        self._tree.setHeaderLabels(_SHOW_HEADERS)
        self._tree.setRootIsDecorated(True)
        self._tree.setItemsExpandable(True)
        self._tree.setIndentation(20)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSortingEnabled(False)
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.setStyleSheet(_HEADER_STYLESHEET)

        tree_header = self._tree.header()
        tree_header.setStretchLastSection(False)
        tree_header.setSectionsMovable(False)
        tree_header.setDefaultSectionSize(160)
        tree_header.setMinimumSectionSize(60)
        for column in range(len(_SHOW_HEADERS)):
            tree_header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        self._tree.setColumnWidth(0, 420)
        self._tree.setColumnWidth(1, 90)
        self._tree.setColumnWidth(2, 110)
        tree_header.sectionClicked.connect(self._on_header_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._placeholder)
        layout.addWidget(self._tree)
        self._tree.hide()

    def set_database_path(self, db_path: Path) -> None:
        self._db_path = db_path

    def load_library(self, library: LibrarySection | None) -> None:
        self._current_library = library
        self._clear_detail_workers()
        self._tree.clear()

        if library is None or not self._is_tv_library(library) or self._db_path is None:
            self._tree.hide()
            self._placeholder.setText("Select a TV Shows library to view series.")
            self._placeholder.show()
            return

        self._placeholder.setText("Loading TV shows…")
        self._placeholder.show()
        self._tree.hide()
        self._start_show_load()

    def _is_tv_library(self, library: LibrarySection) -> bool:
        return library.section_type == PLEX_SECTION_TYPE_SHOW

    def _make_header_item(self, labels: list[str]) -> QTreeWidgetItem:
        """Create a non-expandable sub-header row for a nested grid section."""

        item = QTreeWidgetItem(labels)
        item.setData(_DATA_COLUMN, ROLE_ITEM_KIND, _TreeItemKind.HEADER.value)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)

        header_font = QFont(item.font(_DATA_COLUMN))
        header_font.setBold(True)
        header_background = QBrush(_HEADER_BACKGROUND)
        header_foreground = QBrush(_HEADER_FOREGROUND)
        for column in range(self._tree.columnCount()):
            item.setFont(column, header_font)
            item.setBackground(column, header_background)
            item.setForeground(column, header_foreground)
            if column < len(labels):
                item.setText(column, labels[column])
        return item

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

    def _clear_detail_workers(self) -> None:
        for thread in self._detail_threads.values():
            if thread.isRunning():
                thread.quit()
                thread.wait()
        self._detail_threads.clear()
        self._detail_workers.clear()

    def _on_shows_loaded(self, shows: list[TvShowSummary]) -> None:
        self._tree.clear()
        for show in shows:
            item = QTreeWidgetItem(
                [
                    show.name,
                    str(show.year) if show.year is not None else "",
                    str(show.season_count),
                ]
            )
            item.setData(_DATA_COLUMN, ROLE_ITEM_KIND, _TreeItemKind.SHOW.value)
            item.setData(_DATA_COLUMN, ROLE_SHOW_ID, show.id)
            item.setData(_DATA_COLUMN, ROLE_DETAILS_LOADED, False)
            # Lazy-loaded shows have no children yet; force the expand control to appear.
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            self._tree.addTopLevelItem(item)

        self._placeholder.hide()
        self._tree.show()
        if not shows:
            self._placeholder.setText("No TV shows were found in this library.")
            self._placeholder.show()

    def _on_shows_failed(self, message: str) -> None:
        self._tree.hide()
        self._placeholder.setText(message)
        self._placeholder.show()

    def _on_header_clicked(self, section: int) -> None:
        sort_key = self._SORT_COLUMNS.get(section)
        if sort_key is None:
            return
        if self._sort_by == sort_key:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_by = sort_key
            self._sort_desc = False
        self._start_show_load()

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        if item.data(_DATA_COLUMN, ROLE_ITEM_KIND) != _TreeItemKind.SHOW.value:
            return
        if item.data(_DATA_COLUMN, ROLE_DETAILS_LOADED):
            return
        if self._db_path is None:
            return

        show_id = int(item.data(_DATA_COLUMN, ROLE_SHOW_ID))
        if show_id in self._detail_threads and self._detail_threads[show_id].isRunning():
            return

        loading_item = QTreeWidgetItem(["Loading…", "", ""])
        loading_item.setFlags(loading_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        item.addChild(loading_item)

        thread = QThread(self)
        worker = _TvShowDetailsWorker(self._library_db_service, show_id, self._db_path)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_show_details_loaded)
        worker.failed.connect(self._on_show_details_failed)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(lambda show_id=show_id: self._cleanup_detail_thread(show_id))

        self._detail_threads[show_id] = thread
        self._detail_workers[show_id] = worker
        thread.start()

    def _cleanup_detail_thread(self, show_id: int) -> None:
        thread = self._detail_threads.pop(show_id, None)
        self._detail_workers.pop(show_id, None)
        if thread is not None:
            thread.wait()

    def _find_show_item(self, show_id: int) -> QTreeWidgetItem | None:
        for index in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(index)
            if item is None:
                continue
            if item.data(_DATA_COLUMN, ROLE_SHOW_ID) == show_id:
                return item
        return None

    def _on_show_details_loaded(self, show_id: int, seasons: list[TvSeasonRecord]) -> None:
        show_item = self._find_show_item(show_id)
        if show_item is None:
            return

        show_item.takeChildren()
        if seasons:
            show_item.addChild(self._make_header_item(_SEASON_HEADERS))

        for season in seasons:
            season_label = (
                f"Season {season.season_number}"
                if season.season_number is not None
                else "Season"
            )
            season_item = QTreeWidgetItem([season_label, "", ""])
            season_item.setData(_DATA_COLUMN, ROLE_ITEM_KIND, _TreeItemKind.SEASON.value)
            season_item.setFlags(season_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            show_item.addChild(season_item)

            if season.episodes:
                season_item.addChild(self._make_header_item(_EPISODE_HEADERS))
                season_item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            else:
                season_item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)

            for episode in season.episodes:
                episode_number = (
                    str(episode.episode_number) if episode.episode_number is not None else ""
                )
                episode_item = QTreeWidgetItem([episode_number, episode.title, episode.resolution])
                episode_item.setData(_DATA_COLUMN, ROLE_ITEM_KIND, _TreeItemKind.EPISODE.value)
                episode_item.setFlags(episode_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                season_item.addChild(episode_item)

        show_item.setExpanded(True)
        show_item.setData(_DATA_COLUMN, ROLE_DETAILS_LOADED, True)
        if not seasons:
            empty_item = QTreeWidgetItem(["No seasons found", "", ""])
            empty_item.setFlags(empty_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            show_item.addChild(empty_item)

    def _on_show_details_failed(self, show_id: int, message: str) -> None:
        show_item = self._find_show_item(show_id)
        if show_item is None:
            return
        show_item.takeChildren()
        error_item = QTreeWidgetItem([message, "", ""])
        error_item.setFlags(error_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        show_item.addChild(error_item)
