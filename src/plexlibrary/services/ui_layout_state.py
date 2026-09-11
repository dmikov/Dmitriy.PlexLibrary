"""Helpers for saving and restoring Qt widget layout state."""

from __future__ import annotations

import base64
from collections.abc import Callable

from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QHeaderView, QWidget


def encode_bytes(data: QByteArray) -> str:
    return base64.b64encode(bytes(data)).decode("ascii")


def decode_bytes(value: str) -> QByteArray:
    return QByteArray(base64.b64decode(value.encode("ascii")))


def save_header_state(header: QHeaderView) -> str:
    return encode_bytes(header.saveState())


def restore_header_state(header: QHeaderView, state: str) -> bool:
    if not state:
        return False
    return header.restoreState(decode_bytes(state))


def finalize_stretch_column(header: QHeaderView, stretch_column: int, min_width: int) -> None:
    """Re-apply stretch mode after restoreState() so filler columns stay pinned on the right."""
    header.setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)
    header.resizeSection(stretch_column, min_width)
    spacer_visual = header.visualIndex(stretch_column)
    last_visual = header.count() - 1
    if spacer_visual != last_visual:
        header.moveSection(spacer_visual, last_visual)


def save_window_geometry(window: QWidget) -> str:
    return encode_bytes(window.saveGeometry())


def restore_window_geometry(window: QWidget, state: str) -> bool:
    if not state:
        return False
    return window.restoreGeometry(decode_bytes(state))


def bind_header_state_tracking(header: QHeaderView, on_changed: Callable[[str], None]) -> None:
    """Keep a shared header layout string in sync when the user resizes or reorders columns."""

    def capture() -> None:
        on_changed(save_header_state(header))

    header.sectionResized.connect(capture)
    header.sectionMoved.connect(capture)
