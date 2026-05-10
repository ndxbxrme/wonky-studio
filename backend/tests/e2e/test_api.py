from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.config import Settings
from app.database import create_or_promote_admin, create_session, upsert_user
from app.main import create_app
from app.segmentation import SegmentationCandidate, SegmentationPromptResult
from app.vlm import SceneDraft, SceneDraftObject


@contextmanager
def api_client(
    tmp_path: Path,
    vlm_provider=None,
    segmentation_provider=None,
) -> Iterator[tuple[TestClient, Path, Settings]]:
    db_path = tmp_path / "test.sqlite3"
    settings = Settings(
        organization_id="wonky-studio-test",
        organization_name="Wonky Studio Test",
        frontend_url="http://127.0.0.1:5173",
        api_base_url="http://127.0.0.1:8000",
        session_cookie_name="wonky_studio_session_test",
        session_secret="test-session-secret",
        google_client_id=None,
        google_client_secret=None,
        google_redirect_uri="http://127.0.0.1:8000/api/auth/google/callback",
        storage_root=tmp_path / "uploads",
        script_audio_root=tmp_path / "audio",
    )
    app = create_app(
        db_path,
        settings,
        vlm_provider=vlm_provider,
        segmentation_provider=segmentation_provider,
    )

    with TestClient(app) as client:
        yield client, db_path, settings


def authenticate(client: TestClient, db_path: Path, settings: Settings, role: str = "user"):
    user = upsert_user(
        db_path,
        organization_id=settings.organization_id,
        email=f"{role}@example.com",
        display_name=f"Test {role.title()}",
        avatar_url=None,
        role=role,
    )
    session_token, _ = create_session(db_path, user["id"])
    client.cookies.set(settings.session_cookie_name, session_token)
    return user


def wait_for_job(client: TestClient, job_id: int, timeout_seconds: float = 5.0):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"succeeded", "failed"}:
            return job
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not finish")


def create_script_audio_fixture(audio_root: Path) -> None:
    audio_root.mkdir(parents=True, exist_ok=True)
    script_rows = [
        {"line": "Hello", "path": ["ROOMS", "BEDROOM"]},
        {"line": "Open the door", "path": ["ROOMS", "BEDROOM"]},
        {"line": "Inventory", "path": ["USER INTERFACE"]},
    ]
    (audio_root / "language-adventure-script.json").write_text(
        json.dumps(script_rows),
        encoding="utf-8",
    )
    (audio_root / "language-adventure-script.en.json").write_text(
        json.dumps(script_rows),
        encoding="utf-8",
    )
    (audio_root / "language-adventure-script.fr.json").write_text(
        json.dumps(
            [
                {
                    "line": "Hello",
                    "path": ["ROOMS", "BEDROOM"],
                    "translations": {"fr": "Bonjour"},
                    "translation_meta": {"fr": {"model": "test"}},
                    "line_fr": "Bonjour",
                },
                {
                    "line": "Open the door",
                    "path": ["ROOMS", "BEDROOM"],
                    "translations": {"fr": "Ouvre la porte"},
                    "translation_meta": {"fr": {"model": "test"}},
                    "line_fr": "Ouvre la porte",
                },
                {
                    "line": "Inventory",
                    "path": ["USER INTERFACE"],
                    "translations": {"fr": "Inventaire"},
                    "translation_meta": {"fr": {"model": "test"}},
                    "line_fr": "Inventaire",
                },
            ]
        ),
        encoding="utf-8",
    )

    clips_root = audio_root / "clips_ogg"
    clips_root.mkdir(parents=True, exist_ok=True)
    (clips_root / "0001.ogg").write_bytes(b"OggS narrator one")
    (clips_root / "0002.ogg").write_bytes(b"OggS narrator two")
    (clips_root / "manifest.csv").write_text(
        "\n".join(
            [
                "line_index,rank,score,text_score,quality_score,source_file,start,end,duration,script_line,path,transcript_match,notes,clip,exported",
                "1,1,100,100,100,source.wav,0,1,1,Hello,ROOMS / BEDROOM,Hello,,clips\\0001.ogg,True",
                "2,1,96,97,95,source.wav,1,2,1,Open the door,ROOMS / BEDROOM,Open the door,,clips\\0002.ogg,True",
            ]
        ),
        encoding="utf-8",
    )

    tts_root = audio_root / "clips_tts_ogg" / "fr"
    tts_root.mkdir(parents=True, exist_ok=True)
    (tts_root / "0001_fr.ogg").write_bytes(b"OggS tts one")
    (tts_root / "0003_fr.ogg").write_bytes(b"OggS tts three")
    (audio_root / "clips_tts_ogg" / "manifest_tts_fr.csv").write_text(
        "\n".join(
            [
                "line_id,index,lang,source_line,translated_line,path,output_wav,status,error,seconds",
                "1,0,fr,Hello,Bonjour,ROOMS / BEDROOM,clips_tts\\fr\\0001_fr.ogg,exists,,0.9",
                "1,0,fr,Hello,Bonjour,ROOMS / BEDROOM,clips_tts\\fr\\0001_fr.ogg,generated,,0.9",
                "2,1,fr,Open the door,Ouvre la porte,ROOMS / BEDROOM,clips_tts\\fr\\0002_fr.ogg,error,tts failed,",
                "3,2,fr,Inventory,Inventaire,USER INTERFACE,clips_tts\\fr\\0003_fr.ogg,generated,,0.8",
            ]
        ),
        encoding="utf-8",
    )


