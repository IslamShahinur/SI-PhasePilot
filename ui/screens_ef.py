"""
ui/screens_ef.py — Screens E (Approved Baseline) and F (Critical Notes & Registers).
Phase 2 implementation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTextEdit, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFileDialog, QMessageBox,
    QGroupBox, QScrollArea, QSizePolicy, QCheckBox, QDialog,
    QInputDialog, QMenu,
)

import data
from data import (
    list_baselines,
    add_baseline,
    list_register_items,
    add_register_item,
    update_register_item,
    upload_file,
    download_file,
    ValidationError,
    ConflictError,
    OfflineError,
    DataError,
    RuleViolationError,
)
import services
from services import (
    APP_NAME,
    PHASE_STATUSES,
    STATUS_LABELS,
    NEXT_STATUSES,
    AUDIT_STATUSES,
    REGISTER_TYPES,
    REGISTER_STATUSES,
    SCREEN_ACCENTS,
    format_phase_label,
    git_available,
    validate_repo_path,
    git_capture,
    open_with_default_app,
    temp_dir,
    validate_attachment,
    copy_to_clipboard,
)
from ui.shell import (
    AppState,
    BaseScreen,
    run_async,
    show_error,
    confirm,
)
from ui.secure_delete import request_secure_delete

Row = dict[str, Any]
Rows = list[Row]

# Schema rev 1.3 phase statuses (services.STATUS_LABELS still holds the
# pre-1.3 names, so Screen E maps the current ones itself).
_PHASE_STATUS_LABELS: dict[str, str] = {
    "awaiting_task": "Awaiting Task",
    "coding_in_progress": "Coding In Progress",
    "coding_completed": "Coding Completed",
    "cleared": "Cleared",
}


# ===== SECTION: ScreenE — Approved Baseline =====

class ScreenE(BaseScreen):
    """Screen E: Approved Baseline."""

    screen_id = "E"
    title = "Approved Baseline"
    accent = SCREEN_ACCENTS["E"]

    def __init__(self, state: AppState | None = None):
        super().__init__(state)
        self._phase: Row | None = None
        self._git_request_generation = 0
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Header
        header = QHBoxLayout()
        title = QLabel("Approved Baseline")
        title.setStyleSheet(f"font-size: 14pt; font-weight: bold; color: {self.accent}; background-color: transparent;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # Phase info
        phase_info = QHBoxLayout()
        phase_info.addWidget(QLabel("Phase Status:"))
        self._phase_status_label = QLabel("-")
        phase_info.addWidget(self._phase_status_label)
        phase_info.addStretch()
        layout.addLayout(phase_info)

        # Repository path
        repo_row = QHBoxLayout()
        repo_row.addWidget(QLabel("Repository:"))
        self._repo_path_edit = QLineEdit()
        self._repo_path_edit.setPlaceholderText("Repository path...")
        repo_row.addWidget(self._repo_path_edit)

        self._select_repo_btn = QPushButton("Select Repository...")
        self._select_repo_btn.clicked.connect(self.select_repository)
        repo_row.addWidget(self._select_repo_btn)
        layout.addLayout(repo_row)

        # Git capture fields
        git_row = QHBoxLayout()
        git_row.addWidget(QLabel("Branch:"))
        self._branch_edit = QLineEdit()
        git_row.addWidget(self._branch_edit)

        git_row.addWidget(QLabel("HEAD:"))
        self._head_edit = QLineEdit()
        git_row.addWidget(self._head_edit)

        self._capture_btn = QPushButton("Capture Git")
        self._capture_btn.clicked.connect(self.capture_git)
        git_row.addWidget(self._capture_btn)
        layout.addLayout(git_row)

        tree_row = QHBoxLayout()
        tree_row.addWidget(QLabel("Tree Hash:"))
        self._tree_hash_edit = QLineEdit()
        tree_row.addWidget(self._tree_hash_edit)

        tree_row.addWidget(QLabel("Working Tree:"))
        self._working_tree_combo = QComboBox()
        self._working_tree_combo.addItems(["", "clean", "modified", "unknown"])
        self._working_tree_combo.setCurrentIndex(0)  # blank until Capture Git
        tree_row.addWidget(self._working_tree_combo)
        layout.addLayout(tree_row)

        # Approved summary and next notes
        summary_group = QGroupBox("Approved Summary")
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.setContentsMargins(4, 4, 4, 4)
        self._summary_edit = QTextEdit()
        self._summary_edit.setPlaceholderText("Summary of the approved baseline...")
        summary_layout.addWidget(self._summary_edit)
        layout.addWidget(summary_group)

        notes_group = QGroupBox("Next Phase Notes")
        notes_layout = QVBoxLayout(notes_group)
        notes_layout.setContentsMargins(4, 4, 4, 4)
        self._next_notes_edit = QTextEdit()
        self._next_notes_edit.setPlaceholderText("Notes for the next phase...")
        notes_layout.addWidget(self._next_notes_edit)
        layout.addWidget(notes_group)

        # Override checkbox. Colors come from the app theme
        # (shell._build_stylesheet QCheckBox rules), so this rule only adds
        # emphasis and a larger indicator; it stays visible in light and dark.
        self._override_check = QCheckBox("Override (documented reason required)")
        self._override_check.setStyleSheet("""
            QCheckBox {
                font-weight: bold;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 3px;
            }
        """)
        self._override_check.stateChanged.connect(self._on_override_changed)
        layout.addWidget(self._override_check)

        self._reason_edit = QLineEdit()
        self._reason_edit.setPlaceholderText("Override reason (required if checked)...")
        self._reason_edit.setEnabled(False)
        layout.addWidget(self._reason_edit)

        # Buttons
        btn_row = QHBoxLayout()
        self._save_baseline_btn = QPushButton("Save Baseline")
        self._save_baseline_btn.clicked.connect(self.save_baseline)
        btn_row.addWidget(self._save_baseline_btn)

        self._history_btn = QPushButton("View Baseline History...")
        self._history_btn.clicked.connect(self.show_baseline_history)
        btn_row.addWidget(self._history_btn)
        layout.addLayout(btn_row)

        self._feedback_label = QLabel("")
        self._feedback_label.setWordWrap(True)
        layout.addWidget(self._feedback_label)

        self._set_writable(False)

    def on_show(self) -> None:
        if self.state and self.state.project:
            # Adopt the phase the Top Bar already selected: phase_chosen only
            # reaches screens that are already loaded, so a first visit has to
            # pick it up here or the form stays empty.
            if self.state.phase:
                self._phase = self.state.phase
            if self._phase:
                self._load_phase_data()
                self._sync_writable()
            else:
                self._load_phase_form()

    def on_project_changed(self, project: Row | None) -> None:
        self._git_request_generation += 1
        self._phase = None
        self._clear_ui()
        self._sync_writable()
        # Do not load phases here; the shell loads phases and calls on_phase_changed.
        # on_show will handle the case where the screen is opened before phases are loaded.

    def on_phase_changed(self, phase: Row | None) -> None:
        self._git_request_generation += 1
        self._phase = phase
        if phase:
            self._load_phase_data()
        else:
            self._clear_ui()
        self._sync_writable()

    def reload(self) -> None:
        if self.state and self.state.project and self._phase:
            self._load_phase_data()

    def _load_phase_form(self) -> None:
        """Load phases for the current project and select the first one."""
        if not (self.state and self.state.project):
            return
        run_async(
            lambda: data.list_phases(self.state.project["id"]),
            on_success=self._on_phases_loaded,
            on_error=lambda exc: show_error(self, f"Failed to load phases: {exc}"),
        )

    def _on_phases_loaded(self, phases: Rows) -> None:
        """Adopt the current phase (or the first active one) and load it."""
        if not phases:
            return
        if not (self.state and self.state.phase):
            for ph in phases:
                if not ph.get("archived_at"):
                    if self.state:
                        self.state.phase = ph
                    break
        if self.state and self.state.phase:
            self._phase = self.state.phase
            self._load_phase_data()
            self._sync_writable()

    def _sync_writable(self) -> None:
        """Re-apply the sync gate after the phase presence changed."""
        if self.state:
            self._set_writable(self.state.sync.is_writable())

    def _load_phase_data(self) -> None:
        """Load all data for the current phase."""
        if not self._phase:
            return
        # Load baselines
        run_async(
            lambda: list_baselines(self.state.project["id"], self._phase["id"]),
            on_success=self._on_baselines_loaded,
            on_error=lambda exc: show_error(self, f"Failed to load baselines: {exc}"),
        )
        # Update phase status label
        status = self._phase.get("status", "")
        self._phase_status_label.setText(
            _PHASE_STATUS_LABELS.get(status) or STATUS_LABELS.get(status, status)
        )
        self._update_git_fields()

    def _on_baselines_loaded(self, baselines: Rows) -> None:
        """Update baselines count display."""
        self._baseline_count = len(baselines)

    def _update_git_fields(self) -> None:
        """Try to populate Git fields from the repo path setting."""
        if not (self.state and self.state.project):
            return
        self._git_request_generation += 1
        generation = self._git_request_generation
        project_id = self.state.project["id"]
        device_id = services.get_device_id()
        run_async(
            lambda: data.get_repo_path(project_id, device_id),
            on_success=lambda row, g=generation: self._on_repo_path_loaded(row, g),
            on_error=lambda exc, g=generation: self._on_repo_path_error(exc, g),
        )

    def _on_repo_path_loaded(self, row: Row | None, generation: int) -> None:
        """After loading repo path, populate fields."""
        if generation != self._git_request_generation:
            return
        if row:
            path = row.get("local_path", "")
            self._repo_path_edit.setText(path)
            # Capture Git info for Branch and HEAD, but leave Working Tree blank until user clicks Capture Git
            if path:
                run_async(
                    lambda: services.git_capture(path) if services.git_available() else None,
                    on_success=lambda result, g=generation: (
                        self._on_git_captured_partial(result, g) if result else None
                    ),
                    on_error=lambda exc, g=generation: self._on_git_capture_error(
                        exc, "Git capture failed", g
                    ),
                )

    def _on_repo_path_error(self, exc: Exception, generation: int) -> None:
        if generation == self._git_request_generation:
            show_error(self, f"Failed to load repository path: {exc}")

    def _on_git_capture_error(
        self, exc: Exception, message: str, generation: int
    ) -> None:
        if generation == self._git_request_generation:
            show_error(self, f"{message}: {exc}")

    def _on_git_captured_partial(self, result: Any, generation: int) -> None:
        """Handle captured Git info (Branch/HEAD only, Working Tree left blank)."""
        if generation != self._git_request_generation:
            return
        if result.error:
            show_error(self, f"Git capture error: {result.error}")
            return
        self._branch_edit.setText(result.branch)
        self._head_edit.setText(result.head)
        self._tree_hash_edit.setText(result.tree_hash)
        # Working Tree intentionally left blank
        self._feedback_label.setText("Repository Git details filled.")

    def _on_repo_validated(self, git_data: Any, generation: int) -> None:
        """Handle validated repo info after path selection."""
        if generation != self._git_request_generation:
            return
        if git_data:
            # git_data is a GitInfo dataclass, not a dict. Use attributes.
            if git_data.error:
                show_error(self, f"Git capture error: {git_data.error}")
                return
            self._branch_edit.setText(git_data.branch)
            self._head_edit.setText(git_data.head)
            self._tree_hash_edit.setText(git_data.tree_hash)
            # Working Tree stays blank until Capture Git is clicked.
            self._feedback_label.setText("Repository validated successfully.")
        else:
            show_error(self, "Repository validation produced no data.")

    def _clear_ui(self) -> None:
        """Clear all UI elements."""
        self._repo_path_edit.clear()
        self._branch_edit.clear()
        self._head_edit.clear()
        self._tree_hash_edit.clear()
        self._working_tree_combo.setCurrentIndex(0)  # blank
        self._summary_edit.clear()
        self._next_notes_edit.clear()
        self._override_check.setChecked(False)
        self._reason_edit.clear()
        self._reason_edit.setEnabled(False)
        self._feedback_label.clear()

    def select_repository(self) -> None:
        """Select a repository path manually."""
        try:
            # Guard: check if writable
            if not self.state.sync.is_writable():
                show_error(self, "Cannot write while offline or saving.")
                return
            path = QFileDialog.getExistingDirectory(self, "Select Repository Root")
            if path:
                self._git_request_generation += 1
                generation = self._git_request_generation
                self._repo_path_edit.setText(path)
                # Validate and capture Git info - do the work in the worker lambda
                run_async(
                    lambda: services.git_capture(path) if services.git_available() else None,
                    on_success=lambda result, g=generation: (
                        self._on_repo_validated(result, g) if result else None
                    ),
                    on_error=lambda exc, g=generation: self._on_git_capture_error(
                        exc, "Invalid repository", g
                    ),
                )
        except Exception:
            logging.exception("select_repository failed")
            show_error(self, "An unexpected error occurred while selecting repository.")

    def capture_git(self) -> None:
        """Capture Git information from the current repository path."""
        try:
            # Guard: check if writable
            if not self.state.sync.is_writable():
                show_error(self, "Cannot write while offline or saving.")
                return
            path = self._repo_path_edit.text().strip()
            if not path:
                show_error(self, "Please select a repository path first.")
                return
            self._git_request_generation += 1
            generation = self._git_request_generation
            # Capture Git asynchronously
            run_async(
                lambda: services.git_capture(path) if services.git_available() else None,
                on_success=lambda result, g=generation: (
                    self._on_git_captured(result, g) if result else None
                ),
                on_error=lambda exc, g=generation: self._on_git_capture_error(
                    exc, "Git error", g
                ),
            )
        except Exception:
            logging.exception("capture_git failed")
            show_error(self, "An unexpected error occurred while capturing Git info.")

    def _on_git_captured(self, result: Any, generation: int) -> None:
        """Handle captured Git info (on UI thread)."""
        if generation != self._git_request_generation:
            return
        if result.error:
            show_error(self, f"Git capture error: {result.error}")
            return
        self._branch_edit.setText(result.branch)
        self._head_edit.setText(result.head)
        self._tree_hash_edit.setText(result.tree_hash)
        self._working_tree_combo.setCurrentText(result.working_tree)
        self._feedback_label.setText("Git information captured.")

    def save_baseline(self) -> None:
        """Save the baseline record."""
        try:
            if not (self.state and self.state.project and self._phase):
                return
            # Guard: check if writable (F-01 Blocker)
            if not self.state.sync.is_writable():
                show_error(self, "Cannot write while offline or saving.")
                return
            # Baseline rule (schema rev 1.3): the database trigger
            # pp_baseline_guard requires a passed review for this attempt or a
            # documented override. The UI keeps the override reason check.
            override_used = self._override_check.isChecked()
            if override_used and not self._reason_edit.text().strip():
                show_error(self, "Override requires a written reason.")
                return

            # Working Tree must be captured first (blank until Capture Git)
            working_tree = self._working_tree_combo.currentText()
            if not working_tree:
                show_error(
                    self,
                    "Working Tree is not set. Click Capture Git or choose a state first.",
                )
                return
            # Warn if working tree is modified
            if working_tree == "modified" and not confirm(
                self,
                "The working tree is modified. Are you sure you want to save this baseline?",
            ):
                return

            # Build fields dict
            fields = {
                "attempt_no": self._phase["current_attempt"],
                "approved_summary": self._summary_edit.toPlainText(),
                "next_phase_notes": self._next_notes_edit.toPlainText(),
                "repo_path": self._repo_path_edit.text().strip(),
                "branch": self._branch_edit.text().strip(),
                "git_head": self._head_edit.text().strip(),
                "git_tree_hash": self._tree_hash_edit.text().strip(),
                "working_tree": working_tree,
                "override_used": override_used,
            }
            if override_used:
                fields["override_reason"] = self._reason_edit.text().strip()

            run_async(
                lambda: add_baseline(
                    self.state.project["id"],
                    self._phase["id"],
                    self._phase["current_attempt"],
                    fields,
                ),
                on_success=lambda row: self._on_baseline_saved(row),
                on_error=self._on_baseline_error,
            )
        except Exception:
            logging.exception("save_baseline failed")
            show_error(self, "An unexpected error occurred while saving baseline.")

    def _on_baseline_saved(self, row: Row) -> None:
        """After saving baseline, confirm the write.

        Schema rev 1.3 has no 'baseline_approved' status: the phase is
        cleared later by Screen D (Mark Review Passed), which requires this
        baseline to exist first.
        """
        attempt = row.get("attempt_no", "?")
        self._feedback_label.setText(f"Baseline saved for attempt {attempt}.")

    def _on_baseline_error(self, exc: Exception) -> None:
        if isinstance(exc, RuleViolationError):
            show_error(self, f"Baseline not allowed: {exc}")
        elif isinstance(exc, ConflictError):
            show_error(self, str(exc))
        elif isinstance(exc, ValidationError):
            show_error(self, str(exc))
        elif isinstance(exc, OfflineError):
            show_error(self, "Offline — cannot complete action.")
        else:
            show_error(self, f"Baseline save failed: {exc}")

    def show_baseline_history(self) -> None:
        """Show baseline history dialog."""
        try:
            if not (self.state and self.state.project):
                return
            dialog = QDialog(self)
            dialog.setWindowTitle("Baseline History")
            dialog.setMinimumSize(800, 400)
            layout = QVBoxLayout(dialog)

            table = QTableWidget(0, 7)
            table.setHorizontalHeaderLabels([
                "Phase", "Attempt", "Git HEAD", "Tree Hash", "Override", "Working Tree", "Date"
            ])
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            baseline_rows: Rows = []
            table.customContextMenuRequested.connect(
                lambda pos: self._show_baseline_history_menu(
                    table, dialog, baseline_rows, pos
                )
            )

            def _on_baselines_loaded(rows: Rows) -> None:
                baseline_rows[:] = rows
                self._populate_baseline_history(table, rows)

            run_async(
                lambda: list_baselines(self.state.project["id"], self._phase["id"] if self._phase else None),
                on_success=_on_baselines_loaded,
                on_error=lambda exc: show_error(dialog, f"Failed to load history: {exc}"),
            )

            btn = QPushButton("Close")
            btn.clicked.connect(dialog.accept)
            layout.addWidget(table)
            layout.addWidget(btn)
            dialog.exec()
        except Exception:
            logging.exception("show_baseline_history failed")
            show_error(self, "An unexpected error occurred while showing baseline history.")

    def _show_baseline_history_menu(
        self, table: QTableWidget, dialog: QDialog, rows: Rows, pos: Any
    ) -> None:
        item = table.itemAt(pos)
        if item is None or item.row() >= len(rows):
            return
        baseline = rows[item.row()]
        menu = QMenu(self)
        delete_action = menu.addAction("Delete...")
        writable = bool(self.state and self.state.sync.is_writable())
        delete_action.setEnabled(writable)
        delete_action.triggered.connect(
            lambda: request_secure_delete(
                self,
                "baseline",
                baseline["id"],
                protected=True,
                writable=writable,
                on_deleted=lambda _result: (
                    dialog.accept(),
                    self._load_phase_data(),
                ),
            )
        )
        menu.exec(table.viewport().mapToGlobal(pos))

    def _populate_baseline_history(self, table: QTableWidget, rows: Rows) -> None:
        """Populate the baseline history table."""
        table.setRowCount(len(rows))
        for row_idx, baseline in enumerate(rows):
            table.setItem(row_idx, 0, QTableWidgetItem(f"Phase {baseline.get('phase_id', '?')}"))
            table.setItem(row_idx, 1, QTableWidgetItem(str(baseline.get("attempt_no", "?"))))
            table.setItem(row_idx, 2, QTableWidgetItem(baseline.get("git_head", "")[:8] + "..." if len(baseline.get("git_head", "")) > 8 else baseline.get("git_head", "")))
            table.setItem(row_idx, 3, QTableWidgetItem(baseline.get("git_tree_hash", "")[:8] + "..." if len(baseline.get("git_tree_hash", "")) > 8 else baseline.get("git_tree_hash", "")))
            override = "YES" if baseline.get("override_used") else "NO"
            table.setItem(row_idx, 4, QTableWidgetItem(override))
            table.setItem(row_idx, 5, QTableWidgetItem(baseline.get("working_tree", "-").capitalize()))
            date = baseline.get("created_at", "")[:19] if baseline.get("created_at") else ""
            table.setItem(row_idx, 6, QTableWidgetItem(date))

    def _on_override_changed(self, state: int) -> None:
        """Enable/disable reason field based on override checkbox."""
        self._reason_edit.setEnabled(state == Qt.CheckState.Checked.value)

    def _set_writable(self, writable: bool) -> None:
        has_phase = self._phase is not None
        self._capture_btn.setEnabled(writable and has_phase)
        self._save_baseline_btn.setEnabled(writable and has_phase)
        self._summary_edit.setEnabled(writable and has_phase)
        self._next_notes_edit.setEnabled(writable and has_phase)
        self._override_check.setEnabled(writable and has_phase)
        self._reason_edit.setEnabled(writable and has_phase and self._override_check.isChecked())
        self._select_repo_btn.setEnabled(writable and has_phase)
        self._repo_path_edit.setEnabled(writable and has_phase)

    def set_writable(self, writable: bool) -> None:
        self._set_writable(writable)


# ===== SECTION: ScreenF — Critical Notes & Registers =====

class ScreenF(BaseScreen):
    """Screen F: Critical Notes & Registers."""

    screen_id = "F"
    title = "Critical Notes & Registers"
    accent = SCREEN_ACCENTS["F"]

    def __init__(self, state: AppState | None = None):
        super().__init__(state)
        self._phase: Row | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Header
        header = QHBoxLayout()
        title = QLabel("Critical Notes & Registers")
        title.setStyleSheet(f"font-size: 14pt; font-weight: bold; color: {self.accent}; background-color: transparent;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # Filters
        filters_layout = QHBoxLayout()
        filters_layout.addWidget(QLabel("Type:"))
        self._type_filter = QComboBox()
        self._type_filter.addItem("All types", None)
        for t in REGISTER_TYPES:
            self._type_filter.addItem(t.replace("_", " ").title(), t)
        self._type_filter.currentIndexChanged.connect(self.apply_filters)
        filters_layout.addWidget(self._type_filter)

        filters_layout.addWidget(QLabel("Status:"))
        self._status_filter = QComboBox()
        self._status_filter.addItem("All statuses", None)
        for s in REGISTER_STATUSES:
            self._status_filter.addItem(s.replace("_", " ").title(), s)
        self._status_filter.currentIndexChanged.connect(self.apply_filters)
        filters_layout.addWidget(self._status_filter)

        filters_layout.addWidget(QLabel("Search:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search...")
        self._search_edit.textChanged.connect(self.apply_filters)
        filters_layout.addWidget(self._search_edit)

        self._add_btn = QPushButton("Add Item")
        self._add_btn.clicked.connect(self.add_item)
        filters_layout.addWidget(self._add_btn)
        filters_layout.addStretch()
        layout.addLayout(filters_layout)

        # Items table
        self._items_table = QTableWidget(0, 5)
        self._items_table.setHorizontalHeaderLabels([
            "Type", "Item / Note", "Target Phase", "Status", "Date"
        ])
        self._items_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._items_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._items_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._items_table.itemSelectionChanged.connect(self._on_item_selected)
        layout.addWidget(self._items_table, 1)

        # Action buttons
        btn_row = QHBoxLayout()
        self._edit_btn = QPushButton("Edit")
        self._edit_btn.clicked.connect(self.edit_item)
        btn_row.addWidget(self._edit_btn)

        self._change_status_btn = QPushButton("Change Status")
        self._change_status_btn.clicked.connect(self.change_status)
        btn_row.addWidget(self._change_status_btn)

        self._archive_btn = QPushButton("Archive")
        self._archive_btn.clicked.connect(self.archive_item)
        btn_row.addWidget(self._archive_btn)

        self._save_btn = QPushButton("Save")
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)
        layout.addLayout(btn_row)

        self._set_writable(False)

    def on_show(self) -> None:
        if self.state and self.state.project:
            self._load_items()

    def on_project_changed(self, project: Row | None) -> None:
        self._phase = None
        self._clear_ui()
        if project:
            self._load_items()

    def on_phase_changed(self, phase: Row | None) -> None:
        self._phase = phase
        self._load_items()

    def reload(self) -> None:
        if self.state and self.state.project:
            self._load_items()

    def _load_items(self) -> None:
        """Load register items for the current project."""
        if not self.state or not self.state.project:
            return
        item_type = self._type_filter.currentData()
        status = self._status_filter.currentData()
        search = self._search_edit.text() or None
        run_async(
            lambda: list_register_items(
                self.state.project["id"],
                item_type=item_type,
                status=status,
                search=search,
            ),
            on_success=self._on_items_loaded,
            on_error=lambda exc: show_error(self, f"Failed to load items: {exc}"),
        )

    def _on_items_loaded(self, items: Rows) -> None:
        """Populate the items table."""
        self._items = items
        self._items_table.setRowCount(len(items))
        for row_idx, item in enumerate(items):
            self._items_table.setItem(row_idx, 0, QTableWidgetItem(item.get("item_type", "").replace("_", " ").title()))
            desc = item.get("description", "")
            if len(desc) > 50:
                desc = desc[:50] + "..."
            self._items_table.setItem(row_idx, 1, QTableWidgetItem(desc))
            phase_no = item.get("phase_no", "")
            self._items_table.setItem(row_idx, 2, QTableWidgetItem(f"Phase {phase_no}" if phase_no else "-"))
            self._items_table.setItem(row_idx, 3, QTableWidgetItem(item.get("status", "").replace("_", " ").title()))
            date = item.get("created_at", "")[:19] if item.get("created_at") else ""
            self._items_table.setItem(row_idx, 4, QTableWidgetItem(date))

    def apply_filters(self) -> None:
        """Apply filters to the register items (public interface)."""
        self._load_items()

    def change_status(self) -> None:
        """Change the status of the selected register item."""
        # Guard: check if writable
        if not self.state.sync.is_writable():
            show_error(self, "Cannot write while offline or saving.")
            return
        if not (self.state and self.state.project):
            return
        row = self._items_table.currentRow()
        if row < 0 or row >= len(self._items):
            show_error(self, "Select an item to change status.")
            return
        item = self._items[row]
        # Get new status
        new_status, ok = QInputDialog.getItem(
            self,
            "Change Status",
            "Select new status:",
            REGISTER_STATUSES,
            REGISTER_STATUSES.index(item.get("status", "open")),
            False,
        )
        if not ok:
            return
        run_async(
            lambda: update_register_item(
                item["id"], item["version"], {"status": new_status}
            ),
            on_success=lambda row: self._on_item_status_changed(row),
            on_error=self._on_item_error,
        )

    def _clear_ui(self) -> None:
        """Clear all UI elements."""
        self._items_table.setRowCount(0)
        self._items = []

    def add_item(self) -> None:
        """Add a new register item."""
        # Guard: check if writable
        if not self.state.sync.is_writable():
            show_error(self, "Cannot write while offline or saving.")
            return
        if not (self.state and self.state.project):
            return
        from PySide6.QtWidgets import QInputDialog
        # Get item type
        item_type, ok = QInputDialog.getItem(
            self,
            "New Item",
            "Select type:",
            REGISTER_TYPES,
            0,
            False,
        )
        if not ok:
            return
        # Get description
        desc, ok = QInputDialog.getText(
            self,
            "New Item",
            "Enter description:",
        )
        if not ok or not desc.strip():
            return
        # Get target phase asynchronously
        run_async(
            lambda: data.list_phases(self.state.project["id"]),
            on_success=lambda phases: self._on_phases_loaded_for_item(phases, item_type, desc),
            on_error=lambda exc: show_error(self, f"Failed to load phases: {exc}"),
        )

    def _on_phases_loaded_for_item(self, phases: Rows, item_type: str, desc: str) -> None:
        """After loading phases, prompt for target phase selection."""
        from PySide6.QtWidgets import QInputDialog
        phase_id = None
        if phases:
            phase_options = [f"Phase {p['phase_no']} - {p.get('title', p.get('status', ''))}" for p in phases]
            phase_opt, ok = QInputDialog.getItem(
                self,
                "New Item",
                "Target phase (optional):",
                ["None"] + phase_options,
                0,
                False,
            )
            if ok and phase_opt != "None":
                # Find the selected phase
                for p in phases:
                    label = f"Phase {p['phase_no']} - {p.get('title', p.get('status', ''))}"
                    if label == phase_opt:
                        phase_id = p["id"]
                        break
        # Now add the item
        run_async(
            lambda: add_register_item(
                self.state.project["id"],
                item_type,
                desc,
                phase_id=phase_id,
            ),
            on_success=lambda row: self._on_item_added(row),
            on_error=self._on_item_error,
        )

    def _on_item_added(self, item: Row) -> None:
        """After adding, reload items."""
        self._load_items()

    def edit_item(self) -> None:
        """Edit a selected item."""
        # Guard: check if writable
        if not self.state.sync.is_writable():
            show_error(self, "Cannot write while offline or saving.")
            return
        row = self._items_table.currentRow()
        if row < 0 or row >= len(self._items):
            show_error(self, "Select an item to edit.")
            return
        item = self._items[row]
        from PySide6.QtWidgets import QInputDialog, QSpinBox

        # Edit description
        desc, ok = QInputDialog.getMultiLineText(
            self,
            "Edit Item",
            "Description:",
            item.get("description", ""),
        )
        if not ok:
            return

        # Edit notes
        notes, ok = QInputDialog.getMultiLineText(
            self,
            "Edit Item",
            "Notes:",
            item.get("notes", ""),
        )
        if not ok:
            return

        run_async(
            lambda: update_register_item(
                item["id"],
                item["version"],
                {"description": desc, "notes": notes},
            ),
            on_success=lambda row: self._on_item_updated(row),
            on_error=self._on_item_error,
        )

    def _on_item_updated(self, updated: Row) -> None:
        """After updating, reload items."""
        self._load_items()

    def _on_item_status_changed(self, row: Row) -> None:
        """After changing item status, reload items."""
        self._load_items()

    def archive_item(self) -> None:
        """Archive a selected item."""
        row = self._items_table.currentRow()
        if row < 0 or row >= len(self._items):
            show_error(self, "Select an item to archive.")
            return
        item = self._items[row]
        if not confirm(self, "Archive this item? It will be hidden."):
            return
        run_async(
            lambda: update_register_item(
                item["id"],
                item["version"],
                {"archived_at": datetime.now(timezone.utc).isoformat()},
            ),
            on_success=lambda row: self._on_item_archived(row),
            on_error=self._on_item_error,
        )

    def _on_item_archived(self, updated: Row) -> None:
        """After archiving, reload items."""
        self._load_items()

    def _on_save(self) -> None:
        """Save changes (no-op for now, items auto-save)."""
        QMessageBox.information(self, "Save", "Items are saved automatically.")

    def _on_item_selected(self) -> None:
        """Update button states based on selection."""
        row = self._items_table.currentRow()
        self._edit_btn.setEnabled(row >= 0)
        self._archive_btn.setEnabled(row >= 0)
        self._change_status_btn.setEnabled(row >= 0)

    def _on_item_error(self, exc: Exception) -> None:
        if isinstance(exc, ConflictError):
            show_error(self, str(exc))
        elif isinstance(exc, ValidationError):
            show_error(self, str(exc))
        elif isinstance(exc, OfflineError):
            show_error(self, "Offline — cannot complete action.")
        else:
            show_error(self, f"Action failed: {exc}")

    def _set_writable(self, writable: bool) -> None:
        self._add_btn.setEnabled(writable)
        self._edit_btn.setEnabled(writable and self._items_table.currentRow() >= 0)
        self._archive_btn.setEnabled(writable and self._items_table.currentRow() >= 0)
        self._change_status_btn.setEnabled(writable and self._items_table.currentRow() >= 0)
        self._save_btn.setEnabled(writable)

    def set_writable(self, writable: bool) -> None:
        self._set_writable(writable)