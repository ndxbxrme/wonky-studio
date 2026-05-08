from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops


@dataclass(frozen=True)
class RenderedObject:
    bbox: tuple[int, int, int, int]
    output_size: tuple[int, int]


def render_masked_object_crop(
    original_path: Path,
    mask_path: Path,
    output_path: Path,
    max_size: int = 256,
    threshold: int = 1,
) -> RenderedObject | None:
    with Image.open(original_path) as original_image:
        original = original_image.convert("RGBA")
        original.load()
    with Image.open(mask_path) as mask_image:
        mask = mask_image.convert("L")
        mask.load()

    if mask.size != original.size:
        mask = mask.resize(original.size, Image.Resampling.LANCZOS)

    binary_mask = mask.point(lambda value: 255 if value >= threshold else 0)
    bbox = binary_mask.getbbox()
    if bbox is None:
        return None

    object_crop = original.crop(bbox)
    alpha_crop = mask.crop(bbox)
    if object_crop.mode == "RGBA":
        alpha_crop = ImageChops.multiply(object_crop.getchannel("A"), alpha_crop)
    object_crop.putalpha(alpha_crop)

    if max_size > 0:
        object_crop.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    object_crop.save(output_path, format="PNG")
    return RenderedObject(bbox=bbox, output_size=object_crop.size)
