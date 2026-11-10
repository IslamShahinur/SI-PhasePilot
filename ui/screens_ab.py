"""

ui/screens_ab.py — Screens A (Project Foundation) and B (UI & Visual Documents).

Phase 4A: frames from migration/06; DocumentPanel lives in ui/panels.py

and is re-exported here for the frozen contract.

"""

from __future__ import annotations



from typing import Any



from PySide6.QtCore import Qt

from PySide6.QtWidgets import (

    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,

    QLineEdit, QFormLayout, QFileDialog, QGroupBox, QScrollArea,

    QFrame,

)



from data import (

    get_repo_path,

    set_repo_path,

    create_project,

    update_project,

    set_project_archived,

    ValidationError,

    ConflictError,

    OfflineError,

)

from services import (

    FOUNDATION_CATEGORIES,

    UI_CATEGORIES,

    SCREEN_ACCENTS,

    get_device_id,

    get_device_label,

    git_capture,

)

from ui.shell import (

    AppState,

    BaseScreen,

    get_main_window,

    run_async,

    show_error,

    confirm,

    load_local_settings,

    save_local_settings,

)

from ui.panels import DocumentPanel
from ui.secure_delete import request_secure_delete



Row = dict[str, Any]



__all__ = ["DocumentPanel", "ScreenA", "ScreenB"]





# ===== SECTION: ScreenA — Project Foundation =====



