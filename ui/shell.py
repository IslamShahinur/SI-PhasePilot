"""
ui/shell.py — application shell: shared state, async runner, themes,
login dialog, base screen, screen registry and the main window.
"""
from __future__ import annotations

import importlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer, Signal, QObject, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QDialog, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QLineEdit, QFrame, QSizePolicy, QStackedWidget, QFormLayout,
    QMessageBox,
)

from services import (
    APP_NAME,
    SCREEN_ACCENTS,
    SyncState,
    SyncTracker,
    load_local_settings,
    save_local_settings,
    screen_label,
    sync_session_to_review_client,
    clear_both_sessions,
)
import data
from data import OfflineError

Row = dict[str, Any]
Rows = list[Row]

_NEW_PROJECT_ENTRY = "+ New project..."
_UNSET: Any = object()


# ===== SECTION: Module-level state =====

_sync_tracker: SyncTracker | None = None
_dispatcher: "_UiDispatcher | None" = None

_main_window: "MainWindow | None" = None

def get_main_window() -> "MainWindow | None":
    """Return the main window instance, if created."""
    return _main_window

def set_main_window(window: "MainWindow") -> None:
    """Set the module-level main window reference."""
    global _main_window
    _main_window = window


def set_sync_tracker(tracker: SyncTracker) -> None:
    """Set the module-level sync tracker used by run_async."""
    global _sync_tracker
    _sync_tracker = tracker


