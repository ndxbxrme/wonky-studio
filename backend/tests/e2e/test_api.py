from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.database import create_or_promote_admin, create_session, upsert_user
from app.main import create_app


@contextmanager
def api_client(tmp_path: Path) -> Iterator[tuple[TestClient, Path, Settings]]:
    db_path = tmp_path / "test.sqlite3"
    settings = Settings(
        organization_id="wonky-studio-test",
        organization_name="Wonky Studio Test",
        frontend_url="http://127.0.0.1:5173",
        api_base_url="http://127.0.0.1:8000",
        session_cookie_name="wonky_studio_session_test",
        session_secret="test-session-secret",
        google_client_id=None,
        google_client_secret=None,
        google_redirect_uri="http://127.0.0.1:8000/api/auth/google/callback",
    )
    app = create_app(db_path, settings)

    with TestClient(app) as client:
        yield client, db_path, settings


def authenticate(client: TestClient, db_path: Path, settings: Settings, role: str = "user"):
    user = upsert_user(
        db_path,
        organization_id=settings.organization_id,
        email=f"{role}@example.com",
        display_name=f"Test {role.title()}",
        avatar_url=None,
        role=role,
    )
    session_token, _ = create_session(db_path, user["id"])
    client.cookies.set(settings.session_cookie_name, session_token)
    return user


def test_health_check_responds(tmp_path):
    with api_client(tmp_path) as (client, _, _):
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_session_returns_current_user_when_authenticated(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        user = authenticate(client, db_path, settings, role="admin")
        response = client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json()["user"]["email"] == user["email"]
    assert response.json()["user"]["role"] == "admin"
    assert response.json()["organization_id"] == settings.organization_id


def test_admin_can_generate_invite_link(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        admin = create_or_promote_admin(
            db_path,
            organization_id=settings.organization_id,
            email="admin@example.com",
            display_name="Admin User",
        )
        session_token, _ = create_session(db_path, admin["id"])
        client.cookies.set(settings.session_cookie_name, session_token)

        response = client.post(
            "/api/invites",
            json={
                "email": "artist@example.com",
                "role": "user",
                "expires_in_days": 14,
            },
        )

    assert response.status_code == 201
    invite = response.json()
    assert invite["email"] == "artist@example.com"
    assert invite["role"] == "user"
    assert invite["organization_id"] == settings.organization_id
    assert invite["invite_link"].startswith(f"{settings.frontend_url}/?invite=")


def test_regular_user_cannot_generate_invite_link(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="user")

        response = client.post("/api/invites", json={"role": "user"})

    assert response.status_code == 403


def test_assets_require_authentication(tmp_path):
    with api_client(tmp_path) as (client, _, _):
        response = client.get("/api/assets")

    assert response.status_code == 401


def test_assets_can_be_created_and_listed_by_authenticated_user(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="user")
        create_response = client.post(
            "/api/assets",
            json={
                "name": "Knight Idle Animation",
                "asset_type": "animation",
                "status": "in_progress",
            },
        )
        list_response = client.get("/api/assets")

    assert create_response.status_code == 201
    created_asset = create_response.json()
    assert created_asset["id"] == 1
    assert created_asset["organization_id"] == settings.organization_id
    assert created_asset["name"] == "Knight Idle Animation"
    assert created_asset["asset_type"] == "animation"
    assert created_asset["status"] == "in_progress"
    assert "created_at" in created_asset

    assert list_response.status_code == 200
    assert list_response.json() == [created_asset]


def test_google_login_requires_oauth_configuration(tmp_path):
    with api_client(tmp_path) as (client, _, _):
        response = client.get("/api/auth/google/login", follow_redirects=False)

    assert response.status_code == 503
