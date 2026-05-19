import {apiFetch, objectMaskUrl, objectThumbnailUrl, uploadedFileThumbnailUrl, uploadedFileUrl} from '../api.js';

const scenes = [];

async function loadScenes() {
  const sceneSummaries = await loadSceneSummaries();
  await hydrateSceneDetails(sceneSummaries.map(scene => scene.id));
  return scenes;
}

async function loadSceneSummaries() {
  const sceneSummaries = await apiFetch('/api/scenes');
  replaceScenes(sceneSummaries.map(prepareScene));
  return scenes;
}

async function loadScene(sceneId) {
  const scene = await apiFetch(`/api/scenes/${sceneId}`);
  return prepareScene(scene);
}

async function hydrateSceneDetails(sceneIds = []) {
  const ids = sceneIds.length
    ? sceneIds.map(Number)
    : scenes.filter(scene => !scene.hasLoadedDetails).map(scene => Number(scene.id));
  for (const sceneId of ids) {
    try {
      replaceScene(await loadScene(sceneId));
    } catch {
      // Keep lightweight summary data if detail hydration fails.
    }
  }
  return scenes;
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
  const images = (scene.images ?? []).map(image => ({
    ...image,
    originalUrl: uploadedFileUrl(image.uploaded_file_id)
  }));
  const objects = (scene.objects ?? []).map(object => {
    const masks = (object.masks ?? []).map(mask => ({
      ...mask,
      originalUrl: uploadedFileUrl(mask.uploaded_file_id),
      rawUrl: objectMaskUrl(mask.id, 'raw', shortCacheKey(maskCacheKey(mask))),
      softUrl: mask.soft_relative_path
        ? objectMaskUrl(mask.id, 'soft', shortCacheKey(maskCacheKey(mask)))
        : ''
    }));
    const thumbnailCacheKey = shortCacheKey([
      masks.map(maskCacheKey).join('~'),
      object.inventory_image_relative_path ?? '',
      object.updated_at ?? ''
    ].join('~'));
    return {
      ...object,
      prompt: object.prompt ?? object.name,
      maskCount: masks.length || object.mask_image_count || 0,
      animationCount: object.animation_count ?? 0,
      hasAnimations: Boolean(object.animation_count),
      hasMasks: Boolean(masks.length),
      hasNoMasks: !masks.length,
      firstMaskId: masks[0]?.id ?? '',
      thumbnailUrl: masks.length ? objectThumbnailUrl(object.id, 160, thumbnailCacheKey) : '',
      masks
    };
  });
  const hasLoadedDetails = Array.isArray(scene.images) || Array.isArray(scene.objects);
  const imageCount = images.length || Number(scene.image_count ?? 0);
  const objectCount = objects.length || Number(scene.object_count ?? 0);
  const objectMaskCount = hasLoadedDetails
    ? objects.reduce((total, object) => total + object.maskCount, 0)
    : Number(scene.object_mask_count ?? 0);

  return {
    ...scene,
    presentation_mode: scene.presentation_mode ?? 'base',
    background_frame_index: Number(scene.background_frame_index ?? 0),
    images,
    imageCount,
    objects,
    objectCount,
    thumbnailUrl: scene.representative_uploaded_file_id
      ? uploadedFileThumbnailUrl(
        scene.representative_uploaded_file_id,
        640,
        shortCacheKey([
          String(scene.representative_uploaded_file_id ?? ''),
          String(scene.representative_hash ?? ''),
          String(scene.background_frame_index ?? 0),
          String(scene.updated_at ?? '')
        ].join('|'))
      )
      : '',
    hasLoadedDetails,
    hasObjects: Boolean(objectCount),
    hasLoadedObjectList: Boolean(objects.length),
    objectMaskCount,
    backgroundFrameMax: Math.max(0, images.length - 1)
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

function shortCacheKey(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `k${(hash >>> 0).toString(36)}`;
}

export {
  findScene,
  hydrateSceneDetails,
  loadScene,
  loadSceneSummaries,
  loadScenes,
  prepareScene,
  replaceScene,
  scenes
};
