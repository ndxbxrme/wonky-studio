# Wonky Studio

Internal asset tooling for a point-and-click adventure game built from real-world diorama photography. The current focus is scene intake, object inventory, AI-assisted mask generation, animation authoring, script/audio review, action authoring, and live scene preview.

## Run Locally

Backend:

```bash
cd backend
source .venv/bin/activate
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --env-file .env
```

Frontend:

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173/`. The API runs at `http://127.0.0.1:8000/`.

In development, the frontend uses a Vite `/api` proxy to the backend. Browser code should use relative `/api/...` paths rather than hardcoding `127.0.0.1:8000`.

Tests:

```bash
cd backend && .venv/bin/pytest
cd frontend && npm run build && npm run test:e2e
```

## Environment

Backend config is read from `backend/.env` when started with `--env-file .env`.

Useful values:

```bash
WONKY_STUDIO_ORGANIZATION_ID=wonky-studio
WONKY_STUDIO_FRONTEND_URL=http://127.0.0.1:5173
WONKY_STUDIO_API_BASE_URL=http://127.0.0.1:8000
WONKY_STUDIO_STORAGE_ROOT=/mnt/d/wonky-studio/uploads
WONKY_STUDIO_GOOGLE_CLIENT_ID=...
WONKY_STUDIO_GOOGLE_CLIENT_SECRET=...
WONKY_STUDIO_GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/api/auth/google/callback
WONKY_STUDIO_VLM_PROVIDER=ollama
WONKY_STUDIO_VLM_MODEL=gemma3:4b
WONKY_STUDIO_VLM_KEEP_ALIVE=0
WONKY_STUDIO_SEGMENTATION_PROVIDER=sam3-subprocess
WONKY_STUDIO_SEGMENTATION_CONDA_ENV=sam3
```

The default SQLite database is `backend/data/wonky-studio.sqlite3`. Uploaded and derived files should live on the D: drive in WSL via `/mnt/d/wonky-studio/uploads` because the repo drive is space-limited.

Create/promote the first admin:

```bash
cd backend
source .venv/bin/activate
python -m scripts.create_admin you@example.com --name "Your Name"
```

## What Exists

Authentication:

- Google OAuth login.
- Session cookie auth.
- Roles: `admin` and `user`.
- Admins can create invite links and reset development workspace tables without deleting users/sessions.

Upload and scene grouping:

- Logged-in users can drag/drop batches of files.
- Uploads are stored under `WONKY_STUDIO_STORAGE_ROOT`.
- Image batches can be processed into scenes.
- Similar images uploaded in later batches are matched back into an existing scene using local image fingerprints.
- Scene frames are sorted by natural original filename order, not drag arrival order.

Scene analysis:

- VLM provider abstraction in `backend/app/vlm.py`.
- Current practical path is Ollama with Gemma/Qwen-style local VLMs.
- VLM analysis updates scene description/title and creates draft objects.

Objects and masks:

- Objects have editable segmentation prompts.
- Mask extraction is queued as a background job.
- Segmentation provider abstraction in `backend/app/segmentation.py`.
- Current practical path is SAM3 via a conda subprocess using `tools/sam3_smoke.py`.
- Extraction stores one top-scoring mask per object/frame/prompt.
- Changing an object prompt causes new masks to render while previous mask rows remain untouched.

Manual mask editor:

- Route: `/mask-editor/{sceneId}/{objectId}/{maskId}`.
- Left mouse draws, right mouse erases, middle mouse pans, mouse wheel zooms.
- Controls: brush size, hardness, overlay opacity, display mode, undo/redo, previous/next frame.
- Keyboard shortcuts: `ArrowLeft`/`a` previous frame, `ArrowRight`/`d` next frame, `s` save.
- Display modes: overlay, mask only, masked image.
- Server-side operations: grow mask and fill holes, optionally applied to all masks for the object.
- “Apply to all frames” for brush edits replays the current frame’s brush strokes over every mask, instead of copying one mask to all frames.

Object thumbnails:

