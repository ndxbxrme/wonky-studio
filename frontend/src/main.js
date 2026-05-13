import { TurboMini } from './turbomini.js';
import { initRoutes } from './routing.js';
import {openGamePreview} from './preview-sync.js';

const app = TurboMini('/');

app.run(async app => {
  await initRoutes(app);
  document.addEventListener('click', event => {
    const previewGameLink = event.target instanceof Element
      ? event.target.closest('[data-action="open-game-preview"]')
      : null;
    if (!previewGameLink) return;
    event.preventDefault();
    openGamePreview();
  });
  app.start();
});
