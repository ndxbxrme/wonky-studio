from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

from .security import hash_token, make_token, now_utc, utc_iso


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "wonky-studio.sqlite3"

SYSTEM_GAME_VARIABLES: tuple[dict[str, Any], ...] = (
    {
        "name": "primary_language",
        "value_type": "string",
        "default_value": "en",
        "description": "Built-in runtime variable controlling the primary spoken language.",
    },
    {
        "name": "secondary_language",
        "value_type": "string",
        "default_value": "fr",
        "description": "Built-in runtime variable controlling the secondary spoken language.",
    },
    {
        "name": "translation_mode",
        "value_type": "string",
        "default_value": "sequential",
        "description": "Built-in runtime variable controlling subtitle/audio translation playback mode.",
    },
    {
        "name": "master_volume",
        "value_type": "number",
        "default_value": 5,
        "description": "Built-in runtime variable controlling overall preview volume.",
    },
    {
        "name": "narrator_volume",
        "value_type": "number",
        "default_value": 5,
        "description": "Built-in runtime variable controlling narrator and spoken-line volume.",
    },
    {
        "name": "music_volume",
        "value_type": "number",
        "default_value": 5,
        "description": "Built-in runtime variable controlling background music volume.",
    },
    {
        "name": "sfx_volume",
        "value_type": "number",
        "default_value": 5,
        "description": "Built-in runtime variable controlling sound-effect volume.",
    },
)

CURSOR_STATE_KEYS: tuple[str, ...] = (
    "default",
    "hover_interactive",
    "busy",
    "blocked",
)

DEFAULT_CURSOR_STATES: dict[str, dict[str, Any]] = {
    state_key: {
        "relative_path": None,
        "hotspot_x": 0,
        "hotspot_y": 0,
    }
    for state_key in CURSOR_STATE_KEYS
}


def get_database_path() -> Path:
    configured_path = os.environ.get("WONKY_STUDIO_DB_PATH")
    return Path(configured_path) if configured_path else DEFAULT_DB_PATH


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _get_or_create_default_project_id(connection: sqlite3.Connection, organization_id: str) -> int:
    existing = connection.execute(
        """
        SELECT id
        FROM projects
        WHERE organization_id = ?
        ORDER BY sort_order ASC, id ASC
        LIMIT 1
        """,
        (organization_id,),
    ).fetchone()
    if existing is not None:
        return int(existing["id"])
    cursor = connection.execute(
        """
        INSERT INTO projects (organization_id, name, sort_order)
        VALUES (?, ?, 0)
        """,
        (organization_id, "Main project"),
    )
    return int(cursor.lastrowid)


def _table_column_names(connection: sqlite3.Connection, table_name: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [str(row["name"]) for row in rows]


def _has_unique_constraint(connection: sqlite3.Connection, table_name: str, columns: tuple[str, ...]) -> bool:
    table_info_rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    primary_key_columns = [
        str(row["name"])
        for row in sorted(
            (row for row in table_info_rows if int(row["pk"] or 0) > 0),
            key=lambda row: int(row["pk"]),
        )
    ]
    if primary_key_columns == list(columns):
        return True

    index_rows = connection.execute(f"PRAGMA index_list({table_name})").fetchall()
    for index_row in index_rows:
        if not int(index_row["unique"] or 0):
            continue
        index_name = str(index_row["name"])
        index_columns = [
            str(column_row["name"])
            for column_row in connection.execute(f"PRAGMA index_info({index_name})").fetchall()
        ]
        if index_columns == list(columns):
            return True
    return False


def _rebuild_table(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    create_sql: str,
    insert_sql: str,
) -> None:
    temp_table_name = f"{table_name}__project_migration_old"
    existing_tables = {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if temp_table_name in existing_tables:
        connection.execute(f"DROP TABLE {temp_table_name}")

    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute(f"ALTER TABLE {table_name} RENAME TO {temp_table_name}")
        connection.execute(create_sql)
        connection.execute(insert_sql.format(old_table=temp_table_name))
        connection.execute(f"DROP TABLE {temp_table_name}")
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def _ensure_project_scoped_uniqueness(connection: sqlite3.Connection) -> None:
    if not _has_unique_constraint(connection, "global_settings", ("organization_id", "project_id")):
        _rebuild_table(
            connection,
            table_name="global_settings",
            create_sql="""
            CREATE TABLE global_settings (
                organization_id TEXT NOT NULL,
                project_id INTEGER NOT NULL,
                overlay_open_duration_seconds REAL NOT NULL DEFAULT 0.22,
                overlay_close_duration_seconds REAL NOT NULL DEFAULT 0.18,
                overlay_fade_color TEXT NOT NULL DEFAULT '#000000',
                overlay_affect_audio INTEGER NOT NULL DEFAULT 0,
                start_scene_id INTEGER,
                inventory_key_code TEXT NOT NULL DEFAULT 'KeyI',
                verb_menu_timeout_seconds REAL NOT NULL DEFAULT 4.0,
                verb_menu_show_disabled INTEGER NOT NULL DEFAULT 1,
                verb_text_color TEXT NOT NULL DEFAULT '#34261b',
                inventory_slots_json TEXT NOT NULL DEFAULT '[]',
                inventory_background_relative_path TEXT,
                verb_tag_background_relative_path TEXT,
                cursor_default_relative_path TEXT,
                cursor_default_hotspot_x INTEGER NOT NULL DEFAULT 0,
                cursor_default_hotspot_y INTEGER NOT NULL DEFAULT 0,
                cursor_hover_interactive_relative_path TEXT,
                cursor_hover_interactive_hotspot_x INTEGER NOT NULL DEFAULT 0,
                cursor_hover_interactive_hotspot_y INTEGER NOT NULL DEFAULT 0,
                cursor_busy_relative_path TEXT,
                cursor_busy_hotspot_x INTEGER NOT NULL DEFAULT 0,
                cursor_busy_hotspot_y INTEGER NOT NULL DEFAULT 0,
                cursor_blocked_relative_path TEXT,
                cursor_blocked_hotspot_x INTEGER NOT NULL DEFAULT 0,
                cursor_blocked_hotspot_y INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (organization_id, project_id),
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (start_scene_id) REFERENCES scenes(id)
            )
            """,
            insert_sql="""
            INSERT INTO global_settings (
                organization_id,
                project_id,
                overlay_open_duration_seconds,
                overlay_close_duration_seconds,
                overlay_fade_color,
                overlay_affect_audio,
                start_scene_id,
                inventory_key_code,
                verb_menu_timeout_seconds,
                verb_menu_show_disabled,
                verb_text_color,
                inventory_slots_json,
                inventory_background_relative_path,
                verb_tag_background_relative_path,
                cursor_default_relative_path,
                cursor_default_hotspot_x,
                cursor_default_hotspot_y,
                cursor_hover_interactive_relative_path,
                cursor_hover_interactive_hotspot_x,
                cursor_hover_interactive_hotspot_y,
                cursor_busy_relative_path,
                cursor_busy_hotspot_x,
                cursor_busy_hotspot_y,
                cursor_blocked_relative_path,
                cursor_blocked_hotspot_x,
                cursor_blocked_hotspot_y,
                created_at,
                updated_at
            )
            SELECT organization_id,
                   project_id,
                   overlay_open_duration_seconds,
                   overlay_close_duration_seconds,
                   overlay_fade_color,
                   overlay_affect_audio,
                   start_scene_id,
                   inventory_key_code,
                   verb_menu_timeout_seconds,
                   verb_menu_show_disabled,
                   verb_text_color,
                   inventory_slots_json,
                   inventory_background_relative_path,
                   verb_tag_background_relative_path,
                   cursor_default_relative_path,
                   cursor_default_hotspot_x,
                   cursor_default_hotspot_y,
                   cursor_hover_interactive_relative_path,
                   cursor_hover_interactive_hotspot_x,
                   cursor_hover_interactive_hotspot_y,
                   cursor_busy_relative_path,
                   cursor_busy_hotspot_x,
                   cursor_busy_hotspot_y,
                   cursor_blocked_relative_path,
                   cursor_blocked_hotspot_x,
                   cursor_blocked_hotspot_y,
                   created_at,
                   updated_at
            FROM {old_table}
            """,
        )

    table_rebuild_specs = (
        (
            "script_lines",
            ("organization_id", "project_id", "line_id"),
            """
            CREATE TABLE script_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                project_id INTEGER NOT NULL,
                line_id INTEGER NOT NULL,
                script_index INTEGER NOT NULL,
                source_text TEXT NOT NULL,
                path_json TEXT NOT NULL DEFAULT '[]',
                path_text TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (organization_id, project_id, line_id),
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            )
            """,
            """
            INSERT INTO script_lines (
                id,
                organization_id,
                project_id,
                line_id,
                script_index,
                source_text,
                path_json,
                path_text,
                created_at,
                updated_at
            )
            SELECT id,
                   organization_id,
                   project_id,
                   line_id,
                   script_index,
                   source_text,
                   path_json,
                   path_text,
                   created_at,
                   updated_at
            FROM {old_table}
            """,
        ),
        (
            "characters",
            ("organization_id", "project_id", "name"),
            """
            CREATE TABLE characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                scene_id INTEGER,
                mouth_scene_object_id INTEGER,
                sort_order INTEGER NOT NULL DEFAULT 0,
                default_x REAL NOT NULL DEFAULT 960,
                default_y REAL NOT NULL DEFAULT 540,
                default_scale REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (organization_id, project_id, name),
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (scene_id) REFERENCES scenes(id),
                FOREIGN KEY (mouth_scene_object_id) REFERENCES scene_objects(id)
            )
            """,
            """
            INSERT INTO characters (
                id,
                organization_id,
                project_id,
                name,
                description,
                scene_id,
                mouth_scene_object_id,
                sort_order,
                default_x,
                default_y,
                default_scale,
                created_at,
                updated_at
            )
            SELECT id,
                   organization_id,
                   project_id,
                   name,
                   description,
                   scene_id,
                   mouth_scene_object_id,
                   sort_order,
                   default_x,
                   default_y,
                   default_scale,
                   created_at,
                   updated_at
            FROM {old_table}
            """,
        ),
        (
            "conversations",
            ("organization_id", "project_id", "name"),
            """
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                start_node_id INTEGER,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (organization_id, project_id, name),
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (start_node_id) REFERENCES conversation_nodes(id)
            )
            """,
            """
            INSERT INTO conversations (
                id,
                organization_id,
                project_id,
                name,
                description,
                start_node_id,
                sort_order,
                created_at,
                updated_at
            )
            SELECT id,
                   organization_id,
                   project_id,
                   name,
                   description,
                   start_node_id,
                   sort_order,
                   created_at,
                   updated_at
            FROM {old_table}
            """,
        ),
        (
            "game_variables",
            ("organization_id", "project_id", "name"),
            """
            CREATE TABLE game_variables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                value_type TEXT NOT NULL CHECK (value_type IN ('bool', 'string', 'number')),
                default_value_json TEXT NOT NULL DEFAULT 'null',
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (organization_id, project_id, name),
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            )
            """,
            """
            INSERT INTO game_variables (
                id,
                organization_id,
                project_id,
                name,
                value_type,
                default_value_json,
                description,
                created_at,
                updated_at
            )
            SELECT id,
                   organization_id,
                   project_id,
                   name,
                   value_type,
                   default_value_json,
                   description,
                   created_at,
                   updated_at
            FROM {old_table}
            """,
        ),
        (
            "overlay_scene_bindings",
            ("organization_id", "project_id", "key_code"),
            """
            CREATE TABLE overlay_scene_bindings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                project_id INTEGER NOT NULL,
                key_code TEXT NOT NULL,
                overlay_scene_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (organization_id, project_id, key_code),
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (overlay_scene_id) REFERENCES scenes(id)
            )
            """,
            """
            INSERT INTO overlay_scene_bindings (
                id,
                organization_id,
                project_id,
                key_code,
                overlay_scene_id,
                created_at,
                updated_at
            )
            SELECT id,
                   organization_id,
                   project_id,
                   key_code,
                   overlay_scene_id,
                   created_at,
                   updated_at
            FROM {old_table}
            """,
        ),
        (
            "verbs",
            ("organization_id", "project_id", "key"),
            """
            CREATE TABLE verbs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                project_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                labels_json TEXT NOT NULL DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (organization_id, project_id, key),
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            )
            """,
            """
            INSERT INTO verbs (
                id,
                organization_id,
                project_id,
                key,
                labels_json,
                enabled,
                sort_order,
                created_at,
                updated_at
            )
            SELECT id,
                   organization_id,
                   project_id,
                   key,
                   labels_json,
                   enabled,
                   sort_order,
                   created_at,
                   updated_at
            FROM {old_table}
            """,
        ),
    )
    for table_name, unique_columns, create_sql, insert_sql in table_rebuild_specs:
        if not _has_unique_constraint(connection, table_name, unique_columns):
            _rebuild_table(
                connection,
                table_name=table_name,
                create_sql=create_sql,
                insert_sql=insert_sql,
            )

    connection.execute("DROP INDEX IF EXISTS idx_script_lines_path")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_script_lines_path ON script_lines (organization_id, project_id, path_text)"
    )
    connection.execute("DROP INDEX IF EXISTS idx_characters_org_sort")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_characters_org_sort ON characters (organization_id, project_id, sort_order, id)"
    )
    connection.execute("DROP INDEX IF EXISTS idx_conversations_org_sort")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_org_sort ON conversations (organization_id, project_id, sort_order, id)"
    )
    connection.execute("DROP INDEX IF EXISTS idx_overlay_scene_bindings_org")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_overlay_scene_bindings_org ON overlay_scene_bindings (organization_id, project_id, overlay_scene_id)"
    )
    connection.execute("DROP INDEX IF EXISTS idx_verbs_org")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_verbs_org ON verbs (organization_id, project_id, sort_order, id)"
    )


