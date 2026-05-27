import {apiUrl} from '../api.js';

const user = {
  session: null,
  current: null,
  organizationId: 'wonky-studio',
  activeProjectId: null,
  activeProjectName: '',
  authProviders: [],
  loaded: false,

  get isAuthenticated() {
    return Boolean(this.current);
  },

  get isAdmin() {
    return this.current?.role === 'admin';
  }
};

async function loadUser() {
  try {
    const response = await fetch(apiUrl('/api/auth/session'), {
      credentials: 'include'
    });
    if (!response.ok) {
      setUser(null);
      return user;
    }
    const session = await response.json();
    setUser(session);
  } catch {
    setUser(null);
  }
  return user;
}

async function logoutUser() {
  await fetch(apiUrl('/api/auth/logout'), {
    method: 'POST',
    credentials: 'include'
  });
  setUser(null);
}

function loginUrl(inviteToken = '') {
  const url = new URL(apiUrl('/api/auth/google/login'));
  if (inviteToken) url.searchParams.set('invite', inviteToken);
  return url.toString();
}

function setUser(session) {
  user.session = session;
  user.current = session?.user ?? null;
  if (user.current && !user.current.display_name) {
    user.current.display_name = user.current.email;
  }
  user.organizationId = session?.organization_id ?? 'wonky-studio';
  user.activeProjectId = Number.isFinite(Number(session?.active_project_id)) ? Number(session.active_project_id) : null;
  user.activeProjectName = String(session?.active_project_name ?? '');
  user.authProviders = session?.auth_providers ?? [];
  user.loaded = true;
}

export {loadUser, loginUrl, logoutUser, user};