def test_health_check_responds(tmp_path):
    with api_client(tmp_path) as (client, _, _):
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_session_returns_current_user_when_authenticated(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        user = authenticate(client, db_path, settings, role="admin")
        response = client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json()["user"]["email"] == user["email"]
    assert response.json()["user"]["role"] == "admin"
    assert response.json()["organization_id"] == settings.organization_id


def test_admin_can_generate_invite_link(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        admin = create_or_promote_admin(
            db_path,
            organization_id=settings.organization_id,
            email="admin@example.com",
            display_name="Admin User",
        )
        session_token, _ = create_session(db_path, admin["id"])
        client.cookies.set(settings.session_cookie_name, session_token)

        response = client.post(
            "/api/invites",
            json={
                "email": "artist@example.com",
                "role": "user",
                "expires_in_days": 14,
            },
        )

    assert response.status_code == 201
    invite = response.json()
    assert invite["email"] == "artist@example.com"
    assert invite["role"] == "user"
    assert invite["organization_id"] == settings.organization_id
    assert invite["invite_link"].startswith(f"{settings.frontend_url}/?invite=")


def test_regular_user_cannot_generate_invite_link(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="user")

        response = client.post("/api/invites", json={"role": "user"})

    assert response.status_code == 403


def test_admin_can_import_and_review_script_audio(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="admin")
        create_script_audio_fixture(settings.script_audio_root)

        import_response = client.post("/api/admin/import-script-audio", json={})
        list_response = client.get("/api/script-lines?language=fr&q=Bonjour")

        assert import_response.status_code == 200
        import_result = import_response.json()
        assert import_result["script_lines"] == 3
        assert import_result["translations"] == 6
        assert import_result["narrator_candidates"] == 2
        assert import_result["tts_candidates"] == 3
        assert import_result["missing_narrator_line_ids"] == [3]

        assert list_response.status_code == 200
        listed = list_response.json()
        assert listed["total"] == 1
        assert listed["items"][0]["line_id"] == 1
        assert listed["items"][0]["selected_translation"]["text"] == "Bonjour"

        detail_response = client.get("/api/script-lines/1")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        narrator = next(
            candidate
            for candidate in detail["audio_candidates"]
            if candidate["source_type"] == "narrator_candidate"
        )
        audio_response = client.get(f"/api/script-audio-candidates/{narrator['id']}/content")
        assert audio_response.status_code == 200
        assert audio_response.content.startswith(b"OggS")

        translation_response = client.patch(
            "/api/script-lines/1/translations/fr",
            json={
                "text": "Salut",
                "review_status": "approved",
                "notes": "Native speaker approved",
            },
        )
        assert translation_response.status_code == 200
        assert translation_response.json()["manually_edited"] is True

        selected_response = client.patch(
            f"/api/script-audio-candidates/{narrator['id']}",
            json={
                "review_status": "approved",
                "notes": "Clean take",
                "selected": True,
            },
        )
        assert selected_response.status_code == 200
        assert selected_response.json()["selected"] is True

        reimport_response = client.post("/api/admin/import-script-audio", json={})
        assert reimport_response.status_code == 200
        updated_detail = client.get("/api/script-lines/1").json()
        french = next(
            translation
            for translation in updated_detail["translations"]
            if translation["language"] == "fr"
        )
        updated_narrator = next(
            candidate
            for candidate in updated_detail["audio_candidates"]
            if candidate["id"] == narrator["id"]
        )
        assert french["text"] == "Salut"
        assert french["review_status"] == "approved"
        assert updated_narrator["selected"] is True
        assert updated_narrator["review_status"] == "approved"


def test_regular_user_cannot_import_script_audio(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="user")
        create_script_audio_fixture(settings.script_audio_root)

        response = client.post("/api/admin/import-script-audio", json={})

    assert response.status_code == 403


def test_assets_require_authentication(tmp_path):
    with api_client(tmp_path) as (client, _, _):
        response = client.get("/api/assets")

    assert response.status_code == 401


def test_assets_can_be_created_and_listed_by_authenticated_user(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="user")
        create_response = client.post(
            "/api/assets",
            json={
                "name": "Knight Idle Animation",
                "asset_type": "animation",
                "status": "in_progress",
            },
        )
        list_response = client.get("/api/assets")

    assert create_response.status_code == 201
    created_asset = create_response.json()
    assert created_asset["id"] == 1
    assert created_asset["organization_id"] == settings.organization_id
    assert created_asset["name"] == "Knight Idle Animation"
    assert created_asset["asset_type"] == "animation"
    assert created_asset["status"] == "in_progress"
    assert "created_at" in created_asset

    assert list_response.status_code == 200
    assert list_response.json() == [created_asset]


def test_upload_batch_requires_authentication(tmp_path):
    with api_client(tmp_path) as (client, _, _):
        response = client.post(
            "/api/uploads/batches",
            files=[("files", ("scene.jpg", b"image-data", "image/jpeg"))],
        )

    assert response.status_code == 401


def test_authenticated_user_can_upload_file_batch(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        user = authenticate(client, db_path, settings, role="user")
        response = client.post(
            "/api/uploads/batches",
            files=[
                ("files", ("scene 001.jpg", b"image-data-1", "image/jpeg")),
                ("files", ("line.txt", b"bonjour", "text/plain")),
            ],
        )
        list_response = client.get("/api/uploads/batches")

    assert response.status_code == 201
    batch = response.json()
    assert batch["organization_id"] == settings.organization_id
    assert batch["created_by_user_id"] == user["id"]
    assert batch["status"] == "queued"
    assert batch["file_count"] == 2
    assert batch["total_bytes"] == len(b"image-data-1") + len(b"bonjour")
    assert [file["processing_status"] for file in batch["files"]] == ["queued", "queued"]
    assert batch["files"][0]["original_filename"] == "scene 001.jpg"
    assert batch["files"][1]["content_type"] == "text/plain"

    for uploaded_file in batch["files"]:
        stored_path = settings.storage_root / uploaded_file["relative_path"]
        assert stored_path.exists()

    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == batch["id"]
    assert list_response.json()[0]["file_count"] == 2


def test_upload_batch_can_be_processed_into_draft_scene(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        user = authenticate(client, db_path, settings, role="user")
        upload_response = client.post(
            "/api/uploads/batches",
            files=[
                ("files", ("bedroom-open.png", png_bytes(draw_flower=False), "image/png")),
                ("files", ("bedroom-flower.png", png_bytes(draw_flower=True), "image/png")),
            ],
        )
        batch_id = upload_response.json()["id"]

        process_response = client.post(f"/api/uploads/batches/{batch_id}/process-scene")
        scenes_response = client.get("/api/scenes")

    assert process_response.status_code == 200
    result = process_response.json()
    assert result["created"] is True
    assert result["matched_existing"] is False
    assert result["processed_file_count"] == 2
    assert result["scene"]["created_by_user_id"] == user["id"]
    assert result["scene"]["title"] == f"Draft scene from batch {batch_id}"
    assert len(result["scene"]["images"]) == 2
    assert result["scene"]["images"][0]["width"] == 96
    assert result["scene"]["images"][0]["height"] == 54

    assert scenes_response.status_code == 200
    assert scenes_response.json()[0]["id"] == result["scene"]["id"]
    assert scenes_response.json()[0]["image_count"] == 2
    assert scenes_response.json()[0]["object_count"] == 0


def test_similar_images_from_later_batch_reuse_existing_scene(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="user")
        first_upload = client.post(
            "/api/uploads/batches",
            files=[("files", ("bedroom-a.png", png_bytes(draw_flower=False), "image/png"))],
        )
        first_batch_id = first_upload.json()["id"]
        first_process = client.post(
            f"/api/uploads/batches/{first_batch_id}/process-scene"
        ).json()

        second_upload = client.post(
            "/api/uploads/batches",
            files=[("files", ("bedroom-b.png", png_bytes(draw_flower=True), "image/png"))],
        )
        second_batch_id = second_upload.json()["id"]
        second_response = client.post(
            f"/api/uploads/batches/{second_batch_id}/process-scene"
        )

    assert second_response.status_code == 200
    second_process = second_response.json()
    assert second_process["created"] is False
    assert second_process["matched_existing"] is True
    assert second_process["scene"]["id"] == first_process["scene"]["id"]
    assert len(second_process["scene"]["images"]) == 2


def test_scene_frames_and_object_masks_are_sorted_by_original_filename(tmp_path):
    fake_segmentation = FakeSegmentationProvider()
    with api_client(
        tmp_path,
        segmentation_provider=fake_segmentation,
    ) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="user")
        upload_response = client.post(
            "/api/uploads/batches",
            files=[
                ("files", ("bedroom_0003.png", png_bytes(draw_flower=True), "image/png")),
                ("files", ("bedroom_0001.png", png_bytes(draw_flower=True), "image/png")),
                ("files", ("bedroom_0002.png", png_bytes(draw_flower=True), "image/png")),
                ("files", ("bedroom_0000.png", png_bytes(draw_flower=True), "image/png")),
            ],
        )
        batch_id = upload_response.json()["id"]
        scene = client.post(f"/api/uploads/batches/{batch_id}/process-scene").json()["scene"]
        client.post(
            f"/api/scenes/{scene['id']}/objects",
            json={"name": "bed", "prompt": "bed"},
        )
        extract_response = client.post(f"/api/scenes/{scene['id']}/extract-masks")
        wait_for_job(client, extract_response.json()["id"])
        detail_response = client.get(f"/api/scenes/{scene['id']}")

    detail = detail_response.json()
    expected_names = [
        "bedroom_0000.png",
        "bedroom_0001.png",
        "bedroom_0002.png",
        "bedroom_0003.png",
    ]
    assert [image["original_filename"] for image in scene["images"]] == expected_names
    assert [
        path.name.split("-", 1)[1]
        for path in fake_segmentation.image_calls
    ] == expected_names
    assert [
        mask["original_filename"]
        for mask in detail["objects"][0]["masks"]
    ] == expected_names


def test_scene_detail_supports_manual_object_inventory_and_image_access(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="user")
        upload_response = client.post(
            "/api/uploads/batches",
            files=[("files", ("bedroom.png", png_bytes(draw_flower=True), "image/png"))],
        )
        batch_id = upload_response.json()["id"]
        process_response = client.post(f"/api/uploads/batches/{batch_id}/process-scene")
        scene = process_response.json()["scene"]
        uploaded_file_id = scene["images"][0]["uploaded_file_id"]

        object_response = client.post(
            f"/api/scenes/{scene['id']}/objects",
            json={
                "name": "bed",
                "description": "Wooden bed with pillow and blanket.",
            },
        )
        detail_response = client.get(f"/api/scenes/{scene['id']}")
        file_response = client.get(f"/api/uploads/files/{uploaded_file_id}/content")

    assert object_response.status_code == 201
    created_object = object_response.json()
    assert created_object["name"] == "bed"
    assert created_object["status"] == "draft"

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["objects"] == [created_object]
    assert detail["images"][0]["original_filename"] == "bedroom.png"

    assert file_response.status_code == 200
    assert file_response.headers["content-type"] == "image/png"
    assert file_response.content.startswith(b"\x89PNG")


def test_scene_object_animations_can_be_created_updated_listed_and_removed(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="user")
        upload_response = client.post(
            "/api/uploads/batches",
            files=[("files", ("bedroom.png", png_bytes(draw_flower=True), "image/png"))],
        )
        batch_id = upload_response.json()["id"]
        scene = client.post(f"/api/uploads/batches/{batch_id}/process-scene").json()["scene"]
        scene_object = client.post(
            f"/api/scenes/{scene['id']}/objects",
            json={"name": "bed", "prompt": "bed"},
        ).json()

        create_response = client.post(
            f"/api/scene-objects/{scene_object['id']}/animations",
            json={
                "name": "idle",
                "segments": [
                    {"start_frame": 0, "end_frame": 10, "frame_duration_seconds": 1 / 15},
                    {"start_frame": 11, "end_frame": 11, "frame_duration_seconds": 1},
                    {"start_frame": 10, "end_frame": 1, "frame_duration_seconds": 1 / 15},
                ],
            },
        )
        animation = create_response.json()
        list_response = client.get(f"/api/scene-objects/{scene_object['id']}/animations")
        detail_response = client.get(f"/api/scenes/{scene['id']}")
        update_response = client.patch(
            f"/api/scene-objects/{scene_object['id']}/animations/{animation['id']}",
            json={
                "name": "idle hold",
                "segments": [
                    {"start_frame": 0, "end_frame": 0, "frame_duration_seconds": 0.5},
                ],
            },
        )
        delete_response = client.delete(
            f"/api/scene-objects/{scene_object['id']}/animations/{animation['id']}"
        )
        empty_list_response = client.get(f"/api/scene-objects/{scene_object['id']}/animations")

    assert create_response.status_code == 201
    assert animation["name"] == "idle"
    assert [segment["sort_order"] for segment in animation["segments"]] == [0, 1, 2]
    assert animation["segments"][2]["start_frame"] == 10
    assert animation["segments"][2]["end_frame"] == 1

    assert list_response.status_code == 200
    assert list_response.json() == [animation]
    assert detail_response.json()["objects"][0]["animation_count"] == 1

    assert update_response.status_code == 200
    updated_animation = update_response.json()
    assert updated_animation["name"] == "idle hold"
    assert len(updated_animation["segments"]) == 1
    assert updated_animation["segments"][0]["frame_duration_seconds"] == 0.5

    assert delete_response.status_code == 204
    assert empty_list_response.json() == []


def test_scene_interactions_validate_actions_and_export_json(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="user")
        create_script_audio_fixture(settings.script_audio_root)
        assert client.post("/api/admin/import-script-audio", json={}).status_code == 403

    with api_client(tmp_path) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="admin")
        create_script_audio_fixture(settings.script_audio_root)
        client.post("/api/admin/import-script-audio", json={})

        upload_response = client.post(
            "/api/uploads/batches",
            files=[("files", ("bedroom.png", png_bytes(draw_flower=True), "image/png"))],
        )
        scene = client.post(
            f"/api/uploads/batches/{upload_response.json()['id']}/process-scene"
        ).json()["scene"]
        clock = client.post(
            f"/api/scenes/{scene['id']}/objects",
            json={"name": "clock", "prompt": "clock"},
        ).json()
        bed = client.post(
            f"/api/scenes/{scene['id']}/objects",
            json={"name": "bed", "prompt": "bed"},
        ).json()
        animation = client.post(
            f"/api/scene-objects/{clock['id']}/animations",
            json={
                "name": "tick",
                "segments": [
                    {"start_frame": 0, "end_frame": 0, "frame_duration_seconds": 0.5},
                ],
            },
        ).json()
        variable_response = client.post(
            "/api/variables",
            json={
                "name": "clock_opened",
                "value_type": "bool",
                "default_value": False,
                "description": "Clock has been opened.",
            },
        )
        variable = variable_response.json()

        create_response = client.post(
            f"/api/scenes/{scene['id']}/interactions",
            json={
                "name": "Click clock",
                "enabled": True,
                "trigger": {"type": "object_click", "object_id": clock["id"]},
                "action_tree": [
                    {
                        "type": "play_audio",
                        "script_line_ids": [1, 2],
                        "wait": "wait",
                    },
                    {
                        "type": "set_object_property",
                        "target_object_id": bed["id"],
                        "property": "visible",
                        "value": True,
                    },
                    {
                        "type": "play_animation",
                        "target_object_id": clock["id"],
                        "animation_id": animation["id"],
                        "mode": "queued",
                        "wait": "continue",
                    },
                    {
                        "type": "if_variable",
                        "variable_id": variable["id"],
                        "operator": "equals",
                        "value": False,
                        "then_steps": [
                            {
                                "type": "set_variable",
                                "variable_id": variable["id"],
                                "value": True,
                            }
                        ],
                        "else_steps": [
                            {
                                "type": "show_subtitle",
                                "script_line_ids": [3],
                                "duration_seconds": 1.5,
                            }
                        ],
                    },
                ],
            },
        )
        list_response = client.get(f"/api/scenes/{scene['id']}/interactions")
        export_response = client.get(
            f"/api/scenes/{scene['id']}/interactions/validation-json"
        )

        wrong_animation_response = client.post(
            f"/api/scenes/{scene['id']}/interactions",
            json={
                "name": "Bad animation",
                "enabled": True,
                "trigger": {"type": "object_click", "object_id": bed["id"]},
                "action_tree": [
                    {
                        "type": "play_animation",
                        "target_object_id": bed["id"],
                        "animation_id": animation["id"],
                    }
                ],
            },
        )
        bad_variable_response = client.post(
            f"/api/scenes/{scene['id']}/interactions",
            json={
                "name": "Bad variable",
                "enabled": True,
                "trigger": {"type": "scene_enter"},
                "action_tree": [
                    {
                        "type": "set_variable",
                        "variable_id": variable["id"],
                        "value": "yes",
                    }
                ],
            },
        )
        missing_audio_response = client.post(
            f"/api/scenes/{scene['id']}/interactions",
            json={
                "name": "Missing audio",
                "enabled": True,
                "trigger": {"type": "scene_enter"},
                "action_tree": [
                    {
                        "type": "play_audio",
                        "script_line_ids": [99999],
                    }
                ],
            },
        )

    assert variable_response.status_code == 201
    assert variable["default_value"] is False

    assert create_response.status_code == 201
    interaction = create_response.json()
    assert interaction["trigger"] == {"type": "object_click", "object_id": clock["id"]}
    assert interaction["action_tree"][0]["selection"] == "random"
    assert interaction["action_tree"][0]["script_line_ids"] == [1, 2]
    assert interaction["action_tree"][0]["id"]
    assert interaction["action_tree"][3]["then_steps"][0]["type"] == "set_variable"

    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == interaction["id"]

    assert export_response.status_code == 200
    exported = export_response.json()
    assert exported["scene_id"] == scene["id"]
    assert exported["variables"][0]["name"] == "clock_opened"
    assert exported["interactions"][0]["name"] == "Click clock"

    assert wrong_animation_response.status_code == 400
    assert bad_variable_response.status_code == 400
    assert missing_audio_response.status_code == 400


def test_scene_vlm_analysis_updates_description_and_adds_missing_draft_objects(tmp_path):
    fake_vlm = FakeVlmProvider()
    with api_client(tmp_path, vlm_provider=fake_vlm) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="user")
        upload_response = client.post(
            "/api/uploads/batches",
            files=[("files", ("bedroom.png", png_bytes(draw_flower=True), "image/png"))],
        )
        batch_id = upload_response.json()["id"]
        scene = client.post(f"/api/uploads/batches/{batch_id}/process-scene").json()["scene"]
        client.post(
            f"/api/scenes/{scene['id']}/objects",
            json={"name": "bed", "description": "Already reviewed by a human."},
        )

        response = client.post(f"/api/scenes/{scene['id']}/analyze-vlm")

    assert response.status_code == 200
    result = response.json()
    assert fake_vlm.analyzed_path.name.endswith("bedroom.png")
    assert result["created_object_count"] == 2
    assert result["skipped_existing_object_count"] == 1
    assert result["scene"]["title"] == "Mini Bedroom"
    assert result["scene"]["description"] == "A miniature bedroom with a wooden bed and small props."
    objects_by_name = {scene_object["name"]: scene_object for scene_object in result["scene"]["objects"]}
    assert objects_by_name["bed"]["source"] == "manual"
    assert objects_by_name["lamp"]["source"] == "vlm"
    assert objects_by_name["lamp"]["prompt"] == "lamp"
    assert objects_by_name["lamp"]["category"] == "prop"
    assert objects_by_name["window"]["category"] == "fixture"


def test_scene_object_prompts_can_be_reviewed_extracted_and_removed(tmp_path):
    fake_segmentation = FakeSegmentationProvider()
    with api_client(
        tmp_path,
        segmentation_provider=fake_segmentation,
    ) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="user")
        upload_response = client.post(
            "/api/uploads/batches",
            files=[("files", ("bedroom.png", png_bytes(draw_flower=True), "image/png"))],
        )
        batch_id = upload_response.json()["id"]
        scene = client.post(f"/api/uploads/batches/{batch_id}/process-scene").json()["scene"]

        object_response = client.post(
            f"/api/scenes/{scene['id']}/objects",
            json={
                "name": "bed",
                "description": "Already reviewed by a human.",
                "prompt": "bed",
            },
        )
        scene_object = object_response.json()
        prompt_response = client.patch(
            f"/api/scenes/{scene['id']}/objects/{scene_object['id']}",
            json={"prompt": "bed with covers and pillow"},
        )
        updated_object = prompt_response.json()
        extract_response = client.post(f"/api/scenes/{scene['id']}/extract-masks")
        extract_job = wait_for_job(client, extract_response.json()["id"])
        detail_response = client.get(f"/api/scenes/{scene['id']}")
        object_detail = detail_response.json()["objects"][0]
        first_mask = object_detail["masks"][0]
        raw_response = client.get(f"/api/object-masks/{first_mask['id']}/raw")
        soft_response = client.get(f"/api/object-masks/{first_mask['id']}/soft")
        second_extract_response = client.post(f"/api/scenes/{scene['id']}/extract-masks")
        second_extract_job = wait_for_job(client, second_extract_response.json()["id"])
        changed_prompt_response = client.patch(
            f"/api/scenes/{scene['id']}/objects/{scene_object['id']}",
            json={"prompt": "bed with covers and pillow plus blanket"},
        )
        changed_extract_response = client.post(f"/api/scenes/{scene['id']}/extract-masks")
        changed_extract_job = wait_for_job(client, changed_extract_response.json()["id"])
        changed_detail_response = client.get(f"/api/scenes/{scene['id']}")
        delete_response = client.delete(
            f"/api/scenes/{scene['id']}/objects/{scene_object['id']}"
        )
        deleted_detail_response = client.get(f"/api/scenes/{scene['id']}")

    assert object_response.status_code == 201
    assert scene_object["prompt"] == "bed"
    assert prompt_response.status_code == 200
    assert updated_object["prompt"] == "bed with covers and pillow"

    assert extract_response.status_code == 200
    assert extract_response.json()["status"] == "queued"
    assert extract_job["status"] == "succeeded"
    result = json.loads(extract_job["result_json"])
    assert fake_segmentation.prompt_calls[0] == ["bed with covers and pillow"]
    assert result["processed_image_count"] == 1
    assert result["created_candidate_count"] == 1
    assert object_detail["mask_image_count"] == 1
    assert first_mask["prompt_text"] == "bed with covers and pillow"
    assert first_mask["score"] == 0.95
    assert (settings.storage_root / first_mask["relative_path"]).exists()
    assert (settings.storage_root / first_mask["soft_relative_path"]).exists()

    assert raw_response.status_code == 200
    assert raw_response.headers["content-type"] == "image/png"
    assert raw_response.headers["cache-control"] == "no-store, max-age=0"
    assert soft_response.status_code == 200
    assert soft_response.headers["cache-control"] == "no-store, max-age=0"

    assert second_extract_response.status_code == 200
    assert second_extract_job["status"] == "succeeded"
    second_result = json.loads(second_extract_job["result_json"])
    assert second_result["created_candidate_count"] == 0
    assert second_result["skipped_existing_count"] == 1
    assert changed_prompt_response.status_code == 200
    assert changed_prompt_response.json()["prompt"] == "bed with covers and pillow plus blanket"
    assert changed_extract_response.status_code == 200
    assert changed_extract_job["status"] == "succeeded"
    changed_result = json.loads(changed_extract_job["result_json"])
    assert fake_segmentation.prompt_calls[-1] == ["bed with covers and pillow plus blanket"]
    assert changed_result["created_candidate_count"] == 1
    assert len(changed_detail_response.json()["objects"][0]["masks"]) == 2
    assert delete_response.status_code == 204
    assert deleted_detail_response.json()["objects"] == []


