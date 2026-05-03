from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field

from .config import Settings, get_settings
from .database import (
    create_asset,
    create_invite,
    create_session,
    delete_session,
    get_available_invite,
    get_database_path,
    get_session_by_token,
    get_user_by_email,
    get_user_by_identity,
    init_database,
    link_identity,
    list_assets,
    mark_invite_used,
    upsert_user,
)
from .security import sign_state, verify_state


GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


class AssetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    asset_type: str = Field(min_length=1, max_length=80)
    status: str = Field(default="planned", min_length=1, max_length=80)


class Asset(AssetCreate):
    id: int
    organization_id: str
    created_at: str


class User(BaseModel):
    id: int
    organization_id: str
    email: EmailStr
    display_name: str | None = None
    avatar_url: str | None = None
    role: str


class SessionResponse(BaseModel):
    user: User | None
    organization_id: str
    auth_providers: list[str]


class InviteCreate(BaseModel):
    email: EmailStr | None = None
    role: str = Field(default="user", pattern="^(admin|user)$")
    expires_in_days: int = Field(default=7, ge=1, le=30)


class Invite(BaseModel):
    id: int
    organization_id: str
    email: EmailStr | None
    role: str
    created_by_user_id: int
    created_at: str
    expires_at: str
    used_at: str | None
    used_by_user_id: int | None
    invite_link: str


