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
    this.backgroundImage = null;
    this.browseAllFrames = false;
    this.currentFrameIndex = 0;
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
    this.brushShape = 'round';
    this.hardness = 0.75;
    this.opacity = 0.55;
    this.displayMode = 'overlay';
    this.applyAll = false;
    this.isPointerDown = false;
    this.pointerMode = null;
    this.activeOperation = null;
    this.lastPoint = null;
    this.hoverPoint = null;
    this.brushPreviewVisible = false;
    this.brushPreviewUntil = 0;
    this.brushPreviewTimer = null;
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
    if (this.brushPreviewTimer) window.clearTimeout(this.brushPreviewTimer);
  }

  async configure({scene, object, masks, currentIndex}) {
    this.scene = scene;
    this.object = object;
    this.masks = masks ?? [];
    this.currentIndex = Math.max(0, Math.min(currentIndex ?? 0, this.masks.length - 1));
    this.currentMask = this.masks[this.currentIndex] ?? null;
    this.currentFrameIndex = this.findSceneFrameIndexForUploadedFileId(this.currentMask?.uploaded_file_id);
    this.undoStack = [];
    this.redoStack = [];
    this.render();
    this.canvas = this.shadowRoot.querySelector('[data-editor-canvas]');
    this.canvasContext = this.canvas.getContext('2d');
    this.bindEvents();
    this.emitFrameContext();
    await this.loadCurrentFrame();
  }

  bindEvents() {
    const root = this.shadowRoot;
    root.querySelector('[data-action="previous"]')?.addEventListener('click', () => this.navigate(-1));
    root.querySelector('[data-action="next"]')?.addEventListener('click', () => this.navigate(1));
    root.querySelector('[data-action="go-to-frame"]')?.addEventListener('click', () => this.goToFrameNumber());
    root.querySelector('[data-action="go-to-pickup-frame"]')?.addEventListener('click', () => this.goToPickupFrame());
    root.querySelector('[data-action="set-default-frame"]')?.addEventListener('click', () => this.dispatchSetDefaultFrame());
    root.querySelector('[data-action="save"]')?.addEventListener('click', () => this.dispatchSave());
    root.querySelector('[data-action="undo"]')?.addEventListener('click', () => this.undo());
    root.querySelector('[data-action="redo"]')?.addEventListener('click', () => this.redo());
    root.querySelector('[data-action="fit"]')?.addEventListener('click', () => this.fitToView());
    root.querySelector('[data-action="grow"]')?.addEventListener('click', () => this.dispatchProcess('grow'));
    root.querySelector('[data-action="fill-holes"]')?.addEventListener('click', () => this.dispatchProcess('fill_holes'));
    root.querySelector('[data-action="combine"]')?.addEventListener('click', () => this.dispatchProcess('combine'));
    root.querySelector('[data-action="invert"]')?.addEventListener('click', () => this.dispatchProcess('invert'));
    root.querySelector('[data-action="solid"]')?.addEventListener('click', () => this.dispatchProcess('solid'));
    root.querySelector('[data-action="clear"]')?.addEventListener('click', () => this.dispatchProcess('clear'));
    root.querySelector('[name="brushSize"]')?.addEventListener('input', event => {
      this.brushSize = Number(event.target.value);
      root.querySelector('[data-brush-size]').textContent = String(this.brushSize);
      this.showBrushPreview();
    });
    root.querySelector('[name="brushShape"]')?.addEventListener('change', event => {
      this.brushShape = event.target.value === 'square' ? 'square' : 'round';
      this.showBrushPreview();
    });
    root.querySelector('[name="hardness"]')?.addEventListener('input', event => {
      this.hardness = Number(event.target.value) / 100;
      root.querySelector('[data-hardness]').textContent = `${event.target.value}%`;
      this.showBrushPreview();
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
    root.querySelector('[name="browseAllFrames"]')?.addEventListener('change', event => {
      this.setBrowseAllFrames(event.target.checked);
    });
    root.querySelector('[name="frameNumber"]')?.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        this.goToFrameNumber();
      }
    });
    this.canvas?.addEventListener('pointerdown', event => this.onPointerDown(event));
    this.canvas?.addEventListener('pointermove', event => this.onPointerMove(event));
    this.canvas?.addEventListener('pointerup', event => this.onPointerUp(event));
    this.canvas?.addEventListener('pointercancel', event => this.onPointerUp(event));
    this.canvas?.addEventListener('pointerleave', () => this.onPointerLeave());
    this.canvas?.addEventListener('contextmenu', event => event.preventDefault());
    this.canvas?.addEventListener('wheel', event => this.onWheel(event), {passive: false});
  }

  adjustBrushSize(delta) {
    const nextSize = Math.max(2, Math.min(180, this.brushSize + delta));
    if (nextSize === this.brushSize) return;
    this.brushSize = nextSize;
    const input = this.shadowRoot.querySelector('[name="brushSize"]');
    if (input) input.value = String(this.brushSize);
    const label = this.shadowRoot.querySelector('[data-brush-size]');
    if (label) label.textContent = String(this.brushSize);
    this.showBrushPreview();
  }

  setDisplayMode(mode) {
    if (!['overlay', 'scene_background', 'mask', 'masked'].includes(mode)) return;
    this.displayMode = mode;
    const select = this.shadowRoot.querySelector('[name="displayMode"]');
    if (select) select.value = mode;
    this.renderCanvas();
  }

  goToBoundaryFrame(position) {
    if (this.browseAllFrames) {
      const frameCount = this.scene?.images?.length ?? 0;
      if (!frameCount) return;
      this.setCurrentFrameIndex(position === 'start' ? 0 : frameCount - 1);
      this.loadCurrentFrame();
      return;
    }
    if (!this.masks.length) return;
    this.currentIndex = position === 'start' ? 0 : this.masks.length - 1;
    this.currentMask = this.masks[this.currentIndex] ?? null;
    this.currentFrameIndex = this.findSceneFrameIndexForUploadedFileId(this.currentMask?.uploaded_file_id);
    this.undoStack = [];
    this.redoStack = [];
    this.emitFrameContext();
    this.render();
    this.canvas = this.shadowRoot.querySelector('[data-editor-canvas]');
    this.canvasContext = this.canvas.getContext('2d');
    this.bindEvents();
    this.loadCurrentFrame();
  }

  render() {
    const currentFrameNumber = this.currentFrameNumber();
    const maxFrameNumber = Array.isArray(this.scene?.images) && this.scene.images.length
      ? this.scene.images.length
      : Math.max(1, this.masks.length);
    const isDefaultFrame = Boolean(
      this.currentMask
      && this.object
      && Number(this.object.default_uploaded_file_id) === Number(this.currentMask.uploaded_file_id)
    );
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
          align-items: stretch;
          border-bottom: 1px solid #2d3748;
          background: #ffffff;
        }
        .toolbar-section {
          min-width: 0;
          display: grid;
          gap: 8px;
          align-content: start;
          padding: 10px 12px;
          border: 1px solid #d7ded6;
          border-radius: 10px;
          background: #f8faf8;
        }
        .toolbar-section--grow {
          flex: 1 1 340px;
        }
        .toolbar-section__title {
          margin: 0;
          color: #516071;
          font-size: 0.72rem;
          font-weight: 800;
          letter-spacing: 0.04em;
          text-transform: uppercase;
        }
        .toolbar-group {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          align-items: center;
        }
        .toolbar-group--stack {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
          align-items: start;
        }
        .toolbar-group--brush {
          display: grid;
          grid-template-columns: minmax(110px, 150px) repeat(3, minmax(0, 1fr));
          gap: 10px;
          align-items: end;
        }
        .toolbar-group--frame-jump {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          align-items: center;
        }
        label {
          min-width: 0;
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
        button.toggle-active {
          border-color: #1f6f5b;
          background: #eef7f1;
          color: #1f6f5b;
        }
        button:disabled {
          opacity: 0.45;
          cursor: default;
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
          <div class="toolbar-section">
            <p class="toolbar-section__title">Navigate</p>
            <div class="toolbar-group">
              <button type="button" data-action="previous" ${(this.browseAllFrames ? this.currentFrameIndex <= 0 : this.currentIndex <= 0) ? 'disabled' : ''}>Previous</button>
              <button type="button" data-action="next" ${(this.browseAllFrames ? this.currentFrameIndex >= maxFrameNumber - 1 : this.currentIndex >= this.masks.length - 1) ? 'disabled' : ''}>Next</button>
              <button type="button" data-action="go-to-pickup-frame" ${this.object?.pickup_uploaded_file_id ? '' : 'disabled'}>Go to pickup frame</button>
            </div>
            <label>
              Go to frame
              <div class="toolbar-group toolbar-group--frame-jump">
                <input name="frameNumber" type="number" min="1" max="${maxFrameNumber}" value="${currentFrameNumber}" />
                <button type="button" data-action="go-to-frame">Go</button>
                <button type="button" data-action="undo" ${this.undoStack.length ? '' : 'disabled'}>Undo</button>
                <button type="button" data-action="redo" ${this.redoStack.length ? '' : 'disabled'}>Redo</button>
                <button type="button" data-action="fit">Fit</button>
              </div>
            </label>
          </div>
        </div>
        <div class="toolbar-section toolbar-section--grow">
          <p class="toolbar-section__title">Brush</p>
          <div class="toolbar-group toolbar-group--brush">
            <label>
              Shape
              <select name="brushShape">
                <option value="round" ${this.brushShape === 'round' ? 'selected' : ''}>Round</option>
                <option value="square" ${this.brushShape === 'square' ? 'selected' : ''}>Square</option>
              </select>
            </label>
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
          </div>
        </div>
        <div class="toolbar-section">
          <p class="toolbar-section__title">View</p>
          <label>
            Display
            <select name="displayMode">
              <option value="overlay" ${this.displayMode === 'overlay' ? 'selected' : ''}>Overlay</option>
              <option value="scene_background" ${this.displayMode === 'scene_background' ? 'selected' : ''}>Scene background</option>
              <option value="mask" ${this.displayMode === 'mask' ? 'selected' : ''}>Mask only</option>
              <option value="masked" ${this.displayMode === 'masked' ? 'selected' : ''}>Masked image</option>
            </select>
          </label>
          <label class="checkbox">
            <input name="browseAllFrames" type="checkbox" ${this.browseAllFrames ? 'checked' : ''} />
            Browse all scene frames
          </label>
          <label class="checkbox">
            <input name="applyAll" type="checkbox" ${this.applyAll ? 'checked' : ''} ${maxFrameNumber > 0 ? '' : 'disabled'} />
            Apply to all frames
          </label>
        </div>
        <div class="toolbar-section toolbar-section--grow">
          <p class="toolbar-section__title">Mask ops</p>
          <div class="toolbar-group">
            <button type="button" data-action="grow" ${this.currentMask ? '' : 'disabled'}>Grow mask</button>
            <button type="button" data-action="fill-holes" ${this.currentMask ? '' : 'disabled'}>Fill holes</button>
            <button type="button" data-action="combine" ${this.currentMask ? '' : 'disabled'}>Combine masks</button>
            <button type="button" data-action="invert" ${this.currentMask ? '' : 'disabled'}>Invert mask</button>
            <button type="button" data-action="solid" ${this.currentMask ? '' : 'disabled'}>Solid mask</button>
            <button type="button" data-action="clear" ${this.currentMask ? '' : 'disabled'}>Clear mask</button>
          </div>
          <div class="toolbar-group">
            <button class="${isDefaultFrame ? 'toggle-active' : ''}" type="button" data-action="set-default-frame" ${this.currentMask ? '' : 'disabled'}>${isDefaultFrame ? 'Default frame' : 'Use as default frame'}</button>
            <button class="primary" type="button" data-action="save">Save</button>
          </div>
        </div>
      </div>
      <div class="canvas-wrap">
        <canvas data-editor-canvas></canvas>
      </div>
    `;
  }

  async loadCurrentFrame() {
    const sceneImage = this.currentSceneImage();
    const originalUrl = sceneImage?.originalUrl || this.currentMask?.originalUrl;
    if (!originalUrl) return;
    const backgroundUrl = this.sceneBackgroundImage()?.originalUrl || '';
    const [originalImage, backgroundImage] = await Promise.all([
      loadImage(originalUrl),
      backgroundUrl ? loadImage(backgroundUrl).catch(() => null) : Promise.resolve(null)
    ]);
    this.originalImage = originalImage;
    this.backgroundImage = backgroundImage;
    this.maskCanvas.width = originalImage.naturalWidth;
    this.maskCanvas.height = originalImage.naturalHeight;
    this.maskContext.clearRect(0, 0, this.maskCanvas.width, this.maskCanvas.height);
    if (this.currentMask?.rawUrl) {
      const maskImage = await loadImage(this.currentMask.rawUrl);
      this.maskContext.drawImage(maskImage, 0, 0, this.maskCanvas.width, this.maskCanvas.height);
    } else {
      this.maskContext.fillStyle = '#000000';
      this.maskContext.fillRect(0, 0, this.maskCanvas.width, this.maskCanvas.height);
    }
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
    this.renderBrushPreview(ctx);
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
    if (this.displayMode === 'scene_background') {
      if (this.backgroundImage) {
        ctx.drawImage(this.backgroundImage, 0, 0, width, height);
      } else {
        ctx.drawImage(this.originalImage, 0, 0, width, height);
      }
      drawMaskedImage(ctx, this.originalImage, this.maskAlphaCanvas, width, height, 1);
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
    this.hoverPoint = this.lastPoint;
    if (this.pointerMode === 'pan') {
      this.lastPointer = {x: event.clientX, y: event.clientY};
      return;
    }
    this.activeOperation = {
      type: this.pointerMode,
      size: this.brushSize,
      shape: this.brushShape,
      hardness: this.hardness,
      points: [this.lastPoint]
    };
    this.beforeStroke = this.maskContext.getImageData(0, 0, this.maskCanvas.width, this.maskCanvas.height);
    this.applyBrush(this.lastPoint, this.activeOperation);
    this.updateMaskAlphaCanvas();
    this.renderCanvas();
  }

  onPointerMove(event) {
    if (!this.originalImage) return;
    this.hoverPoint = this.eventToImagePoint(event);
    if (!this.isPointerDown) {
      if (this.brushPreviewVisible) this.renderCanvas();
      return;
    }
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
    this.hoverPoint = this.eventToImagePoint(event);
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
    if (this.brushPreviewVisible) this.renderCanvas();
  }

  onPointerLeave() {
    this.hoverPoint = null;
    if (this.brushPreviewVisible) this.renderCanvas();
  }

  onWheel(event) {
    if (!this.originalImage) return;
    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      const delta = event.deltaY < 0 ? 4 : -4;
      this.hoverPoint = this.eventToImagePoint(event);
      this.adjustBrushSize(delta);
      return;
    }
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
    if (operation.shape === 'square') {
      this.applySquareBrush(point, operation, context);
      return;
    }
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

  applySquareBrush(point, operation, context = this.maskContext) {
    const size = Math.max(1, operation.size);
    const half = size / 2;
    const hardStop = Math.max(0, Math.min(1, operation.hardness));
    const color = operation.type === 'erase' ? 0 : 255;
    const innerHalf = half * hardStop;
    const outerLeft = point.x - half;
    const outerTop = point.y - half;
    if (hardStop >= 0.999 || innerHalf <= 0.5) {
      context.fillStyle = `rgba(${color}, ${color}, ${color}, 1)`;
      context.fillRect(outerLeft, outerTop, size, size);
      return;
    }
    const offscreen = document.createElement('canvas');
    offscreen.width = Math.max(1, Math.ceil(size));
    offscreen.height = Math.max(1, Math.ceil(size));
    const offscreenContext = offscreen.getContext('2d');
    const imageData = offscreenContext.createImageData(offscreen.width, offscreen.height);
    const data = imageData.data;
    const localCenterX = offscreen.width / 2;
    const localCenterY = offscreen.height / 2;
    for (let y = 0; y < offscreen.height; y += 1) {
      for (let x = 0; x < offscreen.width; x += 1) {
        const dx = Math.abs((x + 0.5) - localCenterX);
        const dy = Math.abs((y + 0.5) - localCenterY);
        const outside = Math.max(dx, dy);
        let alpha = 1;
        if (outside > innerHalf) {
          alpha = 1 - ((outside - innerHalf) / Math.max(0.0001, half - innerHalf));
        }
        alpha = Math.max(0, Math.min(1, alpha));
        const index = (y * offscreen.width + x) * 4;
        data[index] = color;
        data[index + 1] = color;
        data[index + 2] = color;
        data[index + 3] = Math.round(alpha * 255);
      }
    }
    offscreenContext.putImageData(imageData, 0, 0);
    context.drawImage(offscreen, outerLeft, outerTop);
  }

  showBrushPreview(durationMs = 700) {
    this.brushPreviewVisible = true;
    this.brushPreviewUntil = Date.now() + durationMs;
    if (this.brushPreviewTimer) window.clearTimeout(this.brushPreviewTimer);
    this.brushPreviewTimer = window.setTimeout(() => {
      this.brushPreviewVisible = false;
      this.brushPreviewTimer = null;
      this.renderCanvas();
    }, durationMs);
    this.renderCanvas();
  }

  renderBrushPreview(ctx) {
    if (!this.brushPreviewVisible || !this.originalImage) return;
    if (Date.now() > this.brushPreviewUntil) {
      this.brushPreviewVisible = false;
      return;
    }
    const point = this.hoverPoint ?? {
      x: this.originalImage.naturalWidth / 2,
      y: this.originalImage.naturalHeight / 2
    };
    const screenX = point.x * this.zoom + this.panX;
    const screenY = point.y * this.zoom + this.panY;
    const size = this.brushSize * this.zoom;
    const half = size / 2;
    const innerHalf = half * Math.max(0, Math.min(1, this.hardness));
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.95)';
    ctx.lineWidth = 2;
    ctx.fillStyle = 'rgba(255, 255, 255, 0.12)';
    if (this.brushShape === 'square') {
      ctx.fillRect(screenX - innerHalf, screenY - innerHalf, innerHalf * 2, innerHalf * 2);
      ctx.strokeRect(screenX - half, screenY - half, size, size);
      if (innerHalf > 1 && innerHalf < half) {
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.45)';
        ctx.strokeRect(screenX - innerHalf, screenY - innerHalf, innerHalf * 2, innerHalf * 2);
      }
    } else {
      ctx.beginPath();
      ctx.arc(screenX, screenY, innerHalf, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.arc(screenX, screenY, half, 0, Math.PI * 2);
      ctx.stroke();
      if (innerHalf > 1 && innerHalf < half) {
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.45)';
        ctx.beginPath();
        ctx.arc(screenX, screenY, innerHalf, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
    ctx.restore();
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
    if (this.browseAllFrames) {
      const nextFrameIndex = this.currentFrameIndex + delta;
      if (nextFrameIndex < 0 || nextFrameIndex >= (this.scene?.images?.length ?? 0)) return;
      this.setCurrentFrameIndex(nextFrameIndex);
      this.loadCurrentFrame();
      return;
    }
    const nextIndex = this.currentIndex + delta;
    if (nextIndex < 0 || nextIndex >= this.masks.length) return;
    this.currentIndex = nextIndex;
    this.currentMask = this.masks[nextIndex] ?? null;
    this.currentFrameIndex = this.findSceneFrameIndexForUploadedFileId(this.currentMask?.uploaded_file_id);
    this.undoStack = [];
    this.redoStack = [];
    this.emitFrameContext();
    this.render();
    this.canvas = this.shadowRoot.querySelector('[data-editor-canvas]');
    this.canvasContext = this.canvas.getContext('2d');
    this.bindEvents();
    this.loadCurrentFrame();
  }

  currentFrameNumber() {
    if (Array.isArray(this.scene?.images) && this.scene.images.length) {
      return Math.max(1, this.currentFrameIndex + 1);
    }
    return Math.max(1, this.currentIndex + 1);
  }

  goToFrameNumber() {
    const input = this.shadowRoot.querySelector('[name="frameNumber"]');
    const sceneImages = this.scene?.images ?? [];
    const frameNumber = Number(input?.value ?? 0);
    if (!sceneImages.length) {
      this.dispatchMessage('This scene has no numbered frames.');
      return;
    }
    if (!Number.isFinite(frameNumber) || frameNumber < 1 || frameNumber > sceneImages.length) {
      this.dispatchMessage(`Frame must be between 1 and ${sceneImages.length}.`);
      return;
    }
    const targetSceneImage = sceneImages[frameNumber - 1];
    const targetMask = this.masks.find(
      mask => Number(mask.uploaded_file_id) === Number(targetSceneImage.uploaded_file_id)
    );
    if (!this.browseAllFrames && !targetMask) {
      this.dispatchMessage('Enable "Browse all scene frames" to jump to frames with no mask yet.');
      return;
    }
    this.dispatchMessage('');
    this.setCurrentFrameIndex(frameNumber - 1);
    this.loadCurrentFrame();
  }

  goToPickupFrame() {
    const pickupUploadedFileId = Number(this.object?.pickup_uploaded_file_id ?? 0);
    if (!pickupUploadedFileId) {
      this.dispatchMessage('This object does not have a linked pickup frame yet.');
      return;
    }
    const frameIndex = this.findSceneFrameIndexForUploadedFileId(pickupUploadedFileId);
    this.dispatchMessage('');
    this.setCurrentFrameIndex(frameIndex);
    this.loadCurrentFrame();
  }

  dispatchSave() {
    this.dispatchEvent(new CustomEvent('save-mask', {
      bubbles: true,
      detail: {
        applyAll: this.applyAll,
        maskId: this.currentMask?.id ?? null,
        uploadedFileId: this.currentSceneImage()?.uploaded_file_id ?? this.currentMask?.uploaded_file_id ?? null
      }
    }));
  }

  dispatchProcess(operation) {
    if (!this.currentMask) return;
    this.dispatchEvent(new CustomEvent('process-mask', {
      bubbles: true,
      detail: {operation, applyAll: this.applyAll, maskId: this.currentMask.id}
    }));
  }

  dispatchSetDefaultFrame() {
    if (!this.currentMask) return;
    this.dispatchEvent(new CustomEvent('set-default-frame', {
      bubbles: true,
      detail: {uploadedFileId: this.currentMask.uploaded_file_id, maskId: this.currentMask.id}
    }));
  }

  dispatchMessage(message) {
    this.dispatchEvent(new CustomEvent('editor-message', {
      bubbles: true,
      detail: {message}
    }));
  }

  currentSceneImage() {
    if (Array.isArray(this.scene?.images) && this.scene.images.length) {
      return this.scene.images[this.currentFrameIndex] ?? null;
    }
    return null;
  }

  sceneBackgroundImage() {
    const sceneImages = this.scene?.images ?? [];
    if (!sceneImages.length) return null;
    const backgroundIndex = Math.max(
      0,
      Math.min(Number(this.scene?.background_frame_index ?? 0), sceneImages.length - 1)
    );
    return sceneImages[backgroundIndex] ?? null;
  }

  findSceneFrameIndexForUploadedFileId(uploadedFileId) {
    if (!uploadedFileId || !Array.isArray(this.scene?.images)) return 0;
    const index = this.scene.images.findIndex(
      sceneImage => Number(sceneImage.uploaded_file_id) === Number(uploadedFileId)
    );
    return index >= 0 ? index : 0;
  }

  setCurrentFrameIndex(index) {
    const sceneImages = this.scene?.images ?? [];
    if (!sceneImages.length) return;
    this.currentFrameIndex = Math.max(0, Math.min(index, sceneImages.length - 1));
    const uploadedFileId = sceneImages[this.currentFrameIndex]?.uploaded_file_id;
    this.currentIndex = this.masks.findIndex(
      mask => Number(mask.uploaded_file_id) === Number(uploadedFileId)
    );
    this.currentMask = this.currentIndex >= 0 ? this.masks[this.currentIndex] : null;
    this.undoStack = [];
    this.redoStack = [];
    this.emitFrameContext();
    this.render();
    this.canvas = this.shadowRoot.querySelector('[data-editor-canvas]');
    this.canvasContext = this.canvas.getContext('2d');
    this.bindEvents();
  }

  setBrowseAllFrames(enabled) {
    this.browseAllFrames = Boolean(enabled);
    if (!this.browseAllFrames && !this.currentMask && this.masks.length) {
      this.currentIndex = 0;
      this.currentMask = this.masks[0];
      this.currentFrameIndex = this.findSceneFrameIndexForUploadedFileId(this.currentMask?.uploaded_file_id);
    }
    this.undoStack = [];
    this.redoStack = [];
    this.emitFrameContext();
    this.render();
    this.canvas = this.shadowRoot.querySelector('[data-editor-canvas]');
    this.canvasContext = this.canvas.getContext('2d');
    this.bindEvents();
    this.loadCurrentFrame();
  }

  async exportCurrentBlob() {
    return canvasToPngBlob(this.maskCanvas);
  }

  async exportEditedBlobsForAll() {
    const operations = this.undoStack.map(entry => entry.operation);
    const results = [];
    const sceneImages = Array.isArray(this.scene?.images) && this.scene.images.length
      ? this.scene.images
      : this.masks.map(mask => ({
          uploaded_file_id: mask.uploaded_file_id,
          width: this.maskCanvas.width,
          height: this.maskCanvas.height
        }));
    const masksByUploadedFileId = new Map(
      this.masks.map(mask => [Number(mask.uploaded_file_id), mask])
    );
    const currentUploadedFileId = Number(
      this.currentSceneImage()?.uploaded_file_id ?? this.currentMask?.uploaded_file_id ?? 0
    );
    for (const sceneImage of sceneImages) {
      const uploadedFileId = Number(sceneImage?.uploaded_file_id ?? 0);
      const mask = masksByUploadedFileId.get(uploadedFileId) ?? null;
      if (uploadedFileId && uploadedFileId === currentUploadedFileId) {
        results.push({
          mask,
          uploadedFileId,
          blob: await this.exportCurrentBlob()
        });
        continue;
      }
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Number(sceneImage?.width) || this.maskCanvas.width);
      canvas.height = Math.max(1, Number(sceneImage?.height) || this.maskCanvas.height);
      const context = canvas.getContext('2d');
      if (mask?.rawUrl) {
        const maskImage = await loadImage(mask.rawUrl);
        context.drawImage(maskImage, 0, 0, canvas.width, canvas.height);
      } else {
        context.fillStyle = '#000000';
        context.fillRect(0, 0, canvas.width, canvas.height);
      }
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
      results.push({
        mask,
        uploadedFileId,
        blob: await canvasToPngBlob(canvas)
      });
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

  emitFrameContext() {
    const currentSceneImage = this.currentSceneImage();
    const sceneFrameTotal = Math.max(1, this.scene?.images?.length ?? this.masks.length ?? 1);
    const sceneFrameNumber = this.currentFrameNumber();
    const meta = this.currentMask
      ? `Mask ${this.currentIndex + 1} / ${Math.max(1, this.masks.length)} · Scene frame ${sceneFrameNumber} / ${sceneFrameTotal}`
      : `No mask yet · Scene frame ${sceneFrameNumber} / ${sceneFrameTotal}`;
    const filename = this.currentMask?.original_filename ?? currentSceneImage?.original_filename ?? '';
    const note = this.currentMask
      && this.object
      && Number(this.object.pickup_uploaded_file_id) === Number(this.currentMask.uploaded_file_id)
      ? 'Pickup frame linked to this object'
      : '';
    this.dispatchEvent(new CustomEvent('frame-context-change', {
      bubbles: true,
      detail: {meta, filename, note}
    }));
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

function drawMaskedImage(ctx, image, maskImage, width, height, opacity) {
  const temp = document.createElement('canvas');
  temp.width = width;
  temp.height = height;
  const tempCtx = temp.getContext('2d');
  tempCtx.drawImage(image, 0, 0, width, height);
  tempCtx.globalCompositeOperation = 'destination-in';
  tempCtx.drawImage(maskImage, 0, 0, width, height);
  tempCtx.globalCompositeOperation = 'source-over';
  ctx.globalAlpha = opacity;
  ctx.drawImage(temp, 0, 0);
  ctx.globalAlpha = 1;
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
