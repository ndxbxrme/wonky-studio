from __future__ import annotations

import copy
import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Protocol

import httpx

from .config import Settings


class CharacterImageProviderUnavailable(RuntimeError):
    pass


class VisemeExtractionProviderUnavailable(RuntimeError):
    pass


class CharacterImageProvider(Protocol):
    async def generate_variants(
        self,
        *,
        base_image_path: Path,
        source_folder: Path,
        prompt_text: str,
        output_root: Path,
        filename_prefix_root: str,
    ) -> list[tuple[Path, Path]]:
        ...


class VisemeExtractionProvider(Protocol):
    async def extract_visemes(
        self,
        *,
        audio_path: Path,
        language: str,
        text: str,
    ) -> list[dict[str, Any]]:
        ...


class ComfyUiCharacterImageProvider:
    def __init__(
        self,
        *,
        comfy_url: str,
        workflow_path: Path,
        input_root: Path,
        comfy_input_root: str,
        output_root: Path,
        timeout_seconds: float,
        base_node_id: str,
        prompt_node_id: str,
        pose_node_id: str,
    ) -> None:
        self.comfy_url = comfy_url.rstrip("/")
        self.workflow_path = workflow_path
        self.input_root = input_root
        self.comfy_input_root = comfy_input_root.rstrip("/\\")
        self.output_root = output_root
        self.timeout_seconds = timeout_seconds
        self.base_node_id = base_node_id
        self.prompt_node_id = prompt_node_id
        self.pose_node_id = pose_node_id
        self.client_id = f"wonky-studio-character-{uuid.uuid4().hex}"
        self.workflow_template = json.loads(self.workflow_path.read_text(encoding="utf-8"))

    async def generate_variants(
        self,
        *,
        base_image_path: Path,
        source_folder: Path,
        prompt_text: str,
        output_root: Path,
        filename_prefix_root: str,
    ) -> list[tuple[Path, Path]]:
        if not base_image_path.exists():
            raise FileNotFoundError(f"Character base image not found: {base_image_path}")
        if not source_folder.exists() or not source_folder.is_dir():
            raise FileNotFoundError(f"Source folder not found: {source_folder}")
        output_root.mkdir(parents=True, exist_ok=True)
        self.input_root.mkdir(parents=True, exist_ok=True)
        results: list[tuple[Path, Path]] = []
        staged_base_path = _stage_comfy_input_file(
            input_root=self.input_root,
            source_path=base_image_path,
            label="base",
        )
        for source_path in sorted(source_folder.iterdir()):
            if not source_path.is_file() or source_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            staged_source_path = _stage_comfy_input_file(
                input_root=self.input_root,
                source_path=source_path,
                label=source_path.stem,
            )
            generated_prefix = f"{filename_prefix_root}/{source_path.stem}_{uuid.uuid4().hex[:10]}"
            workflow = copy.deepcopy(self.workflow_template)
            workflow[str(self.base_node_id)]["inputs"]["image"] = _comfy_visible_input_path(
                self.comfy_input_root,
                staged_base_path,
            )
            workflow[str(self.pose_node_id)]["inputs"]["image"] = _comfy_visible_input_path(
                self.comfy_input_root,
                staged_source_path,
            )
            workflow[str(self.prompt_node_id)]["inputs"]["text"] = prompt_text
            save_node_id = _find_save_node_id(workflow)
            workflow[save_node_id]["inputs"]["filename_prefix"] = generated_prefix
            prompt_id = await self._queue_prompt(workflow)
            generated_output = await self._wait_for_output_file(prompt_id, generated_prefix)
            destination_path = output_root / source_path.name
            destination_path.write_bytes(generated_output.read_bytes())
            results.append((source_path, destination_path))
        return results

    async def _queue_prompt(self, workflow: dict[str, Any]) -> str:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{self.comfy_url}/prompt",
                    json={"prompt": workflow, "client_id": self.client_id},
                )
                response.raise_for_status()
                return str(response.json()["prompt_id"])
        except Exception as exc:  # noqa: BLE001
            raise CharacterImageProviderUnavailable(
                "Character image generation is unavailable. Please make sure ComfyUI is running."
            ) from exc

    async def _wait_for_output_file(self, prompt_id: str, expected_prefix: str) -> Path:
        elapsed = 0.0
        async with httpx.AsyncClient(timeout=20.0) as client:
            while elapsed < self.timeout_seconds:
                try:
                    response = await client.get(f"{self.comfy_url}/history/{prompt_id}")
                    response.raise_for_status()
                    history_payload = response.json()
                except Exception as exc:  # noqa: BLE001
                    raise CharacterImageProviderUnavailable(
                        "Character image generation is unavailable. Please make sure ComfyUI is running."
                    ) from exc
                history_item = history_payload.get(prompt_id) if isinstance(history_payload, dict) else None
                image_path = _extract_history_image_path(self.output_root, history_item)
                if image_path is not None and image_path.exists():
                    return image_path
                fallback = _find_generated_output(self.output_root, expected_prefix)
                if fallback is not None:
                    return fallback
                await _sleep_poll()
                elapsed += 0.5
        raise RuntimeError("Character image generation timed out")


