import {apiFetch} from '../api.js';
import {uploadedFileUrl} from '../api.js';
import {applyStatus} from '../status.js';
import {
  findScene,
  loadScene,
  replaceScene
} from '../state/scenes.js';
import {notifyScenePreview} from '../preview-sync.js';
import {user} from '../state/user.js';
import './animation-preview-element.js';

const DEFAULT_FRAME_DURATION = 0.066;

const AnimationsCtrl = app => async params => {
  const sceneId = Number(params[0]);
  const objectId = Number(params[1]);
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    sceneId,
    objectId,
    scene: findScene(sceneId),
    object: null,
    animations: [],
    selectedAnimationId: null,
    selectedAnimation: null,
    backgroundObjectId: 'scene',
    frameRows: [],
    previewFrames: [],
    editorReady: false,
    editorMissing: false,
    hasAnimations: false,
    hasNoAnimations: true,
    hasSelectedAnimation: false,
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-animation-page]');
      this.preview = this.root?.querySelector('wonky-animation-preview');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.root, 'submit', event => this.onSubmit(event));
      this.bind(this.root, 'change', event => this.onChange(event));
      this.bind(this.preview, 'preview-error', event => this.onPreviewError(event));
      this.bind(window, 'keydown', event => this.onKeyDown(event));
      this.setSelectValues();
      await this.configurePreview();
    },

    unload() {
      this.unloadHandlers.forEach(unload => unload());
      this.unloadHandlers = [];
    },

    bind(target, type, handler) {
      if (!target) return;
      target.addEventListener(type, handler);
      this.unloadHandlers.push(() => target.removeEventListener(type, handler));
    },

    async refreshData() {
      this.scene = replaceScene(await loadScene(this.sceneId));
      this.object = this.scene.objects.find(sceneObject => sceneObject.id === this.objectId) ?? null;
      if (!this.object) {
        this.editorReady = false;
        this.editorMissing = true;
        return;
      }
      this.animations = await apiFetch(`/api/scene-objects/${this.objectId}/animations`);
      if (!this.selectedAnimationId && this.animations.length) {
        this.selectedAnimationId = this.animations[0].id;
      }
      if (!this.animations.some(animation => animation.id === this.selectedAnimationId)) {
        this.selectedAnimationId = this.animations[0]?.id ?? null;
      }
      this.prepareState();
    },

    prepareState() {
      this.animations = this.animations.map(animation => ({
        ...animation,
        isSelected: animation.id === this.selectedAnimationId,
        segmentCount: animation.segments?.length ?? 0,
        summary: summarizeAnimation(animation)
      }));
      this.selectedAnimation = this.animations.find(
        animation => animation.id === this.selectedAnimationId
      ) ?? null;
      this.hasAnimations = Boolean(this.animations.length);
      this.hasNoAnimations = !this.hasAnimations;
      this.hasSelectedAnimation = Boolean(this.selectedAnimation);
      this.frameRows = this.selectedAnimation
        ? buildFrameRows(this.selectedAnimation, this.scene, this.object)
        : [];
      this.previewFrames = this.frameRows
        .filter(frame => frame.available)
        .map(frame => ({
          frameIndex: frame.frameIndex,
          filename: frame.filename,
          durationSeconds: frame.durationSeconds,
          originalUrl: frame.mask.originalUrl,
          maskUrl: frame.mask.softUrl || frame.mask.rawUrl,
          backgroundUrl: sceneBackgroundUrl(this.scene),
          backgroundMode: this.backgroundObjectId === 'scene' ? 'scene' : 'plate'
        }));
      this.editorReady = Boolean(this.object);
      this.editorMissing = !this.editorReady;
    },

    setSelectValues() {
      const backgroundSelect = this.root?.querySelector('[name="backgroundObjectId"]');
      if (backgroundSelect) backgroundSelect.value = String(this.backgroundObjectId ?? '');
    },

    setStatus(message) {
      const status = this.root?.querySelector('[data-animation-status]');
      applyStatus(status, message);
    },

    async configurePreview() {
      if (!this.preview || !this.editorReady) return;
      await this.preview.configure({
        frames: this.previewFrames,
        objectName: this.object?.name ?? '',
        backgroundName: this.backgroundObjectId === 'scene' ? 'Scene background' : 'Scene plate only'
      });
    },

    async refreshView() {
      app.refresh();
      await Promise.resolve();
      this.root = document.querySelector('[data-animation-page]');
      this.preview = this.root?.querySelector('wonky-animation-preview');
      this.setSelectValues();
      await this.configurePreview();
    },

    syncSelectedAnimationFromForm() {
      if (!this.selectedAnimation) return;
      const form = this.root?.querySelector('[data-animation-edit-form]');
      if (!form) return;
      const payload = readAnimationForm(form);
      this.selectedAnimation.name = payload.name || this.selectedAnimation.name;
      this.selectedAnimation.segments = payload.segments.map((segment, index) => ({
        id: this.selectedAnimation.segments[index]?.id ?? `draft-${Date.now()}-${index}`,
        object_animation_id: this.selectedAnimation.id,
        start_frame: segment.start_frame,
        end_frame: segment.end_frame,
        frame_duration_seconds: segment.frame_duration_seconds,
        sort_order: index,
        created_at: '',
        updated_at: ''
      }));
    },

    async onClick(event) {
      const selectButton = event.target.closest('[data-action="select-animation"]');
      if (selectButton) {
        this.selectedAnimationId = Number(selectButton.dataset.animationId);
        this.prepareState();
        await this.refreshView();
        return;
      }

      const addSegmentButton = event.target.closest('[data-action="add-segment"]');
      if (addSegmentButton) {
        this.addSegment();
        return;
      }

      const removeSegmentButton = event.target.closest('[data-action="remove-segment"]');
      if (removeSegmentButton) {
        this.removeSegment(Number(removeSegmentButton.dataset.segmentIndex));
        return;
      }

      const deleteButton = event.target.closest('[data-action="delete-animation"]');
      if (deleteButton) {
        await this.deleteAnimation(deleteButton);
      }
    },

    async onSubmit(event) {
      const createForm = event.target.closest('[data-animation-create-form]');
      if (createForm) {
        event.preventDefault();
        await this.createAnimation(createForm);
        return;
      }

      const editForm = event.target.closest('[data-animation-edit-form]');
      if (editForm) {
        event.preventDefault();
        await this.saveAnimation(editForm);
      }
    },

    async onChange(event) {
      const backgroundSelect = event.target.closest('[name="backgroundObjectId"]');
      if (backgroundSelect) {
        this.backgroundObjectId = backgroundSelect.value;
        this.prepareState();
        await this.refreshView();
        return;
      }

      const editField = event.target.closest('[data-animation-edit-form] input');
      if (!editField) return;
      await this.refreshDraftAnimationView();
    },

    async refreshDraftAnimationView() {
      if (!this.selectedAnimation) return;
      this.syncSelectedAnimationFromForm();
      this.prepareState();
      await this.refreshView();
    },

    onPreviewError(event) {
      const frame = event.detail?.frame;
      const frameLabel = frame ? `frame ${frame.frameIndex}` : 'a frame';
      this.setStatus(`Could not load ${frameLabel} for preview.`);
    },

    async onKeyDown(event) {
      if (event.defaultPrevented || event.altKey) return;
      const key = event.key;
      const lowerKey = key.toLowerCase();
      const editable = isEditableTarget(event.target);

      if ((event.ctrlKey || event.metaKey) && lowerKey === 's') {
        const form = this.root?.querySelector('[data-animation-edit-form]');
        if (!form || !this.selectedAnimation) return;
        event.preventDefault();
        await this.saveAnimation(form);
        return;
      }

      if (editable || event.ctrlKey || event.metaKey) return;

      if (key === 'ArrowLeft') {
        event.preventDefault();
        await this.preview?.previous();
        return;
      }
      if (key === 'ArrowRight') {
        event.preventDefault();
        await this.preview?.next();
        return;
      }
      if (key === 'Home') {
        event.preventDefault();
        await this.preview?.first();
        return;
      }
      if (key === 'End') {
        event.preventDefault();
        await this.preview?.last();
        return;
      }
      if (lowerKey === 'f') {
        event.preventDefault();
        this.preview?.fitToView();
        return;
      }
      if (key === ' ') {
        event.preventDefault();
        this.preview?.togglePlayback();
      }
    },

    async createAnimation(form) {
      const formData = new FormData(form);
      const name = String(formData.get('name') ?? '').trim();
      if (!name) return;
      this.setStatus('Creating animation...');
      const lastFrame = Math.max(0, (this.scene?.images?.length ?? 1) - 1);
      try {
        const animation = await apiFetch(`/api/scene-objects/${this.objectId}/animations`, {
          method: 'POST',
          body: JSON.stringify({
            name,
            segments: [
              {
                start_frame: 0,
                end_frame: lastFrame,
                frame_duration_seconds: DEFAULT_FRAME_DURATION
              }
            ]
          })
        });
        this.selectedAnimationId = animation.id;
        form.reset();
        await this.refreshData();
        await this.refreshView();
        notifyScenePreview(this.sceneId, 'animation-updated');
        this.setStatus('');
      } catch {
        this.setStatus('Could not create animation.');
      }
    },

    async saveAnimation(form) {
      if (!this.selectedAnimation) return;
      const payload = readAnimationForm(form);
      if (!payload.name || !payload.segments.length) return;
      this.setStatus('Saving animation...');
      try {
        const animation = await apiFetch(
          `/api/scene-objects/${this.objectId}/animations/${this.selectedAnimation.id}`,
          {
            method: 'PATCH',
            body: JSON.stringify(payload)
          }
        );
        this.selectedAnimationId = animation.id;
        await this.refreshData();
        await this.refreshView();
        notifyScenePreview(this.sceneId, 'animation-updated');
        this.setStatus('Saved.');
      } catch {
        this.setStatus('Could not save animation.');
      }
    },

    addSegment() {
      if (!this.selectedAnimation) return;
      this.syncSelectedAnimationFromForm();
      const lastSegment = this.selectedAnimation.segments.at(-1);
      const nextStart = lastSegment ? lastSegment.end_frame : 0;
      this.selectedAnimation.segments.push({
        id: `draft-${Date.now()}`,
        object_animation_id: this.selectedAnimation.id,
        start_frame: nextStart,
        end_frame: nextStart,
        frame_duration_seconds: DEFAULT_FRAME_DURATION,
        sort_order: this.selectedAnimation.segments.length,
        created_at: '',
        updated_at: ''
      });
      this.prepareState();
      this.refreshView();
    },

    removeSegment(segmentIndex) {
      if (!this.selectedAnimation || Number.isNaN(segmentIndex)) return;
      this.syncSelectedAnimationFromForm();
      this.selectedAnimation.segments.splice(segmentIndex, 1);
      this.prepareState();
      this.refreshView();
    },

    async deleteAnimation(button) {
      const animationId = Number(button.dataset.animationId);
      if (!animationId) return;
      const animationName = button.dataset.animationName ?? 'this animation';
      if (!window.confirm(`Remove ${animationName}?`)) return;
      button.disabled = true;
      this.setStatus('Removing animation...');
      try {
        await apiFetch(`/api/scene-objects/${this.objectId}/animations/${animationId}`, {
          method: 'DELETE'
        });
        if (this.selectedAnimationId === animationId) this.selectedAnimationId = null;
        await this.refreshData();
        await this.refreshView();
        notifyScenePreview(this.sceneId, 'animation-updated');
        this.setStatus('');
      } catch {
        button.disabled = false;
        this.setStatus('Could not remove animation.');
      }
    }
  };

  try {
    await controller.refreshData();
  } catch {
    controller.editorReady = false;
    controller.editorMissing = true;
  }
  return controller;
};