def test_scene_preview_data_renders_default_and_animation_frames_only(tmp_path):
    fake_segmentation = FakeSegmentationProvider()
    with api_client(
        tmp_path,
        segmentation_provider=fake_segmentation,
    ) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="user")
        upload_response = client.post(
            "/api/uploads/batches",
            files=[
                ("files", ("bedroom_0002.png", png_bytes(draw_flower=True), "image/png")),
                ("files", ("bedroom_0000.png", png_bytes(draw_flower=False), "image/png")),
                ("files", ("bedroom_0001.png", png_bytes(draw_flower=True), "image/png")),
            ],
        )
        batch_id = upload_response.json()["id"]
        scene = client.post(f"/api/uploads/batches/{batch_id}/process-scene").json()["scene"]
        scene_object = client.post(
            f"/api/scenes/{scene['id']}/objects",
            json={"name": "bed", "prompt": "bed"},
        ).json()
        extract_response = client.post(f"/api/scenes/{scene['id']}/extract-masks")
        extract_job = wait_for_job(client, extract_response.json()["id"])
        assert extract_job["status"] == "succeeded"

        animation_response = client.post(
            f"/api/scene-objects/{scene_object['id']}/animations",
            json={
                "name": "idle",
                "segments": [
                    {"start_frame": 0, "end_frame": 1, "frame_duration_seconds": 0.25},
                ],
            },
        )
        preview_response = client.get(f"/api/scenes/{scene['id']}/preview-data")

        assert animation_response.status_code == 201
        assert preview_response.status_code == 200
        preview = preview_response.json()
        assert [image["original_filename"] for image in preview["images"]] == [
            "bedroom_0000.png",
            "bedroom_0001.png",
            "bedroom_0002.png",
        ]
        assert preview["width"] == 96
        assert preview["height"] == 54

        preview_object = preview["objects"][0]
        assert preview_object["name"] == "bed"
        assert preview_object["default_render"]["original_filename"] == "bedroom_0000.png"
        assert preview_object["default_render"]["frame_index"] == 0
        assert preview_object["default_render"]["url"].startswith(
            f"/api/scene-objects/{scene_object['id']}/preview-renders/"
        )

        animation = preview_object["animations"][0]
        assert animation["name"] == "idle"
        assert [frame["frame_index"] for frame in animation["frames"]] == [0, 1]
        assert [frame["original_filename"] for frame in animation["frames"]] == [
            "bedroom_0000.png",
            "bedroom_0001.png",
        ]
        assert all(frame["render"] for frame in animation["frames"])

        preview_root = (
            settings.storage_root
            / settings.organization_id
            / "derived"
            / "scenes"
            / str(scene["id"])
            / "objects"
            / str(scene_object["id"])
            / "preview"
        )
        rendered_files = sorted(path.name for path in preview_root.glob("*.png"))
        assert rendered_files == [
            str(preview["images"][0]["uploaded_file_id"]) + ".png",
            str(preview["images"][1]["uploaded_file_id"]) + ".png",
        ]

        first_render_response = client.get(
            f"/api/scene-objects/{scene_object['id']}/preview-renders/{preview['images'][0]['uploaded_file_id']}"
        )
        second_render_response = client.get(
            f"/api/scene-objects/{scene_object['id']}/preview-renders/{preview['images'][1]['uploaded_file_id']}"
        )
        missing_render_response = client.get(
            f"/api/scene-objects/{scene_object['id']}/preview-renders/{preview['images'][2]['uploaded_file_id']}"
        )

        assert first_render_response.status_code == 200
        assert second_render_response.status_code == 200
        assert missing_render_response.status_code == 200


