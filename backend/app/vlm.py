from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from .config import Settings


ALLOWED_CATEGORIES = {"furniture", "prop", "fixture", "background", "character", "other"}
CATEGORY_ALIASES = {
    "architectural": "fixture",
    "architecture": "fixture",
    "art": "background",
    "decor": "prop",
    "object": "prop",
    "textile": "prop",
}


@dataclass(frozen=True)
class SceneDraftObject:
    name: str
    category: str
    description: str


@dataclass(frozen=True)
class SceneDraft:
    scene_description: str
    scene_key: str
    objects: list[SceneDraftObject]


class SceneVlmProvider(Protocol):
    async def analyze_scene(self, image_path: Path) -> SceneDraft:
        ...


class OllamaSceneVlmProvider:
    def __init__(self, base_url: str, model: str, timeout_seconds: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def analyze_scene(self, image_path: Path) -> SceneDraft:
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload = {
            "model": self.model,
            "prompt": _scene_analysis_prompt(),
            "images": [image_b64],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(f"{self.base_url}/api/generate", json=payload)
            response.raise_for_status()

        raw_response = response.json().get("response")
        if not isinstance(raw_response, str):
            raise ValueError("Ollama response did not include a text response")

        return parse_scene_draft(raw_response)


def build_scene_vlm_provider(settings: Settings) -> SceneVlmProvider | None:
    provider = settings.vlm_provider.strip().lower()
    if provider in {"", "none", "disabled"}:
        return None
    if provider == "ollama":
        return OllamaSceneVlmProvider(
            base_url=settings.vlm_base_url,
            model=settings.vlm_model,
            timeout_seconds=settings.vlm_timeout_seconds,
        )
    raise ValueError(f"Unsupported VLM provider: {settings.vlm_provider}")


def parse_scene_draft(raw_response: str) -> SceneDraft:
    payload = _loads_json_response(raw_response)
    if not isinstance(payload, dict):
        raise ValueError("VLM response must be a JSON object")

    raw_objects = payload.get("objects", [])
    objects = []
    if isinstance(raw_objects, list):
        for raw_object in raw_objects[:24]:
            if not isinstance(raw_object, dict):
                continue
            name = _clean_text(raw_object.get("name"), max_length=120)
            if not name:
                continue
            objects.append(
                SceneDraftObject(
                    name=_normalize_name(name),
                    category=_normalize_category(raw_object.get("category")),
                    description=_clean_text(raw_object.get("description"), max_length=500),
                )
            )

    return SceneDraft(
        scene_description=_clean_text(payload.get("scene_description"), max_length=500),
        scene_key=_normalize_scene_key(payload.get("scene_key")),
        objects=objects,
    )


def scene_draft_to_dict(draft: SceneDraft) -> dict[str, Any]:
    return {
        "scene_description": draft.scene_description,
        "scene_key": draft.scene_key,
        "objects": [
            {
                "name": scene_object.name,
                "category": scene_object.category,
                "description": scene_object.description,
            }
            for scene_object in draft.objects
        ],
    }


def _scene_analysis_prompt() -> str:
    return (
        "You are helping catalog assets for a point-and-click adventure game. "
        "Analyze this image and return only JSON with keys scene_description, scene_key, "
        "and objects. scene_description must be one short sentence. scene_key must be a "
        "short stable snake_case name. objects must be an array of visible separable "
        "objects useful for cleanup, with name, category, and description. category must "
        "be one of furniture, prop, fixture, background, character, other. Keep objects "
        "to 16 or fewer. Do not include markdown."
    )


def _loads_json_response(raw_response: str) -> Any:
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return json.loads(cleaned)


def _clean_text(value: Any, max_length: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())[:max_length]


def _normalize_name(value: str) -> str:
    return " ".join(value.replace("_", " ").strip().lower().split())


def _normalize_scene_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = "_".join(value.replace("-", "_").strip().lower().split())
    return "".join(character for character in normalized if character.isalnum() or character == "_")[
        :80
    ]


def _normalize_category(value: Any) -> str:
    if not isinstance(value, str):
        return "other"
    category = value.strip().lower().replace(" ", "_")
    category = CATEGORY_ALIASES.get(category, category)
    return category if category in ALLOWED_CATEGORIES else "other"
