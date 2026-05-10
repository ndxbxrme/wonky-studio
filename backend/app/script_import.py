from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .database import connect, json_dumps


TRANSLATION_LANGUAGES = ("en", "de", "es", "fr", "it", "pt")


def import_script_audio_data(
    db_path: Path,
    audio_root: Path,
    organization_id: str,
) -> dict[str, Any]:
    script_path = audio_root / "language-adventure-script.json"
    if not script_path.exists():
        raise FileNotFoundError(f"Could not find {script_path}")

    script_rows = _read_json_list(script_path)
    counts = {
        "script_lines": 0,
        "translations": 0,
        "narrator_candidates": 0,
        "tts_candidates": 0,
        "missing_narrator_line_ids": [],
        "skipped_files": [],
    }

    with connect(db_path) as connection:
        for index, row in enumerate(script_rows):
            line_id = index + 1
            path_parts = _path_parts(row.get("path"))
            _upsert_script_line(
                connection,
                organization_id=organization_id,
                line_id=line_id,
                script_index=index,
                source_text=str(row.get("line") or ""),
                path_parts=path_parts,
            )
            counts["script_lines"] += 1

        line_db_ids = _load_script_line_ids(connection, organization_id)

        for language in TRANSLATION_LANGUAGES:
            translated_path = audio_root / f"language-adventure-script.{language}.json"
            if not translated_path.exists():
                counts["skipped_files"].append(str(translated_path))
                continue
            for index, row in enumerate(_read_json_list(translated_path)):
                line_id = index + 1
                text = _translation_text(row, language)
                meta = row.get("translation_meta", {}).get(language, {})
                if _upsert_script_translation(
                    connection,
                    line_db_ids,
                    organization_id=organization_id,
                    line_id=line_id,
                    language=language,
                    text=text,
                    source="script" if language == "en" else "ai_translation",
                    meta=meta if isinstance(meta, dict) else {},
                ):
                    counts["translations"] += 1

        narrator_line_ids = set()
        narrator_manifest = audio_root / "clips_ogg" / "manifest.csv"
        if narrator_manifest.exists():
            for row in _read_csv_rows(narrator_manifest):
                line_id = _int_or_none(row.get("line_index"))
                if line_id is None:
                    continue
                narrator_line_ids.add(line_id)
                if _upsert_script_audio_candidate(
                    connection,
                    line_db_ids,
                    organization_id=organization_id,
                    line_id=line_id,
                    language="en",
                    source_type="narrator_candidate",
                    manifest_status="exported" if _boolish(row.get("exported")) else "not_exported",
                    relative_path=_normalize_audio_path(row.get("clip"), audio_root),
                    original_path=str(row.get("clip") or ""),
                    rank=_int_or_none(row.get("rank")),
                    score=_float_or_none(row.get("score")),
                    text_score=_float_or_none(row.get("text_score")),
                    quality_score=_float_or_none(row.get("quality_score")),
                    duration_seconds=_float_or_none(row.get("duration")),
                    transcript_match=str(row.get("transcript_match") or ""),
                    notes=str(row.get("notes") or ""),
                    source_file=str(row.get("source_file") or ""),
                    start_seconds=_float_or_none(row.get("start")),
                    end_seconds=_float_or_none(row.get("end")),
                    review_status="candidate",
                ):
                    counts["narrator_candidates"] += 1
        else:
            counts["skipped_files"].append(str(narrator_manifest))

        all_line_ids = set(range(1, len(script_rows) + 1))
        counts["missing_narrator_line_ids"] = sorted(all_line_ids - narrator_line_ids)

        for language in TRANSLATION_LANGUAGES:
            tts_manifest = audio_root / "clips_tts_ogg" / f"manifest_tts_{language}.csv"
            if not tts_manifest.exists():
                counts["skipped_files"].append(str(tts_manifest))
                continue
            for row in _best_tts_rows(_read_csv_rows(tts_manifest)):
                line_id = _int_or_none(row.get("line_id") or row.get("index"))
                if line_id is None:
                    continue
                status = str(row.get("status") or "").strip().lower()
                relative_path = _normalize_audio_path(row.get("output_wav"), audio_root)
                if _upsert_script_audio_candidate(
                    connection,
                    line_db_ids,
                    organization_id=organization_id,
                    line_id=line_id,
                    language=language,
                    source_type="tts",
                    manifest_status=status,
                    relative_path=relative_path if status != "error" else "",
                    original_path=str(row.get("output_wav") or ""),
                    duration_seconds=_float_or_none(row.get("seconds")),
                    error=str(row.get("error") or ""),
                    review_status="needs_edit" if status == "error" else "needs_review",
                ):
                    counts["tts_candidates"] += 1

    return counts


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, list):
        raise ValueError(f"{path} did not contain a JSON list")
    return [row for row in value if isinstance(row, dict)]


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _upsert_script_line(
    connection,
    organization_id: str,
    line_id: int,
    script_index: int,
    source_text: str,
    path_parts: list[str],
) -> None:
    path_json = json.dumps(path_parts, ensure_ascii=False)
    path_text = " / ".join(path_parts)
    connection.execute(
        """
        INSERT INTO script_lines (
            organization_id,
            line_id,
            script_index,
            source_text,
            path_json,
            path_text
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (organization_id, line_id) DO UPDATE SET
            script_index = excluded.script_index,
            source_text = excluded.source_text,
            path_json = excluded.path_json,
            path_text = excluded.path_text,
            updated_at = CURRENT_TIMESTAMP
        """,
        (organization_id, line_id, script_index, source_text, path_json, path_text),
    )


