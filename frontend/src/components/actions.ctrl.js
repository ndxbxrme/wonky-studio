import {apiFetch, scriptAudioCandidateUrl} from '../api.js';
import {findScene, loadScene, replaceScene} from '../state/scenes.js';
import {notifyScenePreview, openScenePreview} from '../preview-sync.js';
import {user} from '../state/user.js';

const ACTION_TYPES = [
  {value: 'play_animation', label: 'Play animation'},
  {value: 'set_object_property', label: 'Set object property'},
  {value: 'show_subtitle', label: 'Show subtitle'},
  {value: 'play_audio', label: 'Play audio'},
  {value: 'set_variable', label: 'Set variable'},
  {value: 'if_variable', label: 'If variable'},
  {value: 'delay', label: 'Delay'}
];

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
    selectedInteractionId: routeOptions.interactionId,
    preselectedObjectId: routeOptions.objectId,
    selectedInteraction: null,
    objectOptions: [],
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
        this.variables = await apiFetch('/api/variables');
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
        defaultValueText: String(variable.default_value ?? '')
      }));
      this.hasVariables = Boolean(this.variables.length);
      this.interactions = this.interactions.map(interaction => ({
        ...interaction,
        triggerLabel: triggerLabel(interaction, this.scene, this.variables),
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
      }
    },

    async onChange(event) {
      if (event.target.matches('[name="action_type"]')) {
        this.updateActionFormVisibility(event.target.closest('[data-action-step-form]'));
        return;
      }
      if (event.target.matches('[name="property"]')) {
        this.updateActionFormVisibility(event.target.closest('[data-action-step-form]'));
      }
    },

    async createVariable(form) {
      const formData = new FormData(form);
      const payload = {
        name: String(formData.get('name') ?? '').trim(),
        value_type: String(formData.get('value_type') ?? 'bool'),
        default_value: parseTypedValue(
          String(formData.get('value_type') ?? 'bool'),
          String(formData.get('default_value') ?? '')
        ),
        description: String(formData.get('description') ?? '')
      };
      if (!payload.name) return;
      this.setStatus('Creating variable...');
      try {
        await apiFetch('/api/variables', {method: 'POST', body: JSON.stringify(payload)});
        form.reset();
        await this.refreshData();
        this.refreshView();
        notifyScenePreview(this.sceneId, 'variable-updated');
        this.setStatus('Variable created.');
      } catch {
        this.setStatus('Could not create variable.');
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

    setControlValues() {
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
      form.querySelector('[data-action-type-help]')?.replaceChildren(
        document.createTextNode(actionTypeHelp(selectedType))
      );
      form.querySelectorAll('[data-visible-for]').forEach(field => {
        const visibleFor = (field.dataset.visibleFor ?? '').split(/\s+/);
        field.hidden = !visibleFor.includes(selectedType);
      });
      form.querySelectorAll('[data-property-visible-for]').forEach(field => {
        const visibleFor = (field.dataset.propertyVisibleFor ?? '').split(/\s+/);
        field.hidden = selectedType !== 'set_object_property' || !visibleFor.includes(selectedProperty);
      });
    },

    refreshView() {
      app.refresh();
      requestAnimationFrame(() => this.setControlValues());
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
  const trigger = {type};
  if (type.startsWith('object_')) trigger.object_id = Number(formData.get('trigger_object_id'));
  if (type === 'variable_changed') trigger.variable_id = Number(formData.get('trigger_variable_id'));
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
  if (form.elements.trigger_variable_id) {
    form.elements.trigger_variable_id.value = interaction.trigger?.variable_id ?? '';
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

function triggerLabel(interaction, scene, variables) {
  const trigger = interaction.trigger ?? {};
  if (trigger.type?.startsWith('object_')) {
    const object = scene?.objects?.find(item => item.id === trigger.object_id);
    return `${trigger.type.replace(/_/g, ' ')} · ${object?.name ?? 'object'}`;
  }
  if (trigger.type === 'variable_changed') {
    const variable = variables.find(item => item.id === trigger.variable_id);
    return `variable changed · ${variable?.name ?? 'variable'}`;
  }
  return String(trigger.type ?? 'scene_enter').replace(/_/g, ' ');
}

function actionLabel(step) {
  return String(step.type ?? 'action').replace(/_/g, ' ');
}

function actionMeta(step) {
  if (step.type === 'play_audio') return `audio lines ${step.script_line_ids?.join(', ')}`;
  if (step.type === 'show_subtitle') return `subtitle lines ${step.script_line_ids?.join(', ')}`;
  if (step.type === 'set_object_property') return `${step.property} = ${step.value}`;
  if (step.type === 'set_variable') return `variable ${step.variable_id} = ${step.value}`;
  if (step.type === 'if_variable') return `if variable ${step.variable_id} ${step.operator} ${step.value}`;
  if (step.type === 'delay') return `${step.duration_seconds}s`;
  return step.wait ? `${step.wait}` : '';
}

function actionTypeHelp(type) {
  return {
    play_animation: 'Uses the animation picker. Mode controls queued vs immediate playback.',
    set_object_property: 'Uses target object, property, and value fields.',
    show_subtitle: 'Uses script line IDs and duration. Search below and add matching lines.',
    play_audio: 'Uses script line IDs. Search below and add matching lines.',
    set_variable: 'Uses variable, value type, and value.',
    if_variable: 'Creates a branch target; add child steps into then/else after saving it.',
    delay: 'Uses duration only.'
  }[type] ?? '';
}

export {ActionsCtrl};
