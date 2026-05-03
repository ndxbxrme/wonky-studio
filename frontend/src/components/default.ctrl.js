const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000';

const DefaultCtrl = app => async () => {
  const params = new URLSearchParams(window.location.search);
  const inviteToken = params.get('invite');
  const loginUrl = new URL('/api/auth/google/login', API_BASE_URL);
  if (inviteToken) loginUrl.searchParams.set('invite', inviteToken);

  const session = await loadSession();
  const user = session?.user ?? null;
  if (user && !user.display_name) user.display_name = user.email;

  return {
    appName: 'Wonky Studio',
    organizationId: session?.organization_id ?? 'wonky-studio',
    user,
    isGuest: !user,
    isAdmin: user?.role === 'admin',
    loginUrl: loginUrl.toString(),
    inviteToken: inviteToken ?? '',
    postLoad() {
      wireInviteForm();
      wireLogoutButton(app);
    }
  };
};

async function loadSession() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/auth/session`, {
      credentials: 'include'
    });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

function wireInviteForm() {
  const form = document.querySelector('[data-invite-form]');
  const result = document.querySelector('[data-invite-result]');
  if (!form || !result || form.dataset.bound) return;
  form.dataset.bound = 'true';

  form.addEventListener('submit', async event => {
    event.preventDefault();
    result.textContent = 'Generating invite...';

    const formData = new FormData(form);
    const payload = {
      email: formData.get('email') || null,
      role: formData.get('role') || 'user',
      expires_in_days: Number(formData.get('expires_in_days') || 7)
    };

    try {
      const response = await fetch(`${API_BASE_URL}/api/invites`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!response.ok) throw new Error(`Invite failed: ${response.status}`);
      const invite = await response.json();
      result.replaceChildren();
      const link = document.createElement('a');
      link.href = invite.invite_link;
      link.textContent = invite.invite_link;
      result.append(link);
      form.reset();
    } catch {
      result.textContent = 'Could not generate an invite link.';
    }
  });
}

function wireLogoutButton(app) {
  const button = document.querySelector('[data-logout-button]');
  if (!button || button.dataset.bound) return;
  button.dataset.bound = 'true';

  button.addEventListener('click', async () => {
    await fetch(`${API_BASE_URL}/api/auth/logout`, {
      method: 'POST',
      credentials: 'include'
    });
    app.goto('/');
  });
}

export {DefaultCtrl};
