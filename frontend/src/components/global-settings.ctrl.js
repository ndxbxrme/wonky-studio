import {apiFetch, globalSettingsAssetUrl} from '../api.js';
import {applyStatus} from '../status.js';
import {user} from '../state/user.js';

const KEY_CODE_OPTIONS = [
  'Escape', 'Enter', 'Space', 'Tab',
  'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
  'KeyI', 'KeyS', 'KeyQ', 'KeyE', 'KeyR', 'KeyT',
  'KeyA', 'KeyD', 'KeyW', 'Digit1', 'Digit2', 'Digit3'
].map(value => ({value, label: value}));

const CURSOR_STATE_OPTIONS = [
  {
    key: 'default',
    label: 'Default cursor',
    description: 'Shown over empty preview space when nothing special is happening.'
  },
  {
    key: 'hover_interactive',
    label: 'Hover interactive',
    description: 'Shown when the pointer is over a clickable or usable runtime target.'
  },
  {
    key: 'busy',
    label: 'Busy',
    description: 'Shown while the preview is actively loading or refreshing.'
  },
  {
    key: 'blocked',
    label: 'Blocked',
    description: 'Shown when the pointer is over a target that cannot be used in the current context.'
  }
];

const GlobalSettingsCtrl = app => async () => {
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    globalSettings: null,
    verbs: [],
    selectedVerbId: null,
    overlayBindings: [],
    overlaySceneOptions: [],
    baseSceneOptions: [],
    keyCodeOptions: KEY_CODE_OPTIONS,
    status: '',
    isEditingVerb: false,
    verbSubmitLabel: 'Add verb',
    hasVerbs: false,
    hasOverlayBindings: false,
    hasVerbTagBackground: false,
    hasInventoryBackground: false,
    verbTagBackgroundUrl: '',
    inventoryBackgroundUrl: '',
    cursorStates: [],
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
      const [globalSettings, overlayBindings, scenes, verbs] = await Promise.all([
        apiFetch('/api/global-settings'),
        apiFetch('/api/overlay-bindings'),
        apiFetch('/api/scenes'),
        apiFetch('/api/verbs')
      ]);
      this.globalSettings = globalSettings;
      this.overlayBindings = overlayBindings;
      this.overlaySceneOptions = scenes.filter(scene => scene.presentation_mode === 'overlay');
      this.baseSceneOptions = scenes
        .filter(scene => scene.presentation_mode !== 'overlay')
        .sort((left, right) => Number(left.id) - Number(right.id));
      this.verbs = verbs
        .map(verb => ({
          ...verb,
          labelSummary: Object.entries(verb.labels ?? {})
            .map(([language, text]) => `${language}: ${text}`)
            .join(' · '),
          isSelected: Number(verb.id) === Number(this.selectedVerbId)
        }));
      this.hasVerbs = this.verbs.length > 0;
      this.hasOverlayBindings = this.overlayBindings.length > 0;
      if (!this.verbs.some(verb => Number(verb.id) === Number(this.selectedVerbId))) {
        this.selectedVerbId = null;
      }
      this.isEditingVerb = Boolean(this.selectedVerbId);
      this.verbSubmitLabel = this.isEditingVerb ? 'Update verb' : 'Add verb';
      this.hasVerbTagBackground = Boolean(this.globalSettings?.verb_tag_background_relative_path);
      this.hasInventoryBackground = Boolean(this.globalSettings?.inventory_background_relative_path);
      this.verbTagBackgroundUrl = this.hasVerbTagBackground
        ? `${globalSettingsAssetUrl('verb_tag_background')}?v=${encodeURIComponent(this.globalSettings.updated_at || '')}`
        : '';
      this.inventoryBackgroundUrl = this.hasInventoryBackground
        ? `${globalSettingsAssetUrl('inventory_background')}?v=${encodeURIComponent(this.globalSettings.updated_at || '')}`
        : '';
      this.cursorStates = CURSOR_STATE_OPTIONS.map(stateOption => {
        const state = this.globalSettings?.cursor_states?.[stateOption.key] ?? {};
        const hasAsset = Boolean(state.relative_path);
        return {
          ...stateOption,
          hasAsset,
          hotspotX: Number(state.hotspot_x ?? 0),
          hotspotY: Number(state.hotspot_y ?? 0),
          previewUrl: hasAsset
            ? `${globalSettingsAssetUrl(`cursor_${stateOption.key}`)}?v=${encodeURIComponent(this.globalSettings.updated_at || '')}`
            : ''
        };
      });
    },

    setControlValues() {
      const form = this.root?.querySelector('[data-global-overlay-settings-form]');
      if (form && this.globalSettings) {
        form.elements.overlay_open_duration_seconds.value = String(this.globalSettings.overlay_open_duration_seconds ?? 0.22);
        form.elements.overlay_close_duration_seconds.value = String(this.globalSettings.overlay_close_duration_seconds ?? 0.18);
        form.elements.overlay_affect_audio.checked = Boolean(this.globalSettings.overlay_affect_audio);
        form.elements.start_scene_id.value = this.globalSettings.start_scene_id ? String(this.globalSettings.start_scene_id) : '';
        form.elements.inventory_key_code.value = this.globalSettings.inventory_key_code ?? 'KeyI';
        form.elements.verb_menu_timeout_seconds.value = String(this.globalSettings.verb_menu_timeout_seconds ?? 4);
      }
      const inventoryForm = this.root?.querySelector('[data-inventory-layout-form]');
      if (inventoryForm && this.globalSettings) {
        inventoryForm.elements.inventory_slots_json.value = JSON.stringify(this.globalSettings.inventory_slots ?? [], null, 2);
      }
      const cursorForm = this.root?.querySelector('[data-cursor-settings-form]');
      if (cursorForm) {
        for (const state of this.cursorStates) {
          const xControl = cursorForm.elements[`${state.key}_hotspot_x`];
          const yControl = cursorForm.elements[`${state.key}_hotspot_y`];
          if (xControl) xControl.value = String(state.hotspotX ?? 0);
          if (yControl) yControl.value = String(state.hotspotY ?? 0);
        }
      }
      const verbForm = this.root?.querySelector('[data-verb-form]');
      if (verbForm) {
        const selectedVerb = this.verbs.find(verb => Number(verb.id) === Number(this.selectedVerbId)) ?? null;
        verbForm.elements.verb_id.value = selectedVerb?.id ?? '';
        verbForm.elements.key.value = selectedVerb?.key ?? '';
        verbForm.elements.labels_json.value = JSON.stringify(selectedVerb?.labels ?? {}, null, 2);
        verbForm.elements.sort_order.value = String(selectedVerb?.sort_order ?? 0);
        verbForm.elements.enabled.checked = selectedVerb ? Boolean(selectedVerb.enabled) : true;
      }
    },

    async onClick(event) {
      const selectVerbButton = event.target.closest('[data-action="select-verb"]');
      if (selectVerbButton) {
        this.selectedVerbId = Number(selectVerbButton.dataset.verbId);
        await this.refreshData();
        this.refreshView();
        return;
      }
      const cancelVerbEditButton = event.target.closest('[data-action="cancel-verb-edit"]');
      if (cancelVerbEditButton) {
        this.selectedVerbId = null;
        await this.refreshData();
        this.refreshView();
        return;
      }
      const saveCursorSettingsButton = event.target.closest('[data-action="save-cursor-settings"]');
      if (saveCursorSettingsButton) {
        const cursorForm = this.root?.querySelector('[data-cursor-settings-form]');
        if (cursorForm) await this.saveCursorSettings(cursorForm);
        return;
      }
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
      const inventoryForm = event.target.closest('[data-inventory-layout-form]');
      if (inventoryForm) {
        event.preventDefault();
        await this.saveInventoryLayout(inventoryForm);
        return;
      }
      const bindingForm = event.target.closest('[data-overlay-binding-form]');
      if (bindingForm) {
        event.preventDefault();
        await this.saveOverlayBinding(bindingForm);
        return;
      }
      const verbForm = event.target.closest('[data-verb-form]');
      if (verbForm) {
        event.preventDefault();
        await this.saveVerb(verbForm);
        return;
      }
      const assetForm = event.target.closest('[data-global-asset-form]');
      if (assetForm) {
        event.preventDefault();
        await this.uploadGlobalAsset(assetForm);
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
            start_scene_id: formData.get('start_scene_id') ? Number(formData.get('start_scene_id')) : null,
            inventory_key_code: String(formData.get('inventory_key_code') ?? 'KeyI'),
            verb_menu_timeout_seconds: Number(formData.get('verb_menu_timeout_seconds') || 4)
          })
        });
        await this.refreshData();
        this.refreshView();
        this.setStatus('Global settings saved.');
      } catch {
        this.setStatus('Could not save global settings.');
      }
    },

    async saveInventoryLayout(form) {
      this.setStatus('Saving inventory layout...');
      try {
        const inventorySlots = JSON.parse(String(form.elements.inventory_slots_json.value || '[]'));
        this.globalSettings = await apiFetch('/api/global-settings', {
          method: 'PATCH',
          body: JSON.stringify({inventory_slots: inventorySlots})
        });
        await this.refreshData();
        this.refreshView();
        this.setStatus('Inventory layout saved.');
      } catch {
        this.setStatus('Could not save inventory layout.');
      }
    },

    async saveCursorSettings(form) {
      this.setStatus('Saving cursor settings...');
      try {
        const cursor_states = Object.fromEntries(this.cursorStates.map(state => [
          state.key,
          {
            hotspot_x: Number(form.elements[`${state.key}_hotspot_x`]?.value || 0),
            hotspot_y: Number(form.elements[`${state.key}_hotspot_y`]?.value || 0)
          }
        ]));
        this.globalSettings = await apiFetch('/api/global-settings', {
          method: 'PATCH',
          body: JSON.stringify({cursor_states})
        });
        await this.refreshData();
        this.refreshView();
        this.setStatus('Cursor settings saved.');
      } catch {
        this.setStatus('Could not save cursor settings.');
      }
    },

    async saveVerb(form) {
      const formData = new FormData(form);
      const verbId = Number(formData.get('verb_id'));
      const payload = {
        key: String(formData.get('key') ?? '').trim(),
        labels: JSON.parse(String(formData.get('labels_json') ?? '{}')),
        enabled: formData.get('enabled') === 'on',
        sort_order: Number(formData.get('sort_order') || 0)
      };
      if (!payload.key) return;
      this.setStatus(verbId ? 'Saving verb...' : 'Creating verb...');
      try {
        await apiFetch(verbId ? `/api/verbs/${verbId}` : '/api/verbs', {
          method: verbId ? 'PATCH' : 'POST',
          body: JSON.stringify(payload)
        });
        this.selectedVerbId = null;
        await this.refreshData();
        this.refreshView();
        this.setStatus(verbId ? 'Verb saved.' : 'Verb created.');
      } catch {
        this.setStatus(verbId ? 'Could not save verb.' : 'Could not create verb.');
      }
    },

    async uploadGlobalAsset(form) {
      const assetKind = form.dataset.globalAssetForm;
      const input = form.querySelector('input[type="file"]');
      const file = input?.files?.[0];
      if (!assetKind || !file) return;
      const formData = new FormData();
      formData.append('file', file);
      this.setStatus('Uploading asset...');
      try {
        this.globalSettings = await apiFetch(`/api/global-settings/assets/${assetKind}`, {
          method: 'POST',
          body: formData
        });
        await this.refreshData();
        this.refreshView();
        this.setStatus('Asset uploaded.');
      } catch {
        this.setStatus('Could not upload asset.');
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
        this.refreshView();
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
        this.refreshView();
        this.setStatus('Overlay binding removed.');
      } catch {
        this.setStatus('Could not remove overlay binding.');
      }
    },

    refreshView() {
      app.refresh();
      requestAnimationFrame(() => this.setControlValues());
    },

    setStatus(message) {
      this.status = message;
      const status = this.root?.querySelector('[data-global-settings-status]');
      applyStatus(status, message);
    }
  };

  await controller.refreshData();
  return controller;
};

export {GlobalSettingsCtrl};
