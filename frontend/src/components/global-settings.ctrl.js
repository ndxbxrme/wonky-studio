import {apiFetch} from '../api.js';
import {user} from '../state/user.js';

const KEY_CODE_OPTIONS = [
  'Escape', 'Enter', 'Space', 'Tab',
  'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
  'KeyI', 'KeyS', 'KeyQ', 'KeyE', 'KeyR', 'KeyT',
  'KeyA', 'KeyD', 'KeyW', 'Digit1', 'Digit2', 'Digit3'
].map(value => ({value, label: value}));

const GlobalSettingsCtrl = app => async () => {
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    globalSettings: null,
    overlayBindings: [],
    overlaySceneOptions: [],
    baseSceneOptions: [],
    keyCodeOptions: KEY_CODE_OPTIONS,
    status: '',
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-global-settings-page]');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.root, 'submit', event => this.onSubmit(event));
      this.bind(this.root, 'change', event => this.onChange(event));
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
      const [globalSettings, overlayBindings, scenes] = await Promise.all([
        apiFetch('/api/global-settings'),
        apiFetch('/api/overlay-bindings'),
        apiFetch('/api/scenes')
      ]);
      this.globalSettings = globalSettings;
      this.overlayBindings = overlayBindings;
      this.overlaySceneOptions = scenes.filter(scene => scene.presentation_mode === 'overlay');
      this.baseSceneOptions = scenes
        .filter(scene => scene.presentation_mode !== 'overlay')
        .sort((left, right) => Number(left.id) - Number(right.id));
    },

    setControlValues() {
      const form = this.root?.querySelector('[data-global-overlay-settings-form]');
      if (!form || !this.globalSettings) return;
      form.elements.overlay_open_duration_seconds.value = String(this.globalSettings.overlay_open_duration_seconds ?? 0.22);
      form.elements.overlay_close_duration_seconds.value = String(this.globalSettings.overlay_close_duration_seconds ?? 0.18);
      form.elements.overlay_affect_audio.checked = Boolean(this.globalSettings.overlay_affect_audio);
      form.elements.start_scene_id.value = this.globalSettings.start_scene_id ? String(this.globalSettings.start_scene_id) : '';
    },

    async onClick(event) {
      const deleteButton = event.target.closest('[data-action="delete-overlay-binding"]');
      if (deleteButton) {
        await this.deleteOverlayBinding(deleteButton.dataset.bindingId);
      }
    },

    async onSubmit(event) {
      const settingsForm = event.target.closest('[data-global-overlay-settings-form]');
      if (settingsForm) {
        event.preventDefault();
        await this.saveGlobalSettings(settingsForm);
        return;
      }
      const bindingForm = event.target.closest('[data-overlay-binding-form]');
      if (bindingForm) {
        event.preventDefault();
        await this.saveOverlayBinding(bindingForm);
      }
    },

    onChange(event) {
      if (event.target.matches('[name="key_code"]')) {
        const note = this.root?.querySelector('[data-escape-note]');
        if (note) {
          note.hidden = String(event.target.value) !== 'Escape';
        }
      }
    },

    async saveGlobalSettings(form) {
      const formData = new FormData(form);
      this.setStatus('Saving global settings...');
      try {
        this.globalSettings = await apiFetch('/api/global-settings', {
          method: 'PATCH',
          body: JSON.stringify({
            overlay_open_duration_seconds: Number(formData.get('overlay_open_duration_seconds') || 0.22),
            overlay_close_duration_seconds: Number(formData.get('overlay_close_duration_seconds') || 0.18),
            overlay_affect_audio: formData.get('overlay_affect_audio') === 'on',
            start_scene_id: formData.get('start_scene_id')
              ? Number(formData.get('start_scene_id'))
              : null
          })
        });
        this.setControlValues();
        this.setStatus('Global settings saved.');
      } catch {
        this.setStatus('Could not save global settings.');
      }
    },

    async saveOverlayBinding(form) {
      const formData = new FormData(form);
      this.setStatus('Saving overlay binding...');
      try {
        await apiFetch('/api/overlay-bindings', {
          method: 'POST',
          body: JSON.stringify({
            key_code: String(formData.get('key_code') ?? ''),
            overlay_scene_id: Number(formData.get('overlay_scene_id'))
          })
        });
        form.reset();
        await this.refreshData();
        app.refresh();
        this.setStatus('Overlay binding saved.');
      } catch {
        this.setStatus('Could not save overlay binding.');
      }
    },

    async deleteOverlayBinding(bindingId) {
      const numericId = Number(bindingId);
      if (!numericId) return;
      this.setStatus('Removing overlay binding...');
      try {
        await apiFetch(`/api/overlay-bindings/${numericId}`, {method: 'DELETE'});
        await this.refreshData();
        app.refresh();
        this.setStatus('Overlay binding removed.');
      } catch {
        this.setStatus('Could not remove overlay binding.');
      }
    },

    setStatus(message) {
      this.status = message;
      const status = this.root?.querySelector('[data-global-settings-status]');
      if (status) status.textContent = message;
    }
  };

  await controller.refreshData();
  return controller;
};

export {GlobalSettingsCtrl};
