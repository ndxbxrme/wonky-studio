from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from .database import connect


PROJECT_ARCHIVE_FORMAT_VERSION = 1

EXPORT_TABLE_ORDER = [
    "assets",
    "upload_batches",
    "uploaded_files",
    "audio_assets",
    "script_lines",
    "script_translations",
    "script_audio_candidates",
    "script_audio_candidate_viseme_events",
    "game_variables",
    "verbs",
    "characters",
    "character_images",
    "character_objects",
    "character_object_masks",
    "character_animations",
    "character_animation_frames",
    "conversations",
    "conversation_nodes",
    "conversation_choices",
    "scenes",
    "scene_images",
    "scene_objects",
    "object_animations",
    "object_animation_segments",
    "object_masks",
    "scene_mask_prompts",
    "mask_candidates",
    "overlay_scene_bindings",
    "global_settings",
    "scene_interactions",
]

TABLE_SELECTS = {
    "assets": "SELECT * FROM assets WHERE organization_id = ? ORDER BY id ASC",
    "upload_batches": "SELECT * FROM upload_batches WHERE organization_id = ? ORDER BY id ASC",
    "uploaded_files": "SELECT * FROM uploaded_files WHERE organization_id = ? ORDER BY id ASC",
    "audio_assets": "SELECT * FROM audio_assets WHERE organization_id = ? ORDER BY id ASC",
    "script_lines": "SELECT * FROM script_lines WHERE organization_id = ? ORDER BY id ASC",
    "script_translations": """
        SELECT st.*
        FROM script_translations st
        JOIN script_lines sl ON sl.id = st.script_line_id
        WHERE sl.organization_id = ?
        ORDER BY st.id ASC
    """,
    "script_audio_candidates": """
        SELECT sac.*
        FROM script_audio_candidates sac
        JOIN script_lines sl ON sl.id = sac.script_line_id
        WHERE sl.organization_id = ?
        ORDER BY sac.id ASC
    """,
    "script_audio_candidate_viseme_events": """
        SELECT save.*
        FROM script_audio_candidate_viseme_events save
        JOIN script_audio_candidates sac ON sac.id = save.script_audio_candidate_id
        JOIN script_lines sl ON sl.id = sac.script_line_id
        WHERE sl.organization_id = ?
        ORDER BY save.id ASC
    """,
    "game_variables": "SELECT * FROM game_variables WHERE organization_id = ? ORDER BY id ASC",
    "verbs": "SELECT * FROM verbs WHERE organization_id = ? ORDER BY id ASC",
    "characters": "SELECT * FROM characters WHERE organization_id = ? ORDER BY id ASC",
    "character_images": """
        SELECT ci.*
        FROM character_images ci
        JOIN characters c ON c.id = ci.character_id
        WHERE c.organization_id = ?
        ORDER BY ci.id ASC
    """,
    "character_objects": """
        SELECT co.*
        FROM character_objects co
        JOIN characters c ON c.id = co.character_id
        WHERE c.organization_id = ?
        ORDER BY co.id ASC
    """,
    "character_object_masks": """
        SELECT com.*
        FROM character_object_masks com
        JOIN character_objects co ON co.id = com.character_object_id
        JOIN characters c ON c.id = co.character_id
        WHERE c.organization_id = ?
        ORDER BY com.id ASC
    """,
    "character_animations": """
        SELECT ca.*
        FROM character_animations ca
        JOIN characters c ON c.id = ca.character_id
        WHERE c.organization_id = ?
        ORDER BY ca.id ASC
    """,
    "character_animation_frames": """
        SELECT caf.*
        FROM character_animation_frames caf
        JOIN character_animations ca ON ca.id = caf.character_animation_id
        JOIN characters c ON c.id = ca.character_id
        WHERE c.organization_id = ?
        ORDER BY caf.id ASC
    """,
    "conversations": "SELECT * FROM conversations WHERE organization_id = ? ORDER BY id ASC",
    "conversation_nodes": """
        SELECT cn.*
        FROM conversation_nodes cn
        JOIN conversations c ON c.id = cn.conversation_id
        WHERE c.organization_id = ?
        ORDER BY cn.id ASC
    """,
    "conversation_choices": """
        SELECT cc.*
        FROM conversation_choices cc
        JOIN conversation_nodes cn ON cn.id = cc.node_id
        JOIN conversations c ON c.id = cn.conversation_id
        WHERE c.organization_id = ?
        ORDER BY cc.id ASC
    """,
    "scenes": "SELECT * FROM scenes WHERE organization_id = ? ORDER BY id ASC",
    "scene_images": """
        SELECT si.*
        FROM scene_images si
        JOIN scenes s ON s.id = si.scene_id
        WHERE s.organization_id = ?
        ORDER BY si.id ASC
    """,
    "scene_objects": """
        SELECT so.*
        FROM scene_objects so
        JOIN scenes s ON s.id = so.scene_id
        WHERE s.organization_id = ?
        ORDER BY so.id ASC
    """,
    "object_animations": """
        SELECT oa.*
        FROM object_animations oa
        JOIN scene_objects so ON so.id = oa.scene_object_id
        JOIN scenes s ON s.id = so.scene_id
        WHERE s.organization_id = ?
        ORDER BY oa.id ASC
    """,
    "object_animation_segments": """
        SELECT oas.*
        FROM object_animation_segments oas
        JOIN object_animations oa ON oa.id = oas.object_animation_id
        JOIN scene_objects so ON so.id = oa.scene_object_id
        JOIN scenes s ON s.id = so.scene_id
        WHERE s.organization_id = ?
        ORDER BY oas.id ASC
    """,
    "object_masks": """
        SELECT om.*
        FROM object_masks om
        JOIN scene_objects so ON so.id = om.scene_object_id
        JOIN scenes s ON s.id = so.scene_id
        WHERE s.organization_id = ?
        ORDER BY om.id ASC
    """,
    "scene_mask_prompts": """
        SELECT smp.*
        FROM scene_mask_prompts smp
        JOIN scenes s ON s.id = smp.scene_id
        WHERE s.organization_id = ?
        ORDER BY smp.id ASC
    """,
    "mask_candidates": """
        SELECT mc.*
        FROM mask_candidates mc
        JOIN scene_mask_prompts smp ON smp.id = mc.scene_mask_prompt_id
        JOIN scenes s ON s.id = smp.scene_id
        WHERE s.organization_id = ?
        ORDER BY mc.id ASC
    """,
    "overlay_scene_bindings": "SELECT * FROM overlay_scene_bindings WHERE organization_id = ? ORDER BY id ASC",
    "global_settings": "SELECT * FROM global_settings WHERE organization_id = ? ORDER BY organization_id ASC",
    "scene_interactions": """
        SELECT si.*
        FROM scene_interactions si
        JOIN scenes s ON s.id = si.scene_id
        WHERE s.organization_id = ?
        ORDER BY si.id ASC
    """,
}

