from __future__ import annotations

import os
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
