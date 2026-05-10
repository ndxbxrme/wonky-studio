import {apiFetch} from '../api.js';
import {findScene, loadScene, replaceScene} from '../state/scenes.js';
import {user} from '../state/user.js';
import {listenScenePreview} from '../preview-sync.js';
import './scene-preview-element.js';

const PreviewCtrl = app => async params => {
  const sceneId = Number(params[0]);
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    sceneId,
    scene: findScene(sceneId),
    previewData: null,
    selectedObjectId: null,
    selectedAnimationId: null,
    previewObjects: [],
    selectedObject: null,
    selectedAnimation: null,
    showBackground: true,
    status: '',
    editorReady: false,
    editorMissing: false,
    unloadHandlers: [],
    previewSyncCleanup: null,

    async postLoad() {
      this.root = document.querySelector('[data-preview-page]');
      this.preview = this.root?.querySelector('wonky-scene-preview');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.previewSyncCleanup = listenScenePreview(this.sceneId, async () => {
        this.setStatus('Refreshing preview...');
        await this.refreshData();
        await this.refreshView();
        this.setStatus('');
      });
      await this.configurePreview();
    },

    unload() {
      this.unloadHandlers.forEach(unload => unload());
      this.unloadHandlers = [];
      this.previewSyncCleanup?.();
      this.previewSyncCleanup = null;
    },

    bind(target, type, handler) {
      if (!target) return;
      target.addEventListener(type, handler);
      this.unloadHandlers.push(() => target.removeEventListener(type, handler));
    },

    async refreshData() {
      try {
        this.scene = replaceScene(await loadScene(this.sceneId));
        this.previewData = await apiFetch(`/api/scenes/${this.sceneId}/preview-data`);
        this.prepareState();
        this.editorReady = Boolean(this.previewData);
        this.editorMissing = !this.editorReady;
      } catch {
        this.editorReady = false;
        this.editorMissing = true;
      }
    },

    prepareState() {
      const objects = (this.previewData?.objects ?? []).filter(
        object => object.default_render || object.animations?.length
      );
      if (!objects.some(object => object.id === this.selectedObjectId)) {
        this.selectedObjectId = objects.find(object => object.animations?.length)?.id ?? objects[0]?.id ?? null;
      }
      this.previewObjects = objects.map(object => ({
        ...object,
        isSelected: object.id === this.selectedObjectId,
        animationCount: object.animations?.length ?? 0,
        hasAnimations: Boolean(object.animations?.length)
      }));
      this.selectedObject = this.previewObjects.find(object => object.id === this.selectedObjectId) ?? null;
      if (!this.selectedObject?.animations?.some(animation => animation.id === this.selectedAnimationId)) {
        this.selectedAnimationId = this.selectedObject?.animations?.[0]?.id ?? null;
      }
      this.selectedAnimation = this.selectedObject?.animations?.find(
        animation => animation.id === this.selectedAnimationId
      ) ?? null;
      this.previewObjects = this.previewObjects.map(object => ({
        ...object,
        animations: (object.animations ?? []).map(animation => ({
          ...animation,
          isSelected:
            object.id === this.selectedObjectId && animation.id === this.selectedAnimationId,
          frameCount: animation.frames?.length ?? 0
        }))
      }));
    },

    async configurePreview() {
      if (!this.preview || !this.previewData) return;
      await this.preview.configure({
        ...this.previewData,
        showBackground: this.showBackground
      });
    },

    async refreshView() {
      app.refresh();
      await Promise.resolve();
      this.root = document.querySelector('[data-preview-page]');
      this.preview = this.root?.querySelector('wonky-scene-preview');
      await this.configurePreview();
    },

    setStatus(message) {
      this.status = message;
      const status = this.root?.querySelector('[data-preview-status]');
      if (status) status.textContent = message;
    },

    async onClick(event) {
      const refreshButton = event.target.closest('[data-action="refresh-preview"]');
      if (refreshButton) {
        this.setStatus('Refreshing preview...');
        await this.refreshData();
        await this.refreshView();
        this.setStatus('');
        return;
      }

      const selectObjectButton = event.target.closest('[data-action="select-preview-object"]');
      if (selectObjectButton) {
        this.selectedObjectId = Number(selectObjectButton.dataset.objectId);
        this.prepareState();
        await this.refreshView();
        return;
      }

      const playButton = event.target.closest('[data-action="play-animation"]');
      if (playButton) {
        this.selectedObjectId = Number(playButton.dataset.objectId);
        this.selectedAnimationId = Number(playButton.dataset.animationId);
        this.prepareState();
        await this.refreshView();
        this.setStatus('Playing animation...');
        await this.preview?.playAnimation(this.selectedObjectId, this.selectedAnimationId);
        this.setStatus('');
        return;
      }

      const resetButton = event.target.closest('[data-action="reset-preview"]');
      if (resetButton) {
        this.preview?.stop();
        this.setStatus('');
        return;
      }

      const toggleBackgroundButton = event.target.closest('[data-action="toggle-background"]');
      if (toggleBackgroundButton) {
        this.showBackground = !this.showBackground;
        await this.refreshView();
      }
    }
  };

  await controller.refreshData();
  return controller;
};

export {PreviewCtrl};
