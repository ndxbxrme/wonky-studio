from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageFilter
from sam3.model.sam3_image_processor import Sam3Processor
from sam3.model_builder import build_sam3_image_model


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a small SAM3 image segmentation smoke test.")
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--prompt", action="append", dest="prompts")
    parser.add_argument("--output-dir", default=Path("/mnt/d/wonky-studio/sam3-smoke"), type=Path)
    parser.add_argument("--max-edge", default=960, type=int)
    parser.add_argument("--threshold", default=0.35, type=float)
    parser.add_argument("--amp-dtype", choices=["float16", "bfloat16", "off"], default="float16")
    parser.add_argument("--dilate", default=0, type=int)
    parser.add_argument("--blur", default=0.0, type=float)
    parser.add_argument("--summary-file", type=Path)
    args = parser.parse_args()
    prompts = args.prompts or ["bed"]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    image = Image.open(args.image).convert("RGB")
    original_size = image.size
    if max(image.size) > args.max_edge:
        image.thumbnail((args.max_edge, args.max_edge), Image.Resampling.LANCZOS)

    print(
        json.dumps(
            {
                "event": "starting",
                "image": str(args.image),
                "original_size": original_size,
                "inference_size": image.size,
                "prompts": prompts,
            }
        ),
        flush=True,
    )

    model = build_sam3_image_model(compile=False)
    processor = Sam3Processor(model, confidence_threshold=args.threshold)

    amp_dtype = {"float16": torch.float16, "bfloat16": torch.bfloat16}.get(args.amp_dtype)
    with torch.inference_mode():
        if amp_dtype is None or not torch.cuda.is_available():
            state = processor.set_image(image)
        else:
            with torch.amp.autocast("cuda", dtype=amp_dtype):
                state = processor.set_image(image)

    results = []
    for prompt in prompts:
        processor.reset_all_prompts(state)
        with torch.inference_mode():
            if amp_dtype is None or not torch.cuda.is_available():
                output = processor.set_text_prompt(state=state, prompt=prompt)
            else:
                with torch.amp.autocast("cuda", dtype=amp_dtype):
                    output = processor.set_text_prompt(state=state, prompt=prompt)

        masks = output["masks"].detach().cpu()
        boxes = output["boxes"].detach().cpu().tolist()
        scores = output["scores"].detach().cpu().tolist()
        if masks.ndim == 4:
            masks = masks[:, 0]

        written_masks = []
        for index, mask in enumerate(masks):
            prompt_slug = prompt.replace(" ", "_")
            mask_image = Image.fromarray(mask.numpy().astype(np.uint8) * 255, mode="L")
            mask_path = args.output_dir / f"{prompt_slug}_{index:02d}.png"
            mask_image.save(mask_path)
            written_mask = {"raw": str(mask_path)}
            if args.dilate > 0 or args.blur > 0:
                soft_mask = soften_mask(mask_image, dilate=args.dilate, blur=args.blur)
                soft_path = args.output_dir / f"{prompt_slug}_{index:02d}_soft.png"
                soft_mask.save(soft_path)
                written_mask["soft"] = str(soft_path)
            written_masks.append(written_mask)

        results.append(
            {
                "prompt": prompt,
                "mask_count": len(written_masks),
                "boxes": boxes,
                "scores": scores,
                "written_masks": written_masks,
            }
        )

    summary = {"event": "complete", "results": results}
    if args.summary_file:
        args.summary_file.parent.mkdir(parents=True, exist_ok=True)
        args.summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


def soften_mask(mask: Image.Image, dilate: int, blur: float) -> Image.Image:
    softened = mask
    if dilate > 0:
        softened = softened.filter(ImageFilter.MaxFilter(dilate * 2 + 1))
    if blur > 0:
        softened = softened.filter(ImageFilter.GaussianBlur(blur))
    return softened


if __name__ == "__main__":
    main()
