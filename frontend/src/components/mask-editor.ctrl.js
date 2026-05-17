import {apiFetch} from '../api.js';
import {applyStatus} from '../status.js';
import {
  findScene,
  loadScene,
  replaceScene,
  scenes
} from '../state/scenes.js';
import {notifyScenePreview} from '../preview-sync.js';
import {user} from '../state/user.js';
import './mask-editor-element.js';

const MaskEditorCtrl = app => async params => {
  const sceneId = Number(params[0]);
  const objectId = Number(params[1]);
  const maskId = Number(params[2]);
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    sceneId,
    objectId,
    maskId,
    scene: findScene(sceneId),
    object: null,
    masks: [],
    currentMask: null,
    currentIndex: 0,
    editorReady: false,
    editorMissing: false,
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-mask-editor-page]');
      this.editor = this.root?.querySelector('wonky-mask-editor');
      this.bind(this.editor, 'editor-message', event => this.setStatus(event.detail.message ?? ''));
      this.bind(this.editor, 'save-mask', event => this.saveMask(event));
      this.bind(this.editor, 'process-mask', event => this.processMask(event));
      this.bind(this.editor, 'set-default-frame', event => this.setDefaultFrame(event));
      this.bind(window, 'keydown', event => this.onKeyDown(event));
      await this.configureEditor();
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

    async refreshScene() {
      this.scene = replaceScene(await loadScene(this.sceneId));
      this.object = this.scene.objects.find(sceneObject => sceneObject.id === this.objectId) ?? null;
      this.masks = this.object?.masks ?? [];
      this.currentIndex = this.masks.findIndex(mask => mask.id === this.maskId);
      if (this.currentIndex < 0) this.currentIndex = 0;
      this.currentMask = this.masks[this.currentIndex] ?? null;
      this.editorReady = Boolean(this.currentMask);
      this.editorMissing = !this.editorReady;
    },

    async configureEditor() {
      if (!this.editor || !this.editorReady) return;
      await this.editor.configure({
        scene: this.scene,
        object: this.object,
        masks: this.masks,
        currentIndex: this.currentIndex
      });
    },

    setStatus(message) {
      const status = document.querySelector('[data-editor-status]');
      applyStatus(status, message);
    },

    onKeyDown(event) {
      if (shouldIgnoreShortcut(event)) return;
      if (event.key === 'ArrowLeft' || event.key.toLowerCase() === 'a') {
        event.preventDefault();
        this.editor?.navigate(-1);
        return;
      }
      if (event.key === 'ArrowRight' || event.key.toLowerCase() === 'd') {
        event.preventDefault();
        this.editor?.navigate(1);
        return;
      }
      if (event.key.toLowerCase() === 's') {
        event.preventDefault();
        this.editor?.dispatchSave();
      }
    },

    async saveMask(event) {
      if (!this.editor || !event?.detail?.uploadedFileId) return;
      this.setStatus(event.detail.applyAll ? 'Saving edits to all frames...' : 'Saving mask...');
      try {
        if (event.detail.applyAll) {
          const edits = await this.editor.exportEditedBlobsForAll();
          for (const edit of edits) {
            await uploadMaskBlob(edit.mask.id, edit.blob);
          }
        } else {
          let maskId = Number(event.detail.maskId ?? 0);
          if (!maskId) {
            const createdMask = await apiFetch(`/api/scenes/${this.sceneId}/objects/${this.objectId}/masks`, {
              method: 'POST',
              body: JSON.stringify({
                uploaded_file_id: Number(event.detail.uploadedFileId)
              })
            });
            maskId = Number(createdMask.id);
          }
          this.maskId = maskId;
          await uploadMaskBlob(maskId, await this.editor.exportCurrentBlob());
        }
        await this.refreshScene();
        await this.configureEditor();
        notifyScenePreview(this.sceneId, 'mask-updated');
        this.setStatus('Saved.');
      } catch {
        this.setStatus('Could not save mask edits.');
      }
    },

    async processMask(event) {
      if (!event?.detail?.maskId) return;
      const operationLabels = {
        grow: 'Growing mask...',
        fill_holes: 'Filling holes...',
        combine: 'Combining masks across frames...',
        invert: 'Inverting mask...',
        solid: 'Creating solid mask...',
        clear: 'Clearing mask...'
      };
      const label = operationLabels[event.detail.operation] ?? 'Processing mask...';
      this.setStatus(event.detail.applyAll ? `${label} Applying to all frames...` : label);
      try {
        this.maskId = Number(event.detail.maskId);
        await apiFetch(`/api/object-masks/${this.maskId}/process`, {
          method: 'POST',
          body: JSON.stringify({
            operation: event.detail.operation,
            apply_all: event.detail.applyAll,
            pixels: 2
          })
        });
        await this.refreshScene();
        await this.configureEditor();
        notifyScenePreview(this.sceneId, 'mask-updated');
        this.setStatus('Mask operation complete.');
      } catch {
        this.setStatus('Could not process mask.');
      }
    },

    async setDefaultFrame(event) {
      if (!this.object || !event?.detail?.uploadedFileId) return;
      this.setStatus('Setting default frame...');
      try {
        if (event.detail.maskId) this.maskId = Number(event.detail.maskId);
        await apiFetch(`/api/scenes/${this.sceneId}/objects/${this.objectId}/default-frame`, {
          method: 'POST',
          body: JSON.stringify({
            uploaded_file_id: Number(event.detail.uploadedFileId)
          })
        });
        await this.refreshScene();
        await this.configureEditor();
        notifyScenePreview(this.sceneId, 'object-updated');
        this.setStatus('Default frame updated.');
      } catch {
        this.setStatus('Could not update the default frame.');
      }
    }
  };

  try {
    controller.scene = replaceScene(await loadScene(sceneId));
    controller.object = controller.scene.objects.find(sceneObject => sceneObject.id === objectId) ?? null;
    controller.masks = controller.object?.masks ?? [];
    controller.currentIndex = controller.masks.findIndex(mask => mask.id === maskId);
    controller.currentMask = controller.masks[controller.currentIndex] ?? null;
    controller.editorReady = Boolean(controller.currentMask);
    controller.editorMissing = !controller.editorReady;
  } catch {
    controller.editorReady = false;
    controller.editorMissing = true;
  }
  return controller;
};

async function uploadMaskBlob(maskId, blob) {
  return apiFetch(`/api/object-masks/${maskId}/content`, {
    method: 'PUT',
    body: blob,
    headers: {'Content-Type': 'image/png'}
  });
}

function shouldIgnoreShortcut(event) {
  if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return true;
  const target = event.target;
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return Boolean(target.closest('input, textarea, select, [contenteditable="true"]'));
}

export {MaskEditorCtrl};
