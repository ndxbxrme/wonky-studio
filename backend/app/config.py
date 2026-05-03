from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    organization_id: str
    organization_name: str
    frontend_url: str
    api_base_url: str
    session_cookie_name: str
    session_secret: str
    google_client_id: str | None
    google_client_secret: str | None
    google_redirect_uri: str


def get_settings() -> Settings:
    api_base_url = os.environ.get("WONKY_STUDIO_API_BASE_URL", "http://127.0.0.1:8000")
    return Settings(
        organization_id=os.environ.get("WONKY_STUDIO_ORGANIZATION_ID", "wonky-studio"),
        organization_name=os.environ.get("WONKY_STUDIO_ORGANIZATION_NAME", "Wonky Studio"),
        frontend_url=os.environ.get("WONKY_STUDIO_FRONTEND_URL", "http://127.0.0.1:5173"),
        api_base_url=api_base_url,
        session_cookie_name=os.environ.get(
            "WONKY_STUDIO_SESSION_COOKIE_NAME",
            "wonky_studio_session",
        ),
        session_secret=os.environ.get(
            "WONKY_STUDIO_SESSION_SECRET",
            "dev-session-secret-change-me",
        ),
        google_client_id=os.environ.get("WONKY_STUDIO_GOOGLE_CLIENT_ID"),
        google_client_secret=os.environ.get("WONKY_STUDIO_GOOGLE_CLIENT_SECRET"),
        google_redirect_uri=os.environ.get(
            "WONKY_STUDIO_GOOGLE_REDIRECT_URI",
            f"{api_base_url}/api/auth/google/callback",
        ),
    )

