from __future__ import annotations

import asyncio
import json
import sqlite3
import shutil
import tempfile
from subprocess import DEVNULL
from io import BytesIO
from contextlib import asynccontextmanager
from pathlib import Path
from re import sub
from typing import Any
from urllib.parse import urlencode, urlparse
from uuid import uuid4

import httpx
from fastapi import Body, Cookie, Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from starlette.background import BackgroundTask
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
from pydantic import BaseModel, EmailStr, Field

from .config import Settings, get_settings
from .database import (
    assign_uploaded_file_to_scene,
    add_uploaded_file,
    create_character,
    create_character_animation,
    create_character_object,
    create_audio_asset,
    create_asset,
    create_empty_scene,
    create_game_variable,
    create_invite,
    create_or_update_overlay_scene_binding,
    create_object_animation,
    create_script_line,
    create_processing_job,
    create_object_mask,
    create_session,
    create_scene_interaction,
    create_scene_object_if_missing,
    create_scene_object,
    create_scene_mask_prompt,
    create_upload_batch,
    delete_object_animation,
    delete_audio_asset,
    delete_game_variable,
    delete_overlay_scene_binding,
    delete_character,
    delete_character_animation,
    delete_character_image,
    delete_character_object,
    delete_verb,
    delete_script_line,
    delete_scene_mask_prompt,
    delete_scene_and_unhook_references,
    delete_scene_object,
    delete_scene_interaction,
    delete_session,
    ensure_system_game_variables,
    fail_processing_job,
    get_available_invite,
    get_database_path,
    get_mask_candidate_by_id,
    get_object_mask_by_id,
    get_game_variable_by_id,
    get_global_settings,
    get_overlay_scene_binding_by_key,
    get_script_audio_candidate_by_id,
    get_character_by_id,
    get_character_image_by_id,
    get_character_animation_by_id,
    get_character_object_by_id,
    get_script_line_detail,
    get_scene_interaction,
    get_scene_object_for_organization,
    get_active_processing_job_for_scene,
    get_active_processing_job_for_script_line,
    get_audio_asset_by_id,
    get_processing_job,
    get_session_by_token,
    get_scene_with_images,
    get_scene_mask_prompt,
    get_upload_batch,
    get_uploaded_file_by_id,
    get_user_by_email,
    get_user_by_identity,
    get_workspace_summary,
    init_database,
    link_identity,
    list_assets,
    list_audio_assets,
    list_characters,
    list_character_animations,
    list_character_images,
    list_character_objects,
    list_game_variables,
    list_overlay_scene_bindings,
    list_object_animations_for_object,
    list_object_masks_for_object,
    list_scene_objects_for_organization,
    list_script_line_references,
    list_script_line_ids,
    list_script_lines,
    list_script_path_options,
    list_script_audio_candidate_viseme_events,
    list_uploaded_image_files,
    list_scene_objects_for_scene,
    list_scene_images_for_scene,
    list_scene_interactions,
    list_scenes,
    move_scene_sort_order,
    list_upload_batches,
    list_verbs,
    merge_scene_into_scene,
    object_mask_exists_for_prompt,
    mark_invite_used,
    object_animation_belongs_to_object,
    claim_next_processing_job,
    complete_processing_job,
    requeue_interrupted_processing_jobs,
    reset_workspace_tables,
    reorder_scene_images,
    scene_belongs_to_organization,
    scene_object_belongs_to_scene,
    set_scene_object_inventory_image,
    set_scene_object_inventory_image_failed,
    set_scene_object_pickup_frame,
    set_scene_object_pickup_frame_failed,
    script_line_ids_exist,
    touch_object_mask,
    update_game_variable,
    update_global_settings,
    update_scene,
    update_audio_asset,
    update_character,
    update_character_animation,
    update_character_object,
    update_scene_interaction,
    update_script_audio_candidate,
    update_script_translation_review,
    update_script_translation,
    update_object_animation,
    update_scene_mask_prompt,
    update_scene_object,
    update_scene_description,
    update_processing_job_progress,
    update_verb,
    upsert_character_image,
    upsert_script_translation,
    upsert_user,
    upsert_script_audio_candidate,
    replace_script_audio_candidate_viseme_events,
    create_verb,
    get_verb_by_id,
)
from .characters import (
    CharacterImageProvider,
    CharacterImageProviderUnavailable,
    VisemeExtractionProvider,
    VisemeExtractionProviderUnavailable,
    build_character_image_provider,
    build_viseme_extraction_provider,
)
from .object_rendering import render_masked_object_crop
from .inventory_images import (
    InventoryImageProvider,
    InventoryImageProviderUnavailable,
    build_inventory_image_provider,
    build_scene_removal_provider,
)
from .scene_processing import fingerprint_image, process_upload_batch_into_scene
from .security import sign_state, verify_state
from .segmentation import SegmentationProvider, build_segmentation_provider
from .script_import import import_script_audio_data
from .project_archive import (
    database_backup_path,
    export_project_archive,
    export_project_database_json,
    import_project_archive,
    import_project_database_json,
    workspace_is_empty,
)
from .runtime_export import (
    export_godot_code_files,
    export_runtime_bundle,
    export_runtime_bundle_zip,
    runtime_bundle_output_path,
    runtime_bundle_zip_output_path,
)
from .script_localization import (
    ScriptLocalizationProvider,
    build_script_localization_provider,
)
from .vlm import SceneVlmProvider, build_scene_vlm_provider, scene_draft_to_dict


GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
SCENE_PREVIEW_MANIFEST_CACHE_VERSION = 1


class AssetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    asset_type: str = Field(min_length=1, max_length=80)
    status: str = Field(default="planned", min_length=1, max_length=80)


class Asset(AssetCreate):
    id: int
    organization_id: str
    created_at: str


class AudioAssetBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    kind: str = Field(pattern="^(bgm|sfx)$")


class AudioAsset(AudioAssetBase):
    id: int
    organization_id: str
    relative_path: str
    original_filename: str
    content_type: str | None
    file_size: int
    created_at: str
    updated_at: str


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
    sort_order: int = 0
    created_at: str
    original_filename: str
    relative_path: str


class SceneObject(BaseModel):
    id: int
    scene_id: int
    name: str
    description: str
    prompt: str
    inventory_image_prompt: str = ""
    category: str
    source: str
    sort_order: int = 0
    visible: bool = True
    enabled: bool = True
    keyboard_target_enabled: bool = False
    default_uploaded_file_id: int | None = None
    pickup_uploaded_file_id: int | None = None
    inventory_image_relative_path: str | None = None
    inventory_image_failed: bool = False
    pickup_frame_failed: bool = False
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
    presentation_mode: str = "base"
    status: str
    background_frame_index: int = 0
    sort_order: int = 0
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
    presentation_mode: str = "base"
    status: str
    background_frame_index: int = 0
    sort_order: int = 0
    representative_uploaded_file_id: int | None
    representative_hash: str | None
    created_by_user_id: int
    created_at: str
    updated_at: str
    image_count: int
    object_count: int
    object_mask_count: int = 0


class SceneCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=5000)
    presentation_mode: str = Field(default="base", pattern="^(base|overlay)$")


class SceneMoveRequest(BaseModel):
    direction: str = Field(pattern="^(up|down)$")


class BatchSceneProcessResult(BaseModel):
    scene: Scene
    created: bool
    matched_existing: bool
    processed_file_count: int


class SceneObjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    prompt: str | None = Field(default=None, max_length=160)
    inventory_image_prompt: str | None = Field(default=None, max_length=240)


class SceneObjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    prompt: str | None = Field(default=None, min_length=1, max_length=160)
    inventory_image_prompt: str | None = Field(default=None, max_length=240)
    sort_order: int | None = Field(default=None, ge=1, le=100000)
    visible: bool | None = None
    enabled: bool | None = None
    keyboard_target_enabled: bool | None = None


class SceneObjectDefaultFrameUpdate(BaseModel):
    uploaded_file_id: int | None = Field(default=None, ge=1)


class SceneObjectMaskCreateRequest(BaseModel):
    uploaded_file_id: int = Field(ge=1)


class SceneUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
    presentation_mode: str | None = Field(default=None, pattern="^(base|overlay|character)$")
    background_frame_index: int | None = Field(default=None, ge=0)


class UploadedImageSummary(BaseModel):
    uploaded_file_id: int
    batch_id: int
    original_filename: str
    relative_path: str
    content_type: str | None
    file_size: int
    created_at: str
    scene_image_id: int | None = None
    scene_id: int | None = None
    scene_title: str | None = None
    width: int | None = None
    height: int | None = None
    sort_order: int | None = None


class ImageMoveRequest(BaseModel):
    uploaded_file_ids: list[int] = Field(min_length=1)
    target_scene_id: int


class SceneImageReorderRequest(BaseModel):
    ordered_scene_image_ids: list[int] = Field(min_length=1)


class SceneMergeRequest(BaseModel):
    target_scene_id: int = Field(ge=1)


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
    operation: str = Field(pattern="^(grow|fill_holes|invert|solid|clear|combine)$")
    apply_all: bool = False
    pixels: int = Field(default=2, ge=1, le=32)


class ProcessingJob(BaseModel):
    id: int
    organization_id: str
    job_type: str
    status: str
    scene_id: int | None
    script_line_id: int | None
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


class ProjectArchiveSummary(BaseModel):
    format_version: int
    table_counts: dict[str, int]
    file_count: int | None = None
    restored_file_count: int | None = None


class ProjectImportResult(BaseModel):
    ok: bool
    cleared_tables: list[str]
    archive: ProjectArchiveSummary


class DatabaseBackupResult(BaseModel):
    ok: bool
    backup_path: str
    archive: ProjectArchiveSummary


class RuntimeBundleSummary(BaseModel):
    format_version: int
    scene_count: int
    script_line_count: int
    file_count: int


class RuntimeBundleExportResult(BaseModel):
    ok: bool
    output_path: str
    archive: RuntimeBundleSummary


class RuntimeBundleZipExportResult(BaseModel):
    ok: bool
    output_path: str
    source_folder_path: str
    file_count: int
    size_bytes: int
    download_path: str


class GodotCodeExportResult(BaseModel):
    ok: bool
    output_path: str
    file_count: int


class SceneDeleteResult(BaseModel):
    ok: bool
    scene_id: int
    scene_title: str
    deleted_image_count: int
    deleted_object_count: int
    deleted_interaction_count: int
    deleted_processing_job_count: int
    removed_scene_reference_count: int
    updated_interaction_count: int
    removed_overlay_binding_count: int
    cleared_start_scene: bool
    touched_scene_ids: list[int] = []


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
    viseme_events: list[ScriptAudioCandidateVisemeEvent] = []
    created_at: str
    updated_at: str


class ScriptLineUsageReference(BaseModel):
    scene_id: int
    scene_title: str
    interaction_id: int
    interaction_name: str
    step_types: list[str] = []


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
    translation_present: bool = False
    tts_audio_count: int = 0
    reviewed_audio_count: int = 0
    selected_audio_count: int = 0
    failed_tts_count: int = 0


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
    usage_references: list[ScriptLineUsageReference] = []


class ScriptLineListResponse(BaseModel):
    items: list[ScriptLineSummary]
    total: int
    limit: int
    offset: int


class ScriptLineTranslationInput(BaseModel):
    language: str = Field(min_length=2, max_length=12)
    text: str = Field(default="", max_length=5000)
    review_status: str = Field(default="needs_review", pattern="^(needs_review|approved|needs_edit|missing)$")
    notes: str = Field(default="", max_length=1000)


class ScriptLineCreate(BaseModel):
    source_text: str = Field(min_length=1, max_length=5000)
    path_text: str = Field(default="", max_length=1000)
    translations: list[ScriptLineTranslationInput] = Field(default_factory=list, max_length=24)


class ScriptTranslationUpdate(BaseModel):
    text: str = Field(default="", max_length=5000)
    review_status: str = Field(pattern="^(needs_review|approved|needs_edit|missing)$")
    notes: str = Field(default="", max_length=1000)


class ScriptAudioCandidateUpdate(BaseModel):
    review_status: str = Field(pattern="^(candidate|needs_review|approved|needs_edit|missing|rejected)$")
    notes: str = Field(default="", max_length=1000)
    selected: bool | None = None


class ScriptAudioCandidateUploadResult(BaseModel):
    candidate: ScriptAudioCandidate


class ScriptTtsGenerateRequest(BaseModel):
    language: str = Field(min_length=2, max_length=12)


class ScriptLineBulkSelectionRequest(BaseModel):
    line_ids: list[int] = Field(default_factory=list, max_length=500)
    language: str = Field(min_length=2, max_length=12)


class ScriptLineBulkGenerateRequest(BaseModel):
    language: str = Field(min_length=2, max_length=12)
    line_ids: list[int] = Field(default_factory=list, max_length=500)
    q: str = Field(default="", max_length=200)
    path: str = Field(default="", max_length=1000)
    translation_status: str = Field(default="", max_length=32)
    audio_status: str = Field(default="", max_length=32)
    audio_source: str = Field(default="", max_length=64)
    missing_audio: bool = False
    missing_translation: bool = False
    failed_tts: bool = False


class ScriptLineBulkOperationResult(BaseModel):
    processed: int
    succeeded: int
    failed: int
    detail: str
    errors: list[str] = []


class DependencyHealthCheck(BaseModel):
    key: str
    label: str
    status: str = Field(pattern="^(ok|warning|error)$")
    detail: str


class DependencyHealthResponse(BaseModel):
    status: str = Field(pattern="^(ok|warning|error)$")
    dependencies: list[DependencyHealthCheck]


class WorkspaceSummary(BaseModel):
    scenes_count: int
    missing_masks: int
    missing_inventory_art: int
    missing_translations: int
    missing_approved_audio: int
    referenced_missing_selected_audio: int
    referenced_unverified_translations: int
    failed_jobs: int


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


class OverlaySceneBindingCreate(BaseModel):
    key_code: str = Field(min_length=1, max_length=32)
    overlay_scene_id: int


class OverlaySceneBinding(OverlaySceneBindingCreate):
    id: int
    organization_id: str
    overlay_scene_title: str | None = None
    overlay_scene_presentation_mode: str | None = None
    created_at: str
    updated_at: str


class InventorySlot(BaseModel):
    x: float
    y: float
    size: float = Field(gt=0)
    origin: str = Field(default="center", pattern="^(center|top_left)$")