function readAnimationForm(form) {
  const formData = new FormData(form);
  const segmentRows = Array.from(form.querySelectorAll('[data-segment-row]'));
  return {
    name: String(formData.get('name') ?? '').trim(),
    segments: segmentRows.map(row => ({
      start_frame: Number(row.querySelector('[name="start_frame"]')?.value ?? 0),
      end_frame: Number(row.querySelector('[name="end_frame"]')?.value ?? 0),
      frame_duration_seconds: Number(row.querySelector('[name="frame_duration_seconds"]')?.value ?? DEFAULT_FRAME_DURATION)
    }))
  };
}

function buildFrameRows(animation, scene, object) {
  const rows = [];
  for (const segment of animation.segments ?? []) {
    const start = Number(segment.start_frame);
    const end = Number(segment.end_frame);
    const step = start <= end ? 1 : -1;
    for (let frameIndex = start; step > 0 ? frameIndex <= end : frameIndex >= end; frameIndex += step) {
      const sceneImage = scene.images[frameIndex] ?? null;
      const mask = sceneImage ? selectMaskForSceneImage(object, sceneImage) : null;
      rows.push({
        frameIndex,
        durationSeconds: Number(segment.frame_duration_seconds),
        durationLabel: `${Number(segment.frame_duration_seconds).toFixed(3)}s`,
        filename: sceneImage?.original_filename ?? 'missing frame',
        available: Boolean(mask),
        missing: !mask,
        mask
      });
    }
  }
  return rows;
}

