import {apiFetch, characterImageUrl} from '../api.js';
import {applyStatus} from '../status.js';
import {user} from '../state/user.js';

const CharactersCtrl = app => async () => {
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    characters: [],
    selectedCharacterId: null,
    selectedCharacter: null,
    status: '',
    characterFormStatus: '',
    globalHistoryUndoStack: [],
    globalHistoryRedoStack: [],
    canUndoGlobalHistory: false,
    canRedoGlobalHistory: false,
    suppressAutoSelectOnce: false,
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-characters-page]');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.root, 'submit', event => this.onSubmit(event));
      this.bind(this.root, 'change', event => this.onChange(event));
      this.bind(window, 'keydown', event => this.onKeyDown(event));
      this.setControlValues();
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
      this.characters = await apiFetch('/api/characters');
      this.prepareState();
    },

    prepareState() {
      this.characters = (this.characters ?? []).map(character => ({
        ...character,
        isSelected: Number(character.id) === Number(this.selectedCharacterId),
        basePreviewUrl: characterImageUrl(resolvePreferredImageId(character))
      }));
      if (!this.characters.some(character => Number(character.id) === Number(this.selectedCharacterId))) {
        if (this.suppressAutoSelectOnce) {
          this.suppressAutoSelectOnce = false;
          this.selectedCharacterId = null;
        } else {
          this.selectedCharacterId = this.characters[0]?.id ?? null;
        }
      }
      this.selectedCharacter = this.characters.find(character => Number(character.id) === Number(this.selectedCharacterId)) ?? null;
      this.canUndoGlobalHistory = this.globalHistoryUndoStack.length > 0;
      this.canRedoGlobalHistory = this.globalHistoryRedoStack.length > 0;
    },

    refreshView() {
      app.refresh();
      this.setControlValues();
    },

    setControlValues() {
      const form = this.root?.querySelector('[data-character-form]');
      if (!form) return;
      const character = this.selectedCharacter;
      form.elements.character_id.value = character?.id ?? '';
      form.elements.name.value = character?.name ?? '';
      form.elements.description.value = character?.description ?? '';
      form.elements.sort_order.value = character?.sort_order ?? 0;
      form.elements.default_x.value = character?.default_x ?? 960;
      form.elements.default_y.value = character?.default_y ?? 540;
      form.elements.default_scale.value = character?.default_scale ?? 1;
      applyStatus(this.root?.querySelector('[data-character-form-status]'), this.characterFormStatus);
    },

    setStatus(message) {
      this.status = message;
      applyStatus(this.root?.querySelector('[data-characters-status]'), message);
    },

    async onClick(event) {
      const selectCharacter = event.target.closest('[data-action="select-character"]');
      if (selectCharacter) {
        this.selectedCharacterId = Number(selectCharacter.dataset.characterId);
        this.characterFormStatus = '';
        this.prepareState();
        this.refreshView();
        return;
      }
      const newCharacter = event.target.closest('[data-action="new-character"]');
      if (newCharacter) {
        this.suppressAutoSelectOnce = true;
        this.selectedCharacterId = null;
        this.characterFormStatus = '';
        this.prepareState();
        this.refreshView();
        return;
      }
      const deleteCharacter = event.target.closest('[data-action="delete-character"]');
      if (deleteCharacter) {
        await this.deleteCharacter(Number(deleteCharacter.dataset.characterId));
        return;
      }
      const undoButton = event.target.closest('[data-action="undo-character-change"]');
      if (undoButton) {
        await this.undoGlobalHistoryChange();
        return;
      }
      const redoButton = event.target.closest('[data-action="redo-character-change"]');
      if (redoButton) {
        await this.redoGlobalHistoryChange();
      }
    },

    async onChange(event) {
      const form = event.target.closest('[data-character-form]');
      if (!form) return;
      if (!Number(form.elements.character_id?.value || 0)) return;
      await this.autosaveSelectedCharacterForm(form);
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
      const form = event.target.closest('[data-character-form]');
      if (!form) return;
      event.preventDefault();
      await this.saveCharacter(form);
    },

    readCharacterForm(form) {
      return {
        name: String(form.elements.name.value || '').trim(),
        description: String(form.elements.description.value || ''),
        sort_order: Number(form.elements.sort_order.value || 0),
        default_x: Number(form.elements.default_x.value || 960),
        default_y: Number(form.elements.default_y.value || 540),
        default_scale: Number(form.elements.default_scale.value || 1)
      };
    },

    async saveCharacter(form) {
      const payload = this.readCharacterForm(form);
      if (!payload.name) return;
      const characterId = Number(form.elements.character_id.value || 0);
      if (characterId) {
        await this.saveCharacterPayload(characterId, payload);
        return;
      }
      this.setStatus('Creating character...');
      try {
        const saved = await apiFetch('/api/characters', {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        this.selectedCharacterId = saved.id;
        this.characterFormStatus = '';
        await this.refreshData();
        this.refreshView();
        this.setStatus('Character created.');
      } catch {
        this.setStatus('Could not create character.');
      }
    },

    async saveCharacterPayload(characterId, payload, {statusMessage = 'Saving...', successMessage = 'All character changes saved.', failureMessage = 'Could not save character.'} = {}) {
      this.characterFormStatus = statusMessage;
      this.refreshView();
      try {
        await apiFetch(`/api/characters/${characterId}`, {
          method: 'PATCH',
          body: JSON.stringify(payload)
        });
        this.selectedCharacterId = characterId;
        await this.refreshData();
        this.characterFormStatus = successMessage;
        this.refreshView();
        return true;
      } catch {
        this.characterFormStatus = failureMessage;
        this.refreshView();
        return false;
      }
    },

    async autosaveSelectedCharacterForm(form) {
      const characterId = Number(form.elements.character_id.value || 0);
      if (!characterId || !this.selectedCharacter) return;
      const previousPayload = {
        name: String(this.selectedCharacter.name ?? ''),
        description: String(this.selectedCharacter.description ?? ''),
        sort_order: Number(this.selectedCharacter.sort_order ?? 0),
        default_x: Number(this.selectedCharacter.default_x ?? 960),
        default_y: Number(this.selectedCharacter.default_y ?? 540),
        default_scale: Number(this.selectedCharacter.default_scale ?? 1)
      };
      const nextPayload = this.readCharacterForm(form);
      if (JSON.stringify(previousPayload) === JSON.stringify(nextPayload)) return;
      const saved = await this.saveCharacterPayload(characterId, nextPayload);
      if (!saved) return;
      this.recordGlobalHistoryEntry({
        label: 'Edit character',
        undo: () => this.restoreCharacterPayload(characterId, previousPayload),
        redo: () => this.restoreCharacterPayload(characterId, nextPayload)
      });
    },

    async restoreCharacterPayload(characterId, payload) {
      await this.saveCharacterPayload(characterId, payload, {
        statusMessage: 'Saving...',
        successMessage: 'All character changes saved.',
        failureMessage: 'Could not restore character.'
      });
    },

    async deleteCharacter(characterId) {
      if (!window.confirm('Remove this character and its backing scene?')) return;
      this.setStatus('Removing character...');
      try {
        await apiFetch(`/api/characters/${characterId}`, {method: 'DELETE'});
        if (Number(this.selectedCharacterId) === Number(characterId)) this.selectedCharacterId = null;
        this.characterFormStatus = '';
        await this.refreshData();
        this.refreshView();
        this.setStatus('Character removed.');
      } catch {
        this.setStatus('Could not remove character.');
      }
    },

    recordGlobalHistoryEntry(entry) {
      this.globalHistoryUndoStack.push(entry);
      if (this.globalHistoryUndoStack.length > 200) this.globalHistoryUndoStack.shift();
      this.globalHistoryRedoStack = [];
      this.prepareState();
      this.refreshView();
    },

    async undoGlobalHistoryChange() {
      const entry = this.globalHistoryUndoStack.pop();
      if (!entry) return;
      await entry.undo();
      this.globalHistoryRedoStack.push(entry);
      this.prepareState();
      this.refreshView();
    },

    async redoGlobalHistoryChange() {
      const entry = this.globalHistoryRedoStack.pop();
      if (!entry) return;
      await entry.redo();
      this.globalHistoryUndoStack.push(entry);
      this.prepareState();
      this.refreshView();
    }
  };

  await controller.refreshData();
  return controller;
};

function resolvePreferredImageId(character) {
  const images = character?.images ?? [];
  return images.find(image => image.is_default)?.id ?? images[0]?.id ?? 0;
}

export {CharactersCtrl};
