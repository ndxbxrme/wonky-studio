import { TurboMini } from './turbomini.js';
import { initRoutes } from './routing.js';
import {openGamePreview} from './preview-sync.js';
import {hydrateIcons} from './icons.js';

const app = TurboMini('/');

app.run(async app => {
  await initRoutes(app);
  hydrateIcons(document);
  const iconObserver = new MutationObserver(records => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (node instanceof Element) hydrateIcons(node);
      }
    }
  });
  iconObserver.observe(document.body, {childList: true, subtree: true});
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
