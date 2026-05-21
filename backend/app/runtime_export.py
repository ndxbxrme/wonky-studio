from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .database import (
    get_global_settings,
    get_scene_with_images,
    get_script_line_detail,
    list_audio_assets,
    list_game_variables,
    list_object_animations_for_object,
    list_object_masks_for_object,
    list_overlay_scene_bindings,
    list_scene_interactions,
    list_scenes,
    list_verbs,
)
from .object_rendering import render_masked_object_crop

RUNTIME_BUNDLE_FORMAT_VERSION = 2


def runtime_bundle_output_path(storage_root: Path, organization_id: str) -> Path:
    return storage_root.parent / f"wonky-runtime-{organization_id}"


def runtime_bundle_zip_output_path(storage_root: Path, organization_id: str) -> Path:
    return storage_root.parent / f"wonky-runtime-{organization_id}.zip"


def export_runtime_bundle(
    *,
    db_path: Path,
    storage_root: Path,
    script_audio_root: Path,
    organization_id: str,
    output_path: Path,
    godot_project_root: Path,
) -> dict[str, Any]:
    manifest, scene_documents, storage_asset_relative_paths, script_audio_relative_paths = _build_runtime_bundle(
        db_path=db_path,
        storage_root=storage_root,
        organization_id=organization_id,
    )
    if output_path.exists():
        shutil.rmtree(output_path)
    output_path.mkdir(parents=True, exist_ok=True)
    _copy_godot_runtime_shell(godot_project_root, output_path)
    runtime_root = output_path / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    scenes_root = runtime_root / "scenes"
    scenes_root.mkdir(parents=True, exist_ok=True)
    assets_root = runtime_root / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    (runtime_root / "runtime.json").write_text(
        json.dumps(manifest, ensure_ascii=True, separators=(",", ":")),
        encoding="utf-8",
    )

    for scene_id, scene_document in scene_documents.items():
        (scenes_root / f"{scene_id}.json").write_text(
            json.dumps(scene_document, ensure_ascii=True, separators=(",", ":")),
            encoding="utf-8",
        )

    file_count = 0
    for relative_path in sorted(storage_asset_relative_paths):
        source_path = storage_root / relative_path
        if not source_path.exists() or not source_path.is_file():
            continue
        destination_path = assets_root / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        file_count += 1
    for relative_path in sorted(script_audio_relative_paths):
        source_path = script_audio_root / relative_path
        if not source_path.exists() or not source_path.is_file():
            continue
        destination_path = assets_root / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        file_count += 1
    return {
        "format_version": RUNTIME_BUNDLE_FORMAT_VERSION,
        "scene_count": len(scene_documents),
        "script_line_count": len(manifest.get("script_lines", [])),
        "file_count": file_count,
        "output_path": str(output_path),
    }


