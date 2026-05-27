import {apiFetch} from '../api.js';
import {applyStatus} from '../status.js';
import {SceneCtrl} from './scene.ctrl.js';

const CharacterEditorCtrl = app => async params => {
  const characterId = Number(params[0]);
  const character = await apiFetch(`/api/characters/${characterId}`);
  const baseController = await SceneCtrl(app)([String(character.scene_id)]);

  const controller = {
    ...baseController,
    characterId,
    character,
    poseFolders: [],

    async loadCharacterData() {
      const [nextCharacter, poseFolders] = await Promise.all([
        apiFetch(`/api/characters/${this.characterId}`),
        apiFetch('/api/character-pose-folders')
      ]);
      this.character = nextCharacter;
      this.poseFolders = poseFolders;
      this.sceneId = Number(nextCharacter.scene_id);
      return nextCharacter;
    },

    async loadSceneWithActions() {
      await this.loadCharacterData();
      const scene = await baseController.loadSceneWithActions.call(this);
      this.scene = {
        ...scene,
        objects: (scene?.objects ?? []).map(object => ({
          ...object,
          isMouthTarget: Number(object.id) === Number(this.character?.mouth_scene_object_id)
        }))
      };
      return scene;
    },

    async postLoad() {
      await baseController.postLoad.call(this);
      this.root = document.querySelector('[data-character-editor-page]');
      this.syncCharacterControls();
    },

    refreshView() {
      app.refresh();
      this.syncCharacterControls();
    },

    syncCharacterControls() {
      const form = this.root?.querySelector('[data-character-settings-form]');
      if (!form) return;
      form.elements.character_name.value = this.character?.name ?? '';
      form.elements.character_description.value = this.character?.description ?? '';
      form.elements.default_x.value = this.character?.default_x ?? 960;
      form.elements.default_y.value = this.character?.default_y ?? 540;
      form.elements.default_scale.value = this.character?.default_scale ?? 1;
      const mouthSelect = form.elements.mouth_scene_object_id;
      if (mouthSelect) {
        mouthSelect.value = this.character?.mouth_scene_object_id ?? '';
      }
    },

    async onClick(event) {
      const analyzeButton = event.target.closest('[data-action="analyze-vlm"]');
      if (analyzeButton) {
        await this.analyzeWithVlm(analyzeButton);
        return;
      }
      const generateVisemesButton = event.target.closest('[data-action="generate-character-visemes"]');
      if (generateVisemesButton) {
        await this.generateVisemes(generateVisemesButton);
        return;
      }
      const generatePosesButton = event.target.closest('[data-action="generate-character-poses"]');
      if (generatePosesButton) {
        await this.generatePoses(generatePosesButton);
        return;
      }
      await baseController.onClick.call(this, event);
    },

    async onChange(event) {
      const characterForm = event.target.closest('[data-character-settings-form]');
      if (characterForm) {
        await this.autosaveCharacterSettingsForm(characterForm);
        return;
      }
      await baseController.onChange.call(this, event);
    },

    async analyzeWithVlm(button) {
      button.disabled = true;
      button.textContent = 'Analyzing...';
      this.setStatus('[data-vlm-analysis-status]', 'Asking the local VLM to draft character objects...');
      try {
        const result = await apiFetch(`/api/scenes/${this.sceneId}/analyze-vlm`, {
          method: 'POST'
        });
        const objectLabel = result.created_object_count === 1 ? 'object' : 'objects';
        await this.refreshScene();
        this.setStatus(
          '[data-vlm-analysis-status]',
          `Added ${result.created_object_count} draft ${objectLabel}.`
        );
      } catch {
        this.setStatus('[data-vlm-analysis-status]', 'Could not analyze this character.');
      } finally {
        button.disabled = false;
        button.textContent = 'Analyze with VLM';
      }
    },

    async onSubmit(event) {
      const characterForm = event.target.closest('[data-character-settings-form]');
      if (characterForm) {
        event.preventDefault();
        await this.autosaveCharacterSettingsForm(characterForm);
        return;
      }
      await baseController.onSubmit.call(this, event);
    },

    currentCharacterSettingsPayload() {
      return {
        name: String(this.character?.name ?? ''),
        description: String(this.character?.description ?? ''),
        default_x: Number(this.character?.default_x ?? 960),
        default_y: Number(this.character?.default_y ?? 540),
        default_scale: Number(this.character?.default_scale ?? 1),
        mouth_scene_object_id: this.character?.mouth_scene_object_id ? Number(this.character.mouth_scene_object_id) : null,
        clear_mouth_scene_object_id: !this.character?.mouth_scene_object_id
      };
    },

    readCharacterSettingsPayload(form) {
      const formData = new FormData(form);
      return {
        name: String(formData.get('character_name') ?? '').trim() || '',
        description: String(formData.get('character_description') ?? ''),
        default_x: Number(formData.get('default_x') ?? 960),
        default_y: Number(formData.get('default_y') ?? 540),
        default_scale: Number(formData.get('default_scale') ?? 1),
        mouth_scene_object_id: formData.get('mouth_scene_object_id')
          ? Number(formData.get('mouth_scene_object_id'))
          : null,
        clear_mouth_scene_object_id: !formData.get('mouth_scene_object_id')
      };
    },

    async autosaveCharacterSettingsForm(form) {
      const previousPayload = this.currentCharacterSettingsPayload();
      const nextPayload = this.readCharacterSettingsPayload(form);
      if (JSON.stringify(previousPayload) === JSON.stringify(nextPayload)) return;
      const saved = await this.saveCharacterSettings(form, nextPayload);
      if (!saved) return;
      this.recordGlobalHistoryEntry({
        label: 'Edit character settings',
        undo: () => this.restoreCharacterSettingsPayload(previousPayload),
        redo: () => this.restoreCharacterSettingsPayload(nextPayload)
      });
    },

    async saveCharacterSettings(form, payload = null) {
      const nextPayload = payload ?? this.readCharacterSettingsPayload(form);
      this.setStatus('[data-character-settings-status]', 'Saving character settings...');
      try {
        const nextCharacter = await apiFetch(`/api/characters/${this.characterId}`, {
          method: 'PATCH',
          body: JSON.stringify(nextPayload)
        });
        this.character = nextCharacter;
        if (this.scene) {
          this.scene.title = nextCharacter.name;
          this.scene.description = nextCharacter.description;
        }
        this.setStatus('[data-character-settings-status]', 'Character settings saved.');
        this.refreshView();
        return true;
      } catch {
        this.setStatus('[data-character-settings-status]', 'Could not save character settings.');
        return false;
      }
    },

    async restoreCharacterSettingsPayload(payload) {
      const form = this.root?.querySelector('[data-character-settings-form]');
      if (!form) return;
      await this.saveCharacterSettings(form, payload);
    },

    async generateVisemes(button) {
      button.disabled = true;
      this.setStatus('[data-character-generation-status]', 'Generating visemes...');
      try {
        this.character = await apiFetch(`/api/characters/${this.characterId}/generate-visemes`, {
          method: 'POST'
        });
        await this.refreshScene();
        this.setStatus('[data-character-generation-status]', 'Visemes generated.');
      } catch {
        this.setStatus('[data-character-generation-status]', 'Could not generate visemes.');
      } finally {
        button.disabled = false;
      }
    },

    async generatePoses(button) {
      const form = button.closest('[data-generate-character-poses-form]');
      const poseSubfolder = String(form?.elements.pose_subfolder?.value ?? '').trim();
      if (!poseSubfolder) {
        this.setStatus('[data-character-generation-status]', 'Choose a pose folder first.');
        return;
      }
      button.disabled = true;
      this.setStatus('[data-character-generation-status]', 'Generating poses...');
      try {
        this.character = await apiFetch(`/api/characters/${this.characterId}/generate-poses`, {
          method: 'POST',
          body: JSON.stringify({pose_subfolder: poseSubfolder})
        });
        await this.refreshScene();
        this.setStatus('[data-character-generation-status]', 'Poses generated.');
      } catch {
        this.setStatus('[data-character-generation-status]', 'Could not generate poses.');
      } finally {
        button.disabled = false;
      }
    },

    setStatus(selector, message) {
      const status = document.querySelector(selector);
      applyStatus(status, message);
    }
  };

  return controller;
};

export {CharacterEditorCtrl};
