"""
ui/screens_cd.py — Screen C: Phase Worklist (Teal).

Phase 4B: the per-attempt task ladder lives on Screen C. All status logic
comes from workflow.py; all attempt-aware data access goes through
data_review.py. The old worklist table is gone: the Task dropdown replaces
it and each task keeps its own command/report records.
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QGroupBox, QSizePolicy, QDialog, QInputDialog, QFileDialog,
    QMenu,
)

import data
import data_review
from data_review import (
    list_commands,
    add_command,
    list_reports,
    add_report,
    get_review_record,
    set_phase_status,
    ValidationError,
    ConflictError,
    OfflineError,
    RuleViolationError,
)
import workflow
from workflow import (
    all_task_names,
    can_mark_completed,
    can_new_phase,
    can_pick_task,
    next_phase_status,
)
import services
from services import SCREEN_ACCENTS, copy_to_clipboard, validate_attachment
from ui.shell import (
    AppState,
    BaseScreen,
    get_main_window,
    run_async,
    show_error,
    confirm,
)
from ui.secure_delete import request_secure_delete

Row = dict[str, Any]

# ===== SECTION: Screen C constants =====

# Phase status values the User may pick on Screen C (patch section 1).
# "cleared" is a read-only badge: never in the dropdown, never pickable.
_C_STATUS_ORDER: list[str] = ["awaiting_task", "coding_in_progress", "coding_completed"]
_C_STATUS_LABELS: dict[str, str] = {
    "awaiting_task": "Awaiting for Task",
    "coding_in_progress": "Coding In Progress",
    "coding_completed": "Coding Completed",
}

# Task label -> attempt_no. "No Task" means no attempt picked yet.
_TASK_ATTEMPT: dict[str, int | None] = {
    "No Task": None,
    "Coding": 0,
    "Re-Fix-1": 1,
    "Re-Fix-2": 2,
    "Re-Fix-3": 3,
}


# ===== SECTION: ScreenC — Phase Worklist =====

class ScreenC(BaseScreen):
    """Screen C: Phase Worklist (frame C of migration/06, patched by CR-017)."""

    screen_id = "C"
    title = "Phase Worklist"
    accent = SCREEN_ACCENTS["C"]

    def __init__(self, state: AppState | None = None):
        super().__init__(state)
        self._phase: Row | None = None
        self._task_attempt: int | None = None
        self._has_report = False
        self._review_results: dict[int, str] = {}
        self._writable = False
        self._save_in_flight = False
        self._previous_task_index = 0
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        header = QLabel("Phase")
        header.setObjectName("screenTitle")
        header.setStyleSheet(
            f"font-size: 14pt; font-weight: bold; color: {self.accent}; "
            "background-color: transparent;"
        )
        layout.addWidget(header)

        # --- Phase status + task + actions ---
        control = QHBoxLayout()
        control.addWidget(QLabel("Phase Status:"))
        self._status_combo = QComboBox()
        for status in _C_STATUS_ORDER:
            self._status_combo.addItem(_C_STATUS_LABELS[status], status)
        self._status_combo.currentIndexChanged.connect(self._on_status_picked)
        control.addWidget(self._status_combo)
        self._phase_menu_btn = QPushButton("...")
        self._phase_menu_btn.setToolTip("Phase actions")
        self._phase_menu_btn.clicked.connect(self._show_phase_menu)
        control.addWidget(self._phase_menu_btn)

        self._cleared_badge = QLabel("Cleared (read-only)")
        self._cleared_badge.setStyleSheet("font-weight: bold; color: #666666;")
        self._cleared_badge.hide()
        control.addWidget(self._cleared_badge)

        self._new_phase_btn = QPushButton("New Phase")
        self._new_phase_btn.clicked.connect(self.new_phase)
        control.addWidget(self._new_phase_btn)

        control.addWidget(QLabel("Task:"))
        self._task_combo = QComboBox()
        self._task_combo.setModel(self._task_model())
        self._task_combo.currentIndexChanged.connect(self._on_task_picked)
        control.addWidget(self._task_combo, 1)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.reload)
        control.addWidget(self._refresh_btn)
        control.addStretch()
        layout.addLayout(control)

        # --- Notes (per phase, same for every task) ---
        notes_group = QGroupBox("Acceptance Criteria / Notes")
        notes_layout = QVBoxLayout(notes_group)
        notes_layout.setContentsMargins(4, 4, 4, 4)
        self._notes_edit = QTextEdit()
        self._notes_edit.setPlaceholderText("Acceptance criteria or notes for this phase...")
        self._notes_edit.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding
        )
        self._notes_edit.textChanged.connect(self._refresh_buttons)
        notes_layout.addWidget(self._notes_edit)
        self._save_notes_btn = QPushButton("Save Notes")
        self._save_notes_btn.clicked.connect(self.save_worklist_notes)
        notes_layout.addWidget(self._save_notes_btn)
        layout.addWidget(notes_group)

        # --- Coder Command (per task) ---
        cmd_group = QGroupBox("Coder Command")
        cmd_layout = QVBoxLayout(cmd_group)
        cmd_layout.setContentsMargins(4, 4, 4, 4)
        self._cmd_label = QLabel("(Task: No Task)")
        cmd_layout.addWidget(self._cmd_label)
        self._command_edit = QTextEdit()
        self._command_edit.setPlaceholderText("Paste or type the coder command...")
        self._command_edit.textChanged.connect(self._refresh_buttons)
        cmd_layout.addWidget(self._command_edit)
        cmd_btn_row = QHBoxLayout()
        self._save_command_btn = QPushButton("Save Command")
        self._save_command_btn.clicked.connect(self.save_command)
        cmd_btn_row.addWidget(self._save_command_btn)
        self._copy_command_btn = QPushButton("Copy Command")
        self._copy_command_btn.clicked.connect(self.copy_command)
        cmd_btn_row.addWidget(self._copy_command_btn)
        self._command_history_btn = QPushButton("History...")
        self._command_history_btn.clicked.connect(self.show_command_history)
        cmd_btn_row.addWidget(self._command_history_btn)
        cmd_layout.addLayout(cmd_btn_row)
        layout.addWidget(cmd_group)

        # --- Coder Report (per task, last section of Screen C) ---
        rep_group = QGroupBox("Coder Report")
        rep_layout = QVBoxLayout(rep_group)
        rep_layout.setContentsMargins(4, 4, 4, 4)
        self._rep_label = QLabel("(Task: No Task)")
        rep_layout.addWidget(self._rep_label)
        self._report_edit = QTextEdit()
        self._report_edit.setPlaceholderText("Paste or type the coder report...")
        self._report_edit.textChanged.connect(self._refresh_buttons)
        rep_layout.addWidget(self._report_edit)
        rep_btn_row = QHBoxLayout()
        self._attach_report_btn = QPushButton("Attach File...")
        self._attach_report_btn.clicked.connect(self.attach_report)
        rep_btn_row.addWidget(self._attach_report_btn)
        self._paste_report_btn = QPushButton("Paste")
        self._paste_report_btn.clicked.connect(self.paste_report)
        rep_btn_row.addWidget(self._paste_report_btn)
        self._save_report_btn = QPushButton("Save")
        self._save_report_btn.clicked.connect(self.save_report)
        rep_btn_row.addWidget(self._save_report_btn)
        self._copy_report_btn = QPushButton("Copy")
        self._copy_report_btn.clicked.connect(self.copy_report)
        rep_btn_row.addWidget(self._copy_report_btn)
        self._report_history_btn = QPushButton("History...")
        self._report_history_btn.clicked.connect(self.show_report_history)
        rep_btn_row.addWidget(self._report_history_btn)
        rep_layout.addLayout(rep_btn_row)
        layout.addWidget(rep_group)

        # --- COMPLETED (big button) ---
        self._completed_btn = QPushButton("COMPLETED")
        self._completed_btn.setObjectName("completedButton")
        self._completed_btn.setStyleSheet(
            f"QPushButton {{ font-size: 13pt; font-weight: bold; padding: 10px; "
            f"background-color: {self.accent}; color: white; }}"
        )
        self._completed_btn.clicked.connect(self.mark_completed)
        layout.addWidget(self._completed_btn)

        self._set_writable(False)

    # -- task model --

    def _task_model(self) -> QStandardItemModel:
        model = QStandardItemModel()
        for label in workflow.all_task_names():
            item = QStandardItem(label)
            item.setData(_TASK_ATTEMPT[label], Qt.ItemDataRole.UserRole)
            model.appendRow(item)
        return model

    def _refresh_task_model(self) -> None:
        """Re-enable/disable task items according to the review results."""
        model = self._task_combo.model()
        if not isinstance(model, QStandardItemModel):
            return
        for row in range(model.rowCount()):
            item = model.item(row)
            attempt = _TASK_ATTEMPT[item.text()]
            ok = attempt is None or workflow.can_pick_task(attempt, self._review_results)
            item.setEnabled(ok)

    # -- contract hooks --

    def on_show(self) -> None:
        self.reload()

    def on_project_changed(self, project: Row | None) -> None:
        self._phase = None
        self._task_attempt = None
        self._has_report = False
        self._clear_ui()
        if project:
            self._load_phase_form()

    def on_phase_changed(self, phase: Row | None) -> None:
        self._phase = phase
        self._task_attempt = None
        self._has_report = False
        if phase:
            self._load_phase_data()
        else:
            self._clear_ui()

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

    def _on_phases_loaded(self, phases: list[Row]) -> None:
        if not phases:
            if not (self.state and self.state.project):
                return
            if not confirm(self, "No phases exist yet. Create Phase 1?"):
                return
            run_async(
                lambda: data.create_phase(self.state.project["id"], 1),
                on_success=self._on_phase_created,
                on_error=lambda exc: show_error(self, f"Failed to create phase: {exc}"),
            )
            return
        for ph in phases:
            if not ph.get("archived_at"):
                if self.state:
                    self.state.phase = ph
                break

    def _on_phase_created(self, new_phase: Row) -> None:
        if not (self.state and self.state.project):
            return
        run_async(
            lambda: data.list_phases(self.state.project["id"]),
            on_success=lambda rows: self._select_phase(rows, new_phase["id"]),
            on_error=lambda exc: show_error(self, f"Failed to reload phases: {exc}"),
        )
        QMessageBox.information(self, "Phase Created", f"Phase {new_phase['phase_no']:02d} created.")

    def _select_phase(self, phases: list[Row], phase_id: str) -> None:
        for ph in phases:
            if ph["id"] == phase_id:
                if self.state:
                    self.state.phase = ph
                mw = get_main_window()
                if mw is not None:
                    mw.refresh_phases_and_select(ph["id"])
                return

    def _load_phase_data(self) -> None:
        if not self._phase:
            return
        self._rebuild_controls()
        run_async(
            lambda: self._fetch_review_results(),
            on_success=self._on_review_results_loaded,
            on_error=lambda exc: show_error(self, f"Failed to load review records: {exc}"),
        )
        self._notes_edit.setPlainText(self._phase.get("acceptance_notes") or "")

    def _fetch_review_results(self) -> dict[int, str]:
        """Read the review status of every attempt (background thread)."""
        results: dict[int, str] = {}
        for attempt in range(4):
            record = get_review_record(self._phase["id"], attempt)
            results[attempt] = (record or {}).get("audit_status") or "not_reviewed"
        return results

    def _on_review_results_loaded(self, review_results: dict[int, str]) -> None:
        self._review_results = review_results
        phase = self._phase
        if not phase:
            return
        status = phase.get("status", "awaiting_task")

        # Status combo: the three pickable values only.
        self._status_combo.blockSignals(True)
        self._status_combo.clear()
        for s in _C_STATUS_ORDER:
            self._status_combo.addItem(_C_STATUS_LABELS[s], s)
        idx = self._status_combo.findData(status)
        self._status_combo.setCurrentIndex(idx if idx >= 0 else 0)
        cleared = status == "cleared"
        self._status_combo.setEnabled(self._writable and not cleared)
        self._cleared_badge.setVisible(cleared)
        self._status_combo.blockSignals(False)

        # Task combo: determine the next available task based on review results.
        self._task_combo.blockSignals(True)
        self._refresh_task_model()
        
        # Auto-select the next task based on phase status and review results
        next_task_index = self._determine_next_task_index(status, review_results)
        self._task_combo.setCurrentIndex(next_task_index)
        self._previous_task_index = next_task_index
        
        # Update _task_attempt based on selection
        model = self._task_combo.model()
        if isinstance(model, QStandardItemModel):
            item = model.item(next_task_index)
            if item:
                self._task_attempt = _TASK_ATTEMPT.get(item.text())
            else:
                self._task_attempt = None
        else:
            self._task_attempt = None
        
        self._task_combo.blockSignals(False)
        
        # Reset command/report editors for the new task selection
        self._has_report = False
        if self._task_attempt is None:
            self._cmd_label.setText("(Task: No Task)")
            self._rep_label.setText("(Task: No Task)")
            self._command_edit.clear()
            self._report_edit.clear()
            self._command_edit.setEnabled(False)
            self._report_edit.setEnabled(False)
        else:
            self._cmd_label.setText(f"(Task: {self._task_combo.currentText()})")
            self._rep_label.setText(f"(Task: {self._task_combo.currentText()})")
            self._command_edit.clear()
            self._report_edit.clear()
            task_on = self._writable and not cleared
            self._command_edit.setEnabled(task_on)
            self._report_edit.setEnabled(task_on)
            # Load existing command/report for this attempt
            run_async(
                lambda: list_commands(self._phase["id"], kind="coder", attempt_no=self._task_attempt),
                on_success=self._on_commands_loaded,
                on_error=lambda exc: show_error(self, f"Failed to load command: {exc}"),
            )
            run_async(
                lambda: list_reports(self._phase["id"], kind="coder_report", attempt_no=self._task_attempt),
                on_success=self._on_reports_loaded,
                on_error=lambda exc: show_error(self, f"Failed to load coder report: {exc}"),
            )

        self._new_phase_btn.setEnabled(self._writable and workflow.can_new_phase(status))
        self._notes_edit.setEnabled(self._writable and not cleared)
        self._save_notes_btn.setEnabled(self._writable and not cleared)
        self._refresh_buttons()

    def _determine_next_task_index(self, status: str, review_results: dict[int, str]) -> int:
        """
        Determine which task should be auto-selected based on phase status and review results.
        Returns the index in the task combo (0 = "No Task", 1 = "Coding", 2 = "Re-Fix-1", etc.)
        """
        if status == "cleared":
            return 0  # No Task - read only
        
        # Check for failed reviews from highest attempt down
        # If Review-N (attempt N-1) failed, then Re-Fix-N (attempt N) should be selected
        for attempt in range(3, 0, -1):  # 3, 2, 1
            review_attempt = attempt - 1  # Review-N corresponds to attempt N-1
            if review_results.get(review_attempt) == "failed":
                # Re-Fix-N is at index attempt + 1 (0=No Task, 1=Coding, 2=Re-Fix-1, 3=Re-Fix-2, 4=Re-Fix-3)
                return attempt + 1
        
        # No failed reviews - if phase is awaiting_task, Coding (attempt 0) is available
        if status == "awaiting_task" and review_results.get(0, "not_reviewed") == "not_reviewed":
            return 1  # "Coding"
        
        # Default to "No Task"
        return 0

    def _clear_ui(self) -> None:
        self._phase = None
        self._task_attempt = None
        self._has_report = False
        self._review_results = {}
        self._notes_edit.clear()
        self._command_edit.clear()
        self._report_edit.clear()
        self._cmd_label.setText("(Task: No Task)")
        self._rep_label.setText("(Task: No Task)")
        self._command_edit.setEnabled(False)
        self._report_edit.setEnabled(False)
        self._status_combo.setCurrentIndex(0)
        self._task_combo.setCurrentIndex(0)
        has_project = self.state is not None and self.state.project is not None
        self._new_phase_btn.setEnabled(self._writable and has_project)
        self._refresh_buttons()

    def _rebuild_controls(self) -> None:
        """Redraw status/task controls from the current phase state."""
        if not self._phase:
            return
        status = self._phase.get("status", "awaiting_task")
        cleared = status == "cleared"

        self._status_combo.blockSignals(True)
        self._status_combo.clear()
        for s in _C_STATUS_ORDER:
            self._status_combo.addItem(_C_STATUS_LABELS[s], s)
        idx = self._status_combo.findData(status)
        self._status_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._status_combo.setEnabled(self._writable and not cleared)
        self._cleared_badge.setVisible(cleared)
        self._status_combo.blockSignals(False)

        self._refresh_task_model()
        has_project = self.state is not None and self.state.project is not None
        self._new_phase_btn.setEnabled(self._writable and has_project and workflow.can_new_phase(status))
        self._notes_edit.setEnabled(self._writable and not cleared)
        self._save_notes_btn.setEnabled(self._writable and not cleared)
        task_on = self._writable and not cleared and self._task_attempt is not None
        self._command_edit.setEnabled(task_on)
        self._report_edit.setEnabled(task_on)
        self._refresh_buttons()

    def _phase_status(self) -> str | None:
        """Return phase status for can_new_phase check (None when no phase)."""
        return self._phase.get("status") if self._phase else None

    def _phase_status_or_default(self) -> str:
        """Return phase status for workflow functions (defaults to awaiting_task)."""
        return self._phase.get("status", "awaiting_task") if self._phase else "awaiting_task"

    def _phase_cleared(self) -> bool:
        return self._phase is not None and self._phase.get("status") == "cleared"

    def _release_writable(self) -> None:
        self._save_in_flight = False
        self._set_writable(
            bool(self.state is not None and self.state.sync.is_writable())
        )

    # -- task picked --

    def _on_task_picked(self) -> None:
        try:
            if not self._phase:
                return
            index = self._task_combo.currentIndex()
            label = self._task_combo.itemText(index)
            attempt = _TASK_ATTEMPT[label]
            if attempt is None:
                self._task_attempt = None
                self._has_report = False
                self._cmd_label.setText("(Task: No Task)")
                self._rep_label.setText("(Task: No Task)")
                self._command_edit.clear()
                self._report_edit.clear()
                self._command_edit.setEnabled(False)
                self._report_edit.setEnabled(False)
                self._refresh_buttons()
                return
            if not workflow.can_pick_task(attempt, self._review_results):
                show_error(
                    self,
                    f"'{label}' cannot be picked yet: the previous review must be "
                    f"saved as Failed first.",
                )
                self._task_combo.blockSignals(True)
                self._task_combo.setCurrentIndex(self._previous_task_index)
                self._task_combo.blockSignals(False)
                return
            self._previous_task_index = index
            self._task_attempt = attempt
            self._cmd_label.setText(f"(Task: {label})")
            self._rep_label.setText(f"(Task: {label})")
            self._command_edit.clear()
            self._report_edit.clear()
            task_on = self._writable and not self._phase_cleared()
            self._command_edit.setEnabled(task_on)
            self._report_edit.setEnabled(task_on)
            self._refresh_buttons()
            run_async(
                lambda: list_commands(self._phase["id"], kind="coder", attempt_no=attempt),
                on_success=self._on_commands_loaded,
                on_error=lambda exc: show_error(self, f"Failed to load command: {exc}"),
            )
            run_async(
                lambda: list_reports(self._phase["id"], kind="coder_report", attempt_no=attempt),
                on_success=self._on_reports_loaded,
                on_error=lambda exc: show_error(self, f"Failed to load coder report: {exc}"),
            )
        except Exception as exc:
            logging.exception("_on_task_picked failed")

    def _on_commands_loaded(self, commands: list[Row]) -> None:
        if commands:
            self._command_edit.setPlainText(commands[0].get("body", ""))
        else:
            self._command_edit.clear()
        self._refresh_buttons()

    def _on_reports_loaded(self, reports: list[Row]) -> None:
        self._has_report = bool(reports)
        if reports:
            self._report_edit.setPlainText(reports[0].get("content_text", ""))
        else:
            self._report_edit.clear()
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        if not self._phase:
            self._save_command_btn.setEnabled(False)
            self._copy_command_btn.setEnabled(False)
            self._save_report_btn.setEnabled(False)
            self._copy_report_btn.setEnabled(False)
            self._attach_report_btn.setEnabled(False)
            self._paste_report_btn.setEnabled(False)
            self._save_notes_btn.setEnabled(False)
            self._completed_btn.setEnabled(False)
            self._command_history_btn.setEnabled(False)
            self._report_history_btn.setEnabled(False)
            return
        cleared = self._phase_cleared()
        task_on = self._writable and not cleared and self._task_attempt is not None
        cmd_text = bool(self._command_edit.toPlainText().strip())
        rep_text = bool(self._report_edit.toPlainText().strip())
        self._save_command_btn.setEnabled(task_on and cmd_text)
        self._copy_command_btn.setEnabled(task_on and cmd_text)
        self._save_report_btn.setEnabled(task_on and rep_text)
        self._copy_report_btn.setEnabled(task_on and rep_text)
        self._attach_report_btn.setEnabled(task_on)
        self._paste_report_btn.setEnabled(task_on)
        self._command_history_btn.setEnabled(task_on)
        self._report_history_btn.setEnabled(task_on)
        self._completed_btn.setEnabled(
            task_on
            and workflow.can_mark_completed(
                self._phase_status_or_default(), self._has_report, self._task_attempt
            ),
        )

    # -- status picked by hand --

    def _on_status_picked(self) -> None:
        try:
            if not self._phase:
                return
            new_status = self._status_combo.currentData()
            current = self._phase.get("status", "awaiting_task")
            if new_status == current:
                return
            if not confirm(
                self, f"Set phase status to '{_C_STATUS_LABELS[new_status]}'?"
            ):
                self._rebuild_controls()
                return
            self._save_in_flight = True
            self._set_writable(False)
            run_async(
                lambda: set_phase_status(self._phase["id"], self._phase["version"], new_status),
                on_success=lambda updated: self._on_phase_status_changed(updated, None),
                on_error=self._on_status_error,
            )
        except Exception as exc:
            logging.exception("_on_status_picked failed")
            self._on_status_error(exc)

    def _rebuild_status_combo(self) -> None:
        """Redraw the status combo from the current phase (revert after cancel/error)."""
        if not self._phase:
            return
        status = self._phase.get("status", "awaiting_task")
        self._status_combo.blockSignals(True)
        self._status_combo.clear()
        for s in _C_STATUS_ORDER:
            self._status_combo.addItem(_C_STATUS_LABELS[s], s)
        idx = self._status_combo.findData(status)
        self._status_combo.setCurrentIndex(idx if idx >= 0 else 0)
        cleared = status == "cleared"
        self._status_combo.setEnabled(self._writable and not cleared)
        self._cleared_badge.setVisible(cleared)
        self._status_combo.blockSignals(False)
        self._refresh_buttons()

    def _on_status_error(self, exc: Exception) -> None:
        self._release_writable()
        self._rebuild_status_combo()
        if isinstance(exc, RuleViolationError):
            show_error(self, f"Phase transition not allowed: {exc}")
        elif isinstance(exc, ConflictError):
            show_error(self, str(exc))
        else:
            show_error(self, f"Status change failed: {exc}")

    def _on_phase_status_changed(self, updated: Row, message: str | None) -> None:
        self._phase = updated
        if self.state:
            self.state.phase = updated
        self._rebuild_controls()
        if message:
            QMessageBox.information(self, "Saved", message)
        self._release_writable()

    # -- save command --

    def save_command(self) -> None:
        try:
            if not (self.state and self.state.project and self._phase):
                return
            if not self.state.sync.is_writable():
                show_error(self, "Cannot write while offline or saving.")
                return
            attempt = self._task_attempt
            if attempt is None:
                show_error(self, "Pick a task first.")
                return
            body = self._command_edit.toPlainText()
            if not body.strip():
                show_error(self, "Command cannot be empty.")
                return
            new_status = workflow.next_phase_status("save_command", self._phase_status_or_default())
            self._save_in_flight = True
            self._set_writable(False)

            def _do() -> Row:
                row = add_command(
                    self.state.project["id"],
                    self._phase["id"],
                    attempt,
                    "coder",
                    body,
                )
                if new_status != self._phase_status_or_default():
                    row = set_phase_status(
                        self._phase["id"], self._phase["version"], new_status
                    )
                return row

            run_async(
                _do,
                on_success=lambda row: self._on_command_saved(row, new_status),
                on_error=self._on_command_error,
            )
        except Exception as exc:
            logging.exception("save_command failed")
            self._on_command_error(exc)

    def _on_command_saved(self, row: Row, new_status: str) -> None:
        QMessageBox.information(self, "Saved", "Command saved.")
        self._refresh_buttons()
        if new_status != self._phase_status_or_default() and self._phase:
            self._phase = row
            if self.state:
                self.state.phase = row
            self._rebuild_controls()
        self._release_writable()

    def _on_command_error(self, exc: Exception) -> None:
        self._release_writable()
        if isinstance(exc, ConflictError):
            show_error(self, str(exc))
        elif isinstance(exc, ValidationError):
            show_error(self, str(exc))
        elif isinstance(exc, OfflineError):
            show_error(self, "Offline — cannot complete action.")
        else:
            show_error(self, f"Action failed: {exc}")

    # -- notes (per phase) --

    def save_worklist_notes(self) -> None:
        try:
            if not self._phase:
                return
            if not self.state.sync.is_writable():
                show_error(self, "Cannot write while offline or saving.")
                return
            notes = self._notes_edit.toPlainText()
            self._save_in_flight = True
            self._set_writable(False)

            run_async(
                lambda: data.update_phase(
                    self._phase["id"], self._phase["version"], {"acceptance_notes": notes}
                ),
                on_success=self._on_notes_saved,
                on_error=self._on_command_error,
            )
        except Exception as exc:
            logging.exception("save_worklist_notes failed")
            self._on_command_error(exc)

    def _on_notes_saved(self, updated: Row) -> None:
        self._phase = updated
        if self.state:
            self.state.phase = updated
        QMessageBox.information(self, "Saved", "Notes saved.")
        self._release_writable()

    # -- COMPLETED --

    def mark_completed(self) -> None:
        try:
            if not self._phase:
                return
            if not self.state.sync.is_writable():
                show_error(self, "Cannot write while offline or saving.")
                return
            if not workflow.can_mark_completed(
                self._phase_status_or_default(), self._has_report, self._task_attempt
            ):
                return
            new_status = workflow.next_phase_status("completed", self._phase_status_or_default())
            if new_status == self._phase_status_or_default():
                return
            self._save_in_flight = True
            self._set_writable(False)
            run_async(
                lambda: set_phase_status(self._phase["id"], self._phase["version"], new_status),
                on_success=lambda updated: self._on_phase_status_changed(
                    updated, "Phase status set to Coding Completed."
                ),
                on_error=self._on_command_error,
            )
        except Exception as exc:
            logging.exception("mark_completed failed")
            self._on_command_error(exc)

    # -- new phase --

    def new_phase(self) -> None:
        try:
            if not (self.state and self.state.project):
                return
            if not workflow.can_new_phase(self._phase_status()):
                return
            title, ok = QInputDialog.getText(self, "New Phase", "Title (optional):")
            if not ok:
                return
            self._save_in_flight = True
            self._set_writable(False)

            def _do() -> Row:
                next_no = data.get_next_phase_no(self.state.project["id"])
                return data.create_phase(self.state.project["id"], next_no, title or "")

            run_async(
                _do,
                on_success=self._on_phase_created,
                on_error=self._on_command_error,
            )
        except Exception as exc:
            logging.exception("new_phase failed")
            self._on_command_error(exc)

    # -- clipboard / report helpers --

    def copy_command(self) -> None:
        try:
            text = self._command_edit.toPlainText()
            if not text.strip():
                show_error(self, "No command to copy.")
                return
            copy_to_clipboard(text)
            QMessageBox.information(self, "Copied", "Command copied to clipboard.")
        except Exception as exc:
            logging.exception("copy_command failed")
            show_error(self, f"Copy failed: {exc}")

    def copy_report(self) -> None:
        try:
            text = self._report_edit.toPlainText()
            if not text.strip():
                show_error(self, "No report to copy.")
                return
            copy_to_clipboard(text)
            QMessageBox.information(self, "Copied", "Report copied to clipboard.")
        except Exception as exc:
            logging.exception("copy_report failed")
            show_error(self, f"Copy failed: {exc}")

    def paste_report(self) -> None:
        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is None:
                app = QApplication([])
            clipboard = app.clipboard()
            if clipboard is not None:
                self._report_edit.setPlainText(clipboard.text())
        except Exception as exc:
            logging.exception("paste_report failed")
            show_error(self, f"Paste failed: {exc}")

    # -- attach report --

    def attach_report(self) -> None:
        try:
            if not (self.state and self.state.project and self._phase):
                return
            if not self.state.sync.is_writable():
                show_error(self, "Cannot write while offline or saving.")
                return
            if self._task_attempt is None:
                show_error(self, "Pick a task first.")
                return
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Attach File...",
                filter="Allowed Files (*.md *.txt *.pdf *.docx *.png *.jpg *.jpeg *.json *.csv)",
            )
            if not path:
                return
            try:
                validate_attachment(path)
            except ValidationError as exc:
                show_error(self, str(exc))
                return

            def _do() -> Row:
                info = data.upload_file(self.state.project["id"], path)
                return add_report(
                    self.state.project["id"],
                    self._phase["id"],
                    self._task_attempt,
                    "coder_report",
                    file_info=info,
                )

            self._save_in_flight = True
            self._set_writable(False)
            run_async(
                _do,
                on_success=self._on_report_attached,
                on_error=self._on_command_error,
            )
        except Exception as exc:
            logging.exception("attach_report failed")
            self._on_command_error(exc)

    def _on_report_attached(self, row: Row) -> None:
        QMessageBox.information(
            self,
            "Attachment Saved",
            f"{row.get('file_name', '')} ({row.get('size_bytes', 0)} bytes) attached and saved.",
        )
        self._has_report = True
        self._refresh_buttons()
        self._release_writable()

    # -- save report --

    def save_report(self) -> None:
        try:
            if not (self.state and self.state.project and self._phase):
                return
            if not self.state.sync.is_writable():
                show_error(self, "Cannot write while offline or saving.")
                return
            if self._task_attempt is None:
                show_error(self, "Pick a task first.")
                return
            text = self._report_edit.toPlainText()
            if not text.strip():
                show_error(self, "Coder report cannot be empty.")
                return
            self._save_in_flight = True
            self._set_writable(False)
            run_async(
                lambda: add_report(
                    self.state.project["id"],
                    self._phase["id"],
                    self._task_attempt,
                    "coder_report",
                    content_text=text,
                ),
                on_success=lambda row: self._on_report_saved(row),
                on_error=self._on_command_error,
            )
        except Exception as exc:
            logging.exception("save_report failed")
            self._on_command_error(exc)

    def _on_report_saved(self, row: Row) -> None:
        self._has_report = True
        self._refresh_buttons()
        QMessageBox.information(self, "Saved", "Coder report saved.")
        self._release_writable()

    # -- history dialogs --

    def show_command_history(self) -> None:
        try:
            if not self._phase:
                return
            dialog = QDialog(self)
            dialog.setWindowTitle("Command History")
            dialog.setMinimumSize(600, 400)
            layout = QVBoxLayout(dialog)
            table = QTableWidget(0, 3)
            table.setHorizontalHeaderLabels(["Attempt", "Date", "Body"])
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            history_rows: list[Row] = []
            table.customContextMenuRequested.connect(
                lambda pos: self._show_command_history_menu(
                    table, dialog, history_rows, pos
                )
            )

            def _on_history_loaded(rows: list[Row]) -> None:
                history_rows[:] = rows
                self._populate_command_history(table, rows)

            run_async(
                lambda: list_commands(self._phase["id"], kind="coder"),
                on_success=_on_history_loaded,
                on_error=lambda exc: show_error(dialog, f"Failed to load history: {exc}"),
            )
            btn = QPushButton("Close")
            btn.clicked.connect(dialog.accept)
            layout.addWidget(table)
            layout.addWidget(btn)
            dialog.exec()
        except Exception as exc:
            logging.exception("show_command_history failed")
            show_error(self, f"History failed: {exc}")

    def _show_command_history_menu(
        self, table: QTableWidget, dialog: QDialog,
        rows: list[Row], pos: Any,
    ) -> None:
        item = table.itemAt(pos)
        if item is None or item.row() >= len(rows):
            return
        command = rows[item.row()]
        menu = QMenu(self)
        delete_action = menu.addAction("Delete...")
        delete_action.setEnabled(self._writable)
        delete_action.triggered.connect(
            lambda: request_secure_delete(
                self,
                "command",
                command["id"],
                protected=False,
                writable=self._writable,
                on_deleted=lambda _result: (
                    dialog.accept(),
                    self.reload(),
                ),
            )
        )
        menu.exec(table.viewport().mapToGlobal(pos))

    def _populate_command_history(self, table: QTableWidget, rows: list[Row]) -> None:
        table.setRowCount(len(rows))
        for row_idx, cmd in enumerate(rows):
            table.setItem(row_idx, 0, QTableWidgetItem(str(cmd["attempt_no"])))
            date = cmd.get("created_at", "")[:19] if cmd.get("created_at") else ""
            table.setItem(row_idx, 1, QTableWidgetItem(date))
            body = cmd.get("body", "")
            if len(body) > 50:
                body = body[:50] + "..."
            item = QTableWidgetItem(body)
            item.setToolTip(cmd.get("body", ""))
            table.setItem(row_idx, 2, item)

    def show_report_history(self) -> None:
        try:
            if not self._phase:
                return
            dialog = QDialog(self)
            dialog.setWindowTitle("Coder Report History")
            dialog.setMinimumSize(600, 400)
            layout = QVBoxLayout(dialog)
            table = QTableWidget(0, 4)
            table.setHorizontalHeaderLabels(["Attempt", "Date", "File", "Text Length"])
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            run_async(
                lambda: list_reports(self._phase["id"], kind="coder_report"),
                on_success=lambda rows: self._populate_report_history(table, rows),
                on_error=lambda exc: show_error(dialog, f"Failed to load history: {exc}"),
            )
            btn = QPushButton("Close")
            btn.clicked.connect(dialog.accept)
            layout.addWidget(table)
            layout.addWidget(btn)
            dialog.exec()
        except Exception as exc:
            logging.exception("show_report_history failed")
            show_error(self, f"History failed: {exc}")

    def _populate_report_history(self, table: QTableWidget, rows: list[Row]) -> None:
        table.setRowCount(len(rows))
        for row_idx, report in enumerate(rows):
            table.setItem(row_idx, 0, QTableWidgetItem(str(report["attempt_no"])))
            date = report.get("created_at", "")[:19] if report.get("created_at") else ""
            table.setItem(row_idx, 1, QTableWidgetItem(date))
            table.setItem(row_idx, 2, QTableWidgetItem(report.get("file_name", "") or "(pasted)"))
            text = report.get("content_text", "") or ""
            table.setItem(row_idx, 3, QTableWidgetItem(str(len(text))))

    # -- writable gating --

    def set_writable(self, writable: bool) -> None:
        self._set_writable(writable)

    def _set_writable(self, writable: bool) -> None:
        self._writable = bool(writable)
        cleared = self._phase_cleared()
        base = self._writable and not cleared
        self._status_combo.setEnabled(base)
        self._phase_menu_btn.setEnabled(self._writable and self._phase is not None)
        self._cleared_badge.setVisible(cleared)
        has_project = self.state is not None and self.state.project is not None
        self._new_phase_btn.setEnabled(
            self._writable and has_project and workflow.can_new_phase(self._phase_status())
        )
        self._refresh_btn.setEnabled(True)
        self._notes_edit.setEnabled(base)
        self._save_notes_btn.setEnabled(base)
        self._task_combo.setEnabled(base)
        task_on = base and self._task_attempt is not None
        self._command_edit.setEnabled(task_on)
        self._report_edit.setEnabled(task_on)
        self._refresh_buttons()

    def _show_phase_menu(self) -> None:
        if not self._phase:
            return
        menu = QMenu(self)
        delete_action = menu.addAction("Delete...")
        delete_action.setEnabled(self._writable)
        delete_action.triggered.connect(self.delete_phase)
        menu.exec(self._phase_menu_btn.mapToGlobal(
            self._phase_menu_btn.rect().bottomLeft()
        ))

    def delete_phase(self) -> None:
        if not self._phase:
            return
        request_secure_delete(
            self,
            "phase",
            self._phase["id"],
            protected=self._phase.get("status") == "cleared",
            writable=self._writable,
            on_deleted=self._on_phase_deleted,
        )

    def _on_phase_deleted(self, _result: dict[str, Any]) -> None:
        if self.state:
            self.state.phase = None
        mw = get_main_window()
        if mw is not None:
            mw.refresh_phases_and_select()

