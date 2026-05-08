from __future__ import annotations

import asyncio
import json
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
    create_invite,
    create_object_animation,
    create_processing_job,
    create_object_mask,
    create_session,
    create_scene_object_if_missing,
    create_scene_object,
    create_scene_mask_prompt,
    create_upload_batch,
    delete_object_animation,
    delete_scene_mask_prompt,
    delete_scene_object,
    delete_session,
    fail_processing_job,
    get_available_invite,
    get_database_path,
    get_mask_candidate_by_id,
    get_object_mask_by_id,
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
    list_object_animations_for_object,
    list_object_masks_for_object,
    list_scene_objects_for_scene,
    list_scene_images_for_scene,
    list_scenes,
    list_upload_batches,
    object_mask_exists_for_prompt,
    mark_invite_used,
    claim_next_processing_job,
    complete_processing_job,
    requeue_interrupted_processing_jobs,
    reset_workspace_tables,
    scene_belongs_to_organization,
    touch_object_mask,
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


def _batch_storage_root(storage_root: Path, organization_id: str, batch_id: int) -> Path:
    return storage_root / _safe_path_segment(organization_id) / str(batch_id)


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