def test_scene_preview_cache_key_changes_after_mask_edit(tmp_path):
    fake_segmentation = FakeSegmentationProvider()
    with api_client(
        tmp_path,
        segmentation_provider=fake_segmentation,
    ) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="user")
        upload_response = client.post(
            "/api/uploads/batches",
            files=[("files", ("bedroom.png", png_bytes(draw_flower=True), "image/png"))],
        )
        batch_id = upload_response.json()["id"]
        scene = client.post(f"/api/uploads/batches/{batch_id}/process-scene").json()["scene"]
        scene_object = client.post(
            f"/api/scenes/{scene['id']}/objects",
            json={"name": "bed", "prompt": "bed"},
        ).json()
        extract_response = client.post(f"/api/scenes/{scene['id']}/extract-masks")
        extract_job = wait_for_job(client, extract_response.json()["id"])
        assert extract_job["status"] == "succeeded"

        first_preview = client.get(f"/api/scenes/{scene['id']}/preview-data").json()
        first_render = first_preview["objects"][0]["default_render"]
        mask_id = first_render["object_mask_id"]

        edited_mask = Image.new("L", (16, 9), 255)
        ImageDraw.Draw(edited_mask).rectangle((0, 0, 6, 8), fill=0)
        save_response = client.put(
            f"/api/object-masks/{mask_id}/content",
            content=image_bytes(edited_mask),
            headers={"Content-Type": "image/png"},
        )
        second_preview = client.get(f"/api/scenes/{scene['id']}/preview-data").json()
        second_render = second_preview["objects"][0]["default_render"]

        assert save_response.status_code == 200
        assert first_render["cache_key"] != second_render["cache_key"]
        assert first_render["url"] != second_render["url"]


