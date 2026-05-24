import {apiFetch, scriptAudioCandidateUrl} from '../api.js';
import {applyStatus} from '../status.js';
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

const SYSTEM_VARIABLE_NAMES = new Set([
  'primary_language',
  'secondary_language',
  'translation_mode',
  'master_volume',
  'narrator_volume',
  'music_volume',
  'sfx_volume'
]);

const ActionsCtrl = app => async params => {
  const sceneId = Number(params[0]);
  const routeOptions = readRouteOptions();
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    sceneId,
    scene: findScene(sceneId),
    variables: [],
    interactions: [],
    visibleInteractions: [],
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
    animationNameOptions: [],
    actionTypes: ACTION_TYPES,
    branchOptions: [],
    actionRows: [],
    scriptLineSummaryById: {},
    scriptSearchResults: [],
    scriptSearchLanguage: 'en',
    interactionTriggerFilter: 'all',
    interactionObjectFilter: 'all',
    interactionFilterOptions: [],
    interactionObjectFilterOptions: [],
    status: '',
    hasInteractions: false,
    hasVisibleInteractions: false,
    hasSelectedInteraction: false,
    variableCount: 0,
    systemVariableCount: 0,
    gameVariableCount: 0,
    hasScriptSearchResults: false,
    editorReady: false,
    editorMissing: false,
    editorLoadError: '',
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
        this.editorLoadError = '';
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
        await this.loadReferencedScriptLineSummaries();
        if (!this.selectedInteractionId && this.interactions.length) {
          this.selectedInteractionId = this.interactions[0].id;
        }
        if (!this.interactions.some(interaction => interaction.id === this.selectedInteractionId)) {
          this.selectedInteractionId = this.interactions[0]?.id ?? null;
        }
        this.prepareState();
      } catch (error) {
        this.editorReady = false;
        this.editorMissing = error?.response?.status === 404;
        this.editorLoadError = this.editorMissing
          ? ''
          : 'Could not load the actions editor. Please refresh and try again.';
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
              name: animation.name,
              label: `${object.name} / ${animation.name}`
            }));
          } catch {
            return [];
          }
        })
      );
      this.animationOptions = animationGroups.flat();
      this.animationNameOptions = [...new Set(this.animationOptions.map(animation => animation.name || ''))]
        .filter(Boolean)
        .sort((left, right) => left.localeCompare(right))
        .map(name => ({value: name, label: name}));
    },

    async loadReferencedScriptLineSummaries() {
      const lineIds = [...collectScriptLineIds(this.interactions)];
      if (!lineIds.length) {
        this.scriptLineSummaryById = {};
        return;
      }
      const entries = await Promise.all(
        lineIds.map(async lineId => {
          try {
            const detail = await apiFetch(`/api/script-lines/${lineId}`);
            return [lineId, summarizeScriptLine(detail)];
          } catch {
            return [lineId, `Line ${lineId}`];
          }
        })
      );
      this.scriptLineSummaryById = Object.fromEntries(entries);
    },

    prepareInteractionFilters() {
      const triggerTypes = [...new Set(
        this.interactions.map(interaction => String(interaction.trigger?.type ?? 'scene_enter'))
      )].sort((left, right) => left.localeCompare(right));
      this.interactionFilterOptions = [
        {value: 'all', label: 'All triggers'},
        ...triggerTypes.map(type => ({
          value: type,
          label: humanTriggerTypeLabel(type)
        }))
      ];
      const objects = this.scene?.objects ?? [];
      this.interactionObjectFilterOptions = [
        {value: 'all', label: 'All objects'},
        {value: 'none', label: 'Scene / global only'},
        ...objects.map(object => ({
          value: String(object.id),
          label: object.name
        }))
      ];
    },

    prepareState() {
      this.variables = this.variables
        .map(variable => ({
          ...variable,
          defaultValueText: String(variable.default_value ?? ''),
          isSystem: SYSTEM_VARIABLE_NAMES.has(variable.name)
        }))
        .sort((left, right) => left.name.localeCompare(right.name));
      this.variableCount = this.variables.length;
      this.systemVariableCount = this.variables.filter(variable => variable.isSystem).length;
      this.gameVariableCount = this.variables.filter(variable => !variable.isSystem).length;
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
      this.prepareInteractionFilters();
      this.visibleInteractions = this.interactions.filter(interaction => interactionMatchesFilters(interaction, {
        triggerType: this.interactionTriggerFilter,
        objectId: this.interactionObjectFilter
      }));
      this.selectedInteraction = this.interactions.find(
        interaction => interaction.id === this.selectedInteractionId
      ) ?? null;
      this.hasInteractions = Boolean(this.interactions.length);
      this.hasVisibleInteractions = Boolean(this.visibleInteractions.length);
      this.hasSelectedInteraction = Boolean(this.selectedInteraction);
      this.branchOptions = buildBranchOptions(this.selectedInteraction?.action_tree ?? [], this);
      this.actionRows = flattenActionRows(this.selectedInteraction?.action_tree ?? [], this);
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
      if (event.target.matches('[data-interaction-filter-trigger], [data-interaction-filter-object]')) {
        this.interactionTriggerFilter = this.root?.querySelector('[data-interaction-filter-trigger]')?.value ?? 'all';
        this.interactionObjectFilter = this.root?.querySelector('[data-interaction-filter-object]')?.value ?? 'all';
        this.prepareState();
        this.refreshView();
        return;
      }
      if (event.target.matches('[name="action_type"], [name="target_scope"], [name="target_object_mode"], [name="scene_object_mode"], [name="trigger_type"], [name="trigger_match_mode"]')) {
        this.updateActionFormVisibility(event.target.closest('[data-action-step-form]'));
        this.updateInteractionFormVisibility(event.target.closest('[data-interaction-create-form], [data-interaction-edit-form]'));
        return;
      }
      if (event.target.matches('[name="property"]')) {
        this.updateActionFormVisibility(event.target.closest('[data-action-step-form]'));
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
      applyStatus(status, message);
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
      const triggerFilter = this.root?.querySelector('[data-interaction-filter-trigger]');
      if (triggerFilter) triggerFilter.value = this.interactionTriggerFilter;
      const objectFilter = this.root?.querySelector('[data-interaction-filter-object]');
      if (objectFilter) objectFilter.value = this.interactionObjectFilter;
      const createForm = this.root?.querySelector('[data-interaction-create-form]');
      if (createForm && this.preselectedObjectId) {
        createForm.elements.trigger_type.value = 'object_click';
        createForm.elements.trigger_object_id.value = String(this.preselectedObjectId);
      }
      this.root?.querySelectorAll('[data-interaction-create-form], [data-interaction-edit-form]').forEach(form => {
        this.updateInteractionFormVisibility(form);
      });
      const editForm = this.root?.querySelector('[data-interaction-edit-form]');
      if (editForm && this.selectedInteraction) {
        setInteractionFormValues(editForm, this.selectedInteraction);
        this.updateInteractionFormVisibility(editForm);
      }
      this.root?.querySelectorAll('[data-action-step-form]').forEach(form => {
        this.updateActionFormVisibility(form);
      });
    },

    updateInteractionFormVisibility(form) {
      if (!form) return;
      const triggerType = form.elements.trigger_type?.value ?? 'scene_enter';
      const triggerMatchMode = normalizeTriggerMatchMode(triggerType, form.elements.trigger_match_mode?.value ?? 'exact');
      if (form.elements.trigger_match_mode) form.elements.trigger_match_mode.value = triggerMatchMode;
      form.querySelectorAll('[data-trigger-visible-for]').forEach(field => {
        const visibleFor = (field.dataset.triggerVisibleFor ?? '').split(/\s+/);
        field.hidden = !visibleFor.includes(triggerType);
      });
      const objectField = form.querySelector('[data-trigger-field="object"]');
      if (objectField) {
        objectField.hidden = !triggerNeedsObject(triggerType, triggerMatchMode);
      }
      const inventoryField = form.querySelector('[data-trigger-field="inventory"]');
      if (inventoryField) {
        inventoryField.hidden = !(triggerType === 'inventory_use' && triggerMatchMode === 'exact');
      }
      const matchModeField = form.querySelector('[data-trigger-field="match-mode"]');
      if (matchModeField) {
        matchModeField.hidden = !triggerSupportsMatchMode(triggerType);
      }
    },

    updateActionFormVisibility(form) {
      if (!form) return;
      const selectedType = form.elements.action_type?.value ?? 'play_animation';
      const selectedProperty = form.elements.property?.value ?? 'visible';
      const targetScope = form.elements.target_scope?.value ?? 'object';
      const targetObjectMode = form.elements.target_object_mode?.value ?? 'static';
      const sceneObjectMode = form.elements.scene_object_mode?.value ?? 'static';
      form.querySelector('[data-action-type-help]')?.replaceChildren(
        document.createTextNode(actionTypeHelp(selectedType))
      );
      form.querySelectorAll('[data-visible-for]').forEach(field => {
        const visibleFor = (field.dataset.visibleFor ?? '').split(/\s+/);
        field.hidden = !visibleFor.includes(selectedType);
      });
      const targetObjectField = form.querySelector('[data-form-field="target-object"]');
      if (targetObjectField) {
        targetObjectField.hidden = !(
          (
            selectedType === 'go_to_frame'
            && targetScope !== 'background'
            && targetObjectMode === 'static'
          )
          || (
            selectedType === 'set_object_property'
            && targetObjectMode === 'static'
          )
        );
      }
      const frameIndexField = form.querySelector('[data-form-field="frame-index"]');
      if (frameIndexField) {
        frameIndexField.hidden = !(
          selectedType === 'go_to_frame'
          && targetScope !== 'pickup_background'
        );
      }
      const animationField = form.querySelector('[data-form-field="animation"]');
      if (animationField) {
        animationField.hidden = !(selectedType === 'play_animation' && targetObjectMode === 'static');
      }
      const animationNameField = form.querySelector('[data-form-field="animation-name"]');
      if (animationNameField) {
        animationNameField.hidden = !(selectedType === 'play_animation' && targetObjectMode !== 'static');
      }
      const targetObjectModeField = form.querySelector('[data-form-field="target-object-mode"]');
      if (targetObjectModeField) {
        targetObjectModeField.hidden = !(
          selectedType === 'play_animation'
          || selectedType === 'set_object_property'
          || (selectedType === 'go_to_frame' && targetScope !== 'background')
        );
      }
      const sceneObjectModeField = form.querySelector('[data-form-field="scene-object-mode"]');
      if (sceneObjectModeField) sceneObjectModeField.hidden = !(selectedType === 'add_inventory_item' || selectedType === 'remove_inventory_item');
      const inventoryObjectField = form.querySelector('[data-form-field="inventory-object"]');
      if (inventoryObjectField) {
        inventoryObjectField.hidden = !(
          (selectedType === 'add_inventory_item' || selectedType === 'remove_inventory_item')
          && sceneObjectMode === 'static'
        );
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
  const matchMode = normalizeTriggerMatchMode(type, String(formData.get('trigger_match_mode') ?? 'exact'));
  const trigger = {type, match_mode: matchMode};
  if (triggerNeedsObject(type, matchMode)) {
    trigger.object_id = Number(formData.get('trigger_object_id'));
  }
  if (type === 'object_verb') trigger.verb_id = Number(formData.get('trigger_verb_id'));
  if (type === 'inventory_use' && matchMode === 'exact') trigger.inventory_object_id = Number(formData.get('trigger_inventory_object_id'));
  if (type === 'variable_changed') trigger.variable_id = Number(formData.get('trigger_variable_id'));
  if (type === 'key_press') trigger.key_code = String(formData.get('trigger_key_code') ?? '');
  return trigger;
}

function readActionStepForm(form) {
  const formData = new FormData(form);
  const type = String(formData.get('action_type') ?? '');
  const wait = String(formData.get('wait') ?? 'wait');
  if (type === 'play_animation') {
    const targetObjectMode = String(formData.get('target_object_mode') ?? 'static');
    const step = {
      type,
      target_object_mode: targetObjectMode,
      mode: String(formData.get('animation_mode') ?? 'queued'),
      wait
    };
    if (targetObjectMode === 'static') {
      const [targetObjectId, animationId] = String(formData.get('animation_ref') ?? ':').split(':');
      step.target_object_id = Number(targetObjectId);
      step.animation_id = Number(animationId);
    } else {
      step.animation_name = String(formData.get('animation_name') ?? '').trim();
    }
    return step;
  }
  if (type === 'set_object_property') {
    const property = String(formData.get('property') ?? 'visible');
    return {
      type,
      target_object_mode: String(formData.get('target_object_mode') ?? 'static'),
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
      target_object_mode: String(formData.get('target_object_mode') ?? 'static'),
      wait
    };
    if (targetScope === 'object') {
      step.frame_index = Number(formData.get('frame_index') || 0);
      step.target_object_id = Number(formData.get('target_object_id'));
    } else if (targetScope === 'background') {
      step.frame_index = Number(formData.get('frame_index') || 0);
    } else if (targetScope === 'pickup_background') {
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
      scene_object_mode: String(formData.get('scene_object_mode') ?? 'static'),
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
  if (form.elements.trigger_match_mode) {
    form.elements.trigger_match_mode.value = interaction.trigger?.match_mode ?? 'exact';
  }
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

function buildBranchOptions(tree, context) {
  const options = [{value: 'root', label: 'Root sequence'}];
  flattenActionRows(tree, context)
    .filter(row => row.type === 'if_variable')
    .forEach(row => {
      options.push({value: `${row.id}:then`, label: `${row.label} / then`});
      options.push({value: `${row.id}:else`, label: `${row.label} / else`});
    });
  return options;
}

function interactionMatchesFilters(interaction, filters) {
  const triggerType = String(interaction.trigger?.type ?? 'scene_enter');
  const objectId = interaction.trigger?.object_id == null ? null : String(interaction.trigger.object_id);
  if ((filters?.triggerType ?? 'all') !== 'all' && triggerType !== filters.triggerType) return false;
  if ((filters?.objectId ?? 'all') === 'all') return true;
  if (filters.objectId === 'none') return objectId == null;
  return objectId === String(filters.objectId);
}

function triggerSupportsMatchMode(triggerType) {
  return ['object_click', 'object_verb', 'inventory_use'].includes(String(triggerType));
}

function normalizeTriggerMatchMode(triggerType, matchMode) {
  if (!triggerSupportsMatchMode(triggerType)) return 'exact';
  if (['exact', 'object_default', 'scene_default'].includes(String(matchMode))) return String(matchMode);
  return 'exact';
}

function triggerNeedsObject(triggerType, matchMode) {
  const normalizedType = String(triggerType);
  const normalizedMatchMode = normalizeTriggerMatchMode(normalizedType, matchMode);
  if (!['object_mouseover', 'object_mouseout', 'object_click', 'object_use', 'object_verb', 'inventory_use'].includes(normalizedType)) {
    return false;
  }
  if (['object_click', 'object_verb', 'inventory_use'].includes(normalizedType) && normalizedMatchMode === 'scene_default') {
    return false;
  }
  return true;
}

function flattenActionRows(tree, context, depth = 0, branch = '') {
  return tree.flatMap((step, index) => {
    const row = {
      ...step,
      depth,
      index: index + 1,
      branch,
      label: actionLabel(step),
      meta: actionMeta(step, context),
      indent: `${depth * 18}px`
    };
    return [
      row,
      ...flattenActionRows(step.then_steps ?? [], context, depth + 1, 'then'),
      ...flattenActionRows(step.else_steps ?? [], context, depth + 1, 'else')
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
  const matchMode = String(trigger.match_mode ?? 'exact');
  if (['object_mouseover', 'object_mouseout', 'object_click', 'object_use'].includes(trigger.type)) {
    const object = scene?.objects?.find(item => item.id === trigger.object_id);
    return formatTriggerLabelPrefix(trigger.type, matchMode, object?.name ?? 'object');
  }
  if (trigger.type === 'object_verb') {
    const object = scene?.objects?.find(item => item.id === trigger.object_id);
    const verb = verbs.find(item => item.id === trigger.verb_id);
    if (matchMode === 'scene_default') {
      return `scene default verb · ${verb?.label ?? verb?.key ?? 'verb'}`;
    }
    if (matchMode === 'object_default') {
      return `default verb · ${object?.name ?? 'object'} · ${verb?.label ?? verb?.key ?? 'verb'}`;
    }
    return `on verb · ${object?.name ?? 'object'} · ${verb?.label ?? verb?.key ?? 'verb'}`;
  }
  if (trigger.type === 'inventory_use') {
    const object = scene?.objects?.find(item => item.id === trigger.object_id);
    const inventoryObject = inventoryObjects.find(item => item.id === trigger.inventory_object_id);
    if (matchMode === 'scene_default') return 'scene default inventory use';
    if (matchMode === 'object_default') return `default inventory use · ${object?.name ?? 'object'}`;
    return `inventory use · ${inventoryObject?.name ?? 'item'} -> ${object?.name ?? 'object'}`;
  }
  if (trigger.type === 'variable_changed') {
    const variable = variables.find(item => item.id === trigger.variable_id);
    return `variable changed · ${variable?.name ?? 'variable'}`;
  }
  if (trigger.type === 'key_press') {
    return `key press · ${trigger.key_code ?? 'key'}`;
  }
  return humanTriggerTypeLabel(trigger.type ?? 'scene_enter');
}

function actionLabel(step) {
  return String(step.type ?? 'action').replace(/_/g, ' ');
}

function actionMeta(step, context) {
  if (step.type === 'play_audio') return `audio ${formatScriptLineIds(step.script_line_ids, context)}`;
  if (step.type === 'show_subtitle') return `subtitle ${formatScriptLineIds(step.script_line_ids, context)}`;
  if (step.type === 'go_to_frame') {
    if (step.target_scope === 'background') {
      return `background · frame ${step.frame_index}`;
    }
    if (step.target_scope === 'pickup_background') {
      return `${describeObjectTarget(step, context)} · pickup frame`;
    }
    return `${describeObjectTarget(step, context)} · frame ${step.frame_index}`;
  }
  if (step.type === 'set_object_property') return `${describeObjectTarget(step, context)} · ${step.property} = ${step.value}`;
  if (step.type === 'set_variable') return `${findVariableName(context, step.variable_id)} = ${step.value}`;
  if (step.type === 'increment_variable') return `${findVariableName(context, step.variable_id)} += ${step.amount}`;
  if (step.type === 'toggle_variable') return `toggle ${findVariableName(context, step.variable_id)}`;
  if (step.type === 'add_inventory_item') return `add ${describeInventoryTarget(step, context)}`;
  if (step.type === 'remove_inventory_item') return `remove ${describeInventoryTarget(step, context)}`;
  if (step.type === 'clear_held_inventory_item') return 'clear held inventory item';
  if (step.type === 'if_variable') return `if ${findVariableName(context, step.variable_id)} ${step.operator} ${step.value}`;
  if (step.type === 'fade_out' || step.type === 'fade_in') return `${step.color} · ${step.duration_seconds}s${step.affect_audio ? ' · audio' : ''}`;
  if (step.type === 'crossfade_bgm') return `${findAudioAssetName(context, step.audio_asset_id)} · ${step.duration_seconds}s`;
  if (step.type === 'play_sfx') return findAudioAssetName(context, step.audio_asset_id);
  if (step.type === 'change_scene') return findSceneName(context, step.scene_id);
  if (step.type === 'open_overlay_scene') return `open overlay ${findSceneName(context, step.scene_id)}`;
  if (step.type === 'close_overlay_scene') return 'close overlay';
  if (step.type === 'change_overlay_scene') return `change overlay ${findSceneName(context, step.scene_id)}`;
  if (step.type === 'play_animation') {
    return step.target_object_mode === 'trigger_object'
      ? `${step.animation_name} on triggered object${step.mode ? ` · ${step.mode}` : ''}`
      : `${findAnimationName(context, step.animation_id)}${step.mode ? ` · ${step.mode}` : ''}`;
  }
  if (step.type === 'delay') return `${step.duration_seconds}s`;
  return step.wait ? `${step.wait}` : '';
}

function actionTypeHelp(type) {
  return {
    play_animation: 'Uses the animation picker. Mode controls queued vs immediate playback.',
    go_to_frame: 'Object/background use a raw frame index. Pickup frame swaps the selected object to its linked removal frame render.',
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

function collectScriptLineIds(interactions) {
  const lineIds = new Set();
  for (const interaction of interactions ?? []) {
    collectScriptLineIdsFromSteps(interaction.action_tree ?? [], lineIds);
  }
  return lineIds;
}

function collectScriptLineIdsFromSteps(steps, lineIds) {
  for (const step of steps ?? []) {
    if (step.type === 'play_audio' || step.type === 'show_subtitle') {
      for (const lineId of step.script_line_ids ?? []) {
        lineIds.add(Number(lineId));
      }
    }
    collectScriptLineIdsFromSteps(step.then_steps ?? [], lineIds);
    collectScriptLineIdsFromSteps(step.else_steps ?? [], lineIds);
  }
}

function summarizeScriptLine(detail) {
  const sourceText = String(detail?.source_text ?? '').trim();
  if (!sourceText) return `Line ${detail?.line_id ?? ''}`.trim();
  return sourceText.length > 48 ? `${sourceText.slice(0, 45)}...` : sourceText;
}

function formatScriptLineIds(scriptLineIds, context) {
  const labels = (scriptLineIds ?? []).map(lineId => (
    context?.scriptLineSummaryById?.[Number(lineId)] ?? `Line ${lineId}`
  ));
  return labels.join(', ');
}

function findVariableName(context, variableId) {
  return context?.variables?.find(variable => Number(variable.id) === Number(variableId))?.name ?? `variable ${variableId}`;
}

function findObjectName(context, objectId) {
  return context?.scene?.objects?.find(object => Number(object.id) === Number(objectId))?.name ?? `object ${objectId}`;
}

function findInventoryObjectName(context, objectId) {
  const object = context?.inventoryObjectOptions?.find(item => Number(item.id) === Number(objectId));
  return object ? `inventory ${object.name}` : `inventory item ${objectId}`;
}

function findAudioAssetName(context, audioAssetId) {
  return context?.audioAssetOptions?.find(asset => Number(asset.id) === Number(audioAssetId))?.name ?? `audio ${audioAssetId}`;
}

function findSceneName(context, sceneId) {
  const scene = context?.sceneOptions?.find(item => Number(item.id) === Number(sceneId));
  return scene ? `scene ${scene.id} · ${scene.title}` : `scene ${sceneId}`;
}

function findAnimationName(context, animationId) {
  return context?.animationOptions?.find(animation => Number(animation.animationId) === Number(animationId))?.label ?? `animation ${animationId}`;
}

function formatTriggerLabelPrefix(triggerType, matchMode, objectName) {
  const base = humanTriggerTypeLabel(triggerType);
  if (matchMode === 'scene_default') return `scene default ${base}`;
  if (matchMode === 'object_default') return `default ${base} · ${objectName}`;
  return `${base} · ${objectName}`;
}

function humanTriggerTypeLabel(triggerType) {
  if (String(triggerType) === 'object_click') return 'primary action';
  return String(triggerType).replace(/_/g, ' ');
}

function describeObjectTarget(step, context) {
  if (step.target_object_mode === 'trigger_object') return 'triggered object';
  if (step.target_object_mode === 'trigger_inventory_object') return 'used inventory item';
  return findObjectName(context, step.target_object_id);
}

function describeInventoryTarget(step, context) {
  if (step.scene_object_mode === 'trigger_object') return 'triggered object';
  if (step.scene_object_mode === 'trigger_inventory_object') return 'used inventory item';
  return findInventoryObjectName(context, step.scene_object_id);
}

export {ActionsCtrl};
