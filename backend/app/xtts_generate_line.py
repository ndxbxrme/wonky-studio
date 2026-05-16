from __future__ import annotations

import argparse
from pathlib import Path


XTTS_MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"


def maybe_patch_torch_load_for_torch26() -> None:
    import torch  # type: ignore

    old_load = torch.load

    def patched_load(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return old_load(*args, **kwargs)

    torch.load = patched_load  # type: ignore


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate one XTTS line.")
    parser.add_argument("--text", required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--speaker-wav", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--allow-torch26-patch", action="store_true", default=True)
    parser.add_argument("--voice-speed", type=float, default=None)
    args = parser.parse_args()

    if args.allow_torch26_patch:
        maybe_patch_torch_load_for_torch26()

    from TTS.api import TTS  # type: ignore

    tts = TTS(XTTS_MODEL_NAME)
    if args.device:
        tts = tts.to(args.device)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    kwargs = {
        "text": args.text,
        "speaker_wav": str(args.speaker_wav),
        "language": args.language,
        "file_path": str(args.output),
    }
    if args.voice_speed is not None:
        kwargs["speed"] = args.voice_speed
    tts.tts_to_file(**kwargs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