def export_runtime_bundle_zip(
    *,
    runtime_folder_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    runtime_folder_path = runtime_folder_path.resolve()
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    archive_base = output_path.with_suffix("")
    archive_file = shutil.make_archive(
        str(archive_base),
        "zip",
        root_dir=str(runtime_folder_path.parent),
        base_dir=runtime_folder_path.name,
    )
    zip_path = Path(archive_file)
    return {
        "output_path": str(zip_path),
        "folder_path": str(runtime_folder_path),
        "file_count": sum(1 for path in runtime_folder_path.rglob("*") if path.is_file()),
        "size_bytes": zip_path.stat().st_size if zip_path.exists() else 0,
    }


def export_godot_code_files(
    *,
    output_path: Path,
    godot_project_root: Path,
) -> dict[str, Any]:
    output_path.mkdir(parents=True, exist_ok=True)
    copied_file_count = _copy_godot_runtime_shell(godot_project_root, output_path)
    return {
        "output_path": str(output_path),
        "file_count": copied_file_count,
    }


def _copy_godot_runtime_shell(godot_project_root: Path, output_path: Path) -> int:
    copied_file_count = 0
    for source_path in godot_project_root.rglob("*"):
        if source_path.name == ".gitkeep":
            continue
        relative_path = source_path.relative_to(godot_project_root)
        if relative_path.parts and relative_path.parts[0] == "runtime":
            continue
        destination_path = output_path / relative_path
        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
            continue
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        copied_file_count += 1
    return copied_file_count


def _build_runtime_bundle(
    *,
    db_path: Path,
    storage_root: Path,
    organization_id: str,
) -> tuple[dict[str, Any], dict[int, dict[str, Any]], set[str], set[str]]:
    scenes = [
        scene
        for scene in list_scenes(db_path, organization_id)
        if scene.get("presentation_mode") in {"base", "overlay"}
    ]
    global_settings = _map_global_settings_assets(get_global_settings(db_path, organization_id))
    variables = list_game_variables(db_path, organization_id)
    verbs = list_verbs(db_path, organization_id)
    overlay_bindings = list_overlay_scene_bindings(db_path, organization_id)

    scene_documents: dict[int, dict[str, Any]] = {}
    scene_refs: list[dict[str, Any]] = []
    referenced_script_line_ids: set[int] = set()
    storage_asset_relative_paths: set[str] = set()
    script_audio_relative_paths: set[str] = set()

    _collect_relative_path(storage_asset_relative_paths, global_settings.get("inventory_background_relative_path"))
    _collect_relative_path(storage_asset_relative_paths, global_settings.get("verb_tag_background_relative_path"))
    for cursor_state in (global_settings.get("cursor_states") or {}).values():
        _collect_relative_path(storage_asset_relative_paths, (cursor_state or {}).get("relative_path"))

    for scene_summary in scenes:
        scene = get_scene_with_images(db_path, int(scene_summary["id"]))
        if scene is None or scene["organization_id"] != organization_id:
            continue
        interactions = [
            interaction
            for interaction in list_scene_interactions(
                db_path,
                scene_id=scene["id"],
                organization_id=organization_id,
            )
            if interaction.get("enabled")
        ]
        scene_document = _build_runtime_scene(
            db_path=db_path,
            storage_root=storage_root,
            organization_id=organization_id,
            scene=scene,
            interactions=interactions,
            asset_relative_paths=storage_asset_relative_paths,
        )
        scene_documents[int(scene["id"])] = scene_document
        scene_refs.append(
            {
                "scene_id": scene_document["scene_id"],
                "title": scene_document["title"],
                "description": scene_document["description"],
                "presentation_mode": scene_document["presentation_mode"],
                "scene_path": f"scenes/{scene_document['scene_id']}.json",
                "width": scene_document["width"],
                "height": scene_document["height"],
                "image_count": len(scene_document.get("images", [])),
                "object_count": len(scene_document.get("objects", [])),
                "interaction_count": len(scene_document.get("interactions", [])),
            }
        )
        _collect_script_line_ids_from_steps_for_interactions(interactions, referenced_script_line_ids)

    script_line_details = [
        _map_script_line_detail(
            get_script_line_detail(db_path, organization_id, line_id),
            script_audio_relative_paths,
        )
        for line_id in sorted(referenced_script_line_ids)
    ]
    script_lines = [line for line in script_line_details if line is not None]
    referenced_audio_asset_ids = _collect_audio_asset_ids_from_scene_documents(scene_documents.values())
    audio_assets = []
    for asset in list_audio_assets(db_path, organization_id):
        if int(asset["id"]) not in referenced_audio_asset_ids:
            continue
        _collect_relative_path(storage_asset_relative_paths, asset.get("relative_path"))
        audio_assets.append(_map_audio_asset(asset))

    manifest = {
        "format_version": RUNTIME_BUNDLE_FORMAT_VERSION,
        "organization_id": organization_id,
        "exported_at": datetime.now(UTC).isoformat(),
        "global_settings": global_settings,
        "variables": variables,
        "verbs": verbs,
        "audio_assets": audio_assets,
        "overlay_bindings": overlay_bindings,
        "script_lines": script_lines,
        "scenes": scene_refs,
    }
    return manifest, scene_documents, storage_asset_relative_paths, script_audio_relative_paths


def _build_runtime_scene(
    *,
    db_path: Path,
    storage_root: Path,
    organization_id: str,
    scene: dict[str, Any],
    interactions: list[dict[str, Any]],
    asset_relative_paths: set[str],
) -> dict[str, Any]:
    scene_images = scene.get("images", [])
    frame_index_by_uploaded_file_id = {
        int(image["uploaded_file_id"]): index for index, image in enumerate(scene_images)
    }
    go_to_frame_refs, has_contextual_refs = _collect_go_to_frame_refs(interactions)
    referenced_background_frame_indices = _collect_background_frame_refs(
        interactions,
        default_frame_index=int(scene.get("background_frame_index") or 0),
        image_count=len(scene_images),
    )
    runtime_images = []
    for index, image in enumerate(scene_images):
        if index not in referenced_background_frame_indices:
            continue
        _collect_relative_path(asset_relative_paths, image.get("relative_path"))
        runtime_images.append(
            {
                "frame_index": index,
                "uploaded_file_id": image["uploaded_file_id"],
                "original_filename": image["original_filename"],
                "width": image["width"],
                "height": image["height"],
                "relative_path": image["relative_path"],
                "asset_path": _asset_export_path(image["relative_path"]),
            }
        )

    runtime_objects = []
    for scene_object in sorted(
        scene.get("objects", []),
        key=lambda item: (int(item.get("sort_order", 0) or 0), int(item.get("id", 0) or 0)),
    ):
        object_masks = list_object_masks_for_object(
            db_path,
            scene_object_id=scene_object["id"],
            organization_id=organization_id,
        )
        referenced_frame_indices = set(go_to_frame_refs.get(int(scene_object["id"]), set()))
        if has_contextual_refs:
            referenced_frame_indices.update(
                frame_index
                for frame_index, scene_image in enumerate(scene_images)
                if any(int(mask["uploaded_file_id"]) == int(scene_image["uploaded_file_id"]) for mask in object_masks)
            )
        pickup_uploaded_file_id = scene_object.get("pickup_uploaded_file_id")
        if pickup_uploaded_file_id is not None:
            pickup_frame_index = frame_index_by_uploaded_file_id.get(int(pickup_uploaded_file_id))
            if pickup_frame_index is not None:
                referenced_frame_indices.add(pickup_frame_index)

        default_render = None
        for object_mask in _preferred_object_masks(scene_object, object_masks):
            default_render = _runtime_render_payload_for_mask(
                storage_root=storage_root,
                organization_id=organization_id,
                object_mask=object_mask,
                frame_index=frame_index_by_uploaded_file_id.get(int(object_mask["uploaded_file_id"])),
                asset_relative_paths=asset_relative_paths,
            )
            if default_render is not None:
                break

        frame_renders: list[dict[str, Any]] = []
        seen_frame_indices: set[int] = set()
        for object_mask in object_masks:
            frame_index = frame_index_by_uploaded_file_id.get(int(object_mask["uploaded_file_id"]))
            if frame_index is None or frame_index not in referenced_frame_indices or frame_index in seen_frame_indices:
                continue
            render = _runtime_render_payload_for_mask(
                storage_root=storage_root,
                organization_id=organization_id,
                object_mask=object_mask,
                frame_index=frame_index,
                asset_relative_paths=asset_relative_paths,
            )
            if render is None:
                continue
            frame_renders.append(render)
            seen_frame_indices.add(frame_index)

        animations = []
        for animation in list_object_animations_for_object(
            db_path,
            scene_object_id=scene_object["id"],
            organization_id=organization_id,
        ):
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
                            render = _runtime_render_payload_for_mask(
                                storage_root=storage_root,
                                organization_id=organization_id,
                                object_mask=object_mask,
                                frame_index=frame_index,
                                asset_relative_paths=asset_relative_paths,
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

        _collect_relative_path(asset_relative_paths, scene_object.get("inventory_image_relative_path"))
        runtime_objects.append(
            {
                "id": scene_object["id"],
                "name": scene_object["name"],
                "sort_order": int(scene_object.get("sort_order", 0) or 0),
                "keyboard_target_enabled": bool(scene_object.get("keyboard_target_enabled")),
                "pickup_uploaded_file_id": scene_object.get("pickup_uploaded_file_id"),
                "inventory_image_relative_path": scene_object.get("inventory_image_relative_path"),
                "inventory_image_asset_path": _asset_export_path(scene_object.get("inventory_image_relative_path")),
                "default_uploaded_file_id": scene_object.get("default_uploaded_file_id"),
                "default_render": default_render,
                "frame_renders": frame_renders,
                "animations": animations,
            }
        )

    return {
        "scene_id": scene["id"],
        "title": scene["title"],
        "description": scene.get("description") or "",
        "presentation_mode": scene.get("presentation_mode", "base"),
        "background_frame_index": int(scene.get("background_frame_index") or 0),
        "width": int(scene_images[0]["width"]) if scene_images else 0,
        "height": int(scene_images[0]["height"]) if scene_images else 0,
        "images": runtime_images,
        "objects": runtime_objects,
        "interactions": interactions,
    }


def _runtime_render_payload_for_mask(
    *,
    storage_root: Path,
    organization_id: str,
    object_mask: dict[str, Any],
    frame_index: int | None,
    asset_relative_paths: set[str],
) -> dict[str, Any] | None:
    rendered = _ensure_runtime_render(
        storage_root=storage_root,
        organization_id=organization_id,
        object_mask=object_mask,
    )
    if rendered is None:
        return None
    _collect_relative_path(asset_relative_paths, rendered["relative_path"])
    return {
        "frame_index": frame_index,
        "uploaded_file_id": object_mask["uploaded_file_id"],
        "object_mask_id": object_mask["id"],
        "original_filename": object_mask.get("original_filename") or "",
        "left": rendered["left"],
        "top": rendered["top"],
        "width": rendered["width"],
        "height": rendered["height"],
        "relative_path": rendered["relative_path"],
        "asset_path": _asset_export_path(rendered["relative_path"]),
        "cache_key": rendered["cache_key"],
    }


def _ensure_runtime_render(
    *,
    storage_root: Path,
    organization_id: str,
    object_mask: dict[str, Any],
) -> dict[str, Any] | None:
    original_path = storage_root / object_mask["original_relative_path"]
    mask_relative_path = object_mask["soft_relative_path"] or object_mask["relative_path"]
    mask_path = storage_root / mask_relative_path
    if not original_path.exists() or not mask_path.exists():
        return None
    cache_key = _runtime_render_cache_key(object_mask, original_path, mask_path)
    output_path = (
        storage_root
        / organization_id
        / "derived"
        / "scenes"
        / str(object_mask["scene_id"])
        / "objects"
        / str(object_mask["scene_object_id"])
        / "preview"
        / f"{object_mask['uploaded_file_id']}.png"
    )
    metadata_path = output_path.with_suffix(".json")
    metadata = _read_render_metadata(metadata_path)
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
        metadata_path.write_text(json.dumps({"bbox": list(bbox), "cache_key": cache_key}), encoding="utf-8")
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
        metadata_path.write_text(json.dumps({"bbox": list(bbox), "cache_key": cache_key}), encoding="utf-8")
    left, top, right, bottom = bbox
    return {
        "relative_path": str(output_path.relative_to(storage_root)),
        "left": left,
        "top": top,
        "width": max(0, right - left),
        "height": max(0, bottom - top),
        "cache_key": cache_key,
    }


def _runtime_render_cache_key(object_mask: dict[str, Any], original_path: Path, mask_path: Path) -> str:
    return "||".join(
        [
            str(object_mask.get("updated_at") or ""),
            str(object_mask.get("prompt_text") or ""),
            str(object_mask.get("relative_path") or ""),
            str(object_mask.get("soft_relative_path") or ""),
            str(original_path.stat().st_mtime_ns if original_path.exists() else 0),
            str(mask_path.stat().st_mtime_ns if mask_path.exists() else 0),
        ]
    )


def _read_render_metadata(metadata_path: Path) -> dict[str, Any]:
    if not metadata_path.exists():
        return {}
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _preferred_object_masks(scene_object: dict[str, Any], object_masks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    default_uploaded_file_id = scene_object.get("default_uploaded_file_id")
    if default_uploaded_file_id is not None:
        prioritized = [
            object_mask
            for object_mask in object_masks
            if int(object_mask["uploaded_file_id"]) == int(default_uploaded_file_id)
        ]
        remainder = [
            object_mask
            for object_mask in object_masks
            if int(object_mask["uploaded_file_id"]) != int(default_uploaded_file_id)
        ]
        return prioritized + remainder
    return list(object_masks)


def _select_preview_mask_for_uploaded_file(
    object_masks: list[dict[str, Any]],
    *,
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
    prompt_matches = [object_mask for object_mask in candidates if object_mask.get("prompt_text") == prompt_text]
    ranked = prompt_matches or candidates
    return max(ranked, key=lambda object_mask: int(object_mask["id"]))


def _collect_go_to_frame_refs(interactions: list[dict[str, Any]]) -> tuple[dict[int, set[int]], bool]:
    refs: dict[int, set[int]] = {}
    has_contextual_refs = False
    for interaction in interactions:
        has_contextual_refs = _collect_go_to_frame_refs_from_steps(interaction.get("action_tree") or [], refs) or has_contextual_refs
    return refs, has_contextual_refs


def _collect_go_to_frame_refs_from_steps(steps: list[dict[str, Any]], refs: dict[int, set[int]]) -> bool:
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


def _collect_background_frame_refs(
    interactions: list[dict[str, Any]],
    *,
    default_frame_index: int,
    image_count: int,
) -> set[int]:
    refs = {default_frame_index} if 0 <= default_frame_index < image_count else set()
    for interaction in interactions:
        _collect_background_frame_refs_from_steps(interaction.get("action_tree") or [], refs, image_count=image_count)
    return refs


def _collect_background_frame_refs_from_steps(
    steps: list[dict[str, Any]],
    refs: set[int],
    *,
    image_count: int,
) -> None:
    for step in steps:
        if step.get("type") == "go_to_frame" and step.get("target_scope") == "background":
            try:
                frame_index = int(step.get("frame_index"))
            except (TypeError, ValueError):
                frame_index = None
            if frame_index is not None and 0 <= frame_index < image_count:
                refs.add(frame_index)
        _collect_background_frame_refs_from_steps(step.get("then_steps") or [], refs, image_count=image_count)
        _collect_background_frame_refs_from_steps(step.get("else_steps") or [], refs, image_count=image_count)


def _collect_script_line_ids_from_steps_for_interactions(
    interactions: list[dict[str, Any]],
    line_ids: set[int],
) -> None:
    for interaction in interactions:
        _collect_script_line_ids_from_steps(interaction.get("action_tree") or [], line_ids)


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


def _collect_audio_asset_ids_from_scene_documents(scene_documents: Any) -> set[int]:
    audio_asset_ids: set[int] = set()
    for scene_document in scene_documents:
        _collect_audio_asset_ids_from_steps(scene_document.get("interactions") or [], audio_asset_ids)
    return audio_asset_ids


def _collect_audio_asset_ids_from_steps(interactions_or_steps: list[dict[str, Any]], audio_asset_ids: set[int]) -> None:
    for item in interactions_or_steps:
        steps = item.get("action_tree") if "action_tree" in item else None
        if isinstance(steps, list):
            _collect_audio_asset_ids_from_steps(steps, audio_asset_ids)
            continue
        if item.get("type") in {"crossfade_bgm", "play_sfx"}:
            try:
                audio_asset_ids.add(int(item.get("audio_asset_id")))
            except (TypeError, ValueError):
                pass
        _collect_audio_asset_ids_from_steps(item.get("then_steps") or [], audio_asset_ids)
        _collect_audio_asset_ids_from_steps(item.get("else_steps") or [], audio_asset_ids)


def _map_script_line_detail(detail: dict[str, Any] | None, asset_relative_paths: set[str]) -> dict[str, Any] | None:
    if detail is None:
        return None
    mapped = dict(detail)
    mapped["audio_candidates"] = []
    for candidate in _select_runtime_audio_candidates(detail.get("audio_candidates") or []):
        _collect_relative_path(asset_relative_paths, candidate.get("relative_path"))
        mapped["audio_candidates"].append(
            {
                **candidate,
                "asset_path": _asset_export_path(candidate.get("relative_path")),
            }
        )
    return mapped


def _select_runtime_audio_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates_by_language: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        language = str(candidate.get("language") or "").strip()
        relative_path = str(candidate.get("relative_path") or "").strip()
        if not language or not relative_path:
            continue
        candidates_by_language.setdefault(language, []).append(candidate)

    selected_candidates: list[dict[str, Any]] = []
    for language in sorted(candidates_by_language):
        language_candidates = candidates_by_language[language]
        selected = next((candidate for candidate in language_candidates if candidate.get("selected")), None)
        selected_candidates.append(selected or language_candidates[0])
    return selected_candidates


def _map_audio_asset(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        **asset,
        "asset_path": _asset_export_path(asset.get("relative_path")),
    }


def _map_global_settings_assets(settings: dict[str, Any]) -> dict[str, Any]:
    mapped = dict(settings)
    mapped["inventory_background_asset_path"] = _asset_export_path(settings.get("inventory_background_relative_path"))
    mapped["verb_tag_background_asset_path"] = _asset_export_path(settings.get("verb_tag_background_relative_path"))
    mapped["cursor_states"] = {
        key: {
            **(value or {}),
            "asset_path": _asset_export_path((value or {}).get("relative_path")),
        }
        for key, value in (settings.get("cursor_states") or {}).items()
    }
    return mapped


def _asset_export_path(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    return str(Path("assets") / relative_path)


def _collect_relative_path(paths: set[str], relative_path: str | None) -> None:
    if relative_path:
        paths.add(str(relative_path))
