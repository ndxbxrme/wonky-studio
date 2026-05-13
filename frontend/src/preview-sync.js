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
  const previewWindow = window.open('/preview-game', 'wonky-game-preview', buildPreviewWindowFeatures());
  previewWindow?.focus();
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

export {listenScenePreview, notifyScenePreview, openGamePreview, openScenePreview};
