import {apiFetch} from '../api.js';
import {
  findScene,
  loadScene,
  loadScenes,
  replaceScene,
  scenes
} from '../state/scenes.js';
import {notifyScenePreview, openScenePreview} from '../preview-sync.js';
import {logoutUser, user} from '../state/user.js';

const SceneCtrl = app => async params => {
  const sceneId = Number(params[0]);
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    organizationId: user.organizationId,
    sceneId,
    scene: findScene(sceneId),
    interactions: [],
    sceneFound: false,
    sceneMissing: false,
    scenes,
    sceneOptions: [],
    mergeSceneOptions: [],
    previousSceneId: null,
    nextSceneId: null,
    extractionJob: null,
    hasExtractionJob: false,
    extractionJobRunning: false,
    unloadHandlers: [],
    pollTimer: null,

    async postLoad() {
      this.root = document.querySelector('[data-scene-page]');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.root, 'submit', event => this.onSubmit(event));
    },

    unload() {
      this.unloadHandlers.forEach(unload => unload());
      this.unloadHandlers = [];
      if (this.pollTimer) window.clearTimeout(this.pollTimer);
      this.pollTimer = null;
    },

    bind(target, type, handler) {
      if (!target) return;
      target.addEventListener(type, handler);
      this.unloadHandlers.push(() => target.removeEventListener(type, handler));
    },

    async onClick(event) {
      const logoutButton = event.target.closest('[data-action="logout"]');
      if (logoutButton) {
        await logoutUser();
        app.goto('/not-authorized');
        return;
      }

      const analyzeButton = event.target.closest('[data-action="analyze-vlm"]');
      if (analyzeButton) {
        await this.analyzeWithVlm(analyzeButton);
        return;
      }

      const extractButton = event.target.closest('[data-action="extract-masks"]');
      if (extractButton) {
        await this.extractMasks(extractButton);
        return;
      }

      const inventoryButton = event.target.closest('[data-action="generate-inventory-images"]');
      if (inventoryButton) {
        await this.generateInventoryImages(inventoryButton);
        return;
      }

      const previewButton = event.target.closest('[data-action="open-preview"]');
      if (previewButton) {
        openScenePreview(this.sceneId);
        return;
      }

      const moveObjectButton = event.target.closest('[data-action="move-object"]');
      if (moveObjectButton) {
        await this.moveObject(moveObjectButton);
        return;
      }

      const deleteObjectButton = event.target.closest('[data-action="delete-object"]');
      if (deleteObjectButton) {
        await this.deleteObject(deleteObjectButton);
      }
    },

    async onSubmit(event) {
      const objectForm = event.target.closest('[data-object-form]');
      if (objectForm) {
        event.preventDefault();
        await this.addObject(objectForm);
        return;
      }

      const objectPromptForm = event.target.closest('[data-object-prompt-form]');
      if (objectPromptForm) {
        event.preventDefault();
        await this.updateObjectPrompt(objectPromptForm);
        return;
      }

      const sceneJumpForm = event.target.closest('[data-scene-jump-form]');
      if (sceneJumpForm) {
        event.preventDefault();
        this.goToScene(sceneJumpForm);
        return;
      }

      const sceneSettingsForm = event.target.closest('[data-scene-settings-form]');
      if (sceneSettingsForm) {
        event.preventDefault();
        await this.saveSceneSettings(sceneSettingsForm);
        return;
      }

      const sceneMergeForm = event.target.closest('[data-scene-merge-form]');
      if (sceneMergeForm) {
        event.preventDefault();
        await this.mergeIntoScene(sceneMergeForm);
      }
    },

    async refreshScene() {
      await this.loadSceneWithActions();
      this.sceneFound = Boolean(this.scene);
      this.sceneMissing = !this.sceneFound;
      app.refresh();
    },

    async loadSceneWithActions() {
      if (!this.scenes.length) await loadScenes();
      const latestScene = replaceScene(await loadScene(this.sceneId));
      this.interactions = await loadSceneInteractions(this.sceneId);
      this.scene = annotateSceneActions(latestScene, this.interactions);
      this.prepareSceneNavigation();
      return this.scene;
    },

    prepareSceneNavigation() {
      this.sceneOptions = [...this.scenes]
        .sort((left, right) => Number(left.id) - Number(right.id))
        .map(scene => ({
          id: scene.id,
          title: scene.title,
          isCurrent: Number(scene.id) === Number(this.sceneId)
        }));
      this.mergeSceneOptions = this.sceneOptions
        .filter(scene => !scene.isCurrent)
        .map(scene => {
          const source = this.scenes.find(item => Number(item.id) === Number(scene.id));
          return {
            id: scene.id,
            title: scene.title,
            presentation_mode: source?.presentation_mode ?? 'base'
          };
        })
        .filter(scene => scene.presentation_mode === 'base');
      const currentIndex = this.sceneOptions.findIndex(scene => Number(scene.id) === Number(this.sceneId));
      this.previousSceneId = currentIndex > 0 ? this.sceneOptions[currentIndex - 1].id : null;
      this.nextSceneId = currentIndex >= 0 && currentIndex < this.sceneOptions.length - 1
        ? this.sceneOptions[currentIndex + 1].id
        : null;
    },

    setStatus(selector, message) {
      const status = document.querySelector(selector);
      if (status) status.textContent = message;
    },

    async analyzeWithVlm(button) {
      button.disabled = true;
      button.textContent = 'Analyzing...';
      this.setStatus('[data-vlm-analysis-status]', 'Asking the local VLM to draft scene details...');
      try {
        const result = await apiFetch(`/api/scenes/${this.sceneId}/analyze-vlm`, {
          method: 'POST'
        });
        const objectLabel = result.created_object_count === 1 ? 'object' : 'objects';
        this.scene = replaceScene(result.scene);
        this.sceneFound = true;
        this.sceneMissing = false;
        notifyScenePreview(this.sceneId, 'scene-updated');
        this.setStatus(
          '[data-vlm-analysis-status]',
          `Added ${result.created_object_count} draft ${objectLabel}.`
        );
        button.disabled = false;
        button.textContent = 'Analyze with VLM';
        app.refresh();
      } catch {
        button.disabled = false;
        button.textContent = 'Analyze with VLM';
        this.setStatus('[data-vlm-analysis-status]', 'Could not analyze this scene.');
      }
    },

    async extractMasks(button) {
      if (this.extractionJobRunning) return;
      button.disabled = true;
      button.textContent = 'Queueing...';
      this.setStatus('[data-mask-extraction-status]', 'Queueing mask extraction...');
      try {
        const job = await apiFetch(`/api/scenes/${this.sceneId}/extract-masks`, {
          method: 'POST'
        });
        this.setExtractionJob(job);
        button.disabled = false;
        button.textContent = 'Extract masks';
        this.pollExtractionJob(job.id);
        app.refresh();
      } catch {
        button.disabled = false;
        button.textContent = 'Extract masks';
        this.setStatus('[data-mask-extraction-status]', 'Could not extract masks.');
      }
    },

    async generateInventoryImages(button) {
      button.disabled = true;
      button.textContent = 'Generating...';
      this.setStatus('[data-inventory-image-status]', 'Generating inventory art for keyboard-target objects...');
      try {
        const result = await apiFetch(`/api/scenes/${this.sceneId}/generate-inventory-images`, {
          method: 'POST'
        });
        this.scene = replaceScene(result.scene);
        this.sceneFound = true;
        this.sceneMissing = false;
        this.setStatus(
          '[data-inventory-image-status]',
          `Generated ${result.generated_count} inventory image${result.generated_count === 1 ? '' : 's'}${result.skipped_count ? `, skipped ${result.skipped_count}` : ''}.`
        );
        button.disabled = false;
        button.textContent = 'Generate inventory art';
        app.refresh();
      } catch (error) {
        button.disabled = false;
        button.textContent = 'Generate inventory art';
        let detail = '';
        try {
          detail = error?.response ? (await error.response.clone().json()).detail ?? '' : '';
        } catch {
          detail = '';
        }
        if (error?.response?.status === 503) {
          window.alert(detail || 'Inventory image generator is unavailable. Please contact the administrator to turn Comfy on.');
        }
        this.setStatus(
          '[data-inventory-image-status]',
          detail || 'Could not generate inventory art.'
        );
      }
    },

    setExtractionJob(job) {
      this.extractionJob = job;
      this.hasExtractionJob = Boolean(job);
      this.extractionJobRunning = job?.status === 'queued' || job?.status === 'running';
    },

    async pollExtractionJob(jobId) {
      if (this.pollTimer) window.clearTimeout(this.pollTimer);
      try {
        const job = await apiFetch(`/api/jobs/${jobId}`);
        this.setExtractionJob(job);
        if (job.status === 'succeeded') {
          await this.refreshScene();
          notifyScenePreview(this.sceneId, 'mask-updated');
          return;
        }
        if (job.status === 'failed') {
          app.refresh();
          return;
        }
        app.refresh();
        this.pollTimer = window.setTimeout(() => this.pollExtractionJob(jobId), 1500);
      } catch {
        this.pollTimer = window.setTimeout(() => this.pollExtractionJob(jobId), 3000);
      }
    },

    async addObject(form) {
      const status = form.querySelector('[data-object-form-status]');
      const formData = new FormData(form);
      const name = String(formData.get('name') ?? '').trim();
      const description = String(formData.get('description') ?? '').trim();
      const prompt = String(formData.get('prompt') ?? '').trim();
      if (!name) return;
      if (status) status.textContent = 'Adding object...';
      try {
        await apiFetch(`/api/scenes/${this.sceneId}/objects`, {
          method: 'POST',
          body: JSON.stringify({name, description, prompt: prompt || null})
        });
        form.reset();
        if (status) status.textContent = '';
        await this.refreshScene();
        notifyScenePreview(this.sceneId, 'scene-updated');
      } catch {
        if (status) status.textContent = 'Could not add object.';
      }
    },

    async updateObjectPrompt(form) {
      const objectId = form.dataset.objectId;
      if (!objectId) return;
      const status = form.querySelector('[data-object-prompt-status]');
      const formData = new FormData(form);
      const prompt = String(formData.get('prompt') ?? '').trim();
      const keyboardTargetEnabled = formData.get('keyboard_target_enabled') === 'on';
      if (!prompt) return;
      if (status) status.textContent = 'Saving...';
      try {
        const updatedObject = await apiFetch(`/api/scenes/${this.sceneId}/objects/${objectId}`, {
          method: 'PATCH',
          body: JSON.stringify({
            prompt,
            keyboard_target_enabled: keyboardTargetEnabled
          })
        });
        form.elements.prompt.value = updatedObject.prompt ?? prompt;
        form.elements.keyboard_target_enabled.checked = Boolean(updatedObject.keyboard_target_enabled);
        if (status) status.textContent = 'Saved.';
        await this.refreshScene();
        notifyScenePreview(this.sceneId, 'object-updated');
      } catch {
        if (status) status.textContent = 'Could not save prompt.';
      }
    },

    async deleteObject(button) {
      const objectId = button.dataset.objectId;
      if (!objectId) return;
      const objectName = button.dataset.objectName ?? 'this object';
      if (!window.confirm(`Remove ${objectName}? This will also remove its masks.`)) return;
      button.disabled = true;
      try {
        await apiFetch(`/api/scenes/${this.sceneId}/objects/${objectId}`, {
          method: 'DELETE'
        });
        await this.refreshScene();
        notifyScenePreview(this.sceneId, 'object-updated');
      } catch {
        button.disabled = false;
        this.setStatus('[data-object-action-status]', 'Could not remove object.');
      } finally {
        button.disabled = false;
      }
    },

    async moveObject(button) {
      const objectId = Number(button.dataset.objectId);
      const direction = button.dataset.direction === 'up' ? -1 : 1;
      if (!objectId || !direction) return;
      const objects = this.scene?.objects ?? [];
      const currentIndex = objects.findIndex(sceneObject => Number(sceneObject.id) === objectId);
      if (currentIndex < 0) return;
      const nextIndex = currentIndex + direction;
      if (nextIndex < 0 || nextIndex >= objects.length) return;
      const currentObject = objects[currentIndex];
      const swapObject = objects[nextIndex];
      button.disabled = true;
      this.setStatus('[data-object-action-status]', `Moving ${currentObject.name}...`);
      try {
        await Promise.all([
          apiFetch(`/api/scenes/${this.sceneId}/objects/${currentObject.id}`, {
            method: 'PATCH',
            body: JSON.stringify({sort_order: swapObject.sort_order})
          }),
          apiFetch(`/api/scenes/${this.sceneId}/objects/${swapObject.id}`, {
            method: 'PATCH',
            body: JSON.stringify({sort_order: currentObject.sort_order})
          })
        ]);
        await this.refreshScene();
        notifyScenePreview(this.sceneId, 'object-updated');
        this.setStatus('[data-object-action-status]', 'Object order updated.');
      } catch {
        this.setStatus('[data-object-action-status]', 'Could not change object order.');
      } finally {
        button.disabled = false;
      }
    },

    async saveSceneSettings(form) {
      const formData = new FormData(form);
      this.setStatus('[data-scene-settings-status]', 'Saving scene settings...');
      try {
        const updatedScene = await apiFetch(`/api/scenes/${this.sceneId}`, {
          method: 'PATCH',
          body: JSON.stringify({
            title: String(formData.get('title') ?? '').trim() || undefined,
            description: String(formData.get('description') ?? ''),
            presentation_mode: String(formData.get('presentation_mode') ?? 'base')
          })
        });
        this.scene = replaceScene(updatedScene);
        this.sceneFound = true;
        this.sceneMissing = false;
        notifyScenePreview(this.sceneId, 'scene-updated');
        this.setStatus('[data-scene-settings-status]', 'Scene settings saved.');
        app.refresh();
      } catch {
        this.setStatus('[data-scene-settings-status]', 'Could not save scene settings.');
      }
    },

    async mergeIntoScene(form) {
      const formData = new FormData(form);
      const targetSceneId = Number(formData.get('target_scene_id'));
      if (!targetSceneId || targetSceneId === this.sceneId) return;
      const targetScene = this.mergeSceneOptions.find(scene => Number(scene.id) === targetSceneId);
      const confirmed = window.confirm(
        `Merge scene ${this.sceneId} into scene ${targetSceneId}${targetScene ? ` (${targetScene.title})` : ''}?\n\nThis will move images, objects, masks, prompts, interactions, and animations into the target scene, then permanently remove the current scene.`
      );
      if (!confirmed) return;
      this.setStatus('[data-scene-merge-status]', 'Merging scene...');
      try {
        await apiFetch(`/api/scenes/${this.sceneId}/merge-into`, {
          method: 'POST',
          body: JSON.stringify({target_scene_id: targetSceneId})
        });
        await loadScenes();
        notifyScenePreview(this.sceneId, 'scene-updated');
        notifyScenePreview(targetSceneId, 'scene-updated');
        app.goto(`/scene/${targetSceneId}`);
      } catch (error) {
        let detail = '';
        try {
          detail = error?.response ? (await error.response.clone().json()).detail ?? '' : '';
        } catch {
          detail = '';
        }
        this.setStatus('[data-scene-merge-status]', detail || 'Could not merge scene.');
      }
    },

    goToScene(form) {
      const formData = new FormData(form);
      const targetSceneId = Number(formData.get('scene_id'));
      if (!targetSceneId || targetSceneId === this.sceneId) return;
      app.goto(`/scene/${targetSceneId}`);
    }
  };

  try {
    await controller.loadSceneWithActions();
    controller.sceneFound = true;
    controller.sceneMissing = false;
    const activeJob = await loadActiveExtractionJob(sceneId);
    if (activeJob) {
      controller.setExtractionJob(activeJob);
      controller.pollExtractionJob(activeJob.id);
    }
  } catch {
    controller.scene = null;
    controller.sceneFound = false;
    controller.sceneMissing = true;
  }
  return controller;
};

