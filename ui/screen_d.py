"""

ui/screen_d.py — Screen D: Project Review (Indigo).



Phase 4B: per-attempt project review. Review Status (Not reviewed / Passed /

Failed) is stored per attempt and set only by the Mark Review buttons. All

status logic lives in workflow.py; all attempt-aware data access goes through

data_review.py.

"""

from __future__ import annotations

import logging

from typing import Any



from PySide6.QtCore import Qt

from PySide6.QtGui import QStandardItem, QStandardItemModel

from PySide6.QtWidgets import (

    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QTextEdit,

    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,

    QFileDialog, QMessageBox, QFrame, QGroupBox, QSizePolicy, QDialog,
    QScrollArea,
    QWidget, QMenu,

)



import data

from data import (

    upload_file,

    download_file,

    ValidationError,

    ConflictError,

    OfflineError,

    RuleViolationError,

)

import data_review

from data_review import (

    list_commands,

    add_command,

    list_reports,

    add_report,

    get_review_record,

    save_review_record,

    mark_review_passed,

    mark_review_failed,

    set_phase_status,

)

import workflow

from workflow import (

    all_review_names,

    can_mark_review,

    can_pick_review,

    next_phase_status,

    recommendation,

)

import services

from services import SCREEN_ACCENTS, copy_to_clipboard, validate_attachment, temp_dir, safe_filename, open_with_default_app

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



# ===== SECTION: Screen D constants =====



_REVIEW_NAMES: list[str] = ["(none)", "Review-1", "Review-2", "Review-3", "Final Review"]

_ATTEMPT_OF_REVIEW: dict[str, int | None] = {"(none)": None, "Review-1": 0, "Review-2": 1, "Review-3": 2, "Final Review": 3}

_REVIEW_STATUS_LABELS: dict[str, str] = {

    "not_reviewed": "Not reviewed",

    "passed": "Passed",

    "failed": "Failed",

}



# ===== SECTION: ScreenD — Project Review =====