def test_object_mask_content_can_be_saved_and_processed(tmp_path):
    fake_segmentation = FakeSegmentationProvider()
    with api_client(
        tmp_path,
        segmentation_provider=fake_segmentation,
    ) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="user")
        upload_response = client.post(
            "/api/uploads/batches",
            files=[("files", ("bedroom.png", png_bytes(draw_flower=True), "image/png"))],
        )
        batch_id = upload_response.json()["id"]
        scene = client.post(f"/api/uploads/batches/{batch_id}/process-scene").json()["scene"]
        client.post(
            f"/api/scenes/{scene['id']}/objects",
            json={"name": "bed", "prompt": "bed"},
        )
        extract_response = client.post(f"/api/scenes/{scene['id']}/extract-masks")
        wait_for_job(client, extract_response.json()["id"])
        detail = client.get(f"/api/scenes/{scene['id']}").json()
        mask = detail["objects"][0]["masks"][0]
        object_id = detail["objects"][0]["id"]
        thumbnail_response = client.get(f"/api/scene-objects/{object_id}/thumbnail")

        edited = Image.new("L", (16, 9), 0)
        draw = ImageDraw.Draw(edited)
        draw.rectangle((6, 3, 9, 6), fill=255)
        save_response = client.put(
            f"/api/object-masks/{mask['id']}/content",
            content=image_bytes(edited),
            headers={"Content-Type": "image/png"},
        )
        grow_response = client.post(
            f"/api/object-masks/{mask['id']}/process",
            json={"operation": "grow", "pixels": 1},
        )

        hole_mask = Image.new("L", (16, 9), 0)
        draw = ImageDraw.Draw(hole_mask)
        draw.rectangle((3, 2, 12, 7), fill=255)
        draw.rectangle((7, 4, 8, 5), fill=0)
        client.put(
            f"/api/object-masks/{mask['id']}/content",
            content=image_bytes(hole_mask),
            headers={"Content-Type": "image/png"},
        )
        fill_response = client.post(
            f"/api/object-masks/{mask['id']}/process",
            json={"operation": "fill_holes"},
        )
        updated_thumbnail_response = client.get(f"/api/scene-objects/{object_id}/thumbnail")

    raw_path = settings.storage_root / mask["relative_path"]
    assert thumbnail_response.status_code == 200
    assert thumbnail_response.headers["content-type"] == "image/png"
    with Image.open(BytesIO(thumbnail_response.content)) as thumbnail:
        assert thumbnail.mode == "RGBA"
        assert thumbnail.width <= 256
        assert thumbnail.height <= 256
    assert save_response.status_code == 200
    assert grow_response.status_code == 200
    with Image.open(raw_path) as grown:
        assert grown.convert("L").getpixel((5, 3)) == 255
    assert fill_response.status_code == 200
    with Image.open(raw_path) as filled:
        assert filled.convert("L").getpixel((7, 4)) == 255
    assert updated_thumbnail_response.status_code == 200


