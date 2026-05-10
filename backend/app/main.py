from __future__ import annotations

import asyncio
import json
import sqlite3
from io import BytesIO
from contextlib import asynccontextmanager
from pathlib import Path
from re import sub
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from fastapi import Body, Cookie, Depends, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
from pydantic import BaseModel, EmailStr, Field

from .config import Settings, get_settings
from .database import (
    add_uploaded_file,
    create_asset,
    create_game_variable,
    create_invite,
    create_object_animation,
    create_processing_job,
    create_object_mask,
    create_session,
    create_scene_interaction,
    create_scene_object_if_missing,
    create_scene_object,
    create_scene_mask_prompt,
    create_upload_batch,
    delete_object_animation,
    delete_game_variable,
    delete_scene_mask_prompt,
    delete_scene_object,
    delete_scene_interaction,
    delete_session,
    fail_processing_job,
    get_available_invite,
    get_database_path,
    get_mask_candidate_by_id,
    get_object_mask_by_id,
    get_game_variable_by_id,
    get_script_audio_candidate_by_id,
    get_script_line_detail,
    get_scene_interaction,
    get_scene_object_for_organization,
    get_active_processing_job_for_scene,
    get_processing_job,
    get_session_by_token,
    get_scene_with_images,
    get_scene_mask_prompt,
    get_upload_batch,
    get_uploaded_file_by_id,
    get_user_by_email,
    get_user_by_identity,
    init_database,
    link_identity,
    list_assets,
    list_game_variables,
    list_object_animations_for_object,
    list_object_masks_for_object,
    list_script_lines,
    list_script_path_options,
    list_scene_objects_for_scene,
    list_scene_images_for_scene,
    list_scene_interactions,
    list_scenes,
    list_upload_batches,
    object_mask_exists_for_prompt,
    mark_invite_used,
    object_animation_belongs_to_object,
    claim_next_processing_job,
    complete_processing_job,
    requeue_interrupted_processing_jobs,
    reset_workspace_tables,
    scene_belongs_to_organization,
    scene_object_belongs_to_scene,
    script_line_ids_exist,
    touch_object_mask,
    update_game_variable,
    update_scene_interaction,
    update_script_audio_candidate,
    update_script_translation,
    update_object_animation,
    update_scene_mask_prompt,
    update_scene_object,
    update_scene_description,
    update_processing_job_progress,
    upsert_user,
)
from .object_rendering import render_masked_object_crop
from .scene_processing import process_upload_batch_into_scene
from .security import sign_state, verify_state
from .segmentation import SegmentationProvider, build_segmentation_provider
from .script_import import import_script_audio_data
from .vlm import SceneVlmProvider, build_scene_vlm_provider, scene_draft_to_dict


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


class UploadedFileRecord(BaseModel):
    id: int
    batch_id: int
    organization_id: str
    uploaded_by_user_id: int
    original_filename: str
    stored_filename: str
    relative_path: str
    content_type: str | None
    file_size: int
    processing_status: str
    created_at: str


class UploadBatch(BaseModel):
    id: int
    organization_id: str
    created_by_user_id: int
    status: str
    file_count: int
    total_bytes: int
    created_at: str
    files: list[UploadedFileRecord] = []


class UploadBatchSummary(BaseModel):
    id: int
    organization_id: str
    created_by_user_id: int
    status: str
    file_count: int
    total_bytes: int
    created_at: str


class SceneImage(BaseModel):
    id: int
    scene_id: int
    uploaded_file_id: int
    perceptual_hash: str
    width: int
    height: int
    created_at: str
    original_filename: str
    relative_path: str


class SceneObject(BaseModel):
    id: int
    scene_id: int
    name: str
    description: str
    prompt: str
    category: str
    source: str
    status: str
    created_at: str
    updated_at: str
    mask_image_count: int = 0
    animation_count: int = 0
    masks: list["ObjectMask"] = []


class ObjectAnimationSegment(BaseModel):
    id: int
    object_animation_id: int
    start_frame: int
    end_frame: int
    frame_duration_seconds: float
    sort_order: int
    created_at: str
    updated_at: str


class ObjectAnimation(BaseModel):
    id: int
    scene_object_id: int
    name: str
    status: str
    created_at: str
    updated_at: str
    segments: list[ObjectAnimationSegment] = []


class ObjectMask(BaseModel):
    id: int
    scene_object_id: int
    uploaded_file_id: int
    relative_path: str
    soft_relative_path: str | None
    prompt_text: str
    bbox_json: str | None
    score: float | None
    status: str
    created_at: str
    updated_at: str | None = None
    original_filename: str | None = None


class MaskCandidate(BaseModel):
    id: int
    scene_mask_prompt_id: int
    scene_image_id: int
    uploaded_file_id: int
    raw_relative_path: str
    soft_relative_path: str | None
    bbox_json: str | None
    score: float | None
    selected: bool
    status: str
    created_at: str
    original_filename: str | None = None


class SceneMaskPrompt(BaseModel):
    id: int
    scene_id: int
    text: str
    source: str
    enabled: bool
    status: str
    created_at: str
    updated_at: str
    candidates: list[MaskCandidate] = []


class Scene(BaseModel):
    id: int
    organization_id: str
    title: str
    description: str
    status: str
    representative_uploaded_file_id: int | None
    representative_hash: str | None
    created_by_user_id: int
    created_at: str
    updated_at: str
    images: list[SceneImage] = []
    objects: list[SceneObject] = []


class SceneSummary(BaseModel):
    id: int
    organization_id: str
    title: str
    description: str
    status: str
    representative_uploaded_file_id: int | None
    representative_hash: str | None
    created_by_user_id: int
    created_at: str
    updated_at: str
    image_count: int
    object_count: int


class BatchSceneProcessResult(BaseModel):
    scene: Scene
    created: bool
    matched_existing: bool
    processed_file_count: int


class SceneObjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    prompt: str | None = Field(default=None, max_length=160)


class SceneObjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    prompt: str | None = Field(default=None, min_length=1, max_length=160)


class ObjectAnimationSegmentInput(BaseModel):
    start_frame: int = Field(ge=0, le=100000)
    end_frame: int = Field(ge=0, le=100000)
    frame_duration_seconds: float = Field(gt=0, le=60)


class ObjectAnimationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    segments: list[ObjectAnimationSegmentInput] = Field(default_factory=list, max_length=200)


class ObjectAnimationUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    segments: list[ObjectAnimationSegmentInput] = Field(default_factory=list, max_length=200)


class SceneMaskPromptCreate(BaseModel):
    text: str = Field(min_length=1, max_length=120)
    enabled: bool = True


class SceneMaskPromptUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None


class SceneDraftObject(BaseModel):
    name: str
    category: str
    description: str


class SceneDraftResponse(BaseModel):
    scene_description: str
    scene_key: str
    objects: list[SceneDraftObject]


class SceneVlmAnalysisResult(BaseModel):
    scene: Scene
    draft: SceneDraftResponse
    created_object_count: int
    skipped_existing_object_count: int


class SceneMaskExtractionResult(BaseModel):
    scene: Scene
    processed_image_count: int
    prompt_count: int
    created_candidate_count: int
    skipped_existing_count: int


class ObjectMaskProcessRequest(BaseModel):
    operation: str = Field(pattern="^(grow|fill_holes)$")
    apply_all: bool = False
    pixels: int = Field(default=2, ge=1, le=32)


class ProcessingJob(BaseModel):
    id: int
    organization_id: str
    job_type: str
    status: str
    scene_id: int | None
    progress_current: int
    progress_total: int
    message: str
    result_json: str | None
    error: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None


class ResetDatabaseResult(BaseModel):
    ok: bool
    cleared_tables: list[str]


class ScriptImportRequest(BaseModel):
    audio_root: str | None = None


class ScriptImportResult(BaseModel):
    script_lines: int
    translations: int
    narrator_candidates: int
    tts_candidates: int
    missing_narrator_line_ids: list[int]
    skipped_files: list[str]


class ScriptTranslation(BaseModel):
    id: int | None = None
    script_line_id: int
    language: str
    text: str
    source: str
    review_status: str
    notes: str = ""
    manually_edited: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


