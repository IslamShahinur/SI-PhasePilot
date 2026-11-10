"""Secure-delete previews and the ordered database/Storage deletion workflow."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

import data

Row = dict[str, Any]
Rows = list[Row]

_DELETE_KINDS = {"project", "phase", "command", "document", "baseline"}
_COMMAND_REPORT_KINDS = {
    "coder": ("coder_report",),
    "fix": ("coder_report",),
    "auditor": ("auditor_report", "claude_review"),
}
_logger = logging.getLogger(__name__)


# ===== SECTION: Delete preview =====

class SecureDeleteBlockedError(data.DataError):
    """The database refused deletion because a run is active."""


def _get_rows(
    table: str,
    columns: str,
    in_filters: dict[str, list[Any]] | None = None,
    **filters: Any,
) -> Rows:
    return data._secure_delete_select(table, columns, filters, in_filters)


def _require_target(kind: str, item_id: str) -> Row:
    if kind not in _DELETE_KINDS:
        raise data.DataError(f"Unsupported delete type: {kind}")
    table = {
        "project": "projects",
        "phase": "phases",
        "command": "commands",
        "document": "documents",
        "baseline": "baselines",
    }[kind]
    rows = _get_rows(table, "*", id=item_id)
    if not rows:
        raise data.DataError("The item no longer exists or is not accessible.")
    return rows[0]


def _command_name(row: Row) -> str:
    title = str(row.get("title") or "").strip()
    if title:
        return title
    body = str(row.get("body") or "").strip()
    return body.splitlines()[0][:100] if body else "Command"


def _append_group(
    impact: list[dict[str, Any]],
    label: str,
    rows: Rows,
    name_fn: Callable[[Row], Any],
) -> None:
    impact.append({
        "label": label,
        "names": [str(name_fn(row)) for row in rows],
    })


@data._wrap
def preview_secure_delete(kind: str, item_id: str) -> dict[str, Any]:
    """Return the exact visible impact and active-run state for a delete."""
    target = _require_target(kind, item_id)
    impact: list[dict[str, Any]] = []
    active_run = False

    if kind == "project":
        name = str(target.get("name") or "")
        project_id = item_id
        phases = _get_rows(
            "phases", "id,phase_no,title,status", project_id=project_id
        )
        commands = _get_rows(
            "commands", "id,phase_id,attempt_no,kind,title,body",
            project_id=project_id,
        )
        reports = _get_rows(
            "reports", "id,phase_id,attempt_no,kind,file_name",
            project_id=project_id,
        )
        audit_records = _get_rows(
            "audit_records", "id,phase_id,attempt_no", project_id=project_id
        )
        baselines = _get_rows(
            "baselines", "id,phase_id,attempt_no", project_id=project_id
        )
        documents = _get_rows(
            "documents", "id,title", project_id=project_id
        )
        versions = _get_rows(
            "document_versions", "id,file_name", project_id=project_id
        )
        work_items = _get_rows(
            "work_items", "id,title", project_id=project_id
        )
        registers = _get_rows(
            "register_items", "id,description,phase_id", project_id=project_id
        )
        repo_paths = _get_rows(
            "project_repo_paths", "id,device_label,device_id,local_path",
            project_id=project_id,
        )
        active_run = any(
            phase.get("status") == "coding_in_progress" for phase in phases
        )
        _append_group(
            impact, "Phases", phases,
            lambda row: f"Phase {row.get('phase_no')}: {row.get('title') or '(untitled)'}",
        )
        _append_group(impact, "Commands", commands, _command_name)
        _append_group(
            impact, "Coder/Audit reports", reports,
            lambda row: row.get("file_name") or str(row.get("kind") or "Report"),
        )
        _append_group(
            impact, "Audit records", audit_records,
            lambda row: f"Phase {row.get('phase_id')}, attempt {row.get('attempt_no')}",
        )
        _append_group(
            impact, "Approved baselines", baselines,
            lambda row: f"Phase {row.get('phase_id')}, attempt {row.get('attempt_no')}",
        )
        _append_group(impact, "Documents", documents, lambda row: row.get("title", ""))
        _append_group(impact, "Document files", versions, lambda row: row.get("file_name", ""))
        _append_group(impact, "Work items", work_items, lambda row: row.get("title", ""))
        _append_group(
            impact, "Register items", registers,
            lambda row: row.get("description", ""),
        )
        _append_group(
            impact, "Repository paths", repo_paths,
            lambda row: row.get("device_label") or row.get("device_id") or row.get("local_path", ""),
        )

    elif kind == "phase":
        name = (
            f"Phase {target.get('phase_no')}: "
            f"{target.get('title') or '(untitled)'}"
        )
        phase_id = item_id
        active_run = target.get("status") == "coding_in_progress"
        commands = _get_rows(
            "commands", "id,attempt_no,kind,title,body", phase_id=phase_id
        )
        reports = _get_rows(
            "reports", "id,attempt_no,kind,file_name", phase_id=phase_id
        )
        audit_records = _get_rows(
            "audit_records", "id,attempt_no", phase_id=phase_id
        )
        baselines = _get_rows(
            "baselines", "id,attempt_no", phase_id=phase_id
        )
        work_items = _get_rows("work_items", "id,title", phase_id=phase_id)
        registers = _get_rows(
            "register_items", "id,description", phase_id=phase_id
        )
        _append_group(impact, "Commands", commands, _command_name)
        _append_group(
            impact, "Coder/Audit reports", reports,
            lambda row: row.get("file_name") or str(row.get("kind") or "Report"),
        )
        _append_group(
            impact, "Audit records", audit_records,
            lambda row: f"Attempt {row.get('attempt_no')}",
        )
        _append_group(
            impact, "Approved baselines", baselines,
            lambda row: f"Attempt {row.get('attempt_no')}",
        )
        _append_group(impact, "Work items", work_items, lambda row: row.get("title", ""))
        _append_group(
            impact, "Register references", registers,
            lambda row: row.get("description", ""),
        )
        impact[-1]["retained"] = True
        impact[-1]["disposition"] = "retained; phase link cleared"

    elif kind == "command":
        name = _command_name(target)
        phase_id = str(target["phase_id"])
        phase = _get_rows("phases", "id,status", id=phase_id)
        active_run = bool(phase and phase[0].get("status") == "coding_in_progress")
        reports = []
        report_kinds = _COMMAND_REPORT_KINDS.get(str(target.get("kind")), ())
        if report_kinds:
            reports = _get_rows(
                "reports",
                "id,kind,file_name,attempt_no",
                in_filters={"kind": list(report_kinds)},
                phase_id=phase_id,
                attempt_no=target["attempt_no"],
            )
        _append_group(
            impact, "Run reports", reports,
            lambda row: row.get("file_name") or str(row.get("kind") or "Report"),
        )
        if target.get("kind") == "auditor":
            audits = _get_rows(
                "audit_records",
                "id,attempt_no",
                phase_id=phase_id,
                attempt_no=target["attempt_no"],
            )
            _append_group(
                impact, "Audit decisions", audits,
                lambda row: f"Attempt {row.get('attempt_no')}",
            )

    elif kind == "document":
        name = str(target.get("title") or "")
        versions = _get_rows(
            "document_versions", "id,file_name,storage_path", document_id=item_id
        )
        _append_group(
            impact, "Document files", versions,
            lambda row: row.get("file_name", ""),
        )
        file_names = {
            str(target.get("title") or ""),
            *(str(row.get("file_name") or "") for row in versions),
        }
        baselines = _get_rows(
            "baselines", "id,phase_id,attempt_no,document_hashes",
            project_id=str(target["project_id"]),
        )
        refs = []
        for baseline in baselines:
            hashes = baseline.get("document_hashes") or {}
            for file_name in file_names:
                if file_name and file_name in hashes:
                    refs.append({
                        "phase_id": baseline.get("phase_id"),
                        "attempt_no": baseline.get("attempt_no"),
                        "file_name": file_name,
                    })
        _append_group(
            impact, "Baseline references (will break)", refs,
            lambda row: (
                f"{row.get('file_name')} — phase {row.get('phase_id')}, "
                f"attempt {row.get('attempt_no')}"
            ),
        )
        impact[-1]["retained"] = True
        impact[-1]["disposition"] = "will break; retained"

    else:
        phase = _get_rows(
            "phases", "id,phase_no,status", id=str(target["phase_id"])
        )
        phase_name = str(target["phase_id"])
        if phase:
            phase_name = f"Phase {phase[0].get('phase_no')}"
            active_run = phase[0].get("status") == "coding_in_progress"
        name = (
            f"Approved Baseline — {phase_name}, "
            f"attempt {target.get('attempt_no')}"
        )

    return {
        "kind": kind,
        "id": item_id,
        "name": name,
        "impact": impact,
        "active_run": active_run,
    }


def _storage_paths(kind: str, item_id: str) -> list[str]:
    """Read Storage paths before any database rows are deleted."""
    target = _require_target(kind, item_id)
    paths: list[str] = []
    if kind == "project":
        tables = (
            ("document_versions", "project_id"),
            ("reports", "project_id"),
        )
        for table, key in tables:
            paths.extend(
                row["storage_path"]
                for row in _get_rows(table, "storage_path", **{key: item_id})
                if row.get("storage_path")
            )
    elif kind == "phase":
        paths.extend(
            row["storage_path"]
            for row in _get_rows(
                "reports", "storage_path", phase_id=item_id
            )
            if row.get("storage_path")
        )
    elif kind == "command":
        report_kinds = _COMMAND_REPORT_KINDS.get(str(target.get("kind")), ())
        if report_kinds:
            rows = _get_rows(
                "reports",
                "storage_path",
                in_filters={"kind": list(report_kinds)},
                phase_id=target["phase_id"],
                attempt_no=target["attempt_no"],
            )
            paths.extend(
                row["storage_path"]
                for row in rows
                if row.get("storage_path")
            )
    elif kind == "document":
        paths.extend(
            row["storage_path"]
            for row in _get_rows(
                "document_versions", "storage_path", document_id=item_id
            )
            if row.get("storage_path")
        )
    return list(dict.fromkeys(paths))


# ===== SECTION: Delete execution =====

@data._wrap
def secure_delete(kind: str, item_id: str) -> dict[str, Any]:
    """Delete database rows atomically, then remove Storage files best-effort."""
    paths = _storage_paths(kind, item_id)
    response = data._secure_delete_rpc(kind, item_id)

    result = response.data
    if isinstance(result, list):
        result = result[0] if result else {}
    if not isinstance(result, dict):
        raise data.DataError("Secure delete returned an invalid response.")
    if result.get("blocked"):
        raise SecureDeleteBlockedError(
            "A Coder or Auditor run is active on this item. Stop the run first."
        )
    if not result.get("deleted"):
        raise data.DataError("The item no longer exists or is not accessible.")
    returned_paths = result.get("storage_paths")
    if not isinstance(returned_paths, list) or not all(
        isinstance(path, str) for path in returned_paths
    ):
        for path in paths:
            _logger.error(
                "ORPHAN FILE %s: database delete returned an invalid cleanup list",
                path,
            )
        raise data.DataError(
            "The database deleted the records but returned no valid Storage "
            "path list for cleanup; any known paths were logged as ORPHAN FILE."
        )
    paths = list(dict.fromkeys(paths + returned_paths))

    orphan_files: list[str] = []
    for path in paths:
        try:
            data._secure_delete_remove_storage(path)
        except Exception as exc:
            _logger.error("ORPHAN FILE %s: %s", path, exc)
            orphan_files.append(path)

    deleted_name = str(result.get("name") or kind)
    _logger.info(
        "Secure delete completed: type=%s name=%s time=%s",
        kind,
        deleted_name,
        datetime.now(timezone.utc).isoformat(),
    )
    return {
        "deleted": True,
        "kind": kind,
        "name": deleted_name,
        "orphan_files": orphan_files,
    }
