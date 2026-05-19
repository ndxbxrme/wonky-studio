import {apiFetch} from '../api.js';
import {applyStatus} from '../status.js';
import {notifyScenePreview} from '../preview-sync.js';
import {user} from '../state/user.js';

const SYSTEM_VARIABLE_META = {
  primary_language: {
    badge: 'System',
    hint: 'Built-in language setting used by preview and runtime audio/subtitle playback.'
  },
  secondary_language: {
    badge: 'System',
    hint: 'Built-in language setting used for bilingual playback and subtitles.'
  },
  translation_mode: {
    badge: 'System',
    hint: 'Built-in playback mode controlling how primary and secondary languages are sequenced.'
  },
  master_volume: {
    badge: 'Volume',
    hint: 'Built-in master volume control used by preview and runtime audio playback.'
  },
  narrator_volume: {
    badge: 'Volume',
    hint: 'Built-in narrator and spoken-line volume control.'
  },
  music_volume: {
    badge: 'Volume',
    hint: 'Built-in background music volume control.'
  },
  sfx_volume: {
    badge: 'Volume',
    hint: 'Built-in sound-effect volume control.'
  }
};

const VariablesCtrl = app => async () => {
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    variables: [],
    selectedVariableId: null,
    selectedVariable: null,
    systemVariables: [],
    gameVariables: [],
    hasSystemVariables: false,
    hasGameVariables: false,
    hasVariables: false,
    isEditingVariable: false,
    variableSubmitLabel: 'Add variable',
    status: '',
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-variables-page]');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.root, 'submit', event => this.onSubmit(event));
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
      this.variables = await apiFetch('/api/variables');
      this.prepareState();
    },

    prepareState() {
      this.variables = this.variables.map(variable => ({
        ...variable,
        defaultValueText: String(variable.default_value ?? ''),
        isSystem: Boolean(SYSTEM_VARIABLE_META[variable.name]),
        systemBadge: SYSTEM_VARIABLE_META[variable.name]?.badge ?? '',
        systemHint: SYSTEM_VARIABLE_META[variable.name]?.hint ?? '',
        isSelected: Number(variable.id) === Number(this.selectedVariableId)
      })).sort((left, right) => {
        if (left.isSystem !== right.isSystem) return left.isSystem ? -1 : 1;
        return left.name.localeCompare(right.name);
      });
      if (!this.variables.some(variable => Number(variable.id) === Number(this.selectedVariableId))) {
        this.selectedVariableId = null;
        this.variables = this.variables.map(variable => ({...variable, isSelected: false}));
      }
      this.selectedVariable = this.variables.find(variable => Number(variable.id) === Number(this.selectedVariableId)) ?? null;
      this.systemVariables = this.variables.filter(variable => variable.isSystem);
      this.gameVariables = this.variables.filter(variable => !variable.isSystem);
      this.hasSystemVariables = this.systemVariables.length > 0;
      this.hasGameVariables = this.gameVariables.length > 0;
      this.hasVariables = this.variables.length > 0;
      this.isEditingVariable = Boolean(this.selectedVariableId);
      this.variableSubmitLabel = this.selectedVariable?.isSystem
        ? 'Update system value'
        : this.isEditingVariable
          ? 'Update variable'
          : 'Add variable';
    },

    refreshView() {
      app.refresh();
      requestAnimationFrame(() => this.setControlValues());
    },

    setControlValues() {
      const variableForm = this.root?.querySelector('[data-variable-form]');
      if (!variableForm) return;
      const selectedVariable = this.selectedVariable;
      variableForm.elements.variable_id.value = selectedVariable?.id ?? '';
      variableForm.elements.name.value = selectedVariable?.name ?? '';
      variableForm.elements.value_type.value = selectedVariable?.value_type ?? 'bool';
      variableForm.elements.default_value.value = selectedVariable?.defaultValueText ?? 'false';
      variableForm.elements.description.value = selectedVariable?.description ?? '';
      variableForm.elements.name.disabled = Boolean(selectedVariable?.isSystem);
      variableForm.elements.value_type.disabled = Boolean(selectedVariable?.isSystem);
    },

    setStatus(message) {
      this.status = message;
      const status = this.root?.querySelector('[data-variables-status]');
      applyStatus(status, message);
    },

    async onClick(event) {
      const selectVariableButton = event.target.closest('[data-action="select-variable"]');
      if (selectVariableButton) {
        this.selectedVariableId = Number(selectVariableButton.dataset.variableId);
        this.prepareState();
        this.refreshView();
        return;
      }

      const cancelVariableEditButton = event.target.closest('[data-action="cancel-variable-edit"]');
      if (cancelVariableEditButton) {
        this.selectedVariableId = null;
        this.prepareState();
        this.refreshView();
      }
    },

    async onSubmit(event) {
      const variableForm = event.target.closest('[data-variable-form]');
      if (!variableForm) return;
      event.preventDefault();
      await this.createVariable(variableForm);
    },

    async createVariable(form) {
      const variableId = Number(form.elements.variable_id?.value);
      if (variableId) {
        await this.saveVariable(form);
        return;
      }
      const payload = readVariableForm(form);
      if (!payload.name) return;
      this.setStatus('Creating variable...');
      try {
        await apiFetch('/api/variables', {method: 'POST', body: JSON.stringify(payload)});
        form.reset();
        this.selectedVariableId = null;
        await this.refreshData();
        this.refreshView();
        notifyScenePreview(null, 'variable-updated');
        this.setStatus('Variable created.');
      } catch {
        this.setStatus('Could not create variable.');
      }
    },

    async saveVariable(form) {
      const variableId = Number(form.elements.variable_id?.value);
      if (!variableId) return;
      const payload = readVariableForm(form);
      if (!payload.name) return;
      this.setStatus('Saving variable...');
      try {
        await apiFetch(`/api/variables/${variableId}`, {
          method: 'PATCH',
          body: JSON.stringify(payload)
        });
        this.selectedVariableId = null;
        await this.refreshData();
        this.refreshView();
        notifyScenePreview(null, 'variable-updated');
        this.setStatus('Variable saved.');
      } catch {
        this.setStatus('Could not save variable.');
      }
    }
  };

  await controller.refreshData();
  return controller;
};

function readVariableForm(form) {
  const valueType = String(form.elements.value_type?.value ?? 'bool');
  return {
    name: String(form.elements.name?.value ?? '').trim(),
    value_type: valueType,
    default_value: parseTypedValue(
      valueType,
      String(form.elements.default_value?.value ?? '')
    ),
    description: String(form.elements.description?.value ?? '')
  };
}

function parseTypedValue(valueType, rawValue) {
  const trimmed = rawValue.trim();
  if (valueType === 'bool') return ['true', '1', 'yes', 'on'].includes(trimmed.toLowerCase());
  if (valueType === 'number') return Number(trimmed || 0);
  return trimmed;
}

export {VariablesCtrl};
