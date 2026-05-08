from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .database import (
    add_scene_image,
    create_scene,
    get_scene_with_images,
    list_scene_image_hashes,
    list_uploaded_image_files_for_batch,
)


HASH_DISTANCE_THRESHOLD = 8


@dataclass(frozen=True)
class ImageFingerprint:
    perceptual_hash: str
    width: int
    height: int


def process_upload_batch_into_scene(
    db_path: Path,
    storage_root: Path,
    batch_id: int,
    organization_id: str,
    user_id: int,
) -> dict[str, Any]:
    uploaded_files = list_uploaded_image_files_for_batch(
        db_path,
        batch_id=batch_id,
        organization_id=organization_id,
    )
    if not uploaded_files:
        raise ValueError("Batch does not contain any supported image files")

    fingerprints = []
    for uploaded_file in uploaded_files:
        image_path = storage_root / uploaded_file["relative_path"]
        if not image_path.exists():
            raise FileNotFoundError(f"Uploaded image file is missing: {image_path}")
        fingerprints.append((uploaded_file, fingerprint_image(image_path)))

    scene_id = find_matching_scene_id(
        db_path,
        organization_id=organization_id,
        fingerprints=[fingerprint for _, fingerprint in fingerprints],
    )
    created = False
    if scene_id is None:
        first_file, first_fingerprint = fingerprints[0]
        scene = create_scene(
            db_path,
            organization_id=organization_id,
            created_by_user_id=user_id,
            representative_uploaded_file_id=first_file["id"],
            representative_hash=first_fingerprint.perceptual_hash,
            title=f"Draft scene from batch {batch_id}",
            description="Draft scene awaiting visual description.",
        )
        scene_id = scene["id"]
        created = True

    for uploaded_file, fingerprint in fingerprints:
        add_scene_image(
            db_path,
            scene_id=scene_id,
            uploaded_file_id=uploaded_file["id"],
            perceptual_hash=fingerprint.perceptual_hash,
            width=fingerprint.width,
            height=fingerprint.height,
        )

    scene = get_scene_with_images(db_path, scene_id)
    if scene is None:
        raise RuntimeError("Processed scene could not be loaded")

    return {
        "scene": scene,
        "created": created,
        "matched_existing": not created,
        "processed_file_count": len(fingerprints),
    }


def fingerprint_image(image_path: Path) -> ImageFingerprint:
    with Image.open(image_path) as image:
        width, height = image.size
        perceptual_hash = difference_hash(image)
    return ImageFingerprint(
        perceptual_hash=perceptual_hash,
        width=width,
        height=height,
    )


def difference_hash(image: Image.Image) -> str:
    resized = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(resized.getdata())
    bits = []
    for y in range(8):
        row = pixels[y * 9 : (y + 1) * 9]
        bits.extend("1" if row[x] > row[x + 1] else "0" for x in range(8))
    return f"{int(''.join(bits), 2):016x}"


def find_matching_scene_id(
    db_path: Path,
    organization_id: str,
    fingerprints: list[ImageFingerprint],
) -> int | None:
    existing_hashes = list_scene_image_hashes(db_path, organization_id)
    best_scene_id = None
    best_distance = HASH_DISTANCE_THRESHOLD + 1

    for fingerprint in fingerprints:
        for existing in existing_hashes:
            if existing["width"] != fingerprint.width or existing["height"] != fingerprint.height:
                continue
            distance = hamming_distance(existing["perceptual_hash"], fingerprint.perceptual_hash)
            if distance < best_distance:
                best_distance = distance
                best_scene_id = existing["scene_id"]

    if best_distance <= HASH_DISTANCE_THRESHOLD:
        return best_scene_id
    return None


def hamming_distance(left_hash: str, right_hash: str) -> int:
    return (int(left_hash, 16) ^ int(right_hash, 16)).bit_count()

