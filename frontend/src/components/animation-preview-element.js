class WonkyAnimationPreview extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: 'open'});
    this.frames = [];
    this.currentIndex = 0;
    this.playing = false;
    this.zoom = 1;
    this.panX = 0;
    this.panY = 0;
    this.imageWidth = 0;
    this.imageHeight = 0;
    this.originalImage = null;
    this.backgroundImage = null;
    this.maskImage = null;
    this.backgroundMaskImage = null;
    this.bufferCanvas = document.createElement('canvas');
    this.bufferContext = this.bufferCanvas.getContext('2d');
    this.resizeObserver = new ResizeObserver(() => this.renderCanvas());
    this.loadToken = 0;
    this.playTimer = null;
  }

  connectedCallback() {
    this.render();
    this.canvas = this.shadowRoot.querySelector('[data-preview-canvas]');
    this.canvasContext = this.canvas.getContext('2d');
    this.resizeObserver.observe(this);
    this.bindEvents();
  }

  disconnectedCallback() {
    this.resizeObserver.disconnect();
    this.pause();
  }

  async configure({frames = [], objectName = '', backgroundName = ''}) {
    this.frames = frames;
    this.objectName = objectName;
    this.backgroundName = backgroundName;
    this.currentIndex = Math.max(0, Math.min(this.currentIndex, this.frames.length - 1));
    this.render();
    this.canvas = this.shadowRoot.querySelector('[data-preview-canvas]');
    this.canvasContext = this.canvas.getContext('2d');
    this.bindEvents();
    this.updateToolbarState();
    await this.loadCurrentFrame({fit: true});
  }

  bindEvents() {
    const root = this.shadowRoot;
    root.querySelector('[data-action="previous"]')?.addEventListener('click', () => this.previous());
    root.querySelector('[data-action="next"]')?.addEventListener('click', () => this.next());
    root.querySelector('[data-action="play"]')?.addEventListener('click', () => this.play());
    root.querySelector('[data-action="pause"]')?.addEventListener('click', () => this.pause());
    root.querySelector('[data-action="stop"]')?.addEventListener('click', () => this.stop());
    root.querySelector('[data-action="fit"]')?.addEventListener('click', () => this.fitToView());
    this.canvas?.addEventListener('pointerdown', event => this.onPointerDown(event));
    this.canvas?.addEventListener('pointermove', event => this.onPointerMove(event));
    this.canvas?.addEventListener('pointerup', event => this.onPointerUp(event));
    this.canvas?.addEventListener('pointercancel', event => this.onPointerUp(event));
    this.canvas?.addEventListener('contextmenu', event => event.preventDefault());
    this.canvas?.addEventListener('wheel', event => this.onWheel(event), {passive: false});
  }

  render() {
    const frame = this.frames[this.currentIndex] ?? null;
    const frameLabel = frame
      ? `${this.currentIndex + 1} / ${this.frames.length} · frame ${frame.frameIndex} · ${frame.filename}`
      : 'No animation frames';
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          min-height: 0;
          display: grid;
          grid-template-rows: auto minmax(0, 1fr);
          color: #18212f;
          background: #111827;
        }
        .toolbar {
          min-width: 0;
          padding: 10px 12px;
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          align-items: center;
          border-bottom: 1px solid #2d3748;
          background: #ffffff;
        }
        .toolbar-group {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          align-items: center;
        }
        button {
          min-height: 34px;
          padding: 0 11px;
          border: 1px solid #cbd5d1;
          border-radius: 6px;
          background: #ffffff;
          color: #1f2937;
          font: inherit;
          font-weight: 700;
          cursor: pointer;
        }
        button > span {
          display: inline-flex;
          align-items: center;
          gap: 6px;
        }
        button.primary {
          border-color: #1f6f5b;
          color: #ffffff;
          background: #1f6f5b;
        }
        button:disabled {
          opacity: 0.45;
          cursor: default;
        }
        .frame-label {
          min-width: min(360px, 100%);
          flex: 1 1 auto;
          color: #1f2937;
          font-weight: 700;
          overflow-wrap: anywhere;
          text-align: right;
        }
        .toolbar-icon {
          width: 16px;
          height: 16px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          flex: 0 0 auto;
        }
        .toolbar-icon svg {
          width: 16px;
          height: 16px;
        }
        .canvas-wrap {
          min-height: 0;
          display: grid;
          background: #111827;
        }
        canvas {
          width: 100%;
          height: 100%;
          display: block;
          touch-action: none;
          cursor: grab;
        }
      </style>
      <div class="toolbar">
        <div class="toolbar-group">
          <button type="button" data-action="previous" ${this.currentIndex <= 0 ? 'disabled' : ''}>Previous</button>
          <button type="button" data-action="next" ${this.currentIndex >= this.frames.length - 1 ? 'disabled' : ''}>Next</button>
          <button class="primary" type="button" data-action="play" ${this.frames.length ? '' : 'disabled'}><span>${playIcon()}Play</span></button>
          <button type="button" data-action="pause" ${this.playing ? '' : 'disabled'}><span>${pauseIcon()}Pause</span></button>
          <button type="button" data-action="stop" ${this.frames.length ? '' : 'disabled'}><span>${stopIcon()}Stop</span></button>
          <button type="button" data-action="fit" ${this.frames.length ? '' : 'disabled'}>Fit</button>
        </div>
        <div class="frame-label" data-frame-label>${escapeHtml(frameLabel)}</div>
      </div>
      <div class="canvas-wrap">
        <canvas data-preview-canvas></canvas>
      </div>
    `;
  }

  async loadCurrentFrame({fit = false} = {}) {
    const frame = this.frames[this.currentIndex];
    const token = ++this.loadToken;
    if (!frame) {
      this.originalImage = null;
      this.maskImage = null;
      this.backgroundMaskImage = null;
      this.renderCanvas();
      this.updateToolbarState();
      return false;
    }
    let originalImage;
    let backgroundImage;
    let maskImage;
    let backgroundMaskImage;
    try {
      [originalImage, backgroundImage, maskImage, backgroundMaskImage] = await Promise.all([
        loadImage(frame.originalUrl),
        frame.backgroundUrl ? loadImage(frame.backgroundUrl) : Promise.resolve(null),
        loadImage(frame.maskUrl),
        frame.backgroundMaskUrl ? loadImage(frame.backgroundMaskUrl) : Promise.resolve(null)
      ]);
    } catch (error) {
      if (token !== this.loadToken) return;
      this.dispatchEvent(new CustomEvent('preview-error', {
        bubbles: true,
        detail: {message: error.message, frame}
      }));
      this.updateToolbarState();
      return false;
    }
    if (token !== this.loadToken) return;
    this.originalImage = originalImage;
    this.backgroundImage = backgroundImage;
    this.maskImage = maskImage;
    this.backgroundMaskImage = backgroundMaskImage;
    this.imageWidth = originalImage.naturalWidth;
    this.imageHeight = originalImage.naturalHeight;
    if (fit) this.fitToView();
    else this.renderCanvas();
    this.updateToolbarState();
    this.preloadNearbyFrames();
    return true;
  }

  async previous() {
    if (this.currentIndex <= 0) return;
    this.currentIndex -= 1;
    this.updateToolbarState();
    await this.loadCurrentFrame();
  }

  async first() {
    if (!this.frames.length || this.currentIndex <= 0) return;
    this.currentIndex = 0;
    this.updateToolbarState();
    await this.loadCurrentFrame();
  }

  async next({loop = false} = {}) {
    if (!this.frames.length) return false;
    if (this.currentIndex >= this.frames.length - 1) {
      if (!loop) return false;
      this.currentIndex = 0;
    } else {
      this.currentIndex += 1;
    }
    this.updateToolbarState();
    return this.loadCurrentFrame();
  }

  async last() {
    if (!this.frames.length || this.currentIndex >= this.frames.length - 1) return;
    this.currentIndex = this.frames.length - 1;
    this.updateToolbarState();
    await this.loadCurrentFrame();
  }

  play() {
    if (!this.frames.length || this.playing) return;
    this.playing = true;
    this.updateToolbarState();
    this.scheduleNextFrame();
  }

  pause() {
    this.playing = false;
    if (this.playTimer) window.clearTimeout(this.playTimer);
    this.playTimer = null;
    this.updateToolbarState();
    this.renderCanvas();
  }

  async stop() {
    this.pause();
    if (!this.frames.length || this.currentIndex === 0) return;
    this.currentIndex = 0;
    this.updateToolbarState();
    await this.loadCurrentFrame();
  }

  togglePlayback() {
    if (this.playing) this.pause();
    else this.play();
  }

  scheduleNextFrame() {
    if (!this.playing) return;
    const frame = this.frames[this.currentIndex];
    const durationMs = Math.max(16, Math.round((frame?.durationSeconds ?? 1 / 15) * 1000));
    this.playTimer = window.setTimeout(async () => {
      this.playTimer = null;
      if (!this.playing) return;
      await this.next({loop: true});
      if (this.playing) this.scheduleNextFrame();
    }, durationMs);
  }

  updateToolbarState() {
    const frame = this.frames[this.currentIndex] ?? null;
    const frameLabel = frame
      ? `${this.currentIndex + 1} / ${this.frames.length} · frame ${frame.frameIndex} · ${frame.filename}`
      : 'No animation frames';
    const label = this.shadowRoot.querySelector('[data-frame-label]');
    if (label) label.textContent = frameLabel;
    const previous = this.shadowRoot.querySelector('[data-action="previous"]');
    const next = this.shadowRoot.querySelector('[data-action="next"]');
    const play = this.shadowRoot.querySelector('[data-action="play"]');
    const pause = this.shadowRoot.querySelector('[data-action="pause"]');
    const stop = this.shadowRoot.querySelector('[data-action="stop"]');
    const fit = this.shadowRoot.querySelector('[data-action="fit"]');
    if (previous) previous.disabled = this.currentIndex <= 0;
    if (next) next.disabled = this.currentIndex >= this.frames.length - 1;
    if (play) play.disabled = !this.frames.length || this.playing;
    if (pause) pause.disabled = !this.playing;
    if (stop) stop.disabled = !this.frames.length;
    if (fit) fit.disabled = !this.frames.length;
  }

  preloadNearbyFrames() {
    if (!this.frames.length) return;
    for (let offset = 1; offset <= 3; offset += 1) {
      const frame = this.frames[(this.currentIndex + offset) % this.frames.length];
      if (!frame) continue;
      loadImage(frame.originalUrl).catch(() => {});
      loadImage(frame.maskUrl).catch(() => {});
      if (frame.backgroundMaskUrl) loadImage(frame.backgroundMaskUrl).catch(() => {});
    }
  }

  fitToView() {
    if (!this.canvas || !this.imageWidth || !this.imageHeight) return;
    this.resizeCanvas();
    const margin = 36;
    const scaleX = (this.canvas.width - margin) / this.imageWidth;
    const scaleY = (this.canvas.height - margin) / this.imageHeight;
    this.zoom = Math.max(0.05, Math.min(scaleX, scaleY));
    this.panX = (this.canvas.width - this.imageWidth * this.zoom) / 2;
    this.panY = (this.canvas.height - this.imageHeight * this.zoom) / 2;
    this.renderCanvas();
  }

  resizeCanvas() {
    const rect = this.canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.floor(rect.width * ratio));
    const height = Math.max(1, Math.floor(rect.height * ratio));
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
  }

  renderCanvas() {
    if (!this.canvas || !this.canvasContext) return;
    this.resizeCanvas();
    const ctx = this.canvasContext;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.fillStyle = '#111827';
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    if (!this.originalImage || !this.maskImage) return;
    this.renderBuffer();
    ctx.setTransform(this.zoom, 0, 0, this.zoom, this.panX, this.panY);
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(this.bufferCanvas, 0, 0);
  }

  renderBuffer() {
    const width = this.imageWidth;
    const height = this.imageHeight;
    this.bufferCanvas.width = width;
    this.bufferCanvas.height = height;
    const ctx = this.bufferContext;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, width, height);
    if ((this.frames[this.currentIndex]?.backgroundMode ?? 'plate') === 'scene') {
      if (this.backgroundImage) {
        ctx.globalAlpha = 1;
        ctx.drawImage(this.backgroundImage, 0, 0, width, height);
      } else {
        ctx.globalAlpha = 0.18;
        ctx.drawImage(this.originalImage, 0, 0, width, height);
        ctx.globalAlpha = 1;
      }
    } else if (this.backgroundMaskImage) {
      ctx.globalAlpha = 0.18;
      ctx.drawImage(this.originalImage, 0, 0, width, height);
      ctx.globalAlpha = 1;
      drawMaskedImage(ctx, this.originalImage, this.backgroundMaskImage, width, height, 0.62);
    } else {
      ctx.globalAlpha = 0.18;
      ctx.drawImage(this.originalImage, 0, 0, width, height);
      ctx.globalAlpha = 1;
    }
    drawMaskedImage(ctx, this.originalImage, this.maskImage, width, height, 1);
  }

  onPointerDown(event) {
    if (!this.originalImage || event.button !== 1) return;
    event.preventDefault();
    this.canvas.setPointerCapture(event.pointerId);
    this.isPointerDown = true;
    this.lastPointer = {x: event.clientX, y: event.clientY};
  }

  onPointerMove(event) {
    if (!this.isPointerDown) return;
    event.preventDefault();
    const ratio = window.devicePixelRatio || 1;
    this.panX += (event.clientX - this.lastPointer.x) * ratio;
    this.panY += (event.clientY - this.lastPointer.y) * ratio;
    this.lastPointer = {x: event.clientX, y: event.clientY};
    this.renderCanvas();
  }

  onPointerUp(event) {
    if (!this.isPointerDown) return;
    event.preventDefault();
    this.isPointerDown = false;
  }

  onWheel(event) {
    if (!this.originalImage) return;
    event.preventDefault();
    const before = this.eventToImagePoint(event);
    const factor = event.deltaY < 0 ? 1.12 : 0.89;
    this.zoom = Math.max(0.05, Math.min(12, this.zoom * factor));
    const screen = this.eventToCanvasPoint(event);
    this.panX = screen.x - before.x * this.zoom;
    this.panY = screen.y - before.y * this.zoom;
    this.renderCanvas();
  }

  eventToCanvasPoint(event) {
    const rect = this.canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    return {
      x: (event.clientX - rect.left) * ratio,
      y: (event.clientY - rect.top) * ratio
    };
  }

  eventToImagePoint(event) {
    const point = this.eventToCanvasPoint(event);
    return {
      x: (point.x - this.panX) / this.zoom,
      y: (point.y - this.panY) / this.zoom
    };
  }
}

function drawMaskedImage(ctx, image, maskImage, width, height, opacity) {
  const temp = document.createElement('canvas');
  temp.width = width;
  temp.height = height;
  const tempCtx = temp.getContext('2d');
  tempCtx.drawImage(image, 0, 0, width, height);
  const alphaMask = createAlphaMask(maskImage, width, height);
  tempCtx.globalCompositeOperation = 'destination-in';
  tempCtx.drawImage(alphaMask, 0, 0);
  tempCtx.globalCompositeOperation = 'source-over';
  ctx.globalAlpha = opacity;
  ctx.drawImage(temp, 0, 0);
  ctx.globalAlpha = 1;
}

function createAlphaMask(maskImage, width, height) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d', {willReadFrequently: true});
  ctx.drawImage(maskImage, 0, 0, width, height);
  const imageData = ctx.getImageData(0, 0, width, height);
  const data = imageData.data;
  for (let index = 0; index < data.length; index += 4) {
    const alpha = Math.max(data[index], data[index + 1], data[index + 2]);
    data[index] = 255;
    data[index + 1] = 255;
    data[index + 2] = 255;
    data[index + 3] = alpha;
  }
  ctx.putImageData(imageData, 0, 0);
  return canvas;
}

const imageCache = new Map();
const MAX_CACHED_IMAGES = 96;

async function loadImage(src) {
  if (!src) throw new Error('Could not load image: empty source');
  const cachedImage = imageCache.get(src);
  if (cachedImage) return cachedImage;
  const imagePromise = fetchImage(src).catch(error => {
    imageCache.delete(src);
    throw error;
  });
  imageCache.set(src, imagePromise);
  pruneImageCache();
  return imagePromise;
}

async function fetchImage(src) {
  const response = await fetch(src, {
    credentials: 'include',
    cache: 'default'
  });
  if (!response.ok) {
    throw new Error(`Could not fetch image: ${src} (${response.status})`);
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(objectUrl);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error(`Could not load image: ${src}`));
    };
    image.src = objectUrl;
  });
}

function pruneImageCache() {
  while (imageCache.size > MAX_CACHED_IMAGES) {
    imageCache.delete(imageCache.keys().next().value);
  }
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function playIcon() {
  return `<span class="toolbar-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="currentColor"><polygon points="8,5 19,12 8,19"></polygon></svg></span>`;
}

function pauseIcon() {
  return `<span class="toolbar-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="currentColor"><rect x="7" y="5" width="4" height="14" rx="1"></rect><rect x="13" y="5" width="4" height="14" rx="1"></rect></svg></span>`;
}

function stopIcon() {
  return `<span class="toolbar-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="1.5"></rect></svg></span>`;
}

if (!customElements.get('wonky-animation-preview')) {
  customElements.define('wonky-animation-preview', WonkyAnimationPreview);
}