TABLE_USER_FIELDS = {
    "upload_batches": {"created_by_user_id"},
    "uploaded_files": {"uploaded_by_user_id"},
    "scenes": {"created_by_user_id"},
}

PATH_FIELDS = {
    "uploaded_files": {"relative_path"},
    "audio_assets": {"relative_path"},
    "script_audio_candidates": {"relative_path"},
    "character_images": {"relative_path"},
    "character_object_masks": {"relative_path", "soft_relative_path"},
    "scene_objects": {"inventory_image_relative_path"},
    "object_masks": {"relative_path", "soft_relative_path"},
    "mask_candidates": {"raw_relative_path", "soft_relative_path"},
    "global_settings": {
        "inventory_background_relative_path",
        "verb_tag_background_relative_path",
        "cursor_default_relative_path",
        "cursor_hover_interactive_relative_path",
        "cursor_busy_relative_path",
        "cursor_blocked_relative_path",
    },
}

WORKSPACE_TABLES = tuple(EXPORT_TABLE_ORDER)


def database_backup_path(storage_root: Path) -> Path:
    return storage_root.parent / "backup.json"


def workspace_is_empty(db_path: Path, organization_id: str) -> bool:
    with connect(db_path) as connection:
        checks = [
            ("scenes", "SELECT COUNT(*) AS count FROM scenes WHERE organization_id = ?"),
            ("uploaded_files", "SELECT COUNT(*) AS count FROM uploaded_files WHERE organization_id = ?"),
            ("script_lines", "SELECT COUNT(*) AS count FROM script_lines WHERE organization_id = ?"),
            ("audio_assets", "SELECT COUNT(*) AS count FROM audio_assets WHERE organization_id = ?"),
            ("game_variables", "SELECT COUNT(*) AS count FROM game_variables WHERE organization_id = ?"),
            ("verbs", "SELECT COUNT(*) AS count FROM verbs WHERE organization_id = ?"),
        ]
        for _table, sql in checks:
            count = int(connection.execute(sql, (organization_id,)).fetchone()["count"] or 0)
            if count > 0:
                return False
    return True


