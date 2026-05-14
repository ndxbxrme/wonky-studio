import {DefaultCtrl} from './components/default.ctrl.js';
import defaultTemplate from './components/default.html?raw';
import {NotAuthorizedCtrl} from './components/not-authorized.ctrl.js';
import notAuthorizedTemplate from './components/not-authorized.html?raw';
import {SceneCtrl} from './components/scene.ctrl.js';
import sceneTemplate from './components/scene.html?raw';
import {MaskEditorCtrl} from './components/mask-editor.ctrl.js';
import maskEditorTemplate from './components/mask-editor.html?raw';
import {AnimationsCtrl} from './components/animations.ctrl.js';
import animationsTemplate from './components/animations.html?raw';
import {ScriptReviewCtrl} from './components/script-review.ctrl.js';
import scriptReviewTemplate from './components/script-review.html?raw';
import {ActionsCtrl} from './components/actions.ctrl.js';
import actionsTemplate from './components/actions.html?raw';
import {PreviewCtrl} from './components/preview.ctrl.js';
import previewTemplate from './components/preview.html?raw';
import {AudioLibraryCtrl} from './components/audio-library.ctrl.js';
import audioLibraryTemplate from './components/audio-library.html?raw';
import {ImagesCtrl} from './components/images.ctrl.js';
import imagesTemplate from './components/images.html?raw';
import {GlobalSettingsCtrl} from './components/global-settings.ctrl.js';
import globalSettingsTemplate from './components/global-settings.html?raw';
import {PreviewGameCtrl} from './components/preview-game.ctrl.js';
import previewGameTemplate from './components/preview-game.html?raw';
import {authMiddleware} from './auth-middleware.js';

const initRoutes = async (app) => {
  app.registerHelper('not', value => !value);
  app.registerHelper('eq', (left, right) => left === right);
  app.registerHelper('formatBytes', value => formatBytes(Number(value || 0)));
  app.addMiddleware(authMiddleware(app));
  app.template('default', defaultTemplate);
  app.controller('default', DefaultCtrl(app));
  app.template('not-authorized', notAuthorizedTemplate);
  app.controller('not-authorized', NotAuthorizedCtrl(app));
  app.template('scene', sceneTemplate);
  app.controller('scene', SceneCtrl(app));
  app.template('mask-editor', maskEditorTemplate);
  app.controller('mask-editor', MaskEditorCtrl(app));
  app.template('animations', animationsTemplate);
  app.controller('animations', AnimationsCtrl(app));
  app.template('script-review', scriptReviewTemplate);
  app.controller('script-review', ScriptReviewCtrl(app));
  app.template('actions', actionsTemplate);
  app.controller('actions', ActionsCtrl(app));
  app.template('preview', previewTemplate);
  app.controller('preview', PreviewCtrl(app));
  app.template('audio-library', audioLibraryTemplate);
  app.controller('audio-library', AudioLibraryCtrl(app));
  app.template('images', imagesTemplate);
  app.controller('images', ImagesCtrl(app));
  app.template('global-settings', globalSettingsTemplate);
  app.controller('global-settings', GlobalSettingsCtrl(app));
  app.template('preview-game', previewGameTemplate);
  app.controller('preview-game', PreviewGameCtrl(app));
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

export {initRoutes}
