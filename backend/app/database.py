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


def get_database_path() -> Path:
    configured_path = os.environ.get("WONKY_STUDIO_DB_PATH")
    return Path(configured_path) if configured_path else DEFAULT_DB_PATH


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


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
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
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
                status TEXT NOT NULL DEFAULT 'draft',
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS scene_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scene_id INTEGER NOT NULL,
                uploaded_file_id INTEGER NOT NULL UNIQUE,
                perceptual_hash TEXT NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (scene_id) REFERENCES scenes(id),
                FOREIGN KEY (uploaded_file_id) REFERENCES uploaded_files(id)
            )
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
                category TEXT NOT NULL DEFAULT 'other',
                source TEXT NOT NULL DEFAULT 'manual',
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (scene_id) REFERENCES scenes(id)
            )
            """
        )
        _ensure_column(connection, "scene_objects", "prompt", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "scene_objects", "category", "TEXT NOT NULL DEFAULT 'other'")
        _ensure_column(connection, "scene_objects", "source", "TEXT NOT NULL DEFAULT 'manual'")
        connection.execute(
            """
            UPDATE scene_objects
            SET prompt = name
            WHERE trim(prompt) = ''
            """
        )
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
                FOREIGN KEY (scene_id) REFERENCES scenes(id)
            )
            """
        )
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


def reset_workspace_tables(db_path: Path) -> list[str]:
    tables = [
        "scene_interactions",
        "game_variables",
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
    progress_total: int = 0,
    message: str = "",
) -> dict[str, Any]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO processing_jobs (
                organization_id,
                job_type,
                scene_id,
                progress_total,
                message
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (organization_id, job_type, scene_id, progress_total, message),
        )
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   job_type,
                   status,
                   scene_id,
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


def claim_next_processing_job(db_path: Path) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   job_type,
                   status,
                   scene_id,
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


def list_audio_assets(db_path: Path, organization_id: str) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id,
                   organization_id,
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
            ORDER BY kind ASC, id ASC
            """,
            (organization_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def create_audio_asset(
    db_path: Path,
    organization_id: str,
    name: str,
    kind: str,
    relative_path: str,
    original_filename: str,
    content_type: str | None,
    file_size: int,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO audio_assets (
                organization_id,
                name,
                kind,
                relative_path,
                original_filename,
                content_type,
                file_size
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                organization_id,
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
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
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
    return dict(row) if row else None


def update_audio_asset(
    db_path: Path,
    organization_id: str,
    audio_asset_id: int,
    name: str,
    kind: str,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        connection.execute(
            """
            UPDATE audio_assets
            SET name = ?,
                kind = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND organization_id = ?
            """,
            (name, kind, audio_asset_id, organization_id),
        )
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
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
    return dict(row) if row else None


def delete_audio_asset(
    db_path: Path,
    organization_id: str,
    audio_asset_id: int,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
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
        if row is None:
            return None
        connection.execute(
            """
            DELETE FROM audio_assets
            WHERE id = ?
              AND organization_id = ?
            """,
            (audio_asset_id, organization_id),
        )
    return dict(row)


def upsert_script_line(
    db_path: Path,
    organization_id: str,
    line_id: int,
    script_index: int,
    source_text: str,
    path_parts: list[str],
) -> dict[str, Any]:
    path_json = json.dumps(path_parts, ensure_ascii=False)
    path_text = " / ".join(path_parts)
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO script_lines (
                organization_id,
                line_id,
                script_index,
                source_text,
                path_json,
                path_text
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (organization_id, line_id) DO UPDATE SET
                script_index = excluded.script_index,
                source_text = excluded.source_text,
                path_json = excluded.path_json,
                path_text = excluded.path_text,
                updated_at = CURRENT_TIMESTAMP
            """,
            (organization_id, line_id, script_index, source_text, path_json, path_text),
        )
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
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
    return dict(row)


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


