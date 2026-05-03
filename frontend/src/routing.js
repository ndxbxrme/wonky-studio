import {DefaultCtrl} from './components/default.ctrl.js';
import defaultTemplate from './components/default.html?raw';

const initRoutes = async (app) => {
  app.registerHelper('not', value => !value);
  app.template('default', defaultTemplate);
  app.controller('default', DefaultCtrl(app));
}
export {initRoutes}