def _get_dispatcher() -> "_UiDispatcher":
    """Get or create the singleton UiDispatcher (must be called on UI thread)."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = _UiDispatcher()
    return _dispatcher


# ===== SECTION: UI Dispatcher =====

class _UiDispatcher(QObject):
    """Dispatches callables to the UI thread via Qt signal/slot."""

    _invoke = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._invoke.connect(self._on_invoke)

    @Slot(object)
    def _on_invoke(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001
            logging.exception("Exception in UI dispatcher callback")

    def post(self, fn: Callable[[], None]) -> None:
        """Schedule *fn* to run on the UI thread."""
        self._invoke.emit(fn)


# ===== SECTION: AppState =====

@dataclass
class AppState:
    """Shared application state passed to the MainWindow and screens."""
    user_id: str = ""
    email: str = ""
    device_id: str = ""
    project: Row | None = None
    phase: Row | None = None
    theme: str = "light"
    sync: SyncTracker = field(default_factory=SyncTracker)


# ===== SECTION: run_async =====

def _run_background(
    fn: Callable,
    on_done: Callable[[Any | Exception, bool], None],
) -> None:
    """Run *fn* in a worker thread; call *on_done(result, is_error)* on UI thread.

    Does NOT touch the SyncTracker. Use for background work like ping.
    """
    dispatcher = _get_dispatcher()

    def _worker() -> None:
        try:
            result = fn()
            dispatcher.post(lambda r=result: on_done(r, False))
        except Exception as exc:  # noqa: BLE001
            dispatcher.post(lambda e=exc: on_done(e, True))

    threading.Thread(target=_worker, daemon=True).start()


def run_async(
    fn: Callable,
    on_success: Callable[[Any], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
) -> None:
    """Run *fn* in a worker thread; deliver results on the UI thread.

    Manages the global SyncTracker: SAVING before the call, then
    SYNCED / OFFLINE / ERROR on completion.
    """
    if _sync_tracker is not None:
        _sync_tracker.set_state(SyncState.SAVING)

    def _on_done(result: Any, is_error: bool) -> None:
        if is_error:
            exc = result
            if _sync_tracker is not None:
                if isinstance(exc, OfflineError):
                    _sync_tracker.set_state(SyncState.OFFLINE)
                else:
                    _sync_tracker.set_state(SyncState.ERROR, str(exc))
            if on_error is not None:
                on_error(exc)
        else:
            if _sync_tracker is not None:
                _sync_tracker.set_state(SyncState.SYNCED)
            if on_success is not None:
                on_success(result)

    _run_background(fn, _on_done)


# ===== SECTION: Themes =====

# Base font size in points (increased by 2pt for better readability)
BASE_FONT_PT = 11

_LIGHT_PALETTE = {
    "window": "#ffffff",
    "window_text": "#1a1a1a",
    "base": "#1a1a1a",
    "sidebar_bg": "#f5f5f5",
    "topbar_bg": "#f0f0f0",
    "footer_bg": "#f0f0f0",
    "border": "#d0d0d0",
    "hover": "#e8e8e8",
    "pressed": "#d4d4d4",
    "input_bg": "#ffffff",
    "input_border": "#b0b0b0",
    "input_text": "#1a1a1a",
    "placeholder_text": "#888888",
    "disabled_text": "#999999",
    "highlight": "#3b82f6",
    "highlight_text": "#ffffff",
    "selection_bg": "#3b82f6",
    "selection_text": "#ffffff",
    "scrollbar_bg": "#f0f0f0",
    "scrollbar_handle": "#c0c0c0",
    "scrollbar_pressed": "#a0a0a0",
    "groupbox_border": "#d0d0d0",
    "groupbox_title": "#1a1a1a",
    "table_header_bg": "#f0f0f0",
    "table_header_text": "#1a1a1a",
    "table_row_alt": "#f9f9f9",
    "table_border": "#d0d0d0",
    "table_selection_bg": "#f3e5f5",
    "table_selection_text": "#1a1a1a",
    "sync_good": "#0f766e",
    "sync_warning": "#d97706",
    "sync_error": "#e11d48",
}

_DARK_PALETTE = {
    "window": "#1e1e1e",
    "window_text": "#d4d4d4",
    "base": "#d4d4d4",
    "sidebar_bg": "#2d2d30",
    "topbar_bg": "#3c3c3c",
    "footer_bg": "#3c3c3c",
    "border": "#565656",
    "hover": "#4a4a4a",
    "pressed": "#3a3a3a",
    "input_bg": "#2d2d30",
    "input_border": "#565656",
    "input_text": "#d4d4d4",
    "placeholder_text": "#888888",
    "disabled_text": "#666666",
    "highlight": "#2563eb",
    "highlight_text": "#ffffff",
    "selection_bg": "#2563eb",
    "selection_text": "#ffffff",
    "scrollbar_bg": "#2d2d30",
    "scrollbar_handle": "#565656",
    "scrollbar_pressed": "#767676",
    "groupbox_border": "#565656",
    "groupbox_title": "#d4d4d4",
    "table_header_bg": "#2d2d30",
    "table_header_text": "#d4d4d4",
    "table_row_alt": "#252526",
    "table_border": "#565656",
    "table_selection_bg": "#4a148c",
    "table_selection_text": "#ffffff",
    "sync_good": "#0f766e",
    "sync_warning": "#f59e0b",
    "sync_error": "#ef4444",
}

_COLORS = {"light": _LIGHT_PALETTE, "dark": _DARK_PALETTE}


def _build_stylesheet(mode: str) -> str:
    c = _COLORS.get(mode, _LIGHT_PALETTE)
    return f"""
    /* Base application font */
    QApplication {{
        font-family: 'Segoe UI', 'Arial', sans-serif;
        font-size: {BASE_FONT_PT}pt;
        background-color: {c['window']};
        color: {c['window_text']};
    }}

    /* QWidget - base for all widgets */
    QWidget {{
        background-color: {c['window']};
        color: {c['window_text']};
    }}

    /* Top Bar */
    QFrame#topbar {{
        background-color: {c['topbar_bg']};
        border-bottom: 1px solid {c['border']};
        color: {c['window_text']};
    }}
    QLabel#appName {{
        color: {c['window_text']};
        font-size: 14pt;
        font-weight: bold;
        background-color: transparent;
        padding: 0;
        margin: 0;
    }}

    /* Footer */
    QFrame#footer {{
        background-color: {c['footer_bg']};
        border-top: 1px solid {c['border']};
        color: {c['window_text']};
    }}

    /* Main window and stacked widget */
    QMainWindow {{
        background-color: {c['window']};
        color: {c['window_text']};
    }}
    QStackedWidget {{
        background-color: {c['window']};
        color: {c['window_text']};
    }}

    /* Scroll Areas - critical for Screens A and D */
    QScrollArea {{
        background-color: {c['window']};
        color: {c['window_text']};
        border: none;
    }}
    QScrollArea > QWidget > QWidget {{
        background-color: {c['window']};
        color: {c['window_text']};
    }}
    QAbstractScrollArea::viewport {{
        background-color: {c['window']};
        color: {c['window_text']};
    }}
    QScrollArea::corner {{
        background-color: {c['window']};
    }}

    /* Buttons */
    QPushButton {{
        background-color: {c['sidebar_bg']};
        color: {c['window_text']};
        border: 1px solid {c['border']};
        border-radius: 4px;
        padding: 4px 8px;
        min-width: 24px;
        min-height: 24px;
    }}
    QPushButton:hover {{
        background-color: {c['hover']};
    }}
    QPushButton:pressed {{
        background-color: {c['pressed']};
    }}
    QPushButton:disabled {{
        background-color: {c['sidebar_bg']};
        color: {c['disabled_text']};
        border-color: {c['border']};
    }}
    QPushButton:checked {{
        background-color: {c['highlight']};
        color: {c['highlight_text']};
        border-color: {c['highlight']};
    }}

    /* Screen tab buttons (A-G) */
    QPushButton[text="A"], QPushButton[text="B"],
    QPushButton[text="C"], QPushButton[text="D"],
    QPushButton[text="E"], QPushButton[text="F"],
    QPushButton[text="G"] {{
        padding: 4px 10px;
        border: none;
        border-radius: 4px;
        background-color: transparent;
    }}

    /* Combos */
    QComboBox {{
        background-color: {c['input_bg']};
        color: {c['input_text']};
        border: 1px solid {c['input_border']};
        border-radius: 4px;
        padding: 2px 6px;
        selection-background-color: {c['selection_bg']};
        selection-color: {c['selection_text']};
    }}
    QComboBox:disabled {{
        color: {c['disabled_text']};
        background-color: {c['input_bg']};
        border-color: {c['border']};
    }}
    QComboBox QAbstractItemView {{
        background-color: {c['input_bg']};
        color: {c['input_text']};
        border: 1px solid {c['input_border']};
        selection-background-color: {c['selection_bg']};
        selection-color: {c['selection_text']};
    }}
    QComboBox::drop-down {{
        border: 0px;
        background-color: transparent;
    }}
    QComboBox::down-arrow {{
        border: 0px;
    }}

    /* Line Edits */
    QLineEdit {{
        background-color: {c['input_bg']};
        color: {c['input_text']};
        border: 1px solid {c['input_border']};
        border-radius: 4px;
        padding: 4px 6px;
        selection-background-color: {c['selection_bg']};
        selection-color: {c['selection_text']};
    }}
    QLineEdit:disabled {{
        color: {c['disabled_text']};
        background-color: {c['input_bg']};
        border-color: {c['border']};
    }}
    QLineEdit::placeholder {{
        color: {c['placeholder_text']};
    }}

    /* Text Edits */
    QTextEdit {{
        background-color: {c['input_bg']};
        color: {c['input_text']};
        border: 1px solid {c['input_border']};
        border-radius: 4px;
        padding: 6px;
        selection-background-color: {c['highlight']};
        selection-color: {c['highlight_text']};
    }}
    QTextEdit:disabled {{
        color: {c['disabled_text']};
        background-color: {c['input_bg']};
        border-color: {c['border']};
    }}
    QPlainTextEdit {{
        background-color: {c['input_bg']};
        color: {c['input_text']};
        border: 1px solid {c['input_border']};
        border-radius: 4px;
        padding: 6px;
        selection-background-color: {c['highlight']};
        selection-color: {c['highlight_text']};
    }}
    QPlainTextEdit:disabled {{
        color: {c['disabled_text']};
        background-color: {c['input_bg']};
        border-color: {c['border']};
    }}

    /* Labels */
    QLabel {{
        color: {c['window_text']};
        background-color: transparent;
    }}
    QLabel:disabled {{
        color: {c['disabled_text']};
    }}

    /* Specific label styles */
    QLabel#syncLabel {{
        color: {c['window_text']};
        font-weight: bold;
        padding: 0 8px;
        background-color: transparent;
    }}
    QLabel#screenTitle {{
        color: {c['window_text']};
        font-size: 14pt;
        font-weight: bold;
        padding: 4px 0;
        background-color: transparent;
    }}
    QLabel#footerLabel {{
        color: {c['placeholder_text']};
        font-size: 11px;
        padding: 0 8px;
        background-color: transparent;
    }}

    /* Group Boxes */
    QGroupBox {{
        border: 1px solid {c['groupbox_border']};
        border-radius: 4px;
        margin-top: 8px;
        padding-top: 12px;
        background-color: transparent;
        color: {c['groupbox_title']};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 8px;
        padding: 0 2px 0 2px;
        color: {c['groupbox_title']};
        background-color: {c['topbar_bg']};
    }}

    /* Tables */
    QTableWidget {{
        background-color: {c['input_bg']};
        color: {c['input_text']};
        border: 1px solid {c['table_border']};
        border-radius: 4px;
        gridline-color: {c['table_border']};
    }}
    QTableWidget:disabled {{
        color: {c['disabled_text']};
        background-color: {c['input_bg']};
    }}
    QHeaderView::section {{
        background-color: {c['table_header_bg']};
        color: {c['table_header_text']};
        border: none;
        border-bottom: 1px solid {c['table_border']};
        padding: 4px 8px;
        text-align: left;
    }}
    QTableView::verticalHeader::section, QTableWidget::verticalHeader::section {{
        background-color: {c['table_header_bg']};
        color: {c['table_header_text']};
        border: none;
        border-bottom: 1px solid {c['table_border']};
        padding: 4px 8px;
    }}
    QTableView::item:selected, QTableView::item:selected:active, QTableView::item:selected:!active,
    QTableWidget::item:selected, QTableWidget::item:selected:active, QTableWidget::item:selected:!active,
    QListWidget::item:selected, QListWidget::item:selected:active, QListWidget::item:selected:!active {{
        background-color: {c['table_selection_bg']};
        color: {c['table_selection_text']};
    }}
    QTableView::item:alternate, QTableWidget::item:alternate {{
        background-color: {c['table_row_alt']};
    }}
    QTableView {{
        background-color: {c['input_bg']};
        color: {c['input_text']};
        border: 1px solid {c['table_border']};
        border-radius: 4px;
        gridline-color: {c['table_border']};
    }}

    /* Scrollbars */
    QScrollBar:vertical, QScrollBar:horizontal {{
        border: none;
        background-color: {c['scrollbar_bg']};
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background-color: {c['scrollbar_handle']};
        border-radius: 4px;
        min-height: 16px;
        min-width: 16px;
    }}
    QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed {{
        background-color: {c['scrollbar_pressed']};
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        border: none;
        background: none;
    }}
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: none;
    }}

    /* Frames */
    QFrame {{
        background-color: {c['window']};
        color: {c['window_text']};
    }}

    /* Tool buttons */
    QToolButton {{
        background-color: transparent;
        color: {c['window_text']};
        border: none;
        padding: 4px;
    }}
    QToolButton:hover {{
        background-color: {c['hover']};
    }}
    QToolButton:disabled {{
        color: {c['disabled_text']};
    }}

    /* List Widgets */
    QListWidget {{
        background-color: {c['input_bg']};
        color: {c['input_text']};
        border: 1px solid {c['table_border']};
        border-radius: 4px;
    }}
    QListWidget::item:alternate {{
        background-color: {c['table_row_alt']};
    }}

    /* Checkboxes */
    QCheckBox {{
        color: {c['window_text']};
        background-color: transparent;
        spacing: 6px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 2px solid {c['input_border']};
        border-radius: 3px;
        background-color: {c['input_bg']};
    }}
    QCheckBox::indicator:checked {{
        background-color: {c['highlight']};
        border-color: {c['highlight']};
        image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iMTIiIHZpZXdCb3g9IjAgMCAxMiAxMiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTEwIDNMNC41IDguNUwyIDYiIHN0cm9rZT0id2hpdGUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+Cjwvc3ZnPg==);
    }}
    QCheckBox::indicator:hover {{
        border-color: {c['highlight']};
    }}
    QCheckBox::indicator:disabled {{
        border-color: {c['border']};
        background-color: {c['sidebar_bg']};
    }}
    QCheckBox:disabled {{
        color: {c['disabled_text']};
    }}

    /* Danger Zone */
    QGroupBox#dangerZone {{
        border: 1px solid {c['sync_error']};
    }}
    QGroupBox#dangerZone::title {{
        color: {c['sync_error']};
    }}
    QPushButton#dangerButton {{
        color: {c['sync_error']};
        border: 1px solid {c['sync_error']};
    }}
    """


def _get_theme_mode() -> str:
    """Get the current theme mode from the app or state."""
    app = QApplication.instance()
    if app is not None:
        # Try to get from main window state
        mw = get_main_window()
        if mw and mw.state:
            return mw.state.theme
    return "light"


def apply_theme(app: QApplication, mode: str) -> None:
    """Apply the light or dark palette + stylesheet to the QApplication."""
    app.setStyle("Fusion")
    stylesheet = _build_stylesheet(mode)
    app.setStyleSheet(stylesheet)
    # Set base font on the application
    font = app.font()
    font.setPointSize(BASE_FONT_PT)
    font.setFamily("Segoe UI")
    app.setFont(font)


# ===== SECTION: Dialog helpers =====

def show_error(parent: QWidget | None, message: str) -> None:
    """Show an error message in a modal dialog."""
    QMessageBox.critical(parent, "Error", message)


def confirm(parent: QWidget | None, message: str) -> bool:
    """Show a Yes/No confirmation dialog. Returns True if Yes."""
    result = QMessageBox.question(
        parent, "Confirm", message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    return result == QMessageBox.StandardButton.Yes


# ===== SECTION: LoginDialog =====

class LoginDialog(QDialog):
    """Sign-in dialog with email, password and 'Remember me'."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Sign In")
        self.setModal(True)
        self.setMinimumWidth(360)
        self.user_id: str = ""
        self.email: str = ""
        self.refresh_token: str = ""
        self.remember_me: bool = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("SI PhasePilot")
        title.setFont(QFont("", 18, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel("Sign in with your Supabase account.")
        layout.addWidget(subtitle)

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self._email_edit = QLineEdit()
        self._email_edit.setPlaceholderText("you@example.com")
        form.addRow("Email:", self._email_edit)

        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_edit.setPlaceholderText("Password")
        form.addRow("Password:", self._password_edit)

        self._remember_checkbox = QCheckBox("Remember me")
        form.addRow("", self._remember_checkbox)

        layout.addLayout(form)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: #e11d48; background-color: transparent;")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        self._sign_in_btn = QPushButton("Sign In")
        self._sign_in_btn.setDefault(True)
        self._sign_in_btn.clicked.connect(self._on_sign_in)
        layout.addWidget(self._sign_in_btn)

        self._busy = False

    def _on_sign_in(self) -> None:
        if self._busy:
            return
        email = self._email_edit.text().strip()
        password = self._password_edit.text()
        self._error_label.setVisible(False)
        self._sign_in_btn.setEnabled(False)
        self._busy = True

        run_async(
            lambda: data.sign_in(email, password),
            on_success=self._on_sign_in_success,
            on_error=self._on_sign_in_error,
        )

    def _on_sign_in_success(self, result: Row) -> None:
        self._busy = False
        self._sign_in_btn.setEnabled(True)
        self.user_id = result["user_id"]
        self.email = result["email"]
        self.refresh_token = result["refresh_token"]
        self.remember_me = self._remember_checkbox.isChecked()
        self.accept()

    def _on_sign_in_error(self, exc: Exception) -> None:
        self._busy = False
        self._sign_in_btn.setEnabled(True)
        self._error_label.setText(str(exc))
        self._error_label.setVisible(True)


# ===== SECTION: BaseScreen and PlaceholderScreen =====

class BaseScreen(QWidget):
    """Base class for all seven screens."""

    screen_id: str = ""
    title: str = ""
    accent: str = ""

    def __init__(self, state: AppState | None = None):
        super().__init__()
        self.state = state

    def on_show(self) -> None:
        """Called when the screen becomes the active screen."""

    def reload(self) -> None:
        """Reload data from the server."""

    def on_project_changed(self, project: Row | None) -> None:
        """Called when the selected project changes."""

    def on_phase_changed(self, phase: Row | None) -> None:
        """Called when the selected phase changes."""

    def set_writable(self, writable: bool) -> None:
        """Enable/disable write controls based on sync state."""


class PlaceholderScreen(BaseScreen):
    """Shown when a screen module is not delivered yet."""

    def __init__(self, letter: str, phase_number: int):
        super().__init__()
        self.screen_id = letter
        self.title = screen_label(letter)
        self.accent = SCREEN_ACCENTS.get(letter, "#666666")
        self._phase_number = phase_number
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel(f"Coming in Phase {self._phase_number}")
        label.setStyleSheet(
            f"font-size: 18px; color: {self.accent}; font-weight: bold; background-color: transparent;"
        )
        layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignCenter)
        sub = QLabel(f"Screen {self.screen_id}: {self.title}")
        sub.setStyleSheet("color: #888888; background-color: transparent;")
        layout.addWidget(sub, alignment=Qt.AlignmentFlag.AlignCenter)


# ===== SECTION: Screen registry =====

SCREEN_REGISTRY: dict[str, tuple[str, str]] = {
    "A": ("ui.screens_ab", "ScreenA"),
    "B": ("ui.screens_ab", "ScreenB"),
    "C": ("ui.screens_cd", "ScreenC"),
    "D": ("ui.screen_d", "ScreenD"),
    "E": ("ui.screens_ef", "ScreenE"),
    "F": ("ui.screens_ef", "ScreenF"),
    "G": ("ui.screen_g", "ScreenG"),
}


def _phase_for_letter(letter: str) -> int:
    if letter in ("C", "D", "E", "F"):
        return 2
    if letter == "G":
        return 3
    return 1


def _default_phase_id(phases: Rows) -> str | None:
    """Newest phase that is not baseline_approved, else the newest phase."""
    if not phases:
        return None
    open_phases = [
        p for p in phases if p.get("status") != "baseline_approved"
    ]
    if open_phases:
        return open_phases[-1]["id"]
    return phases[-1]["id"]


# ===== SECTION: MainWindow =====

class MainWindow(QMainWindow):
    """Main application window with top bar, screens and footer."""

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        set_sync_tracker(state.sync)
        set_main_window(self)
        self._current_letter = "A"
        self._screen_widgets: dict[str, BaseScreen] = {}
        self._projects: Rows = []          # non-archived projects for top-bar combo
        self._phases: Rows = []
        self._sync_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._load_epoch = 0               # increments on every async load; stale results ignored
        self._project_load_epoch = 0
        self._pending_phase_id: str | None = None  # for refresh_phases_and_select
        self._prefer_project_id: Any = _UNSET

        self.setWindowTitle(APP_NAME)
        self.resize(1100, 720)
        self.setMinimumSize(1000, 650)
        self._build_layout()
        self._setup_ping_timer()
        state.sync.add_listener(self._on_sync_changed)
        self.set_sync_state(state.sync.get_state())
        self._bootstrap()

    def _bootstrap(self) -> None:
        """Show the initial screen and kick off async data loading."""
        self._show_initial_screen()
        self._refresh_projects()

    def _show_initial_screen(self) -> None:
        """Load and show the initial screen (Screen A) at startup."""
        screen = self._load_screen(self._current_letter)
        self._stack.setCurrentWidget(screen)
        self._topbar.set_current_screen(self._current_letter)
        screen.on_show()

    # --- layout building ---

    def _build_layout(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main = QVBoxLayout(central)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        main.addWidget(self._build_topbar())

        body = QHBoxLayout()
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        body.addWidget(self._stack, 1)
        main.addLayout(body)

        main.addWidget(self._build_footer())

    def _build_topbar(self) -> QFrame:
        # Lazy import: ui.panels imports helpers from this module.
        from ui.panels import TopBar

        bar = TopBar()
        self._topbar = bar
        bar.project_chosen.connect(self._on_project_chosen)
        bar.phase_chosen.connect(self._on_phase_chosen)
        bar.screen_chosen.connect(self._switch_screen)
        bar.new_project_chosen.connect(self._on_new_project_chosen)
        bar.archived_chosen.connect(self._on_archived_chosen)
        bar.theme_toggled.connect(self.toggle_theme)
        return bar

    def _build_footer(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("footer")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 4, 12, 4)

        self._account_label = QLabel("Signed in")
        self._account_label.setObjectName("footerLabel")
        layout.addWidget(self._account_label)

        layout.addStretch()

        self._sync_time_label = QLabel("Last sync: --")
        self._sync_time_label.setObjectName("footerLabel")
        layout.addWidget(self._sync_time_label)

        layout.addStretch()

        self._status_label = QLabel("Ready")
        self._status_label.setObjectName("footerLabel")
        layout.addWidget(self._status_label)

        return bar

    # --- screen loading ---

    def _load_screen(self, letter: str) -> BaseScreen:
        """Import the screen module; fall back to PlaceholderScreen."""
        if letter in self._screen_widgets:
            return self._screen_widgets[letter]

        entry = SCREEN_REGISTRY.get(letter)
        if entry is None:
            screen = PlaceholderScreen(letter, _phase_for_letter(letter))
        else:
            module_path, class_name = entry
            try:
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                screen = cls(self.state)
            except ModuleNotFoundError:
                screen = PlaceholderScreen(
                    letter, _phase_for_letter(letter)
                )

        self._stack.addWidget(screen)
        self._screen_widgets[letter] = screen
        screen.set_writable(
            self.state.sync.get_state()
            not in (SyncState.OFFLINE, SyncState.SAVING)
        )
        return screen

    def _switch_screen(self, letter: str) -> None:
        """Show the screen for *letter* and update UI elements."""
        if letter == self._current_letter:
            return
        self._current_letter = letter
        screen = self._load_screen(letter)
        self._stack.setCurrentWidget(screen)
        self._topbar.set_current_screen(letter)
        screen.on_show()

    # --- project / phase management ---

    def _refresh_projects(self) -> None:
        self._project_load_epoch += 1
        expected = self._project_load_epoch
        prefer = self._prefer_project_id
        self._prefer_project_id = _UNSET

        def _fetch() -> Rows:
            return data.list_projects()

        run_async(
            _fetch,
            on_success=lambda projects, e=expected, p=prefer: (
                self._on_projects_loaded(projects, e, p)
            ),
            on_error=self._on_load_error,
        )

    def _on_projects_loaded(
        self, projects: Rows, epoch: int, prefer: Any
    ) -> None:
        if epoch != self._project_load_epoch:
            return  # stale result
        self._projects = projects

        if prefer is _UNSET or prefer is None:
            settings = load_local_settings()
            prefer = settings.get("last_project_id")

        selected_id: str | None
        if prefer == _NEW_PROJECT_ENTRY:
            selected_id = _NEW_PROJECT_ENTRY
        elif prefer and any(p["id"] == prefer for p in projects):
            selected_id = prefer
        elif projects:
            selected_id = projects[0]["id"]
        else:
            selected_id = _NEW_PROJECT_ENTRY

        if (
            selected_id is not None
            and selected_id != _NEW_PROJECT_ENTRY
        ):
            settings = load_local_settings()
            settings["last_project_id"] = selected_id
            save_local_settings(settings)

        self._topbar.set_projects(projects, selected_id)

    def _on_load_error(self, exc: Exception) -> None:
        if isinstance(exc, OfflineError):
            self.state.sync.set_state(SyncState.OFFLINE)
            self._status_label.setText("Offline — last loaded data shown")
        else:
            self._status_label.setText(str(exc))

    def _on_project_chosen(self, project_id: str | None) -> None:
        if project_id is None:
            self._enter_new_project_mode()
            return
        project = next(
            (p for p in self._projects if p["id"] == project_id), None
        )
        if project is None:
            return
        self.state.project = project
        settings = load_local_settings()
        settings["last_project_id"] = project_id
        save_local_settings(settings)
        self.state.phase = None
        self._pending_phase_id = None
        self._refresh_phases(project_id)
        for s in self._screen_widgets.values():
            s.on_project_changed(project)

    def _on_new_project_chosen(self) -> None:
        self._enter_new_project_mode()

    def _enter_new_project_mode(self) -> None:
        self.state.project = None
        self.state.phase = None
        self._phases = []
        self._pending_phase_id = None
        self._topbar.set_phases([], None)
        for s in self._screen_widgets.values():
            s.on_project_changed(None)
            s.on_phase_changed(None)

    def _on_archived_chosen(self) -> None:
        from ui.panels import ArchivedProjectsDialog

        if self.state.project is not None:
            restore_id: str | None = self.state.project["id"]
        else:
            restore_id = _NEW_PROJECT_ENTRY
        writable = self.state.sync.get_state() not in (
            SyncState.OFFLINE, SyncState.SAVING
        )
        dialog = ArchivedProjectsDialog(parent=self, writable=writable)
        reopened = False

        def _on_reopened(_project_id: str) -> None:
            nonlocal reopened
            reopened = True

        dialog.reopened.connect(_on_reopened)
        dialog.exec()
        if reopened:
            self._prefer_project_id = restore_id
            self._refresh_projects()
        else:
            self._topbar.select_project_id(restore_id, silent=True)

    def _refresh_phases(self, project_id: str | None) -> None:
        self._load_epoch += 1
        expected_epoch = self._load_epoch
        self._phases = []
        self._topbar.set_phases([], None)
        if project_id:
            run_async(
                lambda: data.list_phases(project_id),
                on_success=lambda phases: self._on_phases_loaded(
                    phases, expected_epoch
                ),
                on_error=self._on_load_error,
            )

    def _on_phases_loaded(self, phases: Rows, expected_epoch: int) -> None:
        if expected_epoch != self._load_epoch:
            return
        self._phases = phases
        if self._pending_phase_id and any(
            p["id"] == self._pending_phase_id for p in phases
        ):
            phase_id = self._pending_phase_id
            self._pending_phase_id = None
        else:
            self._pending_phase_id = None
            phase_id = _default_phase_id(phases)
        self._topbar.set_phases(phases, phase_id)

    def _on_phase_chosen(self, phase_id: str | None) -> None:
        if phase_id is None:
            self.state.phase = None
        else:
            self.state.phase = next(
                (p for p in self._phases if p["id"] == phase_id), None
            )
        for s in self._screen_widgets.values():
            s.on_phase_changed(self.state.phase)

    def refresh_all(self) -> None:
        """Reload projects, phases and all loaded screens."""
        self._refresh_projects()
        for s in self._screen_widgets.values():
            s.reload()

    def select_project(self, project_id: str) -> None:
        """Select a project by id in the top-bar combo."""
        self._topbar.select_project_id(project_id)

    def select_phase(self, phase_id: str) -> None:
        """Select a phase by id in the top-bar combo."""
        self._topbar.select_phase_id(phase_id)

    # --- sync / theme / footer ---

    def refresh_phases_and_select(self, phase_id: str | None = None) -> None:
        """Refresh phases from server and optionally select a phase."""
        if self.state.project:
            self._pending_phase_id = phase_id
            self._refresh_phases(self.state.project["id"])
        elif phase_id:
            self.select_phase(phase_id)

    def set_sync_state(self, state: SyncState, message: str = "") -> None:
        """Update the sync chip and propagate writability to screens."""
        self._topbar.set_sync_state(state, message)
        writable = state not in (SyncState.OFFLINE, SyncState.SAVING)
        for s in self._screen_widgets.values():
            s.set_writable(writable)
        self._topbar.set_writable(writable)

    def _on_sync_changed(
        self, state: SyncState, message: str
    ) -> None:
        self.set_sync_state(state, message)
        self._sync_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._sync_time_label.setText(f"Last sync: {self._sync_time}")
        if message:
            self._status_label.setText(message)
        elif state == SyncState.SYNCED:
            self._status_label.setText("Ready")

    def toggle_theme(self) -> None:
        """Switch between light and dark themes."""
        new_theme = "dark" if self.state.theme == "light" else "light"
        self.state.theme = new_theme
        self._topbar.set_theme(new_theme)
        settings = load_local_settings()
        settings["theme"] = new_theme
        save_local_settings(settings)
        apply_theme(QApplication.instance(), new_theme)

    def _setup_ping_timer(self) -> None:
        """Start a 30-second timer that pings the server."""
        self._ping_timer = QTimer(self)
        self._ping_timer.timeout.connect(self._do_ping)
        self._ping_timer.start(30_000)
        self._do_ping()

    def _do_ping(self) -> None:
        """Ping the server and update sync state.

        Runs in any state except SAVING. Does not use run_async (no SAVING state).
        Also syncs the session to data_review client in case it was refreshed.
        """
        if self.state.sync.get_state() == SyncState.SAVING:
            return
        _run_background(
            lambda: data.ping(),
            on_done=self._on_ping_done,
        )
        # Sync session to data_review client (in case data client refreshed its session)
        try:
            sync_session_to_review_client()
        except Exception as exc:
            logging.warning("Failed to sync session to data_review client: %s", exc)

    def _on_ping_done(self, result: Any, is_error: bool) -> None:
        if is_error:
            # Network error → treat as offline unless we're saving
            if self.state.sync.get_state() != SyncState.SAVING:
                self.state.sync.set_state(SyncState.OFFLINE)
            return
        online = result
        current = self.state.sync.get_state()
        if online and current == SyncState.OFFLINE:
            self.state.sync.set_state(SyncState.SYNCED)
        elif not online and current != SyncState.SAVING:
            self.state.sync.set_state(SyncState.OFFLINE)

    @property
    def sync_label_text(self) -> str:
        return self._topbar.sync_text()