class ScreenA(BaseScreen):

    """Screen A: Project Foundation (frame A of migration/06)."""



    screen_id = "A"

    title = "Project Foundation"

    accent = SCREEN_ACCENTS["A"]



    def __init__(self, state: AppState | None = None):

        super().__init__(state)

        self._project: Row | None = None

        self._repo_path_row: Row | None = None

        self._branch_text = "—"

        self._checkpoint_text = "—"

        self._build_ui()



    def _build_ui(self) -> None:

        outer = QVBoxLayout(self)

        outer.setContentsMargins(0, 0, 0, 0)



        scroll = QScrollArea()

        scroll.setWidgetResizable(True)

        scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll.setHorizontalScrollBarPolicy(

            Qt.ScrollBarPolicy.ScrollBarAlwaysOff

        )

        outer.addWidget(scroll)



        content = QWidget()

        layout = QVBoxLayout(content)

        layout.setContentsMargins(12, 12, 12, 12)

        layout.setSpacing(12)



        header = QLabel("A  PROJECT FOUNDATION")

        header.setObjectName("screenTitle")

        header.setStyleSheet(

            f"font-size: 14pt; font-weight: bold; color: {self.accent}; background-color: transparent;"

        )

        layout.addWidget(header)



        form_widget = QWidget()

        form = QFormLayout(form_widget)
        form.setContentsMargins(0, 0, 0, 0)

        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        form.setVerticalSpacing(8)



        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Project name")
        self._name_edit.setReadOnly(True)
        form.addRow("Project :", self._name_edit)



        repo_row = QHBoxLayout()

        self._repo_path_edit = QLineEdit()

        self._repo_path_edit.setPlaceholderText("Repository path on this PC")

        self._repo_path_edit.setReadOnly(True)

        repo_row.addWidget(self._repo_path_edit, 1)

        self._browse_btn = QPushButton("Browse")

        self._browse_btn.clicked.connect(self.browse_repo)

        repo_row.addWidget(self._browse_btn)



        self._refresh_git_btn = QPushButton("Refresh")

        self._refresh_git_btn.clicked.connect(self._on_refresh_git)

        repo_row.addWidget(self._refresh_git_btn)

        form.addRow("Repo    :", repo_row)



        info_row = QHBoxLayout()

        self._branch_label = QLabel("—")

        self._branch_label.setTextInteractionFlags(

            Qt.TextInteractionFlag.TextSelectableByMouse

        )

        info_row.addWidget(QLabel("Branch  :"))

        info_row.addWidget(self._branch_label, 1)

        self._checkpoint_label = QLabel("—")

        self._checkpoint_label.setTextInteractionFlags(

            Qt.TextInteractionFlag.TextSelectableByMouse

        )

        info_row.addWidget(QLabel("Checkpoint :"))

        info_row.addWidget(self._checkpoint_label, 1)

        form.addRow(info_row)



        self._goal_edit = QLineEdit()

        self._goal_edit.setPlaceholderText("Project goal")

        form.addRow("Goal    :", self._goal_edit)



        layout.addWidget(form_widget)



        self._doc_panel = DocumentPanel(

            area="foundation",

            categories=FOUNDATION_CATEGORIES,

            accent=self.accent,

        )

        layout.addWidget(self._doc_panel, 1)



        save_row = QHBoxLayout()

        save_row.addStretch()

        self._save_btn = QPushButton("Save")

        self._save_btn.clicked.connect(self.save_project)

        save_row.addWidget(self._save_btn)

        layout.addLayout(save_row)



        danger = QGroupBox("Danger Zone")

        danger.setObjectName("dangerZone")

        danger.setStyleSheet(

            "QGroupBox { margin-top: 8px; padding-top: 12px; background-color: transparent; } "

            "QGroupBox::title { subcontrol-origin: margin; left: 8px; }"

        )

        danger_layout = QHBoxLayout(danger)

        self._archive_btn = QPushButton("Archive this project...")

        self._archive_btn.setObjectName("dangerButton")

        self._archive_btn.clicked.connect(self.archive_project)

        danger_layout.addWidget(self._archive_btn)

        self._delete_btn = QPushButton("Delete project...")

        self._delete_btn.setObjectName("dangerButton")

        self._delete_btn.clicked.connect(self.delete_project)

        danger_layout.addWidget(self._delete_btn)

        danger_layout.addStretch()

        layout.addWidget(danger)



        scroll.setWidget(content)



        self.set_writable(False)



    # --- contract methods ---



    def load_project_form(self) -> None:

        """Reload the project list and fill the form for the current project."""

        mw = get_main_window()

        if mw is not None and mw.state.project is not None:

            self._apply_project(mw.state.project)

        elif self.state is not None and self.state.project is not None:

            self._apply_project(self.state.project)

        else:

            self._apply_project(None)



    def new_project(self) -> None:

        """Clear the form for a new project (Top Bar '+ New project...')."""

        self._project = None

        self._name_edit.clear()

        self._goal_edit.clear()

        self._repo_path_edit.clear()

        self._repo_path_row = None

        self._branch_text = "—"

        self._branch_label.setText("—")

        self._checkpoint_text = "—"

        self._checkpoint_label.setText("—")

        self._refresh_git_btn.setEnabled(False)

        self._doc_panel.load(None)

        self._name_edit.setFocus()



    def save_project(self) -> None:

        """Create or update the project; also persist this PC's repo path."""

        name = self._name_edit.text().strip()

        if not name:

            show_error(self, "Project name cannot be empty.")

            return

        goal = self._goal_edit.text().strip()

        project = self._project

        local_path = self._repo_path_edit.text().strip()

        if project is None:

            self.set_writable(False)



            def _create() -> Row:

                created = create_project(name, goal)

                if local_path:

                    set_repo_path(

                        created["id"], get_device_id(),

                        get_device_label(), local_path, None,

                    )

                return created



            run_async(

                _create,

                on_success=self._on_project_saved,

                on_error=self._on_action_error,

            )

            return

        self.set_writable(False)

        project_id = project["id"]

        changes = {"name": name, "description": goal}

        existing = self._repo_path_row

        expected = existing.get("version") if existing else None



        def _update() -> Row:

            updated = update_project(project_id, project["version"], changes)

            if local_path:

                set_repo_path(

                    project_id, get_device_id(),

                    get_device_label(), local_path, expected,

                )

            return updated



        run_async(

            _update,

            on_success=self._on_project_saved,

            on_error=self._on_action_error,

        )



    def archive_project(self) -> None:

        """Archive the current project after confirmation."""

        project = self._project

        if project is None:

            show_error(self, "Select a project first.")

            return

        if not confirm(self, f"Archive project '{project['name']}'?"):

            return

        self.set_writable(False)

        run_async(

            lambda: set_project_archived(

                project["id"], project["version"], True

            ),

            on_success=self._on_archived,

            on_error=self._on_action_error,

        )

    def delete_project(self) -> None:
        """Permanently delete the selected project after impact confirmation."""
        project = self._project
        if project is None:
            show_error(self, "Select a project first.")
            return
        request_secure_delete(
            self,
            "project",
            project["id"],
            protected=True,
            writable=self.state.sync.is_writable() if self.state else False,
            on_deleted=self._on_project_deleted,
        )



    def reopen_project(self) -> None:

        """Reopen an archived project (used when the form shows one)."""

        project = self._project

        if project is None:

            show_error(self, "Select a project first.")

            return

        self.set_writable(False)

        run_async(

            lambda: set_project_archived(

                project["id"], project["version"], False

            ),

            on_success=self._on_reopened,

            on_error=self._on_action_error,

        )



    def browse_repo(self) -> None:

        """Pick this PC's repository root folder."""

        path = QFileDialog.getExistingDirectory(self, "Select Repository Root")

        if path:

            self._repo_path_edit.setText(path)

            self._capture_git(path)



    def _on_refresh_git(self) -> None:

        local_path = self._repo_path_edit.text().strip()

        if local_path:

            self._capture_git(local_path)



    def save_repo_path(self) -> None:

        """Save this PC's repository path for the current project."""

        project = self._project

        if project is None:

            show_error(self, "Select a project first.")

            return

        local_path = self._repo_path_edit.text().strip()

        if not local_path:

            show_error(self, "Enter a repository path.")

            return

        device_id = get_device_id()

        device_label = get_device_label()

        existing = self._repo_path_row

        expected = existing.get("version") if existing else None

        self.set_writable(False)

        run_async(

            lambda: set_repo_path(

                project["id"], device_id, device_label, local_path, expected

            ),

            on_success=self._on_repo_path_saved,

            on_error=self._on_action_error,

        )



    # --- BaseScreen hooks ---



    def on_show(self) -> None:

        self.load_project_form()



    def on_project_changed(self, project: Row | None) -> None:

        if project is None:

            self.new_project()

        else:

            self._apply_project(project)



    def on_phase_changed(self, phase: Row | None) -> None:

        pass



    def reload(self) -> None:

        self.load_project_form()



    # --- internals ---



    def _apply_project(self, project: Row | None) -> None:

        self._project = project

        if project is None:

            self.new_project()

            return

        self._name_edit.setText(project.get("name", ""))

        self._goal_edit.setText(project.get("description", ""))

        self._doc_panel.load(project)

        self._refresh_git_btn.setEnabled(True)

        self._branch_label.setText("â€¦")

        self._checkpoint_label.setText("â€¦")

        project_id = project["id"]



        def _load_meta() -> Row | None:

            return get_repo_path(project_id, get_device_id())



        run_async(

            _load_meta,

            on_success=lambda row, pid=project_id: self._on_meta_loaded(row, pid),

            on_error=lambda exc: self._on_meta_error(exc),

        )



    def _on_meta_loaded(self, row: Row | None, project_id: str) -> None:

        if self._project is None or self._project["id"] != project_id:

            return  # stale selection

        self._repo_path_row = row

        self._repo_path_edit.setText(

            (row or {}).get("local_path", "") if row else ""

        )

        self._checkpoint_text = "—"

        self._checkpoint_label.setText("—")

        self._checkpoint_label.setToolTip("")

        local_path = self._repo_path_edit.text().strip()

        if local_path:

            self._branch_label.setText("…")

            self._capture_git(local_path)

        else:

            self._branch_label.setText("—")



    def _on_meta_error(self, exc: Exception) -> None:

        self._branch_label.setText("—")

        self._checkpoint_label.setText("—")

        if isinstance(exc, OfflineError):

            return  # keep quiet; sync chip already shows Offline

        show_error(self, f"Failed to load project details: {exc}")



    def _capture_git(self, local_path: str) -> None:

        """Read the branch and the last commit hash from the repo (background thread)."""

        self._branch_label.setText("…")

        self._checkpoint_text = "—"

        self._checkpoint_label.setText("—")

        self._checkpoint_label.setToolTip("")

        run_async(

            lambda: git_capture(local_path),

            on_success=lambda info, path=local_path: self._on_git_captured(info, path),

            on_error=lambda exc, path=local_path: self._on_git_error(exc, path),

        )



    def _on_git_captured(self, info: Any, local_path: str) -> None:

        if self._project is None:

            return

        if self._repo_path_edit.text().strip() != local_path:

            return  # the repo path changed while we were reading

        branch = getattr(info, "branch", None) or ""

        head = getattr(info, "head", None) or ""

        error = getattr(info, "error", None)

        if error and not head:

            self._branch_label.setText("—")

            self._checkpoint_text = "—"

        else:

            self._branch_label.setText(branch or "—")

            if head:

                self._checkpoint_text = head[:7]

                self._checkpoint_label.setToolTip(head)

            else:

                self._checkpoint_text = "—"

        self._checkpoint_label.setText(self._checkpoint_text)



    def _on_git_error(self, exc: Exception, local_path: str) -> None:

        if self._project is None:

            return

        if self._repo_path_edit.text().strip() != local_path:

            return

        self._branch_label.setText("—")

        self._checkpoint_text = "—"

        self._checkpoint_label.setText("—")

        self._checkpoint_label.setToolTip("")



    def _on_project_saved(self, project: Row) -> None:

        self.set_writable(True)

        settings = load_local_settings()

        settings["last_project_id"] = project["id"]

        save_local_settings(settings)

        mw = get_main_window()

        if mw is not None:

            mw.state.project = project

            mw.refresh_all()

        else:

            self._apply_project(project)



    def _on_archived(self, _project: Row) -> None:

        self.set_writable(True)

        settings = load_local_settings()

        settings["last_project_id"] = None

        save_local_settings(settings)

        mw = get_main_window()

        if mw is not None:

            mw.state.project = None

            mw.refresh_all()

        else:

            self.new_project()

    def _on_project_deleted(self, _result: dict[str, Any]) -> None:
        settings = load_local_settings()
        settings["last_project_id"] = None
        save_local_settings(settings)
        mw = get_main_window()
        if mw is not None:
            mw._enter_new_project_mode()
            mw.refresh_all()
        else:
            self.new_project()



    def _on_reopened(self, project: Row) -> None:

        self.set_writable(True)

        settings = load_local_settings()

        settings["last_project_id"] = project["id"]

        save_local_settings(settings)

        mw = get_main_window()

        if mw is not None:

            mw.refresh_all()

        else:

            self._apply_project(project)



    def _on_repo_path_saved(self, row: Row) -> None:

        self.set_writable(True)

        self._repo_path_row = row

        local_path = row.get("local_path", "")

        if local_path:

            self._capture_git(local_path)



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

        self._save_btn.setEnabled(writable)

        self._archive_btn.setEnabled(

            writable and self._project is not None

        )

        self._delete_btn.setEnabled(writable and self._project is not None)

        self._browse_btn.setEnabled(writable)

        self._name_edit.setEnabled(writable)

        self._goal_edit.setEnabled(writable)

        self._doc_panel.set_writable(writable)