def _upsert_script_translation(
    connection,
    line_db_ids: dict[int, int],
    organization_id: str,
    line_id: int,
    language: str,
    text: str,
    source: str,
    meta: dict[str, Any],
) -> bool:
    script_line_id = line_db_ids.get(line_id) or _script_line_db_id(
        connection,
        organization_id,
        line_id,
    )
    if script_line_id is None:
        return False
    connection.execute(
        """
        INSERT INTO script_translations (
            script_line_id,
            language,
            text,
            source,
            review_status,
            meta_json
        )
        VALUES (?, ?, ?, ?, 'needs_review', ?)
        ON CONFLICT (script_line_id, language) DO UPDATE SET
            text = CASE
                WHEN script_translations.manually_edited = 0 THEN excluded.text
                ELSE script_translations.text
            END,
            source = CASE
                WHEN script_translations.manually_edited = 0 THEN excluded.source
                ELSE script_translations.source
            END,
            meta_json = CASE
                WHEN script_translations.manually_edited = 0 THEN excluded.meta_json
                ELSE script_translations.meta_json
            END,
            updated_at = CURRENT_TIMESTAMP
        """,
        (script_line_id, language, text, source, json_dumps(meta)),
    )
    return True


def _upsert_script_audio_candidate(
    connection,
    line_db_ids: dict[int, int],
    organization_id: str,
    line_id: int,
    language: str,
    source_type: str,
    manifest_status: str,
    relative_path: str,
    original_path: str,
    rank: int | None = None,
    score: float | None = None,
    text_score: float | None = None,
    quality_score: float | None = None,
    duration_seconds: float | None = None,
    transcript_match: str = "",
    notes: str = "",
    error: str = "",
    source_file: str = "",
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    review_status: str = "needs_review",
) -> bool:
    script_line_id = line_db_ids.get(line_id) or _script_line_db_id(
        connection,
        organization_id,
        line_id,
    )
    if script_line_id is None:
        return False
    normalized_rank = rank if rank is not None else -1
    connection.execute(
        """
        INSERT INTO script_audio_candidates (
            script_line_id,
            language,
            source_type,
            manifest_status,
            review_status,
            relative_path,
            original_path,
            rank,
            score,
            text_score,
            quality_score,
            duration_seconds,
            transcript_match,
            notes,
            error,
            source_file,
            start_seconds,
            end_seconds
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (script_line_id, language, source_type, original_path, rank)
        DO UPDATE SET
            manifest_status = excluded.manifest_status,
            relative_path = excluded.relative_path,
            score = excluded.score,
            text_score = excluded.text_score,
            quality_score = excluded.quality_score,
            duration_seconds = excluded.duration_seconds,
            transcript_match = excluded.transcript_match,
            error = excluded.error,
            source_file = excluded.source_file,
            start_seconds = excluded.start_seconds,
            end_seconds = excluded.end_seconds,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            script_line_id,
            language,
            source_type,
            manifest_status,
            review_status,
            relative_path,
            original_path,
            normalized_rank,
            score,
            text_score,
            quality_score,
            duration_seconds,
            transcript_match,
            notes,
            error,
            source_file,
            start_seconds,
            end_seconds,
        ),
    )
    return True


def _load_script_line_ids(connection, organization_id: str) -> dict[int, int]:
    rows = connection.execute(
        """
        SELECT id, line_id
        FROM script_lines
        WHERE organization_id = ?
        """,
        (organization_id,),
    ).fetchall()
    return {int(row["line_id"]): int(row["id"]) for row in rows}


def _script_line_db_id(connection, organization_id: str, line_id: int) -> int | None:
    row = connection.execute(
        """
        SELECT id
        FROM script_lines
        WHERE organization_id = ?
          AND line_id = ?
        """,
        (organization_id, line_id),
    ).fetchone()
    return int(row["id"]) if row else None


def _best_tts_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    priority = {"generated": 0, "exists": 1, "error": 2}
    best: dict[tuple[int, str], dict[str, str]] = {}
    for row in rows:
        line_id = _int_or_none(row.get("line_id") or row.get("index"))
        language = str(row.get("lang") or "").strip()
        if line_id is None or not language:
            continue
        key = (line_id, language)
        current = best.get(key)
        if current is None:
            best[key] = row
            continue
        current_priority = priority.get(str(current.get("status") or "").strip().lower(), 99)
        row_priority = priority.get(str(row.get("status") or "").strip().lower(), 99)
        if row_priority < current_priority:
            best[key] = row
    return list(best.values())


def _translation_text(row: dict[str, Any], language: str) -> str:
    translations = row.get("translations")
    if isinstance(translations, dict) and translations.get(language):
        return str(translations[language])
    line_key = f"line_{language}"
    if row.get(line_key):
        return str(row[line_key])
    return str(row.get("line") or "")


def _path_parts(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(part) for part in value if str(part).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split("/") if part.strip()]
    return []


def _normalize_audio_path(value: str | None, audio_root: Path) -> str:
    if not value:
        return ""
    normalized = value.strip().replace("\\", "/")
    lower = normalized.lower()
    for marker in ("wonky-studio/audio/", "/mnt/d/wonky-studio/audio/"):
        index = lower.find(marker)
        if index >= 0:
            normalized = normalized[index + len(marker) :]
            lower = normalized.lower()
            break
    if lower.startswith("d:/wonky-studio/audio/"):
        normalized = normalized[len("D:/wonky-studio/audio/") :]
        lower = normalized.lower()
    while normalized.startswith("/"):
        normalized = normalized[1:]
        lower = normalized.lower()
    if lower.startswith("clips/"):
        normalized = "clips_ogg/" + normalized.split("/", 1)[1]
    elif lower.startswith("clips_tts/"):
        normalized = "clips_tts_ogg/" + normalized.split("/", 1)[1]

    return Path(normalized).as_posix()


def _int_or_none(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(float(str(value)))
    except ValueError:
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value))
    except ValueError:
        return None


def _boolish(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}
