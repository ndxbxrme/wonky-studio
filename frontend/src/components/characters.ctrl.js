import {apiFetch, characterImageUrl} from '../api.js';
import {applyStatus} from '../status.js';
import {user} from '../state/user.js';

const CharactersCtrl = app => async () => {
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    characters: [],
    poseFolders: [],
    selectedCharacterId: null,
    selectedCharacter: null,
    selectedObjectId: null,
    selectedObject: null,
    selectedAnimationId: null,
    selectedAnimation: null,
    animationFrameDrafts: [],
    status: '',
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-characters-page]');
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
      [this.characters, this.poseFolders] = await Promise.all([
        apiFetch('/api/characters'),
        apiFetch('/api/character-pose-folders')
      ]);
      this.prepareState();
    },

    prepareState() {
      this.characters = (this.characters ?? []).map(character => ({
        ...character,
        isSelected: Number(character.id) === Number(this.selectedCharacterId),
        baseImages: (character.images ?? []).filter(image => image.component_key === 'base'),
        visemeImages: (character.images ?? []).filter(image => image.component_key === 'viseme_mouth'),
        basePreviewUrl: characterImageUrl(resolvePreferredImageId(character, 'base')),
      }));
      if (!this.characters.some(character => Number(character.id) === Number(this.selectedCharacterId))) {
        this.selectedCharacterId = this.characters[0]?.id ?? null;
      }
      this.selectedCharacter = this.characters.find(character => Number(character.id) === Number(this.selectedCharacterId)) ?? null;
      const objects = this.selectedCharacter?.objects ?? [];
      if (!objects.some(object => Number(object.id) === Number(this.selectedObjectId))) {
        this.selectedObjectId = objects[0]?.id ?? null;
      }
      if (this.selectedCharacter) {
        this.selectedCharacter.objects = objects.map(object => ({
          ...object,
          isSelected: Number(object.id) === Number(this.selectedObjectId)
        }));
      }
      this.selectedObject = (this.selectedCharacter?.objects ?? []).find(object => Number(object.id) === Number(this.selectedObjectId)) ?? null;
      const animations = this.selectedCharacter?.animations ?? [];
      if (!animations.some(animation => Number(animation.id) === Number(this.selectedAnimationId))) {
        this.selectedAnimationId = animations[0]?.id ?? null;
      }
      if (this.selectedCharacter) {
        this.selectedCharacter.animations = animations.map(animation => ({
          ...animation,
          isSelected: Number(animation.id) === Number(this.selectedAnimationId)
        }));
      }
      this.selectedAnimation = (this.selectedCharacter?.animations ?? []).find(animation => Number(animation.id) === Number(this.selectedAnimationId)) ?? null;
      this.animationFrameDrafts = (this.selectedAnimation?.frames ?? []).map(frame => ({
        key: String(frame.id),
        character_image_id: Number(frame.character_image_id),
        duration_seconds: Number(frame.duration_seconds)
      }));
    },

    refreshView() {
      app.refresh();
      this.setControlValues();
    },

    setControlValues() {
      const characterForm = this.root?.querySelector('[data-character-form]');
      if (characterForm) {
        const character = this.selectedCharacter;
        characterForm.elements.character_id.value = character?.id ?? '';
        characterForm.elements.name.value = character?.name ?? '';
        characterForm.elements.description.value = character?.description ?? '';
        characterForm.elements.sort_order.value = character?.sort_order ?? 0;
        characterForm.elements.default_x.value = character?.default_x ?? 960;
        characterForm.elements.default_y.value = character?.default_y ?? 540;
        characterForm.elements.default_scale.value = character?.default_scale ?? 1;
      }
      const animationForm = this.root?.querySelector('[data-character-animation-form]');
      if (animationForm) {
        animationForm.elements.animation_id.value = this.selectedAnimation?.id ?? '';
        animationForm.elements.animation_name.value = this.selectedAnimation?.name ?? '';
      }
      const objectForm = this.root?.querySelector('[data-character-object-form]');
      if (objectForm) {
        objectForm.elements.character_object_id.value = this.selectedObject?.id ?? '';
        objectForm.elements.name.value = this.selectedObject?.name ?? '';
        objectForm.elements.description.value = this.selectedObject?.description ?? '';
        objectForm.elements.prompt.value = this.selectedObject?.prompt ?? '';
        objectForm.elements.sort_order.value = this.selectedObject?.sort_order ?? 0;
        objectForm.elements.is_viseme_target.checked = Boolean(this.selectedObject?.is_viseme_target);
      }
    },

    setStatus(message) {
      this.status = message;
      applyStatus(this.root?.querySelector('[data-characters-status]'), message);
    },

    async onClick(event) {
      const selectCharacter = event.target.closest('[data-action="select-character"]');
      if (selectCharacter) {
        this.selectedCharacterId = Number(selectCharacter.dataset.characterId);
        this.prepareState();
        this.refreshView();
        return;
      }
      const deleteCharacter = event.target.closest('[data-action="delete-character"]');
      if (deleteCharacter) {
        await this.deleteCharacter(Number(deleteCharacter.dataset.characterId));
        return;
      }
      const deleteImage = event.target.closest('[data-action="delete-character-image"]');
      if (deleteImage) {
        await this.deleteImage(Number(deleteImage.dataset.imageId));
        return;
      }
      const selectAnimation = event.target.closest('[data-action="select-character-animation"]');
      if (selectAnimation) {
        this.selectedAnimationId = Number(selectAnimation.dataset.animationId);
        this.prepareState();
        this.refreshView();
        return;
      }
      const selectObject = event.target.closest('[data-action="select-character-object"]');
      if (selectObject) {
        this.selectedObjectId = Number(selectObject.dataset.objectId);
        this.prepareState();
        this.refreshView();
        return;
      }
      const addFrame = event.target.closest('[data-action="add-character-animation-frame"]');
      if (addFrame) {
        this.animationFrameDrafts.push({
          key: `${Date.now()}-${Math.random()}`,
          character_image_id: Number(this.selectedCharacter?.baseImages?.[0]?.id ?? 0),
          duration_seconds: 0.2
        });
        this.refreshView();
        return;
      }
      const removeFrame = event.target.closest('[data-action="remove-character-animation-frame"]');
      if (removeFrame) {
        const frameKey = String(removeFrame.dataset.frameKey);
        this.animationFrameDrafts = this.animationFrameDrafts.filter(frame => String(frame.key) !== frameKey);
        this.refreshView();
        return;
      }
      const deleteAnimation = event.target.closest('[data-action="delete-character-animation"]');
      if (deleteAnimation) {
        await this.deleteAnimation(Number(deleteAnimation.dataset.animationId));
        return;
      }
      const deleteObject = event.target.closest('[data-action="delete-character-object"]');
      if (deleteObject) {
        await this.deleteObject(Number(deleteObject.dataset.objectId));
      }
    },

    async onSubmit(event) {
      const characterForm = event.target.closest('[data-character-form]');
      if (characterForm) {
        event.preventDefault();
        await this.saveCharacter(characterForm);
        return;
      }
      const uploadForm = event.target.closest('[data-character-image-upload-form]');
      if (uploadForm) {
        event.preventDefault();
        await this.uploadCharacterImage(uploadForm);
        return;
      }
      const animationForm = event.target.closest('[data-character-animation-form]');
      if (animationForm) {
        event.preventDefault();
        await this.saveAnimation(animationForm);
        return;
      }
      const objectForm = event.target.closest('[data-character-object-form]');
      if (objectForm) {
        event.preventDefault();
        await this.saveObject(objectForm);
        return;
      }
      const visemesForm = event.target.closest('[data-generate-visemes-form]');
      if (visemesForm) {
        event.preventDefault();
        await this.generateVisemes();
        return;
      }
      const posesForm = event.target.closest('[data-generate-poses-form]');
      if (posesForm) {
        event.preventDefault();
        await this.generatePoses(posesForm);
      }
    },

    async saveCharacter(form) {
      const payload = {
        name: String(form.elements.name.value || '').trim(),
        description: String(form.elements.description.value || ''),
        sort_order: Number(form.elements.sort_order.value || 0),
        default_x: Number(form.elements.default_x.value || 960),
        default_y: Number(form.elements.default_y.value || 540),
        default_scale: Number(form.elements.default_scale.value || 1),
      };
      if (!payload.name) return;
      const characterId = Number(form.elements.character_id.value || 0);
      this.setStatus(characterId ? 'Saving character...' : 'Creating character...');
      try {
        const saved = await apiFetch(characterId ? `/api/characters/${characterId}` : '/api/characters', {
          method: characterId ? 'PATCH' : 'POST',
          body: JSON.stringify(payload)
        });
        this.selectedCharacterId = saved.id;
        await this.refreshData();
        this.refreshView();
        this.setStatus(characterId ? 'Character saved.' : 'Character created.');
      } catch {
        this.setStatus(characterId ? 'Could not save character.' : 'Could not create character.');
      }
    },

    async uploadCharacterImage(form) {
      if (!this.selectedCharacter) return;
      const formData = new FormData(form);
      this.setStatus('Uploading character image...');
      try {
        await apiFetch(`/api/characters/${this.selectedCharacter.id}/images`, {
          method: 'POST',
          body: formData
        });
        form.reset();
        await this.refreshData();
        this.refreshView();
        this.setStatus('Character image uploaded.');
      } catch {
        this.setStatus('Could not upload character image.');
      }
    },

    async generateVisemes() {
      if (!this.selectedCharacter) return;
      this.setStatus('Generating visemes...');
      try {
        await apiFetch(`/api/characters/${this.selectedCharacter.id}/generate-visemes`, {method: 'POST'});
        await this.refreshData();
        this.refreshView();
        this.setStatus('Visemes generated.');
      } catch {
        this.setStatus('Could not generate visemes.');
      }
    },

    async generatePoses(form) {
      if (!this.selectedCharacter) return;
      const pose_subfolder = String(form.elements.pose_subfolder.value || '').trim();
      if (!pose_subfolder) return;
      this.setStatus('Generating poses...');
      try {
        await apiFetch(`/api/characters/${this.selectedCharacter.id}/generate-poses`, {
          method: 'POST',
          body: JSON.stringify({pose_subfolder})
        });
        await this.refreshData();
        this.refreshView();
        this.setStatus('Poses generated.');
      } catch {
        this.setStatus('Could not generate poses.');
      }
    },

    async saveAnimation(form) {
      if (!this.selectedCharacter) return;
      const payload = {
        name: String(form.elements.animation_name.value || '').trim(),
        frames: this.animationFrameDrafts
          .map(frame => ({
            character_image_id: Number(this.root?.querySelector(`[data-frame-image-id="${frame.key}"]`)?.value || frame.character_image_id || 0),
            duration_seconds: Number(this.root?.querySelector(`[data-frame-duration="${frame.key}"]`)?.value || frame.duration_seconds || 0)
          }))
          .filter(frame => frame.character_image_id > 0 && frame.duration_seconds > 0)
      };
      if (!payload.name) return;
      const animationId = Number(form.elements.animation_id.value || 0);
      this.setStatus(animationId ? 'Saving animation...' : 'Creating animation...');
      try {
        const saved = await apiFetch(
          animationId ? `/api/character-animations/${animationId}` : `/api/characters/${this.selectedCharacter.id}/animations`,
          {
            method: animationId ? 'PATCH' : 'POST',
            body: JSON.stringify(payload)
          }
        );
        this.selectedAnimationId = saved.id;
        await this.refreshData();
        this.refreshView();
        this.setStatus(animationId ? 'Animation saved.' : 'Animation created.');
      } catch {
        this.setStatus(animationId ? 'Could not save animation.' : 'Could not create animation.');
      }
    },

    async saveObject(form) {
      if (!this.selectedCharacter) return;
      const payload = {
        name: String(form.elements.name.value || '').trim(),
        description: String(form.elements.description.value || ''),
        prompt: String(form.elements.prompt.value || ''),
        sort_order: Number(form.elements.sort_order.value || 0),
        is_viseme_target: Boolean(form.elements.is_viseme_target.checked)
      };
      if (!payload.name) return;
      const objectId = Number(form.elements.character_object_id.value || 0);
      this.setStatus(objectId ? 'Saving object...' : 'Adding object...');
      try {
        const saved = await apiFetch(
          objectId ? `/api/character-objects/${objectId}` : `/api/characters/${this.selectedCharacter.id}/objects`,
          {
            method: objectId ? 'PATCH' : 'POST',
            body: JSON.stringify(payload)
          }
        );
        this.selectedObjectId = saved.id;
        await this.refreshData();
        this.refreshView();
        this.setStatus(objectId ? 'Object saved.' : 'Object added.');
      } catch {
        this.setStatus(objectId ? 'Could not save object.' : 'Could not add object.');
      }
    },

    async deleteCharacter(characterId) {
      if (!window.confirm('Remove this character and all of its images and animations?')) return;
      this.setStatus('Removing character...');
      try {
        await apiFetch(`/api/characters/${characterId}`, {method: 'DELETE'});
        if (Number(this.selectedCharacterId) === Number(characterId)) this.selectedCharacterId = null;
        await this.refreshData();
        this.refreshView();
        this.setStatus('Character removed.');
      } catch {
        this.setStatus('Could not remove character.');
      }
    },

    async deleteImage(imageId) {
      this.setStatus('Removing image...');
      try {
        await apiFetch(`/api/character-images/${imageId}`, {method: 'DELETE'});
        await this.refreshData();
        this.refreshView();
        this.setStatus('Image removed.');
      } catch {
        this.setStatus('Could not remove image.');
      }
    },

    async deleteAnimation(animationId) {
      this.setStatus('Removing animation...');
      try {
        await apiFetch(`/api/character-animations/${animationId}`, {method: 'DELETE'});
        if (Number(this.selectedAnimationId) === Number(animationId)) this.selectedAnimationId = null;
        await this.refreshData();
        this.refreshView();
        this.setStatus('Animation removed.');
      } catch {
        this.setStatus('Could not remove animation.');
      }
    },

    async deleteObject(objectId) {
      if (!window.confirm('Remove this character object? Any masks linked to it will be removed too.')) return;
      this.setStatus('Removing object...');
      try {
        await apiFetch(`/api/character-objects/${objectId}`, {method: 'DELETE'});
        if (Number(this.selectedObjectId) === Number(objectId)) this.selectedObjectId = null;
        await this.refreshData();
        this.refreshView();
        this.setStatus('Object removed.');
      } catch {
        this.setStatus('Could not remove object.');
      }
    }
  };

  await controller.refreshData();
  return controller;
};

function resolvePreferredImageId(character, componentKey) {
  const images = (character?.images ?? []).filter(image => image.component_key === componentKey);
  return images.find(image => image.is_default)?.id ?? images[0]?.id ?? 0;
}

export {CharactersCtrl};