# ===== SECTION: ScreenB — UI & Visual Documents =====



class ScreenB(BaseScreen):

    """Screen B: UI & Visual Documents (frame B of migration/06)."""



    screen_id = "B"

    title = "UI & Visual Documents"

    accent = SCREEN_ACCENTS["B"]



    def __init__(self, state: AppState | None = None):

        super().__init__(state)

        self._build_ui()



    def _build_ui(self) -> None:

        layout = QVBoxLayout(self)

        layout.setContentsMargins(12, 12, 12, 12)

        layout.setSpacing(12)



        header = QHBoxLayout()

        title = QLabel("B  UI & VISUAL DOCUMENTS")

        title.setObjectName("screenTitle")

        title.setStyleSheet(

            f"font-size: 14pt; font-weight: bold; color: {self.accent}; background-color: transparent;"

        )

        header.addWidget(title)

        header.addStretch()

        self._add_btn = QPushButton("+ Add document")

        self._add_btn.clicked.connect(self._add_document)

        header.addWidget(self._add_btn)

        layout.addLayout(header)



        self._doc_panel = DocumentPanel(

            area="ui_visual",

            categories=UI_CATEGORIES,

            accent=self.accent,

        )

        layout.addWidget(self._doc_panel, 1)



        self.set_writable(False)



    def _add_document(self) -> None:

        self._doc_panel.add_document()



    def on_show(self) -> None:

        if self.state and self.state.project:

            self._doc_panel.load(self.state.project)



    def on_project_changed(self, project: Row | None) -> None:

        self._doc_panel.load(project)



    def on_phase_changed(self, phase: Row | None) -> None:

        pass



    def reload(self) -> None:

        if self.state and self.state.project:

            self._doc_panel.load(self.state.project)



    def set_writable(self, writable: bool) -> None:

        self._add_btn.setEnabled(writable)

        self._doc_panel.set_writable(writable)






















