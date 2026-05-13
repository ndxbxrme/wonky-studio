import {apiFetch} from '../api.js';

const PreviewGameCtrl = app => async () => {
  const controller = {
    async postLoad() {
      const [globalSettings, scenes] = await Promise.all([
        apiFetch('/api/global-settings'),
        apiFetch('/api/scenes')
      ]);
      const baseScenes = [...scenes]
        .filter(scene => scene.presentation_mode !== 'overlay')
        .sort((left, right) => Number(left.id) - Number(right.id));
      const configuredSceneId = Number(globalSettings?.start_scene_id) || null;
      const targetScene = baseScenes.find(scene => Number(scene.id) === configuredSceneId) ?? baseScenes[0] ?? null;
      app.goto(targetScene ? `/preview/${targetScene.id}` : '/');
    }
  };

  return controller;
};

export {PreviewGameCtrl};
