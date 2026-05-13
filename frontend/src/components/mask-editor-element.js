class WonkyMaskEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: 'open'});
    this.scene = null;
    this.object = null;
    this.masks = [];
    this.currentIndex = 0;
    this.currentMask = null;
    this.originalImage = null;
    this.maskCanvas = document.createElement('canvas');
    this.maskContext = this.maskCanvas.getContext('2d', {willReadFrequently: true});
    this.maskAlphaCanvas = document.createElement('canvas');
    this.maskAlphaContext = this.maskAlphaCanvas.getContext('2d', {willReadFrequently: true});
    this.bufferCanvas = document.createElement('canvas');
    this.bufferContext = this.bufferCanvas.getContext('2d');
    this.zoom = 1;
    this.panX = 0;
    this.panY = 0;
    this.brushSize = 36;
    this.hardness = 0.75;
    this.opacity = 0.55;
    this.displayMode = 'overlay';
    this.applyAll = false;
    this.isPointerDown = false;
    this.pointerMode = null;
    this.activeOperation = null;
    this.lastPoint = null;
    this.undoStack = [];
    this.redoStack = [];
    this.resizeObserver = new ResizeObserver(() => this.renderCanvas());
  }

  connectedCallback() {
    this.render();
    this.canvas = this.shadowRoot.querySelector('[data-editor-canvas]');
    this.canvasContext = this.canvas.getContext('2d');
    this.resizeObserver.observe(this);
    this.bindEvents();
  }

  disconnectedCallback() {
    this.resizeObserver.disconnect();
  }

  async configure({scene, object, masks, currentIndex}) {
    this.scene = scene;
    this.object = object;
    this.masks = masks ?? [];
    this.currentIndex = Math.max(0, Math.min(currentIndex ?? 0, this.masks.length - 1));
    this.currentMask = this.masks[this.currentIndex] ?? null;
    this.undoStack = [];
    this.redoStack = [];
    this.render();
    this.canvas = this.shadowRoot.querySelector('[data-editor-canvas]');
    this.canvasContext = this.canvas.getContext('2d');
    this.bindEvents();
    await this.loadCurrentFrame();
  }

  bindEvents() {
    const root = this.shadowRoot;
    root.querySelector('[data-action="previous"]')?.addEventListener('click', () => this.navigate(-1));
    root.querySelector('[data-action="next"]')?.addEventListener('click', () => this.navigate(1));
    root.querySelector('[data-action="save"]')?.addEventListener('click', () => this.dispatchSave());
    root.querySelector('[data-action="undo"]')?.addEventListener('click', () => this.undo());
    root.querySelector('[data-action="redo"]')?.addEventListener('click', () => this.redo());
    root.querySelector('[data-action="fit"]')?.addEventListener('click', () => this.fitToView());
    root.querySelector('[data-action="grow"]')?.addEventListener('click', () => this.dispatchProcess('grow'));
    root.querySelector('[data-action="fill-holes"]')?.addEventListener('click', () => this.dispatchProcess('fill_holes'));
    root.querySelector('[data-action="invert"]')?.addEventListener('click', () => this.dispatchProcess('invert'));
    root.querySelector('[data-action="solid"]')?.addEventListener('click', () => this.dispatchProcess('solid'));
    root.querySelector('[name="brushSize"]')?.addEventListener('input', event => {
      this.brushSize = Number(event.target.value);
      root.querySelector('[data-brush-size]').textContent = String(this.brushSize);
    });
    root.querySelector('[name="hardness"]')?.addEventListener('input', event => {
      this.hardness = Number(event.target.value) / 100;
      root.querySelector('[data-hardness]').textContent = `${event.target.value}%`;
    });
    root.querySelector('[name="opacity"]')?.addEventListener('input', event => {
      this.opacity = Number(event.target.value) / 100;
      root.querySelector('[data-opacity]').textContent = `${event.target.value}%`;
      this.renderCanvas();
    });
    root.querySelector('[name="displayMode"]')?.addEventListener('change', event => {
      this.displayMode = event.target.value;
      this.renderCanvas();
    });
    root.querySelector('[name="applyAll"]')?.addEventListener('change', event => {
      this.applyAll = event.target.checked;
    });
    this.canvas?.addEventListener('pointerdown', event => this.onPointerDown(event));
    this.canvas?.addEventListener('pointermove', event => this.onPointerMove(event));
    this.canvas?.addEventListener('pointerup', event => this.onPointerUp(event));
    this.canvas?.addEventListener('pointercancel', event => this.onPointerUp(event));
    this.canvas?.addEventListener('contextmenu', event => event.preventDefault());
    this.canvas?.addEventListener('wheel', event => this.onWheel(event), {passive: false});
  }

  render() {
    const frameLabel = this.currentMask
      ? `${this.currentIndex + 1} / ${this.masks.length} · ${this.currentMask.original_filename}`
      : 'No mask selected';
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
          align-items: end;
          border-bottom: 1px solid #2d3748;
          background: #ffffff;
        }
        .toolbar-group {
          display: flex;
          gap: 8px;
          align-items: center;
        }
        label {
          min-width: 130px;
          display: grid;
          gap: 4px;
          color: #374151;
          font-size: 0.78rem;
          font-weight: 700;
        }
        select,
        input {
          min-height: 34px;
          border: 1px solid #cbd5d1;
          border-radius: 6px;
          padding: 0 8px;
          background: #ffffff;
          color: #111827;
        }
        input[type="range"] {
          padding: 0;
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
          min-width: min(280px, 100%);
          color: #1f2937;
          font-weight: 700;
          overflow-wrap: anywhere;
        }
        .checkbox {
          min-width: 170px;
          display: flex;
          grid-template-columns: none;
          align-items: center;
          gap: 8px;
        }
        .checkbox input {
          width: 18px;
          min-height: 18px;
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
          cursor: crosshair;
        }
      </style>
      <div class="toolbar">
        <div class="toolbar-group">
          <button type="button" data-action="previous" ${this.currentIndex <= 0 ? 'disabled' : ''}>Previous</button>
          <button type="button" data-action="next" ${this.currentIndex >= this.masks.length - 1 ? 'disabled' : ''}>Next</button>
        </div>
        <div class="frame-label">${escapeHtml(frameLabel)}</div>
        <label>
          Brush <span data-brush-size>${this.brushSize}</span>
          <input name="brushSize" type="range" min="2" max="180" value="${this.brushSize}" />
        </label>
        <label>
          Hardness <span data-hardness>${Math.round(this.hardness * 100)}%</span>
          <input name="hardness" type="range" min="0" max="100" value="${Math.round(this.hardness * 100)}" />
        </label>
        <label>
          Mask opacity <span data-opacity>${Math.round(this.opacity * 100)}%</span>
          <input name="opacity" type="range" min="10" max="100" value="${Math.round(this.opacity * 100)}" />
        </label>
        <label>
          Display
          <select name="displayMode">
            <option value="overlay" ${this.displayMode === 'overlay' ? 'selected' : ''}>Overlay</option>
            <option value="mask" ${this.displayMode === 'mask' ? 'selected' : ''}>Mask only</option>
            <option value="masked" ${this.displayMode === 'masked' ? 'selected' : ''}>Masked image</option>
          </select>
        </label>
        <label class="checkbox">
          <input name="applyAll" type="checkbox" ${this.applyAll ? 'checked' : ''} />
          Apply to all frames
        </label>
        <div class="toolbar-group">
          <button type="button" data-action="undo" ${this.undoStack.length ? '' : 'disabled'}>Undo</button>
          <button type="button" data-action="redo" ${this.redoStack.length ? '' : 'disabled'}>Redo</button>
          <button type="button" data-action="fit">Fit</button>
        </div>
        <div class="toolbar-group">
          <button type="button" data-action="grow">Grow mask</button>
          <button type="button" data-action="fill-holes">Fill holes</button>
          <button type="button" data-action="invert">Invert mask</button>
          <button type="button" data-action="solid">Solid mask</button>
          <button class="primary" type="button" data-action="save">Save</button>
        </div>
      </div>
      <div class="canvas-wrap">
        <canvas data-editor-canvas></canvas>
      </div>
    `;
  }

  async loadCurrentFrame() {
    if (!this.currentMask) return;
    const [originalImage, maskImage] = await Promise.all([
      loadImage(this.currentMask.originalUrl),
      loadImage(this.currentMask.rawUrl)
    ]);
    this.originalImage = originalImage;
    this.maskCanvas.width = originalImage.naturalWidth;
    this.maskCanvas.height = originalImage.naturalHeight;
    this.maskContext.clearRect(0, 0, this.maskCanvas.width, this.maskCanvas.height);
    this.maskContext.drawImage(maskImage, 0, 0, this.maskCanvas.width, this.maskCanvas.height);
    this.updateMaskAlphaCanvas();
    this.fitToView();
  }

  fitToView() {
    if (!this.canvas || !this.originalImage) return;
    this.resizeCanvas();
    const margin = 36;
    const scaleX = (this.canvas.width - margin) / this.originalImage.naturalWidth;
    const scaleY = (this.canvas.height - margin) / this.originalImage.naturalHeight;
    this.zoom = Math.max(0.05, Math.min(scaleX, scaleY));
    this.panX = (this.canvas.width - this.originalImage.naturalWidth * this.zoom) / 2;
    this.panY = (this.canvas.height - this.originalImage.naturalHeight * this.zoom) / 2;
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
    if (!this.originalImage) return;
    this.renderBuffer();
    ctx.setTransform(this.zoom, 0, 0, this.zoom, this.panX, this.panY);
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(this.bufferCanvas, 0, 0);
  }

  renderBuffer() {
    const width = this.originalImage.naturalWidth;
    const height = this.originalImage.naturalHeight;
    this.bufferCanvas.width = width;
    this.bufferCanvas.height = height;
    const ctx = this.bufferContext;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, width, height);
    if (this.displayMode === 'mask') {
      ctx.drawImage(this.maskCanvas, 0, 0);
      return;
    }
    ctx.drawImage(this.originalImage, 0, 0, width, height);
    if (this.displayMode === 'masked') {
      ctx.globalCompositeOperation = 'destination-in';
      ctx.drawImage(this.maskAlphaCanvas, 0, 0);
      ctx.globalCompositeOperation = 'source-over';
      return;
    }
    const overlay = document.createElement('canvas');
    overlay.width = width;
    overlay.height = height;
    const overlayCtx = overlay.getContext('2d');
    overlayCtx.drawImage(this.maskAlphaCanvas, 0, 0);
    overlayCtx.globalCompositeOperation = 'source-in';
    overlayCtx.fillStyle = `rgba(235, 65, 82, ${this.opacity})`;
    overlayCtx.fillRect(0, 0, width, height);
    ctx.drawImage(overlay, 0, 0);
  }

  onPointerDown(event) {
    if (!this.originalImage) return;
    event.preventDefault();
    this.canvas.setPointerCapture(event.pointerId);
    this.isPointerDown = true;
    this.pointerMode = event.button === 1 ? 'pan' : event.button === 2 ? 'erase' : 'draw';
    this.lastPoint = this.eventToImagePoint(event);
    if (this.pointerMode === 'pan') {
      this.lastPointer = {x: event.clientX, y: event.clientY};
      return;
    }
    this.activeOperation = {
      type: this.pointerMode,
      size: this.brushSize,
      hardness: this.hardness,
      points: [this.lastPoint]
    };
    this.beforeStroke = this.maskContext.getImageData(0, 0, this.maskCanvas.width, this.maskCanvas.height);
    this.applyBrush(this.lastPoint, this.activeOperation);
    this.updateMaskAlphaCanvas();
    this.renderCanvas();
  }

  onPointerMove(event) {
    if (!this.isPointerDown) return;
    event.preventDefault();
    if (this.pointerMode === 'pan') {
      const dx = (event.clientX - this.lastPointer.x) * (window.devicePixelRatio || 1);
      const dy = (event.clientY - this.lastPointer.y) * (window.devicePixelRatio || 1);
      this.panX += dx;
      this.panY += dy;
      this.lastPointer = {x: event.clientX, y: event.clientY};
      this.renderCanvas();
      return;
    }
    const point = this.eventToImagePoint(event);
    this.strokeBetween(this.lastPoint, point, this.activeOperation);
    this.activeOperation.points.push(point);
    this.lastPoint = point;
    this.updateMaskAlphaCanvas();
    this.renderCanvas();
  }

  onPointerUp(event) {
    if (!this.isPointerDown) return;
    event.preventDefault();
    this.isPointerDown = false;
    if (this.pointerMode !== 'pan' && this.beforeStroke) {
      const after = this.maskContext.getImageData(0, 0, this.maskCanvas.width, this.maskCanvas.height);
      this.undoStack.push({
        before: this.beforeStroke,
        after,
        operation: this.activeOperation
      });
      this.redoStack = [];
      this.render();
      this.canvas = this.shadowRoot.querySelector('[data-editor-canvas]');
      this.canvasContext = this.canvas.getContext('2d');
      this.bindEvents();
      this.renderCanvas();
    }
    this.pointerMode = null;
    this.activeOperation = null;
    this.beforeStroke = null;
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
      x: Math.max(0, Math.min(this.maskCanvas.width, (point.x - this.panX) / this.zoom)),
      y: Math.max(0, Math.min(this.maskCanvas.height, (point.y - this.panY) / this.zoom))
    };
  }

  strokeBetween(from, to, operation) {
    const distance = Math.hypot(to.x - from.x, to.y - from.y);
    const step = Math.max(1, operation.size * 0.25);
    const count = Math.max(1, Math.ceil(distance / step));
    for (let index = 1; index <= count; index += 1) {
      const t = index / count;
      this.applyBrush({
        x: from.x + (to.x - from.x) * t,
        y: from.y + (to.y - from.y) * t
      }, operation);
    }
  }

  applyBrush(point, operation, context = this.maskContext) {
    const radius = operation.size / 2;
    const hardStop = Math.max(0, Math.min(1, operation.hardness));
    const gradient = context.createRadialGradient(point.x, point.y, radius * hardStop, point.x, point.y, radius);
    const color = operation.type === 'erase' ? 0 : 255;
    gradient.addColorStop(0, `rgba(${color}, ${color}, ${color}, 1)`);
    gradient.addColorStop(1, `rgba(${color}, ${color}, ${color}, 0)`);
    context.fillStyle = gradient;
    context.beginPath();
    context.arc(point.x, point.y, radius, 0, Math.PI * 2);
    context.fill();
  }

  undo() {
    const entry = this.undoStack.pop();
    if (!entry) return;
    this.maskContext.putImageData(entry.before, 0, 0);
    this.updateMaskAlphaCanvas();
    this.redoStack.push(entry);
    this.render();
    this.canvas = this.shadowRoot.querySelector('[data-editor-canvas]');
    this.canvasContext = this.canvas.getContext('2d');
    this.bindEvents();
    this.renderCanvas();
  }

  redo() {
    const entry = this.redoStack.pop();
    if (!entry) return;
    this.maskContext.putImageData(entry.after, 0, 0);
    this.updateMaskAlphaCanvas();
    this.undoStack.push(entry);
    this.render();
    this.canvas = this.shadowRoot.querySelector('[data-editor-canvas]');
    this.canvasContext = this.canvas.getContext('2d');
    this.bindEvents();
    this.renderCanvas();
  }

  navigate(delta) {
    const nextIndex = this.currentIndex + delta;
    if (nextIndex < 0 || nextIndex >= this.masks.length) return;
    this.dispatchEvent(new CustomEvent('navigate-mask', {
      bubbles: true,
      detail: {index: nextIndex, maskId: this.masks[nextIndex].id}
    }));
  }

  dispatchSave() {
    this.dispatchEvent(new CustomEvent('save-mask', {
      bubbles: true,
      detail: {applyAll: this.applyAll}
    }));
  }

  dispatchProcess(operation) {
    this.dispatchEvent(new CustomEvent('process-mask', {
      bubbles: true,
      detail: {operation, applyAll: this.applyAll}
    }));
  }

  async exportCurrentBlob() {
    return canvasToPngBlob(this.maskCanvas);
  }

  async exportEditedBlobsForAll() {
    const operations = this.undoStack.map(entry => entry.operation);
    const results = [];
    for (const mask of this.masks) {
      if (mask.id === this.currentMask.id) {
        results.push({mask, blob: await this.exportCurrentBlob()});
        continue;
      }
      const maskImage = await loadImage(mask.rawUrl);
      const canvas = document.createElement('canvas');
      canvas.width = this.maskCanvas.width;
      canvas.height = this.maskCanvas.height;
      const context = canvas.getContext('2d');
      context.drawImage(maskImage, 0, 0, canvas.width, canvas.height);
      const scaleX = canvas.width / this.maskCanvas.width;
      const scaleY = canvas.height / this.maskCanvas.height;
      for (const operation of operations) {
        const scaledOperation = scaleOperation(operation, scaleX, scaleY);
        for (let index = 0; index < scaledOperation.points.length; index += 1) {
          if (index === 0) this.applyBrush(scaledOperation.points[index], scaledOperation, context);
          else this.strokeBetweenOnContext(
            scaledOperation.points[index - 1],
            scaledOperation.points[index],
            scaledOperation,
            context
          );
        }
      }
      results.push({mask, blob: await canvasToPngBlob(canvas)});
    }
    return results;
  }

  strokeBetweenOnContext(from, to, operation, context) {
    const distance = Math.hypot(to.x - from.x, to.y - from.y);
    const step = Math.max(1, operation.size * 0.25);
    const count = Math.max(1, Math.ceil(distance / step));
    for (let index = 1; index <= count; index += 1) {
      const t = index / count;
      this.applyBrush({
        x: from.x + (to.x - from.x) * t,
        y: from.y + (to.y - from.y) * t
      }, operation, context);
    }
  }

  updateMaskAlphaCanvas() {
    this.maskAlphaCanvas.width = this.maskCanvas.width;
    this.maskAlphaCanvas.height = this.maskCanvas.height;
    const source = this.maskContext.getImageData(0, 0, this.maskCanvas.width, this.maskCanvas.height);
    const data = source.data;
    for (let index = 0; index < data.length; index += 4) {
      const alpha = Math.max(data[index], data[index + 1], data[index + 2]);
      data[index] = 255;
      data[index + 1] = 255;
      data[index + 2] = 255;
      data[index + 3] = alpha;
    }
    this.maskAlphaContext.putImageData(source, 0, 0);
  }
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = 'use-credentials';
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`Could not load image: ${src}`));
    image.src = src;
  });
}

function canvasToPngBlob(canvas) {
  return new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
}

function scaleOperation(operation, scaleX, scaleY) {
  return {
    ...operation,
    size: operation.size * Math.max(scaleX, scaleY),
    points: operation.points.map(point => ({
      x: point.x * scaleX,
      y: point.y * scaleY
    }))
  };
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

if (!customElements.get('wonky-mask-editor')) {
  customElements.define('wonky-mask-editor', WonkyMaskEditor);
}
