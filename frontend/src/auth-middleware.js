import {loadUser, user} from './state/user.js';

const PUBLIC_PAGES = new Set(['not-authorized']);

function authMiddleware(app) {
  return async context => {
    await loadUser();
    if (PUBLIC_PAGES.has(context.page)) return;
    if (user.isAuthenticated) return;
    app.goto(`/not-authorized${window.location.search}`);
    return false;
  };
}

export {authMiddleware};
