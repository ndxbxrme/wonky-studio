# Wonky Studio

Internal asset tooling for a point-and-click adventure game built from real-world diorama photography. The current focus is scene intake, object inventory, AI-assisted mask generation, and manual mask cleanup.

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
- Display modes: overlay, mask only, masked image.
- Server-side operations: grow mask and fill holes, optionally applied to all masks for the object.
- “Apply to all frames” for brush edits replays the current frame’s brush strokes over every mask, instead of copying one mask to all frames.

Object thumbnails:

- Scene object list shows one server-rendered thumbnail per object.
- The thumbnail uses the first valid mask in frame order.
- Thumbnails are cropped to the object bounds and rendered as transparent PNGs.
- Thumbnail rendering uses `backend/app/object_rendering.py`, which should be reused later for animation/final object rendering.
- Thumbnail URLs include mask cache keys, and derived thumbnails rerender when source/mask files change.

## Backend Map

- `backend/app/main.py`: FastAPI app, routes, auth dependencies, job worker, mask editor endpoints.
- `backend/app/database.py`: SQLite schema and data access functions. There is no external migration tool yet; schema changes are handled in `init_database`.
- `backend/app/config.py`: environment-driven settings.
- `backend/app/security.py`: tokens/session helpers.
- `backend/app/scene_processing.py`: upload batch to scene matching.
- `backend/app/vlm.py`: VLM provider abstraction and Ollama implementation.
- `backend/app/segmentation.py`: segmentation provider abstraction and SAM3 subprocess implementation.
- `backend/app/object_rendering.py`: reusable object crop/render helpers.
- `backend/tests/e2e/test_api.py`: backend e2e coverage for auth, uploads, scenes, VLM, mask extraction, mask editing, thumbnails.

## Frontend Map

- `frontend/src/main.js`: creates the Turbomini app and starts routing.
- `frontend/src/routing.js`: registers templates, controllers, helpers, and auth middleware.
- `frontend/src/api.js`: API wrapper and URL builders.
- `frontend/src/auth-middleware.js`: redirects unauthenticated users to `/not-authorized`.
- `frontend/src/state/user.js`: shared current user/session state.
- `frontend/src/state/scenes.js`: shared scene cache and scene preparation helpers.
- `frontend/src/components/default.*`: home/upload/admin/scene list route.
- `frontend/src/components/scene.*`: scene detail route.
- `frontend/src/components/mask-editor.*`: full-screen mask editor route.
- `frontend/src/components/mask-editor-element.js`: canvas editor web component.
- `frontend/src/app.css`: global app styles.

## Turbomini Notes

Turbomini is a tiny SPA router/template layer in `frontend/src/turbomini.js`. It is not React/Vue/Angular: state is plain JavaScript objects, templates are HTML strings, and controllers return objects consumed by templates.

Routes:

- A route is registered with `app.template(name, html)` and `app.controller(name, Controller(app))`.
- Route matching is prefix-based from the URL path. `/scene/1` uses the `scene` route and receives `["1"]` as params.
- Current routes: `default`, `not-authorized`, `scene`, `mask-editor`.

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
8. Use object thumbnails/list to open the mask editor.
9. Clean masks frame-by-frame or apply operations/brush edits across all frames.

## Known Design Choices

- Scene/object identity is still pragmatic and local-first; no multi-org UI yet, though `organization_id` exists everywhere.
- Scene frame order should always come from natural sorting of original filenames.
- Object prompt text is the extraction key. Existing masks are preserved when a prompt changes.
- Derived files are stored under `derived/scenes/...` inside the storage root.
- Manual mask edits overwrite the raw and soft mask files for now.