def list_script_lines(
    db_path: Path,
    organization_id: str,
    language: str = "en",
    query: str = "",
    path: str = "",
    translation_status: str = "",
    audio_status: str = "",
    audio_source: str = "",
    missing_audio: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    where = ["sl.organization_id = ?"]
    values: list[Any] = [organization_id]
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

    where_sql = " AND ".join(where)
    with connect(db_path) as connection:
        total_row = connection.execute(
            f"SELECT COUNT(*) AS count FROM script_lines sl WHERE {where_sql}",
            values,
        ).fetchone()
        rows = connection.execute(
            f"""
            SELECT sl.id,
                   sl.organization_id,
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
                   (
                       SELECT COUNT(*)
                       FROM script_audio_candidates sac
                       WHERE sac.script_line_id = sl.id
                         AND sac.language = ?
                         AND sac.relative_path != ''
                         AND sac.manifest_status != 'error'
                   ) AS audio_candidate_count
            FROM script_lines sl
            LEFT JOIN script_translations st
              ON st.script_line_id = sl.id
             AND st.language = ?
            WHERE {where_sql}
            ORDER BY sl.line_id ASC
            LIMIT ?
            OFFSET ?
            """,
            [language, language, *values, limit, offset],
        ).fetchall()

    return {
        "items": [_script_line_summary_from_row(row, language) for row in rows],
        "total": int(total_row["count"] if total_row else 0),
        "limit": limit,
        "offset": offset,
    }


def get_script_line_detail(
    db_path: Path,
    organization_id: str,
    line_id: int,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        line = _get_script_line_row(connection, organization_id, line_id)
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
            SELECT *
            FROM script_audio_candidates
            WHERE script_line_id = ?
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
    }


def list_script_path_options(
    db_path: Path,
    organization_id: str,
    limit: int = 500,
) -> list[str]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT path_text
            FROM script_lines
            WHERE organization_id = ?
              AND path_text != ''
            ORDER BY path_text ASC
            LIMIT ?
            """,
            (organization_id, limit),
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
) -> dict[str, Any] | None:
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


def update_script_audio_candidate(
    db_path: Path,
    organization_id: str,
    candidate_id: int,
    review_status: str,
    notes: str = "",
    selected: bool | None = None,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        candidate = _get_audio_candidate_row(connection, organization_id, candidate_id)
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
        row = _get_audio_candidate_row(connection, organization_id, candidate_id)
    return _audio_candidate_from_row(row) if row else None


def get_script_audio_candidate_by_id(
    db_path: Path,
    organization_id: str,
    candidate_id: int,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = _get_audio_candidate_row(connection, organization_id, candidate_id)
    return _audio_candidate_from_row(row) if row else None


def list_game_variables(db_path: Path, organization_id: str) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id,
                   organization_id,
                   name,
                   value_type,
                   default_value_json,
                   description,
                   created_at,
                   updated_at
            FROM game_variables
            WHERE organization_id = ?
            ORDER BY lower(name) ASC, id ASC
            """,
            (organization_id,),
        ).fetchall()
    return [_game_variable_from_row(row) for row in rows]


def get_game_variable_by_id(
    db_path: Path,
    organization_id: str,
    variable_id: int,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
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
    return _game_variable_from_row(row) if row else None


def create_game_variable(
    db_path: Path,
    organization_id: str,
    name: str,
    value_type: str,
    default_value: Any,
    description: str = "",
) -> dict[str, Any]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO game_variables (
                organization_id,
                name,
                value_type,
                default_value_json,
                description
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                organization_id,
                name.strip(),
                value_type,
                json.dumps(default_value, separators=(",", ":")),
                description.strip(),
            ),
        )
    created = get_game_variable_by_id(db_path, organization_id, int(cursor.lastrowid))
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
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
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
            """,
            (
                name.strip(),
                value_type,
                json.dumps(default_value, separators=(",", ":")),
                description.strip(),
                variable_id,
                organization_id,
            ),
        )
    if cursor.rowcount == 0:
        return None
    return get_game_variable_by_id(db_path, organization_id, variable_id)


def delete_game_variable(
    db_path: Path,
    organization_id: str,
    variable_id: int,
) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            DELETE FROM game_variables
            WHERE id = ?
              AND organization_id = ?
            """,
            (variable_id, organization_id),
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


