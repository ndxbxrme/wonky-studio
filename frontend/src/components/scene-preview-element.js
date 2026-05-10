import {apiUrl, uploadedFileUrl} from '../api.js';

class WonkyScenePreviewElement extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: 'open'});
    this.preview = null;
    this.showBackground = true;
    this.playbackToken = 0;
    this.currentBackgroundUrl = '';
    this.currentObjectRenders = new Map();
    this.activeObjectId = null;
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

        .stage {
          width: min(100%, calc(100vh - 220px));
          max-width: 100%;
          aspect-ratio: var(--scene-width, 16) / var(--scene-height, 9);
          background: #18212a;
          display: grid;
        }

        canvas {
          width: 100%;
          height: 100%;
          display: block;
          background: #18212a;
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

  connectedCallback() {
    this.resizeObserver.observe(this);
  }

  disconnectedCallback() {
    this.resizeObserver.disconnect();
    this.playbackToken += 1;
  }

  async configure(preview) {
    this.preview = preview;
    this.showBackground = preview?.showBackground !== false;
    this.playbackToken += 1;
    this.currentObjectRenders.clear();
    if (!preview?.images?.length) {
      this.renderEmpty();
      return;
    }
    this.renderStage();
    await this.primeImages(preview);
    this.setDefaultState();
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
    shell.innerHTML = `
      <div
        class="stage"
        style="--scene-width:${Math.max(1, this.preview.width || 1)}; --scene-height:${Math.max(1, this.preview.height || 1)};"
      >
        <canvas data-preview-canvas></canvas>
      </div>
    `;
    this.canvas = this.shadowRoot.querySelector('[data-preview-canvas]');
    this.context = this.canvas?.getContext('2d');
  }

  async primeImages(preview) {
    const urls = new Set();
    const firstBackground = preview.images?.[0];
    if (firstBackground) urls.add(uploadedFileUrl(firstBackground.uploaded_file_id));
    for (const object of preview.objects ?? []) {
      if (object.default_render?.url) urls.add(resolvePreviewUrl(object.default_render.url));
      for (const animation of object.animations ?? []) {
        for (const frame of animation.frames ?? []) {
          if (frame.render?.url) urls.add(resolvePreviewUrl(frame.render.url));
        }
      }
    }
    await Promise.all([...urls].map(url => loadImage(url)));
  }

  setDefaultState() {
    this.activeObjectId = null;
    const firstBackground = this.preview?.images?.[0];
    this.currentBackgroundUrl = firstBackground ? uploadedFileUrl(firstBackground.uploaded_file_id) : '';
    this.currentObjectRenders.clear();
    for (const object of this.preview?.objects ?? []) {
      if (object.default_render) this.currentObjectRenders.set(Number(object.id), object.default_render);
    }
  }

  async playAnimation(objectId, animationId) {
    const object = (this.preview?.objects ?? []).find(item => Number(item.id) === Number(objectId));
    const animation = object?.animations?.find(item => Number(item.id) === Number(animationId));
    if (!object || !animation?.frames?.length) return false;
    const token = ++this.playbackToken;
    this.activeObjectId = Number(objectId);
    for (const frame of animation.frames) {
      if (token !== this.playbackToken) return false;
      const render = frame.render ?? object.default_render ?? null;
      if (render?.url) {
        await loadImage(resolvePreviewUrl(render.url));
      }
      if (token !== this.playbackToken) return false;
      if (render) this.currentObjectRenders.set(Number(object.id), render);
      else this.currentObjectRenders.delete(Number(object.id));
      this.renderCanvas();
      await wait(frame.duration_seconds);
    }
    if (token !== this.playbackToken) return false;
    this.setDefaultState();
    this.renderCanvas();
    return true;
  }

  stop() {
    this.playbackToken += 1;
    this.setDefaultState();
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
    ctx.fillStyle = '#18212a';
    ctx.fillRect(0, 0, canvasWidth, canvasHeight);
    ctx.imageSmoothingEnabled = true;

    const backgroundImage = imageCache.get(this.currentBackgroundUrl)?.value ?? null;
    if (this.showBackground && backgroundImage) {
      ctx.drawImage(backgroundImage, 0, 0, canvasWidth, canvasHeight);
    }

    const objects = [...(this.preview.objects ?? [])];
    if (this.activeObjectId != null) {
      objects.sort((left, right) => {
        if (left.id === this.activeObjectId) return 1;
        if (right.id === this.activeObjectId) return -1;
        return 0;
      });
    }

    for (const object of objects) {
      const render = this.currentObjectRenders.get(Number(object.id));
      if (!render?.url) continue;
      const image = imageCache.get(resolvePreviewUrl(render.url))?.value ?? null;
      if (!image) continue;
      const x = (render.left / sceneWidth) * canvasWidth;
      const y = (render.top / sceneHeight) * canvasHeight;
      const width = (render.width / sceneWidth) * canvasWidth;
      const height = (render.height / sceneHeight) * canvasHeight;
      if (width <= 0 || height <= 0) continue;
      ctx.drawImage(image, x, y, width, height);
    }
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

customElements.define('wonky-scene-preview', WonkyScenePreviewElement);
