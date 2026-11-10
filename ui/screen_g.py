"""
ui/screen_g.py — Screen G: Project Memory & Handoff.
Phase 3 implementation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QFileDialog, QMessageBox, QGroupBox,
    QTableWidget, QTableWidgetItem, QAbstractItemView,
    QSizePolicy, QCheckBox, QMenu,
)

from data import (
    fetch_handoff_data,
    download_file,
)
from services import (
    SCREEN_ACCENTS,
    STATUS_LABELS,
    build_summary_markdown,
    export_markdown,
    export_zip,
    default_export_dir,
    temp_dir,
    open_with_default_app,
)
from ui.shell import (
    AppState,
    BaseScreen,
    run_async,
    show_error,
)
from ui.secure_delete import request_secure_delete

Row = dict[str, Any]
Rows = list[Row]


# ===== SECTION: ScreenG — Project Memory & Handooff =====

class ScreenG(BaseScreen):
    """Screen G: Project Memory and Handoff exports.

    Displays project summary and allows exporting as Markdown or ZIP.
    """

    screen_id = "G"
    title = "Project Handoff"
    accent = SCREEN_ACCENTS["G"]

    def __init__(self, state: AppState | None = None):
        super().__init__(state)
        self._project: Row | None = None
        self._handoff_data: dict[str, Any] | None = None
        self._selected_doc_ids: set[str] = set()
        self._documents: Rows = []
        self._load_generation = 0
        self._load_in_flight = False
        self._load_pending = False
        self._build_ui()

    def _build_ui(self) -> None:
        """Build the user interface for Screen G."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Header
        header = QHBoxLayout()
        title = QLabel("G  PROJECT HANDOFF")
        title.setStyleSheet(f"font-size: 14pt; font-weight: bold; color: {self.accent}; background-color: transparent;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # Project info summary
        self._info_group = QGroupBox("Project State")
        info_layout = QVBoxLayout(self._info_group)
        info_layout.setContentsMargins(4, 4, 4, 4)
        info_layout.setSpacing(8)

        self._current_phase_label = QLabel("Current phase: -")
        self._baseline_label = QLabel("Latest baseline: -")
        info_layout.addWidget(self._current_phase_label)
        info_layout.addWidget(self._baseline_label)
        layout.addWidget(self._info_group)

        # Summary display
        summary_group = QGroupBox("Handoff Summary")
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.setContentsMargins(4, 4, 4, 4)

        self._summary_edit = QTextEdit()
        self._summary_edit.setReadOnly(True)
        self._summary_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._summary_edit.setMinimumHeight(200)
        summary_layout.addWidget(self._summary_edit)
        layout.addWidget(summary_group, 1)

        # Document selection for export
        doc_group = QGroupBox("Select Documents for Export")
        doc_layout = QVBoxLayout(doc_group)
        doc_layout.setContentsMargins(4, 4, 4, 4)

        self._doc_table = QTableWidget()
        self._doc_table.setColumnCount(4)
        self._doc_table.setHorizontalHeaderLabels(
            ["Select", "Area", "Category", "Title"]
        )
        self._doc_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._doc_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._doc_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._doc_table.horizontalHeader().setStretchLastSection(True)
        self._doc_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._doc_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._doc_table.customContextMenuRequested.connect(self._show_doc_context_menu)
        doc_layout.addWidget(self._doc_table)
        layout.addWidget(doc_group, 1)

        # Export buttons
        btn_row = QHBoxLayout()
        self._generate_btn = QPushButton("Generate Summary")
        self._generate_btn.clicked.connect(self.generate_summary)
        btn_row.addWidget(self._generate_btn)

        self._export_md_btn = QPushButton("Export Markdown")
        self._export_md_btn.clicked.connect(self._export_markdown_clicked)
        btn_row.addWidget(self._export_md_btn)

        self._export_zip_btn = QPushButton("Export ZIP")
        self._export_zip_btn.clicked.connect(self._export_zip_clicked)
        btn_row.addWidget(self._export_zip_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self.set_writable(False)

    def _show_doc_context_menu(self, pos: QPoint) -> None:
        """Show context menu for document table."""
        item = self._doc_table.itemAt(pos)
        if not item:
            return
        row = item.row()
        if row >= len(self._documents):
            return

        menu = QMenu(self)

        open_action = menu.addAction("Open")
        open_action.triggered.connect(lambda: self._open_document(row))
        delete_action = menu.addAction("Delete...")
        writable = bool(self.state and self.state.sync.is_writable())
        delete_action.setEnabled(writable)
        delete_action.triggered.connect(
            lambda: request_secure_delete(
                self,
                "document",
                self._documents[row]["id"],
                protected=False,
                writable=writable,
                on_deleted=lambda _result: self._load_handoff_data(),
            )
        )

        menu.exec(self._doc_table.viewport().mapToGlobal(pos))

    def _open_document(self, row: int) -> None:
        """Open a document from the table."""
        doc = self._documents[row]
        latest_version = doc.get("latest_version", {})
        storage_path = latest_version.get("storage_path", "")
        if storage_path:
            try:
                temp_path = temp_dir() / f"{doc['id']}-{latest_version.get('file_name', 'file')}"
                download_file(storage_path, str(temp_path))
                open_with_default_app(temp_path)
            except Exception as exc:
                show_error(self, f"Failed to open document: {exc}")

    def on_show(self) -> None:
        """Called when the screen becomes active."""
        if self.state and self.state.project:
            if (
                self._project is None
                or self._project.get("id") != self.state.project.get("id")
            ):
                self.on_project_changed(self.state.project)
            else:
                self._load_handoff_data()

    def on_project_changed(self, project: Row | None) -> None:
        """Called when the selected project changes."""
        self._load_generation += 1
        self._project = project
        self._handoff_data = None
        self._documents = []
        self._selected_doc_ids.clear()
        self._clear_ui()
        if project and self.isVisible():
            self._load_handoff_data()

    def on_phase_changed(self, phase: Row | None) -> None:
        """The handoff data is project-scoped and already contains all phases."""

    def reload(self) -> None:
        """Reload data from the server."""
        if self._project:
            self._load_handoff_data()

    def _load_handoff_data(self) -> None:
        """Load handoff data for the current project."""
        if not self._project:
            return
        if self._load_in_flight:
            self._load_pending = True
            return

        project_id = self._project["id"]
        generation = self._load_generation
        self._load_in_flight = True
        self._load_pending = False
        run_async(
            lambda: fetch_handoff_data(project_id),
            on_success=lambda result, p=project_id, g=generation: (
                self._on_handoff_data_result(result, p, g)
            ),
            on_error=lambda exc, p=project_id, g=generation: (
                self._on_handoff_data_error(exc, p, g)
            ),
        )

    def _on_handoff_data_result(
        self, handoff_data: dict[str, Any], project_id: str, generation: int
    ) -> None:
        self._load_in_flight = False
        if (
            generation != self._load_generation
            or self._project is None
            or self._project.get("id") != project_id
        ):
            self._load_pending = False
            if self._project:
                self._load_handoff_data()
            return

        self._on_handoff_data_loaded(handoff_data)
        if self._load_pending:
            self._load_pending = False
            self._load_handoff_data()

    def _on_handoff_data_error(
        self, exc: Exception, project_id: str, generation: int
    ) -> None:
        self._load_in_flight = False
        if (
            generation != self._load_generation
            or self._project is None
            or self._project.get("id") != project_id
        ):
            self._load_pending = False
            if self._project:
                self._load_handoff_data()
            return

        self._load_pending = False
        show_error(self, f"Failed to load handoff data: {exc}")

    def _on_handoff_data_loaded(self, handoff_data: dict[str, Any]) -> None:
        """Handle loaded handoff data."""
        self._handoff_data = handoff_data
        self._documents = handoff_data.get("documents", [])
        self._update_info_display()
        self.generate_summary()
        self._populate_doc_table()

    def _update_info_display(self) -> None:
        """Update the project info display."""
        if not self._handoff_data:
            return

        phases = self._handoff_data.get("phases", [])
        current_phase = None
        for p in phases:
            if p.get("status") != "baseline_approved":
                current_phase = p
                break

        if current_phase:
            phase_no = current_phase.get("phase_no", 0)
            title = current_phase.get("title", "")
            status = current_phase.get("status", "unknown")
            attempt = current_phase.get("current_attempt", 0)
            status_label = STATUS_LABELS.get(status, status)
            self._current_phase_label.setText(
                f"Current phase: {phase_no:02d} — {title} (status: {status_label}, attempt {attempt})"
            )
        else:
            self._current_phase_label.setText("Current phase: None")

        baselines = self._handoff_data.get("baselines", [])
        if baselines:
            latest = baselines[0]
            # phase_id from the join is a dict like {"phase_no": 1}, but handle None/other gracefully
            phase_id_obj = latest.get("phase_id")
            if isinstance(phase_id_obj, dict):
                phase_no = phase_id_obj.get("phase_no", 0)
            else:
                phase_no = 0
            attempt = latest.get("attempt_no", 0)
            git_head = latest.get("git_head", "")[:8] if latest.get("git_head") else "-"
            branch = latest.get("branch", "")
            working_tree = latest.get("working_tree", "unknown")
            date = latest.get("created_at", "Unknown")[:10] if latest.get("created_at") else "Unknown"
            self._baseline_label.setText(
                f"Latest baseline: Phase {phase_no:02d} (attempt {attempt}), "
                f"Git: {git_head} ({branch}), working tree: {working_tree}, on {date}"
            )
        else:
            self._baseline_label.setText("Latest baseline: None")

    def _clear_ui(self) -> None:
        """Clear the UI when no project is selected."""
        self._current_phase_label.setText("Current phase: -")
        self._baseline_label.setText("Latest baseline: -")
        self._status_label.clear()
        self._summary_edit.clear()
        self._doc_table.setRowCount(0)
        self._documents = []
        self._selected_doc_ids.clear()

    def _populate_doc_table(self) -> None:
        """Populate the document selection table."""
        documents = self._documents
        self._doc_table.setRowCount(len(documents))

        for row, doc in enumerate(documents):
            # Select checkbox
            select_cb = QCheckBox()
            select_cb.setChecked(doc["id"] in self._selected_doc_ids)
            select_cb.stateChanged.connect(
                lambda state, doc_id=doc["id"]: self._on_select_changed(state, doc_id)
            )
            self._doc_table.setCellWidget(row, 0, select_cb)

            # Area
            area = doc.get("area", "")
            self._doc_table.setItem(row, 1, QTableWidgetItem(area))

            # Category
            category = doc.get("category", "")
            self._doc_table.setItem(row, 2, QTableWidgetItem(category))

            # Title
            title = doc.get("title", "")
            self._doc_table.setItem(row, 3, QTableWidgetItem(title))

        self._doc_table.resizeColumnsToContents()
        self._doc_table.horizontalHeader().setStretchLastSection(True)

    def _on_select_changed(self, state: int, doc_id: str) -> None:
        """Handle document selection change."""
        if state == Qt.CheckState.Checked.value:
            self._selected_doc_ids.add(doc_id)
        else:
            self._selected_doc_ids.discard(doc_id)

    def generate_summary(self) -> None:
        """Generate the handoff summary from current data."""
        if not self._handoff_data:
            show_error(self, "No handoff data available. Please select a project.")
            return
        self._summary_edit.setPlainText(build_summary_markdown(self._handoff_data))

    def export_markdown(self) -> None:
        """Export the handoff summary as a markdown file."""
        if not self._handoff_data:
            show_error(self, "No handoff data available. Please select a project.")
            return
        if not self.state.sync.is_writable():
            show_error(self, "Cannot write while offline or saving.")
            return

        default_dir = default_export_dir()
        project_name = self._project.get("name", "project") if self._project else "project"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        default_path = default_dir / f"handoff-{project_name}-{timestamp}.md"

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Markdown",
            str(default_path),
            "Markdown Files (*.md);;All Files (*)",
        )
        if not path:
            return

        try:
            export_markdown(self._handoff_data, path)
            self._status_label.setText(f"Summary exported to:\n{path}")
        except Exception as exc:
            show_error(self, f"Failed to export markdown: {exc}")

    def _export_markdown_clicked(self) -> None:
        """Handler for Export Markdown button click."""
        self.export_markdown()

    def export_zip(self) -> None:
        """Export the handoff as a ZIP package."""
        if not self._handoff_data:
            show_error(self, "No handoff data available. Please select a project.")
            return
        if not self.state.sync.is_writable():
            show_error(self, "Cannot write while offline or saving.")
            return
        if not any(
            doc.get("id") in self._selected_doc_ids
            and (doc.get("latest_version") or {}).get("storage_path")
            for doc in self._documents
        ):
            QMessageBox.warning(
                self,
                "No Documents Selected",
                "Select at least one document with a saved file before exporting a ZIP.",
            )
            return

        default_dir = default_export_dir()
        project_name = self._project.get("name", "project") if self._project else "project"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        default_path = default_dir / f"handoff-{project_name}-{timestamp}.zip"

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export ZIP",
            str(default_path),
            "ZIP Files (*.zip);;All Files (*)",
        )
        if not path:
            return

        # Collect selected documents info for async download
        docs_to_download = []
        for doc_id in self._selected_doc_ids:
            doc = None
            for d in self._documents:
                if d["id"] == doc_id:
                    doc = d
                    break
            if doc and doc.get("latest_version"):
                version = doc["latest_version"]
                storage_path = version.get("storage_path", "")
                if storage_path:
                    temp_path = temp_dir() / f"{doc_id}-{version.get('file_name', 'file')}"
                    docs_to_download.append({
                        "doc": doc,
                        "version": version,
                        "storage_path": storage_path,
                        "temp_path": temp_path,
                    })

        def _download_and_zip():
            # Download all files in worker thread
            files_to_export = []
            downloaded_temp_paths = []
            try:
                for item in docs_to_download:
                    download_file(item["storage_path"], str(item["temp_path"]))
                    downloaded_temp_paths.append(item["temp_path"])
                    files_to_export.append(
                        (f"{item['doc']['area']}/{item['doc']['category']}/{item['version']['file_name']}", item["temp_path"])
                    )
                # Create zip
                export_zip(self._handoff_data, path, files_to_export)
                return path
            finally:
                # Clean up temp files always
                for temp_path in downloaded_temp_paths:
                    try:
                        temp_path.unlink()
                    except Exception:
                        pass

        run_async(
            _download_and_zip,
            on_success=lambda p: self._status_label.setText(f"ZIP exported to:\n{p}"),
            on_error=lambda exc: show_error(self, f"Failed to export ZIP: {exc}"),
        )

    def _export_zip_clicked(self) -> None:
        """Handler for Export ZIP button click."""
        self.export_zip()

    def choose_documents(self) -> None:
        """Select all or specific documents for export."""
        # This method exists for programmatic control
        # The UI uses the checkboxes directly
        pass

    def set_writable(self, writable: bool) -> None:
        """Enable/disable write controls based on sync state."""
        self._generate_btn.setEnabled(writable)
        self._export_md_btn.setEnabled(writable)
        self._export_zip_btn.setEnabled(writable)


# ===== SECTION: Module-level helpers =====

def get_screen_class() -> type[ScreenG]:
    """Return the ScreenG class for registry loading."""
    return ScreenG