class VerbBase(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    labels: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    sort_order: int = Field(default=0, ge=0, le=100000)


class VerbCreate(VerbBase):
    pass


class Verb(VerbBase):
    id: int
    organization_id: str
    created_at: str
    updated_at: str


class GlobalSettingsUpdate(BaseModel):
    overlay_open_duration_seconds: float | None = Field(default=None, gt=0, le=10)
    overlay_close_duration_seconds: float | None = Field(default=None, gt=0, le=10)
    overlay_fade_color: str | None = Field(default=None, min_length=1, max_length=32)
    overlay_affect_audio: bool | None = None
    start_scene_id: int | None = Field(default=None, ge=1)
    inventory_key_code: str | None = Field(default=None, min_length=1, max_length=32)
    verb_menu_timeout_seconds: float | None = Field(default=None, gt=0.25, le=30)
    verb_menu_show_disabled: bool | None = None
    verb_text_color: str | None = Field(default=None, min_length=1, max_length=32)
    inventory_slots: list[InventorySlot] | None = None
    cursor_states: dict[str, dict[str, int | None | str | None]] | None = None


class GlobalSettings(GlobalSettingsUpdate):
    organization_id: str
    overlay_open_duration_seconds: float = 0.22
    overlay_close_duration_seconds: float = 0.18
    overlay_fade_color: str = "#000000"
    overlay_affect_audio: bool = False
    start_scene_id: int | None = None
    inventory_key_code: str = "KeyI"
    verb_menu_timeout_seconds: float = 4.0
    verb_menu_show_disabled: bool = True
    verb_text_color: str = "#34261b"
    inventory_slots: list[InventorySlot] = []
    inventory_background_relative_path: str | None = None
    verb_tag_background_relative_path: str | None = None
    cursor_states: dict[str, dict[str, int | None | str | None]] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class InteractionTrigger(BaseModel):
    type: str = Field(
        pattern="^(scene_enter|scene_exit|overlay_open|overlay_close|object_mouseover|object_mouseout|object_click|object_use|object_verb|inventory_use|variable_changed|key_press)$"
    )
    match_mode: str = Field(default="exact", pattern="^(exact|object_default|scene_default)$")
    object_id: int | None = None
    variable_id: int | None = None
    key_code: str | None = None
    verb_id: int | None = None
    inventory_object_id: int | None = None


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


class CharacterImage(BaseModel):
    id: int
    character_id: int
    component_key: str
    variant_key: str
    kind: str
    source_group: str = ""
    source_name: str = ""
    relative_path: str
    original_filename: str = ""
    width: int = 0
    height: int = 0
    is_default: bool = False
    sort_order: int = 0
    created_at: str
    updated_at: str


class CharacterAnimationFrameInput(BaseModel):
    character_image_id: int = Field(ge=1)
    duration_seconds: float = Field(gt=0, le=60)


class CharacterAnimationFrame(BaseModel):
    id: int
    character_animation_id: int
    character_image_id: int
    duration_seconds: float
    sort_order: int
    created_at: str
    updated_at: str
    image: CharacterImage


class CharacterAnimationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    frames: list[CharacterAnimationFrameInput] = Field(default_factory=list, max_length=200)


class CharacterAnimation(CharacterAnimationCreate):
    id: int
    character_id: int
    created_at: str
    updated_at: str
    frames: list[CharacterAnimationFrame] = []


class CharacterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    sort_order: int = Field(default=0, ge=0, le=100000)
    default_x: float = 960
    default_y: float = 540
    default_scale: float = Field(default=1.0, gt=0, le=20)


class CharacterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    mouth_scene_object_id: int | None = Field(default=None, ge=1)
    clear_mouth_scene_object_id: bool = False
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    default_x: float | None = None
    default_y: float | None = None
    default_scale: float | None = Field(default=None, gt=0, le=20)


class Character(BaseModel):
    id: int
    organization_id: str
    name: str
    description: str
    scene_id: int | None = None
    mouth_scene_object_id: int | None = None
    sort_order: int = 0
    default_x: float = 960
    default_y: float = 540
    default_scale: float = 1.0
    created_at: str
    updated_at: str
    scene: Scene | None = None
    images: list[CharacterImage] = []
    objects: list["CharacterObject"] = []
    animations: list[CharacterAnimation] = []


class CharacterImageCreate(BaseModel):
    component_key: str = Field(pattern="^(base|viseme_mouth)$")
    variant_key: str = Field(min_length=1, max_length=160)
    kind: str = Field(pattern="^(default|pose|viseme)$")
    source_group: str = Field(default="", max_length=160)
    source_name: str = Field(default="", max_length=240)
    is_default: bool = False
    sort_order: int = Field(default=0, ge=0, le=100000)


class CharacterObjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    prompt: str = Field(default="", max_length=2000)
    sort_order: int = Field(default=0, ge=0, le=100000)
    is_viseme_target: bool = False


class CharacterObjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    prompt: str | None = Field(default=None, max_length=2000)
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    is_viseme_target: bool | None = None


class CharacterObject(BaseModel):
    id: int
    character_id: int
    name: str
    description: str = ""
    prompt: str = ""
    sort_order: int = 0
    is_viseme_target: bool = False
    mask_count: int = 0
    created_at: str
    updated_at: str


class CharacterGenerateRequest(BaseModel):
    pose_subfolder: str | None = Field(default=None, max_length=240)


class ScriptAudioCandidateVisemeEvent(BaseModel):
    id: int | None = None
    script_audio_candidate_id: int
    viseme_key: str
    start_seconds: float
    end_seconds: float
    sort_order: int = 0
    created_at: str | None = None


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
    sort_order: int = 0
    keyboard_target_enabled: bool = False
    pickup_uploaded_file_id: int | None = None
    visible: bool = True
    enabled: bool = True
    label: str = ""
    default_render: PreviewObjectRender | None = None
    frame_renders: list[PreviewObjectRender] = []
    animations: list[PreviewObjectAnimation] = []


class PreviewCharacterImage(BaseModel):
    id: int
    component_key: str
    variant_key: str
    kind: str
    source_group: str = ""
    source_name: str = ""
    width: int = 0
    height: int = 0
    url: str


class PreviewCharacterAnimationFrame(BaseModel):
    id: int
    character_image_id: int
    duration_seconds: float
    image: PreviewCharacterImage


class PreviewCharacterAnimation(BaseModel):
    id: int
    name: str
    frames: list[PreviewCharacterAnimationFrame] = []


class PreviewCharacterState(BaseModel):
    id: int
    name: str
    description: str = ""
    scene_id: int | None = None
    mouth_scene_object_id: int | None = None
    sort_order: int = 0
    default_x: float = 960
    default_y: float = 540
    default_scale: float = 1.0
    width: int = 0
    height: int = 0
    background_frame_index: int = 0
    objects: list[PreviewObjectState] = []
    viseme_frame_renders: dict[str, PreviewObjectRender] = {}
    images: list[PreviewCharacterImage] = []
    animations: list[PreviewCharacterAnimation] = []


class ScenePreview(BaseModel):
    scene_id: int
    title: str
    description: str
    presentation_mode: str = "base"
    background_frame_index: int = 0
    width: int
    height: int
    available_scenes: list[dict[str, Any]] = []
    overlay_scenes: list[dict[str, Any]] = []
    overlay_bindings: list[OverlaySceneBinding] = []
    global_settings: GlobalSettings | None = None
    images: list[PreviewImageFrame] = []
    objects: list[PreviewObjectState] = []
    audio_assets: list[AudioAsset] = []
    variables: list[GameVariable] = []
    verbs: list[Verb] = []
    characters: list[PreviewCharacterState] = []
    interactions: list[SceneInteraction] = []
    script_lines: list[ScriptLineDetail] = []


class SceneObjectReference(BaseModel):
    id: int
    scene_id: int
    scene_title: str
    name: str
    keyboard_target_enabled: bool = False
    inventory_image_relative_path: str | None = None


def create_app(
    db_path: Path | None = None,
    settings: Settings | None = None,
    vlm_provider: SceneVlmProvider | None = None,
    segmentation_provider: SegmentationProvider | None = None,
    inventory_image_provider: InventoryImageProvider | None = None,
    scene_removal_provider: InventoryImageProvider | None = None,
    script_localization_provider: ScriptLocalizationProvider | None = None,
    character_image_provider: CharacterImageProvider | None = None,
    viseme_extraction_provider: VisemeExtractionProvider | None = None,
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
    scene_inventory_image_provider = inventory_image_provider
    inventory_image_provider_error = None
    if scene_inventory_image_provider is None:
        try:
            scene_inventory_image_provider = build_inventory_image_provider(app_settings)
        except ValueError as exc:
            inventory_image_provider_error = str(exc)
    scene_removal_image_provider = scene_removal_provider
    scene_removal_provider_error = None
    if scene_removal_image_provider is None:
        try:
            scene_removal_image_provider = build_scene_removal_provider(app_settings)
        except ValueError as exc:
            scene_removal_provider_error = str(exc)
    line_localization_provider = script_localization_provider
    line_localization_provider_error = None
    if line_localization_provider is None:
        try:
            line_localization_provider = build_script_localization_provider(app_settings)
        except ValueError as exc:
            line_localization_provider_error = str(exc)
    scene_character_image_provider = character_image_provider
    character_image_provider_error = None
    if scene_character_image_provider is None:
        try:
            scene_character_image_provider = build_character_image_provider(app_settings)
        except ValueError as exc:
            character_image_provider_error = str(exc)
    scene_viseme_extraction_provider = viseme_extraction_provider
    viseme_extraction_provider_error = None
    if scene_viseme_extraction_provider is None:
        try:
            scene_viseme_extraction_provider = build_viseme_extraction_provider(app_settings)
        except ValueError as exc:
            viseme_extraction_provider_error = str(exc)

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
                script_localization_provider=line_localization_provider,
                script_localization_provider_error=line_localization_provider_error,
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

    @app.get("/api/dependency-health", response_model=DependencyHealthResponse)
    async def get_dependency_health(
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        dependencies = await _collect_dependency_health(
            settings=app_settings,
            vlm_provider_error=vlm_provider_error,
            segmentation_provider_error=segmentation_provider_error,
            line_localization_provider_error=line_localization_provider_error,
            inventory_image_provider_error=inventory_image_provider_error,
            scene_removal_provider_error=scene_removal_provider_error,
        )
        overall = "ok"
        if any(item["status"] == "error" for item in dependencies):
            overall = "error"
        elif any(item["status"] == "warning" for item in dependencies):
            overall = "warning"
        return {
            "status": overall,
            "dependencies": dependencies,
        }

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
        _delete_workspace_storage(
            app_settings.storage_root,
            organization_id=admin["organization_id"],
            preserve_audio_assets=True,
        )
        cleared_tables = reset_workspace_tables(
            database_path,
            preserve_audio_assets=True,
        )
        ensure_system_game_variables(database_path, admin["organization_id"])
        return {
            "ok": True,
            "cleared_tables": cleared_tables,
        }

    @app.get("/api/admin/export-project")
    def get_export_project(
        admin: dict[str, Any] = Depends(current_admin),
    ) -> FileResponse:
        temp_file = tempfile.NamedTemporaryFile(prefix="wonky-project-", suffix=".zip", delete=False)
        temp_path = Path(temp_file.name)
        temp_file.close()
        export_project_archive(
            db_path=database_path,
            storage_root=app_settings.storage_root,
            organization_id=admin["organization_id"],
            output_path=temp_path,
        )
        return FileResponse(
            temp_path,
            media_type="application/zip",
            filename=f"wonky-project-{admin['organization_id']}.zip",
            background=BackgroundTask(lambda: temp_path.unlink(missing_ok=True)),
        )

    @app.post("/api/admin/export-runtime-bundle", response_model=RuntimeBundleExportResult)
    def post_export_runtime_bundle(
        admin: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        output_path = runtime_bundle_output_path(
            app_settings.storage_root,
            admin["organization_id"],
        )
        export_summary = export_runtime_bundle(
            db_path=database_path,
            storage_root=app_settings.storage_root,
            script_audio_root=app_settings.script_audio_root,
            organization_id=admin["organization_id"],
            output_path=output_path,
            godot_project_root=Path(__file__).resolve().parents[2] / "godot",
        )
        return {
            "ok": True,
            "output_path": export_summary["output_path"],
            "archive": {
                "format_version": export_summary["format_version"],
                "scene_count": export_summary["scene_count"],
                "script_line_count": export_summary["script_line_count"],
                "file_count": export_summary["file_count"],
            },
        }

    @app.post("/api/admin/export-godot-code-files", response_model=GodotCodeExportResult)
    def post_export_godot_code_files(
        admin: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        output_path = runtime_bundle_output_path(
            app_settings.storage_root,
            admin["organization_id"],
        )
        export_summary = export_godot_code_files(
            output_path=output_path,
            godot_project_root=Path(__file__).resolve().parents[2] / "godot",
        )
        return {
            "ok": True,
            "output_path": export_summary["output_path"],
            "file_count": export_summary["file_count"],
        }

    @app.post("/api/admin/export-runtime-bundle-zip", response_model=RuntimeBundleZipExportResult)
    def post_export_runtime_bundle_zip(
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        runtime_folder_path = runtime_bundle_output_path(
            app_settings.storage_root,
            user["organization_id"],
        )
        zip_output_path = runtime_bundle_zip_output_path(
            app_settings.storage_root,
            user["organization_id"],
        )
        export_summary = export_runtime_bundle_zip(
            runtime_folder_path=runtime_folder_path,
            output_path=zip_output_path,
        )
        return {
            "ok": True,
            "output_path": export_summary["output_path"],
            "source_folder_path": export_summary["folder_path"],
            "file_count": export_summary["file_count"],
            "size_bytes": export_summary["size_bytes"],
            "download_path": "/api/admin/export-runtime-bundle-zip/download",
        }

    @app.get("/api/admin/export-runtime-bundle-zip/download")
    def get_export_runtime_bundle_zip_download(
        user: dict[str, Any] = Depends(current_user),
    ) -> FileResponse:
        zip_output_path = runtime_bundle_zip_output_path(
            app_settings.storage_root,
            user["organization_id"],
        )
        if not zip_output_path.exists() or not zip_output_path.is_file():
            raise HTTPException(status_code=404, detail="Runtime zip has not been built yet.")
        return FileResponse(
            zip_output_path,
            media_type="application/zip",
            filename=f"wonky-runtime-{user['organization_id']}.zip",
        )

    @app.post("/api/admin/export-database-backup", response_model=DatabaseBackupResult)
    def post_export_database_backup(
        admin: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        backup_summary = export_project_database_json(
            db_path=database_path,
            storage_root=app_settings.storage_root,
            organization_id=admin["organization_id"],
        )
        return {
            "ok": True,
            "backup_path": backup_summary["output_path"],
            "archive": {
                "format_version": backup_summary["format_version"],
                "table_counts": backup_summary["table_counts"],
            },
        }

    @app.post("/api/admin/import-project", response_model=ProjectImportResult)
    async def post_import_project(
        archive: UploadFile = File(...),
        admin: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        filename = (archive.filename or "").lower()
        if filename and not filename.endswith(".zip"):
            raise HTTPException(status_code=400, detail="Project import requires a .zip archive")
        if not workspace_is_empty(database_path, admin["organization_id"]):
            raise HTTPException(
                status_code=400,
                detail="Import requires an empty workspace. Reset the workspace first.",
            )
        temp_file = tempfile.NamedTemporaryFile(prefix="wonky-import-", suffix=".zip", delete=False)
        temp_path = Path(temp_file.name)
        try:
            while True:
                chunk = await archive.read(1024 * 1024)
                if not chunk:
                    break
                temp_file.write(chunk)
        finally:
            temp_file.close()
            await archive.close()
        try:
            _delete_workspace_storage(
                app_settings.storage_root,
                organization_id=admin["organization_id"],
                preserve_audio_assets=False,
            )
            cleared_tables = reset_workspace_tables(
                database_path,
                preserve_audio_assets=False,
            )
            archive_summary = import_project_archive(
                db_path=database_path,
                storage_root=app_settings.storage_root,
                organization_id=admin["organization_id"],
                imported_by_user_id=int(admin["id"]),
                archive_path=temp_path,
            )
            ensure_system_game_variables(database_path, admin["organization_id"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            temp_path.unlink(missing_ok=True)
        return {
            "ok": True,
            "cleared_tables": cleared_tables,
            "archive": archive_summary,
        }

    @app.post("/api/admin/import-database-backup", response_model=ProjectImportResult)
    def post_import_database_backup(
        admin: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        if not workspace_is_empty(database_path, admin["organization_id"]):
            raise HTTPException(
                status_code=400,
                detail="Database backup import requires an empty workspace. Reset the workspace first.",
            )
        backup_path = database_backup_path(app_settings.storage_root)
        try:
            archive_summary = import_project_database_json(
                db_path=database_path,
                storage_root=app_settings.storage_root,
                organization_id=admin["organization_id"],
                imported_by_user_id=int(admin["id"]),
                input_path=backup_path,
            )
            ensure_system_game_variables(database_path, admin["organization_id"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "cleared_tables": [],
            "archive": archive_summary,
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
        missing_translation: bool = False,
        failed_tts: bool = False,
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
            missing_translation=missing_translation,
            failed_tts=failed_tts,
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

    @app.post("/api/script-lines", response_model=ScriptLineDetail, status_code=201)
    def post_script_line(
        payload: ScriptLineCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        line = create_script_line(
            database_path,
            organization_id=user["organization_id"],
            source_text=payload.source_text.strip(),
            path_parts=_normalize_script_path_parts(payload.path_text),
        )
        for translation in payload.translations:
            if not translation.text.strip():
                continue
            update_script_translation(
                database_path,
                organization_id=user["organization_id"],
                line_id=line["line_id"],
                language=translation.language.strip().lower(),
                text=translation.text,
                review_status=translation.review_status,
                notes=translation.notes,
            )
        created = get_script_line_detail(database_path, user["organization_id"], line["line_id"])
        if created is None:
            raise RuntimeError("Created script line could not be loaded")
        if line_localization_provider is not None:
            target_languages = [
                language.strip().lower()
                for language in app_settings.script_translation_target_languages.split(",")
                if language.strip()
            ]
            create_processing_job(
                database_path,
                organization_id=user["organization_id"],
                job_type="script_line_localization",
                script_line_id=line["line_id"],
                progress_total=max(1, len(target_languages) + sum(1 for language in target_languages if language != "en")),
                message="Queued translation and TTS generation",
            )
        return created

    @app.delete("/api/script-lines/{line_id}", status_code=204)
    def delete_script_line_endpoint(
        line_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> Response:
        usage_references = list_script_line_references(database_path, user["organization_id"], line_id)
        if usage_references:
            raise HTTPException(
                status_code=409,
                detail=f"Script line #{line_id} is still referenced by scene interactions",
            )
        line = get_script_line_detail(database_path, user["organization_id"], line_id)
        if line is None:
            raise HTTPException(status_code=404, detail="Script line not found")
        for candidate in line.get("audio_candidates", []):
            relative_path = candidate.get("relative_path")
            if not relative_path:
                continue
            file_path = _safe_child_path(app_settings.script_audio_root, relative_path)
            if file_path.exists() and file_path.is_file():
                file_path.unlink()
        delete_script_line(database_path, user["organization_id"], line_id)
        return Response(status_code=204)

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

    @app.post(
        "/api/script-lines/{line_id}/generate-translation",
        response_model=ScriptTranslation,
        status_code=201,
    )
    async def post_script_line_generate_translation(
        line_id: int,
        payload: ScriptTtsGenerateRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if line_localization_provider_error:
            raise HTTPException(status_code=503, detail=line_localization_provider_error)
        if line_localization_provider is None:
            raise HTTPException(status_code=503, detail="Script localization provider is not configured")
        line = get_script_line_detail(database_path, user["organization_id"], line_id)
        if line is None:
            raise HTTPException(status_code=404, detail="Script line not found")
        language = str(payload.language or "").strip().lower()
        try:
            translation = await line_localization_provider.generate_translation(
                source_text=str(line.get("source_text") or ""),
                path_parts=list(line.get("path_parts") or []),
                language=language,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=_humanize_script_provider_error(exc, "translation"),
            ) from exc
        saved_translation = upsert_script_translation(
            database_path,
            organization_id=user["organization_id"],
            line_id=line_id,
            language=str(translation.get("language") or "").strip().lower(),
            text=str(translation.get("text") or ""),
            source=str(translation.get("source") or "auto"),
            meta=translation.get("meta") if isinstance(translation.get("meta"), dict) else {},
            review_status="approved" if str(translation.get("language") or "").strip().lower() == "en" else "needs_review",
        )
        if saved_translation is None:
            raise HTTPException(status_code=404, detail="Script line not found")
        return saved_translation

    @app.post(
        "/api/script-lines/{line_id}/audio-candidates",
        response_model=ScriptAudioCandidateUploadResult,
        status_code=201,
    )
    async def post_script_audio_candidate_upload(
        line_id: int,
        file: UploadFile = File(...),
        language: str = Form(default="en"),
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        line = get_script_line_detail(database_path, user["organization_id"], line_id)
        if line is None:
            raise HTTPException(status_code=404, detail="Script line not found")
        if not file.filename:
            raise HTTPException(status_code=400, detail="Audio file is required")
        candidate = await _ingest_review_audio_upload(
            db_path=database_path,
            settings=app_settings,
            organization_id=user["organization_id"],
            line_id=line_id,
            language=language,
            upload=file,
        )
        return {"candidate": candidate}

    @app.post(
        "/api/script-lines/{line_id}/generate-tts",
        response_model=ScriptAudioCandidateUploadResult,
        status_code=201,
    )
    async def post_script_line_generate_tts(
        line_id: int,
        payload: ScriptTtsGenerateRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if line_localization_provider_error:
            raise HTTPException(status_code=503, detail=line_localization_provider_error)
        if line_localization_provider is None:
            raise HTTPException(status_code=503, detail="Script localization provider is not configured")
        line = get_script_line_detail(database_path, user["organization_id"], line_id)
        if line is None:
            raise HTTPException(status_code=404, detail="Script line not found")
        language = str(payload.language or "").strip().lower()
        text = ""
        if language == "en":
            text = str(line.get("source_text") or "").strip()
        else:
            for translation in line.get("translations", []):
                if str(translation.get("language") or "").strip().lower() == language:
                    text = str(translation.get("text") or "").strip()
                    break
        if not text:
            raise HTTPException(status_code=400, detail=f"No {language.upper()} text is available for this line")

        try:
            generated = await line_localization_provider.generate_tts(
                line_id=line_id,
                language=language,
                text=text,
            )
        except Exception as exc:
            upsert_script_audio_candidate(
                database_path,
                organization_id=user["organization_id"],
                line_id=line_id,
                language=language,
                source_type="tts",
                manifest_status="error",
                relative_path="",
                original_path=f"generated_tts/line-{line_id}/{language}/{line_id:04d}_{language}.ogg",
                rank=0,
                error=_humanize_script_provider_error(exc, "tts"),
                source_file="",
                review_status="missing",
            )
            raise HTTPException(
                status_code=502,
                detail=_humanize_script_provider_error(exc, "tts"),
            ) from exc
        try:
            candidate = await _store_generated_tts_candidate(
                db_path=database_path,
                settings=app_settings,
                organization_id=user["organization_id"],
                line_id=line_id,
                language=language,
                wav_path=Path(generated["wav_path"]),
            )
        finally:
            working_root = generated.get("working_root")
            if isinstance(working_root, Path):
                shutil.rmtree(working_root, ignore_errors=True)
            elif working_root:
                shutil.rmtree(Path(working_root), ignore_errors=True)
        return {"candidate": candidate}

    @app.post(
        "/api/script-lines/bulk/approve-translation",
        response_model=ScriptLineBulkOperationResult,
    )
    def post_script_lines_bulk_approve_translation(
        payload: ScriptLineBulkSelectionRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        language = str(payload.language or "").strip().lower()
        succeeded = 0
        errors: list[str] = []
        for line_id in payload.line_ids:
            line = get_script_line_detail(database_path, user["organization_id"], int(line_id))
            if line is None:
                errors.append(f"Line #{line_id} was not found.")
                continue
            text = ""
            if language == "en":
                text = str(line.get("source_text") or "").strip()
            else:
                for translation in line.get("translations", []):
                    if str(translation.get("language") or "").strip().lower() == language:
                        text = str(translation.get("text") or "").strip()
                        break
            if not text:
                errors.append(f"Line #{line_id} has no {language.upper()} text to approve.")
                continue
            updated = update_script_translation_review(
                database_path,
                organization_id=user["organization_id"],
                line_id=int(line_id),
                language=language,
                review_status="approved",
                notes="",
            )
            if updated is None and language == "en":
                created_translation = upsert_script_translation(
                    database_path,
                    organization_id=user["organization_id"],
                    line_id=int(line_id),
                    language=language,
                    text=text,
                    source="source_text",
                    meta={"source_lang": "en"},
                    review_status="approved",
                )
                if created_translation is not None:
                    updated = update_script_translation_review(
                        database_path,
                        organization_id=user["organization_id"],
                        line_id=int(line_id),
                        language=language,
                        review_status="approved",
                        notes="",
                    )
            if updated is None:
                errors.append(f"Line #{line_id} could not be updated.")
                continue
            succeeded += 1
        processed = len(payload.line_ids)
        failed = processed - succeeded
        return {
            "processed": processed,
            "succeeded": succeeded,
            "failed": failed,
            "detail": f"Approved {succeeded} translation{'s' if succeeded != 1 else ''}.",
            "errors": errors,
        }

    @app.post(
        "/api/script-lines/bulk/generate-tts",
        response_model=ScriptLineBulkOperationResult,
    )
    async def post_script_lines_bulk_generate_tts(
        payload: ScriptLineBulkGenerateRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if line_localization_provider_error:
            raise HTTPException(status_code=503, detail=line_localization_provider_error)
        if line_localization_provider is None:
            raise HTTPException(status_code=503, detail="Script localization provider is not configured")
        language = str(payload.language or "").strip().lower()
        target_line_ids = [int(line_id) for line_id in payload.line_ids if int(line_id) > 0]
        if not target_line_ids:
            target_line_ids = list_script_line_ids(
                database_path,
                organization_id=user["organization_id"],
                language=language,
                query=payload.q.strip(),
                path=payload.path.strip(),
                translation_status=payload.translation_status.strip(),
                audio_status=payload.audio_status.strip(),
                audio_source=payload.audio_source.strip(),
                missing_audio=payload.missing_audio,
                missing_translation=payload.missing_translation,
                failed_tts=payload.failed_tts,
                limit=5000,
            )
        succeeded = 0
        errors: list[str] = []
        for line_id in target_line_ids:
            line = get_script_line_detail(database_path, user["organization_id"], line_id)
            if line is None:
                errors.append(f"Line #{line_id} was not found.")
                continue
            text = ""
            if language == "en":
                text = str(line.get("source_text") or "").strip()
            else:
                for translation in line.get("translations", []):
                    if str(translation.get("language") or "").strip().lower() == language:
                        text = str(translation.get("text") or "").strip()
                        break
            if not text:
                errors.append(f"Line #{line_id} has no {language.upper()} text for TTS.")
                continue
            try:
                generated = await line_localization_provider.generate_tts(
                    line_id=line_id,
                    language=language,
                    text=text,
                )
                try:
                    await _store_generated_tts_candidate(
                        db_path=database_path,
                        settings=app_settings,
                        organization_id=user["organization_id"],
                        line_id=line_id,
                        language=language,
                        wav_path=Path(generated["wav_path"]),
                    )
                    succeeded += 1
                finally:
                    working_root = generated.get("working_root")
                    if isinstance(working_root, Path):
                        shutil.rmtree(working_root, ignore_errors=True)
                    elif working_root:
                        shutil.rmtree(Path(working_root), ignore_errors=True)
            except Exception as exc:
                error_text = _humanize_script_provider_error(exc, "tts")
                upsert_script_audio_candidate(
                    database_path,
                    organization_id=user["organization_id"],
                    line_id=line_id,
                    language=language,
                    source_type="tts",
                    manifest_status="error",
                    relative_path="",
                    original_path=f"generated_tts/line-{line_id}/{language}/{line_id:04d}_{language}.ogg",
                    rank=0,
                    error=error_text,
                    source_file="",
                    review_status="missing",
                )
                errors.append(f"Line #{line_id}: {error_text}")
        processed = len(target_line_ids)
        failed = processed - succeeded
        detail = f"Generated TTS for {succeeded} line{'s' if succeeded != 1 else ''}."
        if processed == 0:
            detail = "No lines matched the current bulk action."
        return {
            "processed": processed,
            "succeeded": succeeded,
            "failed": failed,
            "detail": detail,
            "errors": errors[:25],
        }

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
        ensure_system_game_variables(database_path, user["organization_id"])
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

    @app.get("/api/overlay-bindings", response_model=list[OverlaySceneBinding])
    def get_overlay_bindings(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
        return list_overlay_scene_bindings(database_path, user["organization_id"])

    @app.get("/api/verbs", response_model=list[Verb])
    def get_verbs(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
        return list_verbs(database_path, user["organization_id"])

    @app.post("/api/verbs", response_model=Verb, status_code=201)
    def post_verb(
        verb: VerbCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        try:
            return create_verb(
                database_path,
                organization_id=user["organization_id"],
                key=_normalize_verb_key(verb.key),
                labels=_normalize_verb_labels(verb.labels),
                enabled=verb.enabled,
                sort_order=verb.sort_order,
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Verb key already exists") from exc

    @app.patch("/api/verbs/{verb_id}", response_model=Verb)
    def patch_verb(
        verb_id: int,
        verb: VerbCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        try:
            updated = update_verb(
                database_path,
                organization_id=user["organization_id"],
                verb_id=verb_id,
                key=_normalize_verb_key(verb.key),
                labels=_normalize_verb_labels(verb.labels),
                enabled=verb.enabled,
                sort_order=verb.sort_order,
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Verb key already exists") from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="Verb not found")
        return updated

    @app.delete("/api/verbs/{verb_id}", status_code=204)
    def delete_verb_endpoint(
        verb_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> Response:
        delete_verb(database_path, user["organization_id"], verb_id)
        return Response(status_code=204)

    @app.get("/api/characters", response_model=list[Character])
    def get_characters(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
        characters = []
        for row in list_characters(database_path, user["organization_id"]):
            if row.get("scene_id") is None:
                backing_scene = create_empty_scene(
                    database_path,
                    organization_id=user["organization_id"],
                    created_by_user_id=user["id"],
                    title=str(row["name"]).strip(),
                    description=f"Backing scene for character {str(row['name']).strip()}",
                    presentation_mode="character",
                )
                row = update_character(
                    database_path,
                    organization_id=user["organization_id"],
                    character_id=int(row["id"]),
                    scene_id=int(backing_scene["id"]),
                    update_scene_id=True,
                ) or row
            detail = _load_character_detail(database_path, user["organization_id"], int(row["id"]))
            if detail is not None:
                characters.append(detail)
        return characters

    @app.post("/api/characters", response_model=Character, status_code=201)
    def post_character(
        payload: CharacterCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        try:
            backing_scene = create_empty_scene(
                database_path,
                organization_id=user["organization_id"],
                created_by_user_id=user["id"],
                title=payload.name.strip(),
                description=f"Backing scene for character {payload.name.strip()}",
                presentation_mode="character",
            )
            character = create_character(
                database_path,
                organization_id=user["organization_id"],
                name=payload.name,
                description=payload.description,
                scene_id=int(backing_scene["id"]),
                sort_order=payload.sort_order,
                default_x=payload.default_x,
                default_y=payload.default_y,
                default_scale=payload.default_scale,
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Character name already exists") from exc
        return _load_character_detail(database_path, user["organization_id"], int(character["id"]))

    @app.get("/api/characters/{character_id}", response_model=Character)
    def get_character(
        character_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        character_record = get_character_by_id(database_path, user["organization_id"], character_id)
        if character_record is None:
            raise HTTPException(status_code=404, detail="Character not found")
        if character_record.get("scene_id") is None:
            backing_scene = create_empty_scene(
                database_path,
                organization_id=user["organization_id"],
                created_by_user_id=user["id"],
                title=str(character_record["name"]).strip(),
                description=f"Backing scene for character {str(character_record['name']).strip()}",
                presentation_mode="character",
            )
            update_character(
                database_path,
                organization_id=user["organization_id"],
                character_id=character_id,
                scene_id=int(backing_scene["id"]),
                update_scene_id=True,
            )
        character = _load_character_detail(database_path, user["organization_id"], character_id)
        if not character:
            raise HTTPException(status_code=404, detail="Character not found")
        return character

    @app.get("/api/character-pose-folders", response_model=list[str])
    def get_character_pose_folders(user: dict[str, Any] = Depends(current_user)) -> list[str]:
        root = app_settings.character_pose_source_root
        if not root.exists() or not root.is_dir():
            return []
        return [entry.name for entry in sorted(root.iterdir()) if entry.is_dir()]

    @app.patch("/api/characters/{character_id}", response_model=Character)
    def patch_character(
        character_id: int,
        payload: CharacterUpdate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        existing = get_character_by_id(database_path, user["organization_id"], character_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Character not found")
        mouth_scene_object_id = payload.mouth_scene_object_id
        update_mouth_scene_object_id = payload.clear_mouth_scene_object_id or mouth_scene_object_id is not None
        if mouth_scene_object_id is not None:
            scene_object = get_scene_object_for_organization(
                database_path,
                object_id=mouth_scene_object_id,
                organization_id=user["organization_id"],
            )
            if scene_object is None or int(scene_object["scene_id"]) != int(existing.get("scene_id") or 0):
                raise HTTPException(status_code=400, detail="Mouth target must belong to this character")
        try:
            updated = update_character(
                database_path,
                organization_id=user["organization_id"],
                character_id=character_id,
                name=payload.name,
                description=payload.description,
                mouth_scene_object_id=mouth_scene_object_id,
                update_mouth_scene_object_id=update_mouth_scene_object_id,
                sort_order=payload.sort_order,
                default_x=payload.default_x,
                default_y=payload.default_y,
                default_scale=payload.default_scale,
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Character name already exists") from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="Character not found")
        if updated.get("scene_id") is not None and (payload.name is not None or payload.description is not None):
            update_scene(
                database_path,
                scene_id=int(updated["scene_id"]),
                organization_id=user["organization_id"],
                title=payload.name.strip() if isinstance(payload.name, str) else None,
                description=payload.description if payload.description is not None else None,
            )
        return _load_character_detail(database_path, user["organization_id"], character_id)

    @app.delete("/api/characters/{character_id}", status_code=204)
    def delete_character_endpoint(
        character_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> Response:
        character = get_character_by_id(database_path, user["organization_id"], character_id)
        if character is None:
            raise HTTPException(status_code=404, detail="Character not found")
        scene_id = int(character["scene_id"]) if character.get("scene_id") is not None else None
        image_rows = list_character_images(database_path, user["organization_id"], character_id)
        if not delete_character(database_path, user["organization_id"], character_id):
            raise HTTPException(status_code=404, detail="Character not found")
        for image in image_rows:
            image_path = app_settings.storage_root / image["relative_path"]
            image_path.unlink(missing_ok=True)
        if scene_id is not None:
            deleted_scene = delete_scene_and_unhook_references(
                database_path,
                scene_id=scene_id,
                organization_id=user["organization_id"],
            )
            if deleted_scene is not None:
                for relative_path in deleted_scene.get("deleted_uploaded_file_relative_paths") or []:
                    try:
                        file_path = _safe_child_path(app_settings.storage_root, relative_path)
                    except HTTPException:
                        continue
                    file_path.unlink(missing_ok=True)
                _clear_scene_derived_cache(app_settings.storage_root, user["organization_id"], scene_id)
                _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)
        return Response(status_code=204)

    @app.post("/api/characters/{character_id}/images", response_model=CharacterImage, status_code=201)
    async def post_character_image(
        character_id: int,
        file: UploadFile = File(...),
        component_key: str = Form(...),
        variant_key: str = Form(...),
        kind: str = Form(...),
        source_group: str = Form(""),
        source_name: str = Form(""),
        is_default: bool = Form(False),
        sort_order: int = Form(0),
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        character = get_character_by_id(database_path, user["organization_id"], character_id)
        if character is None:
            raise HTTPException(status_code=404, detail="Character not found")
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(status_code=400, detail="Unsupported image type")
        safe_variant_key = _safe_path_segment(variant_key)
        relative_path = str(
            Path(_safe_path_segment(user["organization_id"]))
            / "characters"
            / str(character_id)
            / _safe_path_segment(component_key)
            / f"{safe_variant_key}{suffix}"
        )
        output_path = app_settings.storage_root / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        await _write_upload(file, output_path)
        width, height = _image_dimensions(output_path)
        image = upsert_character_image(
            database_path,
            organization_id=user["organization_id"],
            character_id=character_id,
            component_key=component_key,
            variant_key=variant_key.strip(),
            kind=kind,
            source_group=source_group.strip(),
            source_name=source_name.strip() or (Path(file.filename or "").name),
            relative_path=relative_path,
            original_filename=str(file.filename or ""),
            width=width,
            height=height,
            is_default=is_default,
            sort_order=sort_order,
        )
        return image

    @app.delete("/api/character-images/{image_id}", status_code=204)
    def delete_character_image_endpoint(
        image_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> Response:
        image = get_character_image_by_id(database_path, user["organization_id"], image_id)
        if image is None:
            raise HTTPException(status_code=404, detail="Character image not found")
        delete_character_image(database_path, user["organization_id"], image_id)
        (app_settings.storage_root / image["relative_path"]).unlink(missing_ok=True)
        return Response(status_code=204)

    @app.get("/api/character-images/{image_id}/content")
    def get_character_image_content(
        image_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> FileResponse:
        image = get_character_image_by_id(database_path, user["organization_id"], image_id)
        if image is None:
            raise HTTPException(status_code=404, detail="Character image not found")
        file_path = app_settings.storage_root / image["relative_path"]
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Character image file not found")
        return FileResponse(
            file_path,
            media_type=_content_type_for_suffix(file_path.suffix),
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @app.get("/api/characters/{character_id}/objects", response_model=list[CharacterObject])
    def get_character_objects_endpoint(
        character_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        return list_character_objects(database_path, user["organization_id"], character_id)

    @app.post("/api/characters/{character_id}/objects", response_model=CharacterObject, status_code=201)
    def post_character_object(
        character_id: int,
        payload: CharacterObjectCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        try:
            return create_character_object(
                database_path,
                organization_id=user["organization_id"],
                character_id=character_id,
                name=payload.name,
                description=payload.description,
                prompt=payload.prompt,
                sort_order=payload.sort_order,
                is_viseme_target=payload.is_viseme_target,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/character-objects/{character_object_id}", response_model=CharacterObject)
    def patch_character_object(
        character_object_id: int,
        payload: CharacterObjectUpdate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        updated = update_character_object(
            database_path,
            organization_id=user["organization_id"],
            character_object_id=character_object_id,
            name=payload.name,
            description=payload.description,
            prompt=payload.prompt,
            sort_order=payload.sort_order,
            is_viseme_target=payload.is_viseme_target,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Character object not found")
        return updated

    @app.delete("/api/character-objects/{character_object_id}", status_code=204)
    def delete_character_object_endpoint(
        character_object_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> Response:
        if not delete_character_object(database_path, user["organization_id"], character_object_id):
            raise HTTPException(status_code=404, detail="Character object not found")
        return Response(status_code=204)

    @app.post("/api/characters/{character_id}/animations", response_model=CharacterAnimation, status_code=201)
    def post_character_animation(
        character_id: int,
        payload: CharacterAnimationCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        try:
            return create_character_animation(
                database_path,
                organization_id=user["organization_id"],
                character_id=character_id,
                name=payload.name,
                frames=[frame.model_dump() for frame in payload.frames],
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Character animation name already exists") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/character-animations/{animation_id}", response_model=CharacterAnimation)
    def patch_character_animation(
        animation_id: int,
        payload: CharacterAnimationCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        try:
            updated = update_character_animation(
                database_path,
                organization_id=user["organization_id"],
                animation_id=animation_id,
                name=payload.name,
                frames=[frame.model_dump() for frame in payload.frames],
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Character animation name already exists") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="Character animation not found")
        return updated

    @app.delete("/api/character-animations/{animation_id}", status_code=204)
    def delete_character_animation_endpoint(
        animation_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> Response:
        if not delete_character_animation(database_path, user["organization_id"], animation_id):
            raise HTTPException(status_code=404, detail="Character animation not found")
        return Response(status_code=204)

    @app.post("/api/characters/{character_id}/generate-visemes", response_model=Character)
    async def post_generate_character_visemes(
        character_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        character = _load_character_detail(database_path, user["organization_id"], character_id)
        if character is None:
            raise HTTPException(status_code=404, detail="Character not found")
        scene = character.get("scene")
        if not scene or not scene.get("images"):
            raise HTTPException(status_code=400, detail="Character needs at least one frame first")
        default_image = _character_default_scene_image(character)
        if default_image is None:
            raise HTTPException(status_code=400, detail="Character needs a default frame first")
        if character_image_provider_error:
            raise HTTPException(status_code=503, detail=character_image_provider_error)
        if scene_character_image_provider is None:
            raise HTTPException(status_code=503, detail="Character image generation is not configured")
        source_folder = app_settings.character_viseme_source_root
        prompt_text = (
            "please apply the exact (paying attention to teeth and tongue) mouth shape from image 2 "
            "to the character in image 1 keeping everything else intact,  especially any mustache and beard"
        )
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
        output_root = batch_root / _safe_path_segment(source_folder.name)
        try:
            results = await scene_character_image_provider.generate_variants(
                base_image_path=app_settings.storage_root / default_image["relative_path"],
                source_folder=source_folder,
                prompt_text=prompt_text,
                output_root=output_root,
                filename_prefix_root=f"characters/{character_id}/visemes/{_safe_path_segment(source_folder.name)}",
            )
        except CharacterImageProviderUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        for sort_order, (source_path, output_path) in enumerate(results):
            original_filename = f"{source_folder.name}-{source_path.name}"
            stored_filename = f"{sort_order:03d}-{_safe_filename(original_filename)}"
            stored_path = batch_root / stored_filename
            shutil.move(output_path, stored_path)
            file_size = stored_path.stat().st_size
            uploaded_file = add_uploaded_file(
                database_path,
                batch_id=batch["id"],
                organization_id=user["organization_id"],
                uploaded_by_user_id=user["id"],
                original_filename=original_filename,
                stored_filename=stored_filename,
                relative_path=str(Path(user["organization_id"]) / str(batch["id"]) / stored_filename),
                content_type=_content_type_for_suffix(stored_path.suffix),
                file_size=file_size,
            )
            fingerprint = fingerprint_image(stored_path)
            assign_uploaded_file_to_scene(
                database_path,
                scene_id=int(character["scene_id"]),
                uploaded_file_id=int(uploaded_file["id"]),
                perceptual_hash=fingerprint.perceptual_hash,
                width=fingerprint.width,
                height=fingerprint.height,
            )
            del sort_order
        _invalidate_scene_preview_manifest_cache(
            app_settings.storage_root,
            user["organization_id"],
            int(character["scene_id"]),
        )
        return _load_character_detail(database_path, user["organization_id"], character_id)

    @app.post("/api/characters/{character_id}/generate-poses", response_model=Character)
    async def post_generate_character_poses(
        character_id: int,
        payload: CharacterGenerateRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        character = _load_character_detail(database_path, user["organization_id"], character_id)
        if character is None:
            raise HTTPException(status_code=404, detail="Character not found")
        scene = character.get("scene")
        if not scene or not scene.get("images"):
            raise HTTPException(status_code=400, detail="Character needs at least one frame first")
        default_image = _character_default_scene_image(character)
        if default_image is None:
            raise HTTPException(status_code=400, detail="Character needs a default frame first")
        if character_image_provider_error:
            raise HTTPException(status_code=503, detail=character_image_provider_error)
        if scene_character_image_provider is None:
            raise HTTPException(status_code=503, detail="Character image generation is not configured")
        pose_folder = _resolve_pose_subfolder(app_settings.character_pose_source_root, payload.pose_subfolder)
        prompt_text = (
            "please apply the pose from image 2 to the character in image 1 being sure to retain "
            "the same clothing, facial features or objects"
        )
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
        output_root = batch_root / _safe_path_segment(pose_folder.name)
        try:
            results = await scene_character_image_provider.generate_variants(
                base_image_path=app_settings.storage_root / default_image["relative_path"],
                source_folder=pose_folder,
                prompt_text=prompt_text,
                output_root=output_root,
                filename_prefix_root=f"characters/{character_id}/poses/{_safe_path_segment(pose_folder.name)}",
            )
        except CharacterImageProviderUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        for sort_order, (source_path, output_path) in enumerate(results):
            original_filename = f"{pose_folder.name}-{source_path.name}"
            stored_filename = f"{sort_order:03d}-{_safe_filename(original_filename)}"
            stored_path = batch_root / stored_filename
            shutil.move(output_path, stored_path)
            file_size = stored_path.stat().st_size
            uploaded_file = add_uploaded_file(
                database_path,
                batch_id=batch["id"],
                organization_id=user["organization_id"],
                uploaded_by_user_id=user["id"],
                original_filename=original_filename,
                stored_filename=stored_filename,
                relative_path=str(Path(user["organization_id"]) / str(batch["id"]) / stored_filename),
                content_type=_content_type_for_suffix(stored_path.suffix),
                file_size=file_size,
            )
            fingerprint = fingerprint_image(stored_path)
            assign_uploaded_file_to_scene(
                database_path,
                scene_id=int(character["scene_id"]),
                uploaded_file_id=int(uploaded_file["id"]),
                perceptual_hash=fingerprint.perceptual_hash,
                width=fingerprint.width,
                height=fingerprint.height,
            )
            del sort_order
        _invalidate_scene_preview_manifest_cache(
            app_settings.storage_root,
            user["organization_id"],
            int(character["scene_id"]),
        )
        return _load_character_detail(database_path, user["organization_id"], character_id)

    @app.post("/api/script-audio-candidates/{candidate_id}/extract-visemes", response_model=ScriptAudioCandidate)
    async def post_extract_script_audio_candidate_visemes(
        candidate_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        candidate = get_script_audio_candidate_by_id(database_path, user["organization_id"], candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Audio candidate not found")
        if not candidate.get("relative_path"):
            raise HTTPException(status_code=400, detail="Audio candidate does not have a file yet")
        if viseme_extraction_provider_error:
            raise HTTPException(status_code=503, detail=viseme_extraction_provider_error)
        if scene_viseme_extraction_provider is None:
            raise HTTPException(status_code=503, detail="Viseme extraction is not configured")
        script_line = get_script_line_detail(
            database_path,
            user["organization_id"],
            int(candidate["script_line_id"]),
        )
        if script_line is None:
            raise HTTPException(status_code=404, detail="Script line not found")
        language = str(candidate.get("language") or "").strip().lower() or "en"
        text = str(script_line.get("source_text") or "").strip()
        if language != "en":
            translation = next(
                (
                    item
                    for item in (script_line.get("translations") or [])
                    if str(item.get("language") or "").strip().lower() == language
                    and str(item.get("text") or "").strip()
                ),
                None,
            )
            if translation is not None:
                text = str(translation.get("text") or "").strip()
        try:
            events = await scene_viseme_extraction_provider.extract_visemes(
                audio_path=app_settings.script_audio_root / candidate["relative_path"],
                language=language,
                text=text,
            )
        except VisemeExtractionProviderUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        replace_script_audio_candidate_viseme_events(
            database_path,
            organization_id=user["organization_id"],
            candidate_id=candidate_id,
            events=events,
        )
        updated = get_script_audio_candidate_by_id(database_path, user["organization_id"], candidate_id)
        if updated is None:
            raise HTTPException(status_code=404, detail="Audio candidate not found")
        updated["viseme_events"] = list_script_audio_candidate_viseme_events(database_path, user["organization_id"], candidate_id)
        return updated

    @app.get("/api/global-settings", response_model=GlobalSettings)
    def get_global_settings_endpoint(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return get_global_settings(database_path, user["organization_id"])

    @app.patch("/api/global-settings", response_model=GlobalSettings)
    def patch_global_settings_endpoint(
        settings_update: GlobalSettingsUpdate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        update_start_scene_id = "start_scene_id" in settings_update.model_fields_set
        if update_start_scene_id and settings_update.start_scene_id is not None:
            _require_base_scene(
                database_path,
                settings_update.start_scene_id,
                user["organization_id"],
            )
        return update_global_settings(
            database_path,
            organization_id=user["organization_id"],
            overlay_open_duration_seconds=settings_update.overlay_open_duration_seconds,
            overlay_close_duration_seconds=settings_update.overlay_close_duration_seconds,
            overlay_fade_color=settings_update.overlay_fade_color,
            overlay_affect_audio=settings_update.overlay_affect_audio,
            start_scene_id=settings_update.start_scene_id,
            inventory_key_code=_normalize_key_code(settings_update.inventory_key_code)
            if settings_update.inventory_key_code
            else None,
            verb_menu_timeout_seconds=settings_update.verb_menu_timeout_seconds,
            verb_menu_show_disabled=settings_update.verb_menu_show_disabled,
            verb_text_color=settings_update.verb_text_color,
            inventory_slots=[
                slot.model_dump()
                for slot in (settings_update.inventory_slots or [])
            ] if "inventory_slots" in settings_update.model_fields_set else None,
            cursor_states=settings_update.cursor_states
            if "cursor_states" in settings_update.model_fields_set
            else None,
            update_start_scene_id=update_start_scene_id,
        )

    @app.post("/api/global-settings/assets/{asset_kind}", response_model=GlobalSettings)
    async def post_global_settings_asset(
        asset_kind: str,
        file: UploadFile = File(...),
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        cursor_asset_kind_map = {
            "cursor_default": "default",
            "cursor_hover_interactive": "hover_interactive",
            "cursor_busy": "busy",
            "cursor_blocked": "blocked",
        }
        if asset_kind not in {"inventory_background", "verb_tag_background", *cursor_asset_kind_map.keys()}:
            raise HTTPException(status_code=404, detail="Global settings asset not found")
        original_name = _safe_filename(file.filename or f"{asset_kind}.png")
        suffix = Path(original_name).suffix.lower() or ".png"
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(status_code=400, detail="Unsupported image type")
        relative_path = str(
            Path(_safe_path_segment(user["organization_id"]))
            / "global-settings"
            / f"{asset_kind}{suffix}"
        )
        output_path = app_settings.storage_root / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        await _write_upload(file, output_path)
        if asset_kind in cursor_asset_kind_map:
            current_settings = get_global_settings(database_path, user["organization_id"])
            cursor_states = {
                key: dict(value)
                for key, value in (current_settings.get("cursor_states") or {}).items()
                if isinstance(value, dict)
            }
            state_key = cursor_asset_kind_map[asset_kind]
            cursor_state = dict(cursor_states.get(state_key) or {})
            cursor_state["relative_path"] = relative_path
            cursor_states[state_key] = cursor_state
            return update_global_settings(
                database_path,
                organization_id=user["organization_id"],
                cursor_states=cursor_states,
            )
        return update_global_settings(
            database_path,
            organization_id=user["organization_id"],
            inventory_background_relative_path=relative_path if asset_kind == "inventory_background" else None,
            verb_tag_background_relative_path=relative_path if asset_kind == "verb_tag_background" else None,
            update_inventory_background_relative_path=asset_kind == "inventory_background",
            update_verb_tag_background_relative_path=asset_kind == "verb_tag_background",
        )

    @app.get("/api/global-settings/assets/{asset_kind}/content")
    def get_global_settings_asset(
        asset_kind: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> FileResponse:
        cursor_asset_kind_map = {
            "cursor_default": "default",
            "cursor_hover_interactive": "hover_interactive",
            "cursor_busy": "busy",
            "cursor_blocked": "blocked",
        }
        if asset_kind not in {"inventory_background", "verb_tag_background", *cursor_asset_kind_map.keys()}:
            raise HTTPException(status_code=404, detail="Global settings asset not found")
        settings_row = get_global_settings(database_path, user["organization_id"])
        if asset_kind == "inventory_background":
            relative_path = settings_row.get("inventory_background_relative_path")
        elif asset_kind == "verb_tag_background":
            relative_path = settings_row.get("verb_tag_background_relative_path")
        else:
            state_key = cursor_asset_kind_map[asset_kind]
            relative_path = (settings_row.get("cursor_states") or {}).get(state_key, {}).get("relative_path")
        if not relative_path:
            raise HTTPException(status_code=404, detail="Global settings asset not found")
        file_path = app_settings.storage_root / relative_path
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Global settings asset content not found")
        return FileResponse(
            file_path,
            media_type=_content_type_for_suffix(file_path.suffix),
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @app.post("/api/overlay-bindings", response_model=OverlaySceneBinding, status_code=201)
    def post_overlay_binding(
        binding: OverlaySceneBindingCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        normalized_key = _normalize_key_code(binding.key_code)
        target_scene = _require_overlay_scene(database_path, binding.overlay_scene_id, user["organization_id"])
        del target_scene
        return create_or_update_overlay_scene_binding(
            database_path,
            organization_id=user["organization_id"],
            key_code=normalized_key,
            overlay_scene_id=binding.overlay_scene_id,
        )

    @app.delete("/api/overlay-bindings/{binding_id}", status_code=204)
    def delete_overlay_binding_endpoint(
        binding_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> Response:
        delete_overlay_scene_binding(database_path, user["organization_id"], binding_id)
        return Response(status_code=204)

    @app.get("/api/scene-objects", response_model=list[SceneObjectReference])
    def get_scene_object_references(
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        return list_scene_objects_for_organization(database_path, user["organization_id"])

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
        created_interaction = create_scene_interaction(
            database_path,
            scene_id=scene_id,
            organization_id=user["organization_id"],
            name=interaction.name,
            enabled=interaction.enabled,
            trigger=trigger,
            action_tree=action_tree,
        )
        _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)
        return created_interaction

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
        _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)
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
        _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)
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

    @app.get("/api/images", response_model=list[UploadedImageSummary])
    def get_images(
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        return list_uploaded_image_files(database_path, user["organization_id"])

    @app.post("/api/images/move", response_model=list[UploadedImageSummary])
    def post_move_images(
        request: ImageMoveRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        _require_scene(
            database_path,
            scene_id=request.target_scene_id,
            organization_id=user["organization_id"],
        )
        current_images_by_uploaded_file_id = {
            int(item["uploaded_file_id"]): item
            for item in list_uploaded_image_files(database_path, user["organization_id"])
        }
        affected_scene_ids: set[int] = {int(request.target_scene_id)}
        seen_uploaded_file_ids: set[int] = set()
        for uploaded_file_id in request.uploaded_file_ids:
            normalized_uploaded_file_id = int(uploaded_file_id)
            if normalized_uploaded_file_id in seen_uploaded_file_ids:
                continue
            seen_uploaded_file_ids.add(normalized_uploaded_file_id)
            current_image = current_images_by_uploaded_file_id.get(normalized_uploaded_file_id)
            if current_image and current_image.get("scene_id") is not None:
                affected_scene_ids.add(int(current_image["scene_id"]))
            uploaded_file = get_uploaded_file_by_id(
                database_path,
                uploaded_file_id=normalized_uploaded_file_id,
                organization_id=user["organization_id"],
            )
            if uploaded_file is None:
                raise HTTPException(status_code=404, detail=f"Uploaded file {normalized_uploaded_file_id} not found")
            image_path = app_settings.storage_root / uploaded_file["relative_path"]
            if not image_path.exists():
                raise HTTPException(status_code=404, detail=f"Uploaded file content missing for {normalized_uploaded_file_id}")
            fingerprint = fingerprint_image(image_path)
            assign_uploaded_file_to_scene(
                database_path,
                scene_id=request.target_scene_id,
                uploaded_file_id=normalized_uploaded_file_id,
                perceptual_hash=fingerprint.perceptual_hash,
                width=fingerprint.width,
                height=fingerprint.height,
            )
        for affected_scene_id in affected_scene_ids:
            _invalidate_scene_preview_manifest_cache(
                app_settings.storage_root,
                user["organization_id"],
                affected_scene_id,
            )
        return list_uploaded_image_files(database_path, user["organization_id"])

    @app.get("/api/scenes", response_model=list[SceneSummary])
    def get_scenes(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
        return list_scenes(database_path, user["organization_id"])

    @app.get("/api/workspace-summary", response_model=WorkspaceSummary)
    def get_workspace_summary_endpoint(
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, int]:
        target_languages = [
            language.strip().lower()
            for language in app_settings.script_translation_target_languages.split(",")
            if language.strip()
        ]
        if "en" not in target_languages:
            target_languages.insert(0, "en")
        return get_workspace_summary(
            database_path,
            user["organization_id"],
            languages=target_languages,
        )

    @app.post("/api/scenes", response_model=Scene, status_code=201)
    def post_scene(
        payload: SceneCreate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        scene = create_empty_scene(
            database_path,
            organization_id=user["organization_id"],
            created_by_user_id=user["id"],
            title=payload.title.strip(),
            description=payload.description.strip(),
            presentation_mode=payload.presentation_mode,
        )
        full_scene = get_scene_with_images(database_path, int(scene["id"]))
        if full_scene is None:
            raise RuntimeError("Created scene could not be loaded")
        return full_scene

    @app.post("/api/scenes/{scene_id}/move", response_model=list[SceneSummary])
    def post_move_scene(
        scene_id: int,
        payload: SceneMoveRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        if not scene_belongs_to_organization(
            database_path,
            scene_id=scene_id,
            organization_id=user["organization_id"],
        ):
            raise HTTPException(status_code=404, detail="Scene not found")
        try:
            return move_scene_sort_order(
                database_path,
                organization_id=user["organization_id"],
                scene_id=scene_id,
                direction=payload.direction,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/scenes/{scene_id}", response_model=Scene)
    def get_scene(
        scene_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        scene = get_scene_with_images(database_path, scene_id)
        if scene is None or scene["organization_id"] != user["organization_id"]:
            raise HTTPException(status_code=404, detail="Scene not found")
        return _annotate_scene_inventory_image_statuses(app_settings.storage_root, scene)

    @app.patch("/api/scenes/{scene_id}", response_model=Scene)
    def patch_scene(
        scene_id: int,
        update: SceneUpdate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        scene = get_scene_with_images(database_path, scene_id)
        if scene is None or scene["organization_id"] != user["organization_id"]:
            raise HTTPException(status_code=404, detail="Scene not found")
        image_count = len(scene.get("images", []))
        if update.background_frame_index is not None:
            if image_count == 0 and int(update.background_frame_index) != 0:
                raise HTTPException(status_code=400, detail="Background frame must be 0 for scenes without images")
            if image_count > 0 and int(update.background_frame_index) >= image_count:
                raise HTTPException(status_code=400, detail="Background frame is outside this scene's image range")
        updated = update_scene(
            database_path,
            scene_id=scene_id,
            organization_id=user["organization_id"],
            title=update.title.strip() if isinstance(update.title, str) else None,
            description=update.description if update.description is not None else None,
            presentation_mode=update.presentation_mode,
            background_frame_index=update.background_frame_index,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Scene not found")
        _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)
        return _annotate_scene_inventory_image_statuses(app_settings.storage_root, updated)

    @app.delete("/api/scenes/{scene_id}", response_model=SceneDeleteResult)
    def delete_scene_endpoint(
        scene_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> SceneDeleteResult:
        deleted = delete_scene_and_unhook_references(
            database_path,
            scene_id=scene_id,
            organization_id=user["organization_id"],
        )
        if deleted is None:
            raise HTTPException(status_code=404, detail="Scene not found")
        for relative_path in deleted.get("deleted_uploaded_file_relative_paths") or []:
            try:
                file_path = _safe_child_path(app_settings.storage_root, relative_path)
            except HTTPException:
                continue
            file_path.unlink(missing_ok=True)
        _clear_scene_derived_cache(app_settings.storage_root, user["organization_id"], scene_id)
        _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)
        for touched_scene_id in deleted.get("touched_scene_ids") or []:
            _invalidate_scene_preview_manifest_cache(
                app_settings.storage_root,
                user["organization_id"],
                int(touched_scene_id),
            )
        return SceneDeleteResult(
            ok=True,
            scene_id=int(deleted["scene_id"]),
            scene_title=str(deleted["scene_title"]),
            deleted_image_count=int(deleted["deleted_image_count"]),
            deleted_object_count=int(deleted["deleted_object_count"]),
            deleted_interaction_count=int(deleted["deleted_interaction_count"]),
            deleted_processing_job_count=int(deleted["deleted_processing_job_count"]),
            removed_scene_reference_count=int(deleted["removed_scene_reference_count"]),
            updated_interaction_count=int(deleted["updated_interaction_count"]),
            removed_overlay_binding_count=int(deleted["removed_overlay_binding_count"]),
            cleared_start_scene=bool(deleted["cleared_start_scene"]),
            touched_scene_ids=[int(value) for value in (deleted.get("touched_scene_ids") or [])],
        )

    @app.post("/api/scenes/{scene_id}/images", response_model=Scene)
    async def post_scene_images(
        scene_id: int,
        files: list[UploadFile] = File(...),
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if not files:
            raise HTTPException(status_code=400, detail="At least one file is required")
        _require_scene(
            database_path,
            scene_id=scene_id,
            organization_id=user["organization_id"],
        )
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
            uploaded_file = add_uploaded_file(
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
            try:
                fingerprint = fingerprint_image(stored_path)
            except OSError as exc:
                raise HTTPException(status_code=400, detail=f"{original_filename} is not a supported image") from exc
            assign_uploaded_file_to_scene(
                database_path,
                scene_id=scene_id,
                uploaded_file_id=int(uploaded_file["id"]),
                perceptual_hash=fingerprint.perceptual_hash,
                width=fingerprint.width,
                height=fingerprint.height,
            )

        updated_scene = get_scene_with_images(database_path, scene_id)
        if updated_scene is None:
            raise RuntimeError("Updated scene could not be loaded")
        _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)
        return _annotate_scene_inventory_image_statuses(app_settings.storage_root, updated_scene)

    @app.post("/api/scenes/{scene_id}/images/reorder", response_model=list[SceneImage])
    def post_reorder_scene_images(
        scene_id: int,
        request: SceneImageReorderRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> list[dict[str, Any]]:
        _require_scene(
            database_path,
            scene_id=scene_id,
            organization_id=user["organization_id"],
        )
        try:
            reordered = reorder_scene_images(
                database_path,
                scene_id=scene_id,
                ordered_scene_image_ids=[int(value) for value in request.ordered_scene_image_ids],
            )
            _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)
            return reordered
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/scenes/{scene_id}/merge-into", response_model=Scene)
    def post_merge_scene_into(
        scene_id: int,
        request: SceneMergeRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if scene_id == request.target_scene_id:
            raise HTTPException(status_code=400, detail="Source and target scenes must be different.")
        source_scene = get_scene_with_images(database_path, scene_id)
        if source_scene is None or source_scene["organization_id"] != user["organization_id"]:
            raise HTTPException(status_code=404, detail="Scene not found")
        target_scene = _require_base_scene(
            database_path,
            request.target_scene_id,
            user["organization_id"],
        )
        del target_scene
        merged_scene = merge_scene_into_scene(
            database_path,
            organization_id=user["organization_id"],
            source_scene_id=scene_id,
            target_scene_id=request.target_scene_id,
        )
        if merged_scene is None:
            raise HTTPException(status_code=404, detail="Scene not found")
        _clear_scene_derived_cache(app_settings.storage_root, user["organization_id"], scene_id)
        _clear_scene_derived_cache(
            app_settings.storage_root,
            user["organization_id"],
            request.target_scene_id,
        )
        _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)
        _invalidate_scene_preview_manifest_cache(
            app_settings.storage_root,
            user["organization_id"],
            request.target_scene_id,
        )
        return _annotate_scene_inventory_image_statuses(app_settings.storage_root, merged_scene)

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
            inventory_image_prompt=scene_object.inventory_image_prompt,
        )
        _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)
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
            inventory_image_prompt=scene_object.inventory_image_prompt,
            sort_order=scene_object.sort_order,
            visible=scene_object.visible,
            enabled=scene_object.enabled,
            keyboard_target_enabled=scene_object.keyboard_target_enabled,
        )
        if updated_object is None:
            raise HTTPException(status_code=404, detail="Object not found")
        _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)
        return {**updated_object, "mask_image_count": 0, "masks": []}

    @app.post("/api/scenes/{scene_id}/objects/{object_id}/default-frame", response_model=SceneObject)
    def post_scene_object_default_frame(
        scene_id: int,
        object_id: int,
        payload: SceneObjectDefaultFrameUpdate,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if not scene_belongs_to_organization(
            database_path,
            scene_id=scene_id,
            organization_id=user["organization_id"],
        ):
            raise HTTPException(status_code=404, detail="Scene not found")
        scene_object = get_scene_object_for_organization(
            database_path,
            object_id=object_id,
            organization_id=user["organization_id"],
        )
        if scene_object is None or int(scene_object["scene_id"]) != scene_id:
            raise HTTPException(status_code=404, detail="Object not found")
        uploaded_file_id = payload.uploaded_file_id
        if uploaded_file_id is not None:
            object_masks = list_object_masks_for_object(
                database_path,
                scene_object_id=object_id,
                organization_id=user["organization_id"],
            )
            valid_uploaded_file_ids = {
                int(object_mask["uploaded_file_id"])
                for object_mask in object_masks
            }
            if int(uploaded_file_id) not in valid_uploaded_file_ids:
                raise HTTPException(status_code=400, detail="Default frame must reference one of this object's masked frames")
        updated_object = update_scene_object(
            database_path,
            scene_id=scene_id,
            object_id=object_id,
            default_uploaded_file_id=uploaded_file_id,
            update_default_uploaded_file_id=True,
        )
        if updated_object is None:
            raise HTTPException(status_code=404, detail="Object not found")
        _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)
        return {**updated_object, "mask_image_count": 0, "masks": []}

    @app.post("/api/scenes/{scene_id}/objects/{object_id}/masks", response_model=ObjectMask, status_code=201)
    def post_scene_object_mask(
        scene_id: int,
        object_id: int,
        payload: SceneObjectMaskCreateRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if not scene_belongs_to_organization(
            database_path,
            scene_id=scene_id,
            organization_id=user["organization_id"],
        ):
            raise HTTPException(status_code=404, detail="Scene not found")
        scene_object = get_scene_object_for_organization(
            database_path,
            object_id=object_id,
            organization_id=user["organization_id"],
        )
        if scene_object is None or int(scene_object["scene_id"]) != scene_id:
            raise HTTPException(status_code=404, detail="Object not found")
        scene_images = list_scene_images_for_scene(database_path, scene_id)
        scene_image = next(
            (
                image
                for image in scene_images
                if int(image["uploaded_file_id"]) == int(payload.uploaded_file_id)
            ),
            None,
        )
        if scene_image is None:
            raise HTTPException(status_code=400, detail="Frame does not belong to this scene")
        uploaded_file = get_uploaded_file_by_id(
            database_path,
            uploaded_file_id=int(payload.uploaded_file_id),
            organization_id=user["organization_id"],
        )
        if uploaded_file is None:
            raise HTTPException(status_code=404, detail="Frame image not found")
        width = int(scene_image.get("width") or 0)
        height = int(scene_image.get("height") or 0)
        if width <= 0 or height <= 0:
            source_image_path = app_settings.storage_root / uploaded_file["relative_path"]
            if not source_image_path.exists():
                raise HTTPException(status_code=404, detail="Frame image file not found")
            with Image.open(source_image_path) as source_image:
                width, height = source_image.size
        blank_mask = Image.new("L", (width, height), 0)
        output_root = (
            app_settings.storage_root
            / _safe_path_segment(user["organization_id"])
            / "derived"
            / "scenes"
            / str(scene_id)
            / "images"
            / str(payload.uploaded_file_id)
        )
        safe_object_stem = _safe_path_segment(str(scene_object["name"]))
        raw_mask_path = output_root / f"{safe_object_stem}_00.png"
        soft_mask_path = output_root / f"{safe_object_stem}_00_soft.png"
        raw_mask_path.parent.mkdir(parents=True, exist_ok=True)
        blank_mask.save(raw_mask_path, format="PNG")
        blank_mask.save(soft_mask_path, format="PNG")
        created_mask = create_object_mask(
            database_path,
            scene_object_id=object_id,
            uploaded_file_id=int(payload.uploaded_file_id),
            relative_path=_relative_storage_path(app_settings.storage_root, raw_mask_path),
            soft_relative_path=_relative_storage_path(app_settings.storage_root, soft_mask_path),
            prompt_text=str(scene_object.get("prompt") or ""),
            bbox_json=None,
            score=None,
        )
        _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)
        return {
            **created_mask,
            "original_filename": uploaded_file.get("original_filename"),
        }

    @app.post("/api/scenes/{scene_id}/objects/{object_id}/generate-inventory-image")
    async def post_generate_inventory_image_for_object(
        scene_id: int,
        object_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if inventory_image_provider_error:
            raise HTTPException(status_code=503, detail=inventory_image_provider_error)
        if scene_inventory_image_provider is None:
            raise HTTPException(
                status_code=503,
                detail="Inventory image generator is unavailable. Please contact the administrator to turn Comfy on.",
            )
        scene = get_scene_with_images(database_path, scene_id)
        if scene is None or scene["organization_id"] != user["organization_id"]:
            raise HTTPException(status_code=404, detail="Scene not found")
        scene_object = next((item for item in scene.get("objects", []) if int(item["id"]) == object_id), None)
        if scene_object is None:
            raise HTTPException(status_code=404, detail="Object not found")
        result = await _generate_inventory_image_for_scene_object(
            database_path=database_path,
            storage_root=app_settings.storage_root,
            inventory_input_root=app_settings.inventory_image_input_root,
            organization_id=user["organization_id"],
            scene_id=scene_id,
            scene_object=scene_object,
            inventory_image_provider=scene_inventory_image_provider,
        )
        _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)
        return result

    @app.post("/api/scenes/{scene_id}/objects/{object_id}/generate-removal-frame")
    async def post_generate_removal_frame_for_object(
        scene_id: int,
        object_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if scene_removal_provider_error:
            raise HTTPException(status_code=503, detail=scene_removal_provider_error)
        if scene_removal_image_provider is None:
            raise HTTPException(
                status_code=503,
                detail="Inventory image generator is unavailable. Please contact the administrator to turn Comfy on.",
            )
        scene = get_scene_with_images(database_path, scene_id)
        if scene is None or scene["organization_id"] != user["organization_id"]:
            raise HTTPException(status_code=404, detail="Scene not found")
        scene_object = next((item for item in scene.get("objects", []) if int(item["id"]) == object_id), None)
        if scene_object is None:
            raise HTTPException(status_code=404, detail="Object not found")
        upload_batch = create_upload_batch(
            database_path,
            organization_id=user["organization_id"],
            created_by_user_id=user["id"],
        )
        _batch_storage_root(app_settings.storage_root, user["organization_id"], upload_batch["id"]).mkdir(
            parents=True,
            exist_ok=True,
        )
        result = await _generate_scene_removal_for_object(
            database_path=database_path,
            storage_root=app_settings.storage_root,
            inventory_input_root=app_settings.inventory_image_input_root,
            organization_id=user["organization_id"],
            scene=scene,
            scene_object=scene_object,
            upload_batch=upload_batch,
            uploaded_by_user_id=int(user["id"]),
            removal_provider=scene_removal_image_provider,
        )
        if result.get("status") == "failed":
            set_scene_object_pickup_frame_failed(
                database_path,
                scene_id=scene_id,
                object_id=object_id,
                failed=True,
            )
        updated_scene = get_scene_with_images(database_path, scene_id)
        if updated_scene is None:
            raise RuntimeError("Updated scene could not be loaded")
        _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)
        return {
            **result,
            "scene": _annotate_scene_inventory_image_statuses(app_settings.storage_root, updated_scene),
        }

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
        _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)
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
        created_animation = create_object_animation(
            database_path,
            scene_object_id=object_id,
            name=animation.name,
            segments=_animation_segments_payload(animation.segments),
        )
        _invalidate_scene_preview_manifest_cache(
            app_settings.storage_root,
            user["organization_id"],
            int(scene_object["scene_id"]),
        )
        return created_animation

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
        _invalidate_scene_preview_manifest_cache(
            app_settings.storage_root,
            user["organization_id"],
            int(scene_object["scene_id"]),
        )
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
        _invalidate_scene_preview_manifest_cache(
            app_settings.storage_root,
            user["organization_id"],
            int(scene_object["scene_id"]),
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
        _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)

        return {
            "scene": _annotate_scene_inventory_image_statuses(app_settings.storage_root, updated_scene),
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

    @app.get("/api/script-lines/{line_id}/jobs/active", response_model=ProcessingJob | None)
    def get_active_script_line_job(
        line_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any] | None:
        line = get_script_line_detail(database_path, user["organization_id"], line_id)
        if line is None:
            raise HTTPException(status_code=404, detail="Script line not found")
        return get_active_processing_job_for_script_line(
            database_path,
            organization_id=user["organization_id"],
            script_line_id=line_id,
            job_type="script_line_localization",
        )

    @app.post("/api/scenes/{scene_id}/generate-inventory-images")
    async def post_generate_inventory_images(
        scene_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if inventory_image_provider_error:
            raise HTTPException(status_code=503, detail=inventory_image_provider_error)
        if scene_inventory_image_provider is None:
            raise HTTPException(
                status_code=503,
                detail="Inventory image generator is unavailable. Please contact the administrator to turn Comfy on.",
            )
        scene = get_scene_with_images(database_path, scene_id)
        if scene is None or scene["organization_id"] != user["organization_id"]:
            raise HTTPException(status_code=404, detail="Scene not found")

        generated_count = 0
        skipped_count = 0
        updated_object_ids: list[int] = []
        failed_object_ids: list[int] = []
        failed_objects: list[dict[str, Any]] = []
        for scene_object in scene.get("objects", []):
            if not scene_object.get("keyboard_target_enabled"):
                continue
            try:
                result = await _generate_inventory_image_for_scene_object(
                    database_path=database_path,
                    storage_root=app_settings.storage_root,
                    inventory_input_root=app_settings.inventory_image_input_root,
                    organization_id=user["organization_id"],
                    scene_id=scene_id,
                    scene_object=scene_object,
                    inventory_image_provider=scene_inventory_image_provider,
                )
            except HTTPException as exc:
                failed_object_ids.append(int(scene_object["id"]))
                failed_objects.append(
                    {
                        "id": int(scene_object["id"]),
                        "name": str(scene_object["name"]),
                        "error": str(exc.detail or "Inventory art generation failed."),
                    }
                )
                continue
            except Exception:  # noqa: BLE001
                set_scene_object_inventory_image_failed(
                    database_path,
                    scene_id=scene_id,
                    object_id=int(scene_object["id"]),
                    failed=True,
                )
                failed_object_ids.append(int(scene_object["id"]))
                failed_objects.append(
                    {
                        "id": int(scene_object["id"]),
                        "name": str(scene_object["name"]),
                        "error": "Inventory art generation failed.",
                    }
                )
                continue
            if result["status"] == "skipped":
                skipped_count += 1
                continue
            if result["status"] == "failed":
                failed_object_ids.append(int(scene_object["id"]))
                failed_objects.append(
                    {
                        "id": int(scene_object["id"]),
                        "name": str(scene_object["name"]),
                        "error": "Generated inventory art was invalid.",
                    }
                )
                continue
            updated_scene_object = result.get("scene_object")
            if updated_scene_object is not None:
                generated_count += 1
                updated_object_ids.append(int(updated_scene_object["id"]))

        updated_scene = get_scene_with_images(database_path, scene_id)
        if updated_scene is None:
            raise RuntimeError("Updated scene could not be loaded")
        return {
            "scene": _annotate_scene_inventory_image_statuses(app_settings.storage_root, updated_scene),
            "generated_count": generated_count,
            "skipped_count": skipped_count,
            "updated_object_ids": updated_object_ids,
            "failed_object_ids": failed_object_ids,
            "failed_objects": failed_objects,
        }

    @app.post("/api/scenes/{scene_id}/generate-removal-frames")
    async def post_generate_scene_removal_frames(
        scene_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if scene_removal_provider_error:
            raise HTTPException(status_code=503, detail=scene_removal_provider_error)
        if scene_removal_image_provider is None:
            raise HTTPException(
                status_code=503,
                detail="Inventory image generator is unavailable. Please contact the administrator to turn Comfy on.",
            )
        scene = get_scene_with_images(database_path, scene_id)
        if scene is None or scene["organization_id"] != user["organization_id"]:
            raise HTTPException(status_code=404, detail="Scene not found")

        keyboard_target_objects = [
            scene_object
            for scene_object in scene.get("objects", [])
            if scene_object.get("keyboard_target_enabled")
        ]
        if not keyboard_target_objects:
            raise HTTPException(status_code=400, detail="Scene does not have any keyboard-target objects")

        upload_batch = create_upload_batch(
            database_path,
            organization_id=user["organization_id"],
            created_by_user_id=user["id"],
        )
        _batch_storage_root(app_settings.storage_root, user["organization_id"], upload_batch["id"]).mkdir(
            parents=True,
            exist_ok=True,
        )

        generated_count = 0
        skipped_count = 0
        failed_object_ids: list[int] = []
        failed_objects: list[dict[str, Any]] = []
        generated_uploaded_file_ids: list[int] = []
        for scene_object in keyboard_target_objects:
            try:
                result = await _generate_scene_removal_for_object(
                    database_path=database_path,
                    storage_root=app_settings.storage_root,
                    inventory_input_root=app_settings.inventory_image_input_root,
                    organization_id=user["organization_id"],
                    scene=scene,
                    scene_object=scene_object,
                    upload_batch=upload_batch,
                    uploaded_by_user_id=int(user["id"]),
                    removal_provider=scene_removal_image_provider,
                )
            except HTTPException as exc:
                failed_object_ids.append(int(scene_object["id"]))
                failed_objects.append(
                    {
                        "id": int(scene_object["id"]),
                        "name": str(scene_object["name"]),
                        "error": str(exc.detail or "Pickup frame generation failed."),
                    }
                )
                continue
            except Exception:  # noqa: BLE001
                set_scene_object_pickup_frame_failed(
                    database_path,
                    scene_id=scene_id,
                    object_id=int(scene_object["id"]),
                    failed=True,
                )
                failed_object_ids.append(int(scene_object["id"]))
                failed_objects.append(
                    {
                        "id": int(scene_object["id"]),
                        "name": str(scene_object["name"]),
                        "error": "Pickup frame generation failed.",
                    }
                )
                continue
            if result["status"] == "generated":
                generated_count += 1
                generated_uploaded_file_ids.append(int(result["uploaded_file_id"]))
            elif result["status"] == "failed":
                failed_object_ids.append(int(scene_object["id"]))
                failed_objects.append(
                    {
                        "id": int(scene_object["id"]),
                        "name": str(scene_object["name"]),
                        "error": "Generated pickup frame was invalid.",
                    }
                )
            else:
                skipped_count += 1

        updated_scene = get_scene_with_images(database_path, scene_id)
        if updated_scene is None:
            raise RuntimeError("Updated scene could not be loaded")
        _invalidate_scene_preview_manifest_cache(app_settings.storage_root, user["organization_id"], scene_id)
        return {
            "scene": _annotate_scene_inventory_image_statuses(app_settings.storage_root, updated_scene),
            "generated_count": generated_count,
            "skipped_count": skipped_count,
            "failed_object_ids": failed_object_ids,
            "failed_objects": failed_objects,
            "generated_uploaded_file_ids": generated_uploaded_file_ids,
        }

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

    @app.get("/api/uploads/files/{uploaded_file_id}/thumbnail")
    def get_uploaded_file_thumbnail(
        uploaded_file_id: int,
        size: int = 320,
        user: dict[str, Any] = Depends(current_user),
    ) -> Response:
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

        try:
            with Image.open(file_path) as image:
                rendered = image.convert("RGB")
                rendered.thumbnail((max(32, min(size, 1024)), max(32, min(size, 1024))), Image.Resampling.LANCZOS)
                buffer = BytesIO()
                rendered.save(buffer, format="JPEG", quality=82, optimize=True)
        except OSError as exc:
            raise HTTPException(status_code=400, detail="Uploaded file is not a supported image") from exc

        return Response(content=buffer.getvalue(), media_type="image/jpeg")

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
        _invalidate_scene_preview_manifest_cache(
            app_settings.storage_root,
            user["organization_id"],
            int(object_mask["scene_id"]),
        )
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
        if request.operation == "combine":
            target_masks = list_object_masks_for_object(
                database_path,
                scene_object_id=object_mask["scene_object_id"],
                organization_id=user["organization_id"],
            )
            combined_image = _combine_object_mask_images(
                app_settings.storage_root,
                target_masks,
            )
            updated_masks = []
            for target_mask in target_masks:
                _write_object_mask_image(app_settings.storage_root, target_mask, combined_image)
                updated_mask = touch_object_mask(database_path, target_mask["id"])
                if updated_mask is not None:
                    updated_masks.append(updated_mask)
            _invalidate_scene_preview_manifest_cache(
                app_settings.storage_root,
                user["organization_id"],
                int(object_mask["scene_id"]),
            )
            return updated_masks
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
        _invalidate_scene_preview_manifest_cache(
            app_settings.storage_root,
            user["organization_id"],
            int(object_mask["scene_id"]),
        )
        return updated_masks

    @app.get("/api/scene-objects/{object_id}/thumbnail")
    def get_scene_object_thumbnail(
        object_id: int,
        size: int = 256,
        user: dict[str, Any] = Depends(current_user),
    ) -> FileResponse:
        scene_object = get_scene_object_for_organization(
            database_path,
            object_id=object_id,
            organization_id=user["organization_id"],
        )
        if scene_object is None:
            raise HTTPException(status_code=404, detail="Object not found")
        inventory_image_relative_path = scene_object.get("inventory_image_relative_path")
        if inventory_image_relative_path:
            inventory_image_path = app_settings.storage_root / inventory_image_relative_path
            if _is_valid_inventory_image_file(inventory_image_path):
                normalized_size = max(32, min(int(size or 256), 1024))
                inventory_thumbnail_path = (
                    app_settings.storage_root
                    / _safe_path_segment(user["organization_id"])
                    / "derived"
                    / "scenes"
                    / str(scene_object["scene_id"])
                    / "objects"
                    / str(object_id)
                    / "inventory-thumbnails"
                    / f"{normalized_size}.png"
                )
                if _derived_file_is_stale(inventory_thumbnail_path, [inventory_image_path]):
                    inventory_thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
                    with Image.open(inventory_image_path) as image:
                        rendered = image.convert("RGBA")
                        rendered.thumbnail((normalized_size, normalized_size), Image.Resampling.LANCZOS)
                        rendered.save(inventory_thumbnail_path, format="PNG")
                return FileResponse(
                    inventory_thumbnail_path if inventory_thumbnail_path.exists() else inventory_image_path,
                    media_type="image/png",
                    headers={"Cache-Control": "no-store, max-age=0"},
                )
        object_masks = list_object_masks_for_object(
            database_path,
            scene_object_id=object_id,
            organization_id=user["organization_id"],
        )
        if not object_masks:
            raise HTTPException(status_code=404, detail="Object does not have masks")

        preferred_masks = _preferred_object_masks(scene_object, object_masks)
        for object_mask in preferred_masks:
            original_path = app_settings.storage_root / object_mask["original_relative_path"]
            mask_relative_path = object_mask["soft_relative_path"] or object_mask["relative_path"]
            mask_path = app_settings.storage_root / mask_relative_path
            if not original_path.exists() or not mask_path.exists():
                continue
            normalized_size = max(32, min(int(size or 256), 1024))
            thumbnail_path = (
                app_settings.storage_root
                / _safe_path_segment(user["organization_id"])
                / "derived"
                / "scenes"
                / str(object_mask["scene_id"])
                / "objects"
                / str(object_id)
                / "thumbnails"
                / f"{object_mask['id']}-{normalized_size}.png"
            )
            if _derived_file_is_stale(thumbnail_path, [original_path, mask_path]):
                rendered = render_masked_object_crop(
                    original_path=original_path,
                    mask_path=mask_path,
                    output_path=thumbnail_path,
                    max_size=normalized_size,
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

    @app.get("/api/audio-assets", response_model=list[AudioAsset])
    def get_audio_assets(user: dict[str, Any] = Depends(current_user)) -> list[dict]:
        return list_audio_assets(database_path, user["organization_id"])

    @app.post("/api/audio-assets", response_model=AudioAsset, status_code=201)
    async def post_audio_asset(
        file: UploadFile = File(...),
        name: str = Form(default=""),
        kind: str = Form(default="sfx"),
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        normalized_kind = str(kind).strip().lower()
        if normalized_kind not in {"bgm", "sfx"}:
            raise HTTPException(status_code=400, detail="Audio kind must be bgm or sfx")
        original_filename = _safe_filename(file.filename or "audio.bin")
        audio_name = str(name).strip() or Path(original_filename).stem
        audio_root = (
            app_settings.storage_root
            / _safe_path_segment(user["organization_id"])
            / "audio"
            / normalized_kind
        )
        audio_root.mkdir(parents=True, exist_ok=True)
        stored_filename = f"{uuid4().hex}-{original_filename}"
        stored_path = audio_root / stored_filename
        file_size = await _write_upload(file, stored_path)
        return create_audio_asset(
            database_path,
            organization_id=user["organization_id"],
            name=audio_name,
            kind=normalized_kind,
            relative_path=str(
                Path(_safe_path_segment(user["organization_id"])) / "audio" / normalized_kind / stored_filename
            ),
            original_filename=original_filename,
            content_type=file.content_type,
            file_size=file_size,
        )

    @app.patch("/api/audio-assets/{audio_asset_id}", response_model=AudioAsset)
    def patch_audio_asset(
        audio_asset_id: int,
        asset: AudioAssetBase,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        updated = update_audio_asset(
            database_path,
            organization_id=user["organization_id"],
            audio_asset_id=audio_asset_id,
            name=asset.name,
            kind=asset.kind,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Audio asset not found")
        return updated

    @app.delete("/api/audio-assets/{audio_asset_id}", status_code=204)
    def delete_audio_asset_endpoint(
        audio_asset_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> Response:
        deleted = delete_audio_asset(
            database_path,
            organization_id=user["organization_id"],
            audio_asset_id=audio_asset_id,
        )
        if deleted is None:
            raise HTTPException(status_code=404, detail="Audio asset not found")
        file_path = app_settings.storage_root / deleted["relative_path"]
        if file_path.exists():
            file_path.unlink()
        return Response(status_code=204)

    @app.get("/api/audio-assets/{audio_asset_id}/content")
    def get_audio_asset_content(
        audio_asset_id: int,
        user: dict[str, Any] = Depends(current_user),
    ) -> FileResponse:
        asset = get_audio_asset_by_id(
            database_path,
            organization_id=user["organization_id"],
            audio_asset_id=audio_asset_id,
        )
        if asset is None:
            raise HTTPException(status_code=404, detail="Audio asset not found")
        file_path = app_settings.storage_root / asset["relative_path"]
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Audio asset content not found")
        return FileResponse(
            file_path,
            media_type=asset["content_type"] or "audio/ogg",
            filename=asset["original_filename"],
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
    script_localization_provider: ScriptLocalizationProvider | None,
    script_localization_provider_error: str | None,
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
            elif job["job_type"] == "script_line_localization":
                if script_localization_provider_error:
                    raise RuntimeError(script_localization_provider_error)
                if script_localization_provider is None:
                    raise RuntimeError("Script localization provider is not configured")
                result = await _run_script_line_localization_job(
                    database_path=database_path,
                    settings=settings,
                    localization_provider=script_localization_provider,
                    job=job,
                )
                complete_processing_job(
                    database_path,
                    job_id=job["id"],
                    result=result,
                    message="Translation and TTS generation complete",
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

    work_items = []
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
        work_items.append(
            {
                "scene_image": scene_image,
                "image_path": image_path,
                "objects_to_extract": objects_to_extract,
            }
        )

    if hasattr(segmentation_provider, "open_worker_session") and work_items:
        worker_session = await segmentation_provider.open_worker_session()  # type: ignore[attr-defined]
        try:
            for item in work_items:
                scene_image = item["scene_image"]
                objects_to_extract = item["objects_to_extract"]
                image_path = item["image_path"]
                update_processing_job_progress(
                    database_path,
                    job_id=job["id"],
                    progress_current=progress_current,
                    progress_total=progress_total,
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
                prompt_results = await worker_session.extract_masks(
                    image_path=image_path,
                    prompts=[scene_object["prompt"] for scene_object in objects_to_extract],
                    output_dir=output_dir,
                    max_edge=settings.segmentation_max_edge,
                    threshold=settings.segmentation_threshold,
                    dilate=settings.segmentation_dilate_pixels,
                    blur=settings.segmentation_blur_radius,
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
        finally:
            await worker_session.close()
    else:
        for item in work_items:
            scene_image = item["scene_image"]
            objects_to_extract = item["objects_to_extract"]
            image_path = item["image_path"]
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

    _invalidate_scene_preview_manifest_cache(settings.storage_root, job["organization_id"], scene_id)

    return {
        "scene_id": scene_id,
        "processed_image_count": processed_image_count,
        "prompt_count": len(scene_objects),
        "created_candidate_count": created_candidate_count,
        "skipped_existing_count": skipped_existing_count,
        "generated_animation_count": 0,
    }


async def _run_script_line_localization_job(
    database_path: Path,
    settings: Settings,
    localization_provider: ScriptLocalizationProvider,
    job: dict[str, Any],
) -> dict[str, Any]:
    line_id = int(job.get("script_line_id") or 0)
    if line_id <= 0:
        raise RuntimeError("Script localization job is missing script_line_id")
    line = get_script_line_detail(database_path, job["organization_id"], line_id)
    if line is None:
        raise RuntimeError(f"Script line #{line_id} no longer exists")

    async def report_progress(current: int, total: int, message: str) -> None:
        update_processing_job_progress(
            database_path,
            job_id=job["id"],
            progress_current=current,
            progress_total=total,
            message=message,
        )

    existing_translations = {
        str(translation.get("language") or "").strip().lower(): str(translation.get("text") or "")
        for translation in line.get("translations", [])
        if str(translation.get("language") or "").strip()
    }
    result = await localization_provider.localize_line(
        line_id=line_id,
        source_text=str(line.get("source_text") or ""),
        path_parts=list(line.get("path_parts") or []),
        existing_translations=existing_translations,
        progress_callback=report_progress,
    )

    created_translations = 0
    created_audio_candidates = 0
    audio_errors = 0

    try:
        for translation in result.get("translations", []):
            language = str(translation.get("language") or "").strip().lower()
            text = str(translation.get("text") or "")
            if not language or not text.strip():
                continue
            created = upsert_script_translation(
                database_path,
                organization_id=job["organization_id"],
                line_id=line_id,
                language=language,
                text=text,
                source=str(translation.get("source") or "auto"),
                meta=translation.get("meta") if isinstance(translation.get("meta"), dict) else {},
                review_status="approved" if language == "en" else "needs_review",
            )
            if created is not None:
                created_translations += 1

        for audio_output in result.get("audio_outputs", []):
            language = str(audio_output.get("language") or "").strip().lower()
            if not language:
                continue
            candidate = await _store_generated_tts_candidate(
                db_path=database_path,
                settings=settings,
                organization_id=job["organization_id"],
                line_id=line_id,
                language=language,
                wav_path=Path(audio_output["wav_path"]),
            )
            if candidate is not None:
                created_audio_candidates += 1

        for error in result.get("errors", []):
            language = str(error.get("language") or "").strip().lower()
            if not language:
                continue
            upsert_script_audio_candidate(
                database_path,
                organization_id=job["organization_id"],
                line_id=line_id,
                language=language,
                source_type="tts",
                manifest_status="error",
                relative_path="",
                original_path=f"generated_tts/line-{line_id}/{language}/{line_id:04d}_{language}.ogg",
                rank=0,
                error=str(error.get("error") or "TTS generation failed"),
                source_file="",
                review_status="missing",
            )
            audio_errors += 1
    finally:
        working_root = result.get("working_root")
        if isinstance(working_root, Path):
            shutil.rmtree(working_root, ignore_errors=True)
        elif working_root:
            shutil.rmtree(Path(working_root), ignore_errors=True)

    return {
        "line_id": line_id,
        "created_translations": created_translations,
        "created_audio_candidates": created_audio_candidates,
        "audio_errors": audio_errors,
    }


async def _store_generated_tts_candidate(
    *,
    db_path: Path,
    settings: Settings,
    organization_id: str,
    line_id: int,
    language: str,
    wav_path: Path,
) -> dict[str, Any] | None:
    generated_root = settings.script_audio_root / "generated_tts" / f"line-{line_id}"
    final_dir = generated_root / language
    final_dir.mkdir(parents=True, exist_ok=True)
    final_path = final_dir / f"{line_id:04d}_{language}.ogg"
    await _process_review_audio_file(wav_path, final_path)
    relative_path = str(final_path.relative_to(settings.script_audio_root))
    return upsert_script_audio_candidate(
        db_path,
        organization_id=organization_id,
        line_id=line_id,
        language=language,
        source_type="tts",
        manifest_status="generated",
        relative_path=relative_path,
        original_path=relative_path,
        rank=0,
        duration_seconds=_probe_audio_duration_seconds(final_path),
        source_file=wav_path.name,
        review_status="candidate",
    )


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
    match_mode = _choice(trigger.get("match_mode"), {"exact", "object_default", "scene_default"}, "exact")
    normalized: dict[str, Any] = {"type": trigger_type, "match_mode": match_mode}
    if trigger_type in {"scene_enter", "scene_exit", "overlay_open", "overlay_close"}:
        normalized["match_mode"] = "exact"
        return normalized
    if trigger_type == "key_press":
        normalized["match_mode"] = "exact"
        normalized["key_code"] = _normalize_key_code(trigger.get("key_code"))
        return normalized
    if trigger_type in {"object_mouseover", "object_mouseout", "object_click", "object_use"}:
        if trigger_type not in {"object_click"} and match_mode != "exact":
            raise HTTPException(status_code=400, detail="Only object click supports default matching")
        if match_mode != "scene_default":
            object_id = _required_int(trigger.get("object_id"), "Trigger object is required")
            if not scene_object_belongs_to_scene(db_path, scene_id, object_id, organization_id):
                raise HTTPException(status_code=400, detail="Trigger object is not in this scene")
            normalized["object_id"] = object_id
        return normalized
    if trigger_type == "object_verb":
        verb_id = _required_int(trigger.get("verb_id"), "Verb is required")
        if get_verb_by_id(db_path, organization_id, verb_id) is None:
            raise HTTPException(status_code=400, detail="Trigger verb does not exist")
        if match_mode != "scene_default":
            object_id = _required_int(trigger.get("object_id"), "Trigger object is required")
            if not scene_object_belongs_to_scene(db_path, scene_id, object_id, organization_id):
                raise HTTPException(status_code=400, detail="Trigger object is not in this scene")
            normalized["object_id"] = object_id
        normalized["verb_id"] = verb_id
        return normalized
    if trigger_type == "inventory_use":
        if match_mode != "scene_default":
            object_id = _required_int(trigger.get("object_id"), "Trigger object is required")
            if not scene_object_belongs_to_scene(db_path, scene_id, object_id, organization_id):
                raise HTTPException(status_code=400, detail="Trigger object is not in this scene")
            normalized["object_id"] = object_id
        if match_mode == "exact":
            inventory_object_id = _required_int(trigger.get("inventory_object_id"), "Inventory object is required")
            if get_scene_object_for_organization(db_path, inventory_object_id, organization_id) is None:
                raise HTTPException(status_code=400, detail="Inventory object does not exist")
            normalized["inventory_object_id"] = inventory_object_id
        return normalized
    if trigger_type == "variable_changed":
        normalized["match_mode"] = "exact"
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


def _static_action_target_object_allowed(
    db_path: Path,
    scene_id: int,
    object_id: int,
    organization_id: str,
) -> bool:
    if scene_object_belongs_to_scene(db_path, scene_id, object_id, organization_id):
        return True
    scene_object = get_scene_object_for_organization(db_path, object_id, organization_id)
    if scene_object is None:
        return False
    owner_scene = get_scene_with_images(db_path, int(scene_object["scene_id"]))
    return bool(owner_scene) and str(owner_scene.get("presentation_mode") or "") == "character"


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
        target_object_mode = _choice(
            step.get("target_object_mode"),
            {"static", "trigger_object", "trigger_inventory_object"},
            "static",
        )
        normalized.update(
            {
                "target_object_mode": target_object_mode,
                "mode": _choice(step.get("mode"), {"queued", "immediate"}, "queued"),
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "wait"),
            }
        )
        if target_object_mode == "static":
            object_id = _required_int(step.get("target_object_id"), "Animation target object is required")
            animation_id = _required_int(step.get("animation_id"), "Animation is required")
            if not scene_object_belongs_to_scene(db_path, scene_id, object_id, organization_id):
                raise HTTPException(status_code=400, detail="Animation target object is not in this scene")
            if not object_animation_belongs_to_object(db_path, animation_id, object_id, organization_id):
                raise HTTPException(status_code=400, detail="Animation does not belong to the target object")
            normalized["target_object_id"] = object_id
            normalized["animation_id"] = animation_id
        else:
            animation_name = str(step.get("animation_name") or "").strip()
            if not animation_name:
                raise HTTPException(status_code=400, detail="Animation name is required for triggered object playback")
            normalized["animation_name"] = animation_name
        return normalized
    if step_type == "set_object_property":
        target_object_mode = _choice(
            step.get("target_object_mode"),
            {"static", "trigger_object", "trigger_inventory_object"},
            "static",
        )
        property_name = _choice(step.get("property"), {"visible", "enabled", "label"}, "")
        value = step.get("value")
        if property_name in {"visible", "enabled"} and not isinstance(value, bool):
            raise HTTPException(status_code=400, detail=f"{property_name} requires a boolean value")
        if property_name == "label" and not isinstance(value, str):
            raise HTTPException(status_code=400, detail="label requires text")
        normalized.update(
            {
                "target_object_mode": target_object_mode,
                "property": property_name,
                "value": value,
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "continue"),
            }
        )
        if target_object_mode == "static":
            object_id = _required_int(step.get("target_object_id"), "Property target object is required")
            if not _static_action_target_object_allowed(db_path, scene_id, object_id, organization_id):
                raise HTTPException(status_code=400, detail="Property target object is not available to this scene")
            normalized["target_object_id"] = object_id
        return normalized
    if step_type == "go_to_frame":
        target_scope = _choice(step.get("target_scope"), {"object", "background", "pickup_background"}, "object")
        target_object_mode = _choice(
            step.get("target_object_mode"),
            {"static", "trigger_object", "trigger_inventory_object"},
            "static",
        )
        scene = get_scene_with_images(db_path, scene_id)
        image_count = len(scene.get("images", [])) if scene else 0
        normalized.update(
            {
                "target_scope": target_scope,
                "target_object_mode": target_object_mode,
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "continue"),
            }
        )
        if target_scope == "object":
            frame_index = _required_int(step.get("frame_index"), "Frame index is required")
            if frame_index < 0 or frame_index >= image_count:
                raise HTTPException(status_code=400, detail="Frame index is outside this scene's image range")
            normalized["frame_index"] = frame_index
            if target_object_mode == "static":
                object_id = _required_int(step.get("target_object_id"), "Frame target object is required")
                if not scene_object_belongs_to_scene(db_path, scene_id, object_id, organization_id):
                    raise HTTPException(status_code=400, detail="Frame target object is not in this scene")
                normalized["target_object_id"] = object_id
        elif target_scope == "background":
            frame_index = _required_int(step.get("frame_index"), "Frame index is required")
            if frame_index < 0 or frame_index >= image_count:
                raise HTTPException(status_code=400, detail="Frame index is outside this scene's image range")
            normalized["frame_index"] = frame_index
        else:
            if target_object_mode == "static":
                object_id = _required_int(step.get("target_object_id"), "Pickup frame target object is required")
                if not scene_object_belongs_to_scene(db_path, scene_id, object_id, organization_id):
                    raise HTTPException(status_code=400, detail="Pickup frame target object is not in this scene")
                normalized["target_object_id"] = object_id
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
        speaker_character_id = None
        if step.get("speaker_character_id") is not None:
            speaker_character_id = _required_int(step.get("speaker_character_id"), "Speaker character is invalid")
            _require_character(db_path, organization_id, speaker_character_id)
        normalized.update(
            {
                "script_line_ids": sorted(set(line_ids)),
                "selection": "random" if len(set(line_ids)) > 1 else "single",
                "speaker_character_id": speaker_character_id,
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "wait"),
            }
        )
        return normalized
    if step_type == "tween_to":
        character_id = _required_int(step.get("character_id"), "Character is required")
        _require_character(db_path, organization_id, character_id)
        property_name = _choice(step.get("property"), {"x", "y", "scale", "opacity"}, "")
        value = step.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise HTTPException(status_code=400, detail="Tween value must be a number")
        normalized.update(
            {
                "character_id": character_id,
                "property": property_name,
                "value": float(value),
                "duration_seconds": _positive_float(step.get("duration_seconds"), "Tween duration is required"),
                "curve": _choice(
                    step.get("curve"),
                    {
                        "linear",
                        "ease_in",
                        "ease_out",
                        "ease_in_out",
                        "back_in",
                        "back_out",
                        "back_in_out",
                        "bounce_out",
                        "elastic_out",
                    },
                    "ease_in_out",
                ),
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
    if step_type == "increment_variable":
        variable = _require_variable(
            db_path,
            organization_id,
            _required_int(step.get("variable_id"), "Variable is required"),
        )
        if variable["value_type"] != "number":
            raise HTTPException(status_code=400, detail="Only number variables can be incremented")
        normalized.update(
            {
                "variable_id": variable["id"],
                "amount": _numeric_delta(step.get("amount"), "Increment amount is required"),
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "continue"),
            }
        )
        return normalized
    if step_type == "toggle_variable":
        variable = _require_variable(
            db_path,
            organization_id,
            _required_int(step.get("variable_id"), "Variable is required"),
        )
        if variable["value_type"] != "bool":
            raise HTTPException(status_code=400, detail="Only bool variables can be toggled")
        normalized.update(
            {
                "variable_id": variable["id"],
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
    if step_type in {"fade_out", "fade_in"}:
        color = step.get("color")
        if not isinstance(color, str) or not color.strip():
            raise HTTPException(status_code=400, detail="Fade color is required")
        normalized.update(
            {
                "duration_seconds": _positive_float(step.get("duration_seconds"), "Fade duration is required"),
                "color": color.strip(),
                "affect_audio": bool(step.get("affect_audio")),
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "wait"),
            }
        )
        return normalized
    if step_type == "crossfade_bgm":
        audio_asset = _require_audio_asset(
            db_path,
            organization_id,
            _required_int(step.get("audio_asset_id"), "Background music is required"),
        )
        if audio_asset["kind"] != "bgm":
            raise HTTPException(status_code=400, detail="Only bgm assets can be used for crossfade_bgm")
        normalized.update(
            {
                "audio_asset_id": audio_asset["id"],
                "duration_seconds": _positive_float(step.get("duration_seconds"), "Crossfade duration is required"),
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "wait"),
            }
        )
        return normalized
    if step_type == "play_sfx":
        audio_asset = _require_audio_asset(
            db_path,
            organization_id,
            _required_int(step.get("audio_asset_id"), "Sound effect is required"),
        )
        if audio_asset["kind"] != "sfx":
            raise HTTPException(status_code=400, detail="Only sfx assets can be used for play_sfx")
        normalized.update(
            {
                "audio_asset_id": audio_asset["id"],
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "continue"),
            }
        )
        return normalized
    if step_type in {"add_inventory_item", "remove_inventory_item"}:
        scene_object_mode = _choice(
            step.get("scene_object_mode"),
            {"static", "trigger_object", "trigger_inventory_object"},
            "static",
        )
        normalized.update(
            {
                "scene_object_mode": scene_object_mode,
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "continue"),
            }
        )
        if scene_object_mode == "static":
            scene_object_id = _required_int(step.get("scene_object_id"), "Inventory object is required")
            if get_scene_object_for_organization(db_path, scene_object_id, organization_id) is None:
                raise HTTPException(status_code=400, detail="Inventory object does not exist")
            normalized["scene_object_id"] = scene_object_id
        return normalized
    if step_type == "clear_held_inventory_item":
        normalized.update({"wait": _choice(step.get("wait"), {"wait", "continue"}, "continue")})
        return normalized
    if step_type == "change_scene":
        target_scene_id = _required_int(step.get("scene_id"), "Target scene is required")
        _require_base_scene(db_path, target_scene_id, organization_id)
        normalized.update(
            {
                "scene_id": target_scene_id,
                "wait": "wait",
            }
        )
        return normalized
    if step_type == "open_overlay_scene":
        target_scene_id = _required_int(step.get("scene_id"), "Target overlay scene is required")
        _require_overlay_scene(db_path, target_scene_id, organization_id)
        normalized.update(
            {
                "scene_id": target_scene_id,
                "wait": "wait",
            }
        )
        return normalized
    if step_type == "close_overlay_scene":
        normalized.update({"wait": "wait"})
        return normalized
    if step_type == "change_overlay_scene":
        target_scene_id = _required_int(step.get("scene_id"), "Target overlay scene is required")
        _require_overlay_scene(db_path, target_scene_id, organization_id)
        normalized.update(
            {
                "scene_id": target_scene_id,
                "wait": "wait",
            }
        )
        return normalized
    if step_type == "show_character":
        character_id = _required_int(step.get("character_id"), "Character is required")
        _require_character(db_path, organization_id, character_id)
        pose_variant_key = str(step.get("pose_variant_key") or "").strip() or None
        animation_id = None
        if step.get("animation_id") is not None:
            animation_id = _required_int(step.get("animation_id"), "Character animation is invalid")
            _require_character_animation(db_path, organization_id, animation_id, character_id)
        normalized.update(
            {
                "character_id": character_id,
                "x": float(step.get("x") if step.get("x") is not None else 960),
                "y": float(step.get("y") if step.get("y") is not None else 540),
                "scale": float(step.get("scale") if step.get("scale") is not None else 1.0),
                "opacity": min(1.0, max(0.0, float(step.get("opacity") if step.get("opacity") is not None else 1.0))),
                "pose_variant_key": pose_variant_key,
                "animation_id": animation_id,
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "continue"),
            }
        )
        return normalized
    if step_type == "hide_character":
        character_id = _required_int(step.get("character_id"), "Character is required")
        _require_character(db_path, organization_id, character_id)
        normalized.update(
            {
                "character_id": character_id,
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "continue"),
            }
        )
        return normalized
    if step_type == "set_character_transform":
        character_id = _required_int(step.get("character_id"), "Character is required")
        _require_character(db_path, organization_id, character_id)
        normalized.update(
            {
                "character_id": character_id,
                "x": float(step.get("x") if step.get("x") is not None else 960),
                "y": float(step.get("y") if step.get("y") is not None else 540),
                "scale": float(step.get("scale") if step.get("scale") is not None else 1.0),
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "continue"),
            }
        )
        return normalized
    if step_type == "play_character_animation":
        character_id = _required_int(step.get("character_id"), "Character is required")
        animation_id = _required_int(step.get("animation_id"), "Character animation is required")
        _require_character(db_path, organization_id, character_id)
        _require_character_animation(db_path, organization_id, animation_id, character_id)
        normalized.update(
            {
                "character_id": character_id,
                "animation_id": animation_id,
                "wait": _choice(step.get("wait"), {"wait", "continue"}, "wait"),
            }
        )
        return normalized
    raise HTTPException(status_code=400, detail="Unsupported action type")


def _require_variable(db_path: Path, organization_id: str, variable_id: int) -> dict[str, Any]:
    variable = get_game_variable_by_id(db_path, organization_id, variable_id)
    if variable is None:
        raise HTTPException(status_code=400, detail="Variable does not exist")
    return variable


def _require_audio_asset(db_path: Path, organization_id: str, audio_asset_id: int) -> dict[str, Any]:
    asset = get_audio_asset_by_id(db_path, organization_id, audio_asset_id)
    if asset is None:
        raise HTTPException(status_code=400, detail="Audio asset does not exist")
    return asset


def _require_character(db_path: Path, organization_id: str, character_id: int) -> dict[str, Any]:
    character = get_character_by_id(db_path, organization_id, character_id)
    if character is None:
        raise HTTPException(status_code=400, detail="Character does not exist")
    return character


def _require_character_animation(
    db_path: Path,
    organization_id: str,
    animation_id: int,
    character_id: int,
) -> dict[str, Any]:
    animation = get_character_animation_by_id(db_path, organization_id, animation_id)
    if animation is None or int(animation["character_id"]) != int(character_id):
        raise HTTPException(status_code=400, detail="Character animation does not belong to the chosen character")
    return animation


def _require_overlay_scene(
    db_path: Path,
    scene_id: int,
    organization_id: str,
) -> dict[str, Any]:
    scene = get_scene_with_images(db_path, scene_id)
    if scene is None or scene["organization_id"] != organization_id:
        raise HTTPException(status_code=400, detail="Target overlay scene does not exist")
    if scene.get("presentation_mode") != "overlay":
        raise HTTPException(status_code=400, detail="Target scene must use overlay presentation mode")
    return scene


def _require_base_scene(
    db_path: Path,
    scene_id: int,
    organization_id: str,
) -> dict[str, Any]:
    scene = get_scene_with_images(db_path, scene_id)
    if scene is None or scene["organization_id"] != organization_id:
        raise HTTPException(status_code=400, detail="Target scene does not exist")
    if scene.get("presentation_mode") == "overlay":
        raise HTTPException(status_code=400, detail="Target scene must use base presentation mode")
    return scene


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


def _numeric_delta(value: Any, detail: str) -> float:
    if value is None or value == "" or isinstance(value, bool):
        raise HTTPException(status_code=400, detail=detail)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=detail) from exc


def _choice(value: Any, allowed: set[str], default: str) -> str:
    selected = str(value or default)
    if selected not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported value: {selected}")
    return selected


ALLOWED_KEY_CODES = {
    "Escape",
    "Enter",
    "Space",
    "Tab",
    "ArrowUp",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
    *{f"Key{letter}" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    *{f"Digit{digit}" for digit in "0123456789"},
}


def _normalize_key_code(value: Any) -> str:
    selected = str(value or "").strip()
    if selected not in ALLOWED_KEY_CODES:
        raise HTTPException(status_code=400, detail=f"Unsupported key code: {selected or 'empty'}")
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


def _is_valid_inventory_image_file(path: Path | None) -> bool:
    if path is None or not path.exists():
        return False
    try:
        if path.stat().st_size <= 0:
            return False
        with Image.open(path) as image:
            image.verify()
    except (OSError, ValueError):
        return False
    return True


def _unlink_if_exists(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def _annotate_scene_inventory_image_statuses(
    storage_root: Path,
    scene: dict[str, Any],
) -> dict[str, Any]:
    scene_copy = {**scene}
    annotated_objects = []
    for scene_object in scene.get("objects", []):
        inventory_relative_path = scene_object.get("inventory_image_relative_path")
        inventory_path = storage_root / inventory_relative_path if inventory_relative_path else None
        annotated_objects.append(
            {
                **scene_object,
                "inventory_image_failed": bool(scene_object.get("inventory_image_failed"))
                or (bool(inventory_relative_path) and not _is_valid_inventory_image_file(inventory_path)),
                "pickup_frame_failed": bool(scene_object.get("pickup_frame_failed")),
            }
        )
    scene_copy["objects"] = annotated_objects
    return scene_copy


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
    if operation == "invert":
        return ImageOps.invert(mask_image)
    if operation == "solid":
        return Image.new("L", mask_image.size, 255)
    if operation == "clear":
        return Image.new("L", mask_image.size, 0)
    raise HTTPException(status_code=400, detail="Unsupported mask operation")


def _combine_object_mask_images(
    storage_root: Path,
    object_masks: list[dict[str, Any]],
) -> Image.Image:
    if not object_masks:
        raise HTTPException(status_code=400, detail="No masks available to combine")
    combined_image = None
    expected_size = None
    for object_mask in object_masks:
        mask_path = storage_root / object_mask["relative_path"]
        if not mask_path.exists():
            raise HTTPException(status_code=404, detail="Mask file not found")
        with Image.open(mask_path) as image:
            mask_image = image.convert("L")
            mask_image.load()
        if expected_size is None:
            expected_size = mask_image.size
            combined_image = mask_image.copy()
            continue
        if mask_image.size != expected_size:
            mask_image = mask_image.resize(expected_size, Image.Resampling.LANCZOS)
        combined_image = ImageChops.lighter(combined_image, mask_image)
    return combined_image


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
    scene_manifest = _get_cached_scene_preview_manifest(
        database_path=database_path,
        storage_root=storage_root,
        organization_id=organization_id,
        scene=scene,
    )
    preview_audio_assets = list_audio_assets(database_path, organization_id)
    preview_variables = list_game_variables(database_path, organization_id)
    preview_verbs = list_verbs(database_path, organization_id)
    scene_summaries = list_scenes(database_path, organization_id)
    available_scenes = [
        {
            "id": item["id"],
            "title": item["title"],
            "presentation_mode": item.get("presentation_mode", "base"),
        }
        for item in scene_summaries
        if item.get("presentation_mode", "base") == "base"
    ]
    overlay_scenes = [
        {
            "id": item["id"],
            "title": item["title"],
            "presentation_mode": item.get("presentation_mode", "base"),
        }
        for item in scene_summaries
        if item.get("presentation_mode", "base") == "overlay"
    ]
    overlay_bindings = list_overlay_scene_bindings(database_path, organization_id)
    global_settings = get_global_settings(database_path, organization_id)
    preview_characters = [
        _character_preview_payload(database_path, storage_root, organization_id, int(character["id"]))
        for character in list_characters(database_path, organization_id)
    ]
    preview_interactions = scene_manifest["interactions"]
    preview_script_lines = [
        line
        for line_id in sorted(_collect_script_line_ids(preview_interactions))
        if (line := get_script_line_detail(database_path, organization_id, line_id)) is not None
    ]
    return {
        **scene_manifest,
        "available_scenes": available_scenes,
        "overlay_scenes": overlay_scenes,
        "overlay_bindings": overlay_bindings,
        "global_settings": global_settings,
        "audio_assets": preview_audio_assets,
        "variables": preview_variables,
        "verbs": preview_verbs,
        "characters": preview_characters,
        "script_lines": preview_script_lines,
    }


def _get_cached_scene_preview_manifest(
    database_path: Path,
    storage_root: Path,
    organization_id: str,
    scene: dict[str, Any],
) -> dict[str, Any]:
    cache_path = _scene_preview_manifest_cache_path(storage_root, organization_id, int(scene["id"]))
    cached = _read_scene_preview_manifest_cache(cache_path)
    if cached is not None:
        return cached
    manifest = _build_scene_preview_manifest(
        database_path=database_path,
        storage_root=storage_root,
        organization_id=organization_id,
        scene=scene,
    )
    _write_scene_preview_manifest_cache(cache_path, manifest)
    return manifest


def _build_scene_preview_manifest(
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
    preview_interactions = [
        interaction
        for interaction in list_scene_interactions(
            database_path,
            scene_id=scene["id"],
            organization_id=organization_id,
        )
        if interaction.get("enabled")
    ]
    preview_objects = []
    go_to_frame_refs, has_contextual_go_to_frame_refs = _collect_go_to_frame_refs(preview_interactions)
    frame_index_by_uploaded_file_id = {
        int(image["uploaded_file_id"]): index for index, image in enumerate(scene_images)
    }
    sorted_scene_objects = sorted(
        scene.get("objects", []),
        key=lambda item: (int(item.get("sort_order", 0) or 0), int(item.get("id", 0) or 0)),
    )
    for scene_object in sorted_scene_objects:
        object_masks = list_object_masks_for_object(
            database_path,
            scene_object_id=scene_object["id"],
            organization_id=organization_id,
        )
        referenced_frame_indices = set(go_to_frame_refs.get(int(scene_object["id"]), set()))
        if has_contextual_go_to_frame_refs:
            referenced_frame_indices.update(
                frame_index
                for frame_index, scene_image in enumerate(scene_images)
                if any(
                    int(object_mask["uploaded_file_id"]) == int(scene_image["uploaded_file_id"])
                    for object_mask in object_masks
                )
            )
        pickup_uploaded_file_id = scene_object.get("pickup_uploaded_file_id")
        if pickup_uploaded_file_id is not None:
            pickup_frame_index = frame_index_by_uploaded_file_id.get(int(pickup_uploaded_file_id))
            if pickup_frame_index is not None:
                referenced_frame_indices.add(pickup_frame_index)
        default_render = None
        for object_mask in _preferred_object_masks(scene_object, object_masks):
            default_render = _preview_render_payload_for_mask(
                storage_root=storage_root,
                organization_id=organization_id,
                object_mask=object_mask,
                frame_index=frame_index_by_uploaded_file_id.get(int(object_mask["uploaded_file_id"])),
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

        frame_renders = []
        seen_frame_indices: set[int] = set()
        for object_mask in object_masks:
            frame_index = frame_index_by_uploaded_file_id.get(int(object_mask["uploaded_file_id"]))
            if frame_index is None or frame_index not in referenced_frame_indices or frame_index in seen_frame_indices:
                continue
            render = _preview_render_payload_for_mask(
                storage_root=storage_root,
                organization_id=organization_id,
                object_mask=object_mask,
                frame_index=frame_index,
            )
            if render is None:
                continue
            seen_frame_indices.add(frame_index)
            frame_renders.append(render)

        preview_objects.append(
            {
                "id": scene_object["id"],
                "name": scene_object["name"],
                "sort_order": int(scene_object.get("sort_order", 0) or 0),
                "visible": bool(scene_object.get("visible", True)),
                "enabled": bool(scene_object.get("enabled", True)),
                "keyboard_target_enabled": bool(scene_object.get("keyboard_target_enabled")),
                "pickup_uploaded_file_id": scene_object.get("pickup_uploaded_file_id"),
                "label": scene_object["name"],
                "default_render": default_render,
                "frame_renders": frame_renders,
                "animations": animations,
            }
        )

    return {
        "scene_id": scene["id"],
        "title": scene["title"],
        "description": scene["description"],
        "presentation_mode": scene.get("presentation_mode", "base"),
        "background_frame_index": int(scene.get("background_frame_index") or 0),
        "width": scene_width,
        "height": scene_height,
        "images": preview_images,
        "objects": preview_objects,
        "interactions": preview_interactions,
    }


def _collect_script_line_ids(interactions: list[dict[str, Any]]) -> set[int]:
    line_ids: set[int] = set()
    for interaction in interactions:
        _collect_script_line_ids_from_steps(interaction.get("action_tree") or [], line_ids)
    return line_ids


def _collect_go_to_frame_refs(interactions: list[dict[str, Any]]) -> tuple[dict[int, set[int]], bool]:
    refs: dict[int, set[int]] = {}
    has_contextual_refs = False
    for interaction in interactions:
        has_contextual_refs = _collect_go_to_frame_refs_from_steps(interaction.get("action_tree") or [], refs) or has_contextual_refs
    return refs, has_contextual_refs


def _collect_script_line_ids_from_steps(steps: list[dict[str, Any]], line_ids: set[int]) -> None:
    for step in steps:
        if step.get("type") in {"show_subtitle", "play_audio"}:
            for line_id in step.get("script_line_ids") or []:
                try:
                    line_ids.add(int(line_id))
                except (TypeError, ValueError):
                    continue
        _collect_script_line_ids_from_steps(step.get("then_steps") or [], line_ids)
        _collect_script_line_ids_from_steps(step.get("else_steps") or [], line_ids)


def _collect_go_to_frame_refs_from_steps(
    steps: list[dict[str, Any]],
    refs: dict[int, set[int]],
) -> bool:
    has_contextual_refs = False
    for step in steps:
        if step.get("type") == "go_to_frame" and step.get("target_scope", "object") == "object":
            if step.get("target_object_mode", "static") != "static":
                has_contextual_refs = True
            else:
                try:
                    object_id = int(step.get("target_object_id"))
                    frame_index = int(step.get("frame_index"))
                except (TypeError, ValueError):
                    object_id = None
                    frame_index = None
                if object_id is not None and frame_index is not None:
                    refs.setdefault(object_id, set()).add(frame_index)
        has_contextual_refs = _collect_go_to_frame_refs_from_steps(step.get("then_steps") or [], refs) or has_contextual_refs
        has_contextual_refs = _collect_go_to_frame_refs_from_steps(step.get("else_steps") or [], refs) or has_contextual_refs
    return has_contextual_refs


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


def _preferred_object_masks(
    scene_object: dict[str, Any],
    object_masks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    preferred_uploaded_file_id = scene_object.get("default_uploaded_file_id")
    if preferred_uploaded_file_id is None:
        return object_masks
    preferred_uploaded_file_id = int(preferred_uploaded_file_id)
    preferred = [
        object_mask
        for object_mask in object_masks
        if int(object_mask["uploaded_file_id"]) == preferred_uploaded_file_id
    ]
    if not preferred:
        return object_masks
    others = [
        object_mask
        for object_mask in object_masks
        if int(object_mask["uploaded_file_id"]) != preferred_uploaded_file_id
    ]
    return [*preferred, *others]


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


def _scene_preview_manifest_cache_path(
    storage_root: Path,
    organization_id: str,
    scene_id: int,
) -> Path:
    return (
        storage_root
        / _safe_path_segment(organization_id)
        / "derived"
        / "scenes"
        / str(scene_id)
        / "preview"
        / "manifest.json"
    )


def _read_scene_preview_manifest_cache(cache_path: Path) -> dict[str, Any] | None:
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get("version") or 0) != SCENE_PREVIEW_MANIFEST_CACHE_VERSION:
        return None
    manifest = payload.get("manifest")
    return manifest if isinstance(manifest, dict) else None


def _write_scene_preview_manifest_cache(cache_path: Path, manifest: dict[str, Any]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "version": SCENE_PREVIEW_MANIFEST_CACHE_VERSION,
                "manifest": manifest,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def _invalidate_scene_preview_manifest_cache(
    storage_root: Path,
    organization_id: str,
    scene_id: int,
) -> None:
    cache_path = _scene_preview_manifest_cache_path(storage_root, organization_id, scene_id)
    try:
        cache_path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _read_preview_render_metadata(metadata_path: Path) -> dict[str, Any]:
    if not metadata_path.exists():
        return {}
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _render_inventory_input_image(
    database_path: Path,
    storage_root: Path,
    inventory_input_root: Path,
    organization_id: str,
    scene_object: dict[str, Any],
) -> Path | None:
    object_masks = _preferred_object_masks(scene_object, list_object_masks_for_object(
        database_path,
        scene_object_id=scene_object["id"],
        organization_id=organization_id,
    ))
    for object_mask in object_masks:
        original_path = storage_root / object_mask["original_relative_path"]
        mask_relative_path = object_mask["soft_relative_path"] or object_mask["relative_path"]
        mask_path = storage_root / mask_relative_path
        if not original_path.exists() or not mask_path.exists():
            continue
        input_path = inventory_input_root / f"scene_{scene_object['scene_id']}_object_{scene_object['id']}.png"
        rendered = render_masked_object_crop(
            original_path=original_path,
            mask_path=mask_path,
            output_path=input_path,
            max_size=768,
        )
        if rendered is None:
            continue
        return input_path
    return None


async def _generate_inventory_image_for_scene_object(
    database_path: Path,
    storage_root: Path,
    inventory_input_root: Path,
    organization_id: str,
    scene_id: int,
    scene_object: dict[str, Any],
    inventory_image_provider: InventoryImageProvider,
) -> dict[str, Any]:
    rendered_input_path = _render_inventory_input_image(
        database_path,
        storage_root=storage_root,
        inventory_input_root=inventory_input_root,
        organization_id=organization_id,
        scene_object=scene_object,
    )
    if rendered_input_path is None:
        return {"status": "skipped", "scene_object": None}

    output_relative_path = (
        f"{_safe_path_segment(organization_id)}/derived/scenes/{scene_id}/objects/"
        f"{scene_object['id']}/inventory/generated.png"
    )
    output_path = storage_root / output_relative_path
    object_description = (
        (scene_object.get("inventory_image_prompt") or "").strip()
        or (scene_object.get("description") or "").strip()
        or str(scene_object.get("name") or "").strip()
    )

    try:
        await inventory_image_provider.generate_inventory_image(
            rendered_input_path=rendered_input_path,
            object_name=scene_object["name"],
            object_description=object_description,
            output_path=output_path,
        )
    except InventoryImageProviderUnavailable as exc:
        set_scene_object_inventory_image_failed(
            database_path,
            scene_id=scene_id,
            object_id=int(scene_object["id"]),
            failed=True,
        )
        _unlink_if_exists(output_path)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        set_scene_object_inventory_image_failed(
            database_path,
            scene_id=scene_id,
            object_id=int(scene_object["id"]),
            failed=True,
        )
        _unlink_if_exists(output_path)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not _is_valid_inventory_image_file(output_path):
        set_scene_object_inventory_image_failed(
            database_path,
            scene_id=scene_id,
            object_id=int(scene_object["id"]),
            failed=True,
        )
        _unlink_if_exists(output_path)
        return {"status": "failed", "scene_object": None}

    updated_scene_object = set_scene_object_inventory_image(
        database_path,
        scene_id=scene_id,
        object_id=int(scene_object["id"]),
        relative_path=output_relative_path,
    )
    return {"status": "generated", "scene_object": updated_scene_object}


def _first_visible_scene_image_for_object(
    scene: dict[str, Any],
    scene_object: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | tuple[None, None]:
    masks_by_uploaded_file_id = {
        int(object_mask["uploaded_file_id"]): object_mask
        for object_mask in (scene_object.get("masks") or [])
    }
    preferred_uploaded_file_id = scene_object.get("default_uploaded_file_id")
    if preferred_uploaded_file_id is not None:
        preferred_uploaded_file_id = int(preferred_uploaded_file_id)
        preferred_mask = masks_by_uploaded_file_id.get(preferred_uploaded_file_id)
        if preferred_mask is not None:
            preferred_scene_image = next(
                (
                    scene_image
                    for scene_image in scene.get("images", [])
                    if int(scene_image["uploaded_file_id"]) == preferred_uploaded_file_id
                ),
                None,
            )
            if preferred_scene_image is not None:
                return preferred_scene_image, preferred_mask
    for scene_image in scene.get("images", []):
        object_mask = masks_by_uploaded_file_id.get(int(scene_image["uploaded_file_id"]))
        if object_mask is not None:
            return scene_image, object_mask
    return None, None


def _render_scene_removal_input_image(
    storage_root: Path,
    inventory_input_root: Path,
    scene: dict[str, Any],
    scene_object: dict[str, Any],
) -> dict[str, Any] | None:
    scene_image, object_mask = _first_visible_scene_image_for_object(scene, scene_object)
    if scene_image is None or object_mask is None:
        return None
    original_path = storage_root / scene_image["relative_path"]
    if not original_path.exists():
        return None
    mask_path = storage_root / (object_mask.get("soft_relative_path") or object_mask["relative_path"])
    if not mask_path.exists():
        return None
    with Image.open(original_path) as image:
        original = image.convert("RGBA")
        original.load()
    with Image.open(mask_path) as image:
        mask = image.convert("L")
        mask.load()
    if mask.size != original.size:
        mask = mask.resize(original.size, Image.Resampling.LANCZOS)
    binary_mask = mask.point(lambda value: 255 if value >= 1 else 0)
    bbox = binary_mask.getbbox()
    if bbox is None:
        return None
    left, top, right, bottom = bbox
    width, height = original.size
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    crop_size = 1024
    crop_left = int(round(center_x - crop_size / 2))
    crop_top = int(round(center_y - crop_size / 2))
    crop_left = max(0, min(crop_left, max(0, width - crop_size)))
    crop_top = max(0, min(crop_top, max(0, height - crop_size)))
    crop_right = min(width, crop_left + crop_size)
    crop_bottom = min(height, crop_top + crop_size)
    crop_box = (crop_left, crop_top, crop_right, crop_bottom)
    crop = original.crop(crop_box)
    if crop.size != (crop_size, crop_size):
        padded = Image.new("RGBA", (crop_size, crop_size), (255, 255, 255, 255))
        padded.paste(crop, (0, 0))
        crop = padded
    input_path = inventory_input_root / f"scene_{scene['id']}_object_{scene_object['id']}_remove.png"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(input_path, format="PNG")
    return {
        "input_path": input_path,
        "scene_image": scene_image,
        "object_mask": object_mask,
        "crop_box": crop_box,
        "scene_size": original.size,
    }


def _composite_scene_removal_crop(
    original_path: Path,
    generated_crop_path: Path,
    crop_box: tuple[int, int, int, int],
    output_path: Path,
) -> None:
    with Image.open(original_path) as image:
        original = image.convert("RGBA")
        original.load()
    with Image.open(generated_crop_path) as image:
        generated = image.convert("RGBA")
        generated.load()
    crop_width = max(1, crop_box[2] - crop_box[0])
    crop_height = max(1, crop_box[3] - crop_box[1])
    if generated.size != (crop_width, crop_height):
        generated = generated.resize((crop_width, crop_height), Image.Resampling.LANCZOS)
    original.paste(generated, crop_box[:2], generated)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    original.save(output_path, format="PNG")


async def _generate_scene_removal_for_object(
    database_path: Path,
    storage_root: Path,
    inventory_input_root: Path,
    organization_id: str,
    scene: dict[str, Any],
    scene_object: dict[str, Any],
    upload_batch: dict[str, Any],
    uploaded_by_user_id: int,
    removal_provider: InventoryImageProvider,
) -> dict[str, Any]:
    rendered_input = _render_scene_removal_input_image(
        storage_root=storage_root,
        inventory_input_root=inventory_input_root,
        scene=scene,
        scene_object=scene_object,
    )
    if rendered_input is None:
        return {"status": "skipped"}

    removal_output_relative_path = (
        f"{_safe_path_segment(organization_id)}/derived/scenes/{scene['id']}/objects/"
        f"{scene_object['id']}/scene-removal/generated.png"
    )
    removal_output_path = storage_root / removal_output_relative_path
    prompt_subject = (
        (scene_object.get("inventory_image_prompt") or "").strip()
        or (scene_object.get("name") or "").strip()
    )
    try:
        await removal_provider.generate_inventory_image(
            rendered_input_path=rendered_input["input_path"],
            object_name=scene_object["name"],
            object_description=prompt_subject,
            output_path=removal_output_path,
        )
    except InventoryImageProviderUnavailable as exc:
        set_scene_object_pickup_frame_failed(
            database_path,
            scene_id=int(scene["id"]),
            object_id=int(scene_object["id"]),
            failed=True,
        )
        _unlink_if_exists(removal_output_path)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        set_scene_object_pickup_frame_failed(
            database_path,
            scene_id=int(scene["id"]),
            object_id=int(scene_object["id"]),
            failed=True,
        )
        _unlink_if_exists(removal_output_path)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not _is_valid_inventory_image_file(removal_output_path):
        set_scene_object_pickup_frame_failed(
            database_path,
            scene_id=int(scene["id"]),
            object_id=int(scene_object["id"]),
            failed=True,
        )
        _unlink_if_exists(removal_output_path)
        return {"status": "failed"}

    batch_root = _batch_storage_root(storage_root, organization_id, upload_batch["id"])
    original_filename = f"removed-{_safe_filename(scene_object['name'])}.png"
    stored_filename = f"{uuid4().hex}-{original_filename}"
    composited_output_path = batch_root / stored_filename
    original_scene_image_path = storage_root / rendered_input["scene_image"]["relative_path"]
    try:
        _composite_scene_removal_crop(
            original_path=original_scene_image_path,
            generated_crop_path=removal_output_path,
            crop_box=rendered_input["crop_box"],
            output_path=composited_output_path,
        )
        file_size = composited_output_path.stat().st_size
        uploaded_file = add_uploaded_file(
            database_path,
            batch_id=upload_batch["id"],
            organization_id=organization_id,
            uploaded_by_user_id=uploaded_by_user_id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            relative_path=str(Path(organization_id) / str(upload_batch["id"]) / stored_filename),
            content_type="image/png",
            file_size=file_size,
        )
        fingerprint = fingerprint_image(composited_output_path)
        assigned_scene_image = assign_uploaded_file_to_scene(
            database_path,
            scene_id=int(scene["id"]),
            uploaded_file_id=int(uploaded_file["id"]),
            perceptual_hash=fingerprint.perceptual_hash,
            width=fingerprint.width,
            height=fingerprint.height,
        )
        combined_mask_image = _combine_object_mask_images(storage_root, scene_object.get("masks") or [])
        combined_mask_output_root = (
            storage_root
            / _safe_path_segment(organization_id)
            / "derived"
            / "scenes"
            / str(scene["id"])
            / "images"
            / str(uploaded_file["id"])
        )
        safe_object_stem = _safe_path_segment(str(scene_object["name"]))
        raw_mask_path = combined_mask_output_root / f"{safe_object_stem}_00.png"
        soft_mask_path = combined_mask_output_root / f"{safe_object_stem}_00_soft.png"
        raw_mask_path.parent.mkdir(parents=True, exist_ok=True)
        combined_mask_image.save(raw_mask_path, format="PNG")
        combined_mask_image.save(soft_mask_path, format="PNG")
        bbox = combined_mask_image.point(lambda value: 255 if value >= 1 else 0).getbbox()
        created_mask = create_object_mask(
            database_path,
            scene_object_id=int(scene_object["id"]),
            uploaded_file_id=int(uploaded_file["id"]),
            relative_path=_relative_storage_path(storage_root, raw_mask_path),
            soft_relative_path=_relative_storage_path(storage_root, soft_mask_path),
            prompt_text=scene_object["prompt"],
            bbox_json=json.dumps(list(bbox)) if bbox else None,
            score=None,
        )
        set_scene_object_pickup_frame(
            database_path,
            scene_id=int(scene["id"]),
            object_id=int(scene_object["id"]),
            uploaded_file_id=int(uploaded_file["id"]),
        )
        return {
            "status": "generated",
            "uploaded_file_id": int(uploaded_file["id"]),
            "scene_image_id": int(assigned_scene_image["id"]) if assigned_scene_image else None,
            "object_mask_id": int(created_mask["id"]),
        }
    except Exception:  # noqa: BLE001
        set_scene_object_pickup_frame_failed(
            database_path,
            scene_id=int(scene["id"]),
            object_id=int(scene_object["id"]),
            failed=True,
        )
        _unlink_if_exists(composited_output_path)
        return {"status": "failed"}


async def _collect_dependency_health(
    *,
    settings: Settings,
    vlm_provider_error: str | None,
    segmentation_provider_error: str | None,
    line_localization_provider_error: str | None,
    inventory_image_provider_error: str | None,
    scene_removal_provider_error: str | None,
) -> list[dict[str, str]]:
    checks = [
        await _check_ollama_health(
            key="vlm",
            label="Scene VLM",
            url=f"{settings.vlm_base_url.rstrip('/')}/api/tags",
            disabled=settings.vlm_provider.strip().lower() in {"", "none", "disabled"},
            configuration_error=vlm_provider_error,
            configured_detail=f"{settings.vlm_model} via {settings.vlm_base_url}",
        ),
        _check_segmentation_health(settings, segmentation_provider_error),
        await _check_ollama_health(
            key="translation",
            label="Translation",
            url=_ollama_tags_url(settings.script_translation_ollama_url),
            disabled=settings.script_localization_provider.strip().lower() in {"", "none", "disabled"},
            configuration_error=line_localization_provider_error,
            configured_detail=f"{settings.script_translation_model} via {settings.script_translation_ollama_url}",
        ),
        _check_xtts_health(settings, line_localization_provider_error),
        await _check_http_dependency(
            key="inventory_art",
            label="Inventory art",
            url=f"{settings.inventory_image_comfy_url.rstrip('/')}/system_stats",
            disabled=settings.inventory_image_provider.strip().lower() in {"", "none", "disabled"},
            configuration_error=inventory_image_provider_error,
            configured_detail=f"ComfyUI via {settings.inventory_image_comfy_url}",
        ),
        await _check_http_dependency(
            key="pickup_frames",
            label="Pickup frames",
            url=f"{settings.inventory_image_comfy_url.rstrip('/')}/system_stats",
            disabled=settings.inventory_image_provider.strip().lower() in {"", "none", "disabled"},
            configuration_error=scene_removal_provider_error,
            configured_detail=f"ComfyUI removal workflow via {settings.inventory_image_comfy_url}",
        ),
    ]
    return checks


async def _check_ollama_health(
    *,
    key: str,
    label: str,
    url: str,
    disabled: bool,
    configuration_error: str | None,
    configured_detail: str,
) -> dict[str, str]:
    return await _check_http_dependency(
        key=key,
        label=label,
        url=url,
        disabled=disabled,
        configuration_error=configuration_error,
        configured_detail=configured_detail,
    )


async def _check_http_dependency(
    *,
    key: str,
    label: str,
    url: str,
    disabled: bool,
    configuration_error: str | None,
    configured_detail: str,
) -> dict[str, str]:
    if disabled:
        return {
            "key": key,
            "label": label,
            "status": "warning",
            "detail": "Disabled in configuration.",
        }
    if configuration_error:
        return {
            "key": key,
            "label": label,
            "status": "error",
            "detail": configuration_error,
        }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
        return {
            "key": key,
            "label": label,
            "status": "ok",
            "detail": configured_detail,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "key": key,
            "label": label,
            "status": "error",
            "detail": f"Could not reach service: {exc}",
        }


def _check_segmentation_health(settings: Settings, configuration_error: str | None) -> dict[str, str]:
    if settings.segmentation_provider.strip().lower() in {"", "none", "disabled"}:
        return {
            "key": "segmentation",
            "label": "Segmentation",
            "status": "warning",
            "detail": "Disabled in configuration.",
        }
    if configuration_error:
        return {
            "key": "segmentation",
            "label": "Segmentation",
            "status": "error",
            "detail": configuration_error,
        }
    script_path = Path(__file__).resolve().parents[2] / "tools" / "sam3_smoke.py"
    if not script_path.exists():
        return {
            "key": "segmentation",
            "label": "Segmentation",
            "status": "error",
            "detail": f"SAM3 script is missing: {script_path}",
        }
    return {
        "key": "segmentation",
        "label": "Segmentation",
        "status": "ok",
        "detail": f"{settings.segmentation_provider} via env {settings.segmentation_conda_env}",
    }


def _check_xtts_health(settings: Settings, configuration_error: str | None) -> dict[str, str]:
    if settings.script_localization_provider.strip().lower() in {"", "none", "disabled"}:
        return {
            "key": "tts",
            "label": "Narrator TTS",
            "status": "warning",
            "detail": "Disabled in configuration.",
        }
    if configuration_error:
        return {
            "key": "tts",
            "label": "Narrator TTS",
            "status": "error",
            "detail": configuration_error,
        }
    cmd_path = shutil.which("cmd.exe")
    fallback_cmd_path = Path("/mnt/c/Windows/system32/cmd.exe")
    if not cmd_path and not fallback_cmd_path.exists():
        return {
            "key": "tts",
            "label": "Narrator TTS",
            "status": "error",
            "detail": "cmd.exe is not available from WSL.",
        }
    if not settings.script_xtts_python_path.exists():
        return {
            "key": "tts",
            "label": "Narrator TTS",
            "status": "error",
            "detail": f"XTTS Python is missing: {settings.script_xtts_python_path}",
        }
    if not settings.script_xtts_speaker_wav.exists():
        return {
            "key": "tts",
            "label": "Narrator TTS",
            "status": "error",
            "detail": f"Speaker reference is missing: {settings.script_xtts_speaker_wav}",
        }
    return {
        "key": "tts",
        "label": "Narrator TTS",
        "status": "ok",
        "detail": f"{settings.script_xtts_python_path} using {settings.script_xtts_device}",
    }


def _ollama_tags_url(generate_url: str) -> str:
    parsed = urlparse(generate_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/api/tags"
    return generate_url


def _humanize_script_provider_error(error: Exception | str, kind: str) -> str:
    message = str(error or "").strip()
    lowered = message.lower()
    if kind == "translation":
        if "ollama" in lowered or "connect" in lowered or "connection" in lowered or "timed out" in lowered:
            return "Translation service is unavailable. Check Ollama on the Health page."
        return "Translation generation failed. Check the translation service on the Health page."
    if "cmd.exe" in lowered or "python is missing" in lowered:
        return "TTS generation is not configured correctly on this machine. Check XTTS on the Health page."
    return "TTS generation failed. Check XTTS on the Health page."


def _batch_storage_root(storage_root: Path, organization_id: str, batch_id: int) -> Path:
    return storage_root / _safe_path_segment(organization_id) / str(batch_id)


def _clear_scene_derived_cache(storage_root: Path, organization_id: str, scene_id: int) -> None:
    derived_root = (
        storage_root
        / _safe_path_segment(organization_id)
        / "derived"
        / "scenes"
        / str(scene_id)
    )
    shutil.rmtree(derived_root, ignore_errors=True)


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


def _normalize_script_path_parts(path_text: str) -> list[str]:
    if not path_text.strip():
        return []
    return [part.strip() for part in path_text.split("/") if part.strip()]


def _normalize_verb_key(value: str) -> str:
    normalized = sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    if not normalized:
        raise HTTPException(status_code=400, detail="Verb key is required")
    return normalized[:64]


def _normalize_verb_labels(labels: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for language, text in (labels or {}).items():
        normalized_language = str(language or "").strip().lower()
        normalized_text = str(text or "").strip()
        if not normalized_language or not normalized_text:
            continue
        normalized[normalized_language] = normalized_text
    if not normalized:
        raise HTTPException(status_code=400, detail="At least one verb label is required")
    return normalized


def _variant_key_from_folder_file(folder_name: str, file_stem: str) -> str:
    return f"{_safe_path_segment(folder_name)}__{_safe_path_segment(file_stem)}"


def _character_component_output_dir(
    organization_id: str,
    character_id: int,
    component_key: str,
    group_name: str,
) -> Path:
    return (
        Path(_safe_path_segment(organization_id))
        / "characters"
        / str(character_id)
        / _safe_path_segment(component_key)
        / _safe_path_segment(group_name)
    )


def _resolve_pose_subfolder(root: Path, subfolder_name: str | None) -> Path:
    if not subfolder_name:
        raise HTTPException(status_code=400, detail="Choose a pose folder first")
    candidate = _safe_child_path(root, subfolder_name)
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(status_code=404, detail="Pose folder not found")
    return candidate


def _image_dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return int(image.width), int(image.height)


def _character_asset_url(image_id: int) -> str:
    return f"/api/character-images/{image_id}/content"


def _character_preview_image_payload(image: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(image["id"]),
        "component_key": str(image["component_key"]),
        "variant_key": str(image["variant_key"]),
        "kind": str(image["kind"]),
        "source_group": str(image.get("source_group") or ""),
        "source_name": str(image.get("source_name") or ""),
        "width": int(image.get("width") or 0),
        "height": int(image.get("height") or 0),
        "url": _character_asset_url(int(image["id"])),
    }


def _character_preview_payload(
    db_path: Path,
    storage_root: Path,
    organization_id: str,
    character_id: int,
) -> dict[str, Any]:
    character = _load_character_detail(db_path, organization_id, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    scene = character.get("scene") or None
    scene_manifest = None
    mouth_scene_object_id = (
        int(character["mouth_scene_object_id"])
        if character.get("mouth_scene_object_id") is not None
        else None
    )
    viseme_frame_renders: dict[str, Any] = {}
    if scene is not None:
        scene_manifest = _build_scene_preview_manifest(
            database_path=db_path,
            storage_root=storage_root,
            organization_id=organization_id,
            scene=scene,
        )
        if mouth_scene_object_id is not None:
            mouth_object = next(
                (
                    item
                    for item in scene_manifest.get("objects", [])
                    if int(item.get("id") or 0) == mouth_scene_object_id
                ),
                None,
            )
            if mouth_object is not None:
                frame_index_by_uploaded_file_id = {
                    int(image["uploaded_file_id"]): index
                    for index, image in enumerate(scene.get("images", []))
                }
                mouth_object_masks = list_object_masks_for_object(
                    db_path,
                    scene_object_id=mouth_scene_object_id,
                    organization_id=organization_id,
                )
                for object_mask in mouth_object_masks:
                    render = _preview_render_payload_for_mask(
                        storage_root=storage_root,
                        organization_id=organization_id,
                        object_mask=object_mask,
                        frame_index=frame_index_by_uploaded_file_id.get(int(object_mask["uploaded_file_id"])),
                    )
                    if render is None:
                        continue
                    original_filename = str(render.get("original_filename") or "")
                    stem = Path(original_filename).stem
                    if "-" in stem:
                        folder_name, file_stem = stem.split("-", 1)
                        viseme_frame_renders[_variant_key_from_folder_file(folder_name, file_stem)] = render

    return {
        "id": int(character["id"]),
        "name": str(character["name"]),
        "description": str(character.get("description") or ""),
        "scene_id": int(character["scene_id"]) if character.get("scene_id") is not None else None,
        "mouth_scene_object_id": mouth_scene_object_id,
        "sort_order": int(character.get("sort_order") or 0),
        "default_x": float(character.get("default_x") or 0),
        "default_y": float(character.get("default_y") or 0),
        "default_scale": float(character.get("default_scale") or 1.0),
        "width": int(scene_manifest.get("width") or 0) if scene_manifest else 0,
        "height": int(scene_manifest.get("height") or 0) if scene_manifest else 0,
        "background_frame_index": int(scene_manifest.get("background_frame_index") or 0) if scene_manifest else 0,
        "objects": scene_manifest.get("objects", []) if scene_manifest else [],
        "viseme_frame_renders": viseme_frame_renders,
        "images": [_character_preview_image_payload(image) for image in character.get("images", [])],
        "animations": [
            {
                "id": int(animation["id"]),
                "name": str(animation["name"]),
                "frames": [
                    {
                        "id": int(frame["id"]),
                        "character_image_id": int(frame["character_image_id"]),
                        "duration_seconds": float(frame["duration_seconds"]),
                        "image": _character_preview_image_payload(frame["image"]),
                    }
                    for frame in animation.get("frames", [])
                ],
            }
            for animation in character.get("animations", [])
        ],
    }


def _load_character_detail(
    db_path: Path,
    organization_id: str,
    character_id: int,
) -> dict[str, Any] | None:
    character = get_character_by_id(db_path, organization_id, character_id)
    if character is None:
        return None
    images = list_character_images(db_path, organization_id, character_id)
    objects = list_character_objects(db_path, organization_id, character_id)
    animations = list_character_animations(db_path, organization_id, character_id)
    scene_id = character.get("scene_id")
    scene = None
    if scene_id is not None:
        scene_record = get_scene_with_images(db_path, int(scene_id))
        if scene_record is not None and scene_record.get("organization_id") == organization_id:
            scene = scene_record
    return {
        **character,
        "scene": scene,
        "images": images,
        "objects": objects,
        "animations": animations,
    }


def _get_default_character_component_image(
    character: dict[str, Any],
    component_key: str,
) -> dict[str, Any] | None:
    images = [
        image
        for image in character.get("images", [])
        if str(image.get("component_key") or "") == component_key
    ]
    default_image = next((image for image in images if image.get("is_default")), None)
    return default_image or (images[0] if images else None)


def _character_default_scene_image(character: dict[str, Any]) -> dict[str, Any] | None:
    scene = character.get("scene") or {}
    images = scene.get("images") or []
    if not images:
        return None
    background_frame_index = int(scene.get("background_frame_index") or 0)
    if 0 <= background_frame_index < len(images):
        return images[background_frame_index]
    return images[0]


def _content_type_for_suffix(suffix: str) -> str:
    normalized = str(suffix or "").strip().lower()
    if normalized in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if normalized == ".webp":
        return "image/webp"
    return "image/png"


async def _write_upload(upload: UploadFile, stored_path: Path) -> int:
    total_bytes = 0
    with stored_path.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            total_bytes += len(chunk)
            output.write(chunk)
    await upload.close()
    return total_bytes


async def _ingest_review_audio_upload(
    db_path: Path,
    settings: Settings,
    organization_id: str,
    line_id: int,
    language: str,
    upload: UploadFile,
) -> dict[str, Any]:
    normalized_language = str(language or "").strip().lower()
    if not normalized_language:
        raise HTTPException(status_code=400, detail="Language is required")
    original_filename = _safe_filename(upload.filename or "line-audio.bin")
    upload_root = (
        settings.script_audio_root
        / "user_uploads"
        / _safe_path_segment(organization_id)
        / f"line-{line_id}"
        / normalized_language
    )
    upload_root.mkdir(parents=True, exist_ok=True)
    source_path = upload_root / f"{uuid4().hex}-{original_filename}"
    await _write_upload(upload, source_path)
    output_path = source_path.with_suffix(".ogg")
    if output_path == source_path:
        output_path = source_path.with_name(f"{source_path.stem}-normalized.ogg")
    try:
        await _process_review_audio_file(source_path, output_path)
        relative_path = str(output_path.relative_to(settings.script_audio_root))
        duration_seconds = _probe_audio_duration_seconds(output_path)
        candidate = upsert_script_audio_candidate(
            db_path,
            organization_id=organization_id,
            line_id=line_id,
            language=normalized_language,
            source_type="uploaded_review",
            manifest_status="uploaded",
            relative_path=relative_path,
            original_path=relative_path,
            rank=None,
            duration_seconds=duration_seconds,
            source_file=original_filename,
            review_status="needs_review",
        )
        if candidate is None:
            raise RuntimeError("Uploaded audio candidate could not be created")
        return candidate
    finally:
        if source_path.exists() and source_path != output_path:
            source_path.unlink()


async def _process_review_audio_file(source_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        shutil.copyfile(source_path, output_path)
        return
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(source_path),
        "-af",
        (
            "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-45dB:"
            "stop_periods=-1:stop_silence=0.1:stop_threshold=-45dB,"
            "loudnorm=I=-19:TP=-2:LRA=7"
        ),
        "-c:a",
        "libvorbis",
        "-q:a",
        "5",
        str(output_path),
    ]
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        error_output = stderr.decode("utf-8", errors="replace").strip()
        if output_path.exists():
            output_path.unlink()
        raise HTTPException(
            status_code=502,
            detail=error_output or "Audio processing failed",
        )


def _probe_audio_duration_seconds(path: Path) -> float | None:
    ffprobe_path = shutil.which("ffprobe")
    if not ffprobe_path:
        return None
    import subprocess

    process = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if process.returncode != 0:
        return None
    try:
        return float(process.stdout.strip())
    except (TypeError, ValueError):
        return None


def _delete_workspace_storage(
    storage_root: Path,
    organization_id: str,
    preserve_audio_assets: bool,
) -> None:
    org_root = storage_root / _safe_path_segment(organization_id)
    if not org_root.exists():
        return
    for child in org_root.iterdir():
        if preserve_audio_assets and child.name == "audio":
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def _error_code(message: str) -> str:
    return (
        message.lower()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("'", "")
        .replace('"', "")
    )


app = create_app()