def test_admin_can_reset_workspace_tables_without_removing_users_or_session(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        admin = create_or_promote_admin(
            db_path,
            organization_id=settings.organization_id,
            email="admin@example.com",
            display_name="Admin User",
        )
        session_token, _ = create_session(db_path, admin["id"])
        client.cookies.set(settings.session_cookie_name, session_token)
        client.post(
            "/api/assets",
            json={"name": "Temp asset", "asset_type": "image"},
        )
        upload_response = client.post(
            "/api/uploads/batches",
            files=[("files", ("bedroom.png", png_bytes(draw_flower=True), "image/png"))],
        )
        batch_id = upload_response.json()["id"]
        client.post(f"/api/uploads/batches/{batch_id}/process-scene")
        client.post("/api/invites", json={"role": "user"})

        reset_response = client.post("/api/admin/reset-database")
        session_response = client.get("/api/auth/session")
        scenes_response = client.get("/api/scenes")
        uploads_response = client.get("/api/uploads/batches")
        assets_response = client.get("/api/assets")

    assert reset_response.status_code == 200
    assert reset_response.json()["ok"] is True
    assert "users" not in reset_response.json()["cleared_tables"]
    assert "sessions" not in reset_response.json()["cleared_tables"]
    assert session_response.status_code == 200
    assert session_response.json()["user"]["email"] == "admin@example.com"
    assert scenes_response.json() == []
    assert uploads_response.json() == []
    assert assets_response.json() == []


def test_regular_user_cannot_reset_workspace_tables(tmp_path):
    with api_client(tmp_path) as (client, db_path, settings):
        authenticate(client, db_path, settings, role="user")

        response = client.post("/api/admin/reset-database")

    assert response.status_code == 403


def test_google_login_requires_oauth_configuration(tmp_path):
    with api_client(tmp_path) as (client, _, _):
        response = client.get("/api/auth/google/login", follow_redirects=False)

    assert response.status_code == 503


class FakeVlmProvider:
    def __init__(self):
        self.analyzed_path = Path()

    async def analyze_scene(self, image_path: Path) -> SceneDraft:
        self.analyzed_path = image_path
        return SceneDraft(
            scene_description="A miniature bedroom with a wooden bed and small props.",
            scene_key="mini_bedroom",
            objects=[
                SceneDraftObject(
                    name="bed",
                    category="furniture",
                    description="A wooden bed with bedding.",
                ),
                SceneDraftObject(
                    name="lamp",
                    category="prop",
                    description="A small bedside lamp.",
                ),
                SceneDraftObject(
                    name="window",
                    category="fixture",
                    description="A window on the back wall.",
                ),
            ],
        )


class FakeSegmentationProvider:
    def __init__(self):
        self.prompts = []
        self.prompt_calls = []
        self.image_calls = []

    async def extract_masks(
        self,
        image_path: Path,
        prompts: list[str],
        output_dir: Path,
    ) -> list[SegmentationPromptResult]:
        self.prompts = prompts
        self.prompt_calls.append(prompts)
        self.image_calls.append(image_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        raw_path = output_dir / "bed_with_covers_00.png"
        soft_path = output_dir / "bed_with_covers_00_soft.png"
        Image.new("L", (16, 9), 255).save(raw_path)
        Image.new("L", (16, 9), 128).save(soft_path)
        lower_raw_path = output_dir / "bed_with_covers_01.png"
        lower_soft_path = output_dir / "bed_with_covers_01_soft.png"
        Image.new("L", (16, 9), 64).save(lower_raw_path)
        Image.new("L", (16, 9), 32).save(lower_soft_path)
        return [
            SegmentationPromptResult(
                prompt=prompts[0],
                candidates=[
                    SegmentationCandidate(
                        raw_path=lower_raw_path,
                        soft_path=lower_soft_path,
                        bbox=[5.0, 6.0, 7.0, 8.0],
                        score=0.25,
                    ),
                    SegmentationCandidate(
                        raw_path=raw_path,
                        soft_path=soft_path,
                        bbox=[1.0, 2.0, 3.0, 4.0],
                        score=0.95,
                    )
                ],
            )
        ]


def png_bytes(draw_flower: bool) -> bytes:
    image = Image.new("RGB", (96, 54), "#d6c0a1")
    draw = ImageDraw.Draw(image)
    draw.rectangle((18, 28, 58, 42), fill="#8b5a2b")
    draw.rectangle((24, 20, 52, 32), fill="#a86f37")
    draw.rectangle((62, 18, 76, 42), fill="#3d372f")
    draw.ellipse((8, 24, 18, 34), fill="#ddd8cd", outline="#444444")
    if draw_flower:
        draw.rectangle((70, 14, 73, 26), fill="#2f8f4e")
        draw.ellipse((66, 9, 76, 19), fill="#d85f91")

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def image_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