async function loadActiveExtractionJob(sceneId) {
  try {
    return await apiFetch(`/api/scenes/${sceneId}/jobs/active`);
  } catch {
    return null;
  }
}

async function loadSceneInteractions(sceneId) {
  try {
    return await apiFetch(`/api/scenes/${sceneId}/interactions`);
  } catch {
    return [];
  }
}

function annotateSceneActions(scene, interactions) {
  const summariesByObjectId = new Map();
  const sceneActionSummaries = [];
  for (const interaction of interactions) {
    const summary = summarizeInteraction(interaction);
    const objectIds = relatedObjectIdsForInteraction(interaction);
    if (!objectIds.size) {
      sceneActionSummaries.push(summary);
      continue;
    }
    for (const objectId of objectIds) {
      if (!summariesByObjectId.has(objectId)) summariesByObjectId.set(objectId, []);
      summariesByObjectId.get(objectId).push(summary);
    }
  }

  const objects = (scene.objects ?? []).map(sceneObject => {
    const actionSummaries = summariesByObjectId.get(sceneObject.id) ?? [];
    return {
      ...sceneObject,
      actionSummaries,
      actionSummaryCount: actionSummaries.length,
      hasActionSummaries: Boolean(actionSummaries.length)
    };
  });
  const objectsWithOrderControls = objects.map((sceneObject, index) => ({
    ...sceneObject,
    hasPreviousObject: index > 0,
    hasNextObject: index < objects.length - 1
  }));

  return {
    ...scene,
    isBasePresentation: (scene.presentation_mode ?? 'base') === 'base',
    isOverlayPresentation: (scene.presentation_mode ?? 'base') === 'overlay',
    objects: objectsWithOrderControls,
    actionCount: interactions.length,
    hasActions: Boolean(interactions.length),
    sceneActionSummaries,
    hasSceneActionSummaries: Boolean(sceneActionSummaries.length)
  };
}

