from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

import httpx

from .config import Settings


LANGUAGE_NAMES = {
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "pt-br": "Brazilian Portuguese",
    "pt-pt": "European Portuguese",
    "es": "Spanish",
    "en": "English",
}

DO_NOT_TRANSLATE_EXACT = {"---", ""}

SHORT_UI_WORDS = {
    "play", "start", "resume", "continue", "quit", "exit", "credits",
    "help", "tutorial", "gallery", "sound", "music", "volume", "speech",
    "language", "settings", "options", "delete", "cancel", "back",
    "overwrite", "close", "yes", "no", "ok", "on", "off",
}

ProgressCallback = Callable[[int, int, str], Awaitable[None] | None]


class ScriptLocalizationProvider:
    target_languages: tuple[str, ...]

    async def localize_line(
        self,
        line_id: int,
        source_text: str,
        path_parts: list[str],
        existing_translations: dict[str, str],
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def generate_tts(
        self,
        line_id: int,
        language: str,
        text: str,
    ) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True)
class ScriptLocalizationSubprocessProvider(ScriptLocalizationProvider):
    script_audio_root: Path
    windows_python: Path
    speaker_wav: Path
    translate_model: str
    translate_source_language: str
    ollama_url: str
    xtts_device: str
    target_languages: tuple[str, ...]
    translation_timeout_seconds: float
    xtts_timeout_seconds: float

    async def localize_line(
        self,
        line_id: int,
        source_text: str,
        path_parts: list[str],
        existing_translations: dict[str, str],
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        working_root = self.script_audio_root / "tmp_localization" / f"line-{line_id}-{uuid4().hex}"
        working_root.mkdir(parents=True, exist_ok=True)
        total_steps = max(1, len(self.target_languages) + sum(1 for language in self.target_languages if language != "en"))
        current_step = 0

        async def report(message: str) -> None:
            if progress_callback is None:
                return
            maybe = progress_callback(current_step, total_steps, message)
            if maybe is not None:
                await maybe

        translations: dict[str, dict[str, Any]] = {}
        audio_outputs: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []

        try:
            for language in self.target_languages:
                if language == "en":
                    translations[language] = {
                        "language": language,
                        "text": source_text.strip(),
                        "source": "source_text",
                        "meta": {"source_lang": self.translate_source_language},
                    }
                    current_step += 1
                    await report(f"Prepared EN source text ({current_step}/{total_steps})")
                    continue

                existing_text = str(existing_translations.get(language) or "").strip()
                if existing_text:
                    translations[language] = {
                        "language": language,
                        "text": existing_text,
                        "source": "existing",
                        "meta": {"source_lang": self.translate_source_language},
                    }
                    current_step += 1
                    await report(f"Kept existing {language.upper()} translation ({current_step}/{total_steps})")
                    continue

                try:
                    translated_text = await self._translate_line(source_text, path_parts, language)
                    if not translated_text:
                        raise RuntimeError("Translation was empty")
                    translations[language] = {
                        "language": language,
                        "text": translated_text,
                        "source": "ollama_auto",
                        "meta": {
                            "model": self.translate_model,
                            "source_lang": self.translate_source_language,
                            "target_lang": LANGUAGE_NAMES.get(language, language),
                        },
                    }
                except Exception as exc:
                    errors.append({"language": language, "error": f"Translation failed: {exc}"})
                current_step += 1
                await report(f"Translated {language.upper()} ({current_step}/{total_steps})")

            for language in self.target_languages:
                translated_text = str(translations.get(language, {}).get("text") or "").strip()
                if not translated_text:
                    errors.append({"language": language, "error": "Missing translation"})
                    current_step += 1
                    await report(f"Skipped {language.upper()} audio ({current_step}/{total_steps})")
                    continue
                try:
                    wav_path = working_root / f"{slugify(source_text, 32)}_{language}.wav"
                    await self._generate_tts(
                        text=translated_text,
                        language=language,
                        output_path=wav_path,
                    )
                    audio_outputs.append(
                        {
                            "language": language,
                            "text": translated_text,
                            "wav_path": wav_path,
                        }
                    )
                except Exception as exc:
                    errors.append({"language": language, "error": f"TTS failed: {exc}"})
                current_step += 1
                await report(f"Generated {language.upper()} audio ({current_step}/{total_steps})")

            return {
                "translations": list(translations.values()),
                "audio_outputs": audio_outputs,
                "errors": errors,
                "working_root": working_root,
            }
        except Exception:
            shutil.rmtree(working_root, ignore_errors=True)
            raise

    async def _translate_line(
        self,
        source_text: str,
        path_parts: list[str],
        language: str,
    ) -> str:
        if source_text in DO_NOT_TRANSLATE_EXACT:
            return source_text
        prompt = build_translation_prompt(
            line=source_text,
            path=path_parts,
            target_language=LANGUAGE_NAMES.get(language, language),
            source_language=self.translate_source_language,
        )
        payload = {
            "model": self.translate_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_ctx": 4096,
            },
        }
        last_error = None
        async with httpx.AsyncClient(timeout=self.translation_timeout_seconds) as client:
            for attempt in range(1, 4):
                try:
                    response = await client.post(self.ollama_url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    return normalise_model_output(str(data.get("response", "")))
                except Exception as exc:
                    last_error = exc
                    if attempt < 3:
                        await asyncio.sleep(2 * attempt)
        raise RuntimeError(f"Ollama request failed: {last_error}")

    async def _generate_tts(
        self,
        *,
        text: str,
        language: str,
        output_path: Path,
    ) -> None:
        helper_script = Path(__file__).with_name("xtts_generate_line.py")
        await self._run_windows_python(
            [
                helper_script,
                "--text",
                text,
                "--language",
                language,
                "--speaker-wav",
                self.speaker_wav,
                "--output",
                output_path,
                "--device",
                self.xtts_device,
            ],
            timeout_seconds=self.xtts_timeout_seconds,
        )

    async def _run_windows_python(
        self,
        arguments: list[Any],
        timeout_seconds: float,
    ) -> None:
        cmd_path = shutil.which("cmd.exe") or "/mnt/c/Windows/system32/cmd.exe"
        command = [cmd_path, "/c", _windows_path(self.windows_python)]
        for argument in arguments:
            if isinstance(argument, Path):
                command.append(_windows_path(argument))
            else:
                command.append(str(argument))
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise RuntimeError("Localization subprocess timed out") from exc
        if process.returncode != 0:
            output = "\n".join(
                part.strip()
                for part in (
                    stdout.decode("utf-8", errors="replace"),
                    stderr.decode("utf-8", errors="replace"),
                )
                if part.strip()
            ).strip()
            raise RuntimeError(output or "Localization subprocess failed")

    async def generate_tts(
        self,
        line_id: int,
        language: str,
        text: str,
    ) -> dict[str, Any]:
        working_root = self.script_audio_root / "tmp_localization" / f"tts-{line_id}-{language}-{uuid4().hex}"
        working_root.mkdir(parents=True, exist_ok=True)
        try:
            wav_path = working_root / f"{slugify(text, 32)}_{language}.wav"
            await self._generate_tts(text=text, language=language, output_path=wav_path)
            return {
                "language": language,
                "text": text,
                "wav_path": wav_path,
                "working_root": working_root,
            }
        except Exception:
            shutil.rmtree(working_root, ignore_errors=True)
            raise


def build_script_localization_provider(settings: Settings) -> ScriptLocalizationProvider:
    if settings.script_localization_provider == "disabled":
        raise ValueError("Script localization provider is disabled")
    windows_python = settings.script_xtts_python_path
    speaker_wav = settings.script_xtts_speaker_wav
    if not windows_python.exists():
        raise ValueError(f"XTTS Python is missing: {windows_python}")
    if not speaker_wav.exists():
        raise ValueError(f"XTTS speaker reference is missing: {speaker_wav}")
    if not shutil.which("cmd.exe") and not Path("/mnt/c/Windows/system32/cmd.exe").exists():
        raise ValueError("cmd.exe is not available from WSL")
    target_languages = tuple(
        language.strip().lower()
        for language in settings.script_translation_target_languages.split(",")
        if language.strip()
    )
    if not target_languages:
        raise ValueError("No target languages configured for script localization")
    return ScriptLocalizationSubprocessProvider(
        script_audio_root=settings.script_audio_root,
        windows_python=windows_python,
        speaker_wav=speaker_wav,
        translate_model=settings.script_translation_model,
        translate_source_language=settings.script_translation_source_language,
        ollama_url=settings.script_translation_ollama_url,
        xtts_device=settings.script_xtts_device,
        target_languages=target_languages,
        translation_timeout_seconds=settings.script_translation_timeout_seconds,
        xtts_timeout_seconds=settings.script_xtts_timeout_seconds,
    )


def build_translation_prompt(
    line: str,
    path: list[str],
    target_language: str,
    source_language: str,
) -> str:
    path_str = " > ".join(path) if path else "(none)"
    is_short = len(line.split()) <= 3
    lower = re.sub(r"[^a-zA-Z]+", "", line).lower()
    short_rule = ""
    if is_short or lower in SHORT_UI_WORDS:
        short_rule = "\n- This is a short UI/menu line: keep it very concise and natural."
    return f"""You are localising dialogue for a whimsical stop-motion language-learning adventure game.

Translate the source line from {source_language} into natural {target_language}.

Rules:
- Preserve the gameplay meaning, intent, humour, and tone.
- Use natural native {target_language}, not a literal word-for-word translation.
- Keep it child-friendly.
- Keep line length similar where possible.
- Preserve punctuation style where it matters, including ! ? … and playful pauses.
- If the source intentionally contains a simple UI label, produce the normal UI label in {target_language}.
- Do not add explanations, alternatives, notes, markdown, or quotation marks.
- Output only the translated line.{short_rule}

Context path: {path_str}

Source line:
{line}
"""


def normalise_model_output(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:text|json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    if text.startswith("{") and text.endswith("}"):
        try:
            obj = json.loads(text)
            for key in ("translation", "translated_line", "line", "text"):
                if key in obj and isinstance(obj[key], str):
                    return obj[key].strip()
        except Exception:
            pass
    text = re.sub(
        r"^(translation|translated line|french|german|italian|spanish|portuguese|english)\s*:\s*",
        "",
        text,
        flags=re.I,
    )
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        for line in lines:
            match = re.match(r'^[“"](.+)[”"]$', line)
            if match:
                return match.group(1).strip()
        return lines[0]
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("“") and text.endswith("”")):
        text = text[1:-1].strip()
    return text


def slugify(text: str, max_len: int = 64) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.lower()
    text = re.sub(r"[’']", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        text = "line"
    return text[:max_len].rstrip("_")


def _windows_path(path: Path) -> str:
    path_str = str(path)
    if path_str.startswith("/mnt/") and len(path_str) > 6 and path_str[5].isalpha() and path_str[6] == "/":
        drive = path_str[5].upper()
        tail = path_str[7:].replace("/", "\\")
        return f"{drive}:\\{tail}"
    process = subprocess.run(
        ["wslpath", "-w", path_str],
        capture_output=True,
        check=False,
        text=True,
    )
    if process.returncode == 0:
        return process.stdout.strip()
    raise RuntimeError(process.stderr.strip() or f"Could not convert path to Windows path: {path}")
