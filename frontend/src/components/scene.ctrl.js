import {apiFetch} from '../api.js';
import {applyStatus} from '../status.js';
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
    extractionJobTracker: null,
    unloadHandlers: [],
    pollTimer: null,

    async postLoad() {
      this.root = document.querySelector('[data-scene-page]');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.root, 'submit', event => this.onSubmit(event));
      this.bind(this.root, 'change', event => this.onChange(event));
      this.bind(this.root, 'dragenter', event => this.onDrag(event));
      this.bind(this.root, 'dragover', event => this.onDrag(event));
      this.bind(this.root, 'dragleave', event => this.onDrag(event));
      this.bind(this.root, 'drop', event => this.onDrop(event));
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

      const objectInventoryButton = event.target.closest('[data-action="generate-object-inventory-image"]');
      if (objectInventoryButton) {
        await this.generateInventoryImageForObject(objectInventoryButton);
        return;
      }

      const removalButton = event.target.closest('[data-action="generate-removal-frames"]');
      if (removalButton) {
        await this.generateRemovalFrames(removalButton);
        return;
      }

      const objectRemovalButton = event.target.closest('[data-action="generate-object-removal-frame"]');
      if (objectRemovalButton) {
        await this.generateRemovalFrameForObject(objectRemovalButton);
        return;
      }

      const previewButton = event.target.closest('[data-action="open-preview"]');
      if (previewButton) {
        openScenePreview(this.sceneId);
        return;
      }

      const uploadImagesButton = event.target.closest('[data-action="browse-scene-images"]');
      if (uploadImagesButton) {
        this.root?.querySelector('[data-scene-image-input]')?.click();
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

    async onChange(event) {
      if (!event.target.matches('[data-scene-image-input]')) return;
      await this.uploadSceneImages(event.target.files);
      event.target.value = '';
    },

    onDrag(event) {
      if (!event.dataTransfer?.types?.includes('Files')) return;
      event.preventDefault();
      if (event.type === 'dragenter' || event.type === 'dragover') {
        this.root?.classList.add('is-dragging-files');
      } else {
        this.root?.classList.remove('is-dragging-files');
      }
    },

    async onDrop(event) {
      if (!event.dataTransfer?.files?.length) return;
      event.preventDefault();
      this.root?.classList.remove('is-dragging-files');
      await this.uploadSceneImages(event.dataTransfer.files);
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
      if (
        latestScene?.presentation_mode === 'character'
        && typeof window !== 'undefined'
        && window.location.pathname.startsWith('/scene/')
      ) {
        try {
          const characters = await apiFetch('/api/characters');
          const character = Array.isArray(characters)
            ? characters.find(item => Number(item.scene_id) === Number(latestScene.id))
            : null;
          if (character) {
            app.goto(`/character/${character.id}`);
            return null;
          }
        } catch {
          // Fall through and render the backing scene if character lookup fails.
        }
      }
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
      applyStatus(status, message);
    },

    objectActionStatusSelector(objectId) {
      return `[data-object-action-status="${objectId}"]`;
    },

    setObjectActionStatus(objectId, message) {
      if (!objectId) return;
      this.setStatus(this.objectActionStatusSelector(objectId), message);
    },

    markObjectGenerationFailure(objectId, kind) {
      const index = (this.scene?.objects ?? []).findIndex(sceneObject => Number(sceneObject.id) === Number(objectId));
      if (index < 0) return;
      const currentObject = this.scene.objects[index];
      this.scene.objects[index] = {
        ...currentObject,
        inventory_image_failed: kind === 'inventory' ? true : Boolean(currentObject.inventory_image_failed),
        pickup_frame_failed: kind === 'pickup' ? true : Boolean(currentObject.pickup_frame_failed)
      };
    },

    markObjectGenerationSuccess(objectId, kind) {
      const index = (this.scene?.objects ?? []).findIndex(sceneObject => Number(sceneObject.id) === Number(objectId));
      if (index < 0) return;
      const currentObject = this.scene.objects[index];
      this.scene.objects[index] = {
        ...currentObject,
        inventory_image_failed: kind === 'inventory' ? false : Boolean(currentObject.inventory_image_failed),
        pickup_frame_failed: kind === 'pickup' ? false : Boolean(currentObject.pickup_frame_failed)
      };
    },

    formatFailedObjectSummary(failedObjects, label) {
      const names = Array.from(failedObjects ?? [])
        .map(item => String(item?.name || '').trim())
        .filter(Boolean);
      if (!names.length) return '';
      const shown = names.slice(0, 3).join(', ');
      const remainder = names.length - Math.min(names.length, 3);
      return ` Failed ${label}: ${shown}${remainder > 0 ? ` and ${remainder} more` : ''}.`;
    },

    async runObjectGenerationBatch({
      button,
      statusSelector,
      idleLabel,
      progressLabel,
      endpointForObject,
      generationKind,
      failedLabel,
      unavailableMessage
    }) {
      const objects = Array.from(this.scene?.objects ?? []).filter(object => object.keyboard_target_enabled);
      if (!objects.length) {
        this.setStatus(statusSelector, 'Scene does not have any keyboard-target objects.');
        return null;
      }

      button.disabled = true;
      button.textContent = 'Generating...';
      let generatedCount = 0;
      let skippedCount = 0;
      const failedObjects = [];
      let currentIndex = 0;

      try {
        for (const object of objects) {
          currentIndex += 1;
          this.setStatus(
            statusSelector,
            `${progressLabel} ${currentIndex}/${objects.length}: ${object.name}...`
          );
          try {
            const result = await apiFetch(endpointForObject(object), {
              method: 'POST'
            });
            if (result.status === 'generated') {
              this.markObjectGenerationSuccess(object.id, generationKind);
              generatedCount += 1;
            } else if (result.status === 'failed') {
              this.markObjectGenerationFailure(object.id, generationKind);
              failedObjects.push({id: object.id, name: object.name, error: failedLabel});
            } else {
              skippedCount += 1;
            }
          } catch (error) {
            let detail = '';
            try {
              detail = error?.response ? (await error.response.clone().json()).detail ?? '' : '';
            } catch {
              detail = '';
            }
            if (error?.response?.status === 503) {
              this.markObjectGenerationFailure(object.id, generationKind);
              window.alert(detail || unavailableMessage);
              failedObjects.push({id: object.id, name: object.name, error: detail || unavailableMessage});
              break;
            }
            this.markObjectGenerationFailure(object.id, generationKind);
            failedObjects.push({id: object.id, name: object.name, error: detail || failedLabel});
          }
        }

        await this.refreshScene();
        return {
          generated_count: generatedCount,
          skipped_count: skippedCount,
          failed_object_ids: failedObjects.map(item => Number(item.id)),
          failed_objects: failedObjects
        };
      } finally {
        button.disabled = false;
        button.textContent = idleLabel;
      }
    },

    async uploadSceneImages(files) {
      const imageFiles = Array.from(files ?? []).filter(file => String(file.type || '').startsWith('image/'));
      if (!imageFiles.length) {
        this.setStatus('[data-scene-image-status]', 'No image files selected.');
        return;
      }
      this.setStatus(
        '[data-scene-image-status]',
        `Uploading ${imageFiles.length} image${imageFiles.length === 1 ? '' : 's'} to this scene...`
      );
      const formData = new FormData();
      imageFiles.forEach(file => formData.append('files', file));
      try {
        const updatedScene = await apiFetch(`/api/scenes/${this.sceneId}/images`, {
          method: 'POST',
          body: formData
        });
        this.scene = replaceScene(updatedScene);
        await loadScenes();
        notifyScenePreview(this.sceneId, 'scene-updated');
        this.setStatus(
          '[data-scene-image-status]',
          `Added ${imageFiles.length} image${imageFiles.length === 1 ? '' : 's'} to this scene.`
        );
        app.refresh();
      } catch {
        this.setStatus('[data-scene-image-status]', 'Could not add images to this scene.');
      }
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
        this.setStatus('[data-mask-extraction-status]', '');
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
      try {
        const result = await this.runObjectGenerationBatch({
          button,
          statusSelector: '[data-inventory-image-status]',
          idleLabel: 'Generate inventory art',
          progressLabel: 'Generating inventory art for keyboard-target objects',
          endpointForObject: object => `/api/scenes/${this.sceneId}/objects/${object.id}/generate-inventory-image`,
          generationKind: 'inventory',
          failedLabel: 'Inventory art generation failed.',
          unavailableMessage: 'Inventory image generator is unavailable. Please contact the administrator to turn Comfy on.'
        });
        if (!result) return;
        const failedCount = Number(result.failed_object_ids?.length ?? 0);
        this.setStatus(
          '[data-inventory-image-status]',
          `Generated ${result.generated_count} inventory image${result.generated_count === 1 ? '' : 's'}${result.skipped_count ? `, skipped ${result.skipped_count}` : ''}${failedCount ? `, failed ${failedCount}` : ''}.${this.formatFailedObjectSummary(result.failed_objects, 'inventory art')}`
        );
      } catch {
        this.setStatus('[data-inventory-image-status]', 'Could not generate inventory art.');
      }
    },

    async generateRemovalFrames(button) {
      try {
        const result = await this.runObjectGenerationBatch({
          button,
          statusSelector: '[data-scene-removal-status]',
          idleLabel: 'Generate pickup frames',
          progressLabel: 'Generating pickup frames for keyboard-target objects',
          endpointForObject: object => `/api/scenes/${this.sceneId}/objects/${object.id}/generate-removal-frame`,
          generationKind: 'pickup',
          failedLabel: 'Pickup frame generation failed.',
          unavailableMessage: 'Inventory image generator is unavailable. Please contact the administrator to turn Comfy on.'
        });
        if (!result) return;
        const failedCount = Number(result.failed_object_ids?.length ?? 0);
        this.setStatus(
          '[data-scene-removal-status]',
          `Generated ${result.generated_count} pickup frame${result.generated_count === 1 ? '' : 's'}${result.skipped_count ? `, skipped ${result.skipped_count}` : ''}${failedCount ? `, failed ${failedCount}` : ''}.${this.formatFailedObjectSummary(result.failed_objects, 'pickup frames')}`
        );
      } catch {
        this.setStatus('[data-scene-removal-status]', 'Could not generate pickup frames.');
      }
    },

    async generateInventoryImageForObject(button) {
      const objectId = Number(button.dataset.objectId);
      if (!objectId) return;
      button.disabled = true;
      this.setObjectActionStatus(objectId, 'Generating inventory art for this object...');
      try {
        const result = await apiFetch(`/api/scenes/${this.sceneId}/objects/${objectId}/generate-inventory-image`, {
          method: 'POST'
        });
        const objectName = this.scene?.objects?.find(item => Number(item.id) === objectId)?.name ?? 'Object';
        let statusMessage = '';
        if (result.status === 'generated') {
          statusMessage = `${objectName} inventory art regenerated.`;
        } else if (result.status === 'failed') {
          statusMessage = `${objectName} inventory art generation failed. Showing mask thumbnail instead.`;
        } else {
          statusMessage = `${objectName} inventory art was skipped because no usable mask render is available.`;
        }
        await this.refreshScene();
        this.setObjectActionStatus(objectId, statusMessage);
        notifyScenePreview(this.sceneId, 'object-updated');
      } catch (error) {
        let detail = '';
        try {
          detail = error?.response ? (await error.response.clone().json()).detail ?? '' : '';
        } catch {
          detail = '';
        }
        if (error?.response?.status === 503) {
          window.alert(detail || 'Inventory image generator is unavailable. Please contact the administrator to turn Comfy on.');
        }
        this.setObjectActionStatus(objectId, detail || 'Could not generate inventory art for this object.');
      } finally {
        button.disabled = false;
      }
    },

    async generateRemovalFrameForObject(button) {
      const objectId = Number(button.dataset.objectId);
      if (!objectId) return;
      button.disabled = true;
      this.setObjectActionStatus(objectId, 'Generating a pickup frame for this object...');
      try {
        const result = await apiFetch(`/api/scenes/${this.sceneId}/objects/${objectId}/generate-removal-frame`, {
          method: 'POST'
        });
        const objectName = this.scene?.objects?.find(item => Number(item.id) === objectId)?.name ?? 'Object';
        let statusMessage = '';
        if (result.status === 'generated') {
          statusMessage = `${objectName} pickup frame generated.`;
        } else if (result.status === 'failed') {
          statusMessage = `${objectName} pickup frame generation failed.`;
        } else {
          statusMessage = `${objectName} pickup frame was skipped because no visible mask was found.`;
        }
        if (result.scene) {
          this.scene = replaceScene(result.scene);
        }
        await this.refreshScene();
        this.setObjectActionStatus(objectId, statusMessage);
        notifyScenePreview(this.sceneId, 'scene-updated');
      } catch (error) {
        let detail = '';
        try {
          detail = error?.response ? (await error.response.clone().json()).detail ?? '' : '';
        } catch {
          detail = '';
        }
        if (error?.response?.status === 503) {
          window.alert(detail || 'Inventory image generator is unavailable. Please contact the administrator to turn Comfy on.');
        }
        this.setObjectActionStatus(objectId, detail || 'Could not generate a pickup frame for this object.');
      } finally {
        button.disabled = false;
      }
    },

    setExtractionJob(job) {
      const now = Date.now();
      this.extractionJobTracker = updateExtractionJobTracker(this.extractionJobTracker, job, now);
      this.extractionJob = job
        ? {
            ...job,
            etaLabel: estimateJobEta(job, this.extractionJobTracker),
            progressLabel: formatJobProgress(job)
          }
        : null;
      this.hasExtractionJob = Boolean(job);
      this.extractionJobRunning = job?.status === 'queued' || job?.status === 'running';
      if (job?.status === 'queued' || job?.status === 'running' || job?.status === 'succeeded') {
        this.setStatus('[data-mask-extraction-status]', '');
      }
      if (job?.status === 'failed') {
        const detail = String(job?.error ?? '').trim();
        this.setStatus('[data-mask-extraction-status]', detail || 'Mask extraction failed.');
      }
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
      const inventoryImagePrompt = String(formData.get('inventory_image_prompt') ?? '').trim();
      if (!name) return;
      applyStatus(status, 'Adding object...');
      try {
        await apiFetch(`/api/scenes/${this.sceneId}/objects`, {
          method: 'POST',
          body: JSON.stringify({
            name,
            description,
            prompt: prompt || null,
            inventory_image_prompt: inventoryImagePrompt || null
          })
        });
        form.reset();
        applyStatus(status, '');
        await this.refreshScene();
        notifyScenePreview(this.sceneId, 'scene-updated');
      } catch {
        applyStatus(status, 'Could not add object.');
      }
    },

    async updateObjectPrompt(form) {
      const objectId = form.dataset.objectId;
      if (!objectId) return;
      const numericObjectId = Number(objectId);
      const status = form.querySelector('[data-object-prompt-status]');
      const formData = new FormData(form);
      const prompt = String(formData.get('prompt') ?? '').trim();
      const inventoryImagePrompt = String(formData.get('inventory_image_prompt') ?? '').trim();
      const previousInventoryImagePrompt = String(form.dataset.inventoryImagePrompt ?? '').trim();
      const visible = formData.get('visible') === 'on';
      const enabled = formData.get('enabled') === 'on';
      const keyboardTargetEnabled = formData.get('keyboard_target_enabled') === 'on';
      if (!prompt) return;
      applyStatus(status, 'Saving...');
      try {
        const updatedObject = await apiFetch(`/api/scenes/${this.sceneId}/objects/${objectId}`, {
          method: 'PATCH',
          body: JSON.stringify({
            prompt,
            inventory_image_prompt: inventoryImagePrompt,
            visible,
            enabled,
            keyboard_target_enabled: keyboardTargetEnabled
          })
        });
        form.elements.prompt.value = updatedObject.prompt ?? prompt;
        form.elements.inventory_image_prompt.value = updatedObject.inventory_image_prompt ?? inventoryImagePrompt;
        form.elements.visible.checked = updatedObject.visible ?? visible;
        form.elements.enabled.checked = updatedObject.enabled ?? enabled;
        form.elements.keyboard_target_enabled.checked = Boolean(updatedObject.keyboard_target_enabled);
        form.dataset.inventoryImagePrompt = updatedObject.inventory_image_prompt ?? inventoryImagePrompt;
        const objectIndex = (this.scene?.objects ?? []).findIndex(sceneObject => Number(sceneObject.id) === numericObjectId);
        if (objectIndex >= 0) {
          const currentObject = this.scene.objects[objectIndex];
          this.scene.objects[objectIndex] = {
            ...currentObject,
            ...updatedObject,
            prompt: updatedObject.prompt ?? prompt,
            inventory_image_prompt: updatedObject.inventory_image_prompt ?? inventoryImagePrompt,
            visible: updatedObject.visible ?? visible,
            enabled: updatedObject.enabled ?? enabled,
            keyboard_target_enabled: Boolean(updatedObject.keyboard_target_enabled)
          };
        }
        const inventoryPromptChanged = previousInventoryImagePrompt !== String(updatedObject.inventory_image_prompt ?? inventoryImagePrompt).trim();
        if (inventoryPromptChanged) {
          applyStatus(status, 'Saved. Regenerating inventory art...');
          const generationResult = await apiFetch(
            `/api/scenes/${this.sceneId}/objects/${objectId}/generate-inventory-image`,
            {method: 'POST'}
          );
          if (generationResult.status === 'generated') {
            applyStatus(status, 'Saved. Inventory art regenerated.');
          } else if (generationResult.status === 'failed') {
            applyStatus(status, 'Saved. Inventory art generation failed. Showing mask thumbnail instead.');
          } else {
            applyStatus(status, 'Saved. Inventory art skipped for this object.');
          }
          await this.refreshScene();
        } else if (status) {
          applyStatus(status, 'Saved.');
        }
        notifyScenePreview(this.sceneId, 'object-updated');
      } catch {
        applyStatus(status, 'Could not save prompt.');
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
        this.setStatus('[data-object-list-status]', 'Could not remove object.');
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
      this.setStatus('[data-object-list-status]', `Moving ${currentObject.name}...`);
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
        this.setStatus('[data-object-list-status]', 'Object order updated.');
      } catch {
        this.setStatus('[data-object-list-status]', 'Could not change object order.');
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
            presentation_mode: String(formData.get('presentation_mode') ?? 'base'),
            background_frame_index: Number(formData.get('background_frame_index') ?? 0)
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
  if (String(type) === 'object_click') return 'primary action';
  return String(type).replace(/_/g, ' ');
}

function formatJobProgress(job) {
  const current = Number(job?.progress_current ?? 0);
  const total = Number(job?.progress_total ?? 0);
  if (!total) return '';
  const percent = Math.max(0, Math.min(100, Math.round((current / total) * 100)));
  return `${current} / ${total} (${percent}%)`;
}

function estimateJobEta(job, tracker) {
  const status = String(job?.status ?? '');
  if (!['queued', 'running'].includes(status)) return '';
  const current = Number(job?.progress_current ?? 0);
  const total = Number(job?.progress_total ?? 0);
  if (!total || current <= 0 || current >= total) return '';
  const secondsPerUnit = estimateSecondsPerUnit(current, tracker);
  if (!Number.isFinite(secondsPerUnit) || secondsPerUnit <= 0) return '';
  const remainingSeconds = Math.round(secondsPerUnit * (total - current));
  if (!Number.isFinite(remainingSeconds) || remainingSeconds <= 0) return '';
  return formatDuration(remainingSeconds);
}

function updateExtractionJobTracker(tracker, job, observedAt) {
  if (!job) return null;
  const jobId = Number(job.id ?? 0);
  const current = Number(job.progress_current ?? 0);
  const nextTracker = tracker && Number(tracker.jobId) === jobId
    ? {
        ...tracker,
        lastObservedAt: observedAt,
        samples: [...tracker.samples]
      }
    : {
        jobId,
        firstSeenAt: observedAt,
        lastObservedAt: observedAt,
        samples: []
      };
  const lastSample = nextTracker.samples[nextTracker.samples.length - 1];
  if (!lastSample || lastSample.current !== current) {
    nextTracker.samples.push({current, observedAt});
    if (nextTracker.samples.length > 12) nextTracker.samples.shift();
  }
  return nextTracker;
}

function estimateSecondsPerUnit(current, tracker) {
  if (!tracker) return Number.NaN;
  const progressSamples = tracker.samples.filter(sample => sample.current > 0);
  if (progressSamples.length >= 2) {
    const windowSamples = progressSamples.slice(-4);
    const firstSample = windowSamples[0];
    const lastSample = windowSamples[windowSamples.length - 1];
    const deltaProgress = lastSample.current - firstSample.current;
    const deltaSeconds = (lastSample.observedAt - firstSample.observedAt) / 1000;
    if (deltaProgress > 0 && deltaSeconds > 0) {
      return deltaSeconds / deltaProgress;
    }
  }
  const firstNonZeroSample = progressSamples[0];
  if (!firstNonZeroSample) return Number.NaN;
  const elapsedSeconds = Math.max(0, (firstNonZeroSample.observedAt - tracker.firstSeenAt) / 1000);
  if (elapsedSeconds <= 0 || current <= 0) return Number.NaN;
  return elapsedSeconds / current;
}

function formatDuration(totalSeconds) {
  const seconds = Math.max(0, Math.round(totalSeconds));
  if (seconds < 60) return `about ${seconds}s remaining`;
  const minutes = Math.floor(seconds / 60);
  const remainderSeconds = seconds % 60;
  if (minutes < 60) {
    return remainderSeconds ? `about ${minutes}m ${remainderSeconds}s remaining` : `about ${minutes}m remaining`;
  }
  const hours = Math.floor(minutes / 60);
  const remainderMinutes = minutes % 60;
  return remainderMinutes ? `about ${hours}h ${remainderMinutes}m remaining` : `about ${hours}h remaining`;
}

export {SceneCtrl};
