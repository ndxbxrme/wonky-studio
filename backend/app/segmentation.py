from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import Settings


@dataclass(frozen=True)
class SegmentationCandidate:
    raw_path: Path
    soft_path: Path | None
    bbox: list[float] | None
    score: float | None


@dataclass(frozen=True)
class SegmentationPromptResult:
    prompt: str
    candidates: list[SegmentationCandidate]


class SegmentationProvider(Protocol):
    async def extract_masks(
        self,
        image_path: Path,
        prompts: list[str],
        output_dir: Path,
    ) -> list[SegmentationPromptResult]:
        ...


class Sam3SubprocessSegmentationProvider:
    def __init__(
        self,
        conda_env: str,
        timeout_seconds: float,
        max_edge: int,
        threshold: float,
        dilate_pixels: int,
        blur_radius: float,
        script_path: Path | None = None,
    ) -> None:
        self.conda_env = conda_env
        self.timeout_seconds = timeout_seconds
        self.max_edge = max_edge
        self.threshold = threshold
        self.dilate_pixels = dilate_pixels
        self.blur_radius = blur_radius
        self.script_path = script_path or Path(__file__).resolve().parents[2] / "tools" / "sam3_smoke.py"

    async def extract_masks(
        self,
        image_path: Path,
        prompts: list[str],
        output_dir: Path,
    ) -> list[SegmentationPromptResult]:
        if not prompts:
            return []
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_path = output_dir / "summary.json"
        command = [
            "conda",
            "run",
            "-n",
            self.conda_env,
            "python",
            str(self.script_path),
            "--image",
            str(image_path),
            "--output-dir",
            str(output_dir),
            "--max-edge",
            str(self.max_edge),
            "--threshold",
            str(self.threshold),
            "--dilate",
            str(self.dilate_pixels),
            "--blur",
            str(self.blur_radius),
            "--summary-file",
            str(summary_path),
        ]
        for prompt in prompts:
            command.extend(["--prompt", prompt])

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"},
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise RuntimeError("Segmentation timed out") from exc

        if process.returncode != 0:
            error_output = stderr.decode("utf-8", errors="replace").strip()
            standard_output = stdout.decode("utf-8", errors="replace").strip()
            raise RuntimeError(error_output or standard_output or "Segmentation failed")
        if not summary_path.exists():
            raise RuntimeError("Segmentation did not write a summary file")

        return parse_segmentation_summary(summary_path.read_text(encoding="utf-8"))


def build_segmentation_provider(settings: Settings) -> SegmentationProvider | None:
    provider = settings.segmentation_provider.strip().lower()
    if provider in {"", "none", "disabled"}:
        return None
    if provider == "sam3-subprocess":
        return Sam3SubprocessSegmentationProvider(
            conda_env=settings.segmentation_conda_env,
            timeout_seconds=settings.segmentation_timeout_seconds,
            max_edge=settings.segmentation_max_edge,
            threshold=settings.segmentation_threshold,
            dilate_pixels=settings.segmentation_dilate_pixels,
            blur_radius=settings.segmentation_blur_radius,
        )
    raise ValueError(f"Unsupported segmentation provider: {settings.segmentation_provider}")


def parse_segmentation_summary(raw_json: str) -> list[SegmentationPromptResult]:
    payload = json.loads(raw_json)
    results = []
    for raw_result in payload.get("results", []):
        prompt = raw_result.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            continue
        boxes = raw_result.get("boxes", [])
        scores = raw_result.get("scores", [])
        candidates = []
        for index, raw_mask in enumerate(raw_result.get("written_masks", [])):
            if not isinstance(raw_mask, dict) or not raw_mask.get("raw"):
                continue
            candidates.append(
                SegmentationCandidate(
                    raw_path=Path(raw_mask["raw"]),
                    soft_path=Path(raw_mask["soft"]) if raw_mask.get("soft") else None,
                    bbox=_coerce_bbox(boxes[index] if index < len(boxes) else None),
                    score=_coerce_score(scores[index] if index < len(scores) else None),
                )
            )
        results.append(SegmentationPromptResult(prompt=prompt.strip().lower(), candidates=candidates))
    return results


def _coerce_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None


def _coerce_score(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
