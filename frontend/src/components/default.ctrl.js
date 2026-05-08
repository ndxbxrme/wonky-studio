import {apiFetch} from '../api.js';
import {loadScenes, scenes} from '../state/scenes.js';
import {logoutUser, user} from '../state/user.js';

const DefaultCtrl = app => async () => {
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    isAdmin: user.isAdmin,
    organizationId: user.organizationId,
    uploadBatches: [],
    hasUploadBatches: false,
    scenes,
    hasScenes: false,
    uploadStatus: '',
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-home-page]');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.root, 'submit', event => this.onSubmit(event));
      this.bind(document, 'change', event => this.onChange(event));
      this.bind(window, 'dragenter', event => this.onDrag(event));
      this.bind(window, 'dragover', event => this.onDrag(event));
      this.bind(window, 'dragleave', event => this.onDrag(event));
      this.bind(window, 'drop', event => this.onDrop(event));
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

    async onClick(event) {
      const browseButton = event.target.closest('[data-action="browse-files"]');
      if (browseButton) {
        document.querySelector('[data-file-input]')?.click();
        return;
      }

      const processButton = event.target.closest('[data-action="process-batch"]');
      if (processButton) {
        await this.processBatch(processButton);
        return;
      }

      const logoutButton = event.target.closest('[data-action="logout"]');
      if (logoutButton) {
        await logoutUser();
        app.goto('/not-authorized');
        return;
      }

      const resetButton = event.target.closest('[data-action="reset-database"]');
      if (resetButton) {
        await this.resetDatabase(resetButton);
      }
    },

    async onSubmit(event) {
      const inviteForm = event.target.closest('[data-invite-form]');
      if (inviteForm) {
        event.preventDefault();
        await this.generateInvite(inviteForm);
      }
    },

    async onChange(event) {
      if (!event.target.matches('[data-file-input]')) return;
      await this.uploadFiles(event.target.files);
      event.target.value = '';
    },

    onDrag(event) {
      event.preventDefault();
      const dropZone = document.querySelector('[data-upload-dropzone]');
      if (!dropZone) return;
      if (event.type === 'dragenter' || event.type === 'dragover') {
        dropZone.classList.add('is-dragging');
      } else {
        dropZone.classList.remove('is-dragging');
      }
    },

    async onDrop(event) {
      event.preventDefault();
      document.querySelector('[data-upload-dropzone]')?.classList.remove('is-dragging');
      await this.uploadFiles(event.dataTransfer?.files);
    },

    async uploadFiles(files) {
      const selectedFiles = Array.from(files ?? []);
      if (!selectedFiles.length) return;
      const status = document.querySelector('[data-upload-status]');
      if (status) {
        status.textContent = `Uploading ${selectedFiles.length} file${selectedFiles.length === 1 ? '' : 's'}...`;
      }

      const formData = new FormData();
      selectedFiles.forEach(file => formData.append('files', file));
      try {
        const batch = await apiFetch('/api/uploads/batches', {
          method: 'POST',
          body: formData
        });
        this.uploadBatches = [batch, ...this.uploadBatches];
        this.hasUploadBatches = this.uploadBatches.length > 0;
        if (status) {
          status.textContent = `Queued ${batch.file_count} file${batch.file_count === 1 ? '' : 's'} for processing.`;
        }
        app.refresh();
      } catch {
        if (status) status.textContent = 'Upload failed. Check that the API is running and try again.';
      }
    },

    async processBatch(button) {
      const batchId = button.dataset.batchId;
      if (!batchId) return;
      button.disabled = true;
      button.textContent = 'Processing...';
      try {
        await apiFetch(`/api/uploads/batches/${batchId}/process-scene`, {method: 'POST'});
        await this.reloadScenes();
        button.textContent = 'Process scene';
        button.disabled = false;
        app.refresh();
      } catch {
        button.disabled = false;
        button.textContent = 'Process scene';
      }
    },

    async generateInvite(form) {
      const result = document.querySelector('[data-invite-result]');
      if (result) result.textContent = 'Generating invite...';
      const formData = new FormData(form);
      try {
        const invite = await apiFetch('/api/invites', {
          method: 'POST',
          body: JSON.stringify({
            email: formData.get('email') || null,
            role: formData.get('role') || 'user',
            expires_in_days: Number(formData.get('expires_in_days') || 7)
          })
        });
        if (result) {
          result.replaceChildren();
          const link = document.createElement('a');
          link.href = invite.invite_link;
          link.textContent = invite.invite_link;
          result.append(link);
        }
        form.reset();
      } catch {
        if (result) result.textContent = 'Could not generate an invite link.';
      }
    },

    async resetDatabase(button) {
      const confirmed = window.confirm(
        'Reset workspace data? This clears scenes, uploads, assets, prompts, masks, and invites, but keeps users.'
      );
      if (!confirmed) return;

      const status = document.querySelector('[data-reset-database-status]');
      button.disabled = true;
      if (status) status.textContent = 'Resetting database...';
      try {
        await apiFetch('/api/admin/reset-database', {method: 'POST'});
        this.uploadBatches = [];
        this.hasUploadBatches = false;
        scenes.splice(0, scenes.length);
        this.hasScenes = false;
        if (status) status.textContent = 'Workspace data cleared.';
        button.disabled = false;
        app.refresh();
      } catch {
        if (status) status.textContent = 'Could not reset database.';
        button.disabled = false;
      }
    },

    async reloadScenes() {
      await loadScenes();
      this.hasScenes = scenes.length > 0;
    }
  };

  controller.uploadBatches = await loadUploadBatches();
  controller.hasUploadBatches = controller.uploadBatches.length > 0;
  await controller.reloadScenes();
  return controller;
};

async function loadUploadBatches() {
  try {
    return await apiFetch('/api/uploads/batches');
  } catch {
    return [];
  }
}

export {DefaultCtrl};