class SubprocessVisemeExtractionProvider:
    def __init__(self, *, python_path: Path, script_path: Path, timeout_seconds: float) -> None:
        self.python_path = python_path
        self.script_path = script_path
        self.timeout_seconds = timeout_seconds

    async def extract_visemes(self, *, audio_path: Path, language: str, text: str) -> list[dict[str, Any]]:
        if not self.python_path.exists():
            raise VisemeExtractionProviderUnavailable(f"Viseme extractor Python was not found: {self.python_path}")
        if not self.script_path.exists():
            raise VisemeExtractionProviderUnavailable(f"Viseme extractor script was not found: {self.script_path}")
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        cleaned_text = text.strip()
        if not cleaned_text:
            raise RuntimeError("Viseme extraction needs transcript text")
        python_path = str(self.python_path)
        script_path = _subprocess_visible_path(self.python_path, self.script_path)
        visible_audio_path = _subprocess_visible_path(self.python_path, audio_path)
        try:
            completed = subprocess.run(
                [
                    python_path,
                    script_path,
                    visible_audio_path,
                    "--language",
                    language.strip().lower(),
                    "--text",
                    cleaned_text,
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Viseme extraction timed out") from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or "Viseme extraction failed"
            raise RuntimeError(detail) from exc
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Viseme extraction returned invalid JSON") from exc
        if not isinstance(payload, list):
            raise RuntimeError("Viseme extraction did not return a list of events")
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                continue
            viseme_key = str(item.get("viseme_key") or item.get("viseme") or "").strip()
            if not viseme_key:
                continue
            start_seconds = float(item.get("start_seconds") or item.get("start") or 0)
            end_seconds = float(item.get("end_seconds") or item.get("end") or start_seconds)
            normalized.append(
                {
                    "viseme_key": viseme_key,
                    "start_seconds": max(0.0, start_seconds),
                    "end_seconds": max(start_seconds, end_seconds),
                    "sort_order": index,
                }
            )
        return normalized


def build_character_image_provider(settings: Settings) -> CharacterImageProvider | None:
    provider = settings.character_image_provider.strip().lower()
    if provider in {"", "none", "disabled"}:
        return None
    if provider == "comfyui":
        if not settings.character_image_workflow_path.exists():
            raise ValueError(f"Character image workflow file was not found: {settings.character_image_workflow_path}")
        return ComfyUiCharacterImageProvider(
            comfy_url=settings.inventory_image_comfy_url,
            workflow_path=settings.character_image_workflow_path,
            input_root=settings.character_image_input_root,
            comfy_input_root=settings.inventory_image_comfy_input_root,
            output_root=settings.inventory_image_output_root,
            timeout_seconds=settings.inventory_image_timeout_seconds,
            base_node_id="18",
            prompt_node_id="21",
            pose_node_id="22",
        )
    raise ValueError(f"Unsupported character image provider: {settings.character_image_provider}")


def build_viseme_extraction_provider(settings: Settings) -> VisemeExtractionProvider | None:
    provider = settings.viseme_extraction_provider.strip().lower()
    if provider in {"", "none", "disabled"}:
        return None
    if provider == "subprocess":
        return SubprocessVisemeExtractionProvider(
            python_path=settings.viseme_extraction_python_path,
            script_path=settings.viseme_extraction_script_path,
            timeout_seconds=settings.viseme_extraction_timeout_seconds,
        )
    raise ValueError(f"Unsupported viseme extraction provider: {settings.viseme_extraction_provider}")


def _comfy_visible_input_path(comfy_input_root: str, input_path: Path) -> str:
    return f"{comfy_input_root}/{input_path.name}"


def _stage_comfy_input_file(*, input_root: Path, source_path: Path, label: str) -> Path:
    safe_label = "".join(character if character.isalnum() else "_" for character in label.strip().lower()).strip("_")
    staged_name = f"{uuid.uuid4().hex}-{safe_label or 'input'}{source_path.suffix.lower()}"
    staged_path = input_root / staged_name
    shutil.copy2(source_path, staged_path)
    return staged_path


def _subprocess_visible_path(python_path: Path, target_path: Path) -> str:
    target = str(target_path)
    if python_path.suffix.lower() != ".exe":
        return target
    parts = target_path.parts
    if len(parts) >= 3 and parts[0] == "/" and parts[1] == "mnt" and len(parts[2]) == 1:
        drive = parts[2].upper()
        remainder = "/".join(parts[3:])
        if remainder:
            return f"{drive}:/{remainder}"
        return f"{drive}:/"
    return target.replace("\\", "/")


def _extract_history_image_path(output_root: Path, history_item: Any) -> Path | None:
    if not isinstance(history_item, dict):
        return None
    outputs = history_item.get("outputs")
    if not isinstance(outputs, dict):
        return None
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        images = node_output.get("images")
        if not isinstance(images, list):
            continue
        for image in images:
            if not isinstance(image, dict):
                continue
            filename = image.get("filename")
            if not isinstance(filename, str) or not filename:
                continue
            subfolder = image.get("subfolder")
            if isinstance(subfolder, str) and subfolder.strip():
                return output_root / subfolder / filename
            return output_root / filename
    return None


def _find_generated_output(output_root: Path, expected_prefix: str) -> Path | None:
    expected = Path(expected_prefix)
    search_root = output_root / expected.parent if str(expected.parent) != "." else output_root
    pattern = f"{expected.name}*"
    candidates = sorted(search_root.glob(pattern))
    return candidates[-1] if candidates else None


def _find_save_node_id(prompt: dict[str, Any]) -> str:
    for node_id, node in prompt.items():
        if isinstance(node, dict) and node.get("class_type") == "SaveImage":
            return str(node_id)
    raise ValueError("Workflow is missing required SaveImage node")


async def _sleep_poll() -> None:
    import asyncio

    await asyncio.sleep(0.5)