function summarizeInteraction(interaction) {
  const triggerType = labelFromType(interaction.trigger?.type ?? 'scene_enter');
  const actionTypes = [...new Set(flattenActionTypes(interaction.action_tree ?? []))]
    .slice(0, 3)
    .map(labelFromType);
  return {
    id: interaction.id,
    name: interaction.name,
    href: `/actions/${interaction.scene_id}?interactionId=${interaction.id}`,
    triggerType,
    actionTypeSummary: actionTypes.join(', '),
    label: actionTypes.length
      ? `${interaction.name} · ${triggerType} -> ${actionTypes.join(', ')}`
      : `${interaction.name} · ${triggerType}`,
    enabled: interaction.enabled
  };
}

function relatedObjectIdsForInteraction(interaction) {
  const objectIds = new Set();
  if (interaction.trigger?.object_id) objectIds.add(Number(interaction.trigger.object_id));
  collectActionObjectIds(interaction.action_tree ?? [], objectIds);
  return objectIds;
}

function collectActionObjectIds(steps, objectIds) {
  for (const step of steps) {
    if (step.target_object_id) objectIds.add(Number(step.target_object_id));
    collectActionObjectIds(step.then_steps ?? [], objectIds);
    collectActionObjectIds(step.else_steps ?? [], objectIds);
  }
}

function flattenActionTypes(steps) {
  return steps.flatMap(step => [
    step.type,
    ...flattenActionTypes(step.then_steps ?? []),
    ...flattenActionTypes(step.else_steps ?? [])
  ]).filter(Boolean);
}

function labelFromType(type) {
  return String(type).replace(/_/g, ' ');
}

export {SceneCtrl};
