"""Shared confirmation dialog and asynchronous entry point for Secure Delete."""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from data_delete import (
    SecureDeleteBlockedError,
    preview_secure_delete,
    secure_delete,
)
from ui.shell import SyncState, get_main_window, run_async, show_error


_KIND_LABELS = {
    "project": "Project",
    "phase": "Phase",
    "command": "Command",
    "document": "Document",
    "baseline": "Approved Baseline",
}


# ===== SECTION: Confirmation dialog =====

class SecureDeleteDialog(QDialog):
    """Show exact impact and require deliberate typed confirmation."""

    def __init__(
        self,
        preview: dict[str, Any],
        protected: bool,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.preview = preview
        self.protected = protected
        self.setWindowTitle(f"Delete {_KIND_LABELS[preview['kind']]}")
        self.setMinimumSize(520, 380)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"You are deleting: {preview['name']}"))

        impact = QTextEdit()
        impact.setReadOnly(True)
        impact.setPlainText(self._impact_text(preview.get("impact", [])))
        layout.addWidget(QLabel("This will be removed or affected:"))
        layout.addWidget(impact, 1)

        warning = QLabel("This is permanent. It cannot be undone.")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        layout.addWidget(QLabel(f"Type {preview['name']} to confirm:"))
        self.name_edit = QLineEdit()
        self.name_edit.installEventFilter(self)
        self.name_edit.textChanged.connect(self._update_delete_enabled)
        layout.addWidget(self.name_edit)

        self.acknowledge = QCheckBox("I understand this cannot be undone.")
        self.acknowledge.setVisible(protected)
        self.acknowledge.stateChanged.connect(self._update_delete_enabled)
        layout.addWidget(self.acknowledge)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setDefault(False)
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.setEnabled(False)
        self.delete_button.setAutoDefault(False)
        self.delete_button.clicked.connect(self.accept)
        buttons.addWidget(self.delete_button)
        layout.addLayout(buttons)
        self.cancel_button.setFocus()

    @staticmethod
    def _impact_text(groups: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for group in groups:
            names = group.get("names", [])
            disposition = group.get("disposition", "")
            if not disposition and group.get("retained"):
                disposition = "retained"
            note = f" ({disposition})" if disposition else ""
            lines.append(f"- {len(names)} {group['label']}{note}")
            lines.extend(f"  - {name}" for name in names)
        return "\n".join(lines) or "- No additional records"

    def _update_delete_enabled(self, *_args: Any) -> None:
        exact_match = self.name_edit.text() == self.preview["name"]
        acknowledged = not self.protected or self.acknowledge.isChecked()
        self.delete_button.setEnabled(exact_match and acknowledged)

    def eventFilter(self, watched: Any, event: QEvent) -> bool:
        if watched is self.name_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                return True
        return super().eventFilter(watched, event)


# ===== SECTION: Delete workflow =====

def request_secure_delete(
    parent: QWidget,
    kind: str,
    item_id: str,
    protected: bool,
    writable: bool,
    on_deleted: Callable[[dict[str, Any]], None],
) -> None:
    """Preview, confirm, then delete through run_async."""
    main_window = get_main_window()
    if not writable or (
        main_window is not None
        and main_window.state.sync.get_state()
        in (SyncState.OFFLINE, SyncState.SAVING)
    ):
        show_error(parent, "Cannot delete while offline or saving.")
        return

    def _preview_loaded(preview: dict[str, Any]) -> None:
        if preview.get("active_run"):
            QMessageBox.warning(
                parent,
                "Cannot delete",
                "A Coder or Auditor run is active on this item. Stop the run first.",
            )
            return
        dialog = SecureDeleteDialog(preview, protected, parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        run_async(
            lambda: secure_delete(kind, item_id),
            on_success=lambda result: _delete_done(
                parent, result, on_deleted
            ),
            on_error=lambda exc: _delete_error(parent, exc),
        )

    run_async(
        lambda: preview_secure_delete(kind, item_id),
        on_success=_preview_loaded,
        on_error=lambda exc: show_error(
            parent, f"Could not load delete impact: {exc}"
        ),
    )


def _delete_done(
    parent: QWidget,
    result: dict[str, Any],
    on_deleted: Callable[[dict[str, Any]], None],
) -> None:
    on_deleted(result)
    orphan_files = result.get("orphan_files", [])
    if orphan_files:
        paths = "\n".join(orphan_files)
        QMessageBox.warning(
            parent,
            "Deleted with file cleanup warning",
            "The database records were deleted, but these Storage files could "
            "not be removed. They are logged as ORPHAN FILE:\n\n" + paths,
        )
    else:
        QMessageBox.information(parent, "Deleted", "The item was permanently deleted.")


def _delete_error(parent: QWidget, exc: Exception) -> None:
    if isinstance(exc, SecureDeleteBlockedError):
        QMessageBox.warning(parent, "Cannot delete", str(exc))
        return
    show_error(parent, f"Secure delete failed: {exc}")
