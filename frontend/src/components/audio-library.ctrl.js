import {apiFetch, audioAssetUrl} from '../api.js';
import {applyStatus} from '../status.js';
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
    audioAssetSaveStates: new Map(),
    globalHistoryUndoStack: [],
    globalHistoryRedoStack: [],
    canUndoGlobalHistory: false,
    canRedoGlobalHistory: false,
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-audio-library-page]');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.root, 'submit', event => this.onSubmit(event));
      this.bind(this.root, 'change', event => this.onChange(event));
      this.bind(window, 'keydown', event => this.onKeyDown(event));
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
      this.canUndoGlobalHistory = this.globalHistoryUndoStack.length > 0;
      this.canRedoGlobalHistory = this.globalHistoryRedoStack.length > 0;
    },

    async refreshData() {
      this.audioAssets = await apiFetch('/api/audio-assets');
      this.prepareState();
    },

    async onClick(event) {
      const undoButton = event.target.closest('[data-action="undo-audio-change"]');
      if (undoButton) {
        await this.undoGlobalHistoryChange();
        return;
      }
      const redoButton = event.target.closest('[data-action="redo-audio-change"]');
      if (redoButton) {
        await this.redoGlobalHistoryChange();
        return;
      }
      const deleteButton = event.target.closest('[data-action="delete-audio-asset"]');
      if (deleteButton) {
        await this.deleteAudioAsset(deleteButton.dataset.audioAssetId, deleteButton.dataset.audioAssetName);
      }
    },

    async onChange(event) {
      const editForm = event.target.closest('[data-audio-asset-form]');
      if (!editForm) return;
      await this.autosaveAudioAsset(editForm);
    },

    async onKeyDown(event) {
      if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
      const target = event.target;
      if (
        target instanceof HTMLInputElement
        || target instanceof HTMLTextAreaElement
        || target instanceof HTMLSelectElement
        || target?.isContentEditable
      ) {
        return;
      }
      const key = String(event.key || '').toLowerCase();
      if (key === 'z' && !event.shiftKey) {
        event.preventDefault();
        await this.undoGlobalHistoryChange();
        return;
      }
      if (key === 'y' || (key === 'z' && event.shiftKey)) {
        event.preventDefault();
        await this.redoGlobalHistoryChange();
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
        await this.autosaveAudioAsset(editForm);
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

    readAudioAssetForm(form) {
      return {
        name: String(form.elements.name.value ?? '').trim(),
        kind: String(form.elements.kind.value ?? 'sfx')
      };
    },

    currentAudioAssetPayload(audioAssetId) {
      const asset = (this.audioAssets ?? []).find(item => Number(item.id) === Number(audioAssetId));
      return asset ? {
        name: String(asset.name ?? ''),
        kind: String(asset.kind ?? 'sfx')
      } : null;
    },

    audioAssetStatusElement(audioAssetId) {
      return this.root?.querySelector(`[data-audio-asset-status="${audioAssetId}"]`);
    },

    ensureAudioAssetSaveState(audioAssetId) {
      const key = Number(audioAssetId);
      if (!this.audioAssetSaveStates.has(key)) {
        this.audioAssetSaveStates.set(key, {isSaving: false, saveQueued: false});
      }
      return this.audioAssetSaveStates.get(key);
    },

    async saveAudioAssetPayload(audioAssetId, payload, {statusMessage = 'Saving...', successMessage = 'All audio changes saved.', failureMessage = 'Could not save audio asset.'} = {}) {
      applyStatus(this.audioAssetStatusElement(audioAssetId), statusMessage);
      try {
        await apiFetch(`/api/audio-assets/${audioAssetId}`, {
          method: 'PATCH',
          body: JSON.stringify(payload)
        });
        await this.refreshData();
        app.refresh();
        applyStatus(this.audioAssetStatusElement(audioAssetId), successMessage);
        return true;
      } catch {
        applyStatus(this.audioAssetStatusElement(audioAssetId), failureMessage);
        return false;
      }
    },

    async autosaveAudioAsset(form) {
      const audioAssetId = Number(form.dataset.audioAssetId);
      if (!audioAssetId) return;
      const previousPayload = this.currentAudioAssetPayload(audioAssetId);
      const nextPayload = this.readAudioAssetForm(form);
      if (!previousPayload || JSON.stringify(previousPayload) === JSON.stringify(nextPayload)) return;
      const state = this.ensureAudioAssetSaveState(audioAssetId);
      state.saveQueued = true;
      if (state.isSaving) return;
      while (state.saveQueued) {
        state.saveQueued = false;
        state.isSaving = true;
        try {
          const saved = await this.saveAudioAssetPayload(audioAssetId, nextPayload);
          if (!saved) continue;
          this.recordGlobalHistoryEntry({
            label: 'Edit audio asset',
            undo: () => this.restoreAudioAssetPayload(audioAssetId, previousPayload),
            redo: () => this.restoreAudioAssetPayload(audioAssetId, nextPayload)
          });
        } finally {
          state.isSaving = false;
        }
      }
    },

    async restoreAudioAssetPayload(audioAssetId, payload) {
      await this.saveAudioAssetPayload(audioAssetId, payload, {
        statusMessage: 'Saving...',
        successMessage: 'All audio changes saved.',
        failureMessage: 'Could not restore audio asset.'
      });
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
      applyStatus(this.root?.querySelector('[data-audio-library-status]'), message);
    },

    recordGlobalHistoryEntry(entry) {
      this.globalHistoryUndoStack.push(entry);
      if (this.globalHistoryUndoStack.length > 200) this.globalHistoryUndoStack.shift();
      this.globalHistoryRedoStack = [];
      this.prepareState();
      app.refresh();
    },

    async undoGlobalHistoryChange() {
      const entry = this.globalHistoryUndoStack.pop();
      if (!entry) return;
      await entry.undo();
      this.globalHistoryRedoStack.push(entry);
      this.prepareState();
      app.refresh();
    },

    async redoGlobalHistoryChange() {
      const entry = this.globalHistoryRedoStack.pop();
      if (!entry) return;
      await entry.redo();
      this.globalHistoryUndoStack.push(entry);
      this.prepareState();
      app.refresh();
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
