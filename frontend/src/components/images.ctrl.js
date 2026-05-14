import {apiFetch, uploadedFileThumbnailUrl} from '../api.js';
import {loadScenes, scenes} from '../state/scenes.js';
import {user} from '../state/user.js';

const ImagesCtrl = app => async () => {
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    scenes,
    images: [],
    visibleImages: [],
    selectedUploadedFileIds: [],
    hasImages: false,
    hasVisibleImages: false,
    selectedCount: 0,
    sceneFilter: 'all',
    searchQuery: '',
    moveTargetSceneId: '',
    sceneFilterOptions: [],
    moveSceneOptions: [],
    status: '',
    reorderSceneId: null,
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-images-page]');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.root, 'submit', event => this.onSubmit(event));
      this.bind(this.root, 'change', event => this.onChange(event));
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

    prepareState() {
      const normalizedQuery = this.searchQuery.trim().toLowerCase();
      const filtered = this.images.filter(image => {
        if (this.sceneFilter === 'unassigned' && image.scene_id) return false;
        if (this.sceneFilter !== 'all' && this.sceneFilter !== 'unassigned') {
          if (Number(image.scene_id) !== Number(this.sceneFilter)) return false;
        }
        if (!normalizedQuery) return true;
        const haystack = `${image.original_filename} ${image.scene_title ?? ''}`.toLowerCase();
        return haystack.includes(normalizedQuery);
      });
      this.visibleImages = filtered.map(image => ({
        ...image,
        isSelected: this.selectedUploadedFileIds.includes(Number(image.uploaded_file_id))
      }));
      this.hasImages = this.images.length > 0;
      this.hasVisibleImages = this.visibleImages.length > 0;
      this.selectedCount = this.selectedUploadedFileIds.length;
      const reorderSceneId = this.sceneFilter !== 'all' && this.sceneFilter !== 'unassigned'
        ? Number(this.sceneFilter)
        : null;
      this.reorderSceneId = Number.isFinite(reorderSceneId) ? reorderSceneId : null;
      if (!this.moveTargetSceneId && scenes[0]?.id) this.moveTargetSceneId = String(scenes[0].id);
      this.sceneFilterOptions = [
        {value: 'all', label: 'All images', selected: this.sceneFilter === 'all'},
        {value: 'unassigned', label: 'Unassigned', selected: this.sceneFilter === 'unassigned'},
        ...this.scenes.map(scene => ({
          value: String(scene.id),
          label: `Scene ${scene.id} · ${scene.title}`,
          selected: String(this.sceneFilter) === String(scene.id)
        }))
      ];
      this.moveSceneOptions = this.scenes.map(scene => ({
        id: String(scene.id),
        label: `Scene ${scene.id} · ${scene.title}`,
        selected: String(this.moveTargetSceneId) === String(scene.id)
      }));
    },

    async refreshData() {
      await loadScenes();
      this.images = (await apiFetch('/api/images')).map(prepareImageRecord);
      this.selectedUploadedFileIds = this.selectedUploadedFileIds.filter(uploadedFileId =>
        this.images.some(image => Number(image.uploaded_file_id) === Number(uploadedFileId))
      );
      this.prepareState();
    },

    async onClick(event) {
      const imageCard = event.target.closest('[data-image-card]');
      if (imageCard && !event.target.closest('button, input, select, label, a')) {
        this.toggleImageSelection(Number(imageCard.dataset.uploadedFileId));
        return;
      }

      const selectButton = event.target.closest('[data-action="toggle-image-selection"]');
      if (selectButton) {
        this.toggleImageSelection(Number(selectButton.dataset.uploadedFileId));
        return;
      }

      const selectAllButton = event.target.closest('[data-action="select-all-images"]');
      if (selectAllButton) {
        this.selectedUploadedFileIds = this.visibleImages.map(image => Number(image.uploaded_file_id));
        this.prepareState();
        app.refresh();
        return;
      }

      const clearButton = event.target.closest('[data-action="clear-image-selection"]');
      if (clearButton) {
        this.selectedUploadedFileIds = [];
        this.prepareState();
        app.refresh();
        return;
      }

      const moveUpButton = event.target.closest('[data-action="move-image-up"]');
      if (moveUpButton) {
        await this.moveImage(moveUpButton.dataset.sceneImageId, -1);
        return;
      }

      const moveDownButton = event.target.closest('[data-action="move-image-down"]');
      if (moveDownButton) {
        await this.moveImage(moveDownButton.dataset.sceneImageId, 1);
      }
    },

    async onSubmit(event) {
      const moveForm = event.target.closest('[data-image-move-form]');
      if (moveForm) {
        event.preventDefault();
        await this.moveSelectedImages(moveForm);
      }
    },

    async onChange(event) {
      const filterSelect = event.target.closest('[data-images-scene-filter]');
      if (filterSelect) {
        this.sceneFilter = String(filterSelect.value || 'all');
        this.prepareState();
        app.refresh();
        return;
      }

      const moveTargetSelect = event.target.closest('[name="target_scene_id"]');
      if (moveTargetSelect) {
        this.moveTargetSceneId = String(moveTargetSelect.value || '');
        this.prepareState();
        app.refresh();
        return;
      }

      const searchInput = event.target.closest('[data-images-search]');
      if (searchInput) {
        this.searchQuery = String(searchInput.value || '');
        this.prepareState();
        app.refresh();
      }
    },

    toggleImageSelection(uploadedFileId) {
      if (!uploadedFileId) return;
      if (this.selectedUploadedFileIds.includes(uploadedFileId)) {
        this.selectedUploadedFileIds = this.selectedUploadedFileIds.filter(id => id !== uploadedFileId);
      } else {
        this.selectedUploadedFileIds = [...this.selectedUploadedFileIds, uploadedFileId];
      }
      this.prepareState();
      app.refresh();
    },

    async moveSelectedImages(form) {
      if (!this.selectedUploadedFileIds.length) {
        this.setStatus('Select one or more images first.');
        return;
      }
      const formData = new FormData(form);
      const targetSceneId = Number(formData.get('target_scene_id'));
      if (!targetSceneId) {
        this.setStatus('Choose a target scene.');
        return;
      }
      this.setStatus(`Moving ${this.selectedUploadedFileIds.length} image${this.selectedUploadedFileIds.length === 1 ? '' : 's'}...`);
      try {
        await apiFetch('/api/images/move', {
          method: 'POST',
          body: JSON.stringify({
            uploaded_file_ids: this.images
              .filter(image => this.selectedUploadedFileIds.includes(Number(image.uploaded_file_id)))
              .map(image => Number(image.uploaded_file_id)),
            target_scene_id: targetSceneId
          })
        });
        this.selectedUploadedFileIds = [];
        await this.refreshData();
        app.refresh();
        this.setStatus('Images moved.');
      } catch {
        this.setStatus('Could not move images.');
      }
    },

    async moveImage(sceneImageId, direction) {
      const sceneId = Number(this.reorderSceneId);
      if (!sceneId || !sceneImageId || !Number.isFinite(direction)) return;
      const sceneImages = this.visibleImages
        .filter(image => Number(image.scene_id) === sceneId)
        .sort((left, right) => Number(left.sort_order) - Number(right.sort_order));
      const currentIndex = sceneImages.findIndex(image => Number(image.scene_image_id) === Number(sceneImageId));
      const targetIndex = currentIndex + direction;
      if (currentIndex < 0 || targetIndex < 0 || targetIndex >= sceneImages.length) return;
      const confirmed = window.confirm(
        'Reordering scene images can break animations and any authored frame references. Continue?'
      );
      if (!confirmed) return;
      const reordered = [...sceneImages];
      const [moved] = reordered.splice(currentIndex, 1);
      reordered.splice(targetIndex, 0, moved);
      this.setStatus('Saving image order...');
      try {
        await apiFetch(`/api/scenes/${sceneId}/images/reorder`, {
          method: 'POST',
          body: JSON.stringify({
            ordered_scene_image_ids: reordered.map(image => Number(image.scene_image_id))
          })
        });
        await this.refreshData();
        app.refresh();
        this.setStatus('Image order updated.');
      } catch {
        this.setStatus('Could not reorder images.');
      }
    },

    setStatus(message) {
      this.status = message;
      const status = this.root?.querySelector('[data-images-status]');
      if (status) status.textContent = message;
    }
  };

  await controller.refreshData();
  return controller;
};

function prepareImageRecord(image) {
  const cacheKey = shortCacheKey(`${image.created_at}|${image.sort_order ?? ''}|${image.scene_id ?? ''}`);
  return {
    ...image,
    sceneLabel: image.scene_title ? `Scene ${image.scene_id} · ${image.scene_title}` : 'Unassigned',
    thumbUrl: uploadedFileThumbnailUrl(image.uploaded_file_id, 320, cacheKey)
  };
}

function shortCacheKey(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `k${(hash >>> 0).toString(36)}`;
}

export {ImagesCtrl};
