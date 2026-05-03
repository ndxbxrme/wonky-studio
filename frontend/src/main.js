import { TurboMini } from './turbomini.js';
import { initRoutes } from './routing.js';

const app = TurboMini('/');

app.run(async app => {
  await initRoutes(app);
  app.start();
});