def create_upload_batch(
    db_path: Path,
    organization_id: str,
    created_by_user_id: int,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO upload_batches (organization_id, created_by_user_id)
            VALUES (?, ?)
            """,
            (organization_id, created_by_user_id),
        )
        row = connection.execute(
            """
            SELECT id, organization_id, created_by_user_id, status, file_count, total_bytes, created_at
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
    uploaded_by_user_id: int,
    original_filename: str,
    stored_filename: str,
    relative_path: str,
    content_type: str | None,
    file_size: int,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO uploaded_files (
                batch_id,
                organization_id,
                uploaded_by_user_id,
                original_filename,
                stored_filename,
                relative_path,
                content_type,
                file_size
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                organization_id,
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
            SELECT id, organization_id, created_by_user_id, status, file_count, total_bytes, created_at
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
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id,
                   batch_id,
                   organization_id,
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
            """,
            (uploaded_file_id, organization_id),
        ).fetchone()

    return dict(row) if row else None


def list_upload_batches(
    db_path: Path,
    organization_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, organization_id, created_by_user_id, status, file_count, total_bytes, created_at
            FROM upload_batches
            WHERE organization_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (organization_id, limit),
        ).fetchall()

    return [dict(row) for row in rows]


def list_uploaded_image_files_for_batch(
    db_path: Path,
    batch_id: int,
    organization_id: str,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id,
                   batch_id,
                   organization_id,
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
              AND (
                content_type LIKE 'image/%'
                OR lower(original_filename) GLOB '*.jpg'
                OR lower(original_filename) GLOB '*.jpeg'
                OR lower(original_filename) GLOB '*.png'
                OR lower(original_filename) GLOB '*.webp'
              )
            ORDER BY id ASC
            """,
            (batch_id, organization_id),
        ).fetchall()

    return sorted(
        [dict(row) for row in rows],
        key=lambda row: (_original_filename_sort_key(row), row["id"]),
    )


def list_scene_image_hashes(
    db_path: Path,
    organization_id: str,
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
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
            """,
            (organization_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def create_scene(
    db_path: Path,
    organization_id: str,
    created_by_user_id: int,
    representative_uploaded_file_id: int,
    representative_hash: str,
    title: str,
    description: str,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO scenes (
                organization_id,
                title,
                description,
                representative_uploaded_file_id,
                representative_hash,
                created_by_user_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                organization_id,
                title,
                description,
                representative_uploaded_file_id,
                representative_hash,
                created_by_user_id,
            ),
        )
        row = connection.execute(
            """
            SELECT id,
                   organization_id,
                   title,
                   description,
                   status,
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


def add_scene_image(
    db_path: Path,
    scene_id: int,
    uploaded_file_id: int,
    perceptual_hash: str,
    width: int,
    height: int,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO scene_images (
                scene_id,
                uploaded_file_id,
                perceptual_hash,
                width,
                height
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(uploaded_file_id)
            DO UPDATE SET scene_id = excluded.scene_id,
                          perceptual_hash = excluded.perceptual_hash,
                          width = excluded.width,
                          height = excluded.height
            """,
            (scene_id, uploaded_file_id, perceptual_hash, width, height),
        )
        row = connection.execute(
            """
            SELECT id, scene_id, uploaded_file_id, perceptual_hash, width, height, created_at
            FROM scene_images
            WHERE uploaded_file_id = ?
            """,
            (uploaded_file_id,),
        ).fetchone()

    return dict(row)


def get_scene_with_images(db_path: Path, scene_id: int) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        scene = connection.execute(
            """
            SELECT id,
                   organization_id,
                   title,
                   description,
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
                   scene_images.created_at,
                   uploaded_files.original_filename,
                   uploaded_files.relative_path
            FROM scene_images
            JOIN uploaded_files ON uploaded_files.id = scene_images.uploaded_file_id
            WHERE scene_images.scene_id = ?
            ORDER BY scene_images.id ASC
            """,
            (scene_id,),
        ).fetchall()
        images = sorted(
            [dict(row) for row in images],
            key=lambda row: (_original_filename_sort_key(row), row["id"]),
        )
        objects = connection.execute(
            """
            SELECT scene_objects.id,
                   scene_objects.scene_id,
                   scene_objects.name,
                   scene_objects.description,
                   scene_objects.prompt,
                   scene_objects.category,
                   scene_objects.source,
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
            ORDER BY lower(scene_objects.name) ASC
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
                "masks": masks_by_object_id[row["id"]],
            }
            for row in objects
        ],
    }


def list_scenes(db_path: Path, organization_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT scenes.id,
                   scenes.organization_id,
                   scenes.title,
                   scenes.description,
                   scenes.status,
                   scenes.representative_uploaded_file_id,
                   scenes.representative_hash,
                   scenes.created_by_user_id,
                   scenes.created_at,
                   scenes.updated_at,
                   COUNT(DISTINCT scene_images.id) AS image_count,
                   COUNT(DISTINCT scene_objects.id) AS object_count
            FROM scenes
            LEFT JOIN scene_images ON scene_images.scene_id = scenes.id
            LEFT JOIN scene_objects ON scene_objects.scene_id = scenes.id
            WHERE scenes.organization_id = ?
            GROUP BY scenes.id
            ORDER BY scenes.id DESC
            LIMIT ?
            """,
            (organization_id, limit),
        ).fetchall()

    return [dict(row) for row in rows]


def create_scene_object(
    db_path: Path,
    scene_id: int,
    name: str,
    description: str = "",
    prompt: str | None = None,
    category: str = "other",
    source: str = "manual",
) -> dict[str, Any]:
    normalized_name = name.strip()
    normalized_prompt = (prompt or normalized_name).strip()
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO scene_objects (scene_id, name, description, prompt, category, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                scene_id,
                normalized_name,
                description.strip(),
                normalized_prompt,
                category.strip(),
                source.strip(),
            ),
        )
        row = connection.execute(
            """
            SELECT id, scene_id, name, description, prompt, category, source, status, created_at, updated_at
            FROM scene_objects
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()

    return dict(row)


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
                   scene_images.created_at,
                   uploaded_files.original_filename,
                   uploaded_files.relative_path,
                   uploaded_files.content_type
            FROM scene_images
            JOIN uploaded_files ON uploaded_files.id = scene_images.uploaded_file_id
            WHERE scene_images.scene_id = ?
            ORDER BY scene_images.id ASC
            """,
            (scene_id,),
        ).fetchall()

    return sorted(
        [dict(row) for row in rows],
        key=lambda row: (_original_filename_sort_key(row), row["id"]),
    )


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
    category: str = "other",
    source: str = "vlm",
) -> tuple[dict[str, Any], bool]:
    normalized_name = _normalize_object_name(name)
    with connect(db_path) as connection:
        existing = connection.execute(
            """
            SELECT id, scene_id, name, description, prompt, category, source, status, created_at, updated_at
            FROM scene_objects
            WHERE scene_id = ?
              AND lower(name) = ?
            """,
            (scene_id, normalized_name.lower()),
        ).fetchone()
        if existing:
            return dict(existing), False

        cursor = connection.execute(
            """
            INSERT INTO scene_objects (scene_id, name, description, prompt, category, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                scene_id,
                normalized_name,
                description.strip(),
                (prompt or normalized_name).strip(),
                category.strip() or "other",
                source.strip() or "vlm",
            ),
        )
        row = connection.execute(
            """
            SELECT id, scene_id, name, description, prompt, category, source, status, created_at, updated_at
            FROM scene_objects
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()

    return dict(row), True


def update_scene_object(
    db_path: Path,
    scene_id: int,
    object_id: int,
    name: str | None = None,
    description: str | None = None,
    prompt: str | None = None,
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


def get_scene_object(
    db_path: Path,
    scene_id: int,
    object_id: int,
) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, scene_id, name, description, prompt, category, source, status, created_at, updated_at
            FROM scene_objects
            WHERE id = ?
              AND scene_id = ?
            """,
            (object_id, scene_id),
        ).fetchone()

    return dict(row) if row else None


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
                   scene_objects.category,
                   scene_objects.source,
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

    return dict(row) if row else None


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
            SELECT id, scene_id, name, description, prompt, category, source, status, created_at, updated_at
            FROM scene_objects
            WHERE scene_id = ?
              AND trim(prompt) != ''
            ORDER BY lower(name) ASC
            """,
            (scene_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def object_mask_exists_for_prompt(
    db_path: Path,
    scene_object_id: int,
    uploaded_file_id: int,
    prompt_text: str,
) -> bool:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM object_masks
            WHERE scene_object_id = ?
              AND uploaded_file_id = ?
              AND prompt_text = ?
            """,
            (scene_object_id, uploaded_file_id, prompt_text.strip()),
        ).fetchone()

    return row is not None


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


