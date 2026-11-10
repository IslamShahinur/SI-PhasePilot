"""
main.py – application entry point.
Phase 1 implementation.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

import data
from data import DataError, restore_session, init_client
import services
import data_review
from services import (
    APP_NAME,
    app_data_dir,
    load_local_settings,
    save_local_settings,
    load_session,
    clear_session,
    get_device_id,
    sync_session_to_review_client,
    clear_both_sessions,
)
from ui.shell import (
    AppState,
    LoginDialog,
    MainWindow,
    apply_theme,
    show_error,
)


# ===== SECTION: Configuration =====

def check_python_version() -> None:
    """Exit with a clear message if Python < 3.11."""
    if sys.version_info < (3, 11):
        msg = f"{APP_NAME} requires Python 3.11 or newer. Current: {sys.version.split()[0]}"
        print(msg, file=sys.stderr)
        if QApplication.instance() is not None:
            QMessageBox.critical(None, "Python Version Error", msg)
        sys.exit(1)


def load_config() -> tuple[str, str]:
    """Read SUPABASE_URL and SUPABASE_ANON_KEY; friendly error if missing."""
    url = os.environ.get("SUPABASE_URL")
    anon_key = os.environ.get("SUPABASE_ANON_KEY")
    if not url or not anon_key:
        missing = []
        if not url:
            missing.append("SUPABASE_URL")
        if not anon_key:
            missing.append("SUPABASE_ANON_KEY")
        msg = (
            f"Missing environment variable(s): {', '.join(missing)}.\n\n"
            f"Set them in your environment and restart the application.\n"
            f"Example:\n"
            f"  set SUPABASE_URL=https://your-project.supabase.co\n"
            f"  set SUPABASE_ANON_KEY=your-anon-key"
        )
        print(msg, file=sys.stderr)
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "Configuration Error", msg)
        sys.exit(1)
    return url, anon_key


def _install_qt_message_handler() -> None:
    """Install a Qt message handler to capture stylesheet parsing warnings."""
    from PySide6.QtCore import qInstallMessageHandler, QtMsgType
    
    def _qt_message_handler(mode: QtMsgType, context, message: str) -> None:
        # Log all Qt messages for debugging stylesheet issues
        if "Could not parse stylesheet" in message:
            logging.warning("QSS PARSE WARNING: %s", message)
        elif mode == QtMsgType.QtWarningMsg:
            logging.warning("Qt WARNING: %s", message)
        elif mode == QtMsgType.QtCriticalMsg:
            logging.error("Qt CRITICAL: %s", message)
        elif mode == QtMsgType.QtFatalMsg:
            logging.critical("Qt FATAL: %s", message)
        elif mode == QtMsgType.QtInfoMsg:
            logging.info("Qt INFO: %s", message)
        else:
            logging.debug("Qt DEBUG: %s", message)
    
    qInstallMessageHandler(_qt_message_handler)


def _install_stylesheet_logger() -> None:
    """Install a wrapper on QPushButton.setStyleSheet to log stylesheet applications."""
    from PySide6.QtWidgets import QPushButton
    
    original_setstylesheet = QPushButton.setStyleSheet
    
    def _logged_setstylesheet(self, styleSheet: str):
        obj_name = self.objectName() or f"QPushButton@{id(self)}"
        logging.debug("Applying stylesheet to %s: %s", obj_name, styleSheet[:200])
        try:
            return original_setstylesheet(self, styleSheet)
        except Exception as e:
            logging.warning("Stylesheet parse failed for %s: %s | QSS: %s", obj_name, e, styleSheet)
            raise
    
    QPushButton.setStyleSheet = _logged_setstylesheet


def setup_logging() -> None:
    """Rotating log in app_data_dir()/logs; never log keys, passwords or tokens."""
    log_dir = app_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    handler = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # Also log to console in debug
    if os.environ.get("SI_PHASEPILOT_DEBUG"):
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        ))
        root.addHandler(console)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("supabase").setLevel(logging.WARNING)

    # Set up sys.excepthook to write tracebacks to logs/app.log
    def _excepthook(exc_type, exc_value, exc_traceback):
        logging.error(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback)
        )
        # Also print to stderr for visibility
        import traceback
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)

    sys.excepthook = _excepthook


def try_restore_session() -> dict | None:
    """Use stored refresh token if 'Remember me' was set."""
    settings = load_local_settings()
    if not settings.get("remember_me"):
        return None
    session = load_session()
    if not session:
        return None
    email, refresh_token = session
    try:
        result = restore_session(refresh_token)
        logging.info("Session restored for %s", email)
        # Sync session to data_review client
        try:
            sync_session_to_review_client()
            logging.info("Session synced to data_review client")
        except Exception as exc:
            logging.error("Failed to sync session to data_review client: %s", exc)
        return result
    except DataError as exc:
        logging.warning("Session restore failed: %s", exc)
        clear_session()
        settings["remember_me"] = False
        save_local_settings(settings)
        return None


# ===== SECTION: Main entry point =====

def main() -> int:
    check_python_version()

    url, anon_key = load_config()
    setup_logging()
    _install_qt_message_handler()
    _install_stylesheet_logger()
    logging.info("Qt message handler and stylesheet logger installed")
    init_client(url, anon_key)
    data_review.init_client(url, anon_key)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    # Load theme
    settings = load_local_settings()
    theme = settings.get("theme", "light")
    apply_theme(app, theme)

    # Device ID
    device_id = get_device_id()

    # Try to restore session
    session = try_restore_session()

    state = AppState(device_id=device_id)

    if session:
        state.user_id = session["user_id"]
        state.email = session["email"]
        # We have a valid session, proceed to main window
        window = MainWindow(state)
        window._topbar.set_theme(theme)  # Set top bar theme button text
        window.show()
    else:
        # Show login dialog
        login = LoginDialog()
        if login.exec() == LoginDialog.DialogCode.Accepted:
            state.user_id = login.user_id
            state.email = login.email
            if login.remember_me:
                save_session(login.email, login.refresh_token)
                settings["remember_me"] = True
            else:
                settings["remember_me"] = False
            save_local_settings(settings)
            # Sync session to data_review client
            try:
                sync_session_to_review_client()
                logging.info("Session synced to data_review client after login")
            except Exception as exc:
                logging.error("Failed to sync session to data_review client: %s", exc)
            window = MainWindow(state)
            window._topbar.set_theme(theme)  # Set top bar theme button text
            window.show()
        else:
            return 0

    return app.exec()


def save_session(email: str, refresh_token: str) -> None:
    """Store session via services (keyring)."""
    from services import save_session as svc_save_session
    svc_save_session(email, refresh_token)


if __name__ == "__main__":
    sys.exit(main())
