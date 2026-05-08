import {apiFetch} from '../api.js';
import {
  findScene,
  loadScene,
  replaceScene,
  scenes
} from '../state/scenes.js';
import {logoutUser, user} from '../state/user.js';

const SceneCtrl = app => async params => {
  const sceneId = Number(params[0]);
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    organizationId: user.organizationId,
    sceneId,
    scene: findScene(sceneId),
    sceneFound: false,
    sceneMissing: false,
    scenes,
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
      }
    },

    async refreshScene() {
      const latestScene = await loadScene(this.sceneId);
      this.scene = replaceScene(latestScene);
      this.sceneFound = Boolean(this.scene);
      this.sceneMissing = !this.sceneFound;
      app.refresh();
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
      if (!prompt) return;
      if (status) status.textContent = 'Saving...';
      try {
        await apiFetch(`/api/scenes/${this.sceneId}/objects/${objectId}`, {
          method: 'PATCH',
          body: JSON.stringify({prompt})
        });
        if (status) status.textContent = '';
        await this.refreshScene();
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
      } catch {
        button.disabled = false;
        this.setStatus('[data-object-action-status]', 'Could not remove object.');
      } finally {
        button.disabled = false;
      }
    }
  };

  try {
    controller.scene = replaceScene(await loadScene(sceneId));
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

export {SceneCtrl};
