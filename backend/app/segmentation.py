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
        self.python_command = _resolve_env_python_command(conda_env)

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
            *self.python_command,
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
            env=_conda_subprocess_env(),
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

    async def open_worker_session(self) -> "Sam3WorkerSession":
        command = [
            *self.python_command,
            str(self.script_path),
            "--worker",
            "--max-edge",
            str(self.max_edge),
            "--threshold",
            str(self.threshold),
            "--dilate",
            str(self.dilate_pixels),
            "--blur",
            str(self.blur_radius),
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_conda_subprocess_env(),
        )
        session = Sam3WorkerSession(
            process=process,
            timeout_seconds=self.timeout_seconds,
        )
        await session.wait_until_ready()
        return session


@dataclass
class Sam3WorkerSession:
    process: asyncio.subprocess.Process
    timeout_seconds: float

    async def wait_until_ready(self) -> None:
        while True:
            line = await asyncio.wait_for(self.process.stdout.readline(), timeout=self.timeout_seconds)
            if not line:
                stdout_tail = await self._read_stdout_tail()
                stderr = await self._read_stderr()
                raise RuntimeError(
                    stderr
                    or stdout_tail
                    or "Segmentation worker exited before becoming ready"
                )
            payload = _parse_json_line(line)
            if payload.get("event") == "worker_ready":
                return

    async def extract_masks(
        self,
        image_path: Path,
        prompts: list[str],
        output_dir: Path,
        *,
        max_edge: int,
        threshold: float,
        dilate: int,
        blur: float,
    ) -> list[SegmentationPromptResult]:
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("Segmentation worker is not available")
        output_dir.mkdir(parents=True, exist_ok=True)
        request = {
            "image": str(image_path),
            "prompts": prompts,
            "output_dir": str(output_dir),
            "max_edge": max_edge,
            "threshold": threshold,
            "dilate": dilate,
            "blur": blur,
        }
        self.process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        await self.process.stdin.drain()
        while True:
            line = await asyncio.wait_for(self.process.stdout.readline(), timeout=self.timeout_seconds)
            if not line:
                stdout_tail = await self._read_stdout_tail()
                stderr = await self._read_stderr()
                raise RuntimeError(stderr or stdout_tail or "Segmentation worker exited unexpectedly")
            payload = _parse_json_line(line)
            event = payload.get("event")
            if event == "result":
                result = payload.get("result")
                if not isinstance(result, dict):
                    return []
                return _segmentation_results_from_image_summary(result)
            if event == "error":
                raise RuntimeError(str(payload.get("error") or "Segmentation failed"))

    async def close(self) -> None:
        if self.process.stdin is not None and self.process.returncode is None:
            try:
                self.process.stdin.write((json.dumps({"event": "shutdown"}) + "\n").encode("utf-8"))
                await self.process.stdin.drain()
            except Exception:
                pass
        if self.process.returncode is None:
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()

    async def _read_stderr(self) -> str:
        if self.process.stderr is None:
            return ""
        try:
            data = await asyncio.wait_for(self.process.stderr.read(), timeout=0.5)
        except TimeoutError:
            return ""
        return data.decode("utf-8", errors="replace").strip()

    async def _read_stdout_tail(self) -> str:
        if self.process.stdout is None:
            return ""
        try:
            data = await asyncio.wait_for(self.process.stdout.read(), timeout=0.2)
        except TimeoutError:
            return ""
        return data.decode("utf-8", errors="replace").strip()


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


def parse_segmentation_batch_summary(raw_json: str) -> dict[Path, list[SegmentationPromptResult]]:
    payload = json.loads(raw_json)
    images = payload.get("images")
    if not isinstance(images, list):
        return {}
    results_by_image: dict[Path, list[SegmentationPromptResult]] = {}
    for image_summary in images:
        if not isinstance(image_summary, dict):
            continue
        image_path = image_summary.get("image")
        if not isinstance(image_path, str) or not image_path.strip():
            continue
        prompt_results = []
        for raw_result in image_summary.get("results", []):
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
            prompt_results.append(
                SegmentationPromptResult(prompt=prompt.strip().lower(), candidates=candidates)
            )
        results_by_image[Path(image_path).resolve()] = prompt_results
    return results_by_image


def _segmentation_results_from_image_summary(image_summary: dict[str, Any]) -> list[SegmentationPromptResult]:
    prompt_results = []
    for raw_result in image_summary.get("results", []):
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
        prompt_results.append(
            SegmentationPromptResult(prompt=prompt.strip().lower(), candidates=candidates)
        )
    return prompt_results


def _parse_json_line(raw_line: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw_line.decode("utf-8", errors="replace").strip())
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


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


def _conda_subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH"):
        env.pop(key, None)
    env["PATH"] = os.pathsep.join(
        path
        for path in env.get("PATH", "").split(os.pathsep)
        if path and "wonky-studio/backend/.venv/bin" not in path
    )
    env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    return env


def _resolve_env_python_command(conda_env: str) -> list[str]:
    home = Path.home()
    candidates = [
        home / "miniforge3" / "envs" / conda_env / "bin" / "python",
        home / "mambaforge" / "envs" / conda_env / "bin" / "python",
        home / "anaconda3" / "envs" / conda_env / "bin" / "python",
        home / "miniconda3" / "envs" / conda_env / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return [str(candidate)]
    return ["conda", "run", "-n", conda_env, "python"]