class ScreenD(BaseScreen):

    """Screen D: Project Review (frame D renamed by CR-017)."""



    screen_id = "D"

    title = "Project Review"

    accent = SCREEN_ACCENTS["D"]



    def __init__(self, state: AppState | None = None):

        super().__init__(state)

        self._phase: Row | None = None

        self._review_attempt: int | None = None

        self._review_status = "not_reviewed"

        self._has_auditor_report = False

        self._reports_presence: dict[int, bool] = {}

        self._review_status_by_attempt: dict[int, dict[str, str]] = {}

        self._writable = False

        self._save_in_flight = False

        self._previous_review_index = 0

        # Last text persisted per record box (kind -> body). Save is disabled
        # while the editor still equals this value (or is empty).

        self._saved_text: dict[str, str] = {}

        self._build_ui()



    def _build_ui(self) -> None:

        outer_layout = QVBoxLayout(self)

        outer_layout.setContentsMargins(0, 0, 0, 0)

        outer_layout.setSpacing(0)



        scroll = QScrollArea()

        scroll.setWidgetResizable(True)

        scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        outer_layout.addWidget(scroll)



        content = QWidget()

        layout = QVBoxLayout(content)

        layout.setContentsMargins(12, 12, 12, 12)

        layout.setSpacing(12)



        header = QHBoxLayout()

        title = QLabel("Project Review")

        title.setStyleSheet(

            f"font-size: 14pt; font-weight: bold; color: {self.accent}; background-color: transparent;"

        )

        header.addWidget(title)

        header.addStretch()

        self._review_status_label = QLabel("Review Status: Not reviewed")

        self._review_status_label.setTextInteractionFlags(

            Qt.TextInteractionFlag.TextSelectableByMouse

        )

        header.addWidget(self._review_status_label)

        layout.addLayout(header)



        control = QHBoxLayout()

        control.addWidget(QLabel("Review:"))

        self._review_combo = QComboBox()

        self._review_combo.setModel(self._review_model())

        self._review_combo.currentIndexChanged.connect(self._on_review_picked)

        control.addWidget(self._review_combo, 1)

        control.addStretch()

        layout.addLayout(control)



        self._record_groups: dict[str, tuple[QGroupBox, QTextEdit, dict]] = {}

        for kind, label in [

            ("auditor_command", "Auditor Command"),

            ("auditor_report", "Auditor Report"),

            ("claude_review", "Claude Review of Reports"),

        ]:

            group = QGroupBox(label)

            group_layout = QVBoxLayout(group)

            group_layout.setContentsMargins(4, 4, 4, 4)



            edit = QTextEdit()

            edit.setPlaceholderText(f"Paste or type the {label.lower()}...")

            edit.setMinimumHeight(100)

            edit.setMaximumHeight(150)

            edit.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

            edit.textChanged.connect(self._refresh_buttons)

            group_layout.addWidget(edit)



            btn_row = QHBoxLayout()

            attach_btn = QPushButton("Attach File...")

            attach_btn.clicked.connect(lambda _, k=kind: self.attach_report(k))

            btn_row.addWidget(attach_btn)



            paste_btn = QPushButton("Paste")

            paste_btn.clicked.connect(lambda _, k=kind: self.paste_report(k))

            btn_row.addWidget(paste_btn)



            save_btn = QPushButton("Save")

            save_btn.clicked.connect(lambda _, k=kind: self.save_record(k))

            btn_row.addWidget(save_btn)



            copy_btn = QPushButton("Copy")

            copy_btn.clicked.connect(lambda _, k=kind: self.copy_record(k))

            btn_row.addWidget(copy_btn)



            history_btn = QPushButton("History...")

            history_btn.clicked.connect(lambda _, k=kind: self.show_report_history(k))

            btn_row.addWidget(history_btn)



            group_layout.addLayout(btn_row)

            layout.addWidget(group)

            self._record_groups[kind] = (group, edit, {

                "attach": attach_btn,

                "paste": paste_btn,

                "save": save_btn,

                "copy": copy_btn,

                "history": history_btn,

            })



        # --- Review decision ---

        dec_group = QGroupBox("Review Decision")

        dec_layout = QVBoxLayout(dec_group)

        dec_layout.setContentsMargins(4, 4, 4, 4)

        dec_layout.setSpacing(8)



        self._findings_edit = QTextEdit()

        self._findings_edit.setPlaceholderText("Findings / defects...")

        self._findings_edit.setMinimumHeight(100)

        self._findings_edit.setMaximumHeight(150)

        self._findings_edit.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        dec_layout.addWidget(QLabel("Findings / Defects:"))

        dec_layout.addWidget(self._findings_edit)



        self._review_notes_edit = QTextEdit()

        self._review_notes_edit.setPlaceholderText("Review notes...")

        self._review_notes_edit.setMinimumHeight(100)

        self._review_notes_edit.setMaximumHeight(150)

        self._review_notes_edit.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        dec_layout.addWidget(QLabel("Review Notes:"))

        dec_layout.addWidget(self._review_notes_edit)



        btn_row = QHBoxLayout()

        self._save_records_btn = QPushButton("Save Records")

        self._save_records_btn.clicked.connect(self.save_records)

        btn_row.addWidget(self._save_records_btn)



        self._mark_passed_btn = QPushButton("Mark Review Passed")

        self._mark_passed_btn.clicked.connect(self.mark_review_passed)

        btn_row.addWidget(self._mark_passed_btn)



        self._mark_failed_btn = QPushButton("Mark Review Failed")

        self._mark_failed_btn.clicked.connect(self.mark_review_failed)

        btn_row.addWidget(self._mark_failed_btn)

        dec_layout.addLayout(btn_row)



        layout.addWidget(dec_group)



        # --- Recommendations ---

        rec_group = QGroupBox("Recommendations")

        rec_layout = QVBoxLayout(rec_group)

        rec_layout.setContentsMargins(4, 4, 4, 4)

        self._recommendation_label = QLabel("Review not decided yet.")

        self._recommendation_label.setTextInteractionFlags(

            Qt.TextInteractionFlag.TextSelectableByMouse

        )

        self._recommendation_label.setWordWrap(True)

        rec_layout.addWidget(self._recommendation_label)

        layout.addWidget(rec_group)



        layout.addStretch()

        scroll.setWidget(content)



        self._set_writable(False)



    # -- review model --



    def _review_model(self) -> QStandardItemModel:

        model = QStandardItemModel()

        for name in _REVIEW_NAMES:

            item = QStandardItem(name)

            item.setData(_ATTEMPT_OF_REVIEW[name], Qt.ItemDataRole.UserRole)

            model.appendRow(item)

        return model



    def _refresh_review_model(self, reports: dict[int, bool]) -> None:

        """Re-enable/disable review items according to the saved Coder Reports."""

        model = self._review_combo.model()

        if not isinstance(model, QStandardItemModel):

            return

        for row in range(model.rowCount()):

            item = model.item(row)

            attempt = _ATTEMPT_OF_REVIEW[item.text()]

            if attempt is None:
                # "(none)" is always enabled
                item.setEnabled(True)
            else:
                item.setEnabled(workflow.can_pick_review(attempt, reports))



    def _phase_cleared(self) -> bool:

        return self._phase is not None and self._phase.get("status") == "cleared"



    def _phase_status(self) -> str:

        return self._phase.get("status", "awaiting_task") if self._phase else "awaiting_task"



    def _release_writable(self) -> None:

        self._save_in_flight = False

        self._set_writable(bool(self.state is not None and self.state.sync.is_writable()))



    # -- contract hooks --



    def on_show(self) -> None:

        self.reload()



    def on_project_changed(self, project: Row | None) -> None:

        self._phase = None

        self._review_attempt = None

        self._clear_ui()

        if project:

            self._load_phase_form()



    def on_phase_changed(self, phase: Row | None) -> None:

        self._phase = phase

        self._review_attempt = None

        if phase:

            self._load_phase_data()

        else:

            self._clear_ui()



    def reload(self) -> None:

        if self.state and self.state.project and self._phase:

            self._load_phase_data()



    def _load_phase_form(self) -> None:

        if not (self.state and self.state.project):

            return

        run_async(

            lambda: data.list_phases(self.state.project["id"]),

            on_success=self._on_phases_loaded,

            on_error=lambda exc: show_error(self, f"Failed to load phases: {exc}"),

        )



    def _on_phases_loaded(self, phases: Rows) -> None:

        if not phases:
            # No phases exist - ensure UI is in empty state
            self._clear_ui()
            return

        for ph in phases:

            if not ph.get("archived_at"):

                if self.state:

                    self.state.phase = ph

                break



    def _load_phase_data(self) -> None:

        if not self._phase:

            return

        run_async(

            lambda: self._fetch_review_bootstrap(),

            on_success=self._on_review_bootstrap_loaded,

            on_error=lambda exc: show_error(self, f"Failed to load review data: {exc}"),

        )



    def _fetch_review_bootstrap(self) -> dict[str, Any]:

        """Read review status + coder-report presence per attempt (background thread)."""

        status_by_attempt: dict[int, dict[str, str]] = {}

        reports_presence: dict[int, bool] = {}

        for attempt in range(4):

            record = get_review_record(self._phase["id"], attempt)

            status_by_attempt[attempt] = {

                "status": (record or {}).get("audit_status") or "not_reviewed",

            }

            reports_presence[attempt] = bool(

                list_reports(self._phase["id"], kind="coder_report", attempt_no=attempt)

            )

        return {"status_by_attempt": status_by_attempt, "reports_presence": reports_presence}



    def _on_review_bootstrap_loaded(self, result: dict[str, Any]) -> None:

        phase = self._phase

        if not phase:

            return

        self._review_status_by_attempt = result["status_by_attempt"]

        self._reports_presence = result["reports_presence"]


        self._review_combo.blockSignals(True)

        self._refresh_review_model(self._reports_presence)

        index = self._determine_next_review_index()

        self._review_combo.setCurrentIndex(index)

        self._previous_review_index = index

        self._review_combo.blockSignals(False)

        self._on_review_picked()


    def _determine_next_review_index(self) -> int:
        """
        Determine which review should be auto-selected based on coder report presence
        and review status. Returns the index in the review combo.
        Index 0 = "(none)", 1 = "Review-1", 2 = "Review-2", etc.
        """
        # Find the first attempt that has a coder report and whose review is not yet decided
        for attempt in range(4):
            has_coder_report = self._reports_presence.get(attempt, False)
            review_status = self._review_status_by_attempt.get(attempt, {}).get("status", "not_reviewed")
            if has_coder_report and review_status == "not_reviewed":
                # This review can be picked and needs attention
                return attempt + 1  # +1 because index 0 is "(none)"
        
        # No review needs attention - show "(none)"
        return 0


    def _on_review_picked(self) -> None:

        if not self._phase:

            return

        index = self._review_combo.currentIndex()

        name = self._review_combo.itemText(index)

        attempt = _ATTEMPT_OF_REVIEW[name]

        if attempt is None:
            # "(none)" selected
            self._previous_review_index = index
            self._review_attempt = None
            self._clear_review_ui()
            return

        if not workflow.can_pick_review(attempt, self._reports_presence):

            show_error(

                self,

                f"'{name}' cannot be picked yet: attempt {attempt} needs a saved Coder Report first.",

            )

            self._review_combo.blockSignals(True)

            self._review_combo.setCurrentIndex(self._previous_review_index)

            self._review_combo.blockSignals(False)

            return

        self._previous_review_index = index

        self._review_attempt = attempt

        self._load_review_attempt(attempt)


    def _clear_review_ui(self) -> None:
        """Clear all review-related UI when no review is selected."""
        self._saved_text = {}
        for kind, record_data in self._record_groups.items():
            _, edit, _ = record_data
            edit.clear()
        self._findings_edit.clear()
        self._review_notes_edit.clear()
        self._review_status = "not_reviewed"
        self._refresh_review_status_label()
        self._refresh_recommendations(None)
        self._refresh_buttons()



    def _load_review_attempt(self, attempt: int) -> None:

        if not self._phase:

            return

        phase_id = self._phase["id"]

        name = _REVIEW_NAMES[attempt + 1]

        self._saved_text = {}

        for kind, record_data in self._record_groups.items():

            _, edit, _ = record_data

            edit.clear()

        self._findings_edit.clear()

        self._review_notes_edit.clear()



        run_async(

            lambda: list_reports(phase_id, kind="auditor_command", attempt_no=attempt),

            on_success=lambda rows, k="auditor_command": self._on_record_loaded(k, rows),

            on_error=lambda exc: show_error(self, f"Failed to load auditor command: {exc}"),

        )

        run_async(

            lambda: list_reports(phase_id, kind="auditor_report", attempt_no=attempt),

            on_success=lambda rows, k="auditor_report": self._on_record_loaded(k, rows),

            on_error=lambda exc: show_error(self, f"Failed to load auditor report: {exc}"),

        )

        run_async(

            lambda: list_reports(phase_id, kind="claude_review", attempt_no=attempt),

            on_success=lambda rows, k="claude_review": self._on_record_loaded(k, rows),

            on_error=lambda exc: show_error(self, f"Failed to load Claude review: {exc}"),

        )

        run_async(

            lambda: get_review_record(phase_id, attempt),

            on_success=self._on_review_record_loaded,

            on_error=lambda exc: show_error(self, f"Failed to load review record: {exc}"),

        )



    def _on_record_loaded(self, kind: str, rows: Rows) -> None:

        record_data = self._record_groups.get(kind)

        if not record_data or not rows:

            return

        _, edit, _ = record_data

        if kind == "auditor_command":

            text = rows[0].get("body", "")

        else:

            text = rows[0].get("content_text", "") or ""

        edit.setPlainText(text)

        self._saved_text[kind] = text

        if kind == "auditor_report":

            self._has_auditor_report = True

        self._refresh_buttons()



    def _on_review_record_loaded(self, record: Row | None) -> None:

        self._review_status = (record or {}).get("audit_status") or "not_reviewed"

        if record:

            self._findings_edit.setPlainText(record.get("findings") or "")

            self._review_notes_edit.setPlainText(record.get("review_notes") or "")

        self._refresh_review_status_label()

        self._refresh_recommendations(self._review_attempt)

        self._refresh_buttons()



    def _refresh_review_status_label(self) -> None:

        label = _REVIEW_STATUS_LABELS[self._review_status]

        self._review_status_label.setText(f"Review Status: {label}")

        if self._review_status == "passed":

            self._review_status_label.setStyleSheet("color: #15803D; font-weight: bold;")

        elif self._review_status == "failed":

            self._review_status_label.setStyleSheet("color: #D97706; font-weight: bold;")

        else:

            self._review_status_label.setStyleSheet("color: #666666;")



    def _refresh_recommendations(self, attempt: int | None) -> None:

        if attempt is None:

            attempt = self._review_attempt or 0

        text = workflow.recommendation(self._review_status, attempt)

        self._recommendation_label.setText(text)



    def _clear_ui(self) -> None:

        self._phase = None

        self._review_attempt = None

        self._review_status = "not_reviewed"

        self._has_auditor_report = False

        self._saved_text = {}

        self._previous_review_index = 0

        for record_data in self._record_groups.values():

            _, edit, _ = record_data

            edit.clear()

        self._findings_edit.clear()

        self._review_notes_edit.clear()

        self._review_combo.setCurrentIndex(0)

        self._refresh_review_status_label()

        self._refresh_recommendations(None)

        self._refresh_buttons()



    def _refresh_buttons(self) -> None:

        if not self._phase:

            self._save_records_btn.setEnabled(False)

            self._mark_passed_btn.setEnabled(False)

            self._mark_failed_btn.setEnabled(False)

            self._review_combo.setEnabled(False)

            for kind, record_data in self._record_groups.items():

                _, edit, btns = record_data

                edit.setEnabled(False)

                btns["save"].setEnabled(False)

                btns["copy"].setEnabled(False)

                btns["paste"].setEnabled(False)

                btns["attach"].setEnabled(False)

                btns["history"].setEnabled(False)

            self._findings_edit.setEnabled(False)

            self._review_notes_edit.setEnabled(False)

            logging.info(
                "_refresh_buttons: no phase — box_kind=None review_on=False writable=%s text_len=0 saved_len=0 save_enabled=False reason=no_phase",
                self._writable,
            )
            return

        cleared = self._phase_cleared()

        base = self._writable and not cleared

        self._review_combo.setEnabled(base)

        review_on = base and self._review_attempt is not None

        for kind, record_data in self._record_groups.items():

            _, edit, btns = record_data

            text = edit.toPlainText()

            has_text = bool(text.strip())

            saved = self._saved_text.get(kind, "")

            edit.setEnabled(review_on)

            save_enabled = review_on and has_text and text != saved

            btns["save"].setEnabled(save_enabled)

            if not save_enabled:
                if not review_on:
                    reason = "no_review_picked"
                elif not has_text:
                    reason = "empty_text"
                else:
                    reason = "text_unchanged"
            else:
                reason = "ok"
            logging.info(
                "_refresh_buttons: box_kind=%s review_on=%s writable=%s text_len=%d saved_len=%d save_enabled=%s reason=%s",
                kind, review_on, self._writable, len(text), len(saved), save_enabled, reason,
            )

            btns["copy"].setEnabled(has_text)

            btns["paste"].setEnabled(review_on)

            btns["attach"].setEnabled(review_on)

            btns["history"].setEnabled(review_on)

        self._findings_edit.setEnabled(review_on)

        self._review_notes_edit.setEnabled(review_on)

        self._save_records_btn.setEnabled(review_on)

        mark_on = review_on

        self._mark_passed_btn.setEnabled(mark_on)

        self._mark_failed_btn.setEnabled(mark_on)

        if review_on and not workflow.can_mark_review(
            self._phase_status(), self._has_auditor_report
        ):

            if self._phase_cleared():

                reason = "Phase is already cleared."

            else:

                reason = "Save an Auditor Report before marking the review."

            self._mark_passed_btn.setToolTip(reason)

            self._mark_failed_btn.setToolTip(reason)

        else:

            self._mark_passed_btn.setToolTip("")

            self._mark_failed_btn.setToolTip("")

        cleared = self._phase_cleared()

        base = self._writable and not cleared

        self._review_combo.setEnabled(base)

        review_on = base and self._review_attempt is not None

        for kind, record_data in self._record_groups.items():

            _, edit, btns = record_data

            text = edit.toPlainText()

            has_text = bool(text.strip())

            saved = self._saved_text.get(kind, "")

            edit.setEnabled(review_on)

            # Save: only when review selected, non-empty, and changed vs saved.

            btns["save"].setEnabled(review_on and has_text and text != saved)

            # Copy: whenever the box has text (clipboard is local).

            btns["copy"].setEnabled(has_text)

            # Paste / Attach / History: writable + review selected.

            btns["paste"].setEnabled(review_on)

            btns["attach"].setEnabled(review_on)

            btns["history"].setEnabled(review_on)

        self._findings_edit.setEnabled(review_on)

        self._review_notes_edit.setEnabled(review_on)

        self._save_records_btn.setEnabled(review_on)

        mark_on = review_on

        self._mark_passed_btn.setEnabled(mark_on)

        self._mark_failed_btn.setEnabled(mark_on)

        if review_on and not workflow.can_mark_review(
            self._phase_status(), self._has_auditor_report
        ):

            if self._phase_cleared():

                reason = "Phase is already cleared."

            else:

                reason = "Save an Auditor Report before marking the review."

            self._mark_passed_btn.setToolTip(reason)

            self._mark_failed_btn.setToolTip(reason)

        else:

            self._mark_passed_btn.setToolTip("")

            self._mark_failed_btn.setToolTip("")


