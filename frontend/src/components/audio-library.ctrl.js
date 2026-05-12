import {apiFetch, audioAssetUrl} from '../api.js';
import {user} from '../state/user.js';

const AudioLibraryCtrl = app => async () => {
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    audioAssets: [],
    bgmAssets: [],
    sfxAssets: [],
    hasBgmAssets: false,
    hasSfxAssets: false,
    status: '',
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-audio-library-page]');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.root, 'submit', event => this.onSubmit(event));
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
      this.bgmAssets = this.audioAssets
        .filter(asset => asset.kind === 'bgm')
        .map(prepareAudioAsset);
      this.sfxAssets = this.audioAssets
        .filter(asset => asset.kind === 'sfx')
        .map(prepareAudioAsset);
      this.hasBgmAssets = this.bgmAssets.length > 0;
      this.hasSfxAssets = this.sfxAssets.length > 0;
    },

    async refreshData() {
      this.audioAssets = await apiFetch('/api/audio-assets');
      this.prepareState();
    },

    async onClick(event) {
      const deleteButton = event.target.closest('[data-action="delete-audio-asset"]');
      if (deleteButton) {
        await this.deleteAudioAsset(deleteButton.dataset.audioAssetId, deleteButton.dataset.audioAssetName);
      }
    },

    async onSubmit(event) {
      const uploadForm = event.target.closest('[data-audio-upload-form]');
      if (uploadForm) {
        event.preventDefault();
        await this.uploadAudioAsset(uploadForm);
        return;
      }
      const editForm = event.target.closest('[data-audio-asset-form]');
      if (editForm) {
        event.preventDefault();
        await this.saveAudioAsset(editForm);
      }
    },

    async uploadAudioAsset(form) {
      const formData = new FormData(form);
      if (!(formData.get('file') instanceof File) || !formData.get('file')?.size) return;
      this.setStatus('Uploading audio...');
      try {
        await apiFetch('/api/audio-assets', {
          method: 'POST',
          body: formData
        });
        form.reset();
        await this.refreshData();
        app.refresh();
        this.setStatus('Audio asset uploaded.');
      } catch {
        this.setStatus('Could not upload audio asset.');
      }
    },

    async saveAudioAsset(form) {
      const audioAssetId = Number(form.dataset.audioAssetId);
      if (!audioAssetId) return;
      const formData = new FormData(form);
      this.setStatus('Saving audio asset...');
      try {
        await apiFetch(`/api/audio-assets/${audioAssetId}`, {
          method: 'PATCH',
          body: JSON.stringify({
            name: String(formData.get('name') ?? '').trim(),
            kind: String(formData.get('kind') ?? 'sfx')
          })
        });
        await this.refreshData();
        app.refresh();
        this.setStatus('Audio asset saved.');
      } catch {
        this.setStatus('Could not save audio asset.');
      }
    },

    async deleteAudioAsset(audioAssetId, audioAssetName) {
      if (!audioAssetId) return;
      if (!window.confirm(`Delete audio asset "${audioAssetName}"?`)) return;
      this.setStatus('Deleting audio asset...');
      try {
        await apiFetch(`/api/audio-assets/${audioAssetId}`, {method: 'DELETE'});
        await this.refreshData();
        app.refresh();
        this.setStatus('Audio asset deleted.');
      } catch {
        this.setStatus('Could not delete audio asset.');
      }
    },

    setStatus(message) {
      this.status = message;
      const status = this.root?.querySelector('[data-audio-library-status]');
      if (status) status.textContent = message;
    }
  };

  await controller.refreshData();
  return controller;
};

function prepareAudioAsset(asset) {
  return {
    ...asset,
    isBgm: asset.kind === 'bgm',
    isSfx: asset.kind === 'sfx',
    audioUrl: audioAssetUrl(asset.id)
  };
}

export {AudioLibraryCtrl};