def export_project_archive(
    *,
    db_path: Path,
    storage_root: Path,
    organization_id: str,
    output_path: Path,
) -> dict[str, Any]:
    export_data = _export_project_tables(db_path=db_path, organization_id=organization_id)

    org_root = storage_root / organization_id
    file_count = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        project_json = {
            "format_version": PROJECT_ARCHIVE_FORMAT_VERSION,
            "organization_id": organization_id,
            "exported_at": datetime.now(UTC).isoformat(),
            "tables": export_data,
        }
        archive.writestr("project.json", json.dumps(project_json, ensure_ascii=True, separators=(",", ":")))
        manifest = {
            "format_version": PROJECT_ARCHIVE_FORMAT_VERSION,
            "organization_id": organization_id,
            "exported_at": project_json["exported_at"],
            "table_counts": {table: len(rows) for table, rows in export_data.items()},
            "file_count": 0,
        }
        if org_root.exists():
            for file_path in sorted(org_root.rglob("*")):
                if not file_path.is_file():
                    continue
                relative_file_path = file_path.relative_to(org_root)
                archive.write(file_path, arcname=str(Path("files") / relative_file_path))
                file_count += 1
        manifest["file_count"] = file_count
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=True, separators=(",", ":")))

    return {
        "format_version": PROJECT_ARCHIVE_FORMAT_VERSION,
        "file_count": file_count,
        "table_counts": {table: len(rows) for table, rows in export_data.items()},
    }


def export_project_database_json(
    *,
    db_path: Path,
    storage_root: Path,
    organization_id: str,
    output_path: Path | None = None,
) -> dict[str, Any]:
    export_data = _export_project_tables(db_path=db_path, organization_id=organization_id)
    target_path = output_path or database_backup_path(storage_root)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    project_json = {
        "format_version": PROJECT_ARCHIVE_FORMAT_VERSION,
        "organization_id": organization_id,
        "exported_at": datetime.now(UTC).isoformat(),
        "tables": export_data,
    }
    target_path.write_text(
        json.dumps(project_json, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "format_version": PROJECT_ARCHIVE_FORMAT_VERSION,
        "table_counts": {table: len(rows) for table, rows in export_data.items()},
        "output_path": str(target_path),
    }


def import_project_archive(
    *,
    db_path: Path,
    storage_root: Path,
    organization_id: str,
    imported_by_user_id: int,
    archive_path: Path,
) -> dict[str, Any]:
    with zipfile.ZipFile(archive_path) as archive:
        try:
            project_data = json.loads(archive.read("project.json").decode("utf-8"))
        except KeyError as exc:
            raise ValueError("Project archive is missing project.json") from exc
        org_root = storage_root / organization_id
        org_root.mkdir(parents=True, exist_ok=True)
        restored_file_count = 0
        for member in archive.infolist():
            filename = member.filename
            if not filename.startswith("files/") or filename.endswith("/"):
                continue
            relative_file_path = Path(filename).relative_to("files")
            destination = org_root / relative_file_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)
            restored_file_count += 1
    return _import_project_tables(
        db_path=db_path,
        organization_id=organization_id,
        imported_by_user_id=imported_by_user_id,
        project_data=project_data,
        restored_file_count=restored_file_count,
    )