def init_database(
    db_path: Path,
    organization_id: str = "wonky-studio",
    organization_name: str = "Wonky Studio",
) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            INSERT INTO organizations (id, name)
            VALUES (?, ?)
            ON CONFLICT(id) DO UPDATE SET name = excluded.name
            """,
            (organization_id, organization_name),
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                name TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (organization_id, name),
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_projects_org_sort ON projects (organization_id, sort_order, id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT,
                avatar_url TEXT,
                role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_identities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                provider_subject TEXT NOT NULL,
                email TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (provider, provider_subject),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                active_project_id INTEGER,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (active_project_id) REFERENCES projects(id)
            )
            """
        )
        _ensure_column(connection, "sessions", "active_project_id", "INTEGER")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                email TEXT,
                role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
                created_by_user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                used_by_user_id INTEGER,
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (created_by_user_id) REFERENCES users(id),
                FOREIGN KEY (used_by_user_id) REFERENCES users(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL DEFAULT 'wonky-studio',
                name TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'planned',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
            """
        )
        _ensure_column(connection, "assets", "organization_id", "TEXT NOT NULL DEFAULT 'wonky-studio'")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audio_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('bgm', 'sfx')),
                relative_path TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                content_type TEXT,
                file_size INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_audio_assets_org_kind ON audio_assets (organization_id, kind, id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS upload_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                created_by_user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                file_count INTEGER NOT NULL DEFAULT 0,
                total_bytes INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (created_by_user_id) REFERENCES users(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS uploaded_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                organization_id TEXT NOT NULL,
                uploaded_by_user_id INTEGER NOT NULL,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                content_type TEXT,
                file_size INTEGER NOT NULL,
                processing_status TEXT NOT NULL DEFAULT 'queued',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (batch_id) REFERENCES upload_batches(id),
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (uploaded_by_user_id) REFERENCES users(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS scenes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                presentation_mode TEXT NOT NULL DEFAULT 'base',
                status TEXT NOT NULL DEFAULT 'draft',
                background_frame_index INTEGER NOT NULL DEFAULT 0,
                representative_uploaded_file_id INTEGER,
                representative_hash TEXT,
                created_by_user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (representative_uploaded_file_id) REFERENCES uploaded_files(id),
                FOREIGN KEY (created_by_user_id) REFERENCES users(id)
            )
            """
        )
        _ensure_column(connection, "scenes", "presentation_mode", "TEXT NOT NULL DEFAULT 'base'")
        _ensure_column(connection, "scenes", "background_frame_index", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "scenes", "sort_order", "INTEGER NOT NULL DEFAULT 0")
        connection.execute(
            """
            UPDATE scenes
            SET presentation_mode = 'base'
            WHERE trim(presentation_mode) = ''
            """
        )
        connection.execute(
            """
            UPDATE scenes
            SET sort_order = id
            WHERE sort_order = 0
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS scene_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scene_id INTEGER NOT NULL,
                uploaded_file_id INTEGER NOT NULL UNIQUE,
                perceptual_hash TEXT NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (scene_id) REFERENCES scenes(id),
                FOREIGN KEY (uploaded_file_id) REFERENCES uploaded_files(id)
            )
            """
        )
        _ensure_column(connection, "scene_images", "sort_order", "INTEGER NOT NULL DEFAULT 0")
        connection.execute(
            """
            UPDATE scene_images
            SET sort_order = id
            WHERE sort_order = 0
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS scene_objects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scene_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                prompt TEXT NOT NULL DEFAULT '',
                inventory_image_prompt TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'other',
                source TEXT NOT NULL DEFAULT 'manual',
                sort_order INTEGER NOT NULL DEFAULT 0,
                visible INTEGER NOT NULL DEFAULT 1,
                enabled INTEGER NOT NULL DEFAULT 1,
                keyboard_target_enabled INTEGER NOT NULL DEFAULT 0,
                default_uploaded_file_id INTEGER,
                inventory_image_relative_path TEXT,
                inventory_image_failed INTEGER NOT NULL DEFAULT 0,
                pickup_frame_failed INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (scene_id) REFERENCES scenes(id)
            )
            """
        )
        _ensure_column(connection, "scene_objects", "prompt", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "scene_objects", "inventory_image_prompt", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "scene_objects", "category", "TEXT NOT NULL DEFAULT 'other'")
        _ensure_column(connection, "scene_objects", "source", "TEXT NOT NULL DEFAULT 'manual'")
        _ensure_column(connection, "scene_objects", "sort_order", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "scene_objects", "visible", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(connection, "scene_objects", "enabled", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(connection, "scene_objects", "keyboard_target_enabled", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "scene_objects", "default_uploaded_file_id", "INTEGER")
        _ensure_column(connection, "scene_objects", "pickup_uploaded_file_id", "INTEGER")
        _ensure_column(connection, "scene_objects", "inventory_image_relative_path", "TEXT")
        _ensure_column(connection, "scene_objects", "inventory_image_failed", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "scene_objects", "pickup_frame_failed", "INTEGER NOT NULL DEFAULT 0")
        connection.execute(
            """
            UPDATE scene_objects
            SET prompt = name
            WHERE trim(prompt) = ''
            """
        )
        connection.execute(
            """
            UPDATE scene_objects
            SET sort_order = id
            WHERE sort_order = 0
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS global_settings (
                organization_id TEXT PRIMARY KEY,
                overlay_open_duration_seconds REAL NOT NULL DEFAULT 0.22,
                overlay_close_duration_seconds REAL NOT NULL DEFAULT 0.18,
                overlay_fade_color TEXT NOT NULL DEFAULT '#000000',
                overlay_affect_audio INTEGER NOT NULL DEFAULT 0,
                start_scene_id INTEGER,
                inventory_key_code TEXT NOT NULL DEFAULT 'KeyI',
                verb_menu_timeout_seconds REAL NOT NULL DEFAULT 4.0,
                verb_menu_show_disabled INTEGER NOT NULL DEFAULT 1,
                verb_text_color TEXT NOT NULL DEFAULT '#34261b',
                inventory_slots_json TEXT NOT NULL DEFAULT '[]',
                inventory_background_relative_path TEXT,
                verb_tag_background_relative_path TEXT,
                cursor_default_relative_path TEXT,
                cursor_default_hotspot_x INTEGER NOT NULL DEFAULT 0,
                cursor_default_hotspot_y INTEGER NOT NULL DEFAULT 0,
                cursor_hover_interactive_relative_path TEXT,
                cursor_hover_interactive_hotspot_x INTEGER NOT NULL DEFAULT 0,
                cursor_hover_interactive_hotspot_y INTEGER NOT NULL DEFAULT 0,
                cursor_busy_relative_path TEXT,
                cursor_busy_hotspot_x INTEGER NOT NULL DEFAULT 0,
                cursor_busy_hotspot_y INTEGER NOT NULL DEFAULT 0,
                cursor_blocked_relative_path TEXT,
                cursor_blocked_hotspot_x INTEGER NOT NULL DEFAULT 0,
                cursor_blocked_hotspot_y INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (start_scene_id) REFERENCES scenes(id)
            )
            """
        )
        _ensure_column(connection, "global_settings", "start_scene_id", "INTEGER")
        _ensure_column(connection, "global_settings", "inventory_key_code", "TEXT NOT NULL DEFAULT 'KeyI'")
        _ensure_column(connection, "global_settings", "verb_menu_timeout_seconds", "REAL NOT NULL DEFAULT 4.0")
        _ensure_column(connection, "global_settings", "verb_menu_show_disabled", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(connection, "global_settings", "verb_text_color", "TEXT NOT NULL DEFAULT '#34261b'")
        _ensure_column(connection, "global_settings", "inventory_slots_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(connection, "global_settings", "inventory_background_relative_path", "TEXT")
        _ensure_column(connection, "global_settings", "verb_tag_background_relative_path", "TEXT")
        _ensure_column(connection, "global_settings", "cursor_default_relative_path", "TEXT")
        _ensure_column(connection, "global_settings", "cursor_default_hotspot_x", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "global_settings", "cursor_default_hotspot_y", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "global_settings", "cursor_hover_interactive_relative_path", "TEXT")
        _ensure_column(connection, "global_settings", "cursor_hover_interactive_hotspot_x", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "global_settings", "cursor_hover_interactive_hotspot_y", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "global_settings", "cursor_busy_relative_path", "TEXT")
        _ensure_column(connection, "global_settings", "cursor_busy_hotspot_x", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "global_settings", "cursor_busy_hotspot_y", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "global_settings", "cursor_blocked_relative_path", "TEXT")
        _ensure_column(connection, "global_settings", "cursor_blocked_hotspot_x", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "global_settings", "cursor_blocked_hotspot_y", "INTEGER NOT NULL DEFAULT 0")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS object_animations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scene_object_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (scene_object_id) REFERENCES scene_objects(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS object_animation_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                object_animation_id INTEGER NOT NULL,
                start_frame INTEGER NOT NULL,
                end_frame INTEGER NOT NULL,
                frame_duration_seconds REAL NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (object_animation_id) REFERENCES object_animations(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS object_masks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scene_object_id INTEGER NOT NULL,
                uploaded_file_id INTEGER NOT NULL,
                relative_path TEXT NOT NULL,
                soft_relative_path TEXT,
                prompt_text TEXT NOT NULL DEFAULT '',
                bbox_json TEXT,
                score REAL,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (scene_object_id) REFERENCES scene_objects(id),
                FOREIGN KEY (uploaded_file_id) REFERENCES uploaded_files(id)
            )
            """
        )
        _ensure_column(connection, "object_masks", "soft_relative_path", "TEXT")
        _ensure_column(connection, "object_masks", "prompt_text", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(
            connection,
            "object_masks",
            "updated_at",
            "TEXT NOT NULL DEFAULT ''",
        )
        connection.execute(
            """
            UPDATE object_masks
            SET updated_at = created_at
            WHERE trim(updated_at) = ''
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS scene_mask_prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scene_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                enabled INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (scene_id) REFERENCES scenes(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mask_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scene_mask_prompt_id INTEGER NOT NULL,
                scene_image_id INTEGER NOT NULL,
                uploaded_file_id INTEGER NOT NULL,
                raw_relative_path TEXT NOT NULL,
                soft_relative_path TEXT,
                bbox_json TEXT,
                score REAL,
                selected INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (scene_mask_prompt_id) REFERENCES scene_mask_prompts(id),
                FOREIGN KEY (scene_image_id) REFERENCES scene_images(id),
                FOREIGN KEY (uploaded_file_id) REFERENCES uploaded_files(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS object_mask_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scene_object_id INTEGER NOT NULL,
                uploaded_file_id INTEGER NOT NULL,
                relative_path TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1,
                source TEXT NOT NULL DEFAULT 'generated',
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (scene_object_id) REFERENCES scene_objects(id),
                FOREIGN KEY (uploaded_file_id) REFERENCES uploaded_files(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS processing_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                scene_id INTEGER,
                script_line_id INTEGER,
                character_id INTEGER,
                script_audio_candidate_id INTEGER,
                progress_current INTEGER NOT NULL DEFAULT 0,
                progress_total INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                result_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                completed_at TEXT,
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (scene_id) REFERENCES scenes(id),
                FOREIGN KEY (character_id) REFERENCES characters(id),
                FOREIGN KEY (script_audio_candidate_id) REFERENCES script_audio_candidates(id)
            )
            """
        )
        _ensure_column(connection, "processing_jobs", "script_line_id", "INTEGER")
        _ensure_column(connection, "processing_jobs", "character_id", "INTEGER")
        _ensure_column(connection, "processing_jobs", "script_audio_candidate_id", "INTEGER")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS script_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                line_id INTEGER NOT NULL,
                script_index INTEGER NOT NULL,
                source_text TEXT NOT NULL,
                path_json TEXT NOT NULL DEFAULT '[]',
                path_text TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (organization_id, line_id),
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS script_translations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                script_line_id INTEGER NOT NULL,
                language TEXT NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'ai_translation',
                review_status TEXT NOT NULL DEFAULT 'needs_review',
                notes TEXT NOT NULL DEFAULT '',
                manually_edited INTEGER NOT NULL DEFAULT 0,
                meta_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (script_line_id, language),
                FOREIGN KEY (script_line_id) REFERENCES script_lines(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS script_audio_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                script_line_id INTEGER NOT NULL,
                language TEXT NOT NULL,
                source_type TEXT NOT NULL,
                manifest_status TEXT NOT NULL DEFAULT '',
                review_status TEXT NOT NULL DEFAULT 'needs_review',
                relative_path TEXT NOT NULL DEFAULT '',
                original_path TEXT NOT NULL DEFAULT '',
                selected INTEGER NOT NULL DEFAULT 0,
                rank INTEGER,
                score REAL,
                text_score REAL,
                quality_score REAL,
                duration_seconds REAL,
                transcript_match TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                source_file TEXT NOT NULL DEFAULT '',
                start_seconds REAL,
                end_seconds REAL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (script_line_id, language, source_type, original_path, rank),
                FOREIGN KEY (script_line_id) REFERENCES script_lines(id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_script_lines_path ON script_lines (organization_id, path_text)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_script_translations_status ON script_translations (language, review_status)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_script_audio_status ON script_audio_candidates (language, source_type, review_status)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS script_audio_candidate_viseme_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                script_audio_candidate_id INTEGER NOT NULL,
                viseme_key TEXT NOT NULL,
                start_seconds REAL NOT NULL,
                end_seconds REAL NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (script_audio_candidate_id) REFERENCES script_audio_candidates(id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_script_audio_visemes_candidate ON script_audio_candidate_viseme_events (script_audio_candidate_id, sort_order, id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                scene_id INTEGER,
                mouth_scene_object_id INTEGER,
                sort_order INTEGER NOT NULL DEFAULT 0,
                default_x REAL NOT NULL DEFAULT 960,
                default_y REAL NOT NULL DEFAULT 540,
                default_scale REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (organization_id, name),
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (scene_id) REFERENCES scenes(id),
                FOREIGN KEY (mouth_scene_object_id) REFERENCES scene_objects(id)
            )
            """
        )
        _ensure_column(connection, "characters", "scene_id", "INTEGER")
        _ensure_column(connection, "characters", "mouth_scene_object_id", "INTEGER")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_characters_org_sort ON characters (organization_id, sort_order, id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS character_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL,
                component_key TEXT NOT NULL,
                variant_key TEXT NOT NULL,
                kind TEXT NOT NULL,
                source_group TEXT NOT NULL DEFAULT '',
                source_name TEXT NOT NULL DEFAULT '',
                relative_path TEXT NOT NULL,
                original_filename TEXT NOT NULL DEFAULT '',
                width INTEGER NOT NULL DEFAULT 0,
                height INTEGER NOT NULL DEFAULT 0,
                is_default INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (character_id, component_key, variant_key),
                FOREIGN KEY (character_id) REFERENCES characters(id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_character_images_character ON character_images (character_id, component_key, sort_order, id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS character_objects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                prompt TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_viseme_target INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (character_id) REFERENCES characters(id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_character_objects_character ON character_objects (character_id, sort_order, id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS character_object_masks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_object_id INTEGER NOT NULL,
                character_image_id INTEGER NOT NULL,
                relative_path TEXT NOT NULL,
                soft_relative_path TEXT,
                prompt_text TEXT NOT NULL DEFAULT '',
                bbox_json TEXT,
                score REAL,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (character_object_id) REFERENCES character_objects(id),
                FOREIGN KEY (character_image_id) REFERENCES character_images(id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_character_object_masks_object ON character_object_masks (character_object_id, character_image_id, id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS character_animations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (character_id, name),
                FOREIGN KEY (character_id) REFERENCES characters(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS character_animation_frames (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_animation_id INTEGER NOT NULL,
                character_image_id INTEGER NOT NULL,
                duration_seconds REAL NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (character_animation_id) REFERENCES character_animations(id),
                FOREIGN KEY (character_image_id) REFERENCES character_images(id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_character_animation_frames_animation ON character_animation_frames (character_animation_id, sort_order, id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                start_node_id INTEGER,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (organization_id, name),
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (start_node_id) REFERENCES conversation_nodes(id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_org_sort ON conversations (organization_id, sort_order, id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                script_line_id INTEGER,
                speaker_character_id INTEGER,
                enter_actions_json TEXT NOT NULL DEFAULT '[]',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id),
                FOREIGN KEY (script_line_id) REFERENCES script_lines(id),
                FOREIGN KEY (speaker_character_id) REFERENCES characters(id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversation_nodes_conversation ON conversation_nodes (conversation_id, sort_order, id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_choices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id INTEGER NOT NULL,
                script_line_id INTEGER,
                conditions_json TEXT NOT NULL DEFAULT '[]',
                actions_json TEXT NOT NULL DEFAULT '[]',
                next_node_id INTEGER,
                end_conversation INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (node_id) REFERENCES conversation_nodes(id),
                FOREIGN KEY (script_line_id) REFERENCES script_lines(id),
                FOREIGN KEY (next_node_id) REFERENCES conversation_nodes(id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversation_choices_node ON conversation_choices (node_id, sort_order, id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS game_variables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                name TEXT NOT NULL,
                value_type TEXT NOT NULL CHECK (value_type IN ('bool', 'string', 'number')),
                default_value_json TEXT NOT NULL DEFAULT 'null',
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (organization_id, name),
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS scene_interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scene_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                trigger_json TEXT NOT NULL DEFAULT '{}',
                action_tree_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (scene_id) REFERENCES scenes(id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_scene_interactions_scene ON scene_interactions (scene_id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS overlay_scene_bindings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                key_code TEXT NOT NULL,
                overlay_scene_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (organization_id, key_code),
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (overlay_scene_id) REFERENCES scenes(id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_overlay_scene_bindings_org ON overlay_scene_bindings (organization_id, overlay_scene_id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS verbs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id TEXT NOT NULL,
                key TEXT NOT NULL,
                labels_json TEXT NOT NULL DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (organization_id, key),
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_verbs_org ON verbs (organization_id, sort_order, id)"
        )
        project_scoped_tables = (
            "assets",
            "audio_assets",
            "upload_batches",
            "uploaded_files",
            "scenes",
            "processing_jobs",
            "script_lines",
            "global_settings",
            "characters",
            "conversations",
            "game_variables",
            "overlay_scene_bindings",
            "verbs",
        )
        for table_name in project_scoped_tables:
            _ensure_column(connection, table_name, "project_id", "INTEGER")

        organization_rows = connection.execute(
            """
            SELECT id
            FROM organizations
            ORDER BY id ASC
            """
        ).fetchall()
        default_project_ids: dict[str, int] = {}
        for organization_row in organization_rows:
            org_id = str(organization_row["id"])
            default_project_ids[org_id] = _get_or_create_default_project_id(connection, org_id)

        for table_name in project_scoped_tables:
            rows = connection.execute(
                f"""
                SELECT rowid AS row_id, organization_id
                FROM {table_name}
                WHERE project_id IS NULL
                """
            ).fetchall()
            for row in rows:
                org_id = str(row["organization_id"])
                project_id = default_project_ids.get(org_id)
                if project_id is None:
                    project_id = _get_or_create_default_project_id(connection, org_id)
                    default_project_ids[org_id] = project_id
                connection.execute(
                    f"UPDATE {table_name} SET project_id = ? WHERE rowid = ?",
                    (project_id, int(row["row_id"])),
                )

        connection.execute(
            """
            UPDATE sessions
            SET active_project_id = (
                SELECT projects.id
                FROM users
                JOIN projects ON projects.organization_id = users.organization_id
                WHERE users.id = sessions.user_id
                ORDER BY projects.sort_order ASC, projects.id ASC
                LIMIT 1
            )
            WHERE active_project_id IS NULL
            """
        )
        _ensure_project_scoped_uniqueness(connection)
    ensure_system_game_variables(db_path, organization_id)


def ensure_system_game_variables(db_path: Path, organization_id: str) -> None:
    with connect(db_path) as connection:
        project_rows = connection.execute(
            """
            SELECT id
            FROM projects
            WHERE organization_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (organization_id,),
        ).fetchall()
        if not project_rows:
            project_rows = [{"id": _get_or_create_default_project_id(connection, organization_id)}]
        for project_row in project_rows:
            project_id = int(project_row["id"])
            for variable in SYSTEM_GAME_VARIABLES:
                connection.execute(
                    """
                    INSERT INTO game_variables (
                        organization_id,
                        project_id,
                        name,
                        value_type,
                        default_value_json,
                        description
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (organization_id, project_id, name) DO NOTHING
                    """,
                    (
                        organization_id,
                        project_id,
                        variable["name"],
                        variable["value_type"],
                        json.dumps(variable["default_value"], separators=(",", ":")),
                        variable["description"],
                    ),
                )


def list_assets(db_path: Path, organization_id: str) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, organization_id, name, asset_type, status, created_at
            FROM assets
            WHERE organization_id = ?
            ORDER BY id ASC
            """,
            (organization_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def reset_workspace_tables(db_path: Path, preserve_audio_assets: bool = False) -> list[str]:
    tables = [
        "scene_interactions",
        "verbs",
        "overlay_scene_bindings",
        "global_settings",
        "game_variables",
        "character_animation_frames",
        "character_animations",
        "character_object_masks",
        "character_objects",
        "character_images",
        "characters",
        "script_audio_candidate_viseme_events",
        "audio_assets",
        "script_audio_candidates",
        "script_translations",
        "script_lines",
        "object_mask_images",
        "mask_candidates",
        "scene_mask_prompts",
        "object_masks",
        "object_animation_segments",
        "object_animations",
        "scene_objects",
        "scene_images",
        "scenes",
        "uploaded_files",
        "upload_batches",
        "assets",
        "invites",
        "processing_jobs",
    ]
    if preserve_audio_assets:
        tables = [table for table in tables if table != "audio_assets"]
    with connect(db_path) as connection:
        for table in tables:
            connection.execute(f"DELETE FROM {table}")
        placeholders = ",".join("?" for _ in tables)
        connection.execute(
            f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})",
            tables,
        )

    return tables


def create_processing_job(
    db_path: Path,
    organization_id: str,
    job_type: str,
    scene_id: int | None = None,
    script_line_id: int | None = None,
    character_id: int | None = None,
    script_audio_candidate_id: int | None = None,
    progress_total: int = 0,
    message: str = "",
) -> dict[str, Any]:
    with connect(db_path) as connection:
        project_id: int | None = None
        if scene_id is not None:
            row = connection.execute(
                "SELECT project_id FROM scenes WHERE id = ? AND organization_id = ?",
                (scene_id, organization_id),
            ).fetchone()
            if row is not None and row["project_id"] is not None:
                project_id = int(row["project_id"])
        if project_id is None and script_line_id is not None:
            row = connection.execute(
                "SELECT project_id FROM script_lines WHERE id = ? AND organization_id = ?",
                (script_line_id, organization_id),
            ).fetchone()
            if row is not None and row["project_id"] is not None:
                project_id = int(row["project_id"])
        if project_id is None and character_id is not None:
            row = connection.execute(
                "SELECT project_id FROM characters WHERE id = ? AND organization_id = ?",
                (character_id, organization_id),
            ).fetchone()
            if row is not None and row["project_id"] is not None:
                project_id = int(row["project_id"])
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        cursor = connection.execute(
            """
            INSERT INTO processing_jobs (
                organization_id,
                project_id,
                job_type,
                scene_id,
                script_line_id,
                character_id,
                script_audio_candidate_id,
                progress_total,
                message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                organization_id,
                project_id,
                job_type,
                scene_id,
                script_line_id,
                character_id,
                script_audio_candidate_id,
                progress_total,
                message,
            ),
        )
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   project_id,
                   job_type,
                   status,
                   scene_id,
                   script_line_id,
                   character_id,
                   script_audio_candidate_id,
                   progress_current,
                   progress_total,
                   message,
                   result_json,
                   error,
                   created_at,
                   updated_at,
                   started_at,
                   completed_at
            FROM processing_jobs
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()

    return dict(row)


def get_processing_job(
    db_path: Path,
    job_id: int,
    organization_id: str,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   job_type,
                   status,
                   scene_id,
                   script_line_id,
                   character_id,
                   script_audio_candidate_id,
                   progress_current,
                   progress_total,
                   message,
                   result_json,
                   error,
                   created_at,
                   updated_at,
                   started_at,
                   completed_at
            FROM processing_jobs
            WHERE id = ?
              AND organization_id = ?
            """,
            (job_id, organization_id),
        ).fetchone()

    return dict(row) if row else None


def get_active_processing_job_for_scene(
    db_path: Path,
    organization_id: str,
    scene_id: int,
    job_type: str,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   job_type,
                   status,
                   scene_id,
                   script_line_id,
                   character_id,
                   script_audio_candidate_id,
                   progress_current,
                   progress_total,
                   message,
                   result_json,
                   error,
                   created_at,
                   updated_at,
                   started_at,
                   completed_at
            FROM processing_jobs
            WHERE organization_id = ?
              AND scene_id = ?
              AND job_type = ?
              AND status IN ('queued', 'running')
            ORDER BY id DESC
            LIMIT 1
            """,
            (organization_id, scene_id, job_type),
        ).fetchone()

    return dict(row) if row else None


def get_active_processing_job_for_script_line(
    db_path: Path,
    organization_id: str,
    script_line_id: int,
    job_type: str,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   job_type,
                   status,
                   scene_id,
                   script_line_id,
                   character_id,
                   script_audio_candidate_id,
                   progress_current,
                   progress_total,
                   message,
                   result_json,
                   error,
                   created_at,
                   updated_at,
                   started_at,
                   completed_at
            FROM processing_jobs
            WHERE organization_id = ?
              AND script_line_id = ?
              AND job_type = ?
              AND status IN ('queued', 'running')
            ORDER BY id DESC
            LIMIT 1
            """,
            (organization_id, script_line_id, job_type),
        ).fetchone()

    return dict(row) if row else None


def claim_next_processing_job(db_path: Path) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   job_type,
                   status,
                   scene_id,
                   script_line_id,
                   character_id,
                   script_audio_candidate_id,
                   progress_current,
                   progress_total,
                   message,
                   result_json,
                   error,
                   created_at,
                   updated_at,
                   started_at,
                   completed_at
            FROM processing_jobs
            WHERE status = 'queued'
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        connection.execute(
            """
            UPDATE processing_jobs
            SET status = 'running',
                message = 'Starting...',
                started_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (row["id"],),
        )
        claimed = connection.execute(
            """
            SELECT id,
                   organization_id,
                   job_type,
                   status,
                   scene_id,
                   script_line_id,
                   character_id,
                   script_audio_candidate_id,
                   progress_current,
                   progress_total,
                   message,
                   result_json,
                   error,
                   created_at,
                   updated_at,
                   started_at,
                   completed_at
            FROM processing_jobs
            WHERE id = ?
            """,
            (row["id"],),
        ).fetchone()

    return dict(claimed)


def requeue_interrupted_processing_jobs(db_path: Path) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            UPDATE processing_jobs
            SET status = 'queued',
                message = 'Requeued after server restart',
                updated_at = CURRENT_TIMESTAMP,
                started_at = NULL
            WHERE status = 'running'
            """
        )


def update_processing_job_progress(
    db_path: Path,
    job_id: int,
    progress_current: int,
    progress_total: int | None = None,
    message: str | None = None,
) -> None:
    assignments = ["progress_current = ?", "updated_at = CURRENT_TIMESTAMP"]
    values: list[Any] = [progress_current]
    if progress_total is not None:
        assignments.append("progress_total = ?")
        values.append(progress_total)
    if message is not None:
        assignments.append("message = ?")
        values.append(message)
    with connect(db_path) as connection:
        connection.execute(
            f"""
            UPDATE processing_jobs
            SET {", ".join(assignments)}
            WHERE id = ?
            """,
            (*values, job_id),
        )


def complete_processing_job(
    db_path: Path,
    job_id: int,
    result: dict[str, Any],
    message: str = "Complete",
) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            UPDATE processing_jobs
            SET status = 'succeeded',
                progress_current = progress_total,
                message = ?,
                result_json = ?,
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (message, json_dumps(result), job_id),
        )


def fail_processing_job(
    db_path: Path,
    job_id: int,
    error: str,
) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            UPDATE processing_jobs
            SET status = 'failed',
                message = 'Failed',
                error = ?,
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (error, job_id),
        )


def create_asset(
    db_path: Path,
    organization_id: str,
    name: str,
    asset_type: str,
    status: str,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO assets (organization_id, name, asset_type, status)
            VALUES (?, ?, ?, ?)
            """,
            (organization_id, name, asset_type, status),
        )
        asset_id = cursor.lastrowid
        row = connection.execute(
            """
            SELECT id, organization_id, name, asset_type, status, created_at
            FROM assets
            WHERE id = ?
            """,
            (asset_id,),
        ).fetchone()

    if row is None:
        raise RuntimeError("Created asset could not be loaded")

    return dict(row)


def list_audio_assets(db_path: Path, organization_id: str, project_id: int | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        rows = connection.execute(
            """
            SELECT id,
                   organization_id,
                   project_id,
                   name,
                   kind,
                   relative_path,
                   original_filename,
                   content_type,
                   file_size,
                   created_at,
                   updated_at
            FROM audio_assets
            WHERE organization_id = ?
              AND project_id = ?
            ORDER BY kind ASC, id ASC
            """,
            (organization_id, project_id),
        ).fetchall()
    return [dict(row) for row in rows]


def create_audio_asset(
    db_path: Path,
    organization_id: str,
    project_id: int | None,
    name: str,
    kind: str,
    relative_path: str,
    original_filename: str,
    content_type: str | None,
    file_size: int,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        cursor = connection.execute(
            """
            INSERT INTO audio_assets (
                organization_id,
                project_id,
                name,
                kind,
                relative_path,
                original_filename,
                content_type,
                file_size
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                organization_id,
                project_id,
                name,
                kind,
                relative_path,
                original_filename,
                content_type,
                file_size,
            ),
        )
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   project_id,
                   name,
                   kind,
                   relative_path,
                   original_filename,
                   content_type,
                   file_size,
                   created_at,
                   updated_at
            FROM audio_assets
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
    if row is None:
        raise RuntimeError("Created audio asset could not be loaded")
    return dict(row)


def get_audio_asset_by_id(
    db_path: Path,
    organization_id: str,
    audio_asset_id: int,
    project_id: int | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        if project_id is None:
            row = connection.execute(
                """
                SELECT id,
                       organization_id,
                       project_id,
                       name,
                       kind,
                       relative_path,
                       original_filename,
                       content_type,
                       file_size,
                       created_at,
                       updated_at
                FROM audio_assets
                WHERE id = ?
                  AND organization_id = ?
                """,
                (audio_asset_id, organization_id),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT id,
                       organization_id,
                       project_id,
                       name,
                       kind,
                       relative_path,
                       original_filename,
                       content_type,
                       file_size,
                       created_at,
                       updated_at
                FROM audio_assets
                WHERE id = ?
                  AND organization_id = ?
                  AND project_id = ?
                """,
                (audio_asset_id, organization_id, project_id),
            ).fetchone()
    return dict(row) if row else None


def update_audio_asset(
    db_path: Path,
    organization_id: str,
    audio_asset_id: int,
    name: str,
    kind: str,
    project_id: int | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        connection.execute(
            """
            UPDATE audio_assets
            SET name = ?,
                kind = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND organization_id = ?
              AND project_id = ?
            """,
            (name, kind, audio_asset_id, organization_id, project_id),
        )
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   project_id,
                   name,
                   kind,
                   relative_path,
                   original_filename,
                   content_type,
                   file_size,
                   created_at,
                   updated_at
            FROM audio_assets
            WHERE id = ?
              AND organization_id = ?
              AND project_id = ?
            """,
            (audio_asset_id, organization_id, project_id),
        ).fetchone()
    return dict(row) if row else None


def delete_audio_asset(
    db_path: Path,
    organization_id: str,
    audio_asset_id: int,
    project_id: int | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   project_id,
                   name,
                   kind,
                   relative_path,
                   original_filename,
                   content_type,
                   file_size,
                   created_at,
                   updated_at
            FROM audio_assets
            WHERE id = ?
              AND organization_id = ?
              AND project_id = ?
            """,
            (audio_asset_id, organization_id, project_id),
        ).fetchone()
        if row is None:
            return None
        connection.execute(
            """
            DELETE FROM audio_assets
            WHERE id = ?
              AND organization_id = ?
              AND project_id = ?
            """,
            (audio_asset_id, organization_id, project_id),
        )
    return dict(row)


def list_overlay_scene_bindings(db_path: Path, organization_id: str, project_id: int | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        rows = connection.execute(
            """
            SELECT overlay_scene_bindings.id,
                   overlay_scene_bindings.organization_id,
                   overlay_scene_bindings.project_id,
                   overlay_scene_bindings.key_code,
                   overlay_scene_bindings.overlay_scene_id,
                   overlay_scene_bindings.created_at,
                   overlay_scene_bindings.updated_at,
                   scenes.title AS overlay_scene_title,
                   scenes.presentation_mode AS overlay_scene_presentation_mode
            FROM overlay_scene_bindings
            JOIN scenes ON scenes.id = overlay_scene_bindings.overlay_scene_id
            WHERE overlay_scene_bindings.organization_id = ?
              AND overlay_scene_bindings.project_id = ?
            ORDER BY lower(overlay_scene_bindings.key_code) ASC, overlay_scene_bindings.id ASC
            """,
            (organization_id, project_id),
        ).fetchall()
    return [dict(row) for row in rows]


def list_verbs(db_path: Path, organization_id: str, project_id: int | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        rows = connection.execute(
            """
            SELECT id,
                   organization_id,
                   project_id,
                   key,
                   labels_json,
                   enabled,
                   sort_order,
                   created_at,
                   updated_at
            FROM verbs
            WHERE organization_id = ?
              AND project_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (organization_id, project_id),
        ).fetchall()
    return [_verb_from_row(row) for row in rows]


def get_verb_by_id(
    db_path: Path,
    organization_id: str,
    verb_id: int,
    project_id: int | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        if project_id is None:
            row = connection.execute(
                """
                SELECT id,
                       organization_id,
                       project_id,
                       key,
                       labels_json,
                       enabled,
                       sort_order,
                       created_at,
                       updated_at
                FROM verbs
                WHERE id = ?
                  AND organization_id = ?
                """,
                (verb_id, organization_id),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT id,
                       organization_id,
                       project_id,
                       key,
                       labels_json,
                       enabled,
                       sort_order,
                       created_at,
                       updated_at
                FROM verbs
                WHERE id = ?
                  AND organization_id = ?
                  AND project_id = ?
                """,
                (verb_id, organization_id, project_id),
            ).fetchone()
    return _verb_from_row(row) if row else None


def create_verb(
    db_path: Path,
    organization_id: str,
    project_id: int | None,
    key: str,
    labels: dict[str, str],
    enabled: bool,
    sort_order: int,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        cursor = connection.execute(
            """
            INSERT INTO verbs (
                organization_id,
                project_id,
                key,
                labels_json,
                enabled,
                sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                organization_id,
                project_id,
                key.strip(),
                json_dumps(labels),
                int(bool(enabled)),
                int(sort_order),
            ),
        )
    created = get_verb_by_id(db_path, organization_id, int(cursor.lastrowid), project_id)
    if created is None:
        raise RuntimeError("Created verb could not be loaded")
    return created


def update_verb(
    db_path: Path,
    organization_id: str,
    verb_id: int,
    key: str,
    labels: dict[str, str],
    enabled: bool,
    sort_order: int,
    project_id: int | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        cursor = connection.execute(
            """
            UPDATE verbs
            SET key = ?,
                labels_json = ?,
                enabled = ?,
                sort_order = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND organization_id = ?
              AND project_id = ?
            """,
            (
                key.strip(),
                json_dumps(labels),
                int(bool(enabled)),
                int(sort_order),
                verb_id,
                organization_id,
                project_id,
            ),
        )
    if cursor.rowcount == 0:
        return None
    return get_verb_by_id(db_path, organization_id, verb_id, project_id)


def delete_verb(
    db_path: Path,
    organization_id: str,
    verb_id: int,
    project_id: int | None = None,
) -> None:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        connection.execute(
            """
            DELETE FROM verbs
            WHERE id = ?
              AND organization_id = ?
              AND project_id = ?
            """,
            (verb_id, organization_id, project_id),
        )


def list_characters(db_path: Path, organization_id: str, project_id: int | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        rows = connection.execute(
            """
            SELECT id,
                   organization_id,
                   project_id,
                   name,
                   description,
                   scene_id,
                   mouth_scene_object_id,
                   sort_order,
                   default_x,
                   default_y,
                   default_scale,
                   created_at,
                   updated_at
            FROM characters
            WHERE organization_id = ?
              AND project_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (organization_id, project_id),
        ).fetchall()
    return [_character_from_row(row) for row in rows]


def get_character_by_id(
    db_path: Path,
    organization_id: str,
    character_id: int,
    project_id: int | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        if project_id is None:
            row = connection.execute(
                """
                SELECT id,
                       organization_id,
                       project_id,
                       name,
                       description,
                       scene_id,
                       mouth_scene_object_id,
                       sort_order,
                       default_x,
                       default_y,
                       default_scale,
                       created_at,
                       updated_at
                FROM characters
                WHERE id = ?
                  AND organization_id = ?
                """,
                (character_id, organization_id),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT id,
                       organization_id,
                       project_id,
                       name,
                       description,
                       scene_id,
                       mouth_scene_object_id,
                       sort_order,
                       default_x,
                       default_y,
                       default_scale,
                       created_at,
                       updated_at
                FROM characters
                WHERE id = ?
                  AND organization_id = ?
                  AND project_id = ?
                """,
                (character_id, organization_id, project_id),
            ).fetchone()
    return _character_from_row(row) if row else None


def create_character(
    db_path: Path,
    organization_id: str,
    project_id: int | None,
    name: str,
    description: str,
    scene_id: int | None,
    sort_order: int,
    default_x: float,
    default_y: float,
    default_scale: float,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        cursor = connection.execute(
            """
            INSERT INTO characters (
                organization_id,
                project_id,
                name,
                description,
                scene_id,
                sort_order,
                default_x,
                default_y,
                default_scale
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                organization_id,
                project_id,
                name.strip(),
                description,
                scene_id if scene_id is None else int(scene_id),
                int(sort_order),
                float(default_x),
                float(default_y),
                float(default_scale),
            ),
        )
    created = get_character_by_id(db_path, organization_id, int(cursor.lastrowid), project_id)
    if created is None:
        raise RuntimeError("Created character could not be loaded")
    return created


def update_character(
    db_path: Path,
    organization_id: str,
    character_id: int,
    name: str | None = None,
    description: str | None = None,
    scene_id: int | None = None,
    update_scene_id: bool = False,
    mouth_scene_object_id: int | None = None,
    update_mouth_scene_object_id: bool = False,
    sort_order: int | None = None,
    default_x: float | None = None,
    default_y: float | None = None,
    default_scale: float | None = None,
) -> dict[str, Any] | None:
    assignments = ["updated_at = CURRENT_TIMESTAMP"]
    values: list[Any] = []
    if name is not None:
        assignments.append("name = ?")
        values.append(name.strip())
    if description is not None:
        assignments.append("description = ?")
        values.append(description)
    if update_scene_id:
        assignments.append("scene_id = ?")
        values.append(scene_id if scene_id is None else int(scene_id))
    if update_mouth_scene_object_id:
        assignments.append("mouth_scene_object_id = ?")
        values.append(
            mouth_scene_object_id
            if mouth_scene_object_id is None
            else int(mouth_scene_object_id)
        )
    if sort_order is not None:
        assignments.append("sort_order = ?")
        values.append(int(sort_order))
    if default_x is not None:
        assignments.append("default_x = ?")
        values.append(float(default_x))
    if default_y is not None:
        assignments.append("default_y = ?")
        values.append(float(default_y))
    if default_scale is not None:
        assignments.append("default_scale = ?")
        values.append(float(default_scale))
    with connect(db_path) as connection:
        cursor = connection.execute(
            f"""
            UPDATE characters
            SET {", ".join(assignments)}
            WHERE id = ?
              AND organization_id = ?
            """,
            (*values, character_id, organization_id),
        )
    if cursor.rowcount == 0:
        return None
    return get_character_by_id(db_path, organization_id, character_id)


def delete_character(db_path: Path, organization_id: str, character_id: int) -> bool:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT 1 FROM characters WHERE id = ? AND organization_id = ?",
            (character_id, organization_id),
        ).fetchone()
        if row is None:
            return False
        connection.execute(
            """
            DELETE FROM character_animation_frames
            WHERE character_animation_id IN (
                SELECT id
                FROM character_animations
                WHERE character_id = ?
            )
            """,
            (character_id,),
        )
        connection.execute(
            """
            DELETE FROM character_object_masks
            WHERE character_object_id IN (
                SELECT id
                FROM character_objects
                WHERE character_id = ?
            )
            """,
            (character_id,),
        )
        connection.execute("DELETE FROM character_objects WHERE character_id = ?", (character_id,))
        connection.execute("DELETE FROM character_animations WHERE character_id = ?", (character_id,))
        connection.execute("DELETE FROM character_images WHERE character_id = ?", (character_id,))
        connection.execute("DELETE FROM characters WHERE id = ?", (character_id,))
    return True


def list_conversations(db_path: Path, organization_id: str, project_id: int | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        rows = connection.execute(
            """
            SELECT id,
                   organization_id,
                   project_id,
                   name,
                   description,
                   start_node_id,
                   sort_order,
                   created_at,
                   updated_at
            FROM conversations
            WHERE organization_id = ?
              AND project_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (organization_id, project_id),
        ).fetchall()
    return [_conversation_from_row(row) for row in rows]


def get_conversation_by_id(
    db_path: Path,
    organization_id: str,
    conversation_id: int,
    project_id: int | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        if project_id is None:
            row = connection.execute(
                """
                SELECT id,
                       organization_id,
                       project_id,
                       name,
                       description,
                       start_node_id,
                       sort_order,
                       created_at,
                       updated_at
                FROM conversations
                WHERE id = ?
                  AND organization_id = ?
                """,
                (conversation_id, organization_id),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT id,
                       organization_id,
                       project_id,
                       name,
                       description,
                       start_node_id,
                       sort_order,
                       created_at,
                       updated_at
                FROM conversations
                WHERE id = ?
                  AND organization_id = ?
                  AND project_id = ?
                """,
                (conversation_id, organization_id, project_id),
            ).fetchone()
    return _conversation_from_row(row) if row else None


def create_conversation(
    db_path: Path,
    organization_id: str,
    project_id: int | None,
    name: str,
    description: str,
    sort_order: int = 0,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        cursor = connection.execute(
            """
            INSERT INTO conversations (
                organization_id,
                project_id,
                name,
                description,
                sort_order
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                organization_id,
                project_id,
                name.strip(),
                description,
                int(sort_order),
            ),
        )
    created = get_conversation_by_id(db_path, organization_id, int(cursor.lastrowid), project_id)
    if created is None:
        raise RuntimeError("Created conversation could not be loaded")
    return created


def update_conversation(
    db_path: Path,
    organization_id: str,
    conversation_id: int,
    name: str | None = None,
    description: str | None = None,
    start_node_id: int | None = None,
    update_start_node_id: bool = False,
    sort_order: int | None = None,
) -> dict[str, Any] | None:
    assignments = ["updated_at = CURRENT_TIMESTAMP"]
    values: list[Any] = []
    if name is not None:
        assignments.append("name = ?")
        values.append(name.strip())
    if description is not None:
        assignments.append("description = ?")
        values.append(description)
    if update_start_node_id:
        assignments.append("start_node_id = ?")
        values.append(start_node_id if start_node_id is None else int(start_node_id))
    if sort_order is not None:
        assignments.append("sort_order = ?")
        values.append(int(sort_order))
    with connect(db_path) as connection:
        cursor = connection.execute(
            f"""
            UPDATE conversations
            SET {", ".join(assignments)}
            WHERE id = ?
              AND organization_id = ?
            """,
            (*values, conversation_id, organization_id),
        )
    if cursor.rowcount == 0:
        return None
    return get_conversation_by_id(db_path, organization_id, conversation_id)


def delete_conversation(db_path: Path, organization_id: str, conversation_id: int) -> bool:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT 1 FROM conversations WHERE id = ? AND organization_id = ?",
            (conversation_id, organization_id),
        ).fetchone()
        if row is None:
            return False
        connection.execute(
            """
            DELETE FROM conversation_choices
            WHERE node_id IN (
                SELECT id
                FROM conversation_nodes
                WHERE conversation_id = ?
            )
            """,
            (conversation_id,),
        )
        connection.execute(
            "DELETE FROM conversation_nodes WHERE conversation_id = ?",
            (conversation_id,),
        )
        connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    return True


def list_conversation_nodes(
    db_path: Path,
    organization_id: str,
    conversation_id: int,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT cn.id,
                   cn.conversation_id,
                   cn.name,
                   cn.script_line_id,
                   cn.speaker_character_id,
                   cn.enter_actions_json,
                   cn.sort_order,
                   cn.created_at,
                   cn.updated_at
            FROM conversation_nodes cn
            JOIN conversations c ON c.id = cn.conversation_id
            WHERE cn.conversation_id = ?
              AND c.organization_id = ?
            ORDER BY cn.sort_order ASC, cn.id ASC
            """,
            (conversation_id, organization_id),
        ).fetchall()
    return [_conversation_node_from_row(row) for row in rows]


def get_conversation_node_by_id(
    db_path: Path,
    organization_id: str,
    node_id: int,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT cn.id,
                   cn.conversation_id,
                   cn.name,
                   cn.script_line_id,
                   cn.speaker_character_id,
                   cn.enter_actions_json,
                   cn.sort_order,
                   cn.created_at,
                   cn.updated_at
            FROM conversation_nodes cn
            JOIN conversations c ON c.id = cn.conversation_id
            WHERE cn.id = ?
              AND c.organization_id = ?
            """,
            (node_id, organization_id),
        ).fetchone()
    return _conversation_node_from_row(row) if row else None


def create_conversation_node(
    db_path: Path,
    organization_id: str,
    conversation_id: int,
    name: str,
    script_line_id: int | None = None,
    speaker_character_id: int | None = None,
    enter_actions: list[dict[str, Any]] | None = None,
    sort_order: int = 0,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO conversation_nodes (
                conversation_id,
                name,
                script_line_id,
                speaker_character_id,
                enter_actions_json,
                sort_order
            )
            SELECT ?, ?, ?, ?, ?, ?
            WHERE EXISTS (
                SELECT 1
                FROM conversations
                WHERE id = ?
                  AND organization_id = ?
            )
            """,
            (
                int(conversation_id),
                name.strip(),
                script_line_id if script_line_id is None else int(script_line_id),
                speaker_character_id if speaker_character_id is None else int(speaker_character_id),
                json.dumps(enter_actions or [], separators=(",", ":")),
                int(sort_order),
                int(conversation_id),
                organization_id,
            ),
        )
    created = get_conversation_node_by_id(db_path, organization_id, int(cursor.lastrowid))
    if created is None:
        raise RuntimeError("Created conversation node could not be loaded")
    return created


def update_conversation_node(
    db_path: Path,
    organization_id: str,
    node_id: int,
    name: str | None = None,
    script_line_id: int | None = None,
    update_script_line_id: bool = False,
    speaker_character_id: int | None = None,
    update_speaker_character_id: bool = False,
    enter_actions: list[dict[str, Any]] | None = None,
    update_enter_actions: bool = False,
    sort_order: int | None = None,
) -> dict[str, Any] | None:
    assignments = ["updated_at = CURRENT_TIMESTAMP"]
    values: list[Any] = []
    if name is not None:
        assignments.append("name = ?")
        values.append(name.strip())
    if update_script_line_id:
        assignments.append("script_line_id = ?")
        values.append(script_line_id if script_line_id is None else int(script_line_id))
    if update_speaker_character_id:
        assignments.append("speaker_character_id = ?")
        values.append(
            speaker_character_id if speaker_character_id is None else int(speaker_character_id)
        )
    if update_enter_actions:
        assignments.append("enter_actions_json = ?")
        values.append(json.dumps(enter_actions or [], separators=(",", ":")))
    if sort_order is not None:
        assignments.append("sort_order = ?")
        values.append(int(sort_order))
    with connect(db_path) as connection:
        cursor = connection.execute(
            f"""
            UPDATE conversation_nodes
            SET {", ".join(assignments)}
            WHERE id = ?
              AND conversation_id IN (
                  SELECT id
                  FROM conversations
                  WHERE organization_id = ?
              )
            """,
            (*values, node_id, organization_id),
        )
    if cursor.rowcount == 0:
        return None
    return get_conversation_node_by_id(db_path, organization_id, node_id)


def delete_conversation_node(db_path: Path, organization_id: str, node_id: int) -> bool:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT cn.id,
                   cn.conversation_id
            FROM conversation_nodes cn
            JOIN conversations c ON c.id = cn.conversation_id
            WHERE cn.id = ?
              AND c.organization_id = ?
            """,
            (node_id, organization_id),
        ).fetchone()
        if row is None:
            return False
        connection.execute(
            "DELETE FROM conversation_choices WHERE node_id = ?",
            (node_id,),
        )
        connection.execute(
            """
            UPDATE conversation_choices
            SET next_node_id = NULL,
                end_conversation = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE next_node_id = ?
            """,
            (node_id,),
        )
        connection.execute(
            """
            UPDATE conversations
            SET start_node_id = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND start_node_id = ?
            """,
            (int(row["conversation_id"]), node_id),
        )
        connection.execute("DELETE FROM conversation_nodes WHERE id = ?", (node_id,))
    return True


def list_conversation_choices(
    db_path: Path,
    organization_id: str,
    node_id: int,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT cc.id,
                   cc.node_id,
                   cc.script_line_id,
                   cc.conditions_json,
                   cc.actions_json,
                   cc.next_node_id,
                   cc.end_conversation,
                   cc.sort_order,
                   cc.created_at,
                   cc.updated_at
            FROM conversation_choices cc
            JOIN conversation_nodes cn ON cn.id = cc.node_id
            JOIN conversations c ON c.id = cn.conversation_id
            WHERE cc.node_id = ?
              AND c.organization_id = ?
            ORDER BY cc.sort_order ASC, cc.id ASC
            """,
            (node_id, organization_id),
        ).fetchall()
    return [_conversation_choice_from_row(row) for row in rows]


def get_conversation_choice_by_id(
    db_path: Path,
    organization_id: str,
    choice_id: int,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT cc.id,
                   cc.node_id,
                   cc.script_line_id,
                   cc.conditions_json,
                   cc.actions_json,
                   cc.next_node_id,
                   cc.end_conversation,
                   cc.sort_order,
                   cc.created_at,
                   cc.updated_at
            FROM conversation_choices cc
            JOIN conversation_nodes cn ON cn.id = cc.node_id
            JOIN conversations c ON c.id = cn.conversation_id
            WHERE cc.id = ?
              AND c.organization_id = ?
            """,
            (choice_id, organization_id),
        ).fetchone()
    return _conversation_choice_from_row(row) if row else None


def create_conversation_choice(
    db_path: Path,
    organization_id: str,
    node_id: int,
    script_line_id: int | None = None,
    conditions: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    next_node_id: int | None = None,
    end_conversation: bool = False,
    sort_order: int = 0,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO conversation_choices (
                node_id,
                script_line_id,
                conditions_json,
                actions_json,
                next_node_id,
                end_conversation,
                sort_order
            )
            SELECT ?, ?, ?, ?, ?, ?, ?
            WHERE EXISTS (
                SELECT 1
                FROM conversation_nodes cn
                JOIN conversations c ON c.id = cn.conversation_id
                WHERE cn.id = ?
                  AND c.organization_id = ?
            )
            """,
            (
                int(node_id),
                script_line_id if script_line_id is None else int(script_line_id),
                json.dumps(conditions or [], separators=(",", ":")),
                json.dumps(actions or [], separators=(",", ":")),
                next_node_id if next_node_id is None else int(next_node_id),
                int(bool(end_conversation)),
                int(sort_order),
                int(node_id),
                organization_id,
            ),
        )
    created = get_conversation_choice_by_id(db_path, organization_id, int(cursor.lastrowid))
    if created is None:
        raise RuntimeError("Created conversation choice could not be loaded")
    return created


def update_conversation_choice(
    db_path: Path,
    organization_id: str,
    choice_id: int,
    script_line_id: int | None = None,
    update_script_line_id: bool = False,
    conditions: list[dict[str, Any]] | None = None,
    update_conditions: bool = False,
    actions: list[dict[str, Any]] | None = None,
    update_actions: bool = False,
    next_node_id: int | None = None,
    update_next_node_id: bool = False,
    end_conversation: bool | None = None,
    sort_order: int | None = None,
) -> dict[str, Any] | None:
    assignments = ["updated_at = CURRENT_TIMESTAMP"]
    values: list[Any] = []
    if update_script_line_id:
        assignments.append("script_line_id = ?")
        values.append(script_line_id if script_line_id is None else int(script_line_id))
    if update_conditions:
        assignments.append("conditions_json = ?")
        values.append(json.dumps(conditions or [], separators=(",", ":")))
    if update_actions:
        assignments.append("actions_json = ?")
        values.append(json.dumps(actions or [], separators=(",", ":")))
    if update_next_node_id:
        assignments.append("next_node_id = ?")
        values.append(next_node_id if next_node_id is None else int(next_node_id))
    if end_conversation is not None:
        assignments.append("end_conversation = ?")
        values.append(int(bool(end_conversation)))
    if sort_order is not None:
        assignments.append("sort_order = ?")
        values.append(int(sort_order))
    with connect(db_path) as connection:
        cursor = connection.execute(
            f"""
            UPDATE conversation_choices
            SET {", ".join(assignments)}
            WHERE id = ?
              AND node_id IN (
                  SELECT cn.id
                  FROM conversation_nodes cn
                  JOIN conversations c ON c.id = cn.conversation_id
                  WHERE c.organization_id = ?
              )
            """,
            (*values, choice_id, organization_id),
        )
    if cursor.rowcount == 0:
        return None
    return get_conversation_choice_by_id(db_path, organization_id, choice_id)


def delete_conversation_choice(db_path: Path, organization_id: str, choice_id: int) -> bool:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            DELETE FROM conversation_choices
            WHERE id = ?
              AND node_id IN (
                  SELECT cn.id
                  FROM conversation_nodes cn
                  JOIN conversations c ON c.id = cn.conversation_id
                  WHERE c.organization_id = ?
              )
            """,
            (choice_id, organization_id),
        )
    return cursor.rowcount > 0


def list_character_images(
    db_path: Path,
    organization_id: str,
    character_id: int,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT character_images.*
            FROM character_images
            JOIN characters ON characters.id = character_images.character_id
            WHERE character_images.character_id = ?
              AND characters.organization_id = ?
            ORDER BY character_images.component_key ASC,
                     character_images.sort_order ASC,
                     character_images.id ASC
            """,
            (character_id, organization_id),
        ).fetchall()
    return [_character_image_from_row(row) for row in rows]


def get_character_image_by_id(
    db_path: Path,
    organization_id: str,
    image_id: int,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT character_images.*
            FROM character_images
            JOIN characters ON characters.id = character_images.character_id
            WHERE character_images.id = ?
              AND characters.organization_id = ?
            """,
            (image_id, organization_id),
        ).fetchone()
    return _character_image_from_row(row) if row else None


def upsert_character_image(
    db_path: Path,
    organization_id: str,
    character_id: int,
    component_key: str,
    variant_key: str,
    kind: str,
    source_group: str,
    source_name: str,
    relative_path: str,
    original_filename: str,
    width: int,
    height: int,
    is_default: bool,
    sort_order: int = 0,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        owner = connection.execute(
            "SELECT id FROM characters WHERE id = ? AND organization_id = ?",
            (character_id, organization_id),
        ).fetchone()
        if owner is None:
            raise ValueError("Character not found")
        if is_default:
            connection.execute(
                """
                UPDATE character_images
                SET is_default = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE character_id = ?
                  AND component_key = ?
                """,
                (character_id, component_key),
            )
        connection.execute(
            """
            INSERT INTO character_images (
                character_id,
                component_key,
                variant_key,
                kind,
                source_group,
                source_name,
                relative_path,
                original_filename,
                width,
                height,
                is_default,
                sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (character_id, component_key, variant_key)
            DO UPDATE SET
                kind = excluded.kind,
                source_group = excluded.source_group,
                source_name = excluded.source_name,
                relative_path = excluded.relative_path,
                original_filename = excluded.original_filename,
                width = excluded.width,
                height = excluded.height,
                is_default = excluded.is_default,
                sort_order = excluded.sort_order,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                character_id,
                component_key,
                variant_key,
                kind,
                source_group,
                source_name,
                relative_path,
                original_filename,
                int(width),
                int(height),
                int(bool(is_default)),
                int(sort_order),
            ),
        )
        row = connection.execute(
            """
            SELECT character_images.*
            FROM character_images
            JOIN characters ON characters.id = character_images.character_id
            WHERE character_images.character_id = ?
              AND character_images.component_key = ?
              AND character_images.variant_key = ?
              AND characters.organization_id = ?
            """,
            (character_id, component_key, variant_key, organization_id),
        ).fetchone()
    if row is None:
        raise RuntimeError("Character image could not be loaded")
    return _character_image_from_row(row)


def delete_character_image(db_path: Path, organization_id: str, image_id: int) -> bool:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT character_images.id
            FROM character_images
            JOIN characters ON characters.id = character_images.character_id
            WHERE character_images.id = ?
              AND characters.organization_id = ?
            """,
            (image_id, organization_id),
        ).fetchone()
        if row is None:
            return False
        connection.execute(
            "DELETE FROM character_animation_frames WHERE character_image_id = ?",
            (image_id,),
        )
        connection.execute("DELETE FROM character_object_masks WHERE character_image_id = ?", (image_id,))
        connection.execute("DELETE FROM character_images WHERE id = ?", (image_id,))
    return True


def list_character_objects(
    db_path: Path,
    organization_id: str,
    character_id: int,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT co.*,
                   COUNT(com.id) AS mask_count
            FROM character_objects co
            JOIN characters c ON c.id = co.character_id
            LEFT JOIN character_object_masks com ON com.character_object_id = co.id
            WHERE co.character_id = ?
              AND c.organization_id = ?
            GROUP BY co.id
            ORDER BY co.sort_order ASC, co.id ASC
            """,
            (character_id, organization_id),
        ).fetchall()
    return [_character_object_from_row(row) for row in rows]


def get_character_object_by_id(
    db_path: Path,
    organization_id: str,
    character_object_id: int,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT co.*,
                   COUNT(com.id) AS mask_count
            FROM character_objects co
            JOIN characters c ON c.id = co.character_id
            LEFT JOIN character_object_masks com ON com.character_object_id = co.id
            WHERE co.id = ?
              AND c.organization_id = ?
            GROUP BY co.id
            """,
            (character_object_id, organization_id),
        ).fetchone()
    return _character_object_from_row(row) if row else None


def create_character_object(
    db_path: Path,
    organization_id: str,
    character_id: int,
    name: str,
    description: str,
    prompt: str,
    sort_order: int,
    is_viseme_target: bool,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        owner = connection.execute(
            "SELECT id FROM characters WHERE id = ? AND organization_id = ?",
            (character_id, organization_id),
        ).fetchone()
        if owner is None:
            raise ValueError("Character not found")
        cursor = connection.execute(
            """
            INSERT INTO character_objects (
                character_id,
                name,
                description,
                prompt,
                sort_order,
                is_viseme_target
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                character_id,
                name.strip(),
                description,
                prompt,
                int(sort_order),
                int(bool(is_viseme_target)),
            ),
        )
    created = get_character_object_by_id(db_path, organization_id, int(cursor.lastrowid))
    if created is None:
        raise RuntimeError("Created character object could not be loaded")
    return created


def update_character_object(
    db_path: Path,
    organization_id: str,
    character_object_id: int,
    name: str | None = None,
    description: str | None = None,
    prompt: str | None = None,
    sort_order: int | None = None,
    is_viseme_target: bool | None = None,
) -> dict[str, Any] | None:
    assignments = ["updated_at = CURRENT_TIMESTAMP"]
    values: list[Any] = []
    if name is not None:
        assignments.append("name = ?")
        values.append(name.strip())
    if description is not None:
        assignments.append("description = ?")
        values.append(description)
    if prompt is not None:
        assignments.append("prompt = ?")
        values.append(prompt)
    if sort_order is not None:
        assignments.append("sort_order = ?")
        values.append(int(sort_order))
    if is_viseme_target is not None:
        assignments.append("is_viseme_target = ?")
        values.append(int(bool(is_viseme_target)))
    with connect(db_path) as connection:
        cursor = connection.execute(
            f"""
            UPDATE character_objects
            SET {", ".join(assignments)}
            WHERE id IN (
                SELECT co.id
                FROM character_objects co
                JOIN characters c ON c.id = co.character_id
                WHERE co.id = ?
                  AND c.organization_id = ?
            )
            """,
            (*values, character_object_id, organization_id),
        )
    if cursor.rowcount == 0:
        return None
    return get_character_object_by_id(db_path, organization_id, character_object_id)


def delete_character_object(db_path: Path, organization_id: str, character_object_id: int) -> bool:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT co.id
            FROM character_objects co
            JOIN characters c ON c.id = co.character_id
            WHERE co.id = ?
              AND c.organization_id = ?
            """,
            (character_object_id, organization_id),
        ).fetchone()
        if row is None:
            return False
        connection.execute("DELETE FROM character_object_masks WHERE character_object_id = ?", (character_object_id,))
        connection.execute("DELETE FROM character_objects WHERE id = ?", (character_object_id,))
    return True


def list_character_animations(
    db_path: Path,
    organization_id: str,
    character_id: int,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        animation_rows = connection.execute(
            """
            SELECT character_animations.*
            FROM character_animations
            JOIN characters ON characters.id = character_animations.character_id
            WHERE character_animations.character_id = ?
              AND characters.organization_id = ?
            ORDER BY lower(character_animations.name) ASC, character_animations.id ASC
            """,
            (character_id, organization_id),
        ).fetchall()
        frame_rows = connection.execute(
            """
            SELECT caf.*,
                   ci.component_key,
                   ci.variant_key,
                   ci.kind,
                   ci.relative_path,
                   ci.original_filename,
                   ci.width,
                   ci.height
            FROM character_animation_frames caf
            JOIN character_animations ca ON ca.id = caf.character_animation_id
            JOIN characters c ON c.id = ca.character_id
            JOIN character_images ci ON ci.id = caf.character_image_id
            WHERE ca.character_id = ?
              AND c.organization_id = ?
            ORDER BY caf.character_animation_id ASC, caf.sort_order ASC, caf.id ASC
            """,
            (character_id, organization_id),
        ).fetchall()
    frames_by_animation: dict[int, list[dict[str, Any]]] = {}
    for row in frame_rows:
        frame = dict(row)
        frames_by_animation.setdefault(int(frame["character_animation_id"]), []).append(frame)
    result = []
    for row in animation_rows:
        animation = _character_animation_from_row(row)
        animation["frames"] = [_character_animation_frame_from_row(frame) for frame in frames_by_animation.get(int(animation["id"]), [])]
        result.append(animation)
    return result


def get_character_animation_by_id(
    db_path: Path,
    organization_id: str,
    animation_id: int,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT character_animations.*
            FROM character_animations
            JOIN characters ON characters.id = character_animations.character_id
            WHERE character_animations.id = ?
              AND characters.organization_id = ?
            """,
            (animation_id, organization_id),
        ).fetchone()
    if row is None:
        return None
    animation = _character_animation_from_row(row)
    character_animations = list_character_animations(db_path, organization_id, int(animation["character_id"]))
    return next((item for item in character_animations if int(item["id"]) == int(animation_id)), None)


def create_character_animation(
    db_path: Path,
    organization_id: str,
    character_id: int,
    name: str,
    frames: list[dict[str, Any]],
) -> dict[str, Any]:
    with connect(db_path) as connection:
        owner = connection.execute(
            "SELECT id FROM characters WHERE id = ? AND organization_id = ?",
            (character_id, organization_id),
        ).fetchone()
        if owner is None:
            raise ValueError("Character not found")
        cursor = connection.execute(
            """
            INSERT INTO character_animations (character_id, name)
            VALUES (?, ?)
            """,
            (character_id, name.strip()),
        )
        animation_id = int(cursor.lastrowid)
        _replace_character_animation_frames(connection, animation_id, character_id, frames)
    created = get_character_animation_by_id(db_path, organization_id, animation_id)
    if created is None:
        raise RuntimeError("Character animation could not be loaded")
    return created


def update_character_animation(
    db_path: Path,
    organization_id: str,
    animation_id: int,
    name: str,
    frames: list[dict[str, Any]],
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT character_animations.id,
                   character_animations.character_id
            FROM character_animations
            JOIN characters ON characters.id = character_animations.character_id
            WHERE character_animations.id = ?
              AND characters.organization_id = ?
            """,
            (animation_id, organization_id),
        ).fetchone()
        if row is None:
            return None
        connection.execute(
            """
            UPDATE character_animations
            SET name = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (name.strip(), animation_id),
        )
        _replace_character_animation_frames(connection, animation_id, int(row["character_id"]), frames)
    return get_character_animation_by_id(db_path, organization_id, animation_id)


def delete_character_animation(db_path: Path, organization_id: str, animation_id: int) -> bool:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT character_animations.id
            FROM character_animations
            JOIN characters ON characters.id = character_animations.character_id
            WHERE character_animations.id = ?
              AND characters.organization_id = ?
            """,
            (animation_id, organization_id),
        ).fetchone()
        if row is None:
            return False
        connection.execute("DELETE FROM character_animation_frames WHERE character_animation_id = ?", (animation_id,))
        connection.execute("DELETE FROM character_animations WHERE id = ?", (animation_id,))
    return True


def replace_script_audio_candidate_viseme_events(
    db_path: Path,
    organization_id: str,
    candidate_id: int,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        candidate = _get_audio_candidate_row(connection, organization_id, candidate_id)
        if candidate is None:
            raise ValueError("Audio candidate not found")
        connection.execute(
            "DELETE FROM script_audio_candidate_viseme_events WHERE script_audio_candidate_id = ?",
            (candidate_id,),
        )
        for index, event in enumerate(events):
            connection.execute(
                """
                INSERT INTO script_audio_candidate_viseme_events (
                    script_audio_candidate_id,
                    viseme_key,
                    start_seconds,
                    end_seconds,
                    sort_order
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    str(event.get("viseme_key") or "").strip(),
                    float(event.get("start_seconds") or 0),
                    float(event.get("end_seconds") or 0),
                    index,
                ),
            )
    return list_script_audio_candidate_viseme_events(db_path, organization_id, candidate_id)


def list_script_audio_candidate_viseme_events(
    db_path: Path,
    organization_id: str,
    candidate_id: int,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        candidate = _get_audio_candidate_row(connection, organization_id, candidate_id)
        if candidate is None:
            return []
        rows = connection.execute(
            """
            SELECT *
            FROM script_audio_candidate_viseme_events
            WHERE script_audio_candidate_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (candidate_id,),
        ).fetchall()
    return [_script_audio_candidate_viseme_event_from_row(row) for row in rows]


def _replace_character_animation_frames(
    connection: sqlite3.Connection,
    animation_id: int,
    character_id: int,
    frames: list[dict[str, Any]],
) -> None:
    connection.execute("DELETE FROM character_animation_frames WHERE character_animation_id = ?", (animation_id,))
    for index, frame in enumerate(frames or []):
        image_id = int(frame["character_image_id"])
        image_row = connection.execute(
            """
            SELECT id
            FROM character_images
            WHERE id = ?
              AND character_id = ?
            """,
            (image_id, character_id),
        ).fetchone()
        if image_row is None:
            raise ValueError("Character animation frame image does not belong to this character")
        connection.execute(
            """
            INSERT INTO character_animation_frames (
                character_animation_id,
                character_image_id,
                duration_seconds,
                sort_order
            )
            VALUES (?, ?, ?, ?)
            """,
            (animation_id, image_id, float(frame["duration_seconds"]), index),
        )


def get_global_settings(db_path: Path, organization_id: str, project_id: int | None = None) -> dict[str, Any]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        row = connection.execute(
            """
            SELECT organization_id,
                   project_id,
                   overlay_open_duration_seconds,
                   overlay_close_duration_seconds,
                   overlay_fade_color,
                   overlay_affect_audio,
                   start_scene_id,
                   inventory_key_code,
                   verb_menu_timeout_seconds,
                   verb_menu_show_disabled,
                   verb_text_color,
                   inventory_slots_json,
                   inventory_background_relative_path,
                   verb_tag_background_relative_path,
                   cursor_default_relative_path,
                   cursor_default_hotspot_x,
                   cursor_default_hotspot_y,
                   cursor_hover_interactive_relative_path,
                   cursor_hover_interactive_hotspot_x,
                   cursor_hover_interactive_hotspot_y,
                   cursor_busy_relative_path,
                   cursor_busy_hotspot_x,
                   cursor_busy_hotspot_y,
                   cursor_blocked_relative_path,
                   cursor_blocked_hotspot_x,
                   cursor_blocked_hotspot_y,
                   created_at,
                   updated_at
            FROM global_settings
            WHERE organization_id = ?
              AND project_id = ?
            """,
            (organization_id, project_id),
        ).fetchone()
        if row is None:
            connection.execute(
                """
                INSERT INTO global_settings (organization_id, project_id)
                VALUES (?, ?)
                """,
                (organization_id, project_id),
            )
            row = connection.execute(
                """
                SELECT organization_id,
                       project_id,
                       overlay_open_duration_seconds,
                       overlay_close_duration_seconds,
                       overlay_fade_color,
                       overlay_affect_audio,
                       start_scene_id,
                       inventory_key_code,
                       verb_menu_timeout_seconds,
                       verb_menu_show_disabled,
                       verb_text_color,
                       inventory_slots_json,
                       inventory_background_relative_path,
                       verb_tag_background_relative_path,
                       cursor_default_relative_path,
                       cursor_default_hotspot_x,
                       cursor_default_hotspot_y,
                       cursor_hover_interactive_relative_path,
                       cursor_hover_interactive_hotspot_x,
                       cursor_hover_interactive_hotspot_y,
                       cursor_busy_relative_path,
                       cursor_busy_hotspot_x,
                       cursor_busy_hotspot_y,
                       cursor_blocked_relative_path,
                       cursor_blocked_hotspot_x,
                       cursor_blocked_hotspot_y,
                       created_at,
                       updated_at
                FROM global_settings
                WHERE organization_id = ?
                  AND project_id = ?
                """,
                (organization_id, project_id),
            ).fetchone()
    result = dict(row)
    result["overlay_affect_audio"] = bool(result["overlay_affect_audio"])
    result["verb_menu_show_disabled"] = bool(result.get("verb_menu_show_disabled", 1))
    result["inventory_slots"] = _json_loads(result.pop("inventory_slots_json", "[]"), [])
    result["cursor_states"] = _extract_cursor_states(result)
    return result


def update_global_settings(
    db_path: Path,
    organization_id: str,
    project_id: int | None = None,
    overlay_open_duration_seconds: float | None = None,
    overlay_close_duration_seconds: float | None = None,
    overlay_fade_color: str | None = None,
    overlay_affect_audio: bool | None = None,
    start_scene_id: int | None = None,
    inventory_key_code: str | None = None,
    verb_menu_timeout_seconds: float | None = None,
    verb_menu_show_disabled: bool | None = None,
    verb_text_color: str | None = None,
    inventory_slots: list[dict[str, Any]] | None = None,
    inventory_background_relative_path: str | None = None,
    verb_tag_background_relative_path: str | None = None,
    cursor_states: dict[str, dict[str, Any]] | None = None,
    update_start_scene_id: bool = False,
    update_inventory_background_relative_path: bool = False,
    update_verb_tag_background_relative_path: bool = False,
) -> dict[str, Any]:
    current_settings = get_global_settings(db_path, organization_id, project_id)
    assignments = ["updated_at = CURRENT_TIMESTAMP"]
    values: list[Any] = []
    if overlay_open_duration_seconds is not None:
        assignments.append("overlay_open_duration_seconds = ?")
        values.append(float(overlay_open_duration_seconds))
    if overlay_close_duration_seconds is not None:
        assignments.append("overlay_close_duration_seconds = ?")
        values.append(float(overlay_close_duration_seconds))
    if overlay_fade_color is not None:
        assignments.append("overlay_fade_color = ?")
        values.append(str(overlay_fade_color))
    if overlay_affect_audio is not None:
        assignments.append("overlay_affect_audio = ?")
        values.append(int(bool(overlay_affect_audio)))
    if update_start_scene_id:
        assignments.append("start_scene_id = ?")
        values.append(start_scene_id if start_scene_id is None else int(start_scene_id))
    if inventory_key_code is not None:
        assignments.append("inventory_key_code = ?")
        values.append(inventory_key_code)
    if verb_menu_timeout_seconds is not None:
        assignments.append("verb_menu_timeout_seconds = ?")
        values.append(float(verb_menu_timeout_seconds))
    if verb_menu_show_disabled is not None:
        assignments.append("verb_menu_show_disabled = ?")
        values.append(int(bool(verb_menu_show_disabled)))
    if verb_text_color is not None:
        assignments.append("verb_text_color = ?")
        values.append(str(verb_text_color))
    if inventory_slots is not None:
        assignments.append("inventory_slots_json = ?")
        values.append(json_dumps(inventory_slots))
    if update_inventory_background_relative_path:
        assignments.append("inventory_background_relative_path = ?")
        values.append(inventory_background_relative_path)
    if update_verb_tag_background_relative_path:
        assignments.append("verb_tag_background_relative_path = ?")
        values.append(verb_tag_background_relative_path)
    if cursor_states is not None:
        normalized_cursor_states = _merge_cursor_states(current_settings.get("cursor_states"), cursor_states)
        for state_key in CURSOR_STATE_KEYS:
            state = normalized_cursor_states[state_key]
            assignments.append(f"cursor_{state_key}_relative_path = ?")
            values.append(state.get("relative_path"))
            assignments.append(f"cursor_{state_key}_hotspot_x = ?")
            values.append(int(state.get("hotspot_x") or 0))
            assignments.append(f"cursor_{state_key}_hotspot_y = ?")
            values.append(int(state.get("hotspot_y") or 0))
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        connection.execute(
            f"""
            UPDATE global_settings
            SET {", ".join(assignments)}
            WHERE organization_id = ?
              AND project_id = ?
            """,
            (*values, organization_id, project_id),
        )
    return get_global_settings(db_path, organization_id, project_id)


def _extract_cursor_states(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cursor_states = _merge_cursor_states(None, None)
    for state_key in CURSOR_STATE_KEYS:
        cursor_states[state_key] = {
            "relative_path": result.pop(f"cursor_{state_key}_relative_path", None),
            "hotspot_x": int(result.pop(f"cursor_{state_key}_hotspot_x", 0) or 0),
            "hotspot_y": int(result.pop(f"cursor_{state_key}_hotspot_y", 0) or 0),
        }
    return cursor_states


def _merge_cursor_states(
    existing_states: dict[str, dict[str, Any]] | None,
    incoming_states: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    merged = {
        state_key: {
            "relative_path": DEFAULT_CURSOR_STATES[state_key]["relative_path"],
            "hotspot_x": DEFAULT_CURSOR_STATES[state_key]["hotspot_x"],
            "hotspot_y": DEFAULT_CURSOR_STATES[state_key]["hotspot_y"],
        }
        for state_key in CURSOR_STATE_KEYS
    }
    for state_key, state in (existing_states or {}).items():
        if state_key not in merged or not isinstance(state, dict):
            continue
        merged[state_key]["relative_path"] = state.get("relative_path") or None
        merged[state_key]["hotspot_x"] = int(state.get("hotspot_x") or 0)
        merged[state_key]["hotspot_y"] = int(state.get("hotspot_y") or 0)
    for state_key, state in (incoming_states or {}).items():
        if state_key not in merged or not isinstance(state, dict):
            continue
        if "relative_path" in state:
            merged[state_key]["relative_path"] = state.get("relative_path") or None
        if "hotspot_x" in state:
            merged[state_key]["hotspot_x"] = int(state.get("hotspot_x") or 0)
        if "hotspot_y" in state:
            merged[state_key]["hotspot_y"] = int(state.get("hotspot_y") or 0)
    return merged


def create_or_update_overlay_scene_binding(
    db_path: Path,
    organization_id: str,
    project_id: int | None,
    key_code: str,
    overlay_scene_id: int,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        connection.execute(
            """
            INSERT INTO overlay_scene_bindings (
                organization_id,
                project_id,
                key_code,
                overlay_scene_id
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT (organization_id, project_id, key_code) DO UPDATE SET
                overlay_scene_id = excluded.overlay_scene_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (organization_id, project_id, key_code, overlay_scene_id),
        )
    row = get_overlay_scene_binding_by_key(db_path, organization_id, key_code, project_id)
    if row is None:
        raise RuntimeError("Overlay scene binding could not be loaded")
    return row


def get_overlay_scene_binding_by_key(
    db_path: Path,
    organization_id: str,
    key_code: str,
    project_id: int | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        row = connection.execute(
            """
            SELECT overlay_scene_bindings.id,
                   overlay_scene_bindings.organization_id,
                   overlay_scene_bindings.project_id,
                   overlay_scene_bindings.key_code,
                   overlay_scene_bindings.overlay_scene_id,
                   overlay_scene_bindings.created_at,
                   overlay_scene_bindings.updated_at,
                   scenes.title AS overlay_scene_title,
                   scenes.presentation_mode AS overlay_scene_presentation_mode
            FROM overlay_scene_bindings
            JOIN scenes ON scenes.id = overlay_scene_bindings.overlay_scene_id
            WHERE overlay_scene_bindings.organization_id = ?
              AND overlay_scene_bindings.project_id = ?
              AND overlay_scene_bindings.key_code = ?
            """,
            (organization_id, project_id, key_code),
        ).fetchone()
    return dict(row) if row else None


def delete_overlay_scene_binding(
    db_path: Path,
    organization_id: str,
    binding_id: int,
    project_id: int | None = None,
) -> None:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        connection.execute(
            """
            DELETE FROM overlay_scene_bindings
            WHERE id = ?
              AND organization_id = ?
              AND project_id = ?
            """,
            (binding_id, organization_id, project_id),
        )


def upsert_script_line(
    db_path: Path,
    organization_id: str,
    project_id: int | None,
    line_id: int,
    script_index: int,
    source_text: str,
    path_parts: list[str],
) -> dict[str, Any]:
    path_json = json.dumps(path_parts, ensure_ascii=False)
    path_text = " / ".join(path_parts)
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        connection.execute(
            """
            INSERT INTO script_lines (
                organization_id,
                project_id,
                line_id,
                script_index,
                source_text,
                path_json,
                path_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (organization_id, project_id, line_id) DO UPDATE SET
                script_index = excluded.script_index,
                source_text = excluded.source_text,
                path_json = excluded.path_json,
                path_text = excluded.path_text,
                updated_at = CURRENT_TIMESTAMP
            """,
            (organization_id, project_id, line_id, script_index, source_text, path_json, path_text),
        )
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   project_id,
                   line_id,
                   script_index,
                   source_text,
                   path_json,
                   path_text,
                   created_at,
                   updated_at
            FROM script_lines
            WHERE organization_id = ?
              AND project_id = ?
              AND line_id = ?
            """,
            (organization_id, project_id, line_id),
        ).fetchone()
    return dict(row)


def get_next_script_line_id(db_path: Path, organization_id: str, project_id: int | None = None) -> int:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        row = connection.execute(
            """
            SELECT COALESCE(MAX(line_id), 0) + 1 AS next_line_id
            FROM script_lines
            WHERE organization_id = ?
              AND project_id = ?
            """,
            (organization_id, project_id),
        ).fetchone()
    return int(row["next_line_id"] if row else 1)


def create_script_line(
    db_path: Path,
    organization_id: str,
    project_id: int | None,
    source_text: str,
    path_parts: list[str],
) -> dict[str, Any]:
    line_id = get_next_script_line_id(db_path, organization_id, project_id)
    return upsert_script_line(
        db_path,
        organization_id=organization_id,
        project_id=project_id,
        line_id=line_id,
        script_index=line_id,
        source_text=source_text,
        path_parts=path_parts,
    )


def upsert_script_translation(
    db_path: Path,
    organization_id: str,
    line_id: int,
    language: str,
    text: str,
    source: str,
    meta: dict[str, Any] | None = None,
    review_status: str = "needs_review",
) -> dict[str, Any] | None:
    meta_json = json_dumps(meta or {})
    with connect(db_path) as connection:
        line = _get_script_line_row(connection, organization_id, line_id)
        if line is None:
            return None
        connection.execute(
            """
            INSERT INTO script_translations (
                script_line_id,
                language,
                text,
                source,
                review_status,
                meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (script_line_id, language) DO UPDATE SET
                text = CASE
                    WHEN script_translations.manually_edited = 0 THEN excluded.text
                    ELSE script_translations.text
                END,
                source = CASE
                    WHEN script_translations.manually_edited = 0 THEN excluded.source
                    ELSE script_translations.source
                END,
                meta_json = CASE
                    WHEN script_translations.manually_edited = 0 THEN excluded.meta_json
                    ELSE script_translations.meta_json
                END,
                updated_at = CURRENT_TIMESTAMP
            """,
            (line["id"], language, text, source, review_status, meta_json),
        )
        row = connection.execute(
            """
            SELECT id,
                   script_line_id,
                   language,
                   text,
                   source,
                   review_status,
                   notes,
                   manually_edited,
                   meta_json,
                   created_at,
                   updated_at
            FROM script_translations
            WHERE script_line_id = ?
              AND language = ?
            """,
            (line["id"], language),
        ).fetchone()
    return dict(row) if row else None


def upsert_script_audio_candidate(
    db_path: Path,
    organization_id: str,
    line_id: int,
    language: str,
    source_type: str,
    manifest_status: str,
    relative_path: str,
    original_path: str,
    rank: int | None = None,
    score: float | None = None,
    text_score: float | None = None,
    quality_score: float | None = None,
    duration_seconds: float | None = None,
    transcript_match: str = "",
    notes: str = "",
    error: str = "",
    source_file: str = "",
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    review_status: str = "needs_review",
) -> dict[str, Any] | None:
    normalized_rank = rank if rank is not None else -1
    with connect(db_path) as connection:
        line = _get_script_line_row(connection, organization_id, line_id)
        if line is None:
            return None
        connection.execute(
            """
            INSERT INTO script_audio_candidates (
                script_line_id,
                language,
                source_type,
                manifest_status,
                review_status,
                relative_path,
                original_path,
                rank,
                score,
                text_score,
                quality_score,
                duration_seconds,
                transcript_match,
                notes,
                error,
                source_file,
                start_seconds,
                end_seconds
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (script_line_id, language, source_type, original_path, rank)
            DO UPDATE SET
                manifest_status = excluded.manifest_status,
                relative_path = excluded.relative_path,
                score = excluded.score,
                text_score = excluded.text_score,
                quality_score = excluded.quality_score,
                duration_seconds = excluded.duration_seconds,
                transcript_match = excluded.transcript_match,
                error = excluded.error,
                source_file = excluded.source_file,
                start_seconds = excluded.start_seconds,
                end_seconds = excluded.end_seconds,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                line["id"],
                language,
                source_type,
                manifest_status,
                review_status,
                relative_path,
                original_path,
                normalized_rank,
                score,
                text_score,
                quality_score,
                duration_seconds,
                transcript_match,
                notes,
                error,
                source_file,
                start_seconds,
                end_seconds,
            ),
        )
        row = connection.execute(
            """
            SELECT *
            FROM script_audio_candidates
            WHERE script_line_id = ?
              AND language = ?
              AND source_type = ?
              AND original_path = ?
              AND rank = ?
            """,
            (line["id"], language, source_type, original_path, normalized_rank),
        ).fetchone()
    return dict(row) if row else None


def _build_script_line_filter_clause(
    *,
    organization_id: str,
    project_id: int | None,
    language: str,
    query: str,
    path: str,
    translation_status: str,
    audio_status: str,
    audio_source: str,
    missing_audio: bool,
    missing_translation: bool,
    failed_tts: bool,
) -> tuple[str, list[Any]]:
    where = ["sl.organization_id = ?"]
    values: list[Any] = [organization_id]
    if project_id is not None:
        where.append("sl.project_id = ?")
        values.append(project_id)
    if query:
        like = f"%{query}%"
        where.append(
            """
            (
                sl.source_text LIKE ?
                OR sl.path_text LIKE ?
                OR EXISTS (
                    SELECT 1
                    FROM script_translations qst
                    WHERE qst.script_line_id = sl.id
                      AND qst.text LIKE ?
                )
            )
            """
        )
        values.extend([like, like, like])
    if path:
        where.append("sl.path_text LIKE ?")
        values.append(f"{path}%")
    if translation_status:
        where.append(
            """
            EXISTS (
                SELECT 1
                FROM script_translations fst
                WHERE fst.script_line_id = sl.id
                  AND fst.language = ?
                  AND fst.review_status = ?
            )
            """
        )
        values.extend([language, translation_status])
    if audio_status:
        where.append(
            """
            EXISTS (
                SELECT 1
                FROM script_audio_candidates fac
                WHERE fac.script_line_id = sl.id
                  AND fac.language = ?
                  AND fac.review_status = ?
            )
            """
        )
        values.extend([language, audio_status])
    if audio_source:
        where.append(
            """
            EXISTS (
                SELECT 1
                FROM script_audio_candidates fsrc
                WHERE fsrc.script_line_id = sl.id
                  AND fsrc.language = ?
                  AND fsrc.source_type = ?
            )
            """
        )
        values.extend([language, audio_source])
    if missing_audio:
        where.append(
            """
            NOT EXISTS (
                SELECT 1
                FROM script_audio_candidates mac
                WHERE mac.script_line_id = sl.id
                  AND mac.language = ?
                  AND mac.relative_path != ''
                  AND mac.manifest_status != 'error'
            )
            """
        )
        values.append(language)
    if missing_translation:
        where.append(
            """
            NOT EXISTS (
                SELECT 1
                FROM script_translations mt
                WHERE mt.script_line_id = sl.id
                  AND mt.language = ?
                  AND TRIM(COALESCE(mt.text, '')) != ''
            )
            """
        )
        values.append(language)
    if failed_tts:
        where.append(
            """
            EXISTS (
                SELECT 1
                FROM script_audio_candidates ft
                WHERE ft.script_line_id = sl.id
                  AND ft.language = ?
                  AND ft.source_type = 'tts'
                  AND ft.manifest_status = 'error'
            )
            """
        )
        values.append(language)
    return " AND ".join(where), values


def list_script_lines(
    db_path: Path,
    organization_id: str,
    project_id: int | None = None,
    language: str = "en",
    query: str = "",
    path: str = "",
    translation_status: str = "",
    audio_status: str = "",
    audio_source: str = "",
    missing_audio: bool = False,
    missing_translation: bool = False,
    failed_tts: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
    where_sql, values = _build_script_line_filter_clause(
        organization_id=organization_id,
        project_id=project_id,
        language=language,
        query=query,
        path=path,
        translation_status=translation_status,
        audio_status=audio_status,
        audio_source=audio_source,
        missing_audio=missing_audio,
        missing_translation=missing_translation,
        failed_tts=failed_tts,
    )
    normalized_query = query.strip().lower()
    order_sql = _build_script_line_order_sql(bool(normalized_query))
    order_values = _build_script_line_order_values(normalized_query)
    with connect(db_path) as connection:
        total_row = connection.execute(
            f"SELECT COUNT(*) AS count FROM script_lines sl WHERE {where_sql}",
            values,
        ).fetchone()
        rows = connection.execute(
            f"""
            SELECT sl.id,
                   sl.organization_id,
                   sl.project_id,
                   sl.line_id,
                   sl.script_index,
                   sl.source_text,
                   sl.path_json,
                   sl.path_text,
                   sl.created_at,
                   sl.updated_at,
                   st.id AS selected_translation_id,
                   st.text AS selected_translation_text,
                   st.source AS selected_translation_source,
                   st.review_status AS selected_translation_status,
                   st.notes AS selected_translation_notes,
                   st.manually_edited AS selected_translation_manually_edited,
                   CASE
                       WHEN st.id IS NOT NULL AND TRIM(COALESCE(st.text, '')) != '' THEN 1
                       ELSE 0
                   END AS translation_present,
                   (
                       SELECT COUNT(*)
                       FROM script_audio_candidates sac
                       WHERE sac.script_line_id = sl.id
                         AND sac.language = ?
                         AND sac.relative_path != ''
                         AND sac.manifest_status != 'error'
                   ) AS audio_candidate_count
                   ,
                   (
                       SELECT COUNT(*)
                       FROM script_audio_candidates tts
                       WHERE tts.script_line_id = sl.id
                         AND tts.language = ?
                         AND tts.source_type = 'tts'
                         AND tts.relative_path != ''
                         AND tts.manifest_status != 'error'
                   ) AS tts_audio_count,
                   (
                       SELECT COUNT(*)
                       FROM script_audio_candidates reviewed
                       WHERE reviewed.script_line_id = sl.id
                         AND reviewed.language = ?
                         AND reviewed.source_type != 'tts'
                         AND reviewed.relative_path != ''
                         AND reviewed.manifest_status != 'error'
                   ) AS reviewed_audio_count,
                   (
                       SELECT COUNT(*)
                       FROM script_audio_candidates selected_audio
                       WHERE selected_audio.script_line_id = sl.id
                         AND selected_audio.language = ?
                         AND selected_audio.selected = 1
                         AND selected_audio.relative_path != ''
                         AND selected_audio.manifest_status != 'error'
                   ) AS selected_audio_count,
                   (
                       SELECT COUNT(*)
                       FROM script_audio_candidates failed
                       WHERE failed.script_line_id = sl.id
                         AND failed.language = ?
                         AND failed.source_type = 'tts'
                         AND failed.manifest_status = 'error'
                   ) AS failed_tts_count
            FROM script_lines sl
            LEFT JOIN script_translations st
              ON st.script_line_id = sl.id
             AND st.language = ?
            WHERE {where_sql}
            {order_sql}
            LIMIT ?
            OFFSET ?
            """,
            [language, language, language, language, language, language, *values, *order_values, limit, offset],
        ).fetchall()

    return {
        "items": [_script_line_summary_from_row(row, language) for row in rows],
        "total": int(total_row["count"] if total_row else 0),
        "limit": limit,
        "offset": offset,
    }


def list_script_line_ids(
    db_path: Path,
    organization_id: str,
    project_id: int | None = None,
    language: str = "en",
    query: str = "",
    path: str = "",
    translation_status: str = "",
    audio_status: str = "",
    audio_source: str = "",
    missing_audio: bool = False,
    missing_translation: bool = False,
    failed_tts: bool = False,
    limit: int = 5000,
) -> list[int]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
    where_sql, values = _build_script_line_filter_clause(
        organization_id=organization_id,
        project_id=project_id,
        language=language,
        query=query,
        path=path,
        translation_status=translation_status,
        audio_status=audio_status,
        audio_source=audio_source,
        missing_audio=missing_audio,
        missing_translation=missing_translation,
        failed_tts=failed_tts,
    )
    normalized_query = query.strip().lower()
    order_sql = _build_script_line_order_sql(bool(normalized_query))
    order_values = _build_script_line_order_values(normalized_query)
    with connect(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT sl.line_id
            FROM script_lines sl
            WHERE {where_sql}
            {order_sql}
            LIMIT ?
            """,
            [*values, *order_values, max(1, limit)],
        ).fetchall()
    return [int(row["line_id"]) for row in rows]


def _build_script_line_order_sql(has_query: bool) -> str:
    if not has_query:
        return "ORDER BY sl.line_id ASC"
    return """
        ORDER BY
            CASE
                WHEN LOWER(sl.source_text) = ? THEN 0
                WHEN EXISTS (
                    SELECT 1
                    FROM script_translations st_exact
                    WHERE st_exact.script_line_id = sl.id
                      AND LOWER(TRIM(COALESCE(st_exact.text, ''))) = ?
                ) THEN 1
                WHEN LOWER(sl.source_text) LIKE ? THEN 2
                WHEN EXISTS (
                    SELECT 1
                    FROM script_translations st_prefix
                    WHERE st_prefix.script_line_id = sl.id
                      AND LOWER(TRIM(COALESCE(st_prefix.text, ''))) LIKE ?
                ) THEN 3
                WHEN INSTR(LOWER(sl.source_text), ?) > 0 THEN 4
                WHEN EXISTS (
                    SELECT 1
                    FROM script_translations st_contains
                    WHERE st_contains.script_line_id = sl.id
                      AND INSTR(LOWER(COALESCE(st_contains.text, '')), ?) > 0
                ) THEN 5
                WHEN LOWER(sl.path_text) LIKE ? THEN 6
                WHEN INSTR(LOWER(sl.path_text), ?) > 0 THEN 7
                ELSE 8
            END ASC,
            ABS(LENGTH(sl.source_text) - ?) ASC,
            LENGTH(sl.source_text) ASC,
            sl.line_id DESC
    """


def _build_script_line_order_values(normalized_query: str) -> list[Any]:
    if not normalized_query:
        return []
    return [
        normalized_query,
        normalized_query,
        f"{normalized_query}%",
        f"{normalized_query}%",
        normalized_query,
        normalized_query,
        f"{normalized_query}%",
        normalized_query,
        len(normalized_query),
    ]


def get_script_line_detail(
    db_path: Path,
    organization_id: str,
    line_id: int,
    project_id: int | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        line = _get_script_line_row(connection, organization_id, line_id, project_id)
        if line is None:
            return None
        translations = connection.execute(
            """
            SELECT id,
                   script_line_id,
                   language,
                   text,
                   source,
                   review_status,
                   notes,
                   manually_edited,
                   meta_json,
                   created_at,
                   updated_at
            FROM script_translations
            WHERE script_line_id = ?
            ORDER BY language ASC
            """,
            (line["id"],),
        ).fetchall()
        audio_candidates = connection.execute(
            """
            SELECT sac.*,
                   COALESCE((
                       SELECT json_group_array(json_object(
                           'id', save.id,
                           'script_audio_candidate_id', save.script_audio_candidate_id,
                           'viseme_key', save.viseme_key,
                           'start_seconds', save.start_seconds,
                           'end_seconds', save.end_seconds,
                           'sort_order', save.sort_order,
                           'created_at', save.created_at
                       ))
                       FROM script_audio_candidate_viseme_events save
                       WHERE save.script_audio_candidate_id = sac.id
                       ORDER BY save.sort_order ASC, save.id ASC
                   ), '[]') AS viseme_events_json
            FROM script_audio_candidates sac
            WHERE sac.script_line_id = ?
            ORDER BY language ASC,
                     source_type ASC,
                     CASE WHEN rank < 0 THEN 999 ELSE rank END ASC,
                     id ASC
            """,
            (line["id"],),
        ).fetchall()

    return {
        **dict(line),
        "path_parts": _json_loads(line["path_json"], []),
        "translations": [_translation_from_row(row) for row in translations],
        "audio_candidates": [_audio_candidate_from_row(row) for row in audio_candidates],
        "usage_references": list_script_line_references(db_path, organization_id, line_id),
    }


def list_script_path_options(
    db_path: Path,
    organization_id: str,
    project_id: int | None = None,
    limit: int = 500,
) -> list[str]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        rows = connection.execute(
            """
            SELECT DISTINCT path_text
            FROM script_lines
            WHERE organization_id = ?
              AND project_id = ?
              AND path_text != ''
            ORDER BY path_text ASC
            LIMIT ?
            """,
            (organization_id, project_id, limit),
        ).fetchall()
    return [str(row["path_text"]) for row in rows]


def update_script_translation(
    db_path: Path,
    organization_id: str,
    line_id: int,
    language: str,
    text: str,
    review_status: str,
    notes: str = "",
    project_id: int | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        line = _get_script_line_row(connection, organization_id, line_id, project_id)
        if line is None:
            return None
        connection.execute(
            """
            INSERT INTO script_translations (
                script_line_id,
                language,
                text,
                source,
                review_status,
                notes,
                manually_edited
            )
            VALUES (?, ?, ?, 'manual', ?, ?, 1)
            ON CONFLICT (script_line_id, language) DO UPDATE SET
                text = excluded.text,
                source = 'manual',
                review_status = excluded.review_status,
                notes = excluded.notes,
                manually_edited = 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (line["id"], language, text, review_status, notes),
        )
        row = connection.execute(
            """
            SELECT id,
                   script_line_id,
                   language,
                   text,
                   source,
                   review_status,
                   notes,
                   manually_edited,
                   meta_json,
                   created_at,
                   updated_at
            FROM script_translations
            WHERE script_line_id = ?
              AND language = ?
            """,
            (line["id"], language),
        ).fetchone()
    return _translation_from_row(row) if row else None


def update_script_translation_review(
    db_path: Path,
    organization_id: str,
    line_id: int,
    language: str,
    review_status: str,
    notes: str = "",
    project_id: int | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        line = _get_script_line_row(connection, organization_id, line_id, project_id)
        if line is None:
            return None
        connection.execute(
            """
            UPDATE script_translations
            SET review_status = ?,
                notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE script_line_id = ?
              AND language = ?
            """,
            (review_status, notes, line["id"], language),
        )
        row = connection.execute(
            """
            SELECT id,
                   script_line_id,
                   language,
                   text,
                   source,
                   review_status,
                   notes,
                   manually_edited,
                   meta_json,
                   created_at,
                   updated_at
            FROM script_translations
            WHERE script_line_id = ?
              AND language = ?
            """,
            (line["id"], language),
        ).fetchone()
    return _translation_from_row(row) if row else None


def update_script_audio_candidate(
    db_path: Path,
    organization_id: str,
    candidate_id: int,
    review_status: str,
    notes: str = "",
    selected: bool | None = None,
    project_id: int | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        candidate = _get_audio_candidate_row(connection, organization_id, candidate_id, project_id)
        if candidate is None:
            return None
        connection.execute(
            """
            UPDATE script_audio_candidates
            SET review_status = ?,
                notes = ?,
                selected = COALESCE(?, selected),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (review_status, notes, int(selected) if selected is not None else None, candidate_id),
        )
        row = _get_audio_candidate_row(connection, organization_id, candidate_id, project_id)
    return _audio_candidate_from_row(row) if row else None


def delete_script_line(
    db_path: Path,
    organization_id: str,
    line_id: int,
    project_id: int | None = None,
) -> bool:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        line = _get_script_line_row(connection, organization_id, line_id, project_id)
        if line is None:
            return False
        connection.execute(
            """
            DELETE FROM script_audio_candidate_viseme_events
            WHERE script_audio_candidate_id IN (
                SELECT id
                FROM script_audio_candidates
                WHERE script_line_id = ?
            )
            """,
            (line["id"],),
        )
        connection.execute(
            "DELETE FROM script_audio_candidates WHERE script_line_id = ?",
            (line["id"],),
        )
        connection.execute(
            "DELETE FROM script_translations WHERE script_line_id = ?",
            (line["id"],),
        )
        connection.execute(
            """
            DELETE FROM script_lines
            WHERE id = ?
              AND organization_id = ?
              AND project_id = ?
            """,
            (line["id"], organization_id, project_id),
        )
    return True


def get_script_audio_candidate_by_id(
    db_path: Path,
    organization_id: str,
    candidate_id: int,
    project_id: int | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        row = _get_audio_candidate_row(connection, organization_id, candidate_id, project_id)
    return _audio_candidate_from_row(row) if row else None


def list_game_variables(db_path: Path, organization_id: str, project_id: int | None = None) -> list[dict[str, Any]]:
    ensure_system_game_variables(db_path, organization_id)
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        rows = connection.execute(
            """
            SELECT id,
                   organization_id,
                   project_id,
                   name,
                   value_type,
                   default_value_json,
                   description,
                   created_at,
                   updated_at
            FROM game_variables
            WHERE organization_id = ?
              AND project_id = ?
            ORDER BY lower(name) ASC, id ASC
            """,
            (organization_id, project_id),
        ).fetchall()
    return [_game_variable_from_row(row) for row in rows]


def get_game_variable_by_id(
    db_path: Path,
    organization_id: str,
    variable_id: int,
    project_id: int | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        if project_id is None:
            row = connection.execute(
                """
                SELECT id,
                       organization_id,
                       project_id,
                       name,
                       value_type,
                       default_value_json,
                       description,
                       created_at,
                       updated_at
                FROM game_variables
                WHERE id = ?
                  AND organization_id = ?
                """,
                (variable_id, organization_id),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT id,
                       organization_id,
                       project_id,
                       name,
                       value_type,
                       default_value_json,
                       description,
                       created_at,
                       updated_at
                FROM game_variables
                WHERE id = ?
                  AND organization_id = ?
                  AND project_id = ?
                """,
                (variable_id, organization_id, project_id),
            ).fetchone()
    return _game_variable_from_row(row) if row else None


def create_game_variable(
    db_path: Path,
    organization_id: str,
    project_id: int | None,
    name: str,
    value_type: str,
    default_value: Any,
    description: str = "",
) -> dict[str, Any]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        cursor = connection.execute(
            """
            INSERT INTO game_variables (
                organization_id,
                project_id,
                name,
                value_type,
                default_value_json,
                description
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                organization_id,
                project_id,
                name.strip(),
                value_type,
                json.dumps(default_value, separators=(",", ":")),
                description.strip(),
            ),
        )
    created = get_game_variable_by_id(db_path, organization_id, int(cursor.lastrowid), project_id)
    if created is None:
        raise RuntimeError("Created variable could not be loaded")
    return created


def update_game_variable(
    db_path: Path,
    organization_id: str,
    variable_id: int,
    name: str,
    value_type: str,
    default_value: Any,
    description: str = "",
    project_id: int | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        cursor = connection.execute(
            """
            UPDATE game_variables
            SET name = ?,
                value_type = ?,
                default_value_json = ?,
                description = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND organization_id = ?
              AND project_id = ?
            """,
            (
                name.strip(),
                value_type,
                json.dumps(default_value, separators=(",", ":")),
                description.strip(),
                variable_id,
                organization_id,
                project_id,
            ),
        )
    if cursor.rowcount == 0:
        return None
    return get_game_variable_by_id(db_path, organization_id, variable_id, project_id)


def delete_game_variable(
    db_path: Path,
    organization_id: str,
    variable_id: int,
    project_id: int | None = None,
) -> None:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        connection.execute(
            """
            DELETE FROM game_variables
            WHERE id = ?
              AND organization_id = ?
              AND project_id = ?
            """,
            (variable_id, organization_id, project_id),
        )


def list_scene_interactions(
    db_path: Path,
    scene_id: int,
    organization_id: str,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT scene_interactions.id,
                   scene_interactions.scene_id,
                   scene_interactions.name,
                   scene_interactions.enabled,
                   scene_interactions.trigger_json,
                   scene_interactions.action_tree_json,
                   scene_interactions.created_at,
                   scene_interactions.updated_at
            FROM scene_interactions
            JOIN scenes ON scenes.id = scene_interactions.scene_id
            WHERE scene_interactions.scene_id = ?
              AND scenes.organization_id = ?
            ORDER BY lower(scene_interactions.name) ASC, scene_interactions.id ASC
            """,
            (scene_id, organization_id),
        ).fetchall()
    return [_scene_interaction_from_row(row) for row in rows]


def get_scene_interaction(
    db_path: Path,
    scene_id: int,
    interaction_id: int,
    organization_id: str,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT scene_interactions.id,
                   scene_interactions.scene_id,
                   scene_interactions.name,
                   scene_interactions.enabled,
                   scene_interactions.trigger_json,
                   scene_interactions.action_tree_json,
                   scene_interactions.created_at,
                   scene_interactions.updated_at
            FROM scene_interactions
            JOIN scenes ON scenes.id = scene_interactions.scene_id
            WHERE scene_interactions.id = ?
              AND scene_interactions.scene_id = ?
              AND scenes.organization_id = ?
            """,
            (interaction_id, scene_id, organization_id),
        ).fetchone()
    return _scene_interaction_from_row(row) if row else None


def create_scene_interaction(
    db_path: Path,
    scene_id: int,
    organization_id: str,
    name: str,
    enabled: bool,
    trigger: dict[str, Any],
    action_tree: list[dict[str, Any]],
) -> dict[str, Any]:
    with connect(db_path) as connection:
        scene = connection.execute(
            "SELECT id FROM scenes WHERE id = ? AND organization_id = ?",
            (scene_id, organization_id),
        ).fetchone()
        if scene is None:
            raise ValueError("Scene not found")
        cursor = connection.execute(
            """
            INSERT INTO scene_interactions (
                scene_id,
                name,
                enabled,
                trigger_json,
                action_tree_json
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                scene_id,
                name.strip(),
                int(enabled),
                json.dumps(trigger, separators=(",", ":")),
                json.dumps(action_tree, separators=(",", ":")),
            ),
        )
    created = get_scene_interaction(db_path, scene_id, int(cursor.lastrowid), organization_id)
    if created is None:
        raise RuntimeError("Created interaction could not be loaded")
    return created


def update_scene_interaction(
    db_path: Path,
    scene_id: int,
    interaction_id: int,
    organization_id: str,
    name: str,
    enabled: bool,
    trigger: dict[str, Any],
    action_tree: list[dict[str, Any]],
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE scene_interactions
            SET name = ?,
                enabled = ?,
                trigger_json = ?,
                action_tree_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND scene_id = ?
              AND EXISTS (
                  SELECT 1
                  FROM scenes
                  WHERE scenes.id = scene_interactions.scene_id
                    AND scenes.organization_id = ?
              )
            """,
            (
                name.strip(),
                int(enabled),
                json.dumps(trigger, separators=(",", ":")),
                json.dumps(action_tree, separators=(",", ":")),
                interaction_id,
                scene_id,
                organization_id,
            ),
        )
    if cursor.rowcount == 0:
        return None
    return get_scene_interaction(db_path, scene_id, interaction_id, organization_id)


def delete_scene_interaction(
    db_path: Path,
    scene_id: int,
    interaction_id: int,
    organization_id: str,
) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            DELETE FROM scene_interactions
            WHERE id = ?
              AND scene_id = ?
              AND EXISTS (
                  SELECT 1
                  FROM scenes
                  WHERE scenes.id = scene_interactions.scene_id
                    AND scenes.organization_id = ?
              )
            """,
            (interaction_id, scene_id, organization_id),
        )


def delete_scene_and_unhook_references(
    db_path: Path,
    scene_id: int,
    organization_id: str,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        scene_row = connection.execute(
            """
            SELECT id,
                   title
            FROM scenes
            WHERE id = ?
              AND organization_id = ?
            """,
            (scene_id, organization_id),
        ).fetchone()
        if scene_row is None:
            return None

        scene_images = connection.execute(
            """
            SELECT scene_images.id,
                   scene_images.uploaded_file_id,
                   uploaded_files.relative_path
            FROM scene_images
            JOIN uploaded_files ON uploaded_files.id = scene_images.uploaded_file_id
            WHERE scene_images.scene_id = ?
            ORDER BY scene_images.id ASC
            """,
            (scene_id,),
        ).fetchall()
        image_uploaded_file_ids = [int(row["uploaded_file_id"]) for row in scene_images]
        image_relative_paths = [str(row["relative_path"]) for row in scene_images if row["relative_path"]]

        object_count_row = connection.execute(
            "SELECT COUNT(*) AS count FROM scene_objects WHERE scene_id = ?",
            (scene_id,),
        ).fetchone()
        interaction_count_row = connection.execute(
            "SELECT COUNT(*) AS count FROM scene_interactions WHERE scene_id = ?",
            (scene_id,),
        ).fetchone()

        removed_action_step_count = 0
        updated_interaction_count = 0
        touched_scene_ids: set[int] = set()
        interaction_rows = connection.execute(
            """
            SELECT scene_interactions.id,
                   scene_interactions.scene_id,
                   scene_interactions.action_tree_json
            FROM scene_interactions
            JOIN scenes ON scenes.id = scene_interactions.scene_id
            WHERE scenes.organization_id = ?
              AND scene_interactions.scene_id != ?
            """,
            (organization_id, scene_id),
        ).fetchall()
        for row in interaction_rows:
            current_tree = _json_loads(row["action_tree_json"], [])
            updated_tree, removed_steps = _strip_deleted_scene_targets_from_steps(current_tree, scene_id)
            if removed_steps <= 0:
                continue
            connection.execute(
                """
                UPDATE scene_interactions
                SET action_tree_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (json.dumps(updated_tree, separators=(",", ":")), int(row["id"])),
            )
            removed_action_step_count += removed_steps
            updated_interaction_count += 1
            touched_scene_ids.add(int(row["scene_id"]))

        overlay_bindings_removed = connection.execute(
            """
            DELETE FROM overlay_scene_bindings
            WHERE organization_id = ?
              AND overlay_scene_id = ?
            """,
            (organization_id, scene_id),
        ).rowcount

        start_scene_row = connection.execute(
            """
            SELECT start_scene_id
            FROM global_settings
            WHERE organization_id = ?
            """,
            (organization_id,),
        ).fetchone()
        cleared_start_scene = bool(start_scene_row and int(start_scene_row["start_scene_id"] or 0) == int(scene_id))
        if cleared_start_scene:
            connection.execute(
                """
                UPDATE global_settings
                SET start_scene_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE organization_id = ?
                """,
                (organization_id,),
            )

        processing_job_count = connection.execute(
            "SELECT COUNT(*) AS count FROM processing_jobs WHERE scene_id = ?",
            (scene_id,),
        ).fetchone()
        connection.execute("DELETE FROM processing_jobs WHERE scene_id = ?", (scene_id,))
        connection.execute("DELETE FROM scene_interactions WHERE scene_id = ?", (scene_id,))
        connection.execute(
            """
            DELETE FROM object_animation_segments
            WHERE object_animation_id IN (
                SELECT object_animations.id
                FROM object_animations
                JOIN scene_objects ON scene_objects.id = object_animations.scene_object_id
                WHERE scene_objects.scene_id = ?
            )
            """,
            (scene_id,),
        )
        connection.execute(
            """
            DELETE FROM object_animations
            WHERE scene_object_id IN (
                SELECT id
                FROM scene_objects
                WHERE scene_id = ?
            )
            """,
            (scene_id,),
        )
        connection.execute(
            """
            DELETE FROM object_masks
            WHERE scene_object_id IN (
                SELECT id
                FROM scene_objects
                WHERE scene_id = ?
            )
            """,
            (scene_id,),
        )
        connection.execute(
            """
            DELETE FROM object_mask_images
            WHERE scene_object_id IN (
                SELECT id
                FROM scene_objects
                WHERE scene_id = ?
            )
            """,
            (scene_id,),
        )
        connection.execute("DELETE FROM scene_objects WHERE scene_id = ?", (scene_id,))
        connection.execute("DELETE FROM scene_images WHERE scene_id = ?", (scene_id,))
        if image_uploaded_file_ids:
            placeholders = ",".join("?" for _ in image_uploaded_file_ids)
            connection.execute(
                f"DELETE FROM uploaded_files WHERE id IN ({placeholders})",
                tuple(image_uploaded_file_ids),
            )
        connection.execute(
            """
            DELETE FROM scenes
            WHERE id = ?
              AND organization_id = ?
            """,
            (scene_id, organization_id),
        )

    return {
        "scene_id": int(scene_row["id"]),
        "scene_title": str(scene_row["title"]),
        "deleted_image_count": len(scene_images),
        "deleted_object_count": int(object_count_row["count"] if object_count_row else 0),
        "deleted_interaction_count": int(interaction_count_row["count"] if interaction_count_row else 0),
        "deleted_processing_job_count": int(processing_job_count["count"] if processing_job_count else 0),
        "deleted_uploaded_file_relative_paths": image_relative_paths,
        "updated_interaction_count": updated_interaction_count,
        "removed_scene_reference_count": removed_action_step_count,
        "removed_overlay_binding_count": int(overlay_bindings_removed or 0),
        "cleared_start_scene": cleared_start_scene,
        "touched_scene_ids": sorted(touched_scene_ids),
    }


def _strip_deleted_scene_targets_from_steps(
    steps: list[dict[str, Any]],
    scene_id: int,
) -> tuple[list[dict[str, Any]], int]:
    normalized_scene_id = int(scene_id)
    updated_steps: list[dict[str, Any]] = []
    removed_count = 0
    for step in steps or []:
        if not isinstance(step, dict):
            updated_steps.append(step)
            continue
        step_type = str(step.get("type") or "")
        if step_type in {"change_scene", "open_overlay_scene", "change_overlay_scene"}:
            target_scene_id = int(step.get("scene_id") or 0)
            if target_scene_id == normalized_scene_id:
                removed_count += 1
                continue
        next_step = dict(step)
        if "then_steps" in next_step:
            then_steps, removed_then = _strip_deleted_scene_targets_from_steps(next_step.get("then_steps") or [], normalized_scene_id)
            next_step["then_steps"] = then_steps
            removed_count += removed_then
        if "else_steps" in next_step:
            else_steps, removed_else = _strip_deleted_scene_targets_from_steps(next_step.get("else_steps") or [], normalized_scene_id)
            next_step["else_steps"] = else_steps
            removed_count += removed_else
        updated_steps.append(next_step)
    return updated_steps, removed_count


def scene_object_belongs_to_scene(
    db_path: Path,
    scene_id: int,
    object_id: int,
    organization_id: str,
) -> bool:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM scene_objects
            JOIN scenes ON scenes.id = scene_objects.scene_id
            WHERE scene_objects.id = ?
              AND scene_objects.scene_id = ?
              AND scenes.organization_id = ?
            """,
            (object_id, scene_id, organization_id),
        ).fetchone()
    return row is not None


def object_animation_belongs_to_object(
    db_path: Path,
    animation_id: int,
    object_id: int,
    organization_id: str,
) -> bool:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM object_animations
            JOIN scene_objects ON scene_objects.id = object_animations.scene_object_id
            JOIN scenes ON scenes.id = scene_objects.scene_id
            WHERE object_animations.id = ?
              AND object_animations.scene_object_id = ?
              AND scenes.organization_id = ?
            """,
            (animation_id, object_id, organization_id),
        ).fetchone()
    return row is not None


def script_line_ids_exist(
    db_path: Path,
    organization_id: str,
    line_ids: list[int],
) -> bool:
    if not line_ids:
        return False
    unique_ids = sorted(set(line_ids))
    placeholders = ",".join("?" for _ in unique_ids)
    with connect(db_path) as connection:
        row = connection.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM script_lines
            WHERE organization_id = ?
              AND line_id IN ({placeholders})
            """,
            [organization_id, *unique_ids],
        ).fetchone()
    return int(row["count"] if row else 0) == len(unique_ids)


def list_script_line_references(
    db_path: Path,
    organization_id: str,
    line_id: int,
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT scene_interactions.id AS interaction_id,
                   scene_interactions.name AS interaction_name,
                   scene_interactions.action_tree_json,
                   scenes.id AS scene_id,
                   scenes.title AS scene_title
            FROM scene_interactions
            JOIN scenes ON scenes.id = scene_interactions.scene_id
            WHERE scenes.organization_id = ?
            ORDER BY scenes.id ASC, scene_interactions.id ASC
            """,
            (organization_id,),
        ).fetchall()
    for row in rows:
        action_tree = _json_loads(row["action_tree_json"], [])
        step_types = sorted(_collect_script_line_reference_step_types(action_tree, int(line_id)))
        if not step_types:
            continue
        references.append(
            {
                "scene_id": row["scene_id"],
                "scene_title": row["scene_title"],
                "interaction_id": row["interaction_id"],
                "interaction_name": row["interaction_name"],
                "step_types": step_types,
            }
        )
    return references


def create_upload_batch(
    db_path: Path,
    organization_id: str,
    project_id: int | None,
    created_by_user_id: int,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        cursor = connection.execute(
            """
            INSERT INTO upload_batches (organization_id, project_id, created_by_user_id)
            VALUES (?, ?, ?)
            """,
            (organization_id, project_id, created_by_user_id),
        )
        row = connection.execute(
            """
            SELECT id, organization_id, project_id, created_by_user_id, status, file_count, total_bytes, created_at
            FROM upload_batches
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()

    return dict(row)


def add_uploaded_file(
    db_path: Path,
    batch_id: int,
    organization_id: str,
    project_id: int | None,
    uploaded_by_user_id: int,
    original_filename: str,
    stored_filename: str,
    relative_path: str,
    content_type: str | None,
    file_size: int,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        cursor = connection.execute(
            """
            INSERT INTO uploaded_files (
                batch_id,
                organization_id,
                project_id,
                uploaded_by_user_id,
                original_filename,
                stored_filename,
                relative_path,
                content_type,
                file_size
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                organization_id,
                project_id,
                uploaded_by_user_id,
                original_filename,
                stored_filename,
                relative_path,
                content_type,
                file_size,
            ),
        )
        connection.execute(
            """
            UPDATE upload_batches
            SET file_count = file_count + 1,
                total_bytes = total_bytes + ?
            WHERE id = ?
            """,
            (file_size, batch_id),
        )
        row = connection.execute(
            """
            SELECT id,
                   batch_id,
                   organization_id,
                   project_id,
                   uploaded_by_user_id,
                   original_filename,
                   stored_filename,
                   relative_path,
                   content_type,
                   file_size,
                   processing_status,
                   created_at
            FROM uploaded_files
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()

    return dict(row)


def get_upload_batch(db_path: Path, batch_id: int) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        batch = connection.execute(
            """
            SELECT id, organization_id, project_id, created_by_user_id, status, file_count, total_bytes, created_at
            FROM upload_batches
            WHERE id = ?
            """,
            (batch_id,),
        ).fetchone()
        if batch is None:
            return None
        files = connection.execute(
            """
            SELECT id,
                   batch_id,
                   organization_id,
                   project_id,
                   uploaded_by_user_id,
                   original_filename,
                   stored_filename,
                   relative_path,
                   content_type,
                   file_size,
                   processing_status,
                   created_at
            FROM uploaded_files
            WHERE batch_id = ?
            ORDER BY id ASC
            """,
            (batch_id,),
        ).fetchall()

    return {**dict(batch), "files": [dict(row) for row in files]}


def get_uploaded_file_by_id(
    db_path: Path,
    uploaded_file_id: int,
    organization_id: str,
    project_id: int | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        row = connection.execute(
            """
            SELECT id,
                   batch_id,
                   organization_id,
                   project_id,
                   uploaded_by_user_id,
                   original_filename,
                   stored_filename,
                   relative_path,
                   content_type,
                   file_size,
                   processing_status,
                   created_at
            FROM uploaded_files
            WHERE id = ?
              AND organization_id = ?
              AND project_id = ?
            """,
            (uploaded_file_id, organization_id, project_id),
        ).fetchone()

    return dict(row) if row else None


def list_upload_batches(
    db_path: Path,
    organization_id: str,
    project_id: int | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        rows = connection.execute(
            """
            SELECT id, organization_id, project_id, created_by_user_id, status, file_count, total_bytes, created_at
            FROM upload_batches
            WHERE organization_id = ?
              AND project_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (organization_id, project_id, limit),
        ).fetchall()

    return [dict(row) for row in rows]


def list_uploaded_image_files_for_batch(
    db_path: Path,
    batch_id: int,
    organization_id: str,
    project_id: int | None = None,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        rows = connection.execute(
            """
            SELECT id,
                   batch_id,
                   organization_id,
                   project_id,
                   uploaded_by_user_id,
                   original_filename,
                   stored_filename,
                   relative_path,
                   content_type,
                   file_size,
                   processing_status,
                   created_at
            FROM uploaded_files
            WHERE batch_id = ?
              AND organization_id = ?
              AND project_id = ?
              AND (
                content_type LIKE 'image/%'
                OR lower(original_filename) GLOB '*.jpg'
                OR lower(original_filename) GLOB '*.jpeg'
                OR lower(original_filename) GLOB '*.png'
                OR lower(original_filename) GLOB '*.webp'
              )
            ORDER BY id ASC
            """,
            (batch_id, organization_id, project_id),
        ).fetchall()

    return sorted(
        [dict(row) for row in rows],
        key=lambda row: (_original_filename_sort_key(row), row["id"]),
    )


def list_scene_image_hashes(
    db_path: Path,
    organization_id: str,
    project_id: int | None = None,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        rows = connection.execute(
            """
            SELECT scene_images.scene_id,
                   scene_images.uploaded_file_id,
                   scene_images.perceptual_hash,
                   scene_images.width,
                   scene_images.height
            FROM scene_images
            JOIN scenes ON scenes.id = scene_images.scene_id
            WHERE scenes.organization_id = ?
              AND scenes.project_id = ?
            """,
            (organization_id, project_id),
        ).fetchall()

    return [dict(row) for row in rows]


def create_scene(
    db_path: Path,
    organization_id: str,
    project_id: int | None,
    created_by_user_id: int,
    representative_uploaded_file_id: int | None,
    representative_hash: str | None,
    title: str,
    description: str,
    presentation_mode: str = "base",
) -> dict[str, Any]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        next_sort_order = connection.execute(
            """
            SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_sort_order
            FROM scenes
            WHERE organization_id = ?
              AND project_id = ?
            """,
            (organization_id, project_id),
        ).fetchone()["next_sort_order"]
        cursor = connection.execute(
            """
            INSERT INTO scenes (
                organization_id,
                project_id,
                title,
                description,
                presentation_mode,
                background_frame_index,
                representative_uploaded_file_id,
                representative_hash,
                created_by_user_id,
                sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                organization_id,
                project_id,
                title,
                description,
                presentation_mode,
                0,
                representative_uploaded_file_id,
                representative_hash,
                created_by_user_id,
                int(next_sort_order),
            ),
        )
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   project_id,
                   title,
                   description,
                   presentation_mode,
                   status,
                   background_frame_index,
                   sort_order,
                   representative_uploaded_file_id,
                   representative_hash,
                   created_by_user_id,
                   created_at,
                   updated_at
            FROM scenes
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()

    return dict(row)


def create_empty_scene(
    db_path: Path,
    organization_id: str,
    created_by_user_id: int,
    title: str,
    project_id: int | None = None,
    description: str = "",
    presentation_mode: str = "base",
) -> dict[str, Any]:
    return create_scene(
        db_path,
        organization_id=organization_id,
        project_id=project_id,
        created_by_user_id=created_by_user_id,
        representative_uploaded_file_id=None,
        representative_hash=None,
        title=title,
        description=description,
        presentation_mode=presentation_mode,
    )


def add_scene_image(
    db_path: Path,
    scene_id: int,
    uploaded_file_id: int,
    perceptual_hash: str,
    width: int,
    height: int,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        next_sort_order = connection.execute(
            """
            SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_sort_order
            FROM scene_images
            WHERE scene_id = ?
            """,
            (scene_id,),
        ).fetchone()["next_sort_order"]
        connection.execute(
            """
            INSERT INTO scene_images (
                scene_id,
                uploaded_file_id,
                perceptual_hash,
                width,
                height,
                sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(uploaded_file_id)
            DO UPDATE SET scene_id = excluded.scene_id,
                          perceptual_hash = excluded.perceptual_hash,
                          width = excluded.width,
                          height = excluded.height,
                          sort_order = excluded.sort_order
            """,
            (scene_id, uploaded_file_id, perceptual_hash, width, height, int(next_sort_order)),
        )
        row = connection.execute(
            """
            SELECT id, scene_id, uploaded_file_id, perceptual_hash, width, height, sort_order, created_at
            FROM scene_images
            WHERE uploaded_file_id = ?
            """,
            (uploaded_file_id,),
        ).fetchone()

    return dict(row)


def list_uploaded_image_files(
    db_path: Path,
    organization_id: str,
    project_id: int | None = None,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        rows = connection.execute(
            """
            SELECT uploaded_files.id AS uploaded_file_id,
                   uploaded_files.batch_id,
                   uploaded_files.organization_id,
                   uploaded_files.project_id,
                   uploaded_files.uploaded_by_user_id,
                   uploaded_files.original_filename,
                   uploaded_files.stored_filename,
                   uploaded_files.relative_path,
                   uploaded_files.content_type,
                   uploaded_files.file_size,
                   uploaded_files.processing_status,
                   uploaded_files.created_at,
                   scene_images.id AS scene_image_id,
                   scene_images.scene_id,
                   scene_images.perceptual_hash,
                   scene_images.width,
                   scene_images.height,
                   scene_images.sort_order,
                   scenes.title AS scene_title,
                   pickup_objects.id AS pickup_object_id,
                   pickup_objects.name AS pickup_object_name
            FROM uploaded_files
            LEFT JOIN scene_images ON scene_images.uploaded_file_id = uploaded_files.id
            LEFT JOIN scenes
              ON scenes.id = scene_images.scene_id
             AND scenes.organization_id = uploaded_files.organization_id
             AND scenes.project_id = uploaded_files.project_id
            LEFT JOIN scene_objects AS pickup_objects
              ON pickup_objects.pickup_uploaded_file_id = uploaded_files.id
             AND pickup_objects.scene_id = scene_images.scene_id
            WHERE uploaded_files.organization_id = ?
              AND uploaded_files.project_id = ?
              AND (
                uploaded_files.content_type LIKE 'image/%'
                OR lower(uploaded_files.original_filename) GLOB '*.jpg'
                OR lower(uploaded_files.original_filename) GLOB '*.jpeg'
                OR lower(uploaded_files.original_filename) GLOB '*.png'
                OR lower(uploaded_files.original_filename) GLOB '*.webp'
              )
            ORDER BY COALESCE(scene_images.scene_id, 2147483647) ASC,
                     COALESCE(scene_images.sort_order, 2147483647) ASC,
                     uploaded_files.id ASC
            """,
            (organization_id, project_id),
        ).fetchall()

    return [dict(row) for row in rows]


def _refresh_scene_representative(connection: sqlite3.Connection, scene_id: int) -> None:
    scene = connection.execute(
        """
        SELECT background_frame_index
        FROM scenes
        WHERE id = ?
        """,
        (scene_id,),
    ).fetchone()
    if scene is None:
        return
    images = connection.execute(
        """
        SELECT uploaded_file_id, perceptual_hash
        FROM scene_images
        WHERE scene_id = ?
        ORDER BY sort_order ASC, id ASC
        """,
        (scene_id,),
    ).fetchall()
    if not images:
        connection.execute(
            """
            UPDATE scenes
            SET representative_uploaded_file_id = NULL,
                representative_hash = NULL,
                background_frame_index = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (scene_id,),
        )
        return
    background_frame_index = int(scene["background_frame_index"] or 0)
    clamped_index = max(0, min(background_frame_index, len(images) - 1))
    representative_image = images[clamped_index]
    connection.execute(
        """
        UPDATE scenes
        SET representative_uploaded_file_id = ?,
            representative_hash = ?,
            background_frame_index = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            representative_image["uploaded_file_id"],
            representative_image["perceptual_hash"],
            clamped_index,
            scene_id,
        ),
    )


def assign_uploaded_file_to_scene(
    db_path: Path,
    scene_id: int,
    uploaded_file_id: int,
    perceptual_hash: str,
    width: int,
    height: int,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        existing = connection.execute(
            """
            SELECT id, scene_id
            FROM scene_images
            WHERE uploaded_file_id = ?
            """,
            (uploaded_file_id,),
        ).fetchone()
        previous_scene_id = int(existing["scene_id"]) if existing else None
        next_sort_order = connection.execute(
            """
            SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_sort_order
            FROM scene_images
            WHERE scene_id = ?
            """,
            (scene_id,),
        ).fetchone()["next_sort_order"]
        connection.execute(
            """
            INSERT INTO scene_images (
                scene_id,
                uploaded_file_id,
                perceptual_hash,
                width,
                height,
                sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(uploaded_file_id)
            DO UPDATE SET scene_id = excluded.scene_id,
                          perceptual_hash = excluded.perceptual_hash,
                          width = excluded.width,
                          height = excluded.height,
                          sort_order = excluded.sort_order
            """,
            (scene_id, uploaded_file_id, perceptual_hash, width, height, int(next_sort_order)),
        )
        _refresh_scene_representative(connection, scene_id)
        if previous_scene_id is not None and previous_scene_id != scene_id:
            _refresh_scene_representative(connection, previous_scene_id)
        row = connection.execute(
            """
            SELECT scene_images.id,
                   scene_images.scene_id,
                   scene_images.uploaded_file_id,
                   scene_images.perceptual_hash,
                   scene_images.width,
                   scene_images.height,
                   scene_images.sort_order,
                   scene_images.created_at,
                   uploaded_files.original_filename,
                   uploaded_files.relative_path,
                   uploaded_files.content_type
            FROM scene_images
            JOIN uploaded_files ON uploaded_files.id = scene_images.uploaded_file_id
            WHERE scene_images.uploaded_file_id = ?
            """,
            (uploaded_file_id,),
        ).fetchone()
    return dict(row) if row else None


def reorder_scene_images(
    db_path: Path,
    scene_id: int,
    ordered_scene_image_ids: list[int],
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        existing_rows = connection.execute(
            """
            SELECT id
            FROM scene_images
            WHERE scene_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (scene_id,),
        ).fetchall()
        existing_ids = [int(row["id"]) for row in existing_rows]
        if sorted(existing_ids) != sorted(int(value) for value in ordered_scene_image_ids):
            raise ValueError("Image reorder payload does not match the scene image set.")
        for sort_order, scene_image_id in enumerate(ordered_scene_image_ids):
            connection.execute(
                """
                UPDATE scene_images
                SET sort_order = ?
                WHERE id = ?
                  AND scene_id = ?
                """,
                (int(sort_order), int(scene_image_id), scene_id),
            )
        _refresh_scene_representative(connection, scene_id)
    return list_scene_images_for_scene(db_path, scene_id)


def get_scene_with_images(db_path: Path, scene_id: int) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        scene = connection.execute(
            """
            SELECT id,
                   organization_id,
                   project_id,
                   title,
                   description,
                   presentation_mode,
                   status,
                   background_frame_index,
                   sort_order,
                   representative_uploaded_file_id,
                   representative_hash,
                   created_by_user_id,
                   created_at,
                   updated_at
            FROM scenes
            WHERE id = ?
            """,
            (scene_id,),
        ).fetchone()
        if scene is None:
            return None
        images = connection.execute(
            """
            SELECT scene_images.id,
                   scene_images.scene_id,
                   scene_images.uploaded_file_id,
                   scene_images.perceptual_hash,
                   scene_images.width,
                   scene_images.height,
                   scene_images.sort_order,
                   scene_images.created_at,
                   uploaded_files.original_filename,
                   uploaded_files.relative_path
            FROM scene_images
            JOIN uploaded_files ON uploaded_files.id = scene_images.uploaded_file_id
            WHERE scene_images.scene_id = ?
            ORDER BY scene_images.sort_order ASC, scene_images.id ASC
            """,
            (scene_id,),
        ).fetchall()
        images = [dict(row) for row in images]
        objects = connection.execute(
            """
            SELECT scene_objects.id,
                   scene_objects.scene_id,
                   scene_objects.name,
                   scene_objects.description,
                   scene_objects.prompt,
                   scene_objects.inventory_image_prompt,
                   scene_objects.category,
                   scene_objects.source,
                   scene_objects.sort_order,
                   scene_objects.visible,
                   scene_objects.enabled,
                   scene_objects.keyboard_target_enabled,
                   scene_objects.default_uploaded_file_id,
                   scene_objects.pickup_uploaded_file_id,
                   scene_objects.inventory_image_relative_path,
                   scene_objects.inventory_image_failed,
                   scene_objects.pickup_frame_failed,
                   scene_objects.status,
                   scene_objects.created_at,
                   scene_objects.updated_at,
                   COUNT(DISTINCT object_masks.id) AS mask_image_count,
                   COUNT(DISTINCT object_animations.id) AS animation_count
            FROM scene_objects
            LEFT JOIN object_masks ON object_masks.scene_object_id = scene_objects.id
            LEFT JOIN object_animations ON object_animations.scene_object_id = scene_objects.id
            WHERE scene_objects.scene_id = ?
            GROUP BY scene_objects.id
            ORDER BY scene_objects.sort_order ASC, scene_objects.id ASC
            """,
            (scene_id,),
        ).fetchall()
        object_ids = [row["id"] for row in objects]
        masks_by_object_id: dict[int, list[dict[str, Any]]] = {
            object_id: [] for object_id in object_ids
        }
        if object_ids:
            placeholders = ",".join("?" for _ in object_ids)
            object_masks = connection.execute(
                f"""
                SELECT object_masks.id,
                       object_masks.scene_object_id,
                       object_masks.uploaded_file_id,
                       object_masks.relative_path,
                       object_masks.soft_relative_path,
                       object_masks.prompt_text,
                       object_masks.bbox_json,
                       object_masks.score,
                       object_masks.status,
                       object_masks.created_at,
                       object_masks.updated_at,
                       uploaded_files.original_filename
                FROM object_masks
                JOIN uploaded_files ON uploaded_files.id = object_masks.uploaded_file_id
                WHERE object_masks.scene_object_id IN ({placeholders})
                ORDER BY uploaded_files.original_filename ASC, object_masks.id DESC
                """,
                object_ids,
            ).fetchall()
            object_masks = sorted(
                [dict(row) for row in object_masks],
                key=lambda row: (
                    row["scene_object_id"],
                    _original_filename_sort_key(row),
                    row["id"],
                ),
            )
            for object_mask in object_masks:
                masks_by_object_id[object_mask["scene_object_id"]].append(object_mask)
    return {
        **dict(scene),
        "images": images,
        "objects": [
            {
                **dict(row),
                "visible": bool(row["visible"]),
                "enabled": bool(row["enabled"]),
                "keyboard_target_enabled": bool(row["keyboard_target_enabled"]),
                "inventory_image_failed": bool(row["inventory_image_failed"]),
                "pickup_frame_failed": bool(row["pickup_frame_failed"]),
                "masks": masks_by_object_id[row["id"]],
            }
            for row in objects
        ],
    }


def list_scenes(
    db_path: Path,
    organization_id: str,
    project_id: int | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        if project_id is None:
            rows = connection.execute(
                """
                SELECT scenes.id,
                       scenes.organization_id,
                       scenes.project_id,
                       scenes.title,
                       scenes.description,
                       scenes.presentation_mode,
                       scenes.status,
                       scenes.background_frame_index,
                       scenes.sort_order,
                       scenes.representative_uploaded_file_id,
                       scenes.representative_hash,
                       scenes.created_by_user_id,
                       scenes.created_at,
                       scenes.updated_at,
                       COUNT(DISTINCT scene_images.id) AS image_count,
                       COUNT(DISTINCT scene_objects.id) AS object_count,
                       COUNT(DISTINCT object_masks.id) AS object_mask_count
                FROM scenes
                LEFT JOIN scene_images ON scene_images.scene_id = scenes.id
                LEFT JOIN scene_objects ON scene_objects.scene_id = scenes.id
                LEFT JOIN object_masks ON object_masks.scene_object_id = scene_objects.id
                WHERE scenes.organization_id = ?
                  AND scenes.presentation_mode != 'character'
                GROUP BY scenes.id
                ORDER BY scenes.sort_order ASC, scenes.id ASC
                LIMIT ?
                """,
                (organization_id, limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT scenes.id,
                       scenes.organization_id,
                       scenes.project_id,
                       scenes.title,
                       scenes.description,
                       scenes.presentation_mode,
                       scenes.status,
                       scenes.background_frame_index,
                       scenes.sort_order,
                       scenes.representative_uploaded_file_id,
                       scenes.representative_hash,
                       scenes.created_by_user_id,
                       scenes.created_at,
                       scenes.updated_at,
                       COUNT(DISTINCT scene_images.id) AS image_count,
                       COUNT(DISTINCT scene_objects.id) AS object_count,
                       COUNT(DISTINCT object_masks.id) AS object_mask_count
                FROM scenes
                LEFT JOIN scene_images ON scene_images.scene_id = scenes.id
                LEFT JOIN scene_objects ON scene_objects.scene_id = scenes.id
                LEFT JOIN object_masks ON object_masks.scene_object_id = scene_objects.id
                WHERE scenes.organization_id = ?
                  AND scenes.project_id = ?
                  AND scenes.presentation_mode != 'character'
                GROUP BY scenes.id
                ORDER BY scenes.sort_order ASC, scenes.id ASC
                LIMIT ?
                """,
                (organization_id, project_id, limit),
            ).fetchall()

    return [dict(row) for row in rows]


def move_scene_sort_order(
    db_path: Path,
    *,
    organization_id: str,
    project_id: int,
    scene_id: int,
    direction: str,
) -> list[dict[str, Any]]:
    normalized_direction = direction.strip().lower()
    if normalized_direction not in {"up", "down"}:
        raise ValueError("Scene move direction must be 'up' or 'down'.")
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, sort_order
            FROM scenes
            WHERE organization_id = ?
              AND project_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (organization_id, project_id),
        ).fetchall()
        ordered_scenes = [dict(row) for row in rows]
        index = next((idx for idx, row in enumerate(ordered_scenes) if int(row["id"]) == scene_id), -1)
        if index < 0:
            return []
        swap_index = index - 1 if normalized_direction == "up" else index + 1
        if swap_index < 0 or swap_index >= len(ordered_scenes):
            return list_scenes(db_path, organization_id, project_id, limit=max(20, len(ordered_scenes)))
        current_scene = ordered_scenes[index]
        target_scene = ordered_scenes[swap_index]
        connection.execute(
            """
            UPDATE scenes
            SET sort_order = ?
            WHERE id = ?
            """,
            (int(target_scene["sort_order"]), int(current_scene["id"])),
        )
        connection.execute(
            """
            UPDATE scenes
            SET sort_order = ?
            WHERE id = ?
            """,
            (int(current_scene["sort_order"]), int(target_scene["id"])),
        )
    return list_scenes(db_path, organization_id, project_id, limit=max(20, len(ordered_scenes)))


def get_workspace_summary(
    db_path: Path,
    organization_id: str,
    project_id: int | None = None,
    languages: list[str] | tuple[str, ...] = (),
) -> dict[str, int]:
    normalized_languages = [
        str(language).strip().lower()
        for language in languages
        if str(language).strip()
    ]
    with connect(db_path) as connection:
        if project_id is None:
            project_id = _get_or_create_default_project_id(connection, organization_id)
        scenes_count = int(connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM scenes
            WHERE organization_id = ?
              AND project_id = ?
              AND presentation_mode != 'character'
            """,
            (organization_id, project_id),
        ).fetchone()["count"] or 0)

        missing_masks = int(connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM scene_objects so
            JOIN scenes s ON s.id = so.scene_id
            WHERE s.organization_id = ?
              AND s.project_id = ?
              AND s.presentation_mode != 'character'
              AND NOT EXISTS (
                SELECT 1
                FROM object_masks om
                WHERE om.scene_object_id = so.id
              )
            """,
            (organization_id, project_id),
        ).fetchone()["count"] or 0)

        missing_inventory_art = int(connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM scene_objects so
            JOIN scenes s ON s.id = so.scene_id
            WHERE s.organization_id = ?
              AND s.project_id = ?
              AND s.presentation_mode != 'character'
              AND so.keyboard_target_enabled = 1
              AND TRIM(COALESCE(so.inventory_image_relative_path, '')) = ''
            """,
            (organization_id, project_id),
        ).fetchone()["count"] or 0)

        failed_jobs = int(connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM processing_jobs
            WHERE organization_id = ?
              AND project_id = ?
              AND status = 'failed'
            """,
            (organization_id, project_id),
        ).fetchone()["count"] or 0)

        missing_translations = 0
        missing_approved_audio = 0
        referenced_missing_selected_audio = 0
        referenced_unverified_translations = 0
        if normalized_languages:
            line_rows = connection.execute(
                """
                SELECT id
                FROM script_lines
                WHERE organization_id = ?
                  AND project_id = ?
                """,
                (organization_id, project_id),
            ).fetchall()
            line_ids = [int(row["id"]) for row in line_rows]
            for line_id in line_ids:
                for language in normalized_languages:
                    if language != "en":
                        translation_row = connection.execute(
                            """
                            SELECT 1
                            FROM script_translations
                            WHERE script_line_id = ?
                              AND language = ?
                              AND TRIM(COALESCE(text, '')) != ''
                            LIMIT 1
                            """,
                            (line_id, language),
                        ).fetchone()
                        if translation_row is None:
                            missing_translations += 1

                    approved_audio_row = connection.execute(
                        """
                        SELECT 1
                        FROM script_audio_candidates
                        WHERE script_line_id = ?
                          AND language = ?
                          AND relative_path != ''
                          AND manifest_status != 'error'
                          AND review_status = 'approved'
                        LIMIT 1
                        """,
                        (line_id, language),
                    ).fetchone()
                    if approved_audio_row is None:
                        missing_approved_audio += 1

            interaction_rows = connection.execute(
                """
                SELECT action_tree_json
                FROM scene_interactions si
                JOIN scenes s ON s.id = si.scene_id
                WHERE s.organization_id = ?
                  AND s.project_id = ?
                  AND si.enabled = 1
                """,
                (organization_id, project_id),
            ).fetchall()
            referenced_line_ids: set[int] = set()
            for row in interaction_rows:
                try:
                    action_tree = json.loads(row["action_tree_json"] or "[]")
                except json.JSONDecodeError:
                    continue
                _collect_script_line_ids_from_action_tree(action_tree, referenced_line_ids)

            for line_id in sorted(referenced_line_ids):
                for language in normalized_languages:
                    selected_audio_row = connection.execute(
                        """
                        SELECT 1
                        FROM script_audio_candidates
                        WHERE script_line_id = ?
                          AND language = ?
                          AND selected = 1
                          AND relative_path != ''
                          AND manifest_status != 'error'
                        LIMIT 1
                        """,
                        (line_id, language),
                    ).fetchone()
                    if selected_audio_row is None:
                        referenced_missing_selected_audio += 1

                    if language == "en":
                        continue
                    translation_row = connection.execute(
                        """
                        SELECT review_status
                        FROM script_translations
                        WHERE script_line_id = ?
                          AND language = ?
                          AND TRIM(COALESCE(text, '')) != ''
                        LIMIT 1
                        """,
                        (line_id, language),
                    ).fetchone()
                    if translation_row is None or str(translation_row["review_status"] or "") != "approved":
                        referenced_unverified_translations += 1

    return {
        "scenes_count": scenes_count,
        "missing_masks": missing_masks,
        "missing_inventory_art": missing_inventory_art,
        "missing_translations": missing_translations,
        "missing_approved_audio": missing_approved_audio,
        "referenced_missing_selected_audio": referenced_missing_selected_audio,
        "referenced_unverified_translations": referenced_unverified_translations,
        "failed_jobs": failed_jobs,
    }


def create_scene_object(
    db_path: Path,
    scene_id: int,
    name: str,
    description: str = "",
    prompt: str | None = None,
    inventory_image_prompt: str | None = None,
    category: str = "other",
    source: str = "manual",
) -> dict[str, Any]:
    normalized_name = name.strip()
    normalized_prompt = (prompt or normalized_name).strip()
    normalized_inventory_prompt = (inventory_image_prompt or "").strip()
    with connect(db_path) as connection:
        next_sort_order = connection.execute(
            """
            SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_sort_order
            FROM scene_objects
            WHERE scene_id = ?
            """,
            (scene_id,),
        ).fetchone()["next_sort_order"]
        cursor = connection.execute(
            """
            INSERT INTO scene_objects (
                scene_id, name, description, prompt, inventory_image_prompt, category, source, sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scene_id,
                normalized_name,
                description.strip(),
                normalized_prompt,
                normalized_inventory_prompt,
                category.strip(),
                source.strip(),
                int(next_sort_order),
            ),
        )
        row = connection.execute(
            """
            SELECT id, scene_id, name, description, prompt, inventory_image_prompt, category, source, sort_order, visible, enabled, keyboard_target_enabled, default_uploaded_file_id, pickup_uploaded_file_id, inventory_image_relative_path, inventory_image_failed, pickup_frame_failed, status, created_at, updated_at
            FROM scene_objects
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
    result = dict(row)
    result["visible"] = bool(result["visible"])
    result["enabled"] = bool(result["enabled"])
    result["keyboard_target_enabled"] = bool(result["keyboard_target_enabled"])
    result["inventory_image_failed"] = bool(result["inventory_image_failed"])
    result["pickup_frame_failed"] = bool(result["pickup_frame_failed"])
    return result


def create_scene_mask_prompt(
    db_path: Path,
    scene_id: int,
    text: str,
    source: str = "manual",
    enabled: bool = True,
) -> tuple[dict[str, Any], bool]:
    normalized_text = _normalize_prompt_text(text)
    with connect(db_path) as connection:
        existing = connection.execute(
            """
            SELECT id, scene_id, text, source, enabled, status, created_at, updated_at
            FROM scene_mask_prompts
            WHERE scene_id = ?
              AND lower(text) = ?
            """,
            (scene_id, normalized_text.lower()),
        ).fetchone()
        if existing:
            return {**dict(existing), "enabled": bool(existing["enabled"])}, False

        cursor = connection.execute(
            """
            INSERT INTO scene_mask_prompts (scene_id, text, source, enabled)
            VALUES (?, ?, ?, ?)
            """,
            (scene_id, normalized_text, source.strip() or "manual", int(enabled)),
        )
        row = connection.execute(
            """
            SELECT id, scene_id, text, source, enabled, status, created_at, updated_at
            FROM scene_mask_prompts
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()

    return {**dict(row), "enabled": bool(row["enabled"])}, True


def update_scene_mask_prompt(
    db_path: Path,
    prompt_id: int,
    scene_id: int,
    text: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any] | None:
    assignments = []
    values: list[Any] = []
    if text is not None:
        assignments.append("text = ?")
        values.append(_normalize_prompt_text(text))
    if enabled is not None:
        assignments.append("enabled = ?")
        values.append(int(enabled))
    if assignments:
        assignments.append("updated_at = CURRENT_TIMESTAMP")
        with connect(db_path) as connection:
            connection.execute(
                f"""
                UPDATE scene_mask_prompts
                SET {", ".join(assignments)}
                WHERE id = ?
                  AND scene_id = ?
                """,
                (*values, prompt_id, scene_id),
            )

    return get_scene_mask_prompt(db_path, prompt_id=prompt_id, scene_id=scene_id)


def delete_scene_mask_prompt(db_path: Path, prompt_id: int, scene_id: int) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            DELETE FROM scene_mask_prompts
            WHERE id = ?
              AND scene_id = ?
            """,
            (prompt_id, scene_id),
        )


def get_scene_mask_prompt(
    db_path: Path,
    prompt_id: int,
    scene_id: int,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, scene_id, text, source, enabled, status, created_at, updated_at
            FROM scene_mask_prompts
            WHERE id = ?
              AND scene_id = ?
            """,
            (prompt_id, scene_id),
        ).fetchone()

    return {**dict(row), "enabled": bool(row["enabled"])} if row else None


def list_enabled_scene_mask_prompts(
    db_path: Path,
    scene_id: int,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, scene_id, text, source, enabled, status, created_at, updated_at
            FROM scene_mask_prompts
            WHERE scene_id = ?
              AND enabled = 1
            ORDER BY lower(text) ASC
            """,
            (scene_id,),
        ).fetchall()

    return [{**dict(row), "enabled": bool(row["enabled"])} for row in rows]


def list_scene_images_for_scene(db_path: Path, scene_id: int) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT scene_images.id,
                   scene_images.scene_id,
                   scene_images.uploaded_file_id,
                   scene_images.perceptual_hash,
                   scene_images.width,
                   scene_images.height,
                   scene_images.sort_order,
                   scene_images.created_at,
                   uploaded_files.original_filename,
                   uploaded_files.relative_path,
                   uploaded_files.content_type
            FROM scene_images
            JOIN uploaded_files ON uploaded_files.id = scene_images.uploaded_file_id
            WHERE scene_images.scene_id = ?
            ORDER BY scene_images.sort_order ASC, scene_images.id ASC
            """,
            (scene_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def mask_candidate_exists(
    db_path: Path,
    prompt_id: int,
    scene_image_id: int,
) -> bool:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM mask_candidates
            WHERE scene_mask_prompt_id = ?
              AND scene_image_id = ?
            """,
            (prompt_id, scene_image_id),
        ).fetchone()

    return row is not None


def create_mask_candidate(
    db_path: Path,
    prompt_id: int,
    scene_image_id: int,
    uploaded_file_id: int,
    raw_relative_path: str,
    soft_relative_path: str | None,
    bbox_json: str | None,
    score: float | None,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO mask_candidates (
                scene_mask_prompt_id,
                scene_image_id,
                uploaded_file_id,
                raw_relative_path,
                soft_relative_path,
                bbox_json,
                score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prompt_id,
                scene_image_id,
                uploaded_file_id,
                raw_relative_path,
                soft_relative_path,
                bbox_json,
                score,
            ),
        )
        row = connection.execute(
            """
            SELECT id,
                   scene_mask_prompt_id,
                   scene_image_id,
                   uploaded_file_id,
                   raw_relative_path,
                   soft_relative_path,
                   bbox_json,
                   score,
                   selected,
                   status,
                   created_at
            FROM mask_candidates
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()

    return {**dict(row), "selected": bool(row["selected"])}


def get_mask_candidate_by_id(
    db_path: Path,
    candidate_id: int,
    organization_id: str,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT mask_candidates.id,
                   mask_candidates.scene_mask_prompt_id,
                   mask_candidates.scene_image_id,
                   mask_candidates.uploaded_file_id,
                   mask_candidates.raw_relative_path,
                   mask_candidates.soft_relative_path,
                   mask_candidates.bbox_json,
                   mask_candidates.score,
                   mask_candidates.selected,
                   mask_candidates.status,
                   mask_candidates.created_at
            FROM mask_candidates
            JOIN scene_mask_prompts ON scene_mask_prompts.id = mask_candidates.scene_mask_prompt_id
            JOIN scenes ON scenes.id = scene_mask_prompts.scene_id
            WHERE mask_candidates.id = ?
              AND scenes.organization_id = ?
            """,
            (candidate_id, organization_id),
        ).fetchone()

    return {**dict(row), "selected": bool(row["selected"])} if row else None


def create_scene_object_if_missing(
    db_path: Path,
    scene_id: int,
    name: str,
    description: str = "",
    prompt: str | None = None,
    inventory_image_prompt: str | None = None,
    category: str = "other",
    source: str = "vlm",
) -> tuple[dict[str, Any], bool]:
    normalized_name = _normalize_object_name(name)
    with connect(db_path) as connection:
        existing = connection.execute(
            """
            SELECT id, scene_id, name, description, prompt, inventory_image_prompt, category, source, sort_order, visible, enabled, keyboard_target_enabled, default_uploaded_file_id, pickup_uploaded_file_id, inventory_image_relative_path, inventory_image_failed, pickup_frame_failed, status, created_at, updated_at
            FROM scene_objects
            WHERE scene_id = ?
              AND lower(name) = ?
            """,
            (scene_id, normalized_name.lower()),
        ).fetchone()
        if existing:
            result = dict(existing)
            result["visible"] = bool(result["visible"])
            result["enabled"] = bool(result["enabled"])
            result["keyboard_target_enabled"] = bool(result["keyboard_target_enabled"])
            result["inventory_image_failed"] = bool(result["inventory_image_failed"])
            result["pickup_frame_failed"] = bool(result["pickup_frame_failed"])
            return result, False

        next_sort_order = connection.execute(
            """
            SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_sort_order
            FROM scene_objects
            WHERE scene_id = ?
            """,
            (scene_id,),
        ).fetchone()["next_sort_order"]

        cursor = connection.execute(
            """
            INSERT INTO scene_objects (
                scene_id, name, description, prompt, inventory_image_prompt, category, source, sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scene_id,
                normalized_name,
                description.strip(),
                (prompt or normalized_name).strip(),
                (inventory_image_prompt or "").strip(),
                category.strip() or "other",
                source.strip() or "vlm",
                int(next_sort_order),
            ),
        )
        row = connection.execute(
            """
            SELECT id, scene_id, name, description, prompt, inventory_image_prompt, category, source, sort_order, visible, enabled, keyboard_target_enabled, default_uploaded_file_id, pickup_uploaded_file_id, inventory_image_relative_path, inventory_image_failed, pickup_frame_failed, status, created_at, updated_at
            FROM scene_objects
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
    result = dict(row)
    result["visible"] = bool(result["visible"])
    result["enabled"] = bool(result["enabled"])
    result["keyboard_target_enabled"] = bool(result["keyboard_target_enabled"])
    result["inventory_image_failed"] = bool(result["inventory_image_failed"])
    result["pickup_frame_failed"] = bool(result["pickup_frame_failed"])
    return result, True


def update_scene_object(
    db_path: Path,
    scene_id: int,
    object_id: int,
    name: str | None = None,
    description: str | None = None,
    prompt: str | None = None,
    inventory_image_prompt: str | None = None,
    sort_order: int | None = None,
    visible: bool | None = None,
    enabled: bool | None = None,
    keyboard_target_enabled: bool | None = None,
    default_uploaded_file_id: int | None = None,
    update_default_uploaded_file_id: bool = False,
    pickup_uploaded_file_id: int | None = None,
    update_pickup_uploaded_file_id: bool = False,
) -> dict[str, Any] | None:
    assignments = []
    values: list[Any] = []
    if name is not None:
        assignments.append("name = ?")
        values.append(name.strip())
    if description is not None:
        assignments.append("description = ?")
        values.append(description.strip())
    if prompt is not None:
        assignments.append("prompt = ?")
        values.append(prompt.strip())
    if inventory_image_prompt is not None:
        assignments.append("inventory_image_prompt = ?")
        values.append(inventory_image_prompt.strip())
    if sort_order is not None:
        assignments.append("sort_order = ?")
        values.append(int(sort_order))
    if visible is not None:
        assignments.append("visible = ?")
        values.append(int(bool(visible)))
    if enabled is not None:
        assignments.append("enabled = ?")
        values.append(int(bool(enabled)))
    if keyboard_target_enabled is not None:
        assignments.append("keyboard_target_enabled = ?")
        values.append(int(bool(keyboard_target_enabled)))
    if update_default_uploaded_file_id:
        assignments.append("default_uploaded_file_id = ?")
        values.append(default_uploaded_file_id if default_uploaded_file_id is None else int(default_uploaded_file_id))
    if update_pickup_uploaded_file_id:
        assignments.append("pickup_uploaded_file_id = ?")
        values.append(pickup_uploaded_file_id if pickup_uploaded_file_id is None else int(pickup_uploaded_file_id))
    if assignments:
        assignments.append("updated_at = CURRENT_TIMESTAMP")
        with connect(db_path) as connection:
            connection.execute(
                f"""
                UPDATE scene_objects
                SET {", ".join(assignments)}
                WHERE id = ?
                  AND scene_id = ?
                """,
                (*values, object_id, scene_id),
            )

    return get_scene_object(db_path, scene_id=scene_id, object_id=object_id)


def delete_scene_object(db_path: Path, scene_id: int, object_id: int) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            DELETE FROM object_animation_segments
            WHERE object_animation_id IN (
                SELECT object_animations.id
                FROM object_animations
                JOIN scene_objects ON scene_objects.id = object_animations.scene_object_id
                WHERE object_animations.scene_object_id = ?
                  AND scene_objects.scene_id = ?
            )
            """,
            (object_id, scene_id),
        )
        connection.execute(
            """
            DELETE FROM object_animations
            WHERE scene_object_id IN (
                SELECT id
                FROM scene_objects
                WHERE id = ?
                  AND scene_id = ?
            )
            """,
            (object_id, scene_id),
        )
        connection.execute(
            """
            DELETE FROM object_masks
            WHERE scene_object_id IN (
                SELECT id
                FROM scene_objects
                WHERE id = ?
                  AND scene_id = ?
            )
            """,
            (object_id, scene_id),
        )
        connection.execute(
            """
            DELETE FROM object_mask_images
            WHERE scene_object_id IN (
                SELECT id
                FROM scene_objects
                WHERE id = ?
                  AND scene_id = ?
            )
            """,
            (object_id, scene_id),
        )
        connection.execute(
            """
            DELETE FROM scene_objects
            WHERE id = ?
              AND scene_id = ?
            """,
            (object_id, scene_id),
        )


def delete_scene_object_masks(db_path: Path, scene_id: int, object_id: int) -> bool:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id
            FROM scene_objects
            WHERE id = ?
              AND scene_id = ?
            """,
            (object_id, scene_id),
        ).fetchone()
        if row is None:
            return False
        connection.execute(
            """
            UPDATE scene_objects
            SET default_uploaded_file_id = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND scene_id = ?
            """,
            (object_id, scene_id),
        )
        connection.execute(
            """
            DELETE FROM object_masks
            WHERE scene_object_id = ?
            """,
            (object_id,),
        )
        connection.execute(
            """
            DELETE FROM object_mask_images
            WHERE scene_object_id = ?
            """,
            (object_id,),
        )
    return True


def get_scene_object(
    db_path: Path,
    scene_id: int,
    object_id: int,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, scene_id, name, description, prompt, inventory_image_prompt, category, source, sort_order, visible, enabled, keyboard_target_enabled, default_uploaded_file_id, pickup_uploaded_file_id, inventory_image_relative_path, inventory_image_failed, pickup_frame_failed, status, created_at, updated_at
            FROM scene_objects
            WHERE id = ?
              AND scene_id = ?
            """,
            (object_id, scene_id),
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["visible"] = bool(result["visible"])
    result["enabled"] = bool(result["enabled"])
    result["keyboard_target_enabled"] = bool(result["keyboard_target_enabled"])
    result["inventory_image_failed"] = bool(result["inventory_image_failed"])
    result["pickup_frame_failed"] = bool(result["pickup_frame_failed"])
    return result


def set_scene_object_inventory_image(
    db_path: Path,
    scene_id: int,
    object_id: int,
    relative_path: str | None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        connection.execute(
            """
            UPDATE scene_objects
            SET inventory_image_relative_path = ?,
                inventory_image_failed = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND scene_id = ?
            """,
            (relative_path, object_id, scene_id),
        )
    return get_scene_object(db_path, scene_id, object_id)


def set_scene_object_pickup_frame(
    db_path: Path,
    scene_id: int,
    object_id: int,
    uploaded_file_id: int | None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        connection.execute(
            """
            UPDATE scene_objects
            SET pickup_uploaded_file_id = ?,
                pickup_frame_failed = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND scene_id = ?
            """,
            (uploaded_file_id if uploaded_file_id is None else int(uploaded_file_id), object_id, scene_id),
        )
    return get_scene_object(db_path, scene_id, object_id)


def set_scene_object_inventory_image_failed(
    db_path: Path,
    scene_id: int,
    object_id: int,
    failed: bool,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        connection.execute(
            """
            UPDATE scene_objects
            SET inventory_image_failed = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND scene_id = ?
            """,
            (int(bool(failed)), object_id, scene_id),
        )
    return get_scene_object(db_path, scene_id, object_id)


def set_scene_object_pickup_frame_failed(
    db_path: Path,
    scene_id: int,
    object_id: int,
    failed: bool,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        connection.execute(
            """
            UPDATE scene_objects
            SET pickup_frame_failed = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND scene_id = ?
            """,
            (int(bool(failed)), object_id, scene_id),
        )
    return get_scene_object(db_path, scene_id, object_id)


def get_scene_object_for_organization(
    db_path: Path,
    object_id: int,
    organization_id: str,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT scene_objects.id,
                   scene_objects.scene_id,
                   scene_objects.name,
                   scene_objects.description,
                   scene_objects.prompt,
                   scene_objects.inventory_image_prompt,
                   scene_objects.category,
                   scene_objects.source,
                   scene_objects.sort_order,
                   scene_objects.visible,
                   scene_objects.enabled,
                   scene_objects.keyboard_target_enabled,
                   scene_objects.default_uploaded_file_id,
                   scene_objects.pickup_uploaded_file_id,
                   scene_objects.inventory_image_relative_path,
                   scene_objects.inventory_image_failed,
                   scene_objects.pickup_frame_failed,
                   scene_objects.status,
                   scene_objects.created_at,
                   scene_objects.updated_at
            FROM scene_objects
            JOIN scenes ON scenes.id = scene_objects.scene_id
            WHERE scene_objects.id = ?
              AND scenes.organization_id = ?
            """,
            (object_id, organization_id),
        ).fetchone()

    if row is None:
        return None
    result = dict(row)
    result["visible"] = bool(result["visible"])
    result["enabled"] = bool(result["enabled"])
    result["keyboard_target_enabled"] = bool(result["keyboard_target_enabled"])
    result["inventory_image_failed"] = bool(result["inventory_image_failed"])
    result["pickup_frame_failed"] = bool(result["pickup_frame_failed"])
    return result


def list_scene_objects_for_organization(
    db_path: Path,
    organization_id: str,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT scene_objects.id,
                   scene_objects.scene_id,
                   scene_objects.name,
                   scene_objects.visible,
                   scene_objects.enabled,
                   scene_objects.keyboard_target_enabled,
                   scene_objects.default_uploaded_file_id,
                   scene_objects.pickup_uploaded_file_id,
                   scene_objects.inventory_image_relative_path,
                   scene_objects.inventory_image_failed,
                   scene_objects.pickup_frame_failed,
                   scenes.title AS scene_title
            FROM scene_objects
            JOIN scenes ON scenes.id = scene_objects.scene_id
            WHERE scenes.organization_id = ?
            ORDER BY scenes.id ASC, scene_objects.sort_order ASC, scene_objects.id ASC
            """,
            (organization_id,),
        ).fetchall()
    results = []
    for row in rows:
        result = dict(row)
        result["visible"] = bool(result["visible"])
        result["enabled"] = bool(result["enabled"])
        result["keyboard_target_enabled"] = bool(result["keyboard_target_enabled"])
        result["inventory_image_failed"] = bool(result["inventory_image_failed"])
        result["pickup_frame_failed"] = bool(result["pickup_frame_failed"])
        results.append(result)
    return results


def list_object_animations_for_object(
    db_path: Path,
    scene_object_id: int,
    organization_id: str,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        animation_rows = connection.execute(
            """
            SELECT object_animations.id,
                   object_animations.scene_object_id,
                   object_animations.name,
                   object_animations.status,
                   object_animations.created_at,
                   object_animations.updated_at
            FROM object_animations
            JOIN scene_objects ON scene_objects.id = object_animations.scene_object_id
            JOIN scenes ON scenes.id = scene_objects.scene_id
            WHERE object_animations.scene_object_id = ?
              AND scenes.organization_id = ?
            ORDER BY lower(object_animations.name) ASC, object_animations.id ASC
            """,
            (scene_object_id, organization_id),
        ).fetchall()
        animations = [dict(row) for row in animation_rows]
        if not animations:
            return []

        animation_ids = [animation["id"] for animation in animations]
        placeholders = ",".join("?" for _ in animation_ids)
        segment_rows = connection.execute(
            f"""
            SELECT id,
                   object_animation_id,
                   start_frame,
                   end_frame,
                   frame_duration_seconds,
                   sort_order,
                   created_at,
                   updated_at
            FROM object_animation_segments
            WHERE object_animation_id IN ({placeholders})
            ORDER BY sort_order ASC, id ASC
            """,
            animation_ids,
        ).fetchall()

    segments_by_animation_id: dict[int, list[dict[str, Any]]] = {
        animation["id"]: [] for animation in animations
    }
    for row in segment_rows:
        segments_by_animation_id[row["object_animation_id"]].append(dict(row))
    return [
        {
            **animation,
            "segments": segments_by_animation_id[animation["id"]],
        }
        for animation in animations
    ]


def create_object_animation(
    db_path: Path,
    scene_object_id: int,
    name: str,
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO object_animations (scene_object_id, name)
            VALUES (?, ?)
            """,
            (scene_object_id, name.strip()),
        )
        animation_id = int(cursor.lastrowid)
        _insert_object_animation_segments(connection, animation_id, segments)

    return get_object_animation(db_path, animation_id, scene_object_id)


def update_object_animation(
    db_path: Path,
    animation_id: int,
    scene_object_id: int,
    name: str,
    segments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE object_animations
            SET name = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND scene_object_id = ?
            """,
            (name.strip(), animation_id, scene_object_id),
        )
        if cursor.rowcount == 0:
            return None
        connection.execute(
            """
            DELETE FROM object_animation_segments
            WHERE object_animation_id = ?
            """,
            (animation_id,),
        )
        _insert_object_animation_segments(connection, animation_id, segments)

    return get_object_animation(db_path, animation_id, scene_object_id)


def delete_object_animation(
    db_path: Path,
    animation_id: int,
    scene_object_id: int,
) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            DELETE FROM object_animation_segments
            WHERE object_animation_id = ?
            """,
            (animation_id,),
        )
        connection.execute(
            """
            DELETE FROM object_animations
            WHERE id = ?
              AND scene_object_id = ?
            """,
            (animation_id, scene_object_id),
        )


def get_object_animation(
    db_path: Path,
    animation_id: int,
    scene_object_id: int,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        animation = connection.execute(
            """
            SELECT id, scene_object_id, name, status, created_at, updated_at
            FROM object_animations
            WHERE id = ?
              AND scene_object_id = ?
            """,
            (animation_id, scene_object_id),
        ).fetchone()
        if animation is None:
            return None
        segments = connection.execute(
            """
            SELECT id,
                   object_animation_id,
                   start_frame,
                   end_frame,
                   frame_duration_seconds,
                   sort_order,
                   created_at,
                   updated_at
            FROM object_animation_segments
            WHERE object_animation_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (animation_id,),
        ).fetchall()

    return {
        **dict(animation),
        "segments": [dict(row) for row in segments],
    }


def _insert_object_animation_segments(
    connection: sqlite3.Connection,
    animation_id: int,
    segments: list[dict[str, Any]],
) -> None:
    for index, segment in enumerate(segments):
        connection.execute(
            """
            INSERT INTO object_animation_segments (
                object_animation_id,
                start_frame,
                end_frame,
                frame_duration_seconds,
                sort_order
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                animation_id,
                int(segment["start_frame"]),
                int(segment["end_frame"]),
                float(segment["frame_duration_seconds"]),
                index,
            ),
        )


def list_scene_objects_for_scene(db_path: Path, scene_id: int) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, scene_id, name, description, prompt, inventory_image_prompt, category, source, sort_order, visible, enabled, keyboard_target_enabled, default_uploaded_file_id, pickup_uploaded_file_id, inventory_image_relative_path, inventory_image_failed, pickup_frame_failed, status, created_at, updated_at
            FROM scene_objects
            WHERE scene_id = ?
              AND trim(prompt) != ''
            ORDER BY sort_order ASC, id ASC
            """,
            (scene_id,),
        ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        result = dict(row)
        result["visible"] = bool(result["visible"])
        result["enabled"] = bool(result["enabled"])
        result["keyboard_target_enabled"] = bool(result["keyboard_target_enabled"])
        result["inventory_image_failed"] = bool(result["inventory_image_failed"])
        result["pickup_frame_failed"] = bool(result["pickup_frame_failed"])
        results.append(result)
    return results


def object_mask_exists_for_prompt(
    db_path: Path,
    scene_object_id: int,
    uploaded_file_id: int,
    prompt_text: str,
) -> bool:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT prompt_text
            FROM object_masks
            WHERE scene_object_id = ?
              AND uploaded_file_id = ?
            """,
            (scene_object_id, uploaded_file_id),
        ).fetchall()
    if len(rows) != 1:
        return False
    return str(rows[0]["prompt_text"] or "").strip() == prompt_text.strip()


def create_object_mask(
    db_path: Path,
    scene_object_id: int,
    uploaded_file_id: int,
    relative_path: str,
    soft_relative_path: str | None,
    prompt_text: str,
    bbox_json: str | None,
    score: float | None,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        connection.execute(
            """
            DELETE FROM object_masks
            WHERE scene_object_id = ?
              AND uploaded_file_id = ?
            """,
            (scene_object_id, uploaded_file_id),
        )
        cursor = connection.execute(
            """
            INSERT INTO object_masks (
                scene_object_id,
                uploaded_file_id,
                relative_path,
                soft_relative_path,
                prompt_text,
                bbox_json,
                score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scene_object_id,
                uploaded_file_id,
                relative_path,
                soft_relative_path,
                prompt_text.strip(),
                bbox_json,
                score,
            ),
        )
        row = connection.execute(
            """
            SELECT id,
                   scene_object_id,
                   uploaded_file_id,
                   relative_path,
                   soft_relative_path,
                   prompt_text,
                   bbox_json,
                   score,
                   status,
                   created_at,
                   updated_at
            FROM object_masks
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()

    return dict(row)


def get_object_mask_by_id(
    db_path: Path,
    object_mask_id: int,
    organization_id: str,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT object_masks.id,
                   object_masks.scene_object_id,
                   scene_objects.scene_id,
                   object_masks.uploaded_file_id,
                   object_masks.relative_path,
                   object_masks.soft_relative_path,
                   object_masks.prompt_text,
                   object_masks.bbox_json,
                   object_masks.score,
                   object_masks.status,
                   object_masks.created_at,
                   object_masks.updated_at
            FROM object_masks
            JOIN scene_objects ON scene_objects.id = object_masks.scene_object_id
            JOIN scenes ON scenes.id = scene_objects.scene_id
            WHERE object_masks.id = ?
              AND scenes.organization_id = ?
            """,
            (object_mask_id, organization_id),
        ).fetchone()

    return dict(row) if row else None


def list_object_masks_for_object(
    db_path: Path,
    scene_object_id: int,
    organization_id: str,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT object_masks.id,
                   object_masks.scene_object_id,
                   scene_objects.scene_id,
                   object_masks.uploaded_file_id,
                   object_masks.relative_path,
                   object_masks.soft_relative_path,
                   object_masks.prompt_text,
                   object_masks.bbox_json,
                   object_masks.score,
                   object_masks.status,
                   object_masks.created_at,
                   object_masks.updated_at,
                   uploaded_files.original_filename,
                   uploaded_files.relative_path AS original_relative_path
            FROM object_masks
            JOIN scene_objects ON scene_objects.id = object_masks.scene_object_id
            JOIN scenes ON scenes.id = scene_objects.scene_id
            JOIN uploaded_files ON uploaded_files.id = object_masks.uploaded_file_id
            WHERE object_masks.scene_object_id = ?
              AND scenes.organization_id = ?
            """,
            (scene_object_id, organization_id),
        ).fetchall()

    return sorted(
        [dict(row) for row in rows],
        key=lambda row: (_original_filename_sort_key(row), row["id"]),
    )


def touch_object_mask(db_path: Path, object_mask_id: int) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        connection.execute(
            """
            UPDATE object_masks
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (object_mask_id,),
        )
        row = connection.execute(
            """
            SELECT id,
                   scene_object_id,
                   uploaded_file_id,
                   relative_path,
                   soft_relative_path,
                   prompt_text,
                   bbox_json,
                   score,
                   status,
                   created_at,
                   updated_at
            FROM object_masks
            WHERE id = ?
            """,
            (object_mask_id,),
        ).fetchone()

    return dict(row) if row else None


def update_scene_description(
    db_path: Path,
    scene_id: int,
    description: str,
    title: str | None = None,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        if title:
            connection.execute(
                """
                UPDATE scenes
                SET title = ?,
                    description = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (title.strip(), description.strip(), scene_id),
            )
        else:
            connection.execute(
                """
                UPDATE scenes
                SET description = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (description.strip(), scene_id),
            )
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   title,
                   description,
                   presentation_mode,
                   status,
                   representative_uploaded_file_id,
                   representative_hash,
                   created_by_user_id,
                   created_at,
                   updated_at
            FROM scenes
            WHERE id = ?
            """,
            (scene_id,),
        ).fetchone()

    return dict(row)


def update_scene(
    db_path: Path,
    scene_id: int,
    organization_id: str,
    title: str | None = None,
    description: str | None = None,
    presentation_mode: str | None = None,
    background_frame_index: int | None = None,
) -> dict[str, Any] | None:
    assignments: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
    values: list[Any] = []
    if title is not None:
        assignments.append("title = ?")
        values.append(title)
    if description is not None:
        assignments.append("description = ?")
        values.append(description)
    if presentation_mode is not None:
        assignments.append("presentation_mode = ?")
        values.append(presentation_mode)
    if background_frame_index is not None:
        assignments.append("background_frame_index = ?")
        values.append(int(background_frame_index))
    with connect(db_path) as connection:
        cursor = connection.execute(
            f"""
            UPDATE scenes
            SET {", ".join(assignments)}
            WHERE id = ?
              AND organization_id = ?
            """,
            (*values, scene_id, organization_id),
        )
        if cursor.rowcount:
            _refresh_scene_representative(connection, scene_id)
    if cursor.rowcount == 0:
        return None
    return get_scene_with_images(db_path, scene_id)


def merge_scene_into_scene(
    db_path: Path,
    organization_id: str,
    source_scene_id: int,
    target_scene_id: int,
) -> dict[str, Any] | None:
    if source_scene_id == target_scene_id:
        raise ValueError("Source and target scenes must be different")

    with connect(db_path) as connection:
        source_scene = connection.execute(
            """
            SELECT id, organization_id
            FROM scenes
            WHERE id = ?
              AND organization_id = ?
            """,
            (source_scene_id, organization_id),
        ).fetchone()
        target_scene = connection.execute(
            """
            SELECT id, organization_id, presentation_mode
            FROM scenes
            WHERE id = ?
              AND organization_id = ?
            """,
            (target_scene_id, organization_id),
        ).fetchone()
        if source_scene is None or target_scene is None:
            return None

        target_image_offset = connection.execute(
            """
            SELECT COUNT(*) AS image_count
            FROM scene_images
            WHERE scene_id = ?
            """,
            (target_scene_id,),
        ).fetchone()["image_count"]
        target_max_image_sort_order = connection.execute(
            """
            SELECT COALESCE(MAX(sort_order), -1) AS max_sort_order
            FROM scene_images
            WHERE scene_id = ?
            """,
            (target_scene_id,),
        ).fetchone()["max_sort_order"]
        target_max_object_sort_order = connection.execute(
            """
            SELECT COALESCE(MAX(sort_order), -1) AS max_sort_order
            FROM scene_objects
            WHERE scene_id = ?
            """,
            (target_scene_id,),
        ).fetchone()["max_sort_order"]

        source_image_rows = connection.execute(
            """
            SELECT id
            FROM scene_images
            WHERE scene_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (source_scene_id,),
        ).fetchall()
        for index, row in enumerate(source_image_rows, start=1):
            connection.execute(
                """
                UPDATE scene_images
                SET scene_id = ?,
                    sort_order = ?
                WHERE id = ?
                """,
                (target_scene_id, int(target_max_image_sort_order) + index, row["id"]),
            )

        source_object_rows = connection.execute(
            """
            SELECT id
            FROM scene_objects
            WHERE scene_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (source_scene_id,),
        ).fetchall()
        source_object_ids = [int(row["id"]) for row in source_object_rows]
        for index, row in enumerate(source_object_rows, start=1):
            connection.execute(
                """
                UPDATE scene_objects
                SET scene_id = ?,
                    sort_order = ?
                WHERE id = ?
                """,
                (target_scene_id, int(target_max_object_sort_order) + index, row["id"]),
            )

        if source_object_ids and int(target_image_offset) > 0:
            placeholders = ",".join("?" for _ in source_object_ids)
            connection.execute(
                f"""
                UPDATE object_animation_segments
                SET start_frame = start_frame + ?,
                    end_frame = end_frame + ?
                WHERE object_animation_id IN (
                    SELECT id
                    FROM object_animations
                    WHERE scene_object_id IN ({placeholders})
                )
                """,
                (int(target_image_offset), int(target_image_offset), *source_object_ids),
            )

        connection.execute(
            """
            UPDATE scene_mask_prompts
            SET scene_id = ?
            WHERE scene_id = ?
            """,
            (target_scene_id, source_scene_id),
        )
        connection.execute(
            """
            UPDATE scene_interactions
            SET scene_id = ?
            WHERE scene_id = ?
            """,
            (target_scene_id, source_scene_id),
        )
        connection.execute(
            """
            UPDATE global_settings
            SET start_scene_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE organization_id = ?
              AND start_scene_id = ?
            """,
            (target_scene_id, organization_id, source_scene_id),
        )
        connection.execute(
            """
            DELETE FROM overlay_scene_bindings
            WHERE organization_id = ?
              AND overlay_scene_id = ?
            """,
            (organization_id, source_scene_id),
        )
        connection.execute(
            """
            DELETE FROM scenes
            WHERE id = ?
              AND organization_id = ?
            """,
            (source_scene_id, organization_id),
        )

    return get_scene_with_images(db_path, target_scene_id)


def scene_belongs_to_organization(
    db_path: Path,
    scene_id: int,
    organization_id: str,
    project_id: int | None = None,
) -> bool:
    with connect(db_path) as connection:
        if project_id is None:
            row = connection.execute(
                """
                SELECT 1
                FROM scenes
                WHERE id = ?
                  AND organization_id = ?
                """,
                (scene_id, organization_id),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT 1
                FROM scenes
                WHERE id = ?
                  AND organization_id = ?
                  AND project_id = ?
                """,
                (scene_id, organization_id, project_id),
            ).fetchone()

    return row is not None


def create_or_promote_admin(
    db_path: Path,
    organization_id: str,
    email: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    return upsert_user(
        db_path,
        organization_id=organization_id,
        email=email,
        display_name=display_name,
        avatar_url=None,
        role="admin",
    )


def upsert_user(
    db_path: Path,
    organization_id: str,
    email: str,
    display_name: str | None,
    avatar_url: str | None,
    role: str,
) -> dict[str, Any]:
    normalized_email = email.strip().lower()
    with connect(db_path) as connection:
        existing = connection.execute(
            """
            SELECT id
            FROM users
            WHERE email = ?
            """,
            (normalized_email,),
        ).fetchone()
        if existing:
            connection.execute(
                """
                UPDATE users
                SET organization_id = ?,
                    display_name = COALESCE(?, display_name),
                    avatar_url = COALESCE(?, avatar_url),
                    role = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (organization_id, display_name, avatar_url, role, existing["id"]),
            )
            user_id = existing["id"]
        else:
            cursor = connection.execute(
                """
                INSERT INTO users (organization_id, email, display_name, avatar_url, role)
                VALUES (?, ?, ?, ?, ?)
                """,
                (organization_id, normalized_email, display_name, avatar_url, role),
            )
            user_id = cursor.lastrowid

        row = connection.execute(
            """
            SELECT id, organization_id, email, display_name, avatar_url, role, created_at, updated_at
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

    return dict(row)


def get_user_by_email(db_path: Path, email: str) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, organization_id, email, display_name, avatar_url, role, created_at, updated_at
            FROM users
            WHERE email = ?
            """,
            (email.strip().lower(),),
        ).fetchone()

    return dict(row) if row else None


def get_user_by_identity(
    db_path: Path,
    provider: str,
    provider_subject: str,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT users.id,
                   users.organization_id,
                   users.email,
                   users.display_name,
                   users.avatar_url,
                   users.role,
                   users.created_at,
                   users.updated_at
            FROM auth_identities
            JOIN users ON users.id = auth_identities.user_id
            WHERE auth_identities.provider = ?
              AND auth_identities.provider_subject = ?
            """,
            (provider, provider_subject),
        ).fetchone()

    return dict(row) if row else None


def link_identity(
    db_path: Path,
    user_id: int,
    provider: str,
    provider_subject: str,
    email: str,
) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO auth_identities (user_id, provider, provider_subject, email)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(provider, provider_subject)
            DO UPDATE SET user_id = excluded.user_id,
                          email = excluded.email,
                          updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, provider, provider_subject, email.strip().lower()),
        )


def list_projects(db_path: Path, organization_id: str) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id,
                   organization_id,
                   name,
                   sort_order,
                   created_at,
                   updated_at
            FROM projects
            WHERE organization_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (organization_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_project_by_id(db_path: Path, organization_id: str, project_id: int) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   name,
                   sort_order,
                   created_at,
                   updated_at
            FROM projects
            WHERE organization_id = ?
              AND id = ?
            """,
            (organization_id, project_id),
        ).fetchone()
    return dict(row) if row else None


def create_project(db_path: Path, organization_id: str, name: str) -> dict[str, Any]:
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Project name is required.")
    with connect(db_path) as connection:
        next_sort_order = int(connection.execute(
            """
            SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_sort_order
            FROM projects
            WHERE organization_id = ?
            """,
            (organization_id,),
        ).fetchone()["next_sort_order"] or 0)
        cursor = connection.execute(
            """
            INSERT INTO projects (organization_id, name, sort_order)
            VALUES (?, ?, ?)
            """,
            (organization_id, normalized_name, next_sort_order),
        )
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   name,
                   sort_order,
                   created_at,
                   updated_at
            FROM projects
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
    return dict(row)


def update_project(
    db_path: Path,
    *,
    organization_id: str,
    project_id: int,
    name: str | None = None,
) -> dict[str, Any] | None:
    assignments: list[str] = []
    values: list[Any] = []
    if name is not None:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Project name is required.")
        assignments.append("name = ?")
        values.append(normalized_name)
    if not assignments:
        return get_project_by_id(db_path, organization_id, project_id)
    assignments.append("updated_at = CURRENT_TIMESTAMP")
    values.extend([organization_id, project_id])
    with connect(db_path) as connection:
        connection.execute(
            f"""
            UPDATE projects
            SET {", ".join(assignments)}
            WHERE organization_id = ?
              AND id = ?
            """,
            values,
        )
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   name,
                   sort_order,
                   created_at,
                   updated_at
            FROM projects
            WHERE organization_id = ?
              AND id = ?
            """,
            (organization_id, project_id),
        ).fetchone()
    return dict(row) if row else None


def get_default_project_for_organization(db_path: Path, organization_id: str) -> dict[str, Any]:
    with connect(db_path) as connection:
        project_id = _get_or_create_default_project_id(connection, organization_id)
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   name,
                   sort_order,
                   created_at,
                   updated_at
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError("Default project could not be loaded")
    return dict(row)


def set_session_active_project(db_path: Path, token: str, project_id: int) -> dict[str, Any] | None:
    token_hash = hash_token(token)
    with connect(db_path) as connection:
        session_row = connection.execute(
            """
            SELECT sessions.id AS session_id,
                   users.organization_id
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            JOIN projects ON projects.id = ?
            WHERE sessions.token_hash = ?
              AND sessions.expires_at > ?
              AND projects.organization_id = users.organization_id
            """,
            (project_id, token_hash, utc_iso(now_utc())),
        ).fetchone()
        if session_row is None:
            return None
        connection.execute(
            """
            UPDATE sessions
            SET active_project_id = ?
            WHERE id = ?
            """,
            (project_id, int(session_row["session_id"])),
        )
    return get_session_by_token(db_path, token)


def create_session(
    db_path: Path,
    user_id: int,
    expires_in_days: int = 30,
) -> tuple[str, dict[str, Any]]:
    token = make_token()
    created_at = now_utc()
    expires_at = created_at + timedelta(days=expires_in_days)
    with connect(db_path) as connection:
        user_row = connection.execute(
            """
            SELECT organization_id
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        if user_row is None:
            raise RuntimeError("User for session creation was not found")
        active_project_id = _get_or_create_default_project_id(connection, str(user_row["organization_id"]))
        connection.execute(
            """
            INSERT INTO sessions (user_id, token_hash, active_project_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, hash_token(token), active_project_id, utc_iso(created_at), utc_iso(expires_at)),
        )

    session = get_session_by_token(db_path, token)
    if session is None:
        raise RuntimeError("Created session could not be loaded")

    return token, session


def get_session_by_token(db_path: Path, token: str) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT sessions.id AS session_id,
                   sessions.expires_at,
                   sessions.active_project_id,
                   users.id,
                   users.organization_id,
                   users.email,
                   users.display_name,
                   users.avatar_url,
                   users.role,
                   projects.name AS active_project_name,
                   users.created_at,
                   users.updated_at
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            LEFT JOIN projects ON projects.id = sessions.active_project_id
            WHERE sessions.token_hash = ?
              AND sessions.expires_at > ?
            """,
            (hash_token(token), utc_iso(now_utc())),
        ).fetchone()

    return dict(row) if row else None


def delete_session(db_path: Path, token: str) -> None:
    with connect(db_path) as connection:
        connection.execute(
            "DELETE FROM sessions WHERE token_hash = ?",
            (hash_token(token),),
        )


def create_invite(
    db_path: Path,
    organization_id: str,
    created_by_user_id: int,
    role: str = "user",
    email: str | None = None,
    expires_in_days: int = 7,
) -> tuple[str, dict[str, Any]]:
    token = make_token()
    created_at = now_utc()
    expires_at = created_at + timedelta(days=expires_in_days)
    normalized_email = email.strip().lower() if email else None
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO invites (
                organization_id,
                token_hash,
                email,
                role,
                created_by_user_id,
                created_at,
                expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                organization_id,
                hash_token(token),
                normalized_email,
                role,
                created_by_user_id,
                utc_iso(created_at),
                utc_iso(expires_at),
            ),
        )
        row = connection.execute(
            """
            SELECT id, organization_id, email, role, created_by_user_id, created_at, expires_at, used_at, used_by_user_id
            FROM invites
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()

    return token, dict(row)


def get_available_invite(db_path: Path, token: str) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, organization_id, email, role, created_by_user_id, created_at, expires_at, used_at, used_by_user_id
            FROM invites
            WHERE token_hash = ?
              AND used_at IS NULL
              AND expires_at > ?
            """,
            (hash_token(token), utc_iso(now_utc())),
        ).fetchone()

    return dict(row) if row else None


def mark_invite_used(db_path: Path, invite_id: int, user_id: int) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            UPDATE invites
            SET used_at = ?,
                used_by_user_id = ?
            WHERE id = ?
            """,
            (utc_iso(now_utc()), user_id, invite_id),
        )


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    columns = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    if column_name not in {column["name"] for column in columns}:
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        )


def _normalize_object_name(name: str) -> str:
    return " ".join(name.replace("_", " ").strip().lower().split())


def _normalize_prompt_text(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _original_filename_sort_key(row: dict[str, Any] | sqlite3.Row) -> list[tuple[int, int | str]]:
    filename = str(row["original_filename"] or "").casefold()
    parts: list[tuple[int, int | str]] = []
    for part in re.split(r"(\d+)", filename):
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part))
    return parts


def _get_script_line_row(
    connection: sqlite3.Connection,
    organization_id: str,
    line_id: int,
    project_id: int | None = None,
) -> sqlite3.Row | None:
    if project_id is None:
        return connection.execute(
            """
            SELECT id,
                   organization_id,
                   project_id,
                   line_id,
                   script_index,
                   source_text,
                   path_json,
                   path_text,
                   created_at,
                   updated_at
            FROM script_lines
            WHERE organization_id = ?
              AND line_id = ?
            """,
            (organization_id, line_id),
        ).fetchone()
    return connection.execute(
        """
        SELECT id,
               organization_id,
               project_id,
               line_id,
               script_index,
               source_text,
               path_json,
               path_text,
               created_at,
               updated_at
        FROM script_lines
        WHERE organization_id = ?
          AND project_id = ?
          AND line_id = ?
        """,
        (organization_id, project_id, line_id),
    ).fetchone()


def _get_audio_candidate_row(
    connection: sqlite3.Connection,
    organization_id: str,
    candidate_id: int,
    project_id: int | None = None,
) -> sqlite3.Row | None:
    if project_id is None:
        return connection.execute(
            """
            SELECT sac.*
            FROM script_audio_candidates sac
            JOIN script_lines sl ON sl.id = sac.script_line_id
            WHERE sac.id = ?
              AND sl.organization_id = ?
            """,
            (candidate_id, organization_id),
        ).fetchone()
    return connection.execute(
        """
        SELECT sac.*
        FROM script_audio_candidates sac
        JOIN script_lines sl ON sl.id = sac.script_line_id
        WHERE sac.id = ?
          AND sl.organization_id = ?
          AND sl.project_id = ?
        """,
        (candidate_id, organization_id, project_id),
    ).fetchone()


def _collect_script_line_ids_from_action_tree(steps: list[Any], line_ids: set[int]) -> None:
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        if step.get("type") in {"play_audio", "show_subtitle"}:
            for line_id in step.get("script_line_ids") or []:
                try:
                    numeric_id = int(line_id)
                except (TypeError, ValueError):
                    continue
                line_ids.add(numeric_id)
        _collect_script_line_ids_from_action_tree(step.get("then_steps") or [], line_ids)
        _collect_script_line_ids_from_action_tree(step.get("else_steps") or [], line_ids)


def _script_line_summary_from_row(row: sqlite3.Row, language: str) -> dict[str, Any]:
    result = dict(row)
    result["path_parts"] = _json_loads(result.get("path_json"), [])
    translation_id = result.pop("selected_translation_id", None)
    result["selected_translation"] = (
        {
            "id": translation_id,
            "script_line_id": result["id"],
            "language": language,
            "text": result.pop("selected_translation_text") or "",
            "source": result.pop("selected_translation_source") or "",
            "review_status": result.pop("selected_translation_status") or "missing",
            "notes": result.pop("selected_translation_notes") or "",
            "manually_edited": bool(result.pop("selected_translation_manually_edited") or 0),
        }
        if translation_id is not None
        else {
            "id": None,
            "script_line_id": result["id"],
            "language": language,
            "text": "",
            "source": "",
            "review_status": "missing",
            "notes": "",
            "manually_edited": False,
        }
    )
    result["audio_candidate_count"] = int(result["audio_candidate_count"] or 0)
    result["translation_present"] = bool(result.get("translation_present"))
    result["tts_audio_count"] = int(result.get("tts_audio_count") or 0)
    result["reviewed_audio_count"] = int(result.get("reviewed_audio_count") or 0)
    result["selected_audio_count"] = int(result.get("selected_audio_count") or 0)
    result["failed_tts_count"] = int(result.get("failed_tts_count") or 0)
    return result


def _translation_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["manually_edited"] = bool(result["manually_edited"])
    result["meta"] = _json_loads(result.pop("meta_json", "{}"), {})
    return result


def _audio_candidate_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["selected"] = bool(result["selected"])
    if result.get("rank") == -1:
        result["rank"] = None
    result["viseme_events"] = _json_loads(result.pop("viseme_events_json", "[]"), [])
    return result


def _game_variable_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["default_value"] = _json_loads(result.pop("default_value_json", "null"), None)
    return result


def _verb_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["labels"] = _json_loads(result.pop("labels_json", "{}"), {})
    result["enabled"] = bool(result["enabled"])
    return result


def _character_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _character_image_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["is_default"] = bool(result.get("is_default"))
    return result


def _character_object_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["is_viseme_target"] = bool(result.get("is_viseme_target"))
    result["mask_count"] = int(result.get("mask_count") or 0)
    return result


def _character_animation_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _character_animation_frame_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "character_animation_id": int(row["character_animation_id"]),
        "character_image_id": int(row["character_image_id"]),
        "duration_seconds": float(row["duration_seconds"]),
        "sort_order": int(row["sort_order"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "image": {
            "id": int(row["character_image_id"]),
            "component_key": str(row["component_key"]),
            "variant_key": str(row["variant_key"]),
            "kind": str(row["kind"]),
            "relative_path": str(row["relative_path"]),
            "original_filename": str(row["original_filename"] or ""),
            "width": int(row["width"] or 0),
            "height": int(row["height"] or 0),
        },
    }


def _conversation_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _conversation_node_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["enter_actions"] = _json_loads(result.pop("enter_actions_json", "[]"), [])
    return result


def _conversation_choice_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["conditions"] = _json_loads(result.pop("conditions_json", "[]"), [])
    result["actions"] = _json_loads(result.pop("actions_json", "[]"), [])
    result["end_conversation"] = bool(result.get("end_conversation"))
    return result


def _script_audio_candidate_viseme_event_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["start_seconds"] = float(result.get("start_seconds") or 0)
    result["end_seconds"] = float(result.get("end_seconds") or 0)
    result["sort_order"] = int(result.get("sort_order") or 0)
    return result


def _scene_interaction_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["enabled"] = bool(result["enabled"])
    result["trigger"] = _json_loads(result.pop("trigger_json", "{}"), {})
    if result["trigger"].get("type") == "object_hover":
        result["trigger"]["type"] = "object_mouseover"
    result["action_tree"] = _json_loads(result.pop("action_tree_json", "[]"), [])
    return result


def _collect_script_line_reference_step_types(
    steps: list[dict[str, Any]],
    target_line_id: int,
) -> set[str]:
    step_types: set[str] = set()
    for step in steps:
        if step.get("type") in {"show_subtitle", "play_audio"}:
            if target_line_id in {int(item) for item in (step.get("script_line_ids") or []) if item is not None}:
                step_types.add(str(step.get("type")))
        step_types.update(_collect_script_line_reference_step_types(step.get("then_steps") or [], target_line_id))
        step_types.update(_collect_script_line_reference_step_types(step.get("else_steps") or [], target_line_id))
    return step_types


def _json_loads(raw: Any, fallback: Any) -> Any:
    try:
        return json.loads(raw) if raw else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def json_dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"))
