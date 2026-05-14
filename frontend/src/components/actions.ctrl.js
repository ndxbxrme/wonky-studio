import {apiFetch, scriptAudioCandidateUrl} from '../api.js';
import {findScene, loadScene, replaceScene} from '../state/scenes.js';
import {notifyScenePreview, openScenePreview} from '../preview-sync.js';
import {user} from '../state/user.js';

const ACTION_TYPES = [
  {value: 'play_animation', label: 'Play animation'},
  {value: 'go_to_frame', label: 'Go to frame'},
  {value: 'set_object_property', label: 'Set object property'},
  {value: 'show_subtitle', label: 'Show subtitle'},
  {value: 'play_audio', label: 'Play audio'},
  {value: 'set_variable', label: 'Set variable'},
  {value: 'increment_variable', label: 'Increment variable'},
  {value: 'toggle_variable', label: 'Toggle variable'},
  {value: 'add_inventory_item', label: 'Add inventory item'},
  {value: 'remove_inventory_item', label: 'Remove inventory item'},
  {value: 'clear_held_inventory_item', label: 'Clear held inventory item'},
  {value: 'if_variable', label: 'If variable'},
  {value: 'fade_out', label: 'Fade out'},
  {value: 'fade_in', label: 'Fade in'},
  {value: 'crossfade_bgm', label: 'Crossfade BGM'},
  {value: 'play_sfx', label: 'Play SFX'},
  {value: 'change_scene', label: 'Change scene'},
  {value: 'open_overlay_scene', label: 'Open overlay scene'},
  {value: 'close_overlay_scene', label: 'Close overlay scene'},
  {value: 'change_overlay_scene', label: 'Change overlay scene'},
  {value: 'delay', label: 'Delay'}
];

const KEY_CODE_OPTIONS = [
  'Escape', 'Enter', 'Space', 'Tab',
  'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
  'KeyI', 'KeyS', 'KeyQ', 'KeyE', 'KeyR', 'KeyT',
  'KeyA', 'KeyD', 'KeyW', 'Digit1', 'Digit2', 'Digit3'
].map(value => ({value, label: value}));