class ScriptAudioCandidate(BaseModel):
    id: int
    script_line_id: int
    language: str
    source_type: str
    manifest_status: str
    review_status: str
    relative_path: str
    original_path: str
    selected: bool
    rank: int | None
    score: float | None
    text_score: float | None
    quality_score: float | None
    duration_seconds: float | None
    transcript_match: str
    notes: str
    error: str
    source_file: str
    start_seconds: float | None
    end_seconds: float | None
    created_at: str
    updated_at: str


class ScriptLineSummary(BaseModel):
    id: int
    organization_id: str
    line_id: int
    script_index: int
    source_text: str
    path_json: str
    path_text: str
    path_parts: list[str]
    created_at: str
    updated_at: str
    selected_translation: ScriptTranslation
    audio_candidate_count: int


class ScriptLineDetail(BaseModel):
    id: int
    organization_id: str
    line_id: int
    script_index: int
    source_text: str
    path_json: str
    path_text: str
    path_parts: list[str]
    created_at: str
    updated_at: str
    translations: list[ScriptTranslation]
    audio_candidates: list[ScriptAudioCandidate]


class ScriptLineListResponse(BaseModel):
    items: list[ScriptLineSummary]
    total: int
    limit: int
    offset: int


class ScriptTranslationUpdate(BaseModel):
    text: str = Field(default="", max_length=5000)
    review_status: str = Field(pattern="^(needs_review|approved|needs_edit|missing)$")
    notes: str = Field(default="", max_length=1000)


class ScriptAudioCandidateUpdate(BaseModel):
    review_status: str = Field(pattern="^(candidate|needs_review|approved|needs_edit|missing|rejected)$")
    notes: str = Field(default="", max_length=1000)
    selected: bool | None = None


class GameVariableCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    value_type: str = Field(pattern="^(bool|string|number)$")
    default_value: Any = None
    description: str = Field(default="", max_length=500)


class GameVariable(GameVariableCreate):
    id: int
    organization_id: str
    created_at: str
    updated_at: str


class InteractionTrigger(BaseModel):
    type: str = Field(
        pattern="^(scene_enter|scene_exit|object_hover|object_click|object_use|variable_changed)$"
    )
    object_id: int | None = None
    variable_id: int | None = None


class SceneInteractionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    enabled: bool = True
    trigger: InteractionTrigger
    action_tree: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


class SceneInteraction(SceneInteractionCreate):
    id: int
    scene_id: int
    created_at: str
    updated_at: str


class SceneInteractionsExport(BaseModel):
    scene_id: int
    variables: list[GameVariable]
    interactions: list[SceneInteraction]


class PreviewImageFrame(BaseModel):
    frame_index: int
    uploaded_file_id: int
    original_filename: str
    width: int
    height: int


class PreviewObjectRender(BaseModel):
    frame_index: int | None = None
    uploaded_file_id: int
    object_mask_id: int
    original_filename: str
    left: int
    top: int
    width: int
    height: int
    url: str
    cache_key: str


class PreviewAnimationFrame(BaseModel):
    frame_index: int
    duration_seconds: float
    original_filename: str
    render: PreviewObjectRender | None = None


class PreviewObjectAnimation(BaseModel):
    id: int
    name: str
    frames: list[PreviewAnimationFrame] = []


class PreviewObjectState(BaseModel):
    id: int
    name: str
    visible: bool = True
    default_render: PreviewObjectRender | None = None
    animations: list[PreviewObjectAnimation] = []


class ScenePreview(BaseModel):
    scene_id: int
    title: str
    description: str
    width: int
    height: int
    images: list[PreviewImageFrame] = []
    objects: list[PreviewObjectState] = []


