import {apiFetch} from '../api.js';
import {
  findScene,
  loadScene,
  replaceScene,
  scenes
} from '../state/scenes.js';
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
      this.bind(this.editor, 'navigate-mask', event => this.navigateMask(event));
      this.bind(this.editor, 'save-mask', event => this.saveMask(event));
      this.bind(this.editor, 'process-mask', event => this.processMask(event));
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
      if (status) status.textContent = message;
    },

    navigateMask(event) {
      app.goto(`/mask-editor/${this.sceneId}/${this.objectId}/${event.detail.maskId}`);
    },

    async saveMask(event) {
      if (!this.editor || !this.currentMask) return;
      this.setStatus(event.detail.applyAll ? 'Saving edits to all frames...' : 'Saving mask...');
      try {
        if (event.detail.applyAll) {
          const edits = await this.editor.exportEditedBlobsForAll();
          for (const edit of edits) {
            await uploadMaskBlob(edit.mask.id, edit.blob);
          }
        } else {
          await uploadMaskBlob(this.currentMask.id, await this.editor.exportCurrentBlob());
        }
        await this.refreshScene();
        app.refresh();
        await this.configureEditor();
        this.setStatus('Saved.');
      } catch {
        this.setStatus('Could not save mask edits.');
      }
    },

    async processMask(event) {
      if (!this.currentMask) return;
      const label = event.detail.operation === 'grow' ? 'Growing mask...' : 'Filling holes...';
      this.setStatus(event.detail.applyAll ? `${label} Applying to all frames...` : label);
      try {
        await apiFetch(`/api/object-masks/${this.currentMask.id}/process`, {
          method: 'POST',
          body: JSON.stringify({
            operation: event.detail.operation,
            apply_all: event.detail.applyAll,
            pixels: 2
          })
        });
        await this.refreshScene();
        app.refresh();
        await this.configureEditor();
        this.setStatus('Mask operation complete.');
      } catch {
        this.setStatus('Could not process mask.');
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

export {MaskEditorCtrl};
