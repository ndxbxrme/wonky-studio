from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
    storage_root: Path
    script_audio_root: Path = Path("/mnt/d/wonky-studio/audio")
    script_localization_provider: str = "subprocess"
    script_translate_script_path: Path = Path("/mnt/d/wonky-studio/audio/translate_script_ollama.py")
    script_xtts_script_path: Path = Path("/mnt/d/wonky-studio/audio/batch_xtts_generate.py")
    script_xtts_python_path: Path = Path("/mnt/d/wonky-studio/audio/xtts-env/Scripts/python.exe")
    script_xtts_speaker_wav: Path = Path("/mnt/d/wonky-studio/audio/voice_refs/narrator_ref.wav")
    script_translation_model: str = "qwen2.5:7b-instruct"
    script_translation_source_language: str = "UK English / en-GB"
    script_translation_target_languages: str = "en,de,es,fr,it,pt"
    script_translation_ollama_url: str = "http://localhost:11434/api/generate"
    script_translation_timeout_seconds: float = 180.0
    script_xtts_device: str = "cuda"
    script_xtts_timeout_seconds: float = 600.0
    vlm_provider: str = "ollama"
    vlm_base_url: str = "http://127.0.0.1:11434"
    vlm_model: str = "gemma3:4b"
    vlm_keep_alive: str = "0"
    vlm_timeout_seconds: float = 60.0
    segmentation_provider: str = "sam3-subprocess"
    segmentation_conda_env: str = "sam3"
    segmentation_timeout_seconds: float = 300.0
    segmentation_max_edge: int = 960
    segmentation_threshold: float = 0.2
    segmentation_dilate_pixels: int = 2
    segmentation_blur_radius: float = 1.5
    inventory_image_provider: str = "comfyui"
    inventory_image_comfy_url: str = "http://172.24.224.1:8189"
    inventory_image_workflow_path: Path = Path("temp/inventory-image-generator/inventory_item_workflow.json")
    inventory_image_input_root: Path = Path("/mnt/d/wonky-studio/temp")
    inventory_image_comfy_input_root: str = "D:/wonky-studio/temp"
    inventory_image_output_root: Path = Path("/mnt/d/AI/ComfyUI_windows_portable/ComfyUI/output")
    inventory_image_timeout_seconds: float = 300.0
    scene_removal_workflow_path: Path = Path("temp/inventory-image-generator/remove_item_workflow.json")
    character_image_provider: str = "comfyui"
    character_image_workflow_path: Path = Path("temp/viseme_pose_workflow.json")
    character_image_input_root: Path = Path("/mnt/d/wonky-studio/temp")
    character_viseme_source_root: Path = Path("/mnt/d/wonky-studio/visemes")
    character_pose_source_root: Path = Path("/mnt/d/wonky-studio/poses")
    viseme_extraction_provider: str = "subprocess"
    viseme_extraction_python_path: Path = Path("/mnt/d/wonky-studio/audio/xtts-env/Scripts/python.exe")
    viseme_extraction_script_path: Path = Path("/mnt/d/wonky-studio/audio/extract_visemes.py")
    viseme_extraction_timeout_seconds: float = 300.0


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
        storage_root=Path(
            os.environ.get("WONKY_STUDIO_STORAGE_ROOT", _default_storage_root())
        ),
        script_audio_root=Path(
            os.environ.get("WONKY_STUDIO_SCRIPT_AUDIO_ROOT", "/mnt/d/wonky-studio/audio")
        ),
        script_localization_provider=os.environ.get(
            "WONKY_STUDIO_SCRIPT_LOCALIZATION_PROVIDER",
            "subprocess",
        ),
        script_translate_script_path=Path(
            os.environ.get(
                "WONKY_STUDIO_SCRIPT_TRANSLATE_SCRIPT_PATH",
                "/mnt/d/wonky-studio/audio/translate_script_ollama.py",
            )
        ),
        script_xtts_script_path=Path(
            os.environ.get(
                "WONKY_STUDIO_SCRIPT_XTTS_SCRIPT_PATH",
                "/mnt/d/wonky-studio/audio/batch_xtts_generate.py",
            )
        ),
        script_xtts_python_path=Path(
            os.environ.get(
                "WONKY_STUDIO_SCRIPT_XTTS_PYTHON_PATH",
                "/mnt/d/wonky-studio/audio/xtts-env/Scripts/python.exe",
            )
        ),
        script_xtts_speaker_wav=Path(
            os.environ.get(
                "WONKY_STUDIO_SCRIPT_XTTS_SPEAKER_WAV",
                "/mnt/d/wonky-studio/audio/voice_refs/narrator_ref.wav",
            )
        ),
        script_translation_model=os.environ.get(
            "WONKY_STUDIO_SCRIPT_TRANSLATION_MODEL",
            "qwen2.5:7b-instruct",
        ),
        script_translation_source_language=os.environ.get(
            "WONKY_STUDIO_SCRIPT_TRANSLATION_SOURCE_LANGUAGE",
            "UK English / en-GB",
        ),
        script_translation_target_languages=os.environ.get(
            "WONKY_STUDIO_SCRIPT_TRANSLATION_TARGET_LANGUAGES",
            "en,de,es,fr,it,pt",
        ),
        script_translation_ollama_url=os.environ.get(
            "WONKY_STUDIO_SCRIPT_TRANSLATION_OLLAMA_URL",
            "http://localhost:11434/api/generate",
        ),
        script_translation_timeout_seconds=float(
            os.environ.get("WONKY_STUDIO_SCRIPT_TRANSLATION_TIMEOUT_SECONDS", "180")
        ),
        script_xtts_device=os.environ.get("WONKY_STUDIO_SCRIPT_XTTS_DEVICE", "cuda"),
        script_xtts_timeout_seconds=float(
            os.environ.get("WONKY_STUDIO_SCRIPT_XTTS_TIMEOUT_SECONDS", "600")
        ),
        vlm_provider=os.environ.get("WONKY_STUDIO_VLM_PROVIDER", "ollama"),
        vlm_base_url=os.environ.get("WONKY_STUDIO_VLM_BASE_URL", "http://127.0.0.1:11434"),
        vlm_model=os.environ.get("WONKY_STUDIO_VLM_MODEL", "gemma3:4b"),
        vlm_keep_alive=os.environ.get("WONKY_STUDIO_VLM_KEEP_ALIVE", "0"),
        vlm_timeout_seconds=float(os.environ.get("WONKY_STUDIO_VLM_TIMEOUT_SECONDS", "60")),
        segmentation_provider=os.environ.get(
            "WONKY_STUDIO_SEGMENTATION_PROVIDER",
            "sam3-subprocess",
        ),
        segmentation_conda_env=os.environ.get("WONKY_STUDIO_SEGMENTATION_CONDA_ENV", "sam3"),
        segmentation_timeout_seconds=float(
            os.environ.get("WONKY_STUDIO_SEGMENTATION_TIMEOUT_SECONDS", "300")
        ),
        segmentation_max_edge=int(os.environ.get("WONKY_STUDIO_SEGMENTATION_MAX_EDGE", "960")),
        segmentation_threshold=float(os.environ.get("WONKY_STUDIO_SEGMENTATION_THRESHOLD", "0.2")),
        segmentation_dilate_pixels=int(
            os.environ.get("WONKY_STUDIO_SEGMENTATION_DILATE_PIXELS", "2")
        ),
        segmentation_blur_radius=float(
            os.environ.get("WONKY_STUDIO_SEGMENTATION_BLUR_RADIUS", "1.5")
        ),
        inventory_image_provider=os.environ.get(
            "WONKY_STUDIO_INVENTORY_IMAGE_PROVIDER",
            "comfyui",
        ),
        inventory_image_comfy_url=os.environ.get(
            "WONKY_STUDIO_INVENTORY_IMAGE_COMFY_URL",
            "http://172.24.224.1:8189",
        ),
        inventory_image_workflow_path=Path(
            os.environ.get(
                "WONKY_STUDIO_INVENTORY_IMAGE_WORKFLOW_PATH",
                str(Path(__file__).resolve().parents[2] / "temp" / "inventory-image-generator" / "inventory_item_workflow.json"),
            )
        ),
        inventory_image_input_root=Path(
            os.environ.get("WONKY_STUDIO_INVENTORY_IMAGE_INPUT_ROOT", "/mnt/d/wonky-studio/temp")
        ),
        inventory_image_comfy_input_root=os.environ.get(
            "WONKY_STUDIO_INVENTORY_IMAGE_COMFY_INPUT_ROOT",
            "D:/wonky-studio/temp",
        ),
        inventory_image_output_root=Path(
            os.environ.get(
                "WONKY_STUDIO_INVENTORY_IMAGE_OUTPUT_ROOT",
                "/mnt/d/AI/ComfyUI_windows_portable/ComfyUI/output",
            )
        ),
        inventory_image_timeout_seconds=float(
            os.environ.get("WONKY_STUDIO_INVENTORY_IMAGE_TIMEOUT_SECONDS", "300")
        ),
        scene_removal_workflow_path=Path(
            os.environ.get(
                "WONKY_STUDIO_SCENE_REMOVAL_WORKFLOW_PATH",
                str(Path(__file__).resolve().parents[2] / "temp" / "inventory-image-generator" / "remove_item_workflow.json"),
            )
        ),
        character_image_provider=os.environ.get(
            "WONKY_STUDIO_CHARACTER_IMAGE_PROVIDER",
            "comfyui",
        ),
        character_image_workflow_path=Path(
            os.environ.get(
                "WONKY_STUDIO_CHARACTER_IMAGE_WORKFLOW_PATH",
                str(Path(__file__).resolve().parents[2] / "temp" / "viseme_pose_workflow.json"),
            )
        ),
        character_image_input_root=Path(
            os.environ.get("WONKY_STUDIO_CHARACTER_IMAGE_INPUT_ROOT", "/mnt/d/wonky-studio/temp")
        ),
        character_viseme_source_root=Path(
            os.environ.get("WONKY_STUDIO_CHARACTER_VISEME_SOURCE_ROOT", "/mnt/d/wonky-studio/visemes")
        ),
        character_pose_source_root=Path(
            os.environ.get("WONKY_STUDIO_CHARACTER_POSE_SOURCE_ROOT", "/mnt/d/wonky-studio/poses")
        ),
        viseme_extraction_provider=os.environ.get(
            "WONKY_STUDIO_VISEME_EXTRACTION_PROVIDER",
            "subprocess",
        ),
        viseme_extraction_python_path=Path(
            os.environ.get(
                "WONKY_STUDIO_VISEME_EXTRACTION_PYTHON_PATH",
                "/mnt/d/wonky-studio/audio/xtts-env/Scripts/python.exe",
            )
        ),
        viseme_extraction_script_path=Path(
            os.environ.get(
                "WONKY_STUDIO_VISEME_EXTRACTION_SCRIPT_PATH",
                "/mnt/d/wonky-studio/audio/extract_visemes.py",
            )
        ),
        viseme_extraction_timeout_seconds=float(
            os.environ.get("WONKY_STUDIO_VISEME_EXTRACTION_TIMEOUT_SECONDS", "300")
        ),
    )


def _default_storage_root() -> str:
    if Path("/mnt/d").is_mount():
        return "/mnt/d/wonky-studio/uploads"
    return str(Path(__file__).resolve().parents[1] / "data" / "uploads")
