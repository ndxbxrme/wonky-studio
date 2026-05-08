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
import {authMiddleware} from './auth-middleware.js';

const initRoutes = async (app) => {
  app.registerHelper('not', value => !value);
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
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

export {initRoutes}