const ActionsCtrl = app => async params => {
  const sceneId = Number(params[0]);
  const routeOptions = readRouteOptions();
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    sceneId,
    scene: findScene(sceneId),
    variables: [],
    selectedVariableId: null,
    interactions: [],
    selectedInteractionId: routeOptions.interactionId,
    preselectedObjectId: routeOptions.objectId,
    selectedInteraction: null,
    objectOptions: [],
    sceneOptions: [],
    baseSceneOptions: [],
    audioAssetOptions: [],
    bgmOptions: [],
    sfxOptions: [],
    overlayBindings: [],
    overlaySceneOptions: [],
    verbs: [],
    inventoryObjectOptions: [],
    keyCodeOptions: KEY_CODE_OPTIONS,
    previousSceneId: null,
    nextSceneId: null,
    animationOptions: [],
    actionTypes: ACTION_TYPES,
    branchOptions: [],
    actionRows: [],
    scriptSearchResults: [],
    scriptSearchLanguage: 'en',
    status: '',
    hasInteractions: false,
    hasSelectedInteraction: false,
    hasVariables: false,
    hasScriptSearchResults: false,
    isEditingVariable: false,
    variableSubmitLabel: 'Add variable',
    editorReady: false,
    editorMissing: false,
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-actions-page]');
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
      try {
        this.scene = replaceScene(await loadScene(this.sceneId));
        this.sceneOptions = [{
          id: this.scene.id,
          title: this.scene.title
        }];
        this.variables = await apiFetch('/api/variables');
        this.sceneOptions = await apiFetch('/api/scenes');
        this.overlayBindings = await apiFetch('/api/overlay-bindings');
        this.verbs = await apiFetch('/api/verbs');
        this.inventoryObjectOptions = await apiFetch('/api/scene-objects');
        this.audioAssetOptions = await apiFetch('/api/audio-assets');
        this.bgmOptions = this.audioAssetOptions.filter(asset => asset.kind === 'bgm');
        this.sfxOptions = this.audioAssetOptions.filter(asset => asset.kind === 'sfx');
        this.overlaySceneOptions = this.sceneOptions.filter(item => item.presentation_mode === 'overlay');
        this.baseSceneOptions = this.sceneOptions.filter(item => item.presentation_mode !== 'overlay');
        this.prepareSceneNavigation();
        await this.loadAnimations();
        this.interactions = await apiFetch(`/api/scenes/${this.sceneId}/interactions`);
        if (!this.selectedInteractionId && this.interactions.length) {
          this.selectedInteractionId = this.interactions[0].id;
        }
        if (!this.interactions.some(interaction => interaction.id === this.selectedInteractionId)) {
          this.selectedInteractionId = this.interactions[0]?.id ?? null;
        }
        this.prepareState();
      } catch {
        this.editorReady = false;
        this.editorMissing = true;
      }
    },

    async loadAnimations() {
      const objects = this.scene?.objects ?? [];
      this.objectOptions = objects.map(object => ({id: object.id, name: object.name}));
      const animationGroups = await Promise.all(
        objects.map(async object => {
          try {
            const animations = object.animationCount
              ? await apiFetch(`/api/scene-objects/${object.id}/animations`)
              : [];
            return animations.map(animation => ({
              objectId: object.id,
              animationId: animation.id,
              label: `${object.name} / ${animation.name}`
            }));
          } catch {
            return [];
          }
        })
      );
      this.animationOptions = animationGroups.flat();
    },

    prepareState() {
      this.variables = this.variables.map(variable => ({
        ...variable,
        defaultValueText: String(variable.default_value ?? ''),
        isSelected: variable.id === this.selectedVariableId
      }));
      if (!this.variables.some(variable => variable.id === this.selectedVariableId)) {
        this.selectedVariableId = null;
        this.variables = this.variables.map(variable => ({...variable, isSelected: false}));
      }
      this.hasVariables = Boolean(this.variables.length);
      this.isEditingVariable = Boolean(this.selectedVariableId);
      this.variableSubmitLabel = this.isEditingVariable ? 'Update variable' : 'Add variable';
      this.overlayBindings = this.overlayBindings.map(binding => ({
        ...binding,
        overlaySceneLabel: this.overlaySceneOptions.find(scene => scene.id === binding.overlay_scene_id)?.title
          ?? binding.overlay_scene_title
          ?? `Scene ${binding.overlay_scene_id}`
      }));
      this.verbs = this.verbs.map(verb => ({
        ...verb,
        label: verb.labels?.en || Object.values(verb.labels ?? {})[0] || verb.key
      }));
      this.interactions = this.interactions.map(interaction => ({
        ...interaction,
        triggerLabel: triggerLabel(interaction, this.scene, this.variables, this.verbs, this.inventoryObjectOptions),
        stepCount: countSteps(interaction.action_tree ?? []),
        isSelected: interaction.id === this.selectedInteractionId
      }));
      this.selectedInteraction = this.interactions.find(
        interaction => interaction.id === this.selectedInteractionId
      ) ?? null;
      this.hasInteractions = Boolean(this.interactions.length);
      this.hasSelectedInteraction = Boolean(this.selectedInteraction);
      this.branchOptions = buildBranchOptions(this.selectedInteraction?.action_tree ?? []);
      this.actionRows = flattenActionRows(this.selectedInteraction?.action_tree ?? []);
      this.editorReady = Boolean(this.scene);
      this.editorMissing = !this.editorReady;
    },

    async onClick(event) {
      const selectButton = event.target.closest('[data-action="select-interaction"]');
      if (selectButton) {
        this.selectedInteractionId = Number(selectButton.dataset.interactionId);
        this.prepareState();
        this.refreshView();
        return;
      }

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
        return;
      }

      const deleteInteractionButton = event.target.closest('[data-action="delete-interaction"]');
      if (deleteInteractionButton) {
        await this.deleteInteraction(deleteInteractionButton);
        return;
      }

      const removeStepButton = event.target.closest('[data-action="remove-step"]');
      if (removeStepButton) {
        await this.removeStep(removeStepButton.dataset.stepId);
        return;
      }

      const moveStepButton = event.target.closest('[data-action="move-step"]');
      if (moveStepButton) {
        await this.moveStep(moveStepButton.dataset.stepId, moveStepButton.dataset.direction);
        return;
      }

      const addLineButton = event.target.closest('[data-action="add-script-line"]');
      if (addLineButton) {
        this.addScriptLineToActionForm(addLineButton.dataset.lineId);
        return;
      }

      const previewButton = event.target.closest('[data-action="open-preview"]');
      if (previewButton) {
        openScenePreview(this.sceneId);
        return;
      }

      const deleteOverlayBindingButton = event.target.closest('[data-action="delete-overlay-binding"]');
      if (deleteOverlayBindingButton) {
        await this.deleteOverlayBinding(deleteOverlayBindingButton);
      }
    },

    async onSubmit(event) {
      const variableForm = event.target.closest('[data-variable-form]');
      if (variableForm) {
        event.preventDefault();
        await this.createVariable(variableForm);
        return;
      }

      const interactionForm = event.target.closest('[data-interaction-create-form]');
      if (interactionForm) {
        event.preventDefault();
        await this.createInteraction(interactionForm);
        return;
      }

      const editForm = event.target.closest('[data-interaction-edit-form]');
      if (editForm) {
        event.preventDefault();
        await this.saveSelectedInteraction(readInteractionForm(editForm, this.selectedInteraction));
        return;
      }

      const actionForm = event.target.closest('[data-action-step-form]');
      if (actionForm) {
        event.preventDefault();
        await this.addActionStep(actionForm);
        return;
      }

      const searchForm = event.target.closest('[data-script-line-search-form]');
      if (searchForm) {
        event.preventDefault();
        await this.searchScriptLines(searchForm);
        return;
      }

      const sceneJumpForm = event.target.closest('[data-scene-jump-form]');
      if (sceneJumpForm) {
        event.preventDefault();
        this.goToScene(sceneJumpForm);
        return;
      }

      const overlayBindingForm = event.target.closest('[data-overlay-binding-form]');
      if (overlayBindingForm) {
        event.preventDefault();
        await this.saveOverlayBinding(overlayBindingForm);
      }
    },

    async onChange(event) {
      if (event.target.matches('[name="action_type"], [name="target_scope"]')) {
        this.updateActionFormVisibility(event.target.closest('[data-action-step-form]'));
        return;
      }
      if (event.target.matches('[name="property"]')) {
        this.updateActionFormVisibility(event.target.closest('[data-action-step-form]'));
      }
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
        notifyScenePreview(this.sceneId, 'variable-updated');
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
        notifyScenePreview(this.sceneId, 'variable-updated');
        this.setStatus('Variable saved.');
      } catch {
        this.setStatus('Could not save variable.');
      }
    },

    async createInteraction(form) {
      const payload = readInteractionForm(form, null);
      if (!payload.name) return;
      this.setStatus('Creating interaction...');
      try {
        const interaction = await apiFetch(`/api/scenes/${this.sceneId}/interactions`, {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        this.selectedInteractionId = interaction.id;
        form.reset();
        await this.refreshData();
        this.refreshView();
        notifyScenePreview(this.sceneId, 'interaction-updated');
        this.setStatus('Interaction created.');
      } catch {
        this.setStatus('Could not create interaction.');
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

    async deleteOverlayBinding(button) {
      const bindingId = Number(button.dataset.bindingId);
      if (!bindingId) return;
      this.setStatus('Removing overlay binding...');
      try {
        await apiFetch(`/api/overlay-bindings/${bindingId}`, {method: 'DELETE'});
        await this.refreshData();
        this.refreshView();
        this.setStatus('Overlay binding removed.');
      } catch {
        this.setStatus('Could not remove overlay binding.');
      }
    },

    async saveSelectedInteraction(payload) {
      if (!this.selectedInteraction) return;
      this.setStatus('Saving interaction...');
      try {
        await apiFetch(`/api/scenes/${this.sceneId}/interactions/${this.selectedInteraction.id}`, {
          method: 'PATCH',
          body: JSON.stringify(payload)
        });
        await this.refreshData();
        this.refreshView();
        notifyScenePreview(this.sceneId, 'interaction-updated');
        this.setStatus('Interaction saved.');
      } catch {
        this.setStatus('Could not save interaction.');
      }
    },

    async deleteInteraction(button) {
      if (!window.confirm(`Remove interaction "${button.dataset.interactionName}"?`)) return;
      this.setStatus('Removing interaction...');
      try {
        await apiFetch(
          `/api/scenes/${this.sceneId}/interactions/${button.dataset.interactionId}`,
          {method: 'DELETE'}
        );
        this.selectedInteractionId = null;
        await this.refreshData();
        this.refreshView();
        notifyScenePreview(this.sceneId, 'interaction-updated');
        this.setStatus('Interaction removed.');
      } catch {
        this.setStatus('Could not remove interaction.');
      }
    },

    async addActionStep(form) {
      if (!this.selectedInteraction) return;
      const step = readActionStepForm(form);
      const nextTree = insertStep(this.selectedInteraction.action_tree ?? [], form.elements.branch.value, step);
      await this.saveSelectedInteraction({
        ...interactionPayload(this.selectedInteraction),
        action_tree: nextTree
      });
      form.reset();
    },

    async removeStep(stepId) {
      if (!this.selectedInteraction) return;
      const nextTree = removeStepById(this.selectedInteraction.action_tree ?? [], stepId);
      await this.saveSelectedInteraction({
        ...interactionPayload(this.selectedInteraction),
        action_tree: nextTree
      });
    },

    async moveStep(stepId, direction) {
      if (!this.selectedInteraction) return;
      const nextTree = moveStepById(this.selectedInteraction.action_tree ?? [], stepId, direction);
      await this.saveSelectedInteraction({
        ...interactionPayload(this.selectedInteraction),
        action_tree: nextTree
      });
    },

    async searchScriptLines(form) {
      const formData = new FormData(form);
      const query = String(formData.get('q') ?? '').trim();
      this.scriptSearchLanguage = String(formData.get('language') ?? 'en');
      if (!query) return;
      this.setStatus('Searching script lines...');
      try {
        const result = await apiFetch(
          `/api/script-lines?${new URLSearchParams({
            q: query,
            language: this.scriptSearchLanguage,
            limit: '10',
            offset: '0'
          })}`
        );
        this.scriptSearchResults = await Promise.all(
          result.items.map(async line => prepareScriptSearchResult(line, this.scriptSearchLanguage))
        );
        this.hasScriptSearchResults = Boolean(this.scriptSearchResults.length);
        this.refreshView();
        this.setStatus('');
      } catch {
        this.setStatus('Could not search script lines.');
      }
    },

    addScriptLineToActionForm(lineId) {
      const input = this.root?.querySelector('[name="script_line_ids"]');
      if (!input || !lineId) return;
      const ids = new Set(
        String(input.value || '')
          .split(',')
          .map(value => value.trim())
          .filter(Boolean)
      );
      ids.add(String(lineId));
      input.value = [...ids].join(', ');
    },

    setStatus(message) {
      this.status = message;
      const status = this.root?.querySelector('[data-actions-status]');
      if (status) status.textContent = message;
    },

    prepareSceneNavigation() {
      this.sceneOptions = [...this.sceneOptions]
        .sort((left, right) => Number(left.id) - Number(right.id))
        .map(scene => ({
          ...scene,
          isCurrent: Number(scene.id) === Number(this.sceneId)
        }));
      const currentIndex = this.sceneOptions.findIndex(scene => Number(scene.id) === Number(this.sceneId));
      this.previousSceneId = currentIndex > 0 ? this.sceneOptions[currentIndex - 1].id : null;
      this.nextSceneId = currentIndex >= 0 && currentIndex < this.sceneOptions.length - 1
        ? this.sceneOptions[currentIndex + 1].id
        : null;
    },

    setControlValues() {
      const variableForm = this.root?.querySelector('[data-variable-form]');
      if (variableForm) {
        const selectedVariable = this.variables.find(item => item.id === this.selectedVariableId) ?? null;
        variableForm.elements.variable_id.value = selectedVariable?.id ?? '';
        variableForm.elements.name.value = selectedVariable?.name ?? '';
        variableForm.elements.value_type.value = selectedVariable?.value_type ?? 'bool';
        variableForm.elements.default_value.value = selectedVariable?.defaultValueText ?? 'false';
        variableForm.elements.description.value = selectedVariable?.description ?? '';
      }
      const createForm = this.root?.querySelector('[data-interaction-create-form]');
      if (createForm && this.preselectedObjectId) {
        createForm.elements.trigger_type.value = 'object_click';
        createForm.elements.trigger_object_id.value = String(this.preselectedObjectId);
      }
      const editForm = this.root?.querySelector('[data-interaction-edit-form]');
      if (editForm && this.selectedInteraction) {
        setInteractionFormValues(editForm, this.selectedInteraction);
      }
      this.root?.querySelectorAll('[data-action-step-form]').forEach(form => {
        this.updateActionFormVisibility(form);
      });
    },

    updateActionFormVisibility(form) {
      if (!form) return;
      const selectedType = form.elements.action_type?.value ?? 'play_animation';
      const selectedProperty = form.elements.property?.value ?? 'visible';
      const targetScope = form.elements.target_scope?.value ?? 'object';
      form.querySelector('[data-action-type-help]')?.replaceChildren(
        document.createTextNode(actionTypeHelp(selectedType))
      );
      form.querySelectorAll('[data-visible-for]').forEach(field => {
        const visibleFor = (field.dataset.visibleFor ?? '').split(/\s+/);
        field.hidden = !visibleFor.includes(selectedType);
      });
      const targetObjectField = form.querySelector('[data-form-field="target-object"]');
      if (targetObjectField && selectedType === 'go_to_frame' && targetScope === 'background') {
        targetObjectField.hidden = true;
      }
      form.querySelectorAll('[data-property-visible-for]').forEach(field => {
        const visibleFor = (field.dataset.propertyVisibleFor ?? '').split(/\s+/);
        field.hidden = selectedType !== 'set_object_property' || !visibleFor.includes(selectedProperty);
      });
    },

    refreshView() {
      app.refresh();
      requestAnimationFrame(() => this.setControlValues());
    },

    goToScene(form) {
      const formData = new FormData(form);
      const targetSceneId = Number(formData.get('scene_id'));
      if (!targetSceneId || targetSceneId === this.sceneId) return;
      app.goto(`/actions/${targetSceneId}`);
    }
  };

  await controller.refreshData();
  return controller;
};

async function prepareScriptSearchResult(line, language) {
  try {
    const detail = await apiFetch(`/api/script-lines/${line.line_id}`);
    const audioCandidate = detail.audio_candidates.find(
      candidate => candidate.language === language && candidate.relative_path
    );
    return {
      ...line,
      audioUrl: audioCandidate ? scriptAudioCandidateUrl(audioCandidate.id) : '',
      hasAudio: Boolean(audioCandidate)
    };
  } catch {
    return {...line, audioUrl: '', hasAudio: false};
  }
}

function readRouteOptions() {
  const searchParams = new URLSearchParams(window.location.search);
  return {
    interactionId: numericSearchParam(searchParams, 'interactionId'),
    objectId: numericSearchParam(searchParams, 'objectId')
  };
}

function numericSearchParam(searchParams, name) {
  const value = Number(searchParams.get(name));
  return Number.isFinite(value) && value > 0 ? value : null;
}

function readVariableForm(form) {
  const formData = new FormData(form);
  const valueType = String(formData.get('value_type') ?? 'bool');
  return {
    name: String(formData.get('name') ?? '').trim(),
    value_type: valueType,
    default_value: parseTypedValue(
      valueType,
      String(formData.get('default_value') ?? '')
    ),
    description: String(formData.get('description') ?? '')
  };
}

function readInteractionForm(form, currentInteraction) {
  const formData = new FormData(form);
  return {
    name: String(formData.get('name') ?? '').trim(),
    enabled: formData.get('enabled') === 'on' || !form.elements.enabled,
    trigger: readTrigger(formData),
    action_tree: currentInteraction?.action_tree ?? []
  };
}

function interactionPayload(interaction) {
  return {
    name: interaction.name,
    enabled: interaction.enabled,
    trigger: interaction.trigger,
    action_tree: interaction.action_tree ?? []
  };
}

function readTrigger(formData) {
  const type = String(formData.get('trigger_type') ?? 'scene_enter');
  const trigger = {type};
  if (['object_mouseover', 'object_mouseout', 'object_click', 'object_use', 'object_verb', 'inventory_use'].includes(type)) {
    trigger.object_id = Number(formData.get('trigger_object_id'));
  }
  if (type === 'object_verb') trigger.verb_id = Number(formData.get('trigger_verb_id'));
  if (type === 'inventory_use') trigger.inventory_object_id = Number(formData.get('trigger_inventory_object_id'));
  if (type === 'variable_changed') trigger.variable_id = Number(formData.get('trigger_variable_id'));
  if (type === 'key_press') trigger.key_code = String(formData.get('trigger_key_code') ?? '');
  return trigger;
}

function readActionStepForm(form) {
  const formData = new FormData(form);
  const type = String(formData.get('action_type') ?? '');
  const wait = String(formData.get('wait') ?? 'wait');
  if (type === 'play_animation') {
    const [targetObjectId, animationId] = String(formData.get('animation_ref') ?? ':').split(':');
    return {
      type,
      target_object_id: Number(targetObjectId),
      animation_id: Number(animationId),
      mode: String(formData.get('animation_mode') ?? 'queued'),
      wait
    };
  }
  if (type === 'set_object_property') {
    const property = String(formData.get('property') ?? 'visible');
    return {
      type,
      target_object_id: Number(formData.get('target_object_id')),
      property,
      value: property === 'label'
        ? String(formData.get('value_text') ?? '')
        : String(formData.get('value_bool') ?? 'true') === 'true',
      wait
    };
  }
  if (type === 'go_to_frame') {
    const targetScope = String(formData.get('target_scope') ?? 'object');
    const step = {
      type,
      target_scope: targetScope,
      frame_index: Number(formData.get('frame_index') || 0),
      wait
    };
    if (targetScope === 'object') {
      step.target_object_id = Number(formData.get('target_object_id'));
    }
    return step;
  }
  if (type === 'show_subtitle') {
    return {
      type,
      script_line_ids: readLineIds(formData),
      duration_seconds: Number(formData.get('duration_seconds') || 1),
      wait
    };
  }
  if (type === 'play_audio') {
    return {
      type,
      script_line_ids: readLineIds(formData),
      wait
    };
  }
  if (type === 'set_variable') {
    const valueType = String(formData.get('variable_value_type') ?? 'bool');
    return {
      type,
      variable_id: Number(formData.get('variable_id')),
      value: parseTypedValue(valueType, String(formData.get('variable_value') ?? '')),
      wait
    };
  }
  if (type === 'increment_variable') {
    return {
      type,
      variable_id: Number(formData.get('variable_id')),
      amount: Number(formData.get('variable_delta') || 1),
      wait
    };
  }
  if (type === 'toggle_variable') {
    return {
      type,
      variable_id: Number(formData.get('variable_id')),
      wait
    };
  }
  if (type === 'add_inventory_item' || type === 'remove_inventory_item') {
    return {
      type,
      scene_object_id: Number(formData.get('inventory_scene_object_id')),
      wait
    };
  }
  if (type === 'clear_held_inventory_item') {
    return {
      type,
      wait
    };
  }
  if (type === 'if_variable') {
    const valueType = String(formData.get('variable_value_type') ?? 'bool');
    return {
      type,
      variable_id: Number(formData.get('variable_id')),
      operator: String(formData.get('operator') ?? 'equals'),
      value: parseTypedValue(valueType, String(formData.get('variable_value') ?? '')),
      then_steps: [],
      else_steps: []
    };
  }
  if (type === 'fade_out' || type === 'fade_in') {
    return {
      type,
      duration_seconds: Number(formData.get('duration_seconds') || 1),
      color: String(formData.get('fade_color') ?? '#000000').trim() || '#000000',
      affect_audio: formData.get('affect_audio') === 'on',
      wait
    };
  }
  if (type === 'crossfade_bgm') {
    return {
      type,
      audio_asset_id: Number(formData.get('bgm_audio_asset_id')),
      duration_seconds: Number(formData.get('duration_seconds') || 1),
      wait
    };
  }
  if (type === 'play_sfx') {
    return {
      type,
      audio_asset_id: Number(formData.get('sfx_audio_asset_id')),
      wait
    };
  }
  if (type === 'change_scene') {
    return {
      type,
      scene_id: Number(formData.get('scene_id')),
      wait: 'wait'
    };
  }
  if (type === 'open_overlay_scene' || type === 'change_overlay_scene') {
    return {
      type,
      scene_id: Number(formData.get('overlay_scene_id')),
      wait: 'wait'
    };
  }
  if (type === 'close_overlay_scene') {
    return {
      type,
      wait: 'wait'
    };
  }
  return {
    type: 'delay',
    duration_seconds: Number(formData.get('duration_seconds') || 1),
    wait: 'wait'
  };
}

function setInteractionFormValues(form, interaction) {
  form.elements.name.value = interaction.name;
  form.elements.enabled.checked = Boolean(interaction.enabled);
  form.elements.trigger_type.value = interaction.trigger?.type ?? 'scene_enter';
  if (form.elements.trigger_object_id) {
    form.elements.trigger_object_id.value = interaction.trigger?.object_id ?? '';
  }
  if (form.elements.trigger_verb_id) {
    form.elements.trigger_verb_id.value = interaction.trigger?.verb_id ?? '';
  }
  if (form.elements.trigger_inventory_object_id) {
    form.elements.trigger_inventory_object_id.value = interaction.trigger?.inventory_object_id ?? '';
  }
  if (form.elements.trigger_variable_id) {
    form.elements.trigger_variable_id.value = interaction.trigger?.variable_id ?? '';
  }
  if (form.elements.trigger_key_code) {
    form.elements.trigger_key_code.value = interaction.trigger?.key_code ?? 'Escape';
  }
}

function parseTypedValue(type, rawValue) {
  if (type === 'bool') return rawValue === 'true' || rawValue === 'on';
  if (type === 'number') return Number(rawValue || 0);
  return rawValue;
}

function readLineIds(formData) {
  return String(formData.get('script_line_ids') ?? '')
    .split(',')
    .map(value => Number(value.trim()))
    .filter(Boolean);
}

function insertStep(tree, branchValue, step) {
  const nextTree = structuredClone(tree);
  if (!branchValue || branchValue === 'root') return [...nextTree, step];
  const [parentId, branch] = branchValue.split(':');
  mutateStep(nextTree, parentId, parent => {
    const key = branch === 'else' ? 'else_steps' : 'then_steps';
    parent[key] = [...(parent[key] ?? []), step];
  });
  return nextTree;
}

function removeStepById(tree, stepId) {
  return tree
    .filter(step => step.id !== stepId)
    .map(step => ({
      ...step,
      then_steps: removeStepById(step.then_steps ?? [], stepId),
      else_steps: removeStepById(step.else_steps ?? [], stepId)
    }));
}

function moveStepById(tree, stepId, direction) {
  const nextTree = structuredClone(tree);
  if (moveWithinList(nextTree, stepId, direction)) return nextTree;
  nextTree.forEach(step => {
    step.then_steps = moveStepById(step.then_steps ?? [], stepId, direction);
    step.else_steps = moveStepById(step.else_steps ?? [], stepId, direction);
  });
  return nextTree;
}

function moveWithinList(steps, stepId, direction) {
  const index = steps.findIndex(step => step.id === stepId);
  if (index < 0) return false;
  const targetIndex = direction === 'up' ? index - 1 : index + 1;
  if (targetIndex < 0 || targetIndex >= steps.length) return true;
  const [step] = steps.splice(index, 1);
  steps.splice(targetIndex, 0, step);
  return true;
}

function mutateStep(tree, stepId, fn) {
  for (const step of tree) {
    if (step.id === stepId) {
      fn(step);
      return true;
    }
    if (mutateStep(step.then_steps ?? [], stepId, fn)) return true;
    if (mutateStep(step.else_steps ?? [], stepId, fn)) return true;
  }
  return false;
}

function buildBranchOptions(tree) {
  const options = [{value: 'root', label: 'Root sequence'}];
  flattenActionRows(tree)
    .filter(row => row.type === 'if_variable')
    .forEach(row => {
      options.push({value: `${row.id}:then`, label: `${row.label} / then`});
      options.push({value: `${row.id}:else`, label: `${row.label} / else`});
    });
  return options;
}

function flattenActionRows(tree, depth = 0, branch = '') {
  return tree.flatMap((step, index) => {
    const row = {
      ...step,
      depth,
      index: index + 1,
      branch,
      label: actionLabel(step),
      meta: actionMeta(step),
      indent: `${depth * 18}px`
    };
    return [
      row,
      ...flattenActionRows(step.then_steps ?? [], depth + 1, 'then'),
      ...flattenActionRows(step.else_steps ?? [], depth + 1, 'else')
    ];
  });
}

function countSteps(tree) {
  return tree.reduce(
    (total, step) => total + 1 + countSteps(step.then_steps ?? []) + countSteps(step.else_steps ?? []),
    0
  );
}

function triggerLabel(interaction, scene, variables, verbs, inventoryObjects) {
  const trigger = interaction.trigger ?? {};
  if (['object_mouseover', 'object_mouseout', 'object_click', 'object_use'].includes(trigger.type)) {
    const object = scene?.objects?.find(item => item.id === trigger.object_id);
    return `${trigger.type.replace(/_/g, ' ')} · ${object?.name ?? 'object'}`;
  }
  if (trigger.type === 'object_verb') {
    const object = scene?.objects?.find(item => item.id === trigger.object_id);
    const verb = verbs.find(item => item.id === trigger.verb_id);
    return `on verb · ${object?.name ?? 'object'} · ${verb?.label ?? verb?.key ?? 'verb'}`;
  }
  if (trigger.type === 'inventory_use') {
    const object = scene?.objects?.find(item => item.id === trigger.object_id);
    const inventoryObject = inventoryObjects.find(item => item.id === trigger.inventory_object_id);
    return `inventory use · ${inventoryObject?.name ?? 'item'} -> ${object?.name ?? 'object'}`;
  }
  if (trigger.type === 'variable_changed') {
    const variable = variables.find(item => item.id === trigger.variable_id);
    return `variable changed · ${variable?.name ?? 'variable'}`;
  }
  if (trigger.type === 'key_press') {
    return `key press · ${trigger.key_code ?? 'key'}`;
  }
  return String(trigger.type ?? 'scene_enter').replace(/_/g, ' ');
}

function actionLabel(step) {
  return String(step.type ?? 'action').replace(/_/g, ' ');
}

function actionMeta(step) {
  if (step.type === 'play_audio') return `audio lines ${step.script_line_ids?.join(', ')}`;
  if (step.type === 'show_subtitle') return `subtitle lines ${step.script_line_ids?.join(', ')}`;
  if (step.type === 'go_to_frame') {
    return `${step.target_scope === 'background' ? 'background' : `object ${step.target_object_id}`} · frame ${step.frame_index}`;
  }
  if (step.type === 'set_object_property') return `${step.property} = ${step.value}`;
  if (step.type === 'set_variable') return `variable ${step.variable_id} = ${step.value}`;
  if (step.type === 'increment_variable') return `variable ${step.variable_id} += ${step.amount}`;
  if (step.type === 'toggle_variable') return `toggle variable ${step.variable_id}`;
  if (step.type === 'add_inventory_item') return `add inventory item ${step.scene_object_id}`;
  if (step.type === 'remove_inventory_item') return `remove inventory item ${step.scene_object_id}`;
  if (step.type === 'clear_held_inventory_item') return 'clear held inventory item';
  if (step.type === 'if_variable') return `if variable ${step.variable_id} ${step.operator} ${step.value}`;
  if (step.type === 'fade_out' || step.type === 'fade_in') return `${step.color} · ${step.duration_seconds}s${step.affect_audio ? ' · audio' : ''}`;
  if (step.type === 'crossfade_bgm') return `audio ${step.audio_asset_id} · ${step.duration_seconds}s`;
  if (step.type === 'play_sfx') return `audio ${step.audio_asset_id}`;
  if (step.type === 'change_scene') return `scene ${step.scene_id}`;
  if (step.type === 'open_overlay_scene') return `open overlay ${step.scene_id}`;
  if (step.type === 'close_overlay_scene') return 'close overlay';
  if (step.type === 'change_overlay_scene') return `change overlay ${step.scene_id}`;
  if (step.type === 'delay') return `${step.duration_seconds}s`;
  return step.wait ? `${step.wait}` : '';
}

function actionTypeHelp(type) {
  return {
    play_animation: 'Uses the animation picker. Mode controls queued vs immediate playback.',
    go_to_frame: 'Uses a target scope plus a raw frame index from this scene. Background changes the scene backdrop.',
    set_object_property: 'Uses target object, property, and value fields.',
    show_subtitle: 'Uses script line IDs and duration. Search below and add matching lines.',
    play_audio: 'Uses script line IDs. Search below and add matching lines.',
    set_variable: 'Uses variable, value type, and value.',
    increment_variable: 'Uses a number variable and a positive or negative amount.',
    toggle_variable: 'Uses a bool variable and flips true/false.',
    add_inventory_item: 'Adds a scene object into the global inventory runtime.',
    remove_inventory_item: 'Removes a scene object from the global inventory runtime.',
    clear_held_inventory_item: 'Cancels any item currently attached to the pointer.',
    if_variable: 'Creates a branch target; add child steps into then/else after saving it.',
    fade_out: 'Fades the preview to a color. Optionally ramps active narration audio down too.',
    fade_in: 'Fades the preview back in from a color. Optionally ramps active narration audio up too.',
    crossfade_bgm: 'Crossfades looping background music to a target BGM asset.',
    play_sfx: 'Plays a one-shot sound effect asset.',
    change_scene: 'Uses a target scene and transfers preview flow into that scene.',
    open_overlay_scene: 'Opens an overlay scene on top of the current base scene.',
    close_overlay_scene: 'Closes the current overlay scene and resumes the base scene.',
    change_overlay_scene: 'Switches from the current overlay scene to another overlay scene.',
    delay: 'Uses duration only.'
  }[type] ?? '';
}

export {ActionsCtrl};
