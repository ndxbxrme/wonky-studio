import {apiFetch} from '../api.js';
import {applyStatus} from '../status.js';
import {user} from '../state/user.js';

const SystemHealthCtrl = app => async () => {
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    status: '',
    overallStatus: 'warning',
    dependencies: [],
    hasDependencies: false,
    hasChecked: false,
    root: null,
    unloadHandlers: [],

    async postLoad() {
      this.root = document.querySelector('[data-system-health-page]');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.applyStatus();
      this.loadHealth();
    },

    unload() {
      this.unloadHandlers.forEach(unload => unload());
      this.unloadHandlers = [];
    },

    bind(target, type, handler) {
      if (!target) return;
      target.addEventListener(type, handler);
      this.unloadHandlers.push(() => target.removeEventListener(type, handler));
    },

    async onClick(event) {
      const refreshButton = event.target.closest('[data-action="refresh-health"]');
      if (!refreshButton) return;
      refreshButton.disabled = true;
      await this.loadHealth();
      refreshButton.disabled = false;
    },

    async loadHealth() {
      this.setStatus('Checking services...');
      try {
        const response = await apiFetch('/api/dependency-health');
        this.overallStatus = response.status ?? 'warning';
        this.dependencies = (response.dependencies ?? []).map(item => ({
          ...item,
          isOk: item.status === 'ok',
          isWarning: item.status === 'warning',
          isError: item.status === 'error',
        }));
        this.hasDependencies = this.dependencies.length > 0;
        this.hasChecked = true;
        this.setStatus('Service status refreshed.');
        this.refreshView();
      } catch {
        this.hasChecked = true;
        this.setStatus('Could not load service status.');
        this.refreshView();
      }
    },

    refreshView() {
      if (!this.root) return;
      app.refresh();
      requestAnimationFrame(() => this.applyStatus());
    },

    setStatus(message) {
      this.status = message;
      this.applyStatus();
    },

    applyStatus() {
      const status = this.root?.querySelector('[data-system-health-status]');
      applyStatus(status, this.status);
    }
  };

  controller.status = 'Checking services...';
  return controller;
};

export {SystemHealthCtrl};