# -- review picked --


    def save_records(self) -> None:

        logging.info(
            "save_records clicked: review_on=%s writable=%s review_attempt=%s",
            self._review_attempt is not None, self._writable, self._review_attempt,
        )
        try:

            if not (self.state and self.state.project and self._phase):

                logging.warning("save_records: missing state/project/phase")
                return

            if not self.state.sync.is_writable():

                show_error(self, "Cannot write while offline or saving.")

                return

            if self._review_attempt is None:

                show_error(self, "Pick a review first.")

                return

            attempt = self._review_attempt

            pid = self.state.project["id"]

            phase_id = self._phase["id"]

            findings = self._findings_edit.toPlainText()

            notes = self._review_notes_edit.toPlainText()


            def _do() -> None:

                for kind, record_data in self._record_groups.items():

                    _, edit, _ = record_data

                    text = edit.toPlainText()

                    if not text.strip():

                        continue

                    if kind == "auditor_command":

                        add_command(pid, phase_id, attempt, "auditor", text)

                    else:

                        add_report(pid, phase_id, attempt, kind, content_text=text)

                save_review_record(pid, phase_id, attempt, findings, notes)


            self._save_in_flight = True

            self._set_writable(False)

            run_async(

                _do,

                on_success=self._on_records_saved,

                on_error=self._on_review_error,

            )

        except Exception as exc:

            logging.exception("save_records failed")

            self._on_review_error(exc)



    def _on_records_saved(self) -> None:

        for kind, record_data in self._record_groups.items():

            _, edit, _ = record_data

            self._saved_text[kind] = edit.toPlainText()

        auditor_edit = self._record_groups["auditor_report"][1]

        if auditor_edit.toPlainText().strip():

            self._has_auditor_report = True

        self._refresh_buttons()

        self._release_writable()

        QMessageBox.information(self, "Saved", "Records saved.")



    def _on_review_error(self, exc: Exception) -> None:

        self._release_writable()

        if isinstance(exc, ConflictError):

            show_error(self, str(exc))

        elif isinstance(exc, ValidationError):

            show_error(self, str(exc))

        elif isinstance(exc, OfflineError):

            show_error(self, "Offline — cannot complete action.")

        else:

            show_error(self, f"Save failed: {exc}")

