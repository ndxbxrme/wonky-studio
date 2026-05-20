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

const LANGUAGE_OPTIONS = [
  {code: 'en', label: 'English', placeholder: 'look'},
  {code: 'de', label: 'German', placeholder: 'schauen'},
  {code: 'es', label: 'Spanish', placeholder: 'mirar'},
  {code: 'fr', label: 'French', placeholder: 'regarder'},
  {code: 'it', label: 'Italian', placeholder: 'guardare'},
  {code: 'pt', label: 'Portuguese', placeholder: 'olhar'}
];

const DEFAULT_INVENTORY_SLOT = {x: 512, y: 128, size: 96, origin: 'center'};

function clampNumber(value, min, max) {
  return Math.min(max, Math.max(min, Number(value) || 0));
}

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
    languageOptions: LANGUAGE_OPTIONS,
    status: '',
    isEditingVerb: false,
    verbSubmitLabel: 'Add verb',
    selectedVerbKey: '',
    hasVerbs: false,
    hasOverlayBindings: false,
    hasVerbTagBackground: false,
    hasInventoryBackground: false,
    verbTagBackgroundUrl: '',
    inventoryBackgroundUrl: '',
    cursorStates: [],
    selectedInventorySlotIndex: 0,
    draggingInventorySlotIndex: null,
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-global-settings-page]');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.root, 'submit', event => this.onSubmit(event));
      this.bind(this.root, 'change', event => this.onChange(event));
      this.bind(this.root, 'input', event => this.onInput(event));
      this.bind(this.root, 'pointerdown', event => this.onPointerDown(event));
      this.bind(window, 'pointermove', event => this.onPointerMove(event));
      this.bind(window, 'pointerup', () => this.onPointerUp());
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
      this.selectedVerbKey = this.verbs.find(verb => Number(verb.id) === Number(this.selectedVerbId))?.key ?? '';
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
        form.elements.verb_menu_show_disabled.value = this.globalSettings.verb_menu_show_disabled === false
          ? 'hide_disabled'
          : 'show_disabled';
      }
      const inventoryForm = this.root?.querySelector('[data-inventory-layout-form]');
      if (inventoryForm && this.globalSettings) {
        this.renderInventorySlotRows(this.globalSettings.inventory_slots ?? []);
      }
      const inventoryPreviewImage = this.root?.querySelector('[data-inventory-layout-preview-image]');
      if (inventoryPreviewImage instanceof HTMLImageElement) {
        inventoryPreviewImage.onload = () => this.syncInventoryLayoutPreview();
      }
      const cursorForm = this.root?.querySelector('[data-cursor-settings-form]');
      if (cursorForm) {
        for (const state of this.cursorStates) {
          const xControl = cursorForm.querySelector(`[name="${state.key}_hotspot_x"]`);
          const yControl = cursorForm.querySelector(`[name="${state.key}_hotspot_y"]`);
          if (xControl instanceof HTMLInputElement) xControl.value = String(state.hotspotX ?? 0);
          if (yControl instanceof HTMLInputElement) yControl.value = String(state.hotspotY ?? 0);
        }
      }
      const verbForm = this.root?.querySelector('[data-verb-form]');
      if (verbForm) {
        const selectedVerb = this.verbs.find(verb => Number(verb.id) === Number(this.selectedVerbId)) ?? null;
        verbForm.elements.verb_id.value = selectedVerb?.id ?? '';
        verbForm.elements.key.value = selectedVerb?.key ?? '';
        verbForm.elements.sort_order.value = String(selectedVerb?.sort_order ?? 0);
        verbForm.elements.enabled.checked = selectedVerb ? Boolean(selectedVerb.enabled) : true;
        for (const language of this.languageOptions) {
          const control = verbForm.elements[`label_${language.code}`];
          if (control) control.value = selectedVerb?.labels?.[language.code] ?? '';
        }
      }
      this.syncInventoryLayoutPreview();
    },

    async onClick(event) {
      const slotMarker = event.target.closest('[data-action="select-inventory-slot-marker"]');
      if (slotMarker) {
        this.selectInventorySlot(Number(slotMarker.dataset.slotIndex));
        return;
      }
      const slotRow = event.target.closest('[data-inventory-slot-row]');
      if (slotRow && !event.target.closest('[data-action="remove-inventory-slot"]')) {
        this.selectInventorySlot(Number(slotRow.dataset.slotIndex));
      }
      const addInventorySlotButton = event.target.closest('[data-action="add-inventory-slot"]');
      if (addInventorySlotButton) {
        const slots = this.readInventorySlotRows(this.root?.querySelector('[data-inventory-layout-form]')) ?? [];
        slots.push({...DEFAULT_INVENTORY_SLOT});
        this.selectedInventorySlotIndex = slots.length - 1;
        this.renderInventorySlotRows(slots);
        return;
      }
      const removeInventorySlotButton = event.target.closest('[data-action="remove-inventory-slot"]');
      if (removeInventorySlotButton) {
        const row = removeInventorySlotButton.closest('[data-inventory-slot-row]');
        const removeIndex = Number(row?.dataset.slotIndex);
        const slots = this.readInventorySlotRows(this.root?.querySelector('[data-inventory-layout-form]')) ?? [];
        slots.splice(removeIndex, 1);
        this.selectedInventorySlotIndex = Math.max(0, Math.min(this.selectedInventorySlotIndex, slots.length - 1));
        this.renderInventorySlotRows(slots);
        return;
      }
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
        return;
      }
      const deleteVerbButton = event.target.closest('[data-action="delete-verb"]');
      if (deleteVerbButton) {
        await this.deleteVerb(deleteVerbButton);
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
      if (event.target.closest('[data-inventory-layout-form]')) {
        const row = event.target.closest('[data-inventory-slot-row]');
        if (row) this.selectInventorySlot(Number(row.dataset.slotIndex));
        this.syncInventoryLayoutPreview();
      }
    },

    onInput(event) {
      if (!event.target.closest('[data-inventory-layout-form]')) return;
      const row = event.target.closest('[data-inventory-slot-row]');
      if (row) this.selectInventorySlot(Number(row.dataset.slotIndex), {syncPreview: false});
      this.syncInventoryLayoutPreview();
    },

    onPointerDown(event) {
      const marker = event.target.closest('[data-action="select-inventory-slot-marker"]');
      if (!marker) return;
      event.preventDefault();
      this.selectedInventorySlotIndex = Number(marker.dataset.slotIndex);
      this.draggingInventorySlotIndex = this.selectedInventorySlotIndex;
      this.refreshInventorySlotSelection();
    },

    onPointerMove(event) {
      if (this.draggingInventorySlotIndex == null) return;
      const image = this.root?.querySelector('[data-inventory-layout-preview-image]');
      if (!(image instanceof HTMLImageElement) || !image.naturalWidth || !image.naturalHeight) return;
      const rect = image.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const scaleX = rect.width / image.naturalWidth;
      const scaleY = rect.height / image.naturalHeight;
      const x = clampNumber((event.clientX - rect.left) / scaleX, 0, image.naturalWidth);
      const y = clampNumber((event.clientY - rect.top) / scaleY, 0, image.naturalHeight);
      this.updateInventorySlotRow(this.draggingInventorySlotIndex, {x, y});
      this.syncInventoryLayoutPreview();
    },

    onPointerUp() {
      this.draggingInventorySlotIndex = null;
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
            verb_menu_timeout_seconds: Number(formData.get('verb_menu_timeout_seconds') || 4),
            verb_menu_show_disabled: String(formData.get('verb_menu_show_disabled') ?? 'show_disabled') !== 'hide_disabled'
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
        const inventorySlots = this.readInventorySlotRows(form);
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
            hotspot_x: Number(form.querySelector(`[name="${state.key}_hotspot_x"]`)?.value || 0),
            hotspot_y: Number(form.querySelector(`[name="${state.key}_hotspot_y"]`)?.value || 0)
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
        labels: this.readVerbLabels(form),
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

    async deleteVerb(button) {
      const verbId = Number(button.dataset.verbId);
      const verbKey = String(button.dataset.verbKey ?? '').trim();
      if (!verbId) return;
      if (!window.confirm(`Remove verb "${verbKey}"? Interactions using it will stop matching until updated.`)) return;
      this.setStatus('Removing verb...');
      try {
        await apiFetch(`/api/verbs/${verbId}`, {method: 'DELETE'});
        this.selectedVerbId = null;
        await this.refreshData();
        this.refreshView();
        this.setStatus('Verb removed.');
      } catch {
        this.setStatus('Could not remove verb.');
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

    inventorySlotsBody() {
      return this.root?.querySelector('[data-inventory-slots-body]') ?? null;
    },

    renderInventorySlotRows(slots) {
      const body = this.inventorySlotsBody();
      if (!body) return;
      const rows = Array.isArray(slots) && slots.length ? slots : [];
      if (!rows.length) {
        this.selectedInventorySlotIndex = 0;
        body.innerHTML = this.inventorySlotRowMarkup(DEFAULT_INVENTORY_SLOT, 0);
      } else {
        this.selectedInventorySlotIndex = Math.max(0, Math.min(this.selectedInventorySlotIndex, rows.length - 1));
        body.innerHTML = rows.map((slot, index) => this.inventorySlotRowMarkup(slot, index)).join('');
      }
      this.syncInventoryLayoutPreview();
    },

    inventorySlotRowMarkup(slot = null, index = 0) {
      const normalized = {
        x: Number(slot?.x ?? DEFAULT_INVENTORY_SLOT.x),
        y: Number(slot?.y ?? DEFAULT_INVENTORY_SLOT.y),
        size: Math.max(1, Number(slot?.size ?? DEFAULT_INVENTORY_SLOT.size) || DEFAULT_INVENTORY_SLOT.size),
        origin: 'center'
      };
      return `
        <tr data-inventory-slot-row data-slot-index="${index}" data-slot-origin="${normalized.origin}" class="${index === this.selectedInventorySlotIndex ? 'is-selected' : ''}">
          <td><input name="slot_x" type="number" step="1" value="${Math.round(normalized.x)}" /></td>
          <td><input name="slot_y" type="number" step="1" value="${Math.round(normalized.y)}" /></td>
          <td><input name="slot_size" type="number" min="1" step="1" value="${Math.round(normalized.size)}" /></td>
          <td class="settings-table__actions">
            <button class="button danger compact" type="button" data-action="remove-inventory-slot">X</button>
          </td>
        </tr>
      `;
    },

    readInventorySlotRows(form) {
      if (!form) return [];
      return [...form.querySelectorAll('[data-inventory-slots-body] [data-inventory-slot-row]')].map(row => ({
        x: Number(row.querySelector('[name="slot_x"]')?.value || DEFAULT_INVENTORY_SLOT.x),
        y: Number(row.querySelector('[name="slot_y"]')?.value || DEFAULT_INVENTORY_SLOT.y),
        size: Math.max(1, Number(row.querySelector('[name="slot_size"]')?.value || DEFAULT_INVENTORY_SLOT.size)),
        origin: 'center'
      }));
    },

    selectInventorySlot(index, options = {}) {
      if (!Number.isFinite(index)) return;
      this.selectedInventorySlotIndex = Math.max(0, Number(index));
      this.refreshInventorySlotSelection();
      if (options.syncPreview !== false) this.syncInventoryLayoutPreview();
    },

    refreshInventorySlotSelection() {
      for (const row of this.root?.querySelectorAll('[data-inventory-slot-row]') ?? []) {
        row.classList.toggle('is-selected', Number(row.dataset.slotIndex) === Number(this.selectedInventorySlotIndex));
      }
      for (const marker of this.root?.querySelectorAll('[data-inventory-slot-marker]') ?? []) {
        marker.classList.toggle('is-selected', Number(marker.dataset.slotIndex) === Number(this.selectedInventorySlotIndex));
      }
    },

    updateInventorySlotRow(index, values) {
      const row = this.root?.querySelector(`[data-inventory-slot-row][data-slot-index="${index}"]`);
      if (!row) return;
      if (values.x != null) row.querySelector('[name="slot_x"]').value = String(Math.round(values.x));
      if (values.y != null) row.querySelector('[name="slot_y"]').value = String(Math.round(values.y));
      if (values.size != null) row.querySelector('[name="slot_size"]').value = String(Math.max(1, Math.round(values.size)));
    },

    syncInventoryLayoutPreview() {
      const overlay = this.root?.querySelector('[data-inventory-layout-overlay]');
      const image = this.root?.querySelector('[data-inventory-layout-preview-image]');
      const form = this.root?.querySelector('[data-inventory-layout-form]');
      if (!(overlay instanceof HTMLElement) || !(image instanceof HTMLImageElement) || !form) return;
      const slots = this.readInventorySlotRows(form);
      if (!image.complete || !image.naturalWidth || !image.naturalHeight) {
        overlay.innerHTML = '';
        return;
      }
      const scaleX = image.clientWidth / image.naturalWidth;
      const scaleY = image.clientHeight / image.naturalHeight;
      overlay.innerHTML = slots.map((slot, index) => {
        const left = slot.x * scaleX;
        const top = slot.y * scaleY;
        const size = slot.size * scaleX;
        return `
          <button
            class="inventory-layout-editor__slot ${index === this.selectedInventorySlotIndex ? 'is-selected' : ''}"
            type="button"
            data-action="select-inventory-slot-marker"
            data-slot-index="${index}"
            style="left:${left}px; top:${top}px; width:${size}px; height:${size}px;"
          >
            <span>${index + 1}</span>
          </button>
        `;
      }).join('');
    },

    readVerbLabels(form) {
      const labels = {};
      for (const language of this.languageOptions) {
        const value = String(form.elements[`label_${language.code}`]?.value ?? '').trim();
        if (value) labels[language.code] = value;
      }
      return labels;
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
