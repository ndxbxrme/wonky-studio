import {apiFetch, objectMaskUrl, objectThumbnailUrl, uploadedFileUrl} from '../api.js';

const scenes = [];

async function loadScenes() {
  const sceneSummaries = await apiFetch('/api/scenes');
  const loadedScenes = await Promise.all(
    sceneSummaries.map(async scene => {
      try {
        return await loadScene(scene.id);
      } catch {
        return scene;
      }
    })
  );
  replaceScenes(loadedScenes.map(prepareScene));
  return scenes;
}

async function loadScene(sceneId) {
  const scene = await apiFetch(`/api/scenes/${sceneId}`);
  return prepareScene(scene);
}

function replaceScenes(nextScenes) {
  scenes.splice(0, scenes.length, ...nextScenes);
}

function replaceScene(updatedScene) {
  const preparedScene = prepareScene(updatedScene);
  const sceneIndex = scenes.findIndex(scene => scene.id === preparedScene.id);
  if (sceneIndex === -1) scenes.unshift(preparedScene);
  else scenes.splice(sceneIndex, 1, preparedScene);
  return preparedScene;
}

function findScene(sceneId) {
  return scenes.find(scene => scene.id === Number(sceneId)) ?? null;
}

function prepareScene(scene) {
  const objects = (scene.objects ?? []).map(object => {
    const masks = (object.masks ?? []).map(mask => ({
      ...mask,
      originalUrl: uploadedFileUrl(mask.uploaded_file_id),
      rawUrl: objectMaskUrl(mask.id, 'raw', maskCacheKey(mask)),
      softUrl: mask.soft_relative_path
        ? objectMaskUrl(mask.id, 'soft', maskCacheKey(mask))
        : ''
    }));
    const thumbnailCacheKey = [
      masks.map(maskCacheKey).join('~'),
      object.inventory_image_relative_path ?? '',
      object.updated_at ?? ''
    ].join('~');
    return {
      ...object,
      prompt: object.prompt ?? object.name,
      maskCount: masks.length || object.mask_image_count || 0,
      animationCount: object.animation_count ?? 0,
      hasAnimations: Boolean(object.animation_count),
      hasMasks: Boolean(masks.length),
      hasNoMasks: !masks.length,
      firstMaskId: masks[0]?.id ?? '',
      thumbnailUrl: masks.length ? objectThumbnailUrl(object.id, thumbnailCacheKey) : '',
      masks
    };
  });
  const objectMaskCount = objects.reduce((total, object) => total + object.maskCount, 0);

  return {
    ...scene,
    presentation_mode: scene.presentation_mode ?? 'base',
    images: scene.images ?? [],
    objects,
    thumbnailUrl: scene.representative_uploaded_file_id
      ? uploadedFileUrl(scene.representative_uploaded_file_id)
      : '',
    hasObjects: Boolean(objects.length),
    objectMaskCount
  };
}

function maskCacheKey(mask) {
  return [
    mask.created_at,
    mask.updated_at ?? '',
    mask.relative_path,
    mask.soft_relative_path ?? '',
    mask.prompt_text ?? ''
  ].join('|');
}

export {
  findScene,
  loadScene,
  loadScenes,
  prepareScene,
  replaceScene,
  scenes
};