function selectMaskForSceneImage(object, sceneImage) {
  if (!object || !sceneImage) return null;
  const candidates = (object.masks ?? []).filter(
    mask => mask.uploaded_file_id === sceneImage.uploaded_file_id
  );
  if (!candidates.length) return null;
  const promptMatches = candidates.filter(mask => mask.prompt_text === object.prompt);
  return latestMask(promptMatches.length ? promptMatches : candidates);
}

function latestMask(masks) {
  return masks.reduce((latest, mask) => {
    if (!latest) return mask;
    return Number(mask.id) > Number(latest.id) ? mask : latest;
  }, null);
}

function summarizeAnimation(animation) {
  if (!animation.segments?.length) return 'No frames';
  return animation.segments
    .map(segment => `${segment.start_frame}-${segment.end_frame} @ ${formatDuration(segment.frame_duration_seconds)}`)
    .join(', ');
}

function formatDuration(value) {
  const seconds = Number(value);
  if (Math.abs(seconds - DEFAULT_FRAME_DURATION) < 0.001) return '1/15s';
  if (Math.abs(seconds - 1 / 24) < 0.001) return '1/24s';
  if (Math.abs(seconds - 1 / 30) < 0.001) return '1/30s';
  if (Number.isInteger(seconds)) return `${seconds}s`;
  return `${seconds.toFixed(3)}s`;
}

function sceneBackgroundUrl(scene) {
  const images = scene?.images ?? [];
  if (!images.length) return '';
  const backgroundIndex = Math.max(0, Math.min(Number(scene?.background_frame_index ?? 0), images.length - 1));
  const backgroundImage = images[backgroundIndex];
  return backgroundImage ? uploadedFileUrl(backgroundImage.uploaded_file_id) : '';
}

function isEditableTarget(target) {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return Boolean(target.closest('input, textarea, select, [contenteditable="true"]'));
}

export {AnimationsCtrl};