def create_app(
    db_path: Path | None = None,
    settings: Settings | None = None,
    vlm_provider: SceneVlmProvider | None = None,
    segmentation_provider: SegmentationProvider | None = None,
) -> FastAPI:
    database_path = db_path or get_database_path()
    app_settings = settings or get_settings()
    scene_vlm_provider = vlm_provider
    vlm_provider_error = None
    if scene_vlm_provider is None:
        try:
            scene_vlm_provider = build_scene_vlm_provider(app_settings)
        except ValueError as exc:
            vlm_provider_error = str(exc)
    scene_segmentation_provider = segmentation_provider
    segmentation_provider_error = None
    if scene_segmentation_provider is None:
        try:
            scene_segmentation_provider = build_segmentation_provider(app_settings)
        except ValueError as exc:
            segmentation_provider_error = str(exc)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_database(
            database_path,
            organization_id=app_settings.organization_id,
            organization_name=app_settings.organization_name,
        )
        requeue_interrupted_processing_jobs(database_path)
        worker_task = asyncio.create_task(
            _processing_job_worker(
                database_path=database_path,
                settings=app_settings,
                segmentation_provider=scene_segmentation_provider,
                segmentation_provider_error=segmentation_provider_error,
            )
        )
        try:
            yield
        finally:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="Wonky Studio API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_allowed_origins(app_settings.frontend_url),
        allow_origin_regex=_cors_allowed_origin_regex(),
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

    @app.post("/api/admin/reset-database", response_model=ResetDatabaseResult)
    def post_reset_database(
        admin: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        _ = admin
        return {
            "ok": True,
            "cleared_tables": reset_workspace_tables(database_path),
        }

    @app.post("/api/admin/import-script-audio", response_model=ScriptImportResult)
    def post_import_script_audio(
        request: ScriptImportRequest,
        admin: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        audio_root = Path(request.audio_root) if request.audio_root else app_settings.script_audio_root
        try:
            return import_script_audio_data(
                database_path,
                audio_root=audio_root,
                organization_id=admin["organization_id"],
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/script-lines", response_model=ScriptLineListResponse)
    def get_script_lines(
        q: str = "",
        path: str = "",
        language: str = "en",
        translation_status: str = "",
        audio_status: str = "",
        audio_source: str = "",
        missing_audio: bool = False,
        limit: int = 50,
        offset: int = 0,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        return list_script_lines(
            database_path,
            organization_id=user["organization_id"],
            language=language,
            query=q.strip(),
            path=path.strip(),
            translation_status=translation_status.strip(),
            audio_status=audio_status.strip(),
            audio_source=audio_source.strip(),
            missing_audio=missing_audio,
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )

    @app.get("/api/script-lines/paths", response_model=list[str])
    def get_script_line_paths(user: dict[str, Any] = Depends(current_user)) -> list[str]:
        return list_script_path_options(database_path, user["organization_id"])

    @app.get("/api/script-lines/{line_id}", response_model=ScriptLineDetail)
    def get_script_line(
        line_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        line = get_script_line_detail(database_path, user["organization_id"], line_id)
        if line is None:
            raise HTTPException(status_code=404, detail="Script line not found")
        return line

    @app.patch(
        "/api/script-lines/{line_id}/translations/{language}",
        response_model=ScriptTranslation,
    )
    def patch_script_translation(
        line_id: int,
        language: str,
        update: ScriptTranslationUpdate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        translation = update_script_translation(
            database_path,
            organization_id=user["organization_id"],
            line_id=line_id,
            language=language,
            text=update.text,
            review_status=update.review_status,
            notes=update.notes,
        )
        if translation is None:
            raise HTTPException(status_code=404, detail="Script line not found")
        return translation

    @app.patch("/api/script-audio-candidates/{candidate_id}", response_model=ScriptAudioCandidate)
    def patch_script_audio_candidate(
        candidate_id: int,
        update: ScriptAudioCandidateUpdate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        candidate = update_script_audio_candidate(
            database_path,
            organization_id=user["organization_id"],
            candidate_id=candidate_id,
            review_status=update.review_status,
            notes=update.notes,
            selected=update.selected,
        )
        if candidate is None:
            raise HTTPException(status_code=404, detail="Audio candidate not found")
        return candidate

    @app.get("/api/script-audio-candidates/{candidate_id}/content")
    def get_script_audio_content(
        candidate_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> FileResponse:
        candidate = get_script_audio_candidate_by_id(
            database_path,
            user["organization_id"],
            candidate_id,
        )
        if candidate is None or not candidate["relative_path"]:
            raise HTTPException(status_code=404, detail="Audio candidate not found")
        file_path = _safe_child_path(app_settings.script_audio_root, candidate["relative_path"])
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="Audio file not found")
        return FileResponse(
            file_path,
            media_type="audio/ogg",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/api/variables", response_model=list[GameVariable])
    def get_variables(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
        return list_game_variables(database_path, user["organization_id"])

    @app.post("/api/variables", response_model=GameVariable, status_code=201)
    def post_variable(
        variable: GameVariableCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        default_value = _validate_variable_value(variable.value_type, variable.default_value)
        try:
            return create_game_variable(
                database_path,
                organization_id=user["organization_id"],
                name=variable.name,
                value_type=variable.value_type,
                default_value=default_value,
                description=variable.description,
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Variable name already exists") from exc

    @app.patch("/api/variables/{variable_id}", response_model=GameVariable)
    def patch_variable(
        variable_id: int,
        variable: GameVariableCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        default_value = _validate_variable_value(variable.value_type, variable.default_value)
        try:
            updated = update_game_variable(
                database_path,
                organization_id=user["organization_id"],
                variable_id=variable_id,
                name=variable.name,
                value_type=variable.value_type,
                default_value=default_value,
                description=variable.description,
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Variable name already exists") from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="Variable not found")
        return updated

    @app.delete("/api/variables/{variable_id}", status_code=204)
    def delete_variable_endpoint(
        variable_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> Response:
        delete_game_variable(database_path, user["organization_id"], variable_id)
        return Response(status_code=204)

    @app.get(
        "/api/scenes/{scene_id}/interactions",
        response_model=list[SceneInteraction],
        response_model_exclude_none=True,
    )
    def get_scene_interactions_endpoint(
        scene_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        _require_scene(database_path, scene_id, user["organization_id"])
        return list_scene_interactions(database_path, scene_id, user["organization_id"])

    @app.post(
        "/api/scenes/{scene_id}/interactions",
        response_model=SceneInteraction,
        response_model_exclude_none=True,
        status_code=201,
    )
    def post_scene_interaction(
        scene_id: int,
        interaction: SceneInteractionCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        _require_scene(database_path, scene_id, user["organization_id"])
        trigger = _normalize_interaction_trigger(
            database_path,
            scene_id,
            user["organization_id"],
            interaction.trigger.model_dump(exclude_none=True),
        )
        action_tree = _normalize_action_tree(
            database_path,
            scene_id,
            user["organization_id"],
            interaction.action_tree,
        )
        return create_scene_interaction(
            database_path,
            scene_id=scene_id,
            organization_id=user["organization_id"],
            name=interaction.name,
            enabled=interaction.enabled,
            trigger=trigger,
            action_tree=action_tree,
        )

    @app.get(
        "/api/scenes/{scene_id}/interactions/validation-json",
        response_model=SceneInteractionsExport,
        response_model_exclude_none=True,
    )
    def get_scene_interactions_validation_json(
        scene_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        _require_scene(database_path, scene_id, user["organization_id"])
        return {
            "scene_id": scene_id,
            "variables": list_game_variables(database_path, user["organization_id"]),
            "interactions": list_scene_interactions(
                database_path,
                scene_id,
                user["organization_id"],
            ),
        }

    @app.patch(
        "/api/scenes/{scene_id}/interactions/{interaction_id}",
        response_model=SceneInteraction,
        response_model_exclude_none=True,
    )
    def patch_scene_interaction(
        scene_id: int,
        interaction_id: int,
        interaction: SceneInteractionCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        _require_scene(database_path, scene_id, user["organization_id"])
        trigger = _normalize_interaction_trigger(
            database_path,
            scene_id,
            user["organization_id"],
            interaction.trigger.model_dump(exclude_none=True),
        )
        action_tree = _normalize_action_tree(
            database_path,
            scene_id,
            user["organization_id"],
            interaction.action_tree,
        )
        updated = update_scene_interaction(
            database_path,
            scene_id=scene_id,
            interaction_id=interaction_id,
            organization_id=user["organization_id"],
            name=interaction.name,
            enabled=interaction.enabled,
            trigger=trigger,
            action_tree=action_tree,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Interaction not found")
        return updated

    @app.delete("/api/scenes/{scene_id}/interactions/{interaction_id}", status_code=204)
    def delete_scene_interaction_endpoint(
        scene_id: int,
        interaction_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> Response:
        _require_scene(database_path, scene_id, user["organization_id"])
        delete_scene_interaction(
            database_path,
            scene_id=scene_id,
            interaction_id=interaction_id,
            organization_id=user["organization_id"],
        )
        return Response(status_code=204)

    @app.get("/api/uploads/batches", response_model=list[UploadBatchSummary])
    def get_upload_batches(user: dict[str, Any] = Depends(current_user)) -> list[dict]:
        return list_upload_batches(database_path, user["organization_id"])

    @app.post("/api/uploads/batches", response_model=UploadBatch, status_code=201)
    async def post_upload_batch(
        files: list[UploadFile] = File(...),
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if not files:
            raise HTTPException(status_code=400, detail="At least one file is required")

        batch = create_upload_batch(
            database_path,
            organization_id=user["organization_id"],
            created_by_user_id=user["id"],
        )
        batch_root = _batch_storage_root(
            app_settings.storage_root,
            user["organization_id"],
            batch["id"],
        )
        batch_root.mkdir(parents=True, exist_ok=True)

        for upload in files:
            original_filename = _safe_filename(upload.filename or "upload.bin")
            stored_filename = f"{uuid4().hex}-{original_filename}"
            stored_path = batch_root / stored_filename
            file_size = await _write_upload(upload, stored_path)
            add_uploaded_file(
                database_path,
                batch_id=batch["id"],
                organization_id=user["organization_id"],
                uploaded_by_user_id=user["id"],
                original_filename=original_filename,
                stored_filename=stored_filename,
                relative_path=str(
                    Path(user["organization_id"]) / str(batch["id"]) / stored_filename
                ),
                content_type=upload.content_type,
                file_size=file_size,
            )

        created_batch = get_upload_batch(database_path, batch["id"])
        if created_batch is None:
            raise RuntimeError("Created upload batch could not be loaded")
        return created_batch

    @app.post(
        "/api/uploads/batches/{batch_id}/process-scene",
        response_model=BatchSceneProcessResult,
    )
    def post_process_upload_batch_scene(
        batch_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        try:
            return process_upload_batch_into_scene(
                database_path,
                storage_root=app_settings.storage_root,
                batch_id=batch_id,
                organization_id=user["organization_id"],
                user_id=user["id"],
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/scenes", response_model=list[SceneSummary])
    def get_scenes(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
        return list_scenes(database_path, user["organization_id"])

    @app.get("/api/scenes/{scene_id}", response_model=Scene)
    def get_scene(
        scene_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        scene = get_scene_with_images(database_path, scene_id)
        if scene is None or scene["organization_id"] != user["organization_id"]:
            raise HTTPException(status_code=404, detail="Scene not found")
        return scene

    @app.post("/api/scenes/{scene_id}/objects", response_model=SceneObject, status_code=201)
    def post_scene_object(
        scene_id: int,
        scene_object: SceneObjectCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if not scene_belongs_to_organization(
            database_path,
            scene_id=scene_id,
            organization_id=user["organization_id"],
        ):
            raise HTTPException(status_code=404, detail="Scene not found")
        created_object = create_scene_object(
            database_path,
            scene_id=scene_id,
            name=scene_object.name,
            description=scene_object.description,
            prompt=scene_object.prompt,
        )
        return created_object

    @app.patch("/api/scenes/{scene_id}/objects/{object_id}", response_model=SceneObject)
    def patch_scene_object(
        scene_id: int,
        object_id: int,
        scene_object: SceneObjectUpdate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if not scene_belongs_to_organization(
            database_path,
            scene_id=scene_id,
            organization_id=user["organization_id"],
        ):
            raise HTTPException(status_code=404, detail="Scene not found")
        updated_object = update_scene_object(
            database_path,
            scene_id=scene_id,
            object_id=object_id,
            name=scene_object.name,
            description=scene_object.description,
            prompt=scene_object.prompt,
        )
        if updated_object is None:
            raise HTTPException(status_code=404, detail="Object not found")
        return {**updated_object, "mask_image_count": 0, "masks": []}

    @app.delete("/api/scenes/{scene_id}/objects/{object_id}", status_code=204)
    def delete_scene_object_endpoint(
        scene_id: int,
        object_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> Response:
        if not scene_belongs_to_organization(
            database_path,
            scene_id=scene_id,
            organization_id=user["organization_id"],
        ):
            raise HTTPException(status_code=404, detail="Scene not found")
        delete_scene_object(database_path, scene_id=scene_id, object_id=object_id)
        return Response(status_code=204)

    @app.get("/api/scene-objects/{object_id}/animations", response_model=list[ObjectAnimation])
    def get_object_animations(
        object_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        scene_object = get_scene_object_for_organization(
            database_path,
            object_id=object_id,
            organization_id=user["organization_id"],
        )
        if scene_object is None:
            raise HTTPException(status_code=404, detail="Object not found")
        return list_object_animations_for_object(
            database_path,
            scene_object_id=object_id,
            organization_id=user["organization_id"],
        )

    @app.post(
        "/api/scene-objects/{object_id}/animations",
        response_model=ObjectAnimation,
        status_code=201,
    )
    def post_object_animation(
        object_id: int,
        animation: ObjectAnimationCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        scene_object = get_scene_object_for_organization(
            database_path,
            object_id=object_id,
            organization_id=user["organization_id"],
        )
        if scene_object is None:
            raise HTTPException(status_code=404, detail="Object not found")
        return create_object_animation(
            database_path,
            scene_object_id=object_id,
            name=animation.name,
            segments=_animation_segments_payload(animation.segments),
        )

    @app.patch(
        "/api/scene-objects/{object_id}/animations/{animation_id}",
        response_model=ObjectAnimation,
    )
    def patch_object_animation(
        object_id: int,
        animation_id: int,
        animation: ObjectAnimationUpdate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        scene_object = get_scene_object_for_organization(
            database_path,
            object_id=object_id,
            organization_id=user["organization_id"],
        )
        if scene_object is None:
            raise HTTPException(status_code=404, detail="Object not found")
        updated_animation = update_object_animation(
            database_path,
            animation_id=animation_id,
            scene_object_id=object_id,
            name=animation.name,
            segments=_animation_segments_payload(animation.segments),
        )
        if updated_animation is None:
            raise HTTPException(status_code=404, detail="Animation not found")
        return updated_animation

    @app.delete("/api/scene-objects/{object_id}/animations/{animation_id}", status_code=204)
    def delete_object_animation_endpoint(
        object_id: int,
        animation_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> Response:
        scene_object = get_scene_object_for_organization(
            database_path,
            object_id=object_id,
            organization_id=user["organization_id"],
        )
        if scene_object is None:
            raise HTTPException(status_code=404, detail="Object not found")
        delete_object_animation(
            database_path,
            animation_id=animation_id,
            scene_object_id=object_id,
        )
        return Response(status_code=204)

    @app.post(
        "/api/scenes/{scene_id}/analyze-vlm",
        response_model=SceneVlmAnalysisResult,
    )
    async def post_scene_vlm_analysis(
        scene_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if vlm_provider_error:
            raise HTTPException(status_code=503, detail=vlm_provider_error)
        if scene_vlm_provider is None:
            raise HTTPException(status_code=503, detail="VLM provider is not configured")

        scene = get_scene_with_images(database_path, scene_id)
        if scene is None or scene["organization_id"] != user["organization_id"]:
            raise HTTPException(status_code=404, detail="Scene not found")

        uploaded_file_id = scene["representative_uploaded_file_id"]
        if uploaded_file_id is None and scene["images"]:
            uploaded_file_id = scene["images"][0]["uploaded_file_id"]
        if uploaded_file_id is None:
            raise HTTPException(status_code=400, detail="Scene does not have an image to analyze")

        uploaded_file = get_uploaded_file_by_id(
            database_path,
            uploaded_file_id=uploaded_file_id,
            organization_id=user["organization_id"],
        )
        if uploaded_file is None:
            raise HTTPException(status_code=404, detail="Representative image not found")

        image_path = app_settings.storage_root / uploaded_file["relative_path"]
        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Representative image content not found")

        try:
            draft = await scene_vlm_provider.analyze_scene(image_path)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"VLM request failed: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=f"VLM response was invalid: {exc}") from exc

        if draft.scene_description:
            update_scene_description(
                database_path,
                scene_id=scene_id,
                description=draft.scene_description,
                title=_draft_scene_title(scene, draft.scene_key),
            )

        created_object_count = 0
        skipped_existing_object_count = 0
        for draft_object in draft.objects:
            _, created = create_scene_object_if_missing(
                database_path,
                scene_id=scene_id,
                name=draft_object.name,
                description=draft_object.description,
                prompt=draft_object.name,
                category=draft_object.category,
                source="vlm",
            )
            if created:
                created_object_count += 1
            else:
                skipped_existing_object_count += 1

        updated_scene = get_scene_with_images(database_path, scene_id)
        if updated_scene is None:
            raise RuntimeError("Analyzed scene could not be loaded")

        return {
            "scene": updated_scene,
            "draft": scene_draft_to_dict(draft),
            "created_object_count": created_object_count,
            "skipped_existing_object_count": skipped_existing_object_count,
        }

    @app.post(
        "/api/scenes/{scene_id}/mask-prompts",
        response_model=SceneMaskPrompt,
        status_code=201,
    )
    def post_scene_mask_prompt(
        scene_id: int,
        prompt: SceneMaskPromptCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if not scene_belongs_to_organization(
            database_path,
            scene_id=scene_id,
            organization_id=user["organization_id"],
        ):
            raise HTTPException(status_code=404, detail="Scene not found")
        created_prompt, _ = create_scene_mask_prompt(
            database_path,
            scene_id=scene_id,
            text=prompt.text,
            source="manual",
            enabled=prompt.enabled,
        )
        return {**created_prompt, "candidates": []}

    @app.patch(
        "/api/scenes/{scene_id}/mask-prompts/{prompt_id}",
        response_model=SceneMaskPrompt,
    )
    def patch_scene_mask_prompt(
        scene_id: int,
        prompt_id: int,
        prompt: SceneMaskPromptUpdate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if not scene_belongs_to_organization(
            database_path,
            scene_id=scene_id,
            organization_id=user["organization_id"],
        ):
            raise HTTPException(status_code=404, detail="Scene not found")
        updated_prompt = update_scene_mask_prompt(
            database_path,
            prompt_id=prompt_id,
            scene_id=scene_id,
            text=prompt.text,
            enabled=prompt.enabled,
        )
        if updated_prompt is None:
            raise HTTPException(status_code=404, detail="Mask prompt not found")
        return {**updated_prompt, "candidates": []}

    @app.delete("/api/scenes/{scene_id}/mask-prompts/{prompt_id}", status_code=204)
    def delete_scene_prompt(
        scene_id: int,
        prompt_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> Response:
        if not scene_belongs_to_organization(
            database_path,
            scene_id=scene_id,
            organization_id=user["organization_id"],
        ):
            raise HTTPException(status_code=404, detail="Scene not found")
        if get_scene_mask_prompt(database_path, prompt_id=prompt_id, scene_id=scene_id) is None:
            raise HTTPException(status_code=404, detail="Mask prompt not found")
        delete_scene_mask_prompt(database_path, prompt_id=prompt_id, scene_id=scene_id)
        return Response(status_code=204)

    @app.post(
        "/api/scenes/{scene_id}/extract-masks",
        response_model=ProcessingJob,
    )
    def post_extract_scene_masks(
        scene_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if segmentation_provider_error:
            raise HTTPException(status_code=503, detail=segmentation_provider_error)
        if scene_segmentation_provider is None:
            raise HTTPException(status_code=503, detail="Segmentation provider is not configured")
        scene = get_scene_with_images(database_path, scene_id)
        if scene is None or scene["organization_id"] != user["organization_id"]:
            raise HTTPException(status_code=404, detail="Scene not found")

        scene_objects = list_scene_objects_for_scene(database_path, scene_id)
        images = list_scene_images_for_scene(database_path, scene_id)
        if not scene_objects:
            raise HTTPException(status_code=400, detail="Scene does not have any objects with prompts")
        if not images:
            raise HTTPException(status_code=400, detail="Scene does not have any images")

        progress_total = _count_mask_extraction_work(database_path, scene_objects, images)
        return create_processing_job(
            database_path,
            organization_id=user["organization_id"],
            job_type="mask_extraction",
            scene_id=scene_id,
            progress_total=progress_total,
            message="Queued mask extraction",
        )

    @app.get("/api/jobs/{job_id}", response_model=ProcessingJob)
    def get_job(
        job_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        job = get_processing_job(
            database_path,
            job_id=job_id,
            organization_id=user["organization_id"],
        )
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    @app.get("/api/scenes/{scene_id}/jobs/active", response_model=ProcessingJob | None)
    def get_active_scene_job(
        scene_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any] | None:
        if not scene_belongs_to_organization(
            database_path,
            scene_id=scene_id,
            organization_id=user["organization_id"],
        ):
            raise HTTPException(status_code=404, detail="Scene not found")
        return get_active_processing_job_for_scene(
            database_path,
            organization_id=user["organization_id"],
            scene_id=scene_id,
            job_type="mask_extraction",
        )

    @app.get("/api/uploads/files/{uploaded_file_id}/content")
    def get_uploaded_file_content(
        uploaded_file_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> FileResponse:
        uploaded_file = get_uploaded_file_by_id(
            database_path,
            uploaded_file_id=uploaded_file_id,
            organization_id=user["organization_id"],
        )
        if uploaded_file is None:
            raise HTTPException(status_code=404, detail="Uploaded file not found")

        file_path = app_settings.storage_root / uploaded_file["relative_path"]
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Uploaded file content not found")

        return FileResponse(
            file_path,
            media_type=uploaded_file["content_type"],
            filename=uploaded_file["original_filename"],
        )

    @app.get("/api/mask-candidates/{candidate_id}/{variant}")
    def get_mask_candidate_content(
        candidate_id: int,
        variant: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> FileResponse:
        if variant not in {"raw", "soft"}:
            raise HTTPException(status_code=404, detail="Mask variant not found")
        candidate = get_mask_candidate_by_id(
            database_path,
            candidate_id=candidate_id,
            organization_id=user["organization_id"],
        )
        if candidate is None:
            raise HTTPException(status_code=404, detail="Mask candidate not found")
        relative_path = (
            candidate["raw_relative_path"]
            if variant == "raw"
            else candidate["soft_relative_path"]
        )
        if not relative_path:
            raise HTTPException(status_code=404, detail="Mask variant not found")
        file_path = app_settings.storage_root / relative_path
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Mask file not found")
        return FileResponse(
            file_path,
            media_type="image/png",
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @app.get("/api/object-masks/{object_mask_id}/{variant}")
    def get_object_mask_content(
        object_mask_id: int,
        variant: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> FileResponse:
        if variant not in {"raw", "soft"}:
            raise HTTPException(status_code=404, detail="Mask variant not found")
        object_mask = get_object_mask_by_id(
            database_path,
            object_mask_id=object_mask_id,
            organization_id=user["organization_id"],
        )
        if object_mask is None:
            raise HTTPException(status_code=404, detail="Object mask not found")
        relative_path = (
            object_mask["relative_path"]
            if variant == "raw"
            else object_mask["soft_relative_path"]
        )
        if not relative_path:
            raise HTTPException(status_code=404, detail="Mask variant not found")
        file_path = app_settings.storage_root / relative_path
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Mask file not found")
        return FileResponse(
            file_path,
            media_type="image/png",
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @app.put("/api/object-masks/{object_mask_id}/content", response_model=ObjectMask)
    async def put_object_mask_content(
        object_mask_id: int,
        content: bytes = Body(media_type="image/png"),
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        object_mask = get_object_mask_by_id(
            database_path,
            object_mask_id=object_mask_id,
            organization_id=user["organization_id"],
        )
        if object_mask is None:
            raise HTTPException(status_code=404, detail="Object mask not found")
        try:
            mask_image = Image.open(BytesIO(content)).convert("L")
            mask_image.load()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Mask image was invalid") from exc

        _write_object_mask_image(app_settings.storage_root, object_mask, mask_image)
        updated_mask = touch_object_mask(database_path, object_mask_id)
        if updated_mask is None:
            raise HTTPException(status_code=404, detail="Object mask not found")
        return updated_mask

    @app.post("/api/object-masks/{object_mask_id}/process", response_model=list[ObjectMask])
    def post_object_mask_process(
        object_mask_id: int,
        request: ObjectMaskProcessRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        object_mask = get_object_mask_by_id(
            database_path,
            object_mask_id=object_mask_id,
            organization_id=user["organization_id"],
        )
        if object_mask is None:
            raise HTTPException(status_code=404, detail="Object mask not found")
        target_masks = (
            list_object_masks_for_object(
                database_path,
                scene_object_id=object_mask["scene_object_id"],
                organization_id=user["organization_id"],
            )
            if request.apply_all
            else [object_mask]
        )
        updated_masks = []
        for target_mask in target_masks:
            processed_image = _process_object_mask_image(
                app_settings.storage_root,
                target_mask,
                operation=request.operation,
                pixels=request.pixels,
            )
            _write_object_mask_image(app_settings.storage_root, target_mask, processed_image)
            updated_mask = touch_object_mask(database_path, target_mask["id"])
            if updated_mask is not None:
                updated_masks.append(updated_mask)
        return updated_masks

    @app.get("/api/scene-objects/{object_id}/thumbnail")
    def get_scene_object_thumbnail(
        object_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> FileResponse:
        object_masks = list_object_masks_for_object(
            database_path,
            scene_object_id=object_id,
            organization_id=user["organization_id"],
        )
        if not object_masks:
            raise HTTPException(status_code=404, detail="Object does not have masks")

        for object_mask in object_masks:
            original_path = app_settings.storage_root / object_mask["original_relative_path"]
            mask_relative_path = object_mask["soft_relative_path"] or object_mask["relative_path"]
            mask_path = app_settings.storage_root / mask_relative_path
            if not original_path.exists() or not mask_path.exists():
                continue
            thumbnail_path = (
                app_settings.storage_root
                / _safe_path_segment(user["organization_id"])
                / "derived"
                / "scenes"
                / str(object_mask["scene_id"])
                / "objects"
                / str(object_id)
                / "thumbnails"
                / f"{object_mask['id']}.png"
            )
            if _derived_file_is_stale(thumbnail_path, [original_path, mask_path]):
                rendered = render_masked_object_crop(
                    original_path=original_path,
                    mask_path=mask_path,
                    output_path=thumbnail_path,
                    max_size=256,
                )
                if rendered is None:
                    continue
            if thumbnail_path.exists():
                return FileResponse(
                    thumbnail_path,
                    media_type="image/png",
                    headers={"Cache-Control": "no-store, max-age=0"},
                )

        raise HTTPException(status_code=404, detail="Object does not have a valid mask")

    @app.get("/api/scene-objects/{object_id}/preview-renders/{uploaded_file_id}")
    def get_scene_object_preview_render(
        object_id: int,
        uploaded_file_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> FileResponse:
        scene_object = get_scene_object_for_organization(
            database_path,
            object_id=object_id,
            organization_id=user["organization_id"],
        )
        if scene_object is None:
            raise HTTPException(status_code=404, detail="Object not found")
        object_masks = list_object_masks_for_object(
            database_path,
            scene_object_id=object_id,
            organization_id=user["organization_id"],
        )
        object_mask = _select_preview_mask_for_uploaded_file(
            object_masks,
            uploaded_file_id=uploaded_file_id,
            prompt_text=scene_object.get("prompt") or "",
        )
        if object_mask is None:
            raise HTTPException(status_code=404, detail="Preview render not found")
        rendered = _ensure_preview_render(
            storage_root=app_settings.storage_root,
            organization_id=user["organization_id"],
            object_mask=object_mask,
        )
        if rendered is None:
            raise HTTPException(status_code=404, detail="Preview render not found")
        return FileResponse(
            rendered["output_path"],
            media_type="image/png",
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @app.get("/api/scenes/{scene_id}/preview-data", response_model=ScenePreview)
    def get_scene_preview_data(
        scene_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        scene = get_scene_with_images(database_path, scene_id)
        if scene is None or scene["organization_id"] != user["organization_id"]:
            raise HTTPException(status_code=404, detail="Scene not found")
        return _build_scene_preview_payload(
            database_path=database_path,
            storage_root=app_settings.storage_root,
            organization_id=user["organization_id"],
            scene=scene,
        )

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


def _cors_allowed_origins(frontend_url: str) -> list[str]:
    origins = {
        frontend_url.rstrip("/"),
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    }
    return sorted(origins)


def _cors_allowed_origin_regex() -> str:
    return (
        r"https?://("
        r"localhost|"
        r"127\.0\.0\.1|"
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"192\.168\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        r")(:\d+)?"
    )


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


def _draft_scene_title(scene: dict[str, Any], scene_key: str) -> str | None:
    if not scene_key or not scene["title"].startswith("Draft scene from batch"):
        return None
    return scene_key.replace("_", " ").title()


async def _processing_job_worker(
    database_path: Path,
    settings: Settings,
    segmentation_provider: SegmentationProvider | None,
    segmentation_provider_error: str | None,
) -> None:
    while True:
        job = claim_next_processing_job(database_path)
        if job is None:
            await asyncio.sleep(1)
            continue

        try:
            if job["job_type"] == "mask_extraction":
                if segmentation_provider_error:
                    raise RuntimeError(segmentation_provider_error)
                if segmentation_provider is None:
                    raise RuntimeError("Segmentation provider is not configured")
                result = await _run_mask_extraction_job(
                    database_path=database_path,
                    settings=settings,
                    segmentation_provider=segmentation_provider,
                    job=job,
                )
                complete_processing_job(
                    database_path,
                    job_id=job["id"],
                    result=result,
                    message="Mask extraction complete",
                )
            else:
                raise RuntimeError(f"Unsupported job type: {job['job_type']}")
        except Exception as exc:
            fail_processing_job(database_path, job_id=job["id"], error=str(exc))


async def _run_mask_extraction_job(
    database_path: Path,
    settings: Settings,
    segmentation_provider: SegmentationProvider,
    job: dict[str, Any],
) -> dict[str, Any]:
    scene_id = job["scene_id"]
    scene = get_scene_with_images(database_path, scene_id)
    if scene is None or scene["organization_id"] != job["organization_id"]:
        raise RuntimeError("Scene not found")

    scene_objects = list_scene_objects_for_scene(database_path, scene_id)
    images = list_scene_images_for_scene(database_path, scene_id)
    if not scene_objects:
        raise RuntimeError("Scene does not have any objects with prompts")
    if not images:
        raise RuntimeError("Scene does not have any images")

    created_candidate_count = 0
    skipped_existing_count = 0
    processed_image_count = 0
    progress_current = 0
    progress_total = _count_mask_extraction_work(database_path, scene_objects, images)
    update_processing_job_progress(
        database_path,
        job_id=job["id"],
        progress_current=0,
        progress_total=progress_total,
        message="Preparing mask extraction",
    )

    for scene_image in images:
        objects_to_extract = [
            scene_object
            for scene_object in scene_objects
            if not object_mask_exists_for_prompt(
                database_path,
                scene_object_id=scene_object["id"],
                uploaded_file_id=scene_image["uploaded_file_id"],
                prompt_text=scene_object["prompt"],
            )
        ]
        skipped_existing_count += len(scene_objects) - len(objects_to_extract)
        if not objects_to_extract:
            continue

        image_path = settings.storage_root / scene_image["relative_path"]
        if not image_path.exists():
            raise RuntimeError(f"Scene image content not found: {scene_image['original_filename']}")

        update_processing_job_progress(
            database_path,
            job_id=job["id"],
            progress_current=progress_current,
            message=f"Extracting masks for {scene_image['original_filename']}",
        )
        output_dir = (
            settings.storage_root
            / _safe_path_segment(job["organization_id"])
            / "derived"
            / "scenes"
            / str(scene_id)
            / "images"
            / str(scene_image["uploaded_file_id"])
        )
        prompt_results = await segmentation_provider.extract_masks(
            image_path=image_path,
            prompts=[scene_object["prompt"] for scene_object in objects_to_extract],
            output_dir=output_dir,
        )

        processed_image_count += 1
        object_by_prompt_text = {
            scene_object["prompt"].lower(): scene_object for scene_object in objects_to_extract
        }
        for prompt_result in prompt_results:
            scene_object = object_by_prompt_text.get(prompt_result.prompt.lower())
            if scene_object is None:
                continue
            candidate = _top_segmentation_candidate(prompt_result.candidates)
            if candidate is None:
                continue
            create_object_mask(
                database_path,
                scene_object_id=scene_object["id"],
                uploaded_file_id=scene_image["uploaded_file_id"],
                relative_path=_relative_storage_path(settings.storage_root, candidate.raw_path),
                soft_relative_path=(
                    _relative_storage_path(settings.storage_root, candidate.soft_path)
                    if candidate.soft_path
                    else None
                ),
                prompt_text=scene_object["prompt"],
                bbox_json=json.dumps(candidate.bbox) if candidate.bbox else None,
                score=candidate.score,
            )
            created_candidate_count += 1

        progress_current += len(objects_to_extract)
        update_processing_job_progress(
            database_path,
            job_id=job["id"],
            progress_current=progress_current,
            progress_total=progress_total,
            message=f"Processed {processed_image_count} image{'' if processed_image_count == 1 else 's'}",
        )

    return {
        "scene_id": scene_id,
        "processed_image_count": processed_image_count,
        "prompt_count": len(scene_objects),
        "created_candidate_count": created_candidate_count,
        "skipped_existing_count": skipped_existing_count,
    }


def _top_segmentation_candidate(candidates):
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate.score if candidate.score is not None else -1)


def _require_scene(db_path: Path, scene_id: int, organization_id: str) -> None:
    if not scene_belongs_to_organization(
        db_path,
        scene_id=scene_id,
        organization_id=organization_id,
    ):
        raise HTTPException(status_code=404, detail="Scene not found")


def _validate_variable_value(value_type: str, value: Any) -> Any:
    if value_type == "bool":
        if isinstance(value, bool):
            return value
        raise HTTPException(status_code=400, detail="Boolean variables require true or false")
    if value_type == "string":
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        raise HTTPException(status_code=400, detail="String variables require text")
    if value_type == "number":
        if isinstance(value, bool):
            raise HTTPException(status_code=400, detail="Number variables require a number")
        if isinstance(value, (int, float)):
            return value
        raise HTTPException(status_code=400, detail="Number variables require a number")
    raise HTTPException(status_code=400, detail="Unsupported variable type")


def _normalize_interaction_trigger(
    db_path: Path,
    scene_id: int,
    organization_id: str,
    trigger: dict[str, Any],
) -> dict[str, Any]:
    trigger_type = str(trigger.get("type") or "")
    normalized: dict[str, Any] = {"type": trigger_type}
    if trigger_type in {"scene_enter", "scene_exit"}:
        return normalized
    if trigger_type in {"object_hover", "object_click", "object_use"}:
        object_id = _required_int(trigger.get("object_id"), "Trigger object is required")
        if not scene_object_belongs_to_scene(db_path, scene_id, object_id, organization_id):
            raise HTTPException(status_code=400, detail="Trigger object is not in this scene")
        normalized["object_id"] = object_id
        return normalized
    if trigger_type == "variable_changed":
        variable_id = _required_int(trigger.get("variable_id"), "Trigger variable is required")
        if get_game_variable_by_id(db_path, organization_id, variable_id) is None:
            raise HTTPException(status_code=400, detail="Trigger variable does not exist")
        normalized["variable_id"] = variable_id
        return normalized
    raise HTTPException(status_code=400, detail="Unsupported trigger type")


def _normalize_action_tree(
    db_path: Path,
    scene_id: int,
    organization_id: str,
    steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(steps, list):
        raise HTTPException(status_code=400, detail="Action tree must be a list")
    return [
        _normalize_action_step(db_path, scene_id, organization_id, step)
        for step in steps
    ]


def _normalize_action_step(
    db_path: Path,
    scene_id: int,
    organization_id: str,
    step: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(step, dict):
        raise HTTPException(status_code=400, detail="Action step must be an object")
    step_type = str(step.get("type") or "")
    normalized: dict[str, Any] = {
        "id": str(step.get("id") or uuid4().hex),
        "type": step_type,
    }
    if step_type == "play_animation":
        object_id = _required_int(step.get("target_object_id"), "Animation target object is required")
        animation_id = _required_int(step.get("animation_id"), "Animation is required")
        if not scene_object_belongs_to_scene(db_path, scene_id, object_id, organization_id):
            raise HTTPException(status_code=400, detail="Animation target object is not in this scene")
        if not object_animation_belongs_to_object(db_path, animation_id, object_id, organization_id):
            raise HTTPException(status_code=400, detail="Animation does not belong to the target object")
        normalized.update(
            {
                "target_object_id": object_id,
                "animation_id": animation_id,
                "mode": _choice(step.get("mode"), {"queued", "immediate"}, "queued"),
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "wait"),
            }
        )
        return normalized
    if step_type == "set_object_property":
        object_id = _required_int(step.get("target_object_id"), "Property target object is required")
        if not scene_object_belongs_to_scene(db_path, scene_id, object_id, organization_id):
            raise HTTPException(status_code=400, detail="Property target object is not in this scene")
        property_name = _choice(step.get("property"), {"visible", "enabled", "label"}, "")
        value = step.get("value")
        if property_name in {"visible", "enabled"} and not isinstance(value, bool):
            raise HTTPException(status_code=400, detail=f"{property_name} requires a boolean value")
        if property_name == "label" and not isinstance(value, str):
            raise HTTPException(status_code=400, detail="label requires text")
        normalized.update(
            {
                "target_object_id": object_id,
                "property": property_name,
                "value": value,
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "continue"),
            }
        )
        return normalized
    if step_type == "show_subtitle":
        line_ids = [
            _required_int(line_id, "Subtitle line IDs must be integers")
            for line_id in (step.get("script_line_ids") or [])
        ]
        if not script_line_ids_exist(db_path, organization_id, line_ids):
            raise HTTPException(status_code=400, detail="One or more subtitle lines do not exist")
        normalized.update(
            {
                "script_line_ids": sorted(set(line_ids)),
                "selection": "random" if len(set(line_ids)) > 1 else "single",
                "duration_seconds": _positive_float(step.get("duration_seconds"), "Subtitle duration is required"),
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "wait"),
            }
        )
        return normalized
    if step_type == "play_audio":
        line_ids = [
            _required_int(line_id, "Audio line IDs must be integers")
            for line_id in (step.get("script_line_ids") or [])
        ]
        if not script_line_ids_exist(db_path, organization_id, line_ids):
            raise HTTPException(status_code=400, detail="One or more script lines do not exist")
        normalized.update(
            {
                "script_line_ids": sorted(set(line_ids)),
                "selection": "random" if len(set(line_ids)) > 1 else "single",
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "wait"),
            }
        )
        return normalized
    if step_type == "set_variable":
        variable = _require_variable(
            db_path,
            organization_id,
            _required_int(step.get("variable_id"), "Variable is required"),
        )
        normalized.update(
            {
                "variable_id": variable["id"],
                "value": _validate_variable_value(variable["value_type"], step.get("value")),
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "continue"),
            }
        )
        return normalized
    if step_type == "if_variable":
        variable = _require_variable(
            db_path,
            organization_id,
            _required_int(step.get("variable_id"), "Condition variable is required"),
        )
        comparator = _choice(
            step.get("operator"),
            {"equals", "not_equals", "greater_than", "less_than", "greater_or_equal", "less_or_equal"},
            "equals",
        )
        if variable["value_type"] != "number" and comparator not in {"equals", "not_equals"}:
            raise HTTPException(status_code=400, detail="Only number variables support ordering comparisons")
        normalized.update(
            {
                "variable_id": variable["id"],
                "operator": comparator,
                "value": _validate_variable_value(variable["value_type"], step.get("value")),
                "then_steps": _normalize_action_tree(
                    db_path,
                    scene_id,
                    organization_id,
                    step.get("then_steps") or [],
                ),
                "else_steps": _normalize_action_tree(
                    db_path,
                    scene_id,
                    organization_id,
                    step.get("else_steps") or [],
                ),
            }
        )
        return normalized
    if step_type == "delay":
        normalized.update(
            {
                "duration_seconds": _positive_float(step.get("duration_seconds"), "Delay duration is required"),
                "wait": "wait",
            }
        )
        return normalized
    raise HTTPException(status_code=400, detail="Unsupported action type")


def _require_variable(db_path: Path, organization_id: str, variable_id: int) -> dict[str, Any]:
    variable = get_game_variable_by_id(db_path, organization_id, variable_id)
    if variable is None:
        raise HTTPException(status_code=400, detail="Variable does not exist")
    return variable


def _required_int(value: Any, detail: str) -> int:
    if value is None or value == "":
        raise HTTPException(status_code=400, detail=detail)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=detail) from exc


def _positive_float(value: Any, detail: str) -> float:
    if value is None or value == "":
        raise HTTPException(status_code=400, detail=detail)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=detail) from exc
    if number <= 0:
        raise HTTPException(status_code=400, detail=detail)
    return number


def _choice(value: Any, allowed: set[str], default: str) -> str:
    selected = str(value or default)
    if selected not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported value: {selected}")
    return selected


def _count_mask_extraction_work(
    database_path: Path,
    scene_objects: list[dict[str, Any]],
    images: list[dict[str, Any]],
) -> int:
    total = 0
    for scene_image in images:
        for scene_object in scene_objects:
            if not object_mask_exists_for_prompt(
                database_path,
                scene_object_id=scene_object["id"],
                uploaded_file_id=scene_image["uploaded_file_id"],
                prompt_text=scene_object["prompt"],
            ):
                total += 1
    return total


def _relative_storage_path(storage_root: Path, path: Path) -> str:
    resolved_root = storage_root.resolve()
    resolved_path = path.resolve()
    try:
        return str(resolved_path.relative_to(resolved_root))
    except ValueError as exc:
        raise RuntimeError(f"Generated mask was written outside storage root: {path}") from exc


def _write_object_mask_image(
    storage_root: Path,
    object_mask: dict[str, Any],
    mask_image: Image.Image,
) -> None:
    normalized = mask_image.convert("L")
    for relative_path in [
        object_mask["relative_path"],
        object_mask.get("soft_relative_path"),
    ]:
        if not relative_path:
            continue
        output_path = storage_root / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        normalized.save(output_path, format="PNG")


def _process_object_mask_image(
    storage_root: Path,
    object_mask: dict[str, Any],
    operation: str,
    pixels: int,
) -> Image.Image:
    mask_path = storage_root / object_mask["relative_path"]
    if not mask_path.exists():
        raise HTTPException(status_code=404, detail="Mask file not found")
    with Image.open(mask_path) as image:
        mask_image = image.convert("L")
        mask_image.load()
    if operation == "grow":
        return mask_image.filter(ImageFilter.MaxFilter(pixels * 2 + 1))
    if operation == "fill_holes":
        return _fill_mask_holes(mask_image)
    raise HTTPException(status_code=400, detail="Unsupported mask operation")


def _fill_mask_holes(mask_image: Image.Image) -> Image.Image:
    binary = mask_image.convert("L").point(lambda value: 255 if value > 0 else 0)
    exterior = ImageOps.invert(binary)
    width, height = exterior.size
    for x in range(width):
        if exterior.getpixel((x, 0)):
            ImageDraw.floodfill(exterior, (x, 0), 0)
        if exterior.getpixel((x, height - 1)):
            ImageDraw.floodfill(exterior, (x, height - 1), 0)
    for y in range(height):
        if exterior.getpixel((0, y)):
            ImageDraw.floodfill(exterior, (0, y), 0)
        if exterior.getpixel((width - 1, y)):
            ImageDraw.floodfill(exterior, (width - 1, y), 0)
    return ImageChops.lighter(binary, exterior)


def _animation_segments_payload(
    segments: list[ObjectAnimationSegmentInput],
) -> list[dict[str, int | float]]:
    return [
        {
            "start_frame": segment.start_frame,
            "end_frame": segment.end_frame,
            "frame_duration_seconds": segment.frame_duration_seconds,
        }
        for segment in segments
    ]


def _derived_file_is_stale(output_path: Path, source_paths: list[Path]) -> bool:
    if not output_path.exists():
        return True
    output_mtime = output_path.stat().st_mtime
    return any(source_path.stat().st_mtime > output_mtime for source_path in source_paths)


def _build_scene_preview_payload(
    database_path: Path,
    storage_root: Path,
    organization_id: str,
    scene: dict[str, Any],
) -> dict[str, Any]:
    scene_images = scene.get("images", [])
    preview_images = [
        {
            "frame_index": index,
            "uploaded_file_id": image["uploaded_file_id"],
            "original_filename": image["original_filename"],
            "width": image["width"],
            "height": image["height"],
        }
        for index, image in enumerate(scene_images)
    ]
    scene_width = int(scene_images[0]["width"]) if scene_images else 0
    scene_height = int(scene_images[0]["height"]) if scene_images else 0
    preview_objects = []

    for scene_object in scene.get("objects", []):
        object_masks = list_object_masks_for_object(
            database_path,
            scene_object_id=scene_object["id"],
            organization_id=organization_id,
        )
        default_render = None
        for object_mask in object_masks:
            default_render = _preview_render_payload_for_mask(
                storage_root=storage_root,
                organization_id=organization_id,
                object_mask=object_mask,
                frame_index=next(
                    (
                        index
                        for index, image in enumerate(scene_images)
                        if image["uploaded_file_id"] == object_mask["uploaded_file_id"]
                    ),
                    None,
                ),
            )
            if default_render is not None:
                break

        animations = []
        object_animations = list_object_animations_for_object(
            database_path,
            scene_object_id=scene_object["id"],
            organization_id=organization_id,
        )
        for animation in object_animations:
            frames = []
            for segment in animation.get("segments", []):
                start = int(segment["start_frame"])
                end = int(segment["end_frame"])
                step = 1 if start <= end else -1
                for frame_index in range(start, end + step, step):
                    scene_image = scene_images[frame_index] if 0 <= frame_index < len(scene_images) else None
                    render = None
                    original_filename = "missing frame"
                    if scene_image is not None:
                        original_filename = scene_image["original_filename"]
                        object_mask = _select_preview_mask_for_uploaded_file(
                            object_masks,
                            uploaded_file_id=scene_image["uploaded_file_id"],
                            prompt_text=scene_object.get("prompt") or "",
                        )
                        if object_mask is not None:
                            render = _preview_render_payload_for_mask(
                                storage_root=storage_root,
                                organization_id=organization_id,
                                object_mask=object_mask,
                                frame_index=frame_index,
                            )
                    frames.append(
                        {
                            "frame_index": frame_index,
                            "duration_seconds": float(segment["frame_duration_seconds"]),
                            "original_filename": original_filename,
                            "render": render,
                        }
                    )
            animations.append(
                {
                    "id": animation["id"],
                    "name": animation["name"],
                    "frames": frames,
                }
            )

        preview_objects.append(
            {
                "id": scene_object["id"],
                "name": scene_object["name"],
                "visible": True,
                "default_render": default_render,
                "animations": animations,
            }
        )

    return {
        "scene_id": scene["id"],
        "title": scene["title"],
        "description": scene["description"],
        "width": scene_width,
        "height": scene_height,
        "images": preview_images,
        "objects": preview_objects,
    }


def _preview_render_payload_for_mask(
    storage_root: Path,
    organization_id: str,
    object_mask: dict[str, Any],
    frame_index: int | None,
) -> dict[str, Any] | None:
    rendered = _ensure_preview_render(
        storage_root=storage_root,
        organization_id=organization_id,
        object_mask=object_mask,
    )
    if rendered is None:
        return None
    cache_key = rendered["cache_key"]
    return {
        "frame_index": frame_index,
        "uploaded_file_id": object_mask["uploaded_file_id"],
        "object_mask_id": object_mask["id"],
        "original_filename": object_mask.get("original_filename") or "",
        "left": rendered["left"],
        "top": rendered["top"],
        "width": rendered["width"],
        "height": rendered["height"],
        "url": _preview_render_url(
            object_id=object_mask["scene_object_id"],
            uploaded_file_id=object_mask["uploaded_file_id"],
            cache_key=cache_key,
        ),
        "cache_key": cache_key,
    }


def _ensure_preview_render(
    storage_root: Path,
    organization_id: str,
    object_mask: dict[str, Any],
) -> dict[str, Any] | None:
    original_path = storage_root / object_mask["original_relative_path"]
    mask_relative_path = object_mask["soft_relative_path"] or object_mask["relative_path"]
    mask_path = storage_root / mask_relative_path
    if not original_path.exists() or not mask_path.exists():
        return None
    cache_key = _preview_render_cache_key(
        object_mask=object_mask,
        original_path=original_path,
        mask_path=mask_path,
    )

    output_path = (
        storage_root
        / _safe_path_segment(organization_id)
        / "derived"
        / "scenes"
        / str(object_mask["scene_id"])
        / "objects"
        / str(object_mask["scene_object_id"])
        / "preview"
        / f"{object_mask['uploaded_file_id']}.png"
    )
    metadata_path = output_path.with_suffix(".json")
    metadata = _read_preview_render_metadata(metadata_path)
    should_render = metadata.get("cache_key") != cache_key or not output_path.exists()
    bbox: tuple[int, int, int, int] | None = None
    if should_render:
        rendered = render_masked_object_crop(
            original_path=original_path,
            mask_path=mask_path,
            output_path=output_path,
            max_size=0,
        )
        if rendered is None:
            return None
        bbox = rendered.bbox
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps({"bbox": list(bbox), "cache_key": cache_key}),
            encoding="utf-8",
        )
    else:
        raw_bbox = metadata.get("bbox")
        if isinstance(raw_bbox, list) and len(raw_bbox) == 4:
            bbox = tuple(int(value) for value in raw_bbox)
    if bbox is None:
        rendered = render_masked_object_crop(
            original_path=original_path,
            mask_path=mask_path,
            output_path=output_path,
            max_size=0,
        )
        if rendered is None:
            return None
        bbox = rendered.bbox
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps({"bbox": list(bbox), "cache_key": cache_key}),
            encoding="utf-8",
        )
    left, top, right, bottom = bbox
    return {
        "output_path": output_path,
        "left": left,
        "top": top,
        "width": max(0, right - left),
        "height": max(0, bottom - top),
        "cache_key": cache_key,
    }


def _select_preview_mask_for_uploaded_file(
    object_masks: list[dict[str, Any]],
    uploaded_file_id: int,
    prompt_text: str,
) -> dict[str, Any] | None:
    candidates = [
        object_mask
        for object_mask in object_masks
        if int(object_mask["uploaded_file_id"]) == int(uploaded_file_id)
    ]
    if not candidates:
        return None
    prompt_matches = [
        object_mask for object_mask in candidates if object_mask.get("prompt_text") == prompt_text
    ]
    ranked = prompt_matches or candidates
    return max(ranked, key=lambda object_mask: int(object_mask["id"]))


def _preview_render_cache_key(
    object_mask: dict[str, Any],
    original_path: Path,
    mask_path: Path,
) -> str:
    original_stat = original_path.stat()
    mask_stat = mask_path.stat()
    return "|".join(
        [
            str(object_mask.get("id") or ""),
            str(object_mask.get("created_at") or ""),
            str(object_mask.get("updated_at") or ""),
            str(object_mask.get("relative_path") or ""),
            str(object_mask.get("soft_relative_path") or ""),
            str(object_mask.get("prompt_text") or ""),
            str(original_stat.st_mtime_ns),
            str(original_stat.st_size),
            str(mask_stat.st_mtime_ns),
            str(mask_stat.st_size),
        ]
    )


def _preview_render_url(object_id: int, uploaded_file_id: int, cache_key: str) -> str:
    query = f"?v={cache_key}" if cache_key else ""
    return f"/api/scene-objects/{object_id}/preview-renders/{uploaded_file_id}{query}"


def _read_preview_render_metadata(metadata_path: Path) -> dict[str, Any]:
    if not metadata_path.exists():
        return {}
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _batch_storage_root(storage_root: Path, organization_id: str, batch_id: int) -> Path:
    return storage_root / _safe_path_segment(organization_id) / str(batch_id)


def _safe_child_path(root: Path, relative_path: str) -> Path:
    root_path = root.resolve()
    file_path = (root_path / relative_path).resolve()
    if file_path != root_path and root_path not in file_path.parents:
        raise HTTPException(status_code=404, detail="File not found")
    return file_path


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    if not name:
        return "upload.bin"
    cleaned = sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return cleaned or "upload.bin"


def _safe_path_segment(value: str) -> str:
    return sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "default"


async def _write_upload(upload: UploadFile, stored_path: Path) -> int:
    total_bytes = 0
    with stored_path.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            total_bytes += len(chunk)
            output.write(chunk)
    await upload.close()
    return total_bytes


def _error_code(message: str) -> str:
    return (
        message.lower()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("'", "")
        .replace('"', "")
    )


app = create_app()
