"""Widget that displays TMDb metadata (poster, overview, ratings) for one TV show."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from plexlibrary.models.metadata import TvShowMetadata

_POSTER_WIDTH = 100


class ShowMetadataPanel(QWidget):
    """Poster plus a text summary sourced from TMDb for the currently inspected show."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._poster_label = QLabel(self)
        self._poster_label.setFixedWidth(_POSTER_WIDTH)
        self._poster_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self._title_label = QLabel(self)
        self._title_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        self._title_label.setWordWrap(True)

        self._facts_label = QLabel(self)
        self._facts_label.setWordWrap(True)
        self._facts_label.setStyleSheet("color: #555555;")

        self._overview_label = QLabel(self)
        self._overview_label.setWordWrap(True)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.addWidget(self._title_label)
        text_column.addWidget(self._facts_label)
        text_column.addWidget(self._overview_label)
        text_column_widget = QWidget(self)
        text_column_widget.setLayout(text_column)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)
        layout.addWidget(self._poster_label)
        layout.addWidget(text_column_widget, stretch=1)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.set_loading()

    def set_loading(self) -> None:
        self._title_label.setText("Loading TMDb metadata…")
        self._facts_label.setText("")
        self._overview_label.setText("")
        self._poster_label.clear()

    def set_error(self, message: str) -> None:
        self._title_label.setText("TMDb metadata unavailable")
        self._facts_label.setText(message)
        self._overview_label.setText("")
        self._poster_label.clear()

    def set_metadata(self, metadata: TvShowMetadata, poster_bytes: bytes | None) -> None:
        self._title_label.setText(metadata.name or "")
        self._facts_label.setText(_build_facts_line(metadata))
        self._overview_label.setText(metadata.overview or "No overview available.")

        self._poster_label.clear()
        if poster_bytes:
            pixmap = QPixmap()
            if pixmap.loadFromData(poster_bytes):
                self._poster_label.setPixmap(
                    pixmap.scaledToWidth(_POSTER_WIDTH, Qt.TransformationMode.SmoothTransformation)
                )


def _build_facts_line(metadata: TvShowMetadata) -> str:
    facts: list[str] = []
    if metadata.first_air_date:
        facts.append(f"First aired {metadata.first_air_date}")
    if metadata.status:
        facts.append(metadata.status)
    if metadata.number_of_seasons is not None:
        facts.append(f"{metadata.number_of_seasons} season(s)")
    if metadata.vote_average:
        facts.append(f"TMDb rating {metadata.vote_average:.1f}/10")
    if metadata.networks:
        facts.append(", ".join(metadata.networks))
    if metadata.genres:
        facts.append(", ".join(metadata.genres))
    return "  •  ".join(facts)
