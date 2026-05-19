import {apiFetch} from '../api.js';
import {applyStatus} from '../status.js';
import {hydrateSceneDetails, loadSceneSummaries, scenes} from '../state/scenes.js';
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
    workspaceSummary: null,
    hasWorkspaceSummary: false,
    hydratingScenes: false,
    sceneHydrationToken: 0,
    uploadStatus: '',
    sceneCreateStatus: '',
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
      this.syncStaticStatuses();
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

      const browseImportButton = event.target.closest('[data-action="browse-import-project"]');
      if (browseImportButton) {
        document.querySelector('[data-import-project-input]')?.click();
        return;
      }

      const logoutButton = event.target.closest('[data-action="logout"]');
      if (logoutButton) {
        await logoutUser();
        app.goto('/not-authorized');
        return;
      }

      const exportProjectButton = event.target.closest('[data-action="export-project"]');
      if (exportProjectButton) {
        this.exportProject(exportProjectButton);
        return;
      }

      const exportDatabaseBackupButton = event.target.closest('[data-action="export-database-backup"]');
      if (exportDatabaseBackupButton) {
        await this.exportDatabaseBackup(exportDatabaseBackupButton);
        return;
      }

      const importDatabaseBackupButton = event.target.closest('[data-action="import-database-backup"]');
      if (importDatabaseBackupButton) {
        await this.importDatabaseBackup(importDatabaseBackupButton);
        return;
      }

      const resetButton = event.target.closest('[data-action="reset-database"]');
      if (resetButton) {
        await this.resetDatabase(resetButton);
        return;
      }

      const moveSceneButton = event.target.closest('[data-action="move-scene-up"], [data-action="move-scene-down"]');
      if (moveSceneButton) {
        await this.moveScene(moveSceneButton);
        return;
      }

      const removeSceneButton = event.target.closest('[data-action="remove-scene"]');
      if (removeSceneButton) {
        await this.removeScene(removeSceneButton);
      }
    },

    async onSubmit(event) {
      const sceneCreateForm = event.target.closest('[data-scene-create-form]');
      if (sceneCreateForm) {
        event.preventDefault();
        await this.createScene(sceneCreateForm);
        return;
      }
      const inviteForm = event.target.closest('[data-invite-form]');
      if (inviteForm) {
        event.preventDefault();
        await this.generateInvite(inviteForm);
      }
    },

    async onChange(event) {
      if (event.target.matches('[data-file-input]')) {
        await this.uploadFiles(event.target.files);
        event.target.value = '';
        return;
      }
      if (event.target.matches('[data-import-project-input]')) {
        await this.importProject(event.target.files?.[0] ?? null);
        event.target.value = '';
      }
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
      const sceneCard = event.target.closest('[data-scene-card]');
      if (sceneCard) {
        await this.uploadFilesToScene(sceneCard.dataset.sceneId, event.dataTransfer?.files);
        return;
      }
      await this.uploadFiles(event.dataTransfer?.files);
    },

    async uploadFiles(files) {
      const selectedFiles = Array.from(files ?? []);
      if (!selectedFiles.length) return;
      const hasImageFiles = selectedFiles.some(file => String(file.type || '').startsWith('image/'));
      const status = document.querySelector('[data-upload-status]');
      if (status) {
        applyStatus(status, `Uploading ${selectedFiles.length} file${selectedFiles.length === 1 ? '' : 's'}...`);
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
          if (hasImageFiles) {
            applyStatus(status, `Uploaded ${batch.file_count} file${batch.file_count === 1 ? '' : 's'}. Assign them from Images or by dropping them onto a scene.`);
          } else {
            applyStatus(status, `Queued ${batch.file_count} file${batch.file_count === 1 ? '' : 's'}.`);
          }
        }
        await this.reloadWorkspaceSummary();
        app.refresh();
      } catch {
        applyStatus(status, 'Upload failed. Check that the API is running and try again.');
      }
    },

    async uploadFilesToScene(sceneId, files) {
      const selectedFiles = Array.from(files ?? []).filter(file => String(file.type || '').startsWith('image/'));
      if (!sceneId || !selectedFiles.length) return;
      const status = document.querySelector('[data-upload-status]');
      applyStatus(status, `Uploading ${selectedFiles.length} image${selectedFiles.length === 1 ? '' : 's'} to scene ${sceneId}...`);
      const formData = new FormData();
      selectedFiles.forEach(file => formData.append('files', file));
      try {
        await apiFetch(`/api/scenes/${sceneId}/images`, {
          method: 'POST',
          body: formData
        });
        await this.reloadScenes();
        await this.reloadWorkspaceSummary();
        applyStatus(status, `Added ${selectedFiles.length} image${selectedFiles.length === 1 ? '' : 's'} to scene ${sceneId}.`);
        app.refresh();
      } catch {
        applyStatus(status, `Could not add images to scene ${sceneId}.`);
      }
    },

    async createScene(form) {
      const formData = new FormData(form);
      const title = String(formData.get('title') ?? '').trim();
      if (!title) {
        this.sceneCreateStatus = 'Scene title is required.';
        app.refresh();
        requestAnimationFrame(() => this.syncStaticStatuses());
        return;
      }
      this.sceneCreateStatus = 'Creating scene...';
      app.refresh();
      requestAnimationFrame(() => this.syncStaticStatuses());
      try {
        const scene = await apiFetch('/api/scenes', {
          method: 'POST',
          body: JSON.stringify({
            title,
            description: String(formData.get('description') ?? '').trim(),
            presentation_mode: 'base'
          })
        });
        form.reset();
        this.sceneCreateStatus = `Scene ${scene.id} created.`;
        await this.reloadScenes();
        await this.reloadWorkspaceSummary();
        app.refresh();
        requestAnimationFrame(() => this.syncStaticStatuses());
      } catch {
        this.sceneCreateStatus = 'Could not create scene.';
        app.refresh();
        requestAnimationFrame(() => this.syncStaticStatuses());
      }
    },

    syncStaticStatuses() {
      applyStatus(document.querySelector('[data-upload-status]'), this.uploadStatus);
      const sceneCreateStatus = document.querySelector('[data-scene-create-form] .form-status');
      applyStatus(sceneCreateStatus, this.sceneCreateStatus);
    },

    exportProject(button) {
      const status = document.querySelector('[data-project-archive-status]');
      button.disabled = true;
      applyStatus(status, 'Preparing project export...');
      window.location.assign('/api/admin/export-project');
      window.setTimeout(() => {
        button.disabled = false;
        applyStatus(status, 'Project export started.');
      }, 800);
    },

    async exportDatabaseBackup(button) {
      const status = document.querySelector('[data-database-backup-status]');
      button.disabled = true;
      applyStatus(status, 'Writing backup.json...');
      try {
        const result = await apiFetch('/api/admin/export-database-backup', {method: 'POST'});
        const sceneCount = Number(result.archive?.table_counts?.scenes ?? 0);
        applyStatus(status, `Wrote ${result.backup_path}. Included ${sceneCount} scene${sceneCount === 1 ? '' : 's'}.`);
      } catch (error) {
        applyStatus(status, error?.message || 'Could not write backup.json.');
      } finally {
        button.disabled = false;
      }
    },

    async generateInvite(form) {
      const result = document.querySelector('[data-invite-result]');
      applyStatus(result, 'Generating invite...');
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
          result.hidden = false;
          result.dataset.tone = 'success';
        }
        form.reset();
      } catch {
        applyStatus(result, 'Could not generate an invite link.');
      }
    },

    async resetDatabase(button) {
      const confirmed = window.confirm(
        'Reset workspace data? This clears scenes, uploads, assets, prompts, masks, and invites, but keeps users.'
      );
      if (!confirmed) return;

      const status = document.querySelector('[data-reset-database-status]');
      button.disabled = true;
      applyStatus(status, 'Resetting database...');
      try {
        await apiFetch('/api/admin/reset-database', {method: 'POST'});
        this.uploadBatches = [];
        this.hasUploadBatches = false;
        scenes.splice(0, scenes.length);
        this.hasScenes = false;
        this.workspaceSummary = null;
        this.hasWorkspaceSummary = false;
        applyStatus(status, 'Workspace data cleared.');
        button.disabled = false;
        app.refresh();
      } catch {
        applyStatus(status, 'Could not reset database.');
        button.disabled = false;
      }
    },

    async importProject(file) {
      if (!(file instanceof File)) return;
      const confirmed = window.confirm(
        'Import a project zip into this workspace? Import only works on an empty workspace and will fail if content already exists.'
      );
      if (!confirmed) return;
      const status = document.querySelector('[data-project-archive-status]');
      applyStatus(status, `Importing ${file.name}...`);
      const formData = new FormData();
      formData.append('archive', file);
      try {
        const result = await apiFetch('/api/admin/import-project', {
          method: 'POST',
          body: formData
        });
        this.uploadBatches = [];
        this.hasUploadBatches = false;
        await this.reloadScenes();
        await this.reloadWorkspaceSummary();
        app.refresh();
        const sceneCount = Number(result.archive?.table_counts?.scenes ?? 0);
        const fileCount = Number(result.archive?.restored_file_count ?? 0);
        applyStatus(status, `Imported project. Restored ${sceneCount} scene${sceneCount === 1 ? '' : 's'} and ${fileCount} file${fileCount === 1 ? '' : 's'}.`);
      } catch (error) {
        applyStatus(status, error?.message || 'Could not import project.');
      }
    },

    async importDatabaseBackup(button) {
      const confirmed = window.confirm(
        'Import /mnt/d/wonky-studio/backup.json into this workspace? Import only works on an empty workspace.'
      );
      if (!confirmed) return;
      const status = document.querySelector('[data-database-backup-status]');
      button.disabled = true;
      applyStatus(status, 'Importing backup.json...');
      try {
        const result = await apiFetch('/api/admin/import-database-backup', {method: 'POST'});
        this.uploadBatches = [];
        this.hasUploadBatches = false;
        await this.reloadScenes();
        await this.reloadWorkspaceSummary();
        app.refresh();
        const sceneCount = Number(result.archive?.table_counts?.scenes ?? 0);
        applyStatus(status, `Imported backup.json. Restored ${sceneCount} scene${sceneCount === 1 ? '' : 's'}.`);
      } catch (error) {
        applyStatus(status, error?.message || 'Could not import backup.json.');
      } finally {
        button.disabled = false;
      }
    },

    async reloadScenes() {
      await loadSceneSummaries();
      this.applySceneList();
      this.hydrateScenesInBackground();
    },

    applySceneList() {
      this.hasScenes = scenes.length > 0;
      this.scenes = scenes.map((scene, index) => ({
        ...scene,
        canMoveUp: index > 0,
        canMoveDown: index < scenes.length - 1,
        disableMoveUp: index === 0,
        disableMoveDown: index === scenes.length - 1
      }));
    },

    async hydrateScenesInBackground() {
      const token = Date.now();
      this.sceneHydrationToken = token;
      this.hydratingScenes = true;
      app.refresh();
      await hydrateSceneDetails();
      if (this.sceneHydrationToken !== token) return;
      this.applySceneList();
      this.hydratingScenes = false;
      app.refresh();
    },

    async moveScene(button) {
      const sceneId = Number(button.dataset.sceneId || 0);
      const direction = button.matches('[data-action="move-scene-up"]') ? 'up' : 'down';
      if (!sceneId) return;
      button.disabled = true;
      try {
        await apiFetch(`/api/scenes/${sceneId}/move`, {
          method: 'POST',
          body: JSON.stringify({direction})
        });
        await this.reloadScenes();
        app.refresh();
      } finally {
        button.disabled = false;
      }
    },

    async removeScene(button) {
      const sceneId = Number(button.dataset.sceneId || 0);
      const sceneTitle = String(button.dataset.sceneTitle || `Scene ${sceneId}`).trim();
      if (!sceneId) return;
      const confirmed = window.confirm(
        `Remove scene "${sceneTitle}"?\n\nThis will delete the scene record, its uploaded images, generated images, masks, animations, and related data. Any scene-change actions targeting it will be unhooked automatically.`
      );
      if (!confirmed) return;
      const typed = window.prompt(
        `Type the scene title exactly to confirm removal:\n\n${sceneTitle}`,
        ''
      );
      if (typed !== sceneTitle) {
        this.sceneCreateStatus = 'Scene removal cancelled.';
        app.refresh();
        requestAnimationFrame(() => this.syncStaticStatuses());
        return;
      }
      button.disabled = true;
      this.sceneCreateStatus = `Removing scene "${sceneTitle}"...`;
      app.refresh();
      requestAnimationFrame(() => this.syncStaticStatuses());
      try {
        const result = await apiFetch(`/api/scenes/${sceneId}`, {method: 'DELETE'});
        await this.reloadScenes();
        await this.reloadWorkspaceSummary();
        const references = Number(result.removed_scene_reference_count ?? 0);
        const updatedInteractions = Number(result.updated_interaction_count ?? 0);
        const images = Number(result.deleted_image_count ?? 0);
        const objects = Number(result.deleted_object_count ?? 0);
        const extraNotes = [
          references > 0
            ? `Unhooked ${references} scene-change step${references === 1 ? '' : 's'} in ${updatedInteractions} interaction${updatedInteractions === 1 ? '' : 's'}.`
            : 'No scene-change actions needed unhooking.',
          Number(result.removed_overlay_binding_count ?? 0) > 0
            ? `Removed ${Number(result.removed_overlay_binding_count)} overlay binding${Number(result.removed_overlay_binding_count) === 1 ? '' : 's'}.`
            : '',
          result.cleared_start_scene ? 'Cleared this scene as the global start scene.' : ''
        ].filter(Boolean).join(' ');
        this.sceneCreateStatus = `Removed "${sceneTitle}" with ${images} image${images === 1 ? '' : 's'} and ${objects} object${objects === 1 ? '' : 's'} cleared. ${extraNotes}`.trim();
        app.refresh();
        requestAnimationFrame(() => this.syncStaticStatuses());
      } catch (error) {
        this.sceneCreateStatus = error?.message || `Could not remove "${sceneTitle}".`;
        app.refresh();
        requestAnimationFrame(() => this.syncStaticStatuses());
      } finally {
        button.disabled = false;
      }
    },

    async reloadWorkspaceSummary() {
      try {
        this.workspaceSummary = await apiFetch('/api/workspace-summary');
        this.hasWorkspaceSummary = Boolean(this.workspaceSummary);
      } catch {
        this.workspaceSummary = null;
        this.hasWorkspaceSummary = false;
      }
    }
  };

  controller.uploadBatches = await loadUploadBatches();
  controller.hasUploadBatches = controller.uploadBatches.length > 0;
  await controller.reloadScenes();
  await controller.reloadWorkspaceSummary();
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
