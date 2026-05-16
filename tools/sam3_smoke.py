from __future__ import annotations

import argparse
import json
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageFilter
from sam3.model.sam3_image_processor import Sam3Processor
from sam3.model_builder import build_sam3_image_model


DEFAULT_GLOBS = ("*.jpg", "*.jpeg", "*.png", "*.webp")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SAM3 image segmentation with single-image or batch input.")
    parser.add_argument("--worker", action="store_true", help="Run as a persistent JSON-line worker.")
    parser.add_argument("--image", action="append", dest="images", type=Path, help="Process one image. Repeat to process multiple images in one run.")
    parser.add_argument("--input-dir", type=Path, help="Process all supported images in a directory.")
    parser.add_argument("--glob", action="append", dest="globs", help="Filename pattern(s) to use with --input-dir. Defaults to common image suffixes.")
    parser.add_argument(
        "--output-dir",
        default=Path("/mnt/d/wonky-studio/sam3-smoke"),
        type=Path,
        help="Output directory. For best throughput under WSL, prefer a Linux filesystem path such as /tmp/sam3-output.",
    )
    parser.add_argument("--prompt", action="append", dest="prompts")
    parser.add_argument("--max-edge", default=960, type=int)
    parser.add_argument("--threshold", default=0.35, type=float)
    parser.add_argument("--amp-dtype", choices=["float16", "bfloat16", "off"], default="float16")
    parser.add_argument("--dilate", default=0, type=int)
    parser.add_argument("--blur", default=0.0, type=float)
    parser.add_argument("--summary-file", type=Path)
    parser.add_argument("--compile", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    if not args.worker:
        if not args.images and args.input_dir is None:
            parser.error("one of --image or --input-dir is required")
        if args.images and args.input_dir is not None:
            parser.error("use either --image or --input-dir, not both")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    amp_dtype = resolve_amp_dtype(args.amp_dtype, device)
    if device == "cuda":
        torch.backends.cudnn.benchmark = True

    print(
        json.dumps(
            {
                "event": "starting",
                "image_count": 0 if args.worker else None,
                "device": device,
                "amp_dtype": args.amp_dtype,
                "compile": bool(args.compile),
                "worker": bool(args.worker),
            }
        ),
        flush=True,
    )

    model = build_sam3_image_model(compile=args.compile).to(device).eval()
    processor = Sam3Processor(model, confidence_threshold=args.threshold)

    if args.worker:
        run_worker(processor=processor, device=device, amp_dtype=amp_dtype)
        return

    prompts = args.prompts or ["bed"]
    image_paths = collect_image_paths(images=args.images or [], input_dir=args.input_dir, globs=args.globs or [])
    if args.limit is not None and args.limit >= 0:
        image_paths = image_paths[: args.limit]
    if not image_paths:
        raise SystemExit("No input images matched")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    multi_image = len(image_paths) > 1 or args.input_dir is not None

    image_summaries = []
    for index, image_path in enumerate(image_paths, start=1):
        started_at = time.perf_counter()
        try:
            image_summary = process_image(
                image_path=image_path,
                output_dir=output_dir_for_image(args.output_dir, image_path, multi_image=multi_image),
                prompts=prompts,
                max_edge=args.max_edge,
                threshold=args.threshold,
                dilate=args.dilate,
                blur=args.blur,
                processor=processor,
                device=device,
                amp_dtype=amp_dtype,
            )
            elapsed_seconds = round(time.perf_counter() - started_at, 3)
            image_summary["elapsed_seconds"] = elapsed_seconds
            image_summaries.append(image_summary)
            print(
                json.dumps(
                    {
                        "event": "image_complete",
                        "index": index,
                        "total": len(image_paths),
                        "image": str(image_path),
                        "elapsed_seconds": elapsed_seconds,
                    }
                ),
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed_seconds = round(time.perf_counter() - started_at, 3)
            image_summaries.append(
                {
                    "image": str(image_path),
                    "error": str(exc),
                    "elapsed_seconds": elapsed_seconds,
                    "results": [],
                }
            )
            print(
                json.dumps(
                    {
                        "event": "image_failed",
                        "index": index,
                        "total": len(image_paths),
                        "image": str(image_path),
                        "elapsed_seconds": elapsed_seconds,
                        "error": str(exc),
                    }
                ),
                flush=True,
            )

    summary = build_summary(image_summaries, multi_image=multi_image)
    if args.summary_file:
        args.summary_file.parent.mkdir(parents=True, exist_ok=True)
        args.summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


def run_worker(*, processor: Sam3Processor, device: str, amp_dtype: torch.dtype | None) -> None:
    print(json.dumps({"event": "worker_ready"}), flush=True)
    while True:
        try:
            raw_line = input()
        except EOFError:
            break
        if not raw_line.strip():
            break
        request = json.loads(raw_line)
        if request.get("event") == "shutdown":
            print(json.dumps({"event": "worker_shutdown"}), flush=True)
            break
        image_path = Path(request["image"])
        prompts = [str(prompt) for prompt in request.get("prompts") or ["bed"]]
        output_dir = Path(request["output_dir"])
        try:
            result = process_image(
                image_path=image_path,
                output_dir=output_dir,
                prompts=prompts,
                max_edge=int(request.get("max_edge", 960)),
                threshold=float(request.get("threshold", 0.35)),
                dilate=int(request.get("dilate", 0)),
                blur=float(request.get("blur", 0.0)),
                processor=processor,
                device=device,
                amp_dtype=amp_dtype,
            )
            print(json.dumps({"event": "result", "image": str(image_path), "result": result}), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(
                json.dumps({"event": "error", "image": str(image_path), "error": str(exc), "results": []}),
                flush=True,
            )


def collect_image_paths(images: list[Path], input_dir: Path | None, globs: list[str]) -> list[Path]:
    if images:
        return [image.resolve() for image in images]
    if input_dir is None:
        return []
    patterns = tuple(globs) if globs else DEFAULT_GLOBS
    candidates: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for image_path in sorted(input_dir.glob(pattern)):
            resolved = image_path.resolve()
            if resolved in seen or not image_path.is_file():
                continue
            seen.add(resolved)
            candidates.append(resolved)
    return candidates


def resolve_amp_dtype(amp_dtype: str, device: str) -> torch.dtype | None:
    if device != "cuda" or amp_dtype == "off":
        return None
    if amp_dtype == "bfloat16":
        return torch.bfloat16
    return torch.float16


def output_dir_for_image(root: Path, image_path: Path, multi_image: bool) -> Path:
    if not multi_image:
        root.mkdir(parents=True, exist_ok=True)
        return root
    output_dir = root / image_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def process_image(
    *,
    image_path: Path,
    output_dir: Path,
    prompts: list[str],
    max_edge: int,
    threshold: float,
    dilate: int,
    blur: float,
    processor: Sam3Processor,
    device: str,
    amp_dtype: torch.dtype | None,
) -> dict[str, object]:
    image = Image.open(image_path).convert("RGB")
    original_size = image.size
    if max(image.size) > max_edge:
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    print(
        json.dumps(
            {
                "event": "starting_image",
                "image": str(image_path),
                "original_size": original_size,
                "inference_size": image.size,
                "prompts": prompts,
            }
        ),
        flush=True,
    )

    with inference_context(device=device, amp_dtype=amp_dtype):
        state = processor.set_image(image)

    results = []
    for prompt in prompts:
        processor.reset_all_prompts(state)
        with inference_context(device=device, amp_dtype=amp_dtype):
            output = processor.set_text_prompt(state=state, prompt=prompt)

        masks = output["masks"].detach()
        boxes = output["boxes"].detach()
        scores = output["scores"].detach()
        if masks.ndim == 4:
            masks = masks[:, 0]
        keep = scores >= threshold
        masks = masks[keep]
        boxes = boxes[keep]
        scores = scores[keep]

        masks_cpu = masks.cpu()
        boxes_list = boxes.cpu().tolist()
        scores_list = scores.cpu().tolist()
        written_masks = []
        for index, mask in enumerate(masks_cpu):
            prompt_slug = prompt.replace(" ", "_")
            mask_image = Image.fromarray(mask.numpy().astype(np.uint8) * 255, mode="L")
            mask_path = output_dir / f"{prompt_slug}_{index:02d}.png"
            mask_image.save(mask_path)
            written_mask = {"raw": str(mask_path)}
            if dilate > 0 or blur > 0:
                soft_mask = soften_mask(mask_image, dilate=dilate, blur=blur)
                soft_path = output_dir / f"{prompt_slug}_{index:02d}_soft.png"
                soft_mask.save(soft_path)
                written_mask["soft"] = str(soft_path)
            written_masks.append(written_mask)

        results.append(
            {
                "prompt": prompt,
                "mask_count": len(written_masks),
                "boxes": boxes_list,
                "scores": scores_list,
                "written_masks": written_masks,
            }
        )

    return {
        "image": str(image_path),
        "original_size": original_size,
        "inference_size": image.size,
        "results": results,
    }


def build_summary(image_summaries: list[dict[str, object]], multi_image: bool) -> dict[str, object]:
    if not multi_image and image_summaries:
        first = image_summaries[0]
        if "error" in first:
            return {"event": "failed", "image": first["image"], "error": first["error"], "results": []}
        return {"event": "complete", "results": first["results"]}
    return {"event": "complete", "images": image_summaries}


def inference_context(*, device: str, amp_dtype: torch.dtype | None):
    return _inference_context(device=device, amp_dtype=amp_dtype)


@contextmanager
def _inference_context(*, device: str, amp_dtype: torch.dtype | None):
    with torch.inference_mode():
        if device == "cuda" and amp_dtype is not None:
            with torch.amp.autocast("cuda", dtype=amp_dtype):
                yield
        else:
            with nullcontext():
                yield


def soften_mask(mask: Image.Image, dilate: int, blur: float) -> Image.Image:
    softened = mask
    if dilate > 0:
        softened = softened.filter(ImageFilter.MaxFilter(dilate * 2 + 1))
    if blur > 0:
        softened = softened.filter(ImageFilter.GaussianBlur(blur))
    return softened

if __name__ == "__main__":
    main()