def import_project_database_json(
    *,
    db_path: Path,
    storage_root: Path,
    organization_id: str,
    imported_by_user_id: int,
    input_path: Path | None = None,
) -> dict[str, Any]:
    source_path = input_path or database_backup_path(storage_root)
    if not source_path.exists():
        raise ValueError(f"Database backup file not found: {source_path}")
    try:
        project_data = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read database backup: {source_path}") from exc
    return _import_project_tables(
        db_path=db_path,
        organization_id=organization_id,
        imported_by_user_id=imported_by_user_id,
        project_data=project_data,
        restored_file_count=None,
    )


def _export_project_tables(
    *,
    db_path: Path,
    organization_id: str,
) -> dict[str, list[dict[str, Any]]]:
    export_data: dict[str, list[dict[str, Any]]] = {}
    with connect(db_path) as connection:
        for table in EXPORT_TABLE_ORDER:
            rows = connection.execute(TABLE_SELECTS[table], (organization_id,)).fetchall()
            export_data[table] = [dict(row) for row in rows]
    return export_data


def _import_project_tables(
    *,
    db_path: Path,
    organization_id: str,
    imported_by_user_id: int,
    project_data: dict[str, Any],
    restored_file_count: int | None,
) -> dict[str, Any]:
    format_version = int(project_data.get("format_version") or 0)
    if format_version != PROJECT_ARCHIVE_FORMAT_VERSION:
        raise ValueError(f"Unsupported project archive format version: {format_version}")
    source_organization_id = str(project_data.get("organization_id") or "").strip()
    if not source_organization_id:
        raise ValueError("Project archive is missing an organization_id")
    tables = project_data.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("Project archive tables payload is invalid")

    with connect(db_path) as connection:
        for table in EXPORT_TABLE_ORDER:
            rows = tables.get(table) or []
            if not isinstance(rows, list):
                raise ValueError(f"Project archive table {table} is invalid")
            if not rows:
                continue
            columns = [row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()]
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError(f"Project archive table {table} contains an invalid row")
                imported_row = {
                    key: _rewrite_import_value(
                        table=table,
                        key=key,
                        value=row.get(key),
                        source_organization_id=source_organization_id,
                        target_organization_id=organization_id,
                        imported_by_user_id=imported_by_user_id,
                    )
                    for key in columns
                    if key in row
                }
                if not imported_row:
                    continue
                ordered_columns = [column for column in columns if column in imported_row]
                placeholders = ",".join("?" for _ in ordered_columns)
                connection.execute(
                    f"INSERT INTO {table} ({', '.join(ordered_columns)}) VALUES ({placeholders})",
                    [imported_row[column] for column in ordered_columns],
                )

    return {
        "format_version": PROJECT_ARCHIVE_FORMAT_VERSION,
        "restored_file_count": restored_file_count,
        "table_counts": {
            table: len(tables.get(table) or [])
            for table in EXPORT_TABLE_ORDER
        },
    }


def _rewrite_import_value(
    *,
    table: str,
    key: str,
    value: Any,
    source_organization_id: str,
    target_organization_id: str,
    imported_by_user_id: int,
) -> Any:
    if key == "organization_id":
        return target_organization_id
    if key in TABLE_USER_FIELDS.get(table, set()):
        return imported_by_user_id
    if key in PATH_FIELDS.get(table, set()):
        return _rewrite_relative_path(value, source_organization_id, target_organization_id)
    return value


def _rewrite_relative_path(
    value: Any,
    source_organization_id: str,
    target_organization_id: str,
) -> Any:
    if not value:
        return value
    normalized = str(value).replace("\\", "/")
    prefix = f"{source_organization_id}/"
    if normalized == source_organization_id:
        return target_organization_id
    if normalized.startswith(prefix):
        return f"{target_organization_id}/{normalized[len(prefix):]}"
    return value