- Scene object list shows one server-rendered thumbnail per object.
- The thumbnail uses the first valid mask in frame order.
- Thumbnails are cropped to the object bounds and rendered as transparent PNGs.
- Thumbnail rendering uses `backend/app/object_rendering.py`, which should be reused later for animation/final object rendering.
- Thumbnail URLs include mask cache keys, and derived thumbnails rerender when source/mask files change.

Animations:

- Each object can have multiple named animations.
- Animations are defined as ordered frame ranges with per-frame duration.
- Route: `/animations/{sceneId}/{objectId}`.
- The animation editor previews saved frame sequences and supports a background object for context.
- Keyboard shortcuts: `ArrowLeft`/`a` previous preview frame, `ArrowRight`/`d` next preview frame, `s` save current animation.

Script/audio review:

- Admin import route loads the script and audio manifests from `WONKY_STUDIO_SCRIPT_AUDIO_ROOT`.
- Route: `/script-review`.
- Script lines are searchable by path/text/language.
- Each translation and audio candidate has review state, notes, and audio preview.

Audio library:

- Route: `/audio-library`.
- Upload and organize looping background music (`bgm`) and one-shot sound effects (`sfx`).
- These assets are used by preview/runtime actions rather than subtitle-bearing script playback.

Actions:

- Route: `/actions/{sceneId}`.
- Global variables: `bool`, `string`, `number`.
- Scene interactions support scene/object/variable triggers.
- Action steps are structured and validated, not free-form script text.
- Supported steps today: `play_animation`, `set_object_property`, `show_subtitle`, `play_audio`, `set_variable`, `increment_variable`, `toggle_variable`, `if_variable`, `fade_out`, `fade_in`, `crossfade_bgm`, `play_sfx`, `change_scene`, `delay`.
- Scene pages show action counts plus per-object action summaries with links back into the action editor.

Scene preview:

- Route: `/preview/{sceneId}`.
- Opened from the scene page or actions page in a popout window.
- Uses cached server-rendered object crops, not raw masks in the browser.
- Renders each object’s first valid frame plus any frames referenced by saved animations.
- Uses a canvas renderer for deterministic composition and playback.
- Background can be toggled on/off for object inspection.
- The currently playing object is drawn on top of the stack during playback.
- Listens for editor updates in the same browser via `BroadcastChannel` and refreshes automatically.

## Backend Map

- `backend/app/main.py`: FastAPI app, routes, auth dependencies, processing worker, mask editor endpoints, script/audio review, actions validation, and scene preview payload/render endpoints.
- `backend/app/database.py`: SQLite schema and data access functions for uploads, scenes, masks, animations, script review, variables, and interactions. There is no external migration tool yet; schema changes are handled in `init_database`.
- `backend/app/config.py`: environment-driven settings.
- `backend/app/security.py`: tokens/session helpers.
- `backend/app/scene_processing.py`: upload batch to scene matching.
- `backend/app/vlm.py`: VLM provider abstraction and Ollama implementation.
- `backend/app/segmentation.py`: segmentation provider abstraction and SAM3 subprocess implementation.
- `backend/app/object_rendering.py`: reusable object crop/render helpers used for thumbnails and preview renders.
- `backend/app/script_import.py`: imports script line, translation, and audio candidate data from local manifests.
- `backend/tests/e2e/test_api.py`: backend e2e coverage for auth, uploads, scenes, VLM, mask extraction, mask editing, thumbnails, script/audio review, actions, and preview payloads.

## Frontend Map

- `frontend/src/main.js`: creates the Turbomini app and starts routing.
- `frontend/src/routing.js`: registers templates, controllers, helpers, and auth middleware.
- `frontend/src/api.js`: API wrapper and URL builders.
- `frontend/src/auth-middleware.js`: redirects unauthenticated users to `/not-authorized`.
- `frontend/src/preview-sync.js`: `BroadcastChannel` helpers for preview invalidation and popout launch.
- `frontend/src/state/user.js`: shared current user/session state.
- `frontend/src/state/scenes.js`: shared scene cache and scene preparation helpers.
- `frontend/src/components/default.*`: home/upload/admin/scene list route.
- `frontend/src/components/scene.*`: scene detail route.
- `frontend/src/components/mask-editor.*`: full-screen mask editor route.
- `frontend/src/components/mask-editor-element.js`: canvas editor web component.
- `frontend/src/components/animations.*`: animation authoring route.
- `frontend/src/components/animation-preview-element.js`: animation preview surface.
- `frontend/src/components/script-review.*`: script/audio review route.
- `frontend/src/components/actions.*`: actions/variables authoring route.
- `frontend/src/components/preview.*`: popout scene preview route.
- `frontend/src/components/scene-preview-element.js`: canvas-based cached scene composition preview surface.
- `frontend/src/app.css`: global app styles.