def scene_belongs_to_organization(
    db_path: Path,
    scene_id: int,
    organization_id: str,
) -> bool:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM scenes
            WHERE id = ?
              AND organization_id = ?
            """,
            (scene_id, organization_id),
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


def create_session(
    db_path: Path,
    user_id: int,
    expires_in_days: int = 30,
) -> tuple[str, dict[str, Any]]:
    token = make_token()
    created_at = now_utc()
    expires_at = created_at + timedelta(days=expires_in_days)
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO sessions (user_id, token_hash, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, hash_token(token), utc_iso(created_at), utc_iso(expires_at)),
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
                   users.id,
                   users.organization_id,
                   users.email,
                   users.display_name,
                   users.avatar_url,
                   users.role,
                   users.created_at,
                   users.updated_at
            FROM sessions
            JOIN users ON users.id = sessions.user_id
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
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT id,
               organization_id,
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


def _get_audio_candidate_row(
    connection: sqlite3.Connection,
    organization_id: str,
    candidate_id: int,
) -> sqlite3.Row | None:
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
    return result


def _game_variable_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["default_value"] = _json_loads(result.pop("default_value_json", "null"), None)
    return result


def _scene_interaction_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["enabled"] = bool(result["enabled"])
    result["trigger"] = _json_loads(result.pop("trigger_json", "{}"), {})
    result["action_tree"] = _json_loads(result.pop("action_tree_json", "[]"), [])
    return result


def _json_loads(raw: Any, fallback: Any) -> Any:
    try:
        return json.loads(raw) if raw else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def json_dumps(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"))
