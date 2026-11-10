"""
ui/panels.py — shared panels: the Top Bar (frame of 06), the document
panel used by Screens A and B, and their dialogs.

Phase 4A: the Top Bar and DocumentPanel are a pure move from
ui/shell.py and ui/screens_ab.py. The Settings dialog (Phase 4) and the
AI dock (Phase 6) are added to this file in later steps.
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFileDialog, QMenu, QDialog,
    QGroupBox, QFormLayout, QDialogButtonBox, QMessageBox,
)

import data
from data import (
    list_documents,
    create_document,
    update_document,
    archive_document,
    list_document_versions,
    add_document_version,
    upload_file,
    download_file,
    set_project_archived,
    ValidationError,
    ConflictError,
    OfflineError,
)
from services import (
    APP_NAME,
    SCREEN_ACCENTS,
    format_phase_label,
    screen_label,
    open_with_default_app,
    validate_attachment,
    temp_dir,
)
from ui.shell import (
    run_async,
    show_error,
    confirm,
)
from ui.secure_delete import request_secure_delete

Row = dict[str, Any]
Rows = list[Row]

NEW_PROJECT_ENTRY: str = "+ New project..."
ARCHIVED_ENTRY: str = "Archived projects..."
_DOC_MENU: list[str] = [
    "Open", "Download", "Replace", "Edit...", "Versions...", "Archive",
    "Delete...",
]


# ===== SECTION: Markdown rendering =====

def _inline_md(text: str) -> str:
    """Render inline Markdown fragments of *text* to HTML."""
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", escaped)
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', escaped
    )
    return escaped


def _markdown_to_html(text: str) -> str:
    """Render a small Markdown subset to HTML (no third-party libraries)."""
    out: list[str] = []
    para: list[str] = []
    in_code = False
    in_list: str | None = None
    in_table = False
    table_rows: list[list[str]] = []
    table_aligns: list[str] = []

    def flush_para() -> None:
        if para:
            out.append("<p>" + _inline_md(" ".join(para)) + "</p>")
            para.clear()

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None

    def flush_table() -> None:
        nonlocal in_table, table_rows, table_aligns
        if table_rows:
            out.append("<table>")
            # Header row
            out.append("<thead><tr>")
            for i, cell in enumerate(table_rows[0]):
                align = table_aligns[i] if i < len(table_aligns) else ""
                style = f' style="text-align:{align};"' if align else ""
                out.append(f"<th{style}>{_inline_md(cell)}</th>")
            out.append("</tr></thead>")
            # Body rows
            if len(table_rows) > 1:
                out.append("<tbody>")
                for row in table_rows[1:]:
                    out.append("<tr>")
                    for i, cell in enumerate(row):
                        align = table_aligns[i] if i < len(table_aligns) else ""
                        style = f' style="text-align:{align};"' if align else ""
                        out.append(f"<td{style}>{_inline_md(cell)}</td>")
                    out.append("</tr>")
                out.append("</tbody>")
            out.append("</table>")
        in_table = False
        table_rows = []
        table_aligns = []

    for raw in text.splitlines():
        line = raw.rstrip()
        if line.strip().startswith("```"):
            flush_para()
            close_list()
            flush_table()
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                out.append("<pre><code>")
                in_code = True
            continue
        if in_code:
            out.append(html.escape(raw))
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            flush_para()
            close_list()
            flush_table()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline_md(heading.group(2))}</h{level}>")
            continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", line.strip()):
            flush_para()
            close_list()
            flush_table()
            out.append("<hr/>")
            continue
        if line.lstrip().startswith(">"):
            flush_para()
            close_list()
            flush_table()
            quoted = line.lstrip().lstrip(">").strip()
            out.append("<blockquote>" + _inline_md(quoted) + "</blockquote>")
            continue
        # Table detection: lines starting and ending with | (or at least containing |)
        if "|" in line and line.strip().startswith("|") and line.strip().endswith("|"):
            flush_para()
            close_list()
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not in_table:
                # Check if this is a separator row (--- | ---)
                if all(re.match(r"^:?-+:?$", c) for c in cells):
                    # This shouldn't happen as first row, but handle gracefully
                    table_aligns = []
                    for c in cells:
                        if c.startswith(":") and c.endswith(":"):
                            table_aligns.append("center")
                        elif c.startswith(":"):
                            table_aligns.append("left")
                        elif c.endswith(":"):
                            table_aligns.append("right")
                        else:
                            table_aligns.append("")
                    in_table = True
                    continue
                else:
                    # Header row
                    table_rows.append(cells)
                    in_table = True
                    continue
            else:
                # Check if this is a separator row
                if all(re.match(r"^:?-+:?$", c) for c in cells):
                    table_aligns = []
                    for c in cells:
                        if c.startswith(":") and c.endswith(":"):
                            table_aligns.append("center")
                        elif c.startswith(":"):
                            table_aligns.append("left")
                        elif c.endswith(":"):
                            table_aligns.append("right")
                        else:
                            table_aligns.append("")
                    continue
                else:
                    # Data row
                    table_rows.append(cells)
                    continue
        else:
            if in_table:
                flush_table()
        item = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if item:
            flush_para()
            close_list()
            marker = item.group(2)
            kind = "ol" if marker[0].isdigit() else "ul"
            if in_list != kind:
                close_list()
                out.append(f"<{kind}>")
                in_list = kind
            out.append("<li>" + _inline_md(item.group(3)) + "</li>")
            continue
        close_list()
        if not line.strip():
            flush_para()
            continue
        para.append(line.strip())
    flush_para()
    close_list()
    flush_table()
    if in_code:
        out.append("</code></pre>")
    body = "\n".join(out)
    return (
        "<html><body style=\"font-family: 'Segoe UI', sans-serif; "
        f"font-size: 13px;\">{body}</body></html>"
    )


# ===== SECTION: Document edit dialog =====

class _EditDocumentDialog(QDialog):
    """Edit... dialog: title, category, notes, status (Draft / Approved)."""

    def __init__(self, doc: Row, categories: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit Document")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._title_edit = QLineEdit(doc.get("title", ""))
        form.addRow("Title:", self._title_edit)

        self._category_combo = QComboBox()
        for cat in categories:
            self._category_combo.addItem(cat)
        current = doc.get("category", "")
        idx = self._category_combo.findText(current)
        if idx >= 0:
            self._category_combo.setCurrentIndex(idx)
        form.addRow("Category:", self._category_combo)

        self._notes_edit = QTextEdit(doc.get("notes", ""))
        self._notes_edit.setMinimumHeight(90)
        form.addRow("Notes:", self._notes_edit)

        self._status_combo = QComboBox()
        self._status_combo.addItem("Draft", "draft")
        self._status_combo.addItem("Approved", "approved")
        status = doc.get("status", "draft")
        self._status_combo.setCurrentIndex(1 if status == "approved" else 0)
        form.addRow("Status:", self._status_combo)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        """Refuse an empty title; otherwise keep the values."""
        if not self._title_edit.text().strip():
            show_error(self, "Title cannot be empty.")
            return
        super().accept()

    def values(self) -> dict[str, Any]:
        """Return the edited field values."""
        return {
            "title": self._title_edit.text().strip(),
            "category": self._category_combo.currentText(),
            "notes": self._notes_edit.toPlainText(),
            "status": self._status_combo.currentData(),
        }


# ===== SECTION: Versions dialog =====

class _VersionsDialog(QDialog):
    """Versions... dialog: version table of one document."""

    def __init__(self, doc: Row, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Versions — {doc.get('title', '')}")
        self.setMinimumSize(480, 260)
        layout = QVBoxLayout(self)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ["Version", "File", "Size", "Date"]
        )
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        layout.addWidget(self._table)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def set_versions(self, versions: Rows) -> None:
        """Fill the table with version rows (newest first)."""
        self._table.setRowCount(len(versions))
        for row, ver in enumerate(versions):
            self._table.setItem(
                row, 0, QTableWidgetItem(str(ver.get("version_no", "")))
            )
            self._table.setItem(
                row, 1, QTableWidgetItem(ver.get("file_name", ""))
            )
            size = ver.get("size_bytes", 0)
            self._table.setItem(row, 2, QTableWidgetItem(f"{size:,} bytes"))
            created = (ver.get("created_at") or "")[:19]
            self._table.setItem(row, 3, QTableWidgetItem(created))


# ===== SECTION: Archived projects dialog =====

class ArchivedProjectsDialog(QDialog):
    """'Archived projects...' list with a Reopen action per row."""

    reopened = Signal(str)

    def __init__(self, parent: QWidget | None = None, writable: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Archived projects")
        self.setMinimumSize(420, 300)
        self._writable = writable
        self._rows: Rows = []
        layout = QVBoxLayout(self)

        hint = QLabel("Archived projects of this account:")
        layout.addWidget(hint)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Project", "", ""])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.setColumnWidth(1, 84)
        self._table.setColumnWidth(2, 44)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        layout.addWidget(self._table)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._status = QLabel("Loading…")
        layout.addWidget(self._status)
        self._load()

    def _load(self) -> None:
        run_async(
            lambda: data.list_projects(include_archived=True),
            on_success=self._on_loaded,
            on_error=self._on_error,
        )

    def _on_loaded(self, projects: Rows) -> None:
        archived = [p for p in projects if p.get("archived_at")]
        self._rows = archived
        self._table.setRowCount(len(archived))
        for row, proj in enumerate(archived):
            self._table.setItem(row, 0, QTableWidgetItem(proj["name"]))
            btn = QPushButton("Reopen")
            btn.setEnabled(self._writable)
            btn.clicked.connect(
                lambda _=False, r=row: self._reopen(r)
            )
            self._table.setCellWidget(row, 1, btn)
            menu_btn = QPushButton("...")
            menu_btn.setFixedWidth(36)
            menu_btn.clicked.connect(
                lambda _=False, r=row: self._show_row_menu(r)
            )
            self._table.setCellWidget(row, 2, menu_btn)
        self._status.setText(
            "No archived projects." if not archived else f"{len(archived)} archived."
        )

    def _on_error(self, exc: Exception) -> None:
        self._status.setText(f"Failed to load: {exc}")

    def _show_row_menu(self, row: int) -> None:
        if row >= len(self._rows):
            return
        project = self._rows[row]
        menu = QMenu(self)
        delete_action = menu.addAction("Delete...")
        delete_action.setEnabled(self._writable)
        delete_action.triggered.connect(
            lambda: request_secure_delete(
                self,
                "project",
                project["id"],
                protected=True,
                writable=self._writable,
                on_deleted=lambda _result: self._load(),
            )
        )
        button = self._table.cellWidget(row, 2)
        if button:
            menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _reopen(self, row: int) -> None:
        if row >= len(self._rows):
            return
        if not self._writable:
            show_error(self, "Cannot reopen while offline or saving.")
            return
        proj = self._rows[row]

        def _do() -> Row:
            return set_project_archived(proj["id"], proj["version"], False)

        run_async(
            _do,
            on_success=lambda _updated, r=row, p=proj: self._on_reopened(r, p),
            on_error=lambda exc: show_error(self, f"Reopen failed: {exc}"),
        )

    def _on_reopened(self, row: int, proj: Row) -> None:
        self.reopened.emit(proj["id"])
        QMessageBox.information(
            self, "Reopened", f"Project '{proj['name']}' was reopened."
        )
        self._load()


# ===== SECTION: DocumentPanel =====

class DocumentPanel(QWidget):
    """Shared document list + row menu panel (used by Screen A and B).

    area == "foundation" (Screen A): Document / Status / [ ... ] table.
    area == "ui_visual" (Screen B): search + category line, Document /
    Updated / Status / [ ... ] table and a Preview panel.
    """

    def __init__(self, area: str, categories: list[str], accent: str):
        super().__init__()
        self.area = area
        self.categories = categories
        self.accent = accent
        self._project: Row | None = None
        self._documents: Rows = []
        self._selected_doc: Row | None = None
        self._selected_version: Row | None = None
        self._loaded_versions: Rows = []
        self._load_epoch = 0
        self._preview_epoch = 0
        self._writable = False
        self._draft: dict[str, Any] = {}
        self._build_ui()

    # --- construction ---

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        if self.area == "foundation":
            toolbar.addWidget(QLabel("Search:"))
            self._search_edit = QLineEdit()
            self._search_edit.setPlaceholderText("Search by title...")
            toolbar.addWidget(self._search_edit, 1)
            toolbar.addWidget(QLabel("Category:"))
            self._category_filter = QComboBox()
            self._category_filter.addItem("All", None)
            for cat in self.categories:
                self._category_filter.addItem(cat, cat)
            toolbar.addWidget(self._category_filter)
            self._add_btn = QPushButton("+ Add document")
            self._add_btn.clicked.connect(self.add_document)
            toolbar.addWidget(self._add_btn)
        else:
            toolbar.addWidget(QLabel("Search:"))
            self._search_edit = QLineEdit()
            self._search_edit.setPlaceholderText("Search by title…")
            toolbar.addWidget(self._search_edit, 1)
            toolbar.addWidget(QLabel("Category:"))
            self._category_filter = QComboBox()
            self._category_filter.addItem("All", None)
            for cat in self.categories:
                self._category_filter.addItem(cat, cat)
            toolbar.addWidget(self._category_filter)
            self._add_btn = None
        layout.addLayout(toolbar)

        if self._search_edit is not None:
            self._search_timer = QTimer(self)
            self._search_timer.setSingleShot(True)
            self._search_timer.setInterval(300)
            self._search_timer.timeout.connect(self._reload_documents)
            self._search_edit.textChanged.connect(
                lambda _t: self._search_timer.start()
            )
            self._category_filter.currentIndexChanged.connect(
                self._reload_documents
            )

        columns = ["Document", "Updated", "Status"]
        columns.append("")
        self._table = QTableWidget(0, len(columns))
        self._table.setHorizontalHeaderLabels(columns)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(columns) - 1):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(columns) - 1,
                                    QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(len(columns) - 1, 44)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table.itemSelectionChanged.connect(self._on_row_selected)
        layout.addWidget(self._table, 1)

        self._empty_label = QLabel("")
        self._empty_label.setStyleSheet("color: #888888; background-color: transparent;")
        layout.addWidget(self._empty_label)

        self._preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(self._preview_group)
        self._preview_edit = QTextEdit()
        self._preview_edit.setReadOnly(True)
        self._preview_edit.setMinimumHeight(110)
        preview_layout.addWidget(self._preview_edit)
        layout.addWidget(self._preview_group, 1)

        self.set_writable(False)

    # --- loading ---

    def load(self, project: Row | None) -> None:
        """Load documents for the given project."""
        self._project = project
        self._load_epoch += 1
        self._preview_epoch += 1
        self._documents = []
        self._selected_doc = None
        self._selected_version = None
        self._loaded_versions = []
        self._table.setRowCount(0)
        self._empty_label.setText(
            "" if project else "Select a project to see its documents."
        )
        if self._preview_group is not None:
            self._preview_edit.clear()
        if project:
            self._reload_documents()

    def _reload_documents(self) -> None:
        """Reload documents from the server (filters applied)."""
        if not self._project:
            return
        self._load_epoch += 1
        epoch = self._load_epoch
        category = None
        search = None
        if self._category_filter is not None:
            category = self._category_filter.currentData()
        if self._search_edit is not None:
            search = self._search_edit.text().strip() or None
        project_id = self._project["id"]
        area = self.area

        def _fetch() -> Rows:
            return list_documents(
                project_id, area, category=category, search=search
            )

        run_async(
            _fetch,
            on_success=lambda docs, e=epoch: self._on_documents_loaded(docs, e),
            on_error=lambda exc, e=epoch: self._on_load_error(exc, e),
        )

    def _on_documents_loaded(self, docs: Rows, epoch: int) -> None:
        if epoch != self._load_epoch:
            return  # stale result: a newer selection wins
        self._documents = docs
        self._table.setRowCount(len(docs))
        cols = self._table.columnCount()
        for row, doc in enumerate(docs):
            title_item = QTableWidgetItem(doc.get("title", ""))
            title_item.setData(Qt.ItemDataRole.UserRole, doc["id"])
            self._table.setItem(row, 0, title_item)
            if cols == 4:
                updated = (doc.get("updated_at") or doc.get("created_at") or "")[:10]
                self._table.setItem(row, 1, QTableWidgetItem(updated))
                status_col = 2
            else:
                status_col = 1
            status = "Approved" if doc.get("status") == "approved" else "Draft"
            self._table.setItem(row, status_col, QTableWidgetItem(status))
            menu_btn = QPushButton("...")
            menu_btn.setFixedWidth(36)
            menu_btn.clicked.connect(
                lambda _=False, r=row: self._show_row_menu(r)
            )
            self._table.setCellWidget(row, cols - 1, menu_btn)
        if docs:
            self._empty_label.setText("")
            self._table.selectRow(0)
        else:
            self._empty_label.setText("No documents yet.")

    def _on_load_error(
        self, exc: Exception, epoch: int | None = None, doc_id: str | None = None
    ) -> None:
        if epoch is not None and epoch != self._load_epoch:
            return
        if doc_id is not None and (
            self._selected_doc is None or self._selected_doc.get("id") != doc_id
        ):
            return
        show_error(self, f"Failed to load documents: {exc}")

    def _on_row_selected(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            self._selected_doc = None
            self._selected_version = None
            return
        row = rows[0].row()
        if row >= len(self._documents):
            return
        self._selected_doc = self._documents[row]
        self._selected_version = None
        self._load_versions()
        if self._preview_group is not None:
            self._load_preview(self._selected_doc)

    def _load_versions(self) -> None:
        if not self._selected_doc:
            return
        doc_id = self._selected_doc["id"]
        epoch = self._load_epoch
        run_async(
            lambda: list_document_versions(doc_id),
            on_success=lambda versions, e=epoch, d=doc_id: (
                self._on_versions_loaded(versions, e, d)
            ),
            on_error=lambda exc, e=epoch, d=doc_id: self._on_load_error(
                exc, e, d
            ),
        )

    def _on_versions_loaded(
        self, versions: Rows, epoch: int, doc_id: str
    ) -> None:
        if (
            epoch != self._load_epoch
            or self._selected_doc is None
            or self._selected_doc.get("id") != doc_id
        ):
            return
        self._loaded_versions = versions
        self._selected_version = versions[0] if versions else None

    def _pick_version(self) -> Row | None:
        """Return the selected version, or the newest as a fallback."""
        if self._selected_version is not None:
            return self._selected_version
        if self._loaded_versions:
            return self._loaded_versions[0]
        if self._selected_doc and self._selected_doc.get("latest_version"):
            return self._selected_doc["latest_version"]
        return None

    # --- preview (Screen B) ---

    def _load_preview(self, doc: Row) -> None:
        if self._preview_group is None:
            return
        latest = doc.get("latest_version")
        if not latest:
            self._preview_edit.setPlainText("No file uploaded yet.")
            return
        name = latest.get("file_name", "")
        ext = Path(name).suffix.lower()
        if ext not in (".md", ".txt"):
            self._preview_edit.setPlainText("No preview - use Open")
            return
        self._preview_edit.setPlainText("Loading preview…")
        self._preview_epoch += 1
        epoch = self._preview_epoch
        storage_path = latest["storage_path"]
        dest = temp_dir() / f"preview-{doc['id']}-{name}"

        def _fetch() -> str:
            download_file(storage_path, str(dest))
            return Path(dest).read_text(encoding="utf-8", errors="replace")

        run_async(
            _fetch,
            on_success=lambda text, e=epoch: self._on_preview_ready(text, e, ext),
            on_error=lambda exc, e=epoch: self._on_preview_error(exc, e),
        )

    def _on_preview_ready(self, text: str, epoch: int, ext: str) -> None:
        if epoch != self._preview_epoch:
            return  # stale preview: a newer selection wins
        if ext == ".md":
            self._preview_edit.setHtml(_markdown_to_html(text))
        else:
            self._preview_edit.setPlainText(text)

    def _on_preview_error(self, exc: Exception, epoch: int) -> None:
        if epoch != self._preview_epoch:
            return
        if self._preview_group is not None:
            self._preview_edit.setPlainText(f"Preview failed: {exc}")

    # --- row menu ---

    def _show_row_menu(self, row: int) -> None:
        if row >= len(self._documents):
            return
        self._table.selectRow(row)
        menu = QMenu(self)
        actions: dict[str, Any] = {}
        for label in _DOC_MENU:
            act = menu.addAction(label)
            actions[label] = act
        actions["Open"].triggered.connect(self.open_selected)
        actions["Download"].triggered.connect(self.download_selected)
        for write_label in ("Replace", "Edit...", "Archive", "Delete..."):
            actions[write_label].setEnabled(self._writable)
        actions["Replace"].triggered.connect(self.replace_selected)
        actions["Edit..."].triggered.connect(self._edit_selected)
        actions["Versions..."].triggered.connect(self._versions_selected)
        actions["Archive"].triggered.connect(self._archive_selected)
        actions["Delete..."].triggered.connect(self._delete_selected)
        btn = self._table.cellWidget(row, self._table.columnCount() - 1)
        pos = btn.mapToGlobal(btn.rect().bottomLeft()) if btn else None
        if pos is None:
            pos = self._table.viewport().mapToGlobal(
                self._table.rect().topLeft()
            )
        menu.exec(pos)

    def _require_selection(self) -> bool:
        if not self._selected_doc:
            show_error(self, "Select a document first.")
            return False
        return True

    def _require_write(self) -> bool:
        if not self._writable:
            show_error(self, "Cannot change documents while offline or saving.")
            return False
        return True

    # --- actions ---

    def add_document(self) -> None:
        """Add document: file picker, validate, upload, version 1 (Draft)."""
        if not self._project:
            show_error(self, "Select a project first.")
            return
        if not self._require_write():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Add Document",
            filter="Allowed Files (*.md *.txt *.pdf *.docx *.png *.jpg "
                   "*.jpeg *.json *.csv)",
        )
        if not path:
            return  # cancel creates nothing
        if self._category_filter is not None:
            category = self._category_filter.currentData()
        else:
            category = None
        if not category:
            category = self.categories[0] if self.categories else "Other"
        title = Path(path).stem
        self.set_writable(False)
        run_async(
            lambda: self._do_add_document(path, category, title),
            on_success=self._on_doc_created,
            on_error=self._on_action_error,
        )

    def _do_add_document(self, local_path: str, category: str, title: str) -> Row:
        validate_attachment(local_path)
        file_info = upload_file(self._project["id"], local_path)
        doc = create_document(
            self._project["id"], self.area, category, title, ""
        )
        add_document_version(doc["id"], self._project["id"], file_info)
        return doc

    def _on_doc_created(self, doc: Row) -> None:
        self.set_writable(True)
        self._reload_documents()
        QMessageBox.information(
            self, "Document Added",
            f"'{doc['title']}' added as Version 1 (Draft).",
        )

    def open_selected(self) -> None:
        if not self._require_selection():
            return
        ver = self._pick_version()
        if ver is None:
            show_error(self, "This document has no file versions yet.")
            return
        dest = temp_dir() / ver["file_name"]
        storage_path = ver["storage_path"]
        run_async(
            lambda: download_file(storage_path, str(dest)),
            on_success=lambda _: open_with_default_app(dest),
            on_error=self._on_action_error,
        )

    def download_selected(self) -> None:
        if not self._require_selection():
            return
        ver = self._pick_version()
        if ver is None:
            show_error(self, "This document has no file versions yet.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save As", ver["file_name"]
        )
        if not path:
            return
        storage_path = ver["storage_path"]
        run_async(
            lambda: download_file(storage_path, path),
            on_success=lambda _p, dest=path: QMessageBox.information(
                self, "Downloaded", f"Saved to:\n{dest}"
            ),
            on_error=self._on_action_error,
        )

    def replace_selected(self) -> None:
        if not self._require_selection():
            return
        if not self._require_write():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Select File to Replace With",
            filter="Allowed Files (*.md *.txt *.pdf *.docx *.png *.jpg "
                   "*.jpeg *.json *.csv)",
        )
        if not path:
            return  # cancel creates nothing
        self.set_writable(False)
        run_async(
            lambda: self._do_replace(path),
            on_success=self._on_replace_done,
            on_error=self._on_action_error,
        )

    def _do_replace(self, local_path: str) -> Row:
        validate_attachment(local_path)
        file_info = upload_file(self._project["id"], local_path)
        return add_document_version(
            self._selected_doc["id"], self._project["id"], file_info
        )

    def _on_replace_done(self, ver: Row) -> None:
        self.set_writable(True)
        self._load_versions()
        self._reload_documents()
        QMessageBox.information(
            self, "Replaced",
            f"Document updated to Version {ver['version_no']}.",
        )

    def _edit_selected(self) -> None:
        if not self._require_selection():
            return
        if not self._require_write():
            return
        dialog = _EditDocumentDialog(self._selected_doc, self.categories, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._draft = dialog.values()
            self.save_details()

    def _versions_selected(self) -> None:
        if not self._require_selection():
            return
        dialog = _VersionsDialog(self._selected_doc, self)
        doc_id = self._selected_doc["id"]
        run_async(
            lambda: list_document_versions(doc_id),
            on_success=dialog.set_versions,
            on_error=lambda exc: show_error(dialog, f"Failed: {exc}"),
        )
        dialog.exec()

    def _archive_selected(self) -> None:
        if not self._require_selection():
            return
        if not self._require_write():
            return
        title = self._selected_doc.get("title", "")
        if not confirm(self, f"Archive document '{title}'?"):
            return
        doc_id = self._selected_doc["id"]
        version = self._selected_doc["version"]
        self.set_writable(False)
        run_async(
            lambda: archive_document(doc_id, version),
            on_success=self._on_archive_done,
            on_error=self._on_action_error,
        )

    def _delete_selected(self) -> None:
        if not self._require_selection():
            return
        if not self._require_write():
            return
        assert self._selected_doc is not None
        request_secure_delete(
            self,
            "document",
            self._selected_doc["id"],
            protected=False,
            writable=self._writable,
            on_deleted=self._on_document_deleted,
        )

    def _on_document_deleted(self, _result: dict[str, Any]) -> None:
        self._selected_doc = None
        self._reload_documents()

    def _on_archive_done(self, _archived: Row) -> None:
        self.set_writable(True)
        self._reload_documents()
        QMessageBox.information(self, "Archived", "Document archived.")

    def save_details(self) -> None:
        """Save the draft collected by the Edit... dialog (versioned)."""
        if not self._require_selection():
            return
        if not self._require_write():
            return
        changes = dict(self._draft) if self._draft else {
            "title": self._selected_doc.get("title", ""),
            "category": self._selected_doc.get("category", ""),
            "notes": self._selected_doc.get("notes", ""),
            "status": self._selected_doc.get("status", "draft"),
        }
        if not str(changes.get("title", "")).strip():
            show_error(self, "Title cannot be empty.")
            return
        changes["title"] = str(changes["title"]).strip()
        doc_id = self._selected_doc["id"]
        version = self._selected_doc["version"]
        run_async(
            lambda: update_document(doc_id, version, changes),
            on_success=self._on_details_saved,
            on_error=self._on_action_error,
        )

    def _on_details_saved(self, updated: Row) -> None:
        if self._selected_doc:
            self._selected_doc.update(updated)
        self._draft = {}
        self._reload_documents()
        QMessageBox.information(self, "Saved", "Document details saved.")

    def _on_action_error(self, exc: Exception) -> None:
        self.set_writable(True)
        if isinstance(exc, (ConflictError, ValidationError)):
            show_error(self, str(exc))
        elif isinstance(exc, OfflineError):
            show_error(self, "Offline — cannot complete action.")
        else:
            show_error(self, f"Action failed: {exc}")

    def set_writable(self, writable: bool) -> None:
        """Enable/disable write controls based on sync state."""
        self._writable = writable
        if self._add_btn is not None:
            self._add_btn.setEnabled(writable)


# ===== SECTION: TopBar =====

def _on_color(accent: str) -> str:
    """Return a readable foreground colour for *accent* as a background."""
    hexval = accent.lstrip("#")
    try:
        r, g, b = (int(hexval[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return "#ffffff"
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return "#1a1a1a" if luminance > 0.55 else "#ffffff"


class TopBar(QFrame):
    """The Top Bar of 06: name, Project, Phase, tabs A–G, [AI], sync, [Dark].

    The Top Bar is the only project/phase selector. Emits the current
    selection; the MainWindow owns the shared AppState.
    """

    project_chosen = Signal(object)      # project id (str) or None
    phase_chosen = Signal(object)        # phase id (str) or None
    screen_chosen = Signal(str)          # letter A..G
    new_project_chosen = Signal()
    archived_chosen = Signal()
    theme_toggled = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("topbar")
        self._tabs: dict[str, QPushButton] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(8)

        app_name = QLabel(APP_NAME)
        app_name.setObjectName("appName")
        app_name.setFont(QFont("", 14, QFont.Weight.Bold))
        layout.addWidget(app_name)
        layout.addStretch()

        layout.addWidget(QLabel("Project:"))
        self._project_combo = QComboBox()
        self._project_combo.setMinimumWidth(170)
        self._project_combo.setToolTip("Current project")
        self._project_combo.currentIndexChanged.connect(self._on_project_index)
        layout.addWidget(self._project_combo)

        self._new_project_btn = QPushButton("+")
        self._new_project_btn.setToolTip("New project...")
        self._new_project_btn.setFixedWidth(28)
        self._new_project_btn.setFixedHeight(28)
        self._new_project_btn.clicked.connect(self.new_project_chosen.emit)
        layout.addWidget(self._new_project_btn)

        layout.addWidget(QLabel("Phase:"))
        self._phase_combo = QComboBox()
        self._phase_combo.setMinimumWidth(110)
        self._phase_combo.setToolTip("Current phase of this project")
        self._phase_combo.currentIndexChanged.connect(self._on_phase_index)
        layout.addWidget(self._phase_combo)
        layout.addStretch()

        for letter in ["A", "B", "C", "D", "E", "F", "G"]:
            btn = QPushButton(letter)
            btn.setCheckable(True)
            btn.setToolTip(f"{letter} — {screen_label(letter).replace('&&', '&')}")
            btn.clicked.connect(
                lambda _=False, l=letter: self.screen_chosen.emit(l)
            )
            layout.addWidget(btn)
            self._tabs[letter] = btn

        ai_btn = QPushButton("AI")
        ai_btn.setEnabled(False)
        ai_btn.setToolTip("Later")
        layout.addWidget(ai_btn)

        self._sync_label = QLabel("SYNCED")
        self._sync_label.setObjectName("syncLabel")
        layout.addWidget(self._sync_label)

        self._theme_btn = QPushButton("Dark")
        self._theme_btn.setCheckable(True)
        self._theme_btn.setToolTip("Switch between light and dark theme")
        self._theme_btn.clicked.connect(self.theme_toggled.emit)
        layout.addWidget(self._theme_btn)

        self.set_current_screen("A")

    # --- project combo ---

    def set_projects(self, projects: Rows, selected_id: str | None) -> None:
        """Rebuild the project combo (signals blocked) and emit the result."""
        self._project_combo.blockSignals(True)
        self._project_combo.clear()
        for proj in projects:
            self._project_combo.addItem(proj["name"], proj["id"])
        self._project_combo.addItem(NEW_PROJECT_ENTRY, NEW_PROJECT_ENTRY)
        self._project_combo.addItem(ARCHIVED_ENTRY, ARCHIVED_ENTRY)
        index = -1
        if selected_id is not None:
            for i in range(self._project_combo.count()):
                if self._project_combo.itemData(i) == selected_id:
                    index = i
                    break
        if index < 0:
            if projects:
                index = 0
            else:
                for i in range(self._project_combo.count()):
                    if self._project_combo.itemData(i) == NEW_PROJECT_ENTRY:
                        index = i
                        break
        self._project_combo.setCurrentIndex(index)
        self._project_combo.blockSignals(False)
        self._emit_project_selection()

    def select_project_id(self, project_id: str | None, silent: bool = False) -> None:
        """Select a project entry by id; *silent* suppresses the signal."""
        index = -1
        if project_id is not None:
            for i in range(self._project_combo.count()):
                if self._project_combo.itemData(i) == project_id:
                    index = i
                    break
        if silent:
            self._project_combo.blockSignals(True)
            self._project_combo.setCurrentIndex(index)
            self._project_combo.blockSignals(False)
        else:
            self._project_combo.setCurrentIndex(index)

    def current_project_id(self) -> str | None:
        return self._project_combo.currentData()

    def _on_project_index(self, index: int) -> None:
        data = self._project_combo.itemData(index)
        if data == NEW_PROJECT_ENTRY:
            self.new_project_chosen.emit()
        elif data == ARCHIVED_ENTRY:
            self.archived_chosen.emit()
        else:
            self.project_chosen.emit(data)

    def _emit_project_selection(self) -> None:
        data = self._project_combo.currentData()
        if data == NEW_PROJECT_ENTRY:
            self.new_project_chosen.emit()
        elif data == ARCHIVED_ENTRY:
            self.archived_chosen.emit()
        else:
            self.project_chosen.emit(data)

    # --- phase combo ---

    def set_phases(self, phases: Rows, selected_id: str | None) -> None:
        """Rebuild the phase combo (signals blocked) and emit the result."""
        self._phase_combo.blockSignals(True)
        self._phase_combo.clear()
        self._phase_combo.addItem("--", None)
        for ph in phases:
            label = format_phase_label(ph.get("phase_no", 0))
            title = (ph.get("title") or "").strip()
            text = f"{label} {title}".strip()
            self._phase_combo.addItem(text, ph["id"])
        index = 0
        if selected_id is not None:
            for i in range(self._phase_combo.count()):
                if self._phase_combo.itemData(i) == selected_id:
                    index = i
                    break
        self._phase_combo.setCurrentIndex(index)
        self._phase_combo.blockSignals(False)
        self.phase_chosen.emit(self._phase_combo.currentData())

    def select_phase_id(self, phase_id: str | None, silent: bool = False) -> None:
        """Select a phase entry by id; *silent* suppresses the signal."""
        index = -1
        if phase_id is not None:
            for i in range(self._phase_combo.count()):
                if self._phase_combo.itemData(i) == phase_id:
                    index = i
                    break
        elif self._phase_combo.count():
            index = 0
        if silent:
            self._phase_combo.blockSignals(True)
            self._phase_combo.setCurrentIndex(index)
            self._phase_combo.blockSignals(False)
        else:
            self._phase_combo.setCurrentIndex(index)

    def current_phase_id(self) -> str | None:
        return self._phase_combo.currentData()

    def _on_phase_index(self, index: int) -> None:
        self.phase_chosen.emit(self._phase_combo.itemData(index))

    # --- tabs / sync / theme ---

    def set_current_screen(self, letter: str) -> None:
        """Mark the active tab in the screen accent colour."""
        for l, btn in self._tabs.items():
            active = l == letter
            btn.setChecked(active)
            if active:
                accent = SCREEN_ACCENTS.get(l, "#666666")
                fg = _on_color(accent)
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {accent}; color: {fg}; "
                    "font-weight: bold; padding: 4px 10px; "
                    "border: none; border-radius: 4px; }}"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { padding: 4px 10px; border: none; "
                    "border-radius: 4px; background-color: transparent; }"
                )

    def set_sync_state(self, state: Any, message: str = "") -> None:
        """Show SYNCED / Saving / Offline / ERROR in the chip."""
        text = {
            "SYNCED": "SYNCED",
            "SAVING": "Saving",
            "OFFLINE": "Offline",
            "ERROR": "ERROR",
        }.get(getattr(state, "value", str(state)), str(state))
        color = {
            "SYNCED": "#0f766e",
            "SAVING": "#d97706",
            "OFFLINE": "#e11d48",
            "ERROR": "#e11d48",
        }.get(getattr(state, "value", ""), "#000000")
        self._sync_label.setText(text)
        self._sync_label.setStyleSheet(
            f"QLabel#syncLabel {{ color: {color}; font-weight: bold; background-color: transparent; }}"
        )
        self._sync_label.setToolTip(message or text)

    def sync_text(self) -> str:
        return self._sync_label.text()

    def set_theme(self, theme: str) -> None:
        """Reflect the active theme on the [Dark] toggle."""
        self._theme_btn.setChecked(theme == "dark")
        # Button shows the mode it switches TO
        self._theme_btn.setText("Light" if theme == "dark" else "Dark")

    def set_writable(self, writable: bool) -> None:
        """Enable/disable the New Project button based on sync state."""
        self._new_project_btn.setEnabled(writable)
        self._project_combo.setEnabled(writable)