## Turbomini Notes

Turbomini is a tiny SPA router/template layer in `frontend/src/turbomini.js`. It is not React/Vue/Angular: state is plain JavaScript objects, templates are HTML strings, and controllers return objects consumed by templates.

Routes:

- A route is registered with `app.template(name, html)` and `app.controller(name, Controller(app))`.
- Route matching is prefix-based from the URL path. `/scene/1` uses the `scene` route and receives `["1"]` as params.
- Current routes: `default`, `not-authorized`, `scene`, `mask-editor`, `animations`, `script-review`, `actions`, `preview`.

Controller pattern:

```js
const SceneCtrl = app => async params => {
  const controller = {
    sceneId: Number(params[0]),
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-scene-page]');
      this.bind(this.root, 'click', event => this.onClick(event));
    },

    unload() {
      this.unloadHandlers.forEach(unload => unload());
      this.unloadHandlers = [];
    },

    bind(target, type, handler) {
      if (!target) return;
      target.addEventListener(type, handler);
      this.unloadHandlers.push(() => target.removeEventListener(type, handler));
    }
  };

  return controller;
};
```

Preferred conventions:

- Controllers return a controller object. Mutate that object and call `app.refresh()` to rerender.
- Use delegated event handling with `event.target.closest('[data-action="..."]')`.
- Put route-specific event listeners in `postLoad()` and remove them in `unload()`.
- Use shared modules for state that multiple routes need, such as `state/user.js` and `state/scenes.js`.
- Use `app.refresh()` for UI updates in the current route. Use `app.goto(path)` for navigation.
- Avoid direct per-row event listeners in templates; prefer data attributes and delegation.

Templates:

- Templates are raw HTML files imported in `routing.js`.
- Supported basics include `{{value}}`, `{{#if value}}...{{/if}}`, and `{{#each items as item}}...{{/each}}`.
- Helpers are registered in `routing.js`, for example `formatBytes`.
- Keep templates mostly declarative; put behavior in the controller or a web component.

When to use a web component:

- Use a web component for self-contained interactive surfaces that need direct DOM/canvas control.
- The mask editor is a good example: Turbomini owns route/data loading; `<wonky-mask-editor>` owns pointer events, canvas drawing, undo/redo, zoom/pan, and export.

## Current Workflow

1. Sign in with Google.
2. Drag image batches into the browser.
3. Click **Process scene** on an upload batch.
4. Open a scene.
5. Optionally run VLM analysis to draft objects.
6. Edit object names/prompts manually as needed.
7. Click **Extract masks** to queue SAM3 extraction.
8. Use object thumbnails/list to open the mask editor and clean masks.
9. Open `/animations/{sceneId}/{objectId}` to define reusable frame sequences.
10. Open `/actions/{sceneId}` to define triggers, variables, and action sequences.
11. Open `/preview/{sceneId}` from the scene/actions UI to test cached object playback in a live popout.
12. Use `/script-review` to import, search, and review dialog/translations/audio candidates.

## Known Design Choices

- Scene/object identity is still pragmatic and local-first; no multi-org UI yet, though `organization_id` exists everywhere.
- Scene frame order should always come from natural sorting of original filenames.
- Object prompt text is the extraction key. Existing masks are preserved when a prompt changes.
- Derived files are stored under `derived/scenes/...` inside the storage root.
- Manual mask edits overwrite the raw and soft mask files for now.
- Preview invalidation currently uses `BroadcastChannel`, so automatic refresh works between windows in the same browser profile.
- The preview is a runtime foundation, not a full game player yet. It currently supports cached composition and manual animation playback, not full authored interaction execution.
- Default object layering is still implicit. During preview playback the currently animating object is temporarily drawn last.