def create_app(
    db_path: Path | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    database_path = db_path or get_database_path()
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_database(
            database_path,
            organization_id=app_settings.organization_id,
            organization_name=app_settings.organization_name,
        )
        yield

    app = FastAPI(title="Wonky Studio API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[app_settings.frontend_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def current_user(
        session_token: str | None = Cookie(
            default=None,
            alias=app_settings.session_cookie_name,
        ),
    ) -> dict[str, Any]:
        if not session_token:
            raise HTTPException(status_code=401, detail="Not authenticated")

        session = get_session_by_token(database_path, session_token)
        if session is None:
            raise HTTPException(status_code=401, detail="Session expired")

        return session

    def current_admin(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Admin role required")
        return user

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/auth/session", response_model=SessionResponse)
    def get_session(
        session_token: str | None = Cookie(
            default=None,
            alias=app_settings.session_cookie_name,
        ),
    ) -> dict[str, Any]:
        user = get_session_by_token(database_path, session_token) if session_token else None
        return {
            "user": _public_user(user) if user else None,
            "organization_id": app_settings.organization_id,
            "auth_providers": ["google"],
        }

    @app.get("/api/auth/google/login")
    def google_login(invite: str | None = None, next: str | None = None) -> RedirectResponse:
        _require_google_config(app_settings)
        state = sign_state(
            {
                "provider": "google",
                "invite": invite,
                "next": _safe_next(next, app_settings.frontend_url),
            },
            app_settings.session_secret,
        )
        query = urlencode(
            {
                "client_id": app_settings.google_client_id,
                "redirect_uri": app_settings.google_redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "prompt": "select_account",
            }
        )
        return RedirectResponse(f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{query}")

    @app.get("/api/auth/google/callback")
    async def google_callback(
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> RedirectResponse:
        _require_google_config(app_settings)
        if error:
            return _frontend_redirect(app_settings, f"/login?error={error}")
        if not code or not state:
            return _frontend_redirect(app_settings, "/login?error=missing_oauth_response")

        state_payload = verify_state(state, app_settings.session_secret)
        if state_payload is None or state_payload.get("provider") != "google":
            return _frontend_redirect(app_settings, "/login?error=invalid_state")

        profile = await _load_google_profile(app_settings, code)
        try:
            user = _resolve_oauth_user(
                database_path,
                app_settings.organization_id,
                provider="google",
                provider_subject=profile["sub"],
                email=profile["email"],
                display_name=profile.get("name"),
                avatar_url=profile.get("picture"),
                invite_token=state_payload.get("invite"),
            )
        except HTTPException as exc:
            return _frontend_redirect(
                app_settings,
                f"/login?error={_error_code(str(exc.detail))}",
            )
        link_identity(database_path, user["id"], "google", profile["sub"], profile["email"])
        session_token, _ = create_session(database_path, user["id"])
        response = _frontend_redirect(
            app_settings,
            state_payload.get("next") or app_settings.frontend_url,
        )
        _set_session_cookie(response, app_settings, session_token)
        return response

    @app.post("/api/auth/logout")
    def logout(
        response: Response,
        session_token: str | None = Cookie(
            default=None,
            alias=app_settings.session_cookie_name,
        ),
    ) -> dict[str, bool]:
        if session_token:
            delete_session(database_path, session_token)
        response.delete_cookie(app_settings.session_cookie_name, path="/")
        return {"ok": True}

    @app.post("/api/invites", response_model=Invite, status_code=201)
    def post_invite(
        invite: InviteCreate,
        admin: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        raw_token, created_invite = create_invite(
            database_path,
            organization_id=admin["organization_id"],
            created_by_user_id=admin["id"],
            role=invite.role,
            email=str(invite.email) if invite.email else None,
            expires_in_days=invite.expires_in_days,
        )
        return {
            **created_invite,
            "invite_link": f"{app_settings.frontend_url}/?invite={raw_token}",
        }

    @app.get("/api/assets", response_model=list[Asset])
    def get_assets(user: dict[str, Any] = Depends(current_user)) -> list[dict]:
        return list_assets(database_path, user["organization_id"])

    @app.post("/api/assets", response_model=Asset, status_code=201)
    def post_asset(
        asset: AssetCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict:
        return create_asset(
            database_path,
            organization_id=user["organization_id"],
            name=asset.name,
            asset_type=asset.asset_type,
            status=asset.status,
        )

    return app


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "organization_id": user["organization_id"],
        "email": user["email"],
        "display_name": user["display_name"],
        "avatar_url": user["avatar_url"],
        "role": user["role"],
    }


def _require_google_config(settings: Settings) -> None:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")


async def _load_google_profile(settings: Settings, code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as client:
        token_response = await client.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        userinfo_response = await client.get(
            GOOGLE_USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        userinfo_response.raise_for_status()

    profile = userinfo_response.json()
    if not profile.get("sub") or not profile.get("email"):
        raise HTTPException(status_code=502, detail="Google profile was incomplete")
    if profile.get("email_verified") is False:
        raise HTTPException(status_code=403, detail="Google email is not verified")
    return profile


def _resolve_oauth_user(
    db_path: Path,
    organization_id: str,
    provider: str,
    provider_subject: str,
    email: str,
    display_name: str | None,
    avatar_url: str | None,
    invite_token: str | None,
) -> dict[str, Any]:
    user = get_user_by_identity(db_path, provider, provider_subject)
    if user:
        return upsert_user(
            db_path,
            organization_id=user["organization_id"],
            email=user["email"],
            display_name=display_name,
            avatar_url=avatar_url,
            role=user["role"],
        )

    user = get_user_by_email(db_path, email)
    if user:
        return upsert_user(
            db_path,
            organization_id=user["organization_id"],
            email=user["email"],
            display_name=display_name,
            avatar_url=avatar_url,
            role=user["role"],
        )

    if not invite_token:
        raise HTTPException(status_code=403, detail="Invite required")

    invite = get_available_invite(db_path, invite_token)
    if invite is None:
        raise HTTPException(status_code=403, detail="Invite is invalid or expired")

    if invite["email"] and invite["email"] != email.strip().lower():
        raise HTTPException(status_code=403, detail="Invite was issued to a different email")

    user = upsert_user(
        db_path,
        organization_id=invite["organization_id"] or organization_id,
        email=email,
        display_name=display_name,
        avatar_url=avatar_url,
        role=invite["role"],
    )
    mark_invite_used(db_path, invite["id"], user["id"])
    return user


def _safe_next(next_url: str | None, frontend_url: str) -> str:
    if not next_url:
        return frontend_url
    if next_url.startswith("/") and not next_url.startswith("//"):
        return f"{frontend_url}{next_url}"
    if next_url.startswith(frontend_url):
        return next_url
    return frontend_url


def _frontend_redirect(settings: Settings, target: str) -> RedirectResponse:
    if target.startswith("http://") or target.startswith("https://"):
        return RedirectResponse(target)
    return RedirectResponse(f"{settings.frontend_url}{target}")


def _set_session_cookie(
    response: RedirectResponse,
    settings: Settings,
    session_token: str,
) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        httponly=True,
        secure=settings.frontend_url.startswith("https://"),
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
        path="/",
    )


def _error_code(message: str) -> str:
    return (
        message.lower()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("'", "")
        .replace('"', "")
    )


app = create_app()
