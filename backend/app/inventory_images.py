from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any, Callable, Protocol

import httpx

from .config import Settings


class InventoryImageProviderUnavailable(RuntimeError):
    pass


class InventoryImageProvider(Protocol):
    async def generate_inventory_image(
        self,
        *,
        rendered_input_path: Path,
        object_name: str,
        object_description: str,
        output_path: Path,
    ) -> None:
        ...


class ComfyUiInventoryImageProvider:
    def __init__(
        self,
        comfy_url: str,
        workflow_path: Path,
        comfy_input_root: str,
        output_root: Path,
        timeout_seconds: float,
        prompt_builder: Callable[[str, str], str],
        filename_prefix_root: str,
    ) -> None:
        self.comfy_url = comfy_url.rstrip("/")
        self.workflow_path = workflow_path
        self.comfy_input_root = comfy_input_root.rstrip("/\\")
        self.output_root = output_root
        self.timeout_seconds = timeout_seconds
        self.prompt_builder = prompt_builder
        self.filename_prefix_root = filename_prefix_root.strip("/\\")
        self.client_id = f"wonky-studio-inventory-{uuid.uuid4().hex}"
        self.workflow_template = json.loads(self.workflow_path.read_text(encoding="utf-8"))

    async def generate_inventory_image(
        self,
        *,
        rendered_input_path: Path,
        object_name: str,
        object_description: str,
        output_path: Path,
    ) -> None:
        prompt = copy.deepcopy(self.workflow_template)
        positive_node = _find_node_id(prompt, class_type="CLIPTextEncode")
        input_node = _find_node_id(prompt, class_type="LoadImage")
        output_node = _find_node_id(prompt, class_type="SaveImage")

        generated_prefix = f"{self.filename_prefix_root}/{_safe_inventory_name(object_name)}_{uuid.uuid4().hex[:10]}"
        prompt[positive_node]["inputs"]["text"] = self.prompt_builder(object_name, object_description)
        prompt[input_node]["inputs"]["image"] = _comfy_visible_input_path(
            self.comfy_input_root,
            rendered_input_path,
        )
        prompt[output_node]["inputs"]["filename_prefix"] = generated_prefix

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{self.comfy_url}/prompt",
                    json={"prompt": prompt, "client_id": self.client_id},
                )
                response.raise_for_status()
                prompt_id = response.json()["prompt_id"]
        except Exception as exc:  # noqa: BLE001
            raise InventoryImageProviderUnavailable(
                "Inventory image generator is unavailable. Please contact the administrator to turn Comfy on."
            ) from exc

        output_file = await self._wait_for_output_file(prompt_id, expected_prefix=generated_prefix)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(output_file.read_bytes())

    async def _wait_for_output_file(self, prompt_id: str, expected_prefix: str) -> Path:
        async with httpx.AsyncClient(timeout=20.0) as client:
            elapsed = 0.0
            while elapsed < self.timeout_seconds:
                try:
                    response = await client.get(f"{self.comfy_url}/history/{prompt_id}")
                    response.raise_for_status()
                    history_payload = response.json()
                except Exception as exc:  # noqa: BLE001
                    raise InventoryImageProviderUnavailable(
                        "Inventory image generator is unavailable. Please contact the administrator to turn Comfy on."
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
        raise RuntimeError("Inventory image generation timed out")


def build_inventory_image_provider(settings: Settings) -> InventoryImageProvider | None:
    provider = settings.inventory_image_provider.strip().lower()
    if provider in {"", "none", "disabled"}:
        return None
    if provider == "comfyui":
        if not settings.inventory_image_workflow_path.exists():
            raise ValueError(
                f"Inventory image workflow file was not found: {settings.inventory_image_workflow_path}"
            )
        return ComfyUiInventoryImageProvider(
            comfy_url=settings.inventory_image_comfy_url,
            workflow_path=settings.inventory_image_workflow_path,
            comfy_input_root=settings.inventory_image_comfy_input_root,
            output_root=settings.inventory_image_output_root,
            timeout_seconds=settings.inventory_image_timeout_seconds,
            prompt_builder=_inventory_prompt,
            filename_prefix_root="inventory",
        )
    raise ValueError(f"Unsupported inventory image provider: {settings.inventory_image_provider}")


def build_scene_removal_provider(settings: Settings) -> InventoryImageProvider | None:
    provider = settings.inventory_image_provider.strip().lower()
    if provider in {"", "none", "disabled"}:
        return None
    if provider == "comfyui":
        if not settings.scene_removal_workflow_path.exists():
            raise ValueError(
                f"Scene removal workflow file was not found: {settings.scene_removal_workflow_path}"
            )
        return ComfyUiInventoryImageProvider(
            comfy_url=settings.inventory_image_comfy_url,
            workflow_path=settings.scene_removal_workflow_path,
            comfy_input_root=settings.inventory_image_comfy_input_root,
            output_root=settings.inventory_image_output_root,
            timeout_seconds=settings.inventory_image_timeout_seconds,
            prompt_builder=_scene_removal_prompt,
            filename_prefix_root="scene-removals",
        )
    raise ValueError(f"Unsupported inventory image provider: {settings.inventory_image_provider}")


def _find_node_id(prompt: dict[str, Any], class_type: str) -> str:
    for node_id, node in prompt.items():
        if isinstance(node, dict) and node.get("class_type") == class_type:
            return str(node_id)
    raise ValueError(f"Workflow is missing required {class_type} node")


def _inventory_prompt(object_name: str, object_description: str) -> str:
    subject = (object_description or object_name).strip() or object_name.strip() or "object"
    return (
        f"High-quality inventory item render of this {subject}, matching a cozy handmade educational "
        "adventure game aesthetic. Object centered, front-facing or slight 3/4 view, isolated on a warm "
        "cream background. Miniature scale, tactile handcrafted realism, soft studio lighting, gentle shadows, "
        "warm color palette, slightly worn materials, charming storybook feel. Clean readable silhouette, "
        "game asset, inventory icon, high detail, no text, no labels, no extra objects, no hands, no clutter."
    )


def _scene_removal_prompt(object_name: str, object_description: str) -> str:
    subject = (object_description or object_name).strip() or object_name.strip() or "object"
    return (
        f"Please remove the {subject} from this scene, keeping everything else intact. "
        "Preserve the original composition, lighting, materials, perspective, and handcrafted storybook aesthetic. "
        "Fill in the missing background naturally and seamlessly. No new objects, no text, no labels, no framing changes."
    )


def _comfy_visible_input_path(comfy_input_root: str, rendered_input_path: Path) -> str:
    return f"{comfy_input_root}/{rendered_input_path.name}"


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
                candidate = output_root / subfolder / filename
            else:
                candidate = output_root / filename
            return candidate
    return None


def _find_generated_output(output_root: Path, expected_prefix: str) -> Path | None:
    expected = Path(expected_prefix)
    search_root = output_root / expected.parent if str(expected.parent) != "." else output_root
    pattern = f"{expected.name}*"
    candidates = sorted(search_root.glob(pattern))
    return candidates[-1] if candidates else None


def _safe_inventory_name(value: str) -> str:
    cleaned = "".join(character if character.isalnum() else "_" for character in value.strip().lower())
    return cleaned.strip("_") or "object"


async def _sleep_poll() -> None:
    import asyncio

    await asyncio.sleep(0.5)
