import {apiUrl, uploadedFileUrl} from '../api.js';

class WonkyScenePreviewElement extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: 'open'});
    this.preview = null;
    this.currentSubtitle = null;
    this.runtimeObjectStates = {};
    this.showBackground = true;
    this.transparentStage = false;
    this.currentBackgroundUrl = '';
    this.currentObjectRenders = new Map();
    this.activeObjectIds = new Set();
    this.objectPlaybackState = new Map();
    this.hoveredObjectId = null;
    this.focusedObjectId = null;
    this.useExternalCursor = false;
    this.longPressTimer = null;
    this.longPressTriggered = false;
    this.pendingImageUrls = new Set();
    this.resizeObserver = new ResizeObserver(() => this.renderCanvas());
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          width: 100%;
          height: 100%;
          min-height: 320px;
        }

        .shell {
          width: 100%;
          height: 100%;
          display: grid;
          place-items: center;
          background: #10171d;
          border-radius: 8px;
          overflow: hidden;
        }

        .shell.is-transparent {
          background: transparent;
          border-radius: 0;
        }

        .stage {
          width: 100%;
          max-width: 100%;
          max-height: 100%;
          aspect-ratio: var(--scene-width, 16) / var(--scene-height, 9);
          background: #18212a;
          display: grid;
          position: relative;
          place-self: center;
        }

        .stage.is-transparent {
          background: transparent;
        }

        canvas {
          width: 100%;
          height: 100%;
          display: block;
          background: #18212a;
          cursor: default;
        }

        .stage.is-transparent canvas {
          background: transparent;
        }

        .subtitles {
          position: absolute;
          left: 28px;
          right: 28px;
          bottom: 34px;
          display: grid;
          justify-items: center;
          pointer-events: none;
        }

        .subtitle-card {
          max-width: min(100%, 82%);
          padding: 12px 18px 14px;
          border-radius: 12px;
          background: rgba(12, 18, 24, 0.82);
          box-shadow: 0 16px 36px rgba(0, 0, 0, 0.28);
          text-align: center;
          color: #f7fbff;
        }

        .subtitle-card.is-entering {
          animation: subtitle-settle-in 180ms cubic-bezier(0.2, 0.9, 0.22, 1.08);
        }

        .subtitle-primary,
        .subtitle-secondary {
          margin: 0;
          line-height: 1.25;
        }

        .subtitle-secondary {
          margin-top: 4px;
          color: #c8e2ff;
        }

        .subtitle-card.is-large .subtitle-primary {
          font-size: 1.55rem;
        }

        .subtitle-card.is-large .subtitle-secondary {
          font-size: 1.2rem;
        }

        .subtitle-card.is-medium .subtitle-primary {
          font-size: 1.35rem;
        }

        .subtitle-card.is-medium .subtitle-secondary {
          font-size: 1.05rem;
        }

        .subtitle-card.is-small .subtitle-primary {
          font-size: 1.12rem;
        }

        .subtitle-card.is-small .subtitle-secondary {
          font-size: 0.94rem;
        }

        .subtitle-card.is-xsmall .subtitle-primary {
          font-size: 0.98rem;
        }

        .subtitle-card.is-xsmall .subtitle-secondary {
          font-size: 0.84rem;
        }

        @keyframes subtitle-settle-in {
          0% {
            opacity: 0;
            transform: translateY(8px) scale(0.985);
          }
          100% {
            opacity: 1;
            transform: translateY(0) scale(1);
          }
        }

        .empty {
          color: #d0d8de;
          font: 600 0.95rem/1.4 system-ui, sans-serif;
        }
      </style>
      <div class="shell">
        <div class="empty">Preview unavailable.</div>
      </div>
    `;
  }

  setUseExternalCursor(active) {
    this.useExternalCursor = Boolean(active);
    this.setCanvasCursor(Boolean(this.hoveredObjectId));
  }

  connectedCallback() {
    this.resizeObserver.observe(this);
  }

  disconnectedCallback() {
    this.resizeObserver.disconnect();
    this.cancelLongPress();
    this.pendingImageUrls.clear();
    this.stop();
  }

  async configure(preview, options = {}) {
    this.preview = preview;
    this.showBackground = preview?.showBackground !== false;
    this.transparentStage = preview?.transparentStage === true;
    this.currentObjectRenders.clear();
    this.activeObjectIds.clear();
    this.objectPlaybackState.clear();
    this.hoveredObjectId = null;
    this.pendingImageUrls.clear();
    if (!preview?.images?.length) {
      this.renderEmpty();
      return;
    }
    this.renderStage();
    try {
      await this.primeImages(preview, options);
    } catch (error) {
      this.dispatchPreviewError(error);
      this.renderEmpty();
      return;
    }
    this.setDefaultState();
    this.renderCanvas();
  }

  applyRuntimeState(runtimeObjectStates) {
    const runtimeState = runtimeObjectStates?.objects ? runtimeObjectStates : {objects: runtimeObjectStates ?? {}};
    this.runtimeObjectStates = runtimeState.objects ?? {};
    for (const [objectId, state] of Object.entries(this.runtimeObjectStates)) {
      const numericId = Number(objectId);
      if (state?.render) this.currentObjectRenders.set(numericId, state.render);
      else this.currentObjectRenders.delete(numericId);
    }
    if (runtimeState.background_frame_index !== undefined) {
      this.setBackgroundFrameIndex(runtimeState.background_frame_index);
    }
    this.syncHoveredObjectState();
    this.renderCanvas();
  }

  setSubtitle(subtitle) {
    this.currentSubtitle = subtitle ?? null;
    this.renderSubtitleOverlay();
  }

  setFocusedObjectId(objectId) {
    const numericId = Number(objectId);
    this.focusedObjectId = Number.isFinite(numericId) && numericId > 0 ? numericId : null;
    this.renderCanvas();
  }

  renderEmpty() {
    const shell = this.shadowRoot.querySelector('.shell');
    if (!shell) return;
    shell.innerHTML = '<div class="empty">Preview unavailable.</div>';
  }

  renderStage() {
    const shell = this.shadowRoot.querySelector('.shell');
    if (!shell) return;
    shell.classList.toggle('is-transparent', this.transparentStage);
    shell.innerHTML = `
      <div
        class="stage ${this.transparentStage ? 'is-transparent' : ''}"
        style="--scene-width:${Math.max(1, this.preview.width || 1)}; --scene-height:${Math.max(1, this.preview.height || 1)};"
      >
        <canvas data-preview-canvas></canvas>
        <div class="subtitles" data-preview-subtitles></div>
      </div>
    `;
    this.canvas = this.shadowRoot.querySelector('[data-preview-canvas]');
    this.context = this.canvas?.getContext('2d');
    this.canvas?.addEventListener('click', event => this.onCanvasClick(event));
    this.canvas?.addEventListener('contextmenu', event => this.onCanvasContextMenu(event));
    this.canvas?.addEventListener('pointerdown', event => this.onCanvasPointerDown(event));
    this.canvas?.addEventListener('pointerup', () => this.cancelLongPress());
    this.canvas?.addEventListener('pointercancel', () => this.cancelLongPress());
    this.canvas?.addEventListener('pointermove', event => this.onCanvasPointerMove(event));
    this.canvas?.addEventListener('pointerleave', () => this.onCanvasPointerLeave());
    this.renderSubtitleOverlay();
  }

  async primeImages(preview, options = {}) {
    await preloadPreviewAssets(preview, options);
  }

  setDefaultState() {
    this.setBackgroundFrameIndex(this.preview?.background_frame_index ?? 0);
    this.currentObjectRenders.clear();
    for (const object of this.preview?.objects ?? []) {
      if (object.default_render) this.currentObjectRenders.set(Number(object.id), object.default_render);
    }
    this.runtimeObjectStates = Object.fromEntries(
      (this.preview?.objects ?? []).map(object => [
        object.id,
        {
          visible: object.visible !== false,
          enabled: object.enabled !== false,
          label: object.label || object.name,
          render: object.default_render ?? null
        }
      ])
    );
  }

  setBackgroundFrameIndex(frameIndex) {
    const numericFrameIndex = Number(frameIndex);
    const backgroundFrame = (this.preview?.images ?? []).find(
      frame => Number(frame.frame_index) === numericFrameIndex
    ) ?? this.preview?.images?.[0] ?? null;
    this.currentBackgroundUrl = backgroundFrame ? uploadedFileUrl(backgroundFrame.uploaded_file_id) : '';
    this.ensureImageLoaded(this.currentBackgroundUrl);
  }

  async playAnimation(objectId, animationId, {mode = 'queued'} = {}) {
    const object = (this.preview?.objects ?? []).find(item => Number(item.id) === Number(objectId));
    const animation = object?.animations?.find(item => Number(item.id) === Number(animationId));
    if (!object || !animation?.frames?.length) return false;

    const numericObjectId = Number(objectId);
    const playbackState = this.objectPlaybackState.get(numericObjectId) ?? {
      token: 0,
      chain: Promise.resolve()
    };
    if (mode === 'immediate') playbackState.token += 1;
    const token = playbackState.token + 1;
    playbackState.token = token;

    const run = async () => {
      this.activeObjectIds.add(numericObjectId);
      try {
        for (const frame of animation.frames) {
          if (token !== playbackState.token) return false;
          const render = frame.render ?? object.default_render ?? null;
          if (render?.url) {
            try {
              await loadImage(resolvePreviewUrl(render.url));
            } catch (error) {
              this.dispatchPreviewError(error);
              return false;
            }
          }
          if (token !== playbackState.token) return false;
          if (render) this.currentObjectRenders.set(numericObjectId, render);
          else this.currentObjectRenders.delete(numericObjectId);
          if (this.runtimeObjectStates[numericObjectId]) {
            this.runtimeObjectStates[numericObjectId].render = render;
          }
          this.renderCanvas();
          await wait(frame.duration_seconds);
        }
        return true;
      } finally {
        if (token === playbackState.token) this.activeObjectIds.delete(numericObjectId);
        this.renderCanvas();
      }
    };

    const queueBase = mode === 'queued' ? playbackState.chain.catch(() => {}) : Promise.resolve();
    const promise = queueBase.then(run);
    playbackState.chain = promise.catch(() => {});
    this.objectPlaybackState.set(numericObjectId, playbackState);
    return promise;
  }

  setObjectRender(objectId, render) {
    const numericObjectId = Number(objectId);
    if (!Number.isFinite(numericObjectId) || numericObjectId <= 0) return;
    const playbackState = this.objectPlaybackState.get(numericObjectId);
    if (playbackState) {
      playbackState.token += 1;
      playbackState.chain = Promise.resolve();
      this.objectPlaybackState.set(numericObjectId, playbackState);
    }
    this.activeObjectIds.delete(numericObjectId);
    if (render) this.currentObjectRenders.set(numericObjectId, render);
    else this.currentObjectRenders.delete(numericObjectId);
    if (this.runtimeObjectStates[numericObjectId]) {
      this.runtimeObjectStates[numericObjectId].render = render;
    }
    this.renderCanvas();
  }

  stop() {
    for (const playbackState of this.objectPlaybackState.values()) {
      playbackState.token += 1;
      playbackState.chain = Promise.resolve();
    }
    this.activeObjectIds.clear();
    this.hoveredObjectId = null;
    this.focusedObjectId = null;
    this.currentObjectRenders.clear();
    for (const [objectId, state] of Object.entries(this.runtimeObjectStates ?? {})) {
      const numericId = Number(objectId);
      if (state?.render) this.currentObjectRenders.set(numericId, state.render);
    }
    this.renderCanvas();
  }

  resizeCanvas() {
    if (!this.canvas || !this.preview) return;
    const rect = this.canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round(rect.width * ratio));
    const height = Math.max(1, Math.round(rect.height * ratio));
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
  }

  renderCanvas() {
    if (!this.canvas || !this.context || !this.preview) return;
    this.resizeCanvas();
    const ctx = this.context;
    const canvasWidth = this.canvas.width;
    const canvasHeight = this.canvas.height;
    const sceneWidth = Math.max(1, this.preview.width || 1);
    const sceneHeight = Math.max(1, this.preview.height || 1);

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvasWidth, canvasHeight);
    if (!this.transparentStage) {
      ctx.fillStyle = '#18212a';
      ctx.fillRect(0, 0, canvasWidth, canvasHeight);
    }
    ctx.imageSmoothingEnabled = true;

    const backgroundImage = imageCache.get(this.currentBackgroundUrl)?.value ?? null;
    if (this.showBackground && backgroundImage) {
      ctx.drawImage(backgroundImage, 0, 0, canvasWidth, canvasHeight);
    } else if (this.showBackground && this.currentBackgroundUrl) {
      this.ensureImageLoaded(this.currentBackgroundUrl);
    }

    const objects = [...(this.preview.objects ?? [])];
    objects.sort((left, right) => {
      const leftActive = this.activeObjectIds.has(Number(left.id)) ? 1 : 0;
      const rightActive = this.activeObjectIds.has(Number(right.id)) ? 1 : 0;
      return leftActive - rightActive;
    });

    for (const object of objects) {
      const objectState = this.runtimeObjectStates?.[object.id];
      if (objectState?.visible === false) continue;
      const render = this.currentObjectRenders.get(Number(object.id));
      if (!render?.url) continue;
      const imageUrl = resolvePreviewUrl(render.url);
      const image = imageCache.get(imageUrl)?.value ?? null;
      if (!image) {
        this.ensureImageLoaded(imageUrl);
        continue;
      }
      const x = (render.left / sceneWidth) * canvasWidth;
      const y = (render.top / sceneHeight) * canvasHeight;
      const width = (render.width / sceneWidth) * canvasWidth;
      const height = (render.height / sceneHeight) * canvasHeight;
      if (width <= 0 || height <= 0) continue;
      ctx.drawImage(image, x, y, width, height);
      if (Number(object.id) === Number(this.focusedObjectId)) {
        ctx.save();
        ctx.strokeStyle = '#f2c94c';
        ctx.lineWidth = Math.max(2, canvasWidth / 320);
        ctx.setLineDash([10, 6]);
        ctx.strokeRect(x, y, width, height);
        ctx.restore();
      }
    }
  }

  onCanvasClick(event) {
    if (this.longPressTriggered) {
      this.longPressTriggered = false;
      return;
    }
    const object = this.findObjectAtCanvasEvent(event);
    if (!object) return;
    this.dispatchEvent(new CustomEvent('preview-object-click', {
      bubbles: true,
      detail: {
        objectId: object.id,
        clientX: event.clientX,
        clientY: event.clientY
      }
    }));
  }

  onCanvasContextMenu(event) {
    event.preventDefault();
    const object = this.findObjectAtCanvasEvent(event);
    if (!object) return;
    this.dispatchObjectMenu(object, event);
  }

  onCanvasPointerDown(event) {
    if (event.button !== 0) return;
    this.cancelLongPress();
    this.longPressTriggered = false;
    this.longPressTimer = window.setTimeout(() => {
      const object = this.findObjectAtCanvasEvent(event);
      if (!object) return;
      this.longPressTriggered = true;
      this.dispatchObjectMenu(object, event);
    }, 420);
  }

  onCanvasPointerMove(event) {
    const object = this.findObjectAtCanvasEvent(event);
    this.updateHoveredObject(object ? Number(object.id) : null);
  }

  onCanvasPointerLeave() {
    this.cancelLongPress();
    this.updateHoveredObject(null);
  }

  cancelLongPress() {
    if (this.longPressTimer) window.clearTimeout(this.longPressTimer);
    this.longPressTimer = null;
  }

  setCanvasCursor(active) {
    if (!this.canvas) return;
    if (this.useExternalCursor) {
      this.canvas.style.cursor = 'none';
      return;
    }
    this.canvas.style.cursor = active ? 'pointer' : 'default';
  }

  updateHoveredObject(nextObjectId) {
    const normalizedNext = Number.isFinite(Number(nextObjectId)) ? Number(nextObjectId) : null;
    if (normalizedNext === this.hoveredObjectId) {
      this.setCanvasCursor(Boolean(normalizedNext));
      return;
    }
    const previousObjectId = this.hoveredObjectId;
    this.hoveredObjectId = normalizedNext;
    this.setCanvasCursor(Boolean(normalizedNext));
    if (previousObjectId) {
      this.dispatchEvent(new CustomEvent('preview-object-mouseout', {
        bubbles: true,
        detail: {objectId: previousObjectId}
      }));
    }
    if (normalizedNext) {
      this.dispatchEvent(new CustomEvent('preview-object-mouseover', {
        bubbles: true,
        detail: {objectId: normalizedNext}
      }));
    }
  }

  syncHoveredObjectState() {
    if (!this.hoveredObjectId) return;
    const hoveredObject = (this.preview?.objects ?? []).find(
      object => Number(object.id) === Number(this.hoveredObjectId)
    );
    if (!hoveredObject) {
      this.updateHoveredObject(null);
      return;
    }
    const objectState = this.runtimeObjectStates?.[hoveredObject.id];
    const render = this.currentObjectRenders.get(Number(hoveredObject.id));
    if (!objectState?.enabled || objectState?.visible === false || !render) {
      this.updateHoveredObject(null);
    }
  }

  findObjectAtCanvasEvent(event) {
    if (!this.canvas || !this.preview) return null;
    const rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const objects = [...(this.preview.objects ?? [])]
      .sort((left, right) => {
        const leftActive = this.activeObjectIds.has(Number(left.id)) ? 1 : 0;
        const rightActive = this.activeObjectIds.has(Number(right.id)) ? 1 : 0;
        return leftActive - rightActive;
      })
      .reverse();
    for (const object of objects) {
      const objectState = this.runtimeObjectStates?.[object.id];
      if (!objectState?.enabled || objectState?.visible === false) continue;
      const render = this.currentObjectRenders.get(Number(object.id));
      if (!render) continue;
      const bounds = previewBounds(render, this.preview.width, this.preview.height, rect.width, rect.height);
      if (
        x >= bounds.left
        && x <= bounds.left + bounds.width
        && y >= bounds.top
        && y <= bounds.top + bounds.height
      ) {
        return object;
      }
    }
    return null;
  }

  dispatchPreviewError(error) {
    this.dispatchEvent(new CustomEvent('preview-error', {
      bubbles: true,
      detail: {message: error?.message || 'Preview could not load one or more images.'}
    }));
  }

  renderSubtitleOverlay() {
    const subtitleRoot = this.shadowRoot.querySelector('[data-preview-subtitles]');
    if (!subtitleRoot) return;
    subtitleRoot.innerHTML = renderSubtitleMarkup(this.currentSubtitle);
  }

  dispatchObjectMenu(object, event) {
    this.dispatchEvent(new CustomEvent('preview-object-menu', {
      bubbles: true,
      detail: {
        objectId: object.id,
        clientX: event.clientX,
        clientY: event.clientY
      }
    }));
  }

  getStageClientRect() {
    return this.shadowRoot.querySelector('.stage')?.getBoundingClientRect() ?? null;
  }

  getObjectClientBounds(objectId) {
    if (!this.canvas || !this.preview) return null;
    const render = this.currentObjectRenders.get(Number(objectId));
    if (!render) return null;
    const rect = this.canvas.getBoundingClientRect();
    const bounds = previewBounds(render, this.preview.width, this.preview.height, rect.width, rect.height);
    return {
      left: rect.left + bounds.left,
      top: rect.top + bounds.top,
      width: bounds.width,
      height: bounds.height
    };
  }

  ensureImageLoaded(url) {
    if (!url || this.pendingImageUrls.has(url) || imageCache.get(url)?.value) return;
    this.pendingImageUrls.add(url);
    void loadImage(url)
      .then(() => {
        this.pendingImageUrls.delete(url);
        this.renderCanvas();
      })
      .catch(error => {
        this.pendingImageUrls.delete(url);
        this.dispatchPreviewError(error);
      });
  }
}

const imageCache = new Map();

async function loadImage(url) {
  if (!url) throw new Error('Could not load image: empty source');
  const cached = imageCache.get(url);
  if (cached?.promise) return cached.promise;

  const promise = fetch(url, {credentials: 'include', cache: 'default'})
    .then(response => {
      if (!response.ok) {
        throw new Error(`Could not fetch image: ${url} (${response.status})`);
      }
      return response.blob();
    })
    .then(blob => blobToImage(blob))
    .then(image => {
      imageCache.set(url, {promise: Promise.resolve(image), value: image});
      return image;
    })
    .catch(error => {
      imageCache.delete(url);
      throw error;
    });

  imageCache.set(url, {promise, value: null});
  return promise;
}

async function preloadPreviewAssets(preview, options = {}) {
  if (!preview?.images?.length) return;
  const onProgress = typeof options.onProgress === 'function' ? options.onProgress : null;
  const mode = options.mode === 'all' ? 'all' : 'initial';
  const urls = collectPreviewAssetUrls(preview, mode);
  const orderedUrls = [...urls];
  const total = orderedUrls.length;
  let loaded = 0;
  onProgress?.({loaded, total});
  await Promise.all(
    orderedUrls.map(async url => {
      await loadImage(url);
      loaded += 1;
      onProgress?.({loaded, total});
    })
  );
}

function collectPreviewAssetUrls(preview, mode = 'initial') {
  const urls = new Set();
  const backgroundFrameIndex = Number(preview?.background_frame_index ?? 0);
  const selectedBackground = (preview?.images ?? []).find(
    frame => Number(frame.frame_index) === backgroundFrameIndex
  ) ?? preview?.images?.[0] ?? null;
  if (selectedBackground) urls.add(uploadedFileUrl(selectedBackground.uploaded_file_id));
  for (const object of preview.objects ?? []) {
    if (object.default_render?.url) urls.add(resolvePreviewUrl(object.default_render.url));
    if (mode !== 'all') continue;
    for (const animation of object.animations ?? []) {
      for (const frame of animation.frames ?? []) {
        if (frame.render?.url) urls.add(resolvePreviewUrl(frame.render.url));
      }
    }
    for (const render of Object.values(object.frame_renders ?? {})) {
      if (render?.url) urls.add(resolvePreviewUrl(render.url));
    }
  }
  return urls;
}

function blobToImage(blob) {
  const objectUrl = URL.createObjectURL(blob);
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(objectUrl);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error('Could not decode image blob'));
    };
    image.src = objectUrl;
  });
}

function resolvePreviewUrl(url) {
  if (!url) return '';
  return apiUrl(url);
}

function wait(durationSeconds) {
  const milliseconds = Math.max(1, Math.round(Number(durationSeconds || 0) * 1000));
  return new Promise(resolve => window.setTimeout(resolve, milliseconds));
}

function previewBounds(render, sceneWidth, sceneHeight, canvasWidth, canvasHeight) {
  return {
    left: (render.left / Math.max(1, sceneWidth || 1)) * canvasWidth,
    top: (render.top / Math.max(1, sceneHeight || 1)) * canvasHeight,
    width: (render.width / Math.max(1, sceneWidth || 1)) * canvasWidth,
    height: (render.height / Math.max(1, sceneHeight || 1)) * canvasHeight
  };
}

function renderSubtitleMarkup(subtitle) {
  if (!subtitle?.primaryText && !subtitle?.secondaryText) return '';
  return `
    <div class="subtitle-card ${subtitle.sizeClass} ${subtitle.motionClass || 'is-entering'}">
      ${subtitle.primaryText ? `<p class="subtitle-primary">${escapeHtml(subtitle.primaryText)}</p>` : ''}
      ${subtitle.secondaryText ? `<p class="subtitle-secondary">${escapeHtml(subtitle.secondaryText)}</p>` : ''}
    </div>
  `;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

if (!customElements.get('wonky-scene-preview')) {
  customElements.define('wonky-scene-preview', WonkyScenePreviewElement);
}

export {preloadPreviewAssets};