# -- mark passed / failed --


    def mark_review_passed(self) -> None:

        try:

            self._mark_review("passed")

        except Exception as exc:

            logging.exception("mark_review_passed failed")

            self._on_review_error(exc)




    def mark_review_failed(self) -> None:

        try:

            self._mark_review("failed")

        except Exception as exc:

            logging.exception("mark_review_failed failed")

            self._on_review_error(exc)




    def _mark_review(self, result: str) -> None:

        try:

            if not self._phase:

                return

            if not self.state.sync.is_writable():

                show_error(self, "Cannot write while offline or saving.")

                return

            if self._review_attempt is None:

                show_error(self, "Pick a review first.")

                return

            if not workflow.can_mark_review(self._phase_status(), self._has_auditor_report):

                if self._phase_cleared():

                    show_error(self, "Phase is already cleared — review decision not allowed.")

                else:

                    show_error(self, "Save an Auditor Report before marking the review.")

                return

            attempt = self._review_attempt

            pid = self.state.project["id"]

            phase_id = self._phase["id"]

            findings = self._findings_edit.toPlainText()

            notes = self._review_notes_edit.toPlainText()




            def _do() -> Row:

                if result == "passed":

                    mark_review_passed(pid, phase_id, attempt, findings, notes)

                    new_status = next_phase_status("review_passed", self._phase_status())

                    if new_status != self._phase_status():

                        return set_phase_status(phase_id, self._phase["version"], new_status)

                else:

                    mark_review_failed(pid, phase_id, attempt, findings, notes)

                    new_status = next_phase_status("review_failed", self._phase_status())

                    if new_status != self._phase_status():

                        return set_phase_status(phase_id, self._phase["version"], new_status)

                return self._phase




            self._save_in_flight = True

            self._set_writable(False)

            run_async(

                _do,

                on_success=lambda updated: self._on_review_marked(result, updated),

                on_error=self._on_review_error,

            )

        except Exception as exc:

            logging.exception("_mark_review failed")

            self._on_review_error(exc)

    def _on_review_marked(self, result: str, updated: Row) -> None:

        self._phase = updated

        if self.state:

            self.state.phase = updated

        self._review_status = result

        self._refresh_review_status_label()

        self._refresh_recommendations(self._review_attempt)

        self._refresh_buttons()

        if result == "passed":

            QMessageBox.information(

                self, "Review Decision", "Review marked as PASSED — phase is Cleared."

            )

        else:

            attempt = self._review_attempt or 0

            if attempt == 3:

                QMessageBox.information(

                    self, "Review Decision",

                    "Final Review marked as FAILED — STOP. Owner decision needed."

                )

            else:

                QMessageBox.information(

                    self, "Review Decision",

                    "Review marked as FAILED. Phase stays Coding Completed.",

                )

        self._release_writable()
