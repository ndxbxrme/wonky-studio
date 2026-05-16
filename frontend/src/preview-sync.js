import {apiFetch} from './api.js';

const PREVIEW_CHANNEL_NAME = 'wonky-scene-preview';

function buildPreviewWindowFeatures() {
  return [
    'popup=yes',
    'width=1600',
    'height=1000',
    'left=80',
    'top=60',
    'resizable=yes',
    'scrollbars=yes'
  ].join(',');
}

function openScenePreview(sceneId) {
  const route = `/preview/${sceneId}`;
  const previewWindow = window.open(route, `wonky-scene-preview-${sceneId}`, buildPreviewWindowFeatures());
  previewWindow?.focus();
  return previewWindow;
}

function openGamePreview() {
  const previewWindow = window.open('', 'wonky-game-preview', buildPreviewWindowFeatures());
  previewWindow?.document.write(`
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <title>Wonky Studio Preview</title>
        <style>
          body {
            margin: 0;
            min-height: 100vh;
            display: grid;
            place-items: center;
            background: linear-gradient(180deg, #f7f2e7 0%, #efe5d4 100%);
            color: #2f281f;
            font: 500 16px/1.4 Georgia, serif;
          }
          .card {
            width: min(420px, calc(100vw - 48px));
            padding: 24px 26px;
            border: 1px solid #d9cfbe;
            border-radius: 18px;
            background: rgba(255, 252, 245, 0.96);
            box-shadow: 0 18px 40px rgba(40, 34, 24, 0.14);
          }
          p {
            margin: 0;
          }
          p + p {
            margin-top: 10px;
            color: #655a4a;
            font-size: 14px;
          }
        </style>
      </head>
      <body>
        <div class="card">
          <p>Opening preview…</p>
          <p>Resolving start scene.</p>
        </div>
      </body>
    </html>
  `);
  previewWindow?.document.close();
  previewWindow?.focus();
  void resolvePreviewGameTarget()
    .then(route => {
      if (!previewWindow || previewWindow.closed) return;
      previewWindow.location.replace(route);
    })
    .catch(() => {
      if (!previewWindow || previewWindow.closed) return;
      previewWindow.location.replace('/preview-game');
    });
  return previewWindow;
}

function notifyScenePreview(sceneId, type = 'scene-updated') {
  if (typeof window === 'undefined' || typeof window.BroadcastChannel === 'undefined') return;
  const channel = new BroadcastChannel(PREVIEW_CHANNEL_NAME);
  channel.postMessage({
    sceneId: Number(sceneId),
    type,
    sentAt: Date.now()
  });
  channel.close();
}

function listenScenePreview(sceneId, handler) {
  if (typeof window === 'undefined' || typeof window.BroadcastChannel === 'undefined') {
    return () => {};
  }
  const channel = new BroadcastChannel(PREVIEW_CHANNEL_NAME);
  const onMessage = event => {
    const message = event.data ?? {};
    if (Number(message.sceneId) !== Number(sceneId)) return;
    handler(message);
  };
  channel.addEventListener('message', onMessage);
  return () => {
    channel.removeEventListener('message', onMessage);
    channel.close();
  };
}

async function resolvePreviewGameTarget() {
  const [globalSettings, scenes] = await Promise.all([
    apiFetch('/api/global-settings'),
    apiFetch('/api/scenes')
  ]);
  const baseScenes = [...scenes]
    .filter(scene => scene.presentation_mode !== 'overlay')
    .sort((left, right) => Number(left.id) - Number(right.id));
  const configuredSceneId = Number(globalSettings?.start_scene_id) || null;
  const targetScene = baseScenes.find(scene => Number(scene.id) === configuredSceneId) ?? baseScenes[0] ?? null;
  return targetScene ? `/preview/${targetScene.id}` : '/';
}

export {listenScenePreview, notifyScenePreview, openGamePreview, openScenePreview};