# -- clipboard / attach / history --




    def paste_report(self, kind: str) -> None:

        try:

            from PySide6.QtWidgets import QApplication




            app = QApplication.instance()

            if app is None:

                app = QApplication([])

            clipboard = app.clipboard()

            if clipboard is not None:

                record_data = self._record_groups.get(kind)

                if record_data:

                    _, edit, _ = record_data

                    edit.setPlainText(clipboard.text())

        except Exception as exc:

            logging.exception("paste_report failed")

            show_error(self, f"Paste failed: {exc}")




    def copy_record(self, kind: str) -> None:

        try:

            record_data = self._record_groups.get(kind)

            if not record_data:

                return

            _, edit, _ = record_data

            text = edit.toPlainText()

            if not text.strip():

                show_error(self, "No text to copy.")

                return

            copy_to_clipboard(text)

            label = "Command" if kind == "auditor_command" else "Report"

            QMessageBox.information(self, "Copied", f"{label} copied to clipboard.")

        except Exception as exc:

            logging.exception("copy_record failed")

            show_error(self, f"Copy failed: {exc}")




    def attach_report(self, kind: str) -> None:

        try:

            if not (self.state and self.state.project and self._phase):

                return

            if not self.state.sync.is_writable():

                show_error(self, "Cannot write while offline or saving.")

                return

            if self._review_attempt is None:

                show_error(self, "Pick a review first.")

                return

            path, _ = QFileDialog.getOpenFileName(

                self,

                f"Attach {kind.replace('_', ' ').title()} File",

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

                info = upload_file(self.state.project["id"], path)

                if kind == "auditor_command":

                    # commands table has no file columns; persist the attachment
                    # as the command body (text content, or a marker for binaries).

                    try:

                        with open(path, "r", encoding="utf-8") as fh:

                            body = fh.read()

                    except (UnicodeDecodeError, OSError):

                        body = ""

                    if not body.strip():

                        body = (
                            f"[Attached: {info['file_name']}] "
                            f"({info['size_bytes']} bytes)"
                        )

                    return add_command(

                        self.state.project["id"],

                        self._phase["id"],

                        self._review_attempt,

                        "auditor",

                        body,

                    )

                return add_report(

                    self.state.project["id"],

                    self._phase["id"],

                    self._review_attempt,

                    kind,

                    file_info=info,

                )




            self._save_in_flight = True

            self._set_writable(False)

            run_async(

                _do,

                on_success=lambda row: self._on_report_attached(kind, row),

                on_error=self._on_review_error,

            )

        except Exception as exc:

            logging.exception("attach_report failed")

            self._on_review_error(exc)
    def _on_report_attached(self, kind: str, row: Row) -> None:

        if kind == "auditor_command":

            body = row.get("body", "") or ""

            if body:

                _, edit, _ = self._record_groups[kind]

                edit.setPlainText(body)

                self._saved_text[kind] = body

        QMessageBox.information(

            self,

            "Attachment Saved",

            f"{row.get('file_name', '') or row.get('body', '')[:40]} attached and saved.",

        )

        self._refresh_buttons()

        self._release_writable()



    def save_record(self, kind: str) -> None:

        logging.info(
            "save_record clicked: box_kind=%s review_on=%s writable=%s review_attempt=%s",
            kind, self._review_attempt is not None, self._writable, self._review_attempt,
        )
        try:

            if not (self.state and self.state.project and self._phase):

                logging.warning("save_record: missing state/project/phase")
                return

            if not self.state.sync.is_writable():

                show_error(self, "Cannot write while offline or saving.")

                return

            if self._review_attempt is None:

                show_error(self, "Pick a review first.")

                return

            record_data = self._record_groups.get(kind)

            if not record_data:

                return

            _, edit, _ = record_data

            text = edit.toPlainText()

            if not text.strip():

                show_error(self, f"{kind.replace('_', ' ').title()} cannot be empty.")

                return

            pid = self.state.project["id"]

            phase_id = self._phase["id"]

            attempt = self._review_attempt

            self._save_in_flight = True

            self._set_writable(False)

            if kind == "auditor_command":

                run_async(

                    lambda: add_command(pid, phase_id, attempt, "auditor", text),

                    on_success=lambda _: self._on_record_saved(kind),

                    on_error=self._on_review_error,

                )

            else:

                run_async(

                    lambda: add_report(pid, phase_id, attempt, kind, content_text=text),

                    on_success=lambda _: self._on_record_saved(kind),

                    on_error=self._on_review_error,

                )

        except Exception as exc:

            logging.exception("save_record failed")

            self._on_review_error(exc)



    def _on_record_saved(self, kind: str) -> None:

        record_data = self._record_groups.get(kind)

        if record_data:

            _, edit, _ = record_data

            self._saved_text[kind] = edit.toPlainText()

        if kind == "auditor_report":

            self._has_auditor_report = True

        self._refresh_buttons()

        self._release_writable()

        QMessageBox.information(self, "Saved", f"{kind.replace('_', ' ').title()} saved.")




    def show_report_history(self, kind: str) -> None:

        try:

            if not self._phase:

                return

            dialog = QDialog(self)

            dialog.setWindowTitle(f"{kind.replace('_', ' ').title()} History")

            dialog.setMinimumSize(600, 400)

            layout = QVBoxLayout(dialog)




            table = QTableWidget(0, 5)

            table.setHorizontalHeaderLabels(["Attempt", "Date", "File", "Size (bytes)", "Text Length"])

            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            command_rows: list[Row] = []
            if kind == "auditor_command":
                table.setContextMenuPolicy(
                    Qt.ContextMenuPolicy.CustomContextMenu
                )
                table.customContextMenuRequested.connect(
                    lambda pos: self._show_command_history_menu(
                        table, dialog, command_rows, pos
                    )
                )

            table.cellDoubleClicked.connect(

                lambda row, _column: self._open_report_attachment(table, row)

            )




            if kind == "auditor_command":
                run_async(
                    lambda: list_commands(self._phase["id"], kind="auditor"),
                    on_success=lambda rows: self._on_command_history_loaded(
                        table, rows, kind, command_rows
                    ),

                    on_error=lambda exc: show_error(dialog, f"Failed to load history: {exc}"),

                )

            else:

                run_async(

                    lambda: list_reports(self._phase["id"], kind=kind),

                    on_success=lambda rows: self._populate_report_history(table, rows, kind),

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

    def _on_command_history_loaded(
        self, table: QTableWidget, rows: Rows, kind: str, command_rows: Rows
    ) -> None:
        command_rows[:] = rows
        self._populate_report_history(table, rows, kind)

    def _show_command_history_menu(
        self, table: QTableWidget, dialog: QDialog, rows: Rows, pos: Any
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



    def _populate_report_history(self, table: QTableWidget, rows: Rows, kind: str) -> None:

        table.setRowCount(len(rows))

        for row_idx, report in enumerate(rows):

            table.setItem(row_idx, 0, QTableWidgetItem(str(report["attempt_no"])))

            date = report.get("created_at", "")[:19] if report.get("created_at") else ""

            table.setItem(row_idx, 1, QTableWidgetItem(date))

            if kind == "auditor_command":

                file_name = "(command)"

                file_size = ""

            else:

                file_name = report.get("file_name", "") or "(pasted)"

                file_size = str(report.get("size_bytes", ""))

            table.setItem(row_idx, 2, QTableWidgetItem(file_name))

            table.setItem(row_idx, 3, QTableWidgetItem(file_size))

            text = report.get("body", "") or report.get("content_text", "") or ""

            table.setItem(row_idx, 4, QTableWidgetItem(str(len(text))))

            storage_path = report.get("storage_path", "")

            item = table.item(row_idx, 2)

            item.setData(Qt.ItemDataRole.UserRole, storage_path)

            item.setData(Qt.ItemDataRole.UserRole + 1, report.get("id", ""))

            if storage_path:

                item.setToolTip("Double-click to open the attached file.")



    def _open_report_attachment(self, table: QTableWidget, row: int) -> None:

        item = table.item(row, 2)

        storage_path = item.data(Qt.ItemDataRole.UserRole) if item else ""

        if not storage_path:

            return

        report_id = item.data(Qt.ItemDataRole.UserRole + 1)

        dest_path = temp_dir() / f"{report_id}-{safe_filename(item.text())}"

        run_async(

            lambda: download_file(storage_path, str(dest_path)),

            on_success=self._open_downloaded_report,

            on_error=lambda exc: show_error(self, f"Failed to open report attachment: {exc}"),

        )



    def _open_downloaded_report(self, path: str) -> None:

        try:

            open_with_default_app(path)

        except Exception as exc:

            show_error(self, f"Failed to open report attachment: {exc}")



    # -- writable gating --



    def _set_writable(self, writable: bool) -> None:

        self._writable = bool(writable)

        self._refresh_buttons()


    def set_writable(self, writable: bool) -> None:

        self._set_writable(writable)



