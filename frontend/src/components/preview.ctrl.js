import {apiFetch, audioAssetUrl, scriptAudioCandidateUrl} from '../api.js';
import {previewAudioRuntime} from '../audio-runtime.js';
import {findScene} from '../state/scenes.js';
import {user} from '../state/user.js';
import {listenScenePreview} from '../preview-sync.js';
import {preloadPreviewAssets} from './scene-preview-element.js';

const MAX_CHAINED_INTERACTIONS = 100;
const SUBTITLE_LINGER_MS = 1000;
const SEQUENTIAL_AUDIO_GAP_MS = 350;
const DEFAULT_PRIMARY_LANGUAGE = 'en';
const DEFAULT_SECONDARY_LANGUAGE = 'fr';
const DEFAULT_TRANSLATION_MODE = 'sequential';
const FADE_FRAME_MS = 33;
const MAX_PRELOADED_CONNECTED_SCENES = 6;
const OVERLAY_OPEN_DUCK_FACTOR = 0.5;
let previewSceneCarryover = null;
let previewRouteTransitionInFlight = false;
const previewDataCache = new Map();

const PreviewCtrl = app => async params => {
  const sceneId = Number(params[0]);
  const controller = {
    appName: 'Wonky Studio',
    user: user.current,
    sceneId,
    scene: findScene(sceneId),
    previewData: null,
    overlayPreviewData: null,
    sceneOptions: [],
    previousSceneId: null,
    nextSceneId: null,
    runtimeSnapshot: null,
    runtimeObjects: [],
    runtimeVariables: [],
    runtimeState: null,
    overlayRuntimeSnapshot: null,
    overlayRuntimeState: null,
    previewObjects: [],
    currentSubtitle: null,
    currentFade: null,
    overlayCurrentSubtitle: null,
    overlayCurrentFade: null,
    overlayPresentationOpacity: 0,
    focusedBaseObjectId: null,
    focusedOverlayObjectId: null,
    showBackground: true,
    status: '',
    editorReady: false,
    editorMissing: false,
    unloadHandlers: [],
    previewSyncCleanup: null,
    executionVersion: 0,
    subtitleToken: 0,
    audioPlaybackToken: 0,
    activeAudio: [],
    activeAudioBaseVolume: 1,
    isTransitioningScene: false,
    runningSceneExit: false,
    pendingSceneTransitionTarget: null,
    preloadTimer: null,
    openingOverlaySceneId: null,
    basePreview: null,
    overlayPreview: null,
    overlayShell: null,
    overlayBackdrop: null,
    overlayFrame: null,

    async postLoad() {
      this.captureDom();
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.root, 'submit', event => this.onSubmit(event));
      this.bindPreviewEvents();
      this.bind(window, 'keydown', event => {
        void this.onWindowKeyDown(event);
      });
      this.previewSyncCleanup = listenScenePreview(this.sceneId, async () => {
        this.setStatus('Refreshing preview...');
        await this.reloadRuntime({rerunSceneEnter: true});
        this.setStatus('');
      });
      await this.configurePreview();
      await this.runSceneEnterActions();
    },

    unload() {
      this.executionVersion += 1;
      this.stopMediaPlayback();
      if (!previewRouteTransitionInFlight) previewAudioRuntime.stopAll();
      if (this.preloadTimer) window.clearTimeout(this.preloadTimer);
      this.preloadTimer = null;
      this.unloadHandlers.forEach(unload => unload());
      this.unloadHandlers = [];
      this.previewSyncCleanup?.();
      this.previewSyncCleanup = null;
    },

    captureDom() {
      this.root = document.querySelector('[data-preview-page]');
      this.basePreview = this.root?.querySelector('[data-preview-layer="base"]') ?? null;
      this.overlayPreview = this.root?.querySelector('[data-preview-layer="overlay"]') ?? null;
      this.overlayShell = this.root?.querySelector('[data-preview-overlay-shell]') ?? null;
      this.overlayBackdrop = this.root?.querySelector('[data-preview-overlay-backdrop]') ?? null;
      this.overlayFrame = this.root?.querySelector('[data-preview-overlay-frame]') ?? null;
    },

    bind(target, type, handler) {
      if (!target) return;
      target.addEventListener(type, handler);
      this.unloadHandlers.push(() => target.removeEventListener(type, handler));
    },

    bindPreviewEvents() {
      this.bind(this.basePreview, 'preview-object-click', event => this.onPreviewObjectClick(event, 'base'));
      this.bind(this.basePreview, 'preview-object-mouseover', event => this.onPreviewObjectMouseover(event, 'base'));
      this.bind(this.basePreview, 'preview-object-mouseout', event => this.onPreviewObjectMouseout(event, 'base'));
      this.bind(this.basePreview, 'preview-error', event => this.onPreviewError(event));
      this.bind(this.overlayPreview, 'preview-object-click', event => this.onPreviewObjectClick(event, 'overlay'));
      this.bind(this.overlayPreview, 'preview-object-mouseover', event => this.onPreviewObjectMouseover(event, 'overlay'));
      this.bind(this.overlayPreview, 'preview-object-mouseout', event => this.onPreviewObjectMouseout(event, 'overlay'));
      this.bind(this.overlayPreview, 'preview-error', event => this.onPreviewError(event));
    },

    async refreshData() {
      try {
        this.scene = findScene(this.sceneId) ?? {id: this.sceneId};
        this.previewData = await fetchPreviewData(this.sceneId);
        this.prepareSceneNavigation();
        this.prepareState();
        this.applyCarriedVariables();
        this.scheduleConnectedScenePreload();
        this.editorReady = Boolean(this.previewData);
        this.editorMissing = !this.editorReady;
      } catch {
        previewRouteTransitionInFlight = false;
        previewSceneCarryover = null;
        this.editorReady = false;
        this.editorMissing = true;
      }
    },

    prepareState() {
      this.runtimeSnapshot = createRuntimeSnapshot(this.previewData);
      this.runtimeState = cloneRuntimeState(this.runtimeSnapshot);
      this.currentSubtitle = null;
      this.currentFade = null;
      this.focusedBaseObjectId = null;
      this.clearOverlayState();
      this.refreshInspectorState();
    },

    prepareSceneNavigation() {
      this.sceneOptions = [...(this.previewData?.available_scenes ?? [])]
        .sort((left, right) => Number(left.id) - Number(right.id))
        .map(scene => ({
          ...scene,
          isCurrent: Number(scene.id) === Number(this.sceneId)
        }));
      const currentIndex = this.sceneOptions.findIndex(scene => Number(scene.id) === Number(this.sceneId));
      this.previousSceneId = currentIndex > 0 ? this.sceneOptions[currentIndex - 1].id : null;
      this.nextSceneId = currentIndex >= 0 && currentIndex < this.sceneOptions.length - 1
        ? this.sceneOptions[currentIndex + 1].id
        : null;
    },

    applyCarriedVariables() {
      if (!previewSceneCarryover || Number(previewSceneCarryover.sceneId) !== Number(this.sceneId)) return;
      for (const [variableId, value] of Object.entries(previewSceneCarryover.variables ?? {})) {
        if (!this.runtimeState?.variables?.[variableId]) continue;
        this.runtimeState.variables[variableId].value = structuredClone(value);
      }
      this.currentFade = previewSceneCarryover.fadeState
        ? structuredClone(previewSceneCarryover.fadeState)
        : null;
      previewSceneCarryover = null;
      previewRouteTransitionInFlight = false;
      this.refreshInspectorState();
    },

    clearOverlayState() {
      this.overlayPreviewData = null;
      this.overlayRuntimeSnapshot = null;
      this.overlayRuntimeState = null;
      this.overlayCurrentSubtitle = null;
      this.overlayCurrentFade = null;
      this.overlayPresentationOpacity = 0;
      this.focusedOverlayObjectId = null;
      this.openingOverlaySceneId = null;
    },

    refreshInspectorState() {
      const layer = this.getActiveLayerName();
      const previewData = this.getLayerPreviewData(layer);
      const runtimeState = this.getLayerRuntimeState(layer);
      const runtimeObjects = [...(previewData?.objects ?? [])]
        .map(object => {
          const state = runtimeState?.objects?.[object.id];
          return {
            id: object.id,
            name: state?.label || object.label || object.name,
            visible: Boolean(state?.visible),
            enabled: Boolean(state?.enabled),
            animationCount: object.animations?.length ?? 0,
            hasAnimations: Boolean(object.animations?.length),
            animations: (object.animations ?? []).map(animation => ({
              ...animation,
              frameCount: animation.frames?.length ?? 0
            }))
          };
        });
      this.runtimeObjects = runtimeObjects;
      this.previewObjects = runtimeObjects;
      this.runtimeVariables = Object.values(this.runtimeState?.variables ?? {}).map(variable => ({
        id: variable.id,
        name: variable.name,
        valueType: variable.value_type,
        valueText: formatRuntimeValue(variable.value)
      }));
      this.syncContinuousAudioState();
      this.syncRuntimePanels();
    },

    getActiveLayerName() {
      return this.overlayPreviewData ? 'overlay' : 'base';
    },

    getLayerPreviewData(layer) {
      return layer === 'overlay' ? this.overlayPreviewData : this.previewData;
    },

    getLayerRuntimeState(layer) {
      return layer === 'overlay' ? this.overlayRuntimeState : this.runtimeState;
    },

    getLayerPreviewElement(layer) {
      return layer === 'overlay' ? this.overlayPreview : this.basePreview;
    },

    getLayerSubtitle(layer) {
      return layer === 'overlay' ? this.overlayCurrentSubtitle : this.currentSubtitle;
    },

    setLayerSubtitle(layer, subtitle) {
      if (layer === 'overlay') this.overlayCurrentSubtitle = subtitle;
      else this.currentSubtitle = subtitle;
    },

    getLayerFade(layer) {
      return layer === 'overlay' ? this.overlayCurrentFade : this.currentFade;
    },

    setLayerFade(layer, fade) {
      if (layer === 'overlay') this.overlayCurrentFade = fade;
      else this.currentFade = fade;
    },

    getFocusedObjectId(layer) {
      return layer === 'overlay' ? this.focusedOverlayObjectId : this.focusedBaseObjectId;
    },

    setFocusedObjectId(layer, objectId) {
      const numericId = Number(objectId);
      const nextId = Number.isFinite(numericId) && numericId > 0 ? numericId : null;
      if (layer === 'overlay') this.focusedOverlayObjectId = nextId;
      else this.focusedBaseObjectId = nextId;
      this.getLayerPreviewElement(layer)?.setFocusedObjectId(nextId);
    },

    getTargetableObjects(layer) {
      const previewData = this.getLayerPreviewData(layer);
      const runtimeState = this.getLayerRuntimeState(layer);
      return [...(previewData?.objects ?? [])]
        .filter(object => {
          const objectState = runtimeState?.objects?.[object.id];
          return (
            object.keyboard_target_enabled
            && objectState?.visible !== false
            && objectState?.enabled !== false
          );
        })
        .sort((left, right) => (
          Number(left.sort_order ?? 0) - Number(right.sort_order ?? 0)
          || Number(left.id) - Number(right.id)
        ));
    },

    syncKeyboardFocusState(layer) {
      const targetableObjects = this.getTargetableObjects(layer);
      const focusedObjectId = this.getFocusedObjectId(layer);
      if (!focusedObjectId) {
        this.setFocusedObjectId(layer, null);
        return;
      }
      if (!targetableObjects.some(object => Number(object.id) === Number(focusedObjectId))) {
        this.setFocusedObjectId(layer, null);
      } else {
        this.setFocusedObjectId(layer, focusedObjectId);
      }
    },

    async moveKeyboardFocus(layer, direction) {
      const objects = this.getTargetableObjects(layer);
      if (!objects.length) return;
      const currentId = this.getFocusedObjectId(layer);
      let nextIndex = direction > 0 ? 0 : objects.length - 1;
      if (currentId) {
        const currentIndex = objects.findIndex(object => Number(object.id) === Number(currentId));
        if (currentIndex >= 0) {
          nextIndex = (currentIndex + direction + objects.length) % objects.length;
        }
      }
      await this.updateKeyboardFocus(layer, objects[nextIndex]?.id ?? null);
    },

    async updateKeyboardFocus(layer, nextObjectId) {
      const previousObjectId = this.getFocusedObjectId(layer);
      const normalizedNext = Number(nextObjectId) || null;
      if (previousObjectId === normalizedNext) {
        this.setFocusedObjectId(layer, normalizedNext);
        return;
      }
      this.setFocusedObjectId(layer, normalizedNext);
      if (previousObjectId) {
        await this.executeMatchingInteractionsForLayer(
          layer,
          interaction => (
            interaction.trigger?.type === 'object_mouseout'
            && Number(interaction.trigger?.object_id) === Number(previousObjectId)
          ),
          {reason: 'object_mouseout', objectId: Number(previousObjectId), keyboardDriven: true}
        );
      }
      if (normalizedNext) {
        await this.executeMatchingInteractionsForLayer(
          layer,
          interaction => (
            interaction.trigger?.type === 'object_mouseover'
            && Number(interaction.trigger?.object_id) === Number(normalizedNext)
          ),
          {reason: 'object_mouseover', objectId: Number(normalizedNext), keyboardDriven: true}
        );
      }
    },

    async configurePreview() {
      if (!this.basePreview || !this.previewData) return;
      await this.basePreview.configure({
        ...this.previewData,
        showBackground: this.showBackground
      });
      this.pushRuntimeToPreview('base');
      this.syncSubtitleOverlay('base');
      this.syncFadeOverlay('base');
      await this.configureOverlayPreview();
    },

    async configureOverlayPreview() {
      const active = Boolean(this.overlayPreviewData && this.overlayPreview);
      if (this.overlayShell) {
        this.overlayShell.classList.toggle('is-hidden', !active);
      }
      if (!active) {
        this.syncOverlayPresentation();
        this.syncFadeOverlay('overlay');
        this.syncSubtitleOverlay('overlay');
        return;
      }
      await this.overlayPreview.configure({
        ...this.overlayPreviewData,
        showBackground: true,
        transparentStage: true
      });
      this.pushRuntimeToPreview('overlay');
      this.syncOverlayPresentation();
      this.syncSubtitleOverlay('overlay');
      this.syncFadeOverlay('overlay');
    },

    pushRuntimeToPreview(layer) {
      const preview = this.getLayerPreviewElement(layer);
      const runtimeState = this.getLayerRuntimeState(layer);
      if (!preview) return;
      preview.applyRuntimeState(runtimeState?.objects ?? {});
      this.syncKeyboardFocusState(layer);
    },

    async refreshView() {
      app.refresh();
      await Promise.resolve();
      this.captureDom();
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.root, 'submit', event => this.onSubmit(event));
      this.bindPreviewEvents();
      await this.configurePreview();
      this.syncRuntimePanels();
    },

    syncRuntimePanels() {
      const objectsRoot = this.root?.querySelector('[data-preview-objects]');
      if (objectsRoot) objectsRoot.innerHTML = renderPreviewObjects(this.previewObjects);
      const variablesRoot = this.root?.querySelector('[data-preview-variables]');
      if (variablesRoot) variablesRoot.innerHTML = renderPreviewVariables(this.runtimeVariables);
      this.syncSubtitleOverlay('base');
      this.syncFadeOverlay('base');
      this.syncOverlayPresentation();
      this.syncSubtitleOverlay('overlay');
      this.syncFadeOverlay('overlay');
    },

    syncSubtitleOverlay(layer) {
      this.getLayerPreviewElement(layer)?.setSubtitle?.(this.getLayerSubtitle(layer));
    },

    syncFadeOverlay(layer) {
      const fadeRoot = this.root?.querySelector(`[data-preview-fade="${layer}"]`);
      if (!fadeRoot) return;
      const fade = this.getLayerFade(layer) ?? {opacity: 0, color: '#000000'};
      fadeRoot.style.background = fade.color || '#000000';
      fadeRoot.style.opacity = String(Math.max(0, Math.min(1, Number(fade.opacity) || 0)));
    },

    syncOverlayPresentation() {
      const opacity = Math.max(0, Math.min(1, Number(this.overlayPresentationOpacity) || 0));
      if (this.overlayBackdrop) {
        this.overlayBackdrop.style.opacity = String(opacity);
      }
      if (this.overlayFrame) {
        this.overlayFrame.style.opacity = String(opacity);
      }
    },

    setOverlayPresentationOpacity(opacity) {
      this.overlayPresentationOpacity = Math.max(0, Math.min(1, Number(opacity) || 0));
      this.syncOverlayPresentation();
      this.syncContinuousAudioState();
    },

    syncContinuousAudioState() {
      const settings = this.getLanguageSettings();
      previewAudioRuntime.setVolumes({
        bgmVolume: volumeForChannel(settings.masterVolume, settings.musicVolume),
        sfxVolume: volumeForChannel(settings.masterVolume, settings.sfxVolume)
      });
      previewAudioRuntime.setDuckFactor(combinedAudioDuckFactor(this));
      const adjustedVolume = this.activeAudioBaseVolume * combinedAudioDuckFactor(this);
      for (const audio of this.activeAudio) {
        audio.volume = Math.max(0, Math.min(1, adjustedVolume));
      }
    },

    setStatus(message) {
      this.status = message;
      const status = this.root?.querySelector('[data-preview-status]');
      if (status) status.textContent = message;
    },

    async reloadRuntime({rerunSceneEnter}) {
      this.executionVersion += 1;
      this.stopMediaPlayback();
      invalidatePreviewDataCache(this.sceneId);
      await this.refreshData();
      await this.refreshView();
      if (rerunSceneEnter) {
        await this.runSceneEnterActions();
      }
    },

    async resetRuntime() {
      this.executionVersion += 1;
      this.stopMediaPlayback();
      this.runtimeState = cloneRuntimeState(this.runtimeSnapshot);
      this.currentSubtitle = null;
      this.currentFade = null;
      this.clearOverlayState();
      this.refreshInspectorState();
      this.basePreview?.stop();
      this.overlayPreview?.stop();
      this.pushRuntimeToPreview('base');
      await this.configureOverlayPreview();
      this.syncSubtitleOverlay('base');
      this.syncFadeOverlay('base');
    },

    stopMediaPlayback() {
      this.subtitleToken += 1;
      this.audioPlaybackToken += 1;
      this.currentSubtitle = null;
      this.overlayCurrentSubtitle = null;
      for (const audio of this.activeAudio) {
        audio.pause();
        audio.src = '';
      }
      this.activeAudio = [];
      this.activeAudioBaseVolume = 1;
      this.syncSubtitleOverlay('base');
      this.syncSubtitleOverlay('overlay');
    },

    resetNonVolumeVariables() {
      this.stopMediaPlayback();
      const snapshotVariables = this.runtimeSnapshot?.variables ?? {};
      const runtimeVariables = this.runtimeState?.variables ?? {};
      for (const [variableId, variable] of Object.entries(runtimeVariables)) {
        const snapshot = snapshotVariables[variableId];
        if (!snapshot) continue;
        if (isVolumeVariable(variable.name)) continue;
        variable.value = structuredClone(snapshot.value);
      }
      this.refreshInspectorState();
    },

    async runSceneEnterActions() {
      await this.executeMatchingInteractionsForLayer(
        'base',
        interaction => interaction.trigger?.type === 'scene_enter',
        {reason: 'scene_enter'}
      );
    },

    async runSceneExitActions() {
      await this.executeMatchingInteractionsForLayer(
        'base',
        interaction => interaction.trigger?.type === 'scene_exit',
        {reason: 'scene_exit', targetSceneId: this.pendingSceneTransitionTarget}
      );
    },

    async onClick(event) {
      const refreshButton = event.target.closest('[data-action="refresh-preview"]');
      if (refreshButton) {
        this.setStatus('Refreshing preview...');
        await this.reloadRuntime({rerunSceneEnter: true});
        this.setStatus('');
        return;
      }

      const playButton = event.target.closest('[data-action="play-animation"]');
      if (playButton) {
        const objectId = Number(playButton.dataset.objectId);
        const animationId = Number(playButton.dataset.animationId);
        await this.executeAnimationPreview(this.getActiveLayerName(), objectId, animationId);
        return;
      }

      const resetButton = event.target.closest('[data-action="reset-preview"]');
      if (resetButton) {
        await this.resetRuntime();
        this.setStatus('Preview reset.');
        return;
      }

      const resetVariablesButton = event.target.closest('[data-action="reset-preview-variables"]');
      if (resetVariablesButton) {
        this.resetNonVolumeVariables();
        this.setStatus('Global variables reset.');
        return;
      }

      const toggleBackgroundButton = event.target.closest('[data-action="toggle-background"]');
      if (toggleBackgroundButton) {
        this.showBackground = !this.showBackground;
        await this.refreshView();
      }
    },

    async onSubmit(event) {
      const sceneJumpForm = event.target.closest('[data-scene-jump-form]');
      if (!sceneJumpForm) return;
      event.preventDefault();
      const formData = new FormData(sceneJumpForm);
      const targetSceneId = Number(formData.get('scene_id'));
      if (!targetSceneId || targetSceneId === this.sceneId) return;
      previewRouteTransitionInFlight = true;
      app.goto(`/preview/${targetSceneId}`);
    },

    async onWindowKeyDown(event) {
      if (event.defaultPrevented || event.repeat || isEditableTarget(event.target)) return;
      const keyCode = normalizeEventKeyCode(event);
      if (!keyCode) return;

      if (keyCode === 'Escape' && this.overlayPreviewData) {
        event.preventDefault();
        await this.closeOverlayScene();
        return;
      }

      const overlayBinding = (this.previewData?.overlay_bindings ?? []).find(
        binding => binding.key_code === keyCode
      );
      if (overlayBinding) {
        event.preventDefault();
        if (Number(this.overlayPreviewData?.id) === Number(overlayBinding.overlay_scene_id)) {
          await this.closeOverlayScene();
        } else if (this.overlayPreviewData) {
          await this.changeOverlayScene(overlayBinding.overlay_scene_id);
        } else {
          await this.openOverlayScene(overlayBinding.overlay_scene_id);
        }
        return;
      }

      const layer = this.getActiveLayerName();
      if (keyCode === 'Tab') {
        event.preventDefault();
        await this.moveKeyboardFocus(layer, event.shiftKey ? -1 : 1);
        return;
      }
      if (['ArrowUp', 'ArrowLeft'].includes(keyCode)) {
        event.preventDefault();
        await this.moveKeyboardFocus(layer, -1);
        return;
      }
      if (['ArrowDown', 'ArrowRight'].includes(keyCode)) {
        event.preventDefault();
        await this.moveKeyboardFocus(layer, 1);
        return;
      }
      if (['Enter', 'Space'].includes(keyCode)) {
        const focusedObjectId = this.getFocusedObjectId(layer);
        if (focusedObjectId) {
          event.preventDefault();
          await this.triggerObjectClick(layer, focusedObjectId, {keyboardDriven: true});
          return;
        }
      }
      await this.executeMatchingInteractionsForLayer(
        layer,
        interaction => (
          interaction.trigger?.type === 'key_press'
          && interaction.trigger?.key_code === keyCode
        ),
        {reason: 'key_press', keyCode}
      );
    },

    async onPreviewObjectClick(event, layer) {
      if (layer === 'base' && this.overlayPreviewData) return;
      if (layer === 'overlay' && !this.overlayPreviewData) return;
      const objectId = Number(event.detail?.objectId);
      if (!objectId) return;
      await this.triggerObjectClick(layer, objectId);
    },

    async triggerObjectClick(layer, objectId, metadata = {}) {
      const state = this.getLayerRuntimeState(layer)?.objects?.[objectId];
      if (!state?.enabled || !state?.visible) return;
      await this.executeMatchingInteractionsForLayer(
        layer,
        interaction => (
          interaction.trigger?.type === 'object_click'
          && Number(interaction.trigger?.object_id) === Number(objectId)
        ),
        {reason: 'object_click', objectId: Number(objectId), ...metadata}
      );
    },

    async onPreviewObjectMouseover(event, layer) {
      if (layer === 'base' && this.overlayPreviewData) return;
      if (layer === 'overlay' && !this.overlayPreviewData) return;
      const objectId = Number(event.detail?.objectId);
      if (!objectId) return;
      const state = this.getLayerRuntimeState(layer)?.objects?.[objectId];
      if (!state?.enabled || !state?.visible) return;
      await this.executeMatchingInteractionsForLayer(
        layer,
        interaction => (
          interaction.trigger?.type === 'object_mouseover'
          && Number(interaction.trigger?.object_id) === objectId
        ),
        {reason: 'object_mouseover', objectId}
      );
    },

    async onPreviewObjectMouseout(event, layer) {
      if (layer === 'base' && this.overlayPreviewData) return;
      if (layer === 'overlay' && !this.overlayPreviewData) return;
      const objectId = Number(event.detail?.objectId);
      if (!objectId) return;
      await this.executeMatchingInteractionsForLayer(
        layer,
        interaction => (
          interaction.trigger?.type === 'object_mouseout'
          && Number(interaction.trigger?.object_id) === objectId
        ),
        {reason: 'object_mouseout', objectId}
      );
    },

    onPreviewError(event) {
      const message = event.detail?.message || 'Preview could not load one or more images.';
      this.setStatus(message);
    },

    async executeAnimationPreview(layer, objectId, animationId) {
      const version = ++this.executionVersion;
      this.setStatus('Playing animation...');
      try {
        await this.getLayerPreviewElement(layer)?.playAnimation(objectId, animationId, {mode: 'immediate'});
        if (version !== this.executionVersion) return;
        const render = getAnimationLastRender(this.getLayerPreviewData(layer), objectId, animationId);
        const runtimeState = this.getLayerRuntimeState(layer);
        if (render && runtimeState?.objects?.[objectId]) {
          runtimeState.objects[objectId].render = render;
          this.pushRuntimeToPreview(layer);
        }
        this.refreshInspectorState();
      } finally {
        if (version === this.executionVersion) this.setStatus('');
      }
    },

    async executeMatchingInteractionsForLayer(layer, predicate, metadata = {}) {
      const interactions = (this.getLayerPreviewData(layer)?.interactions ?? []).filter(predicate);
      if (!interactions.length) return;
      const chainState = {remaining: MAX_CHAINED_INTERACTIONS};
      await this.executeInteractions(layer, interactions, metadata, chainState);
    },

    async executeInteractions(layer, interactions, metadata = {}, chainState = {remaining: MAX_CHAINED_INTERACTIONS}) {
      const version = this.executionVersion;
      for (const interaction of interactions) {
        if (version !== this.executionVersion) return;
        if (!interaction?.enabled) continue;
        if (chainState.remaining <= 0) {
          this.setStatus('Stopped preview actions after hitting the interaction safety limit.');
          return;
        }
        chainState.remaining -= 1;
        await this.executeActionTree(layer, interaction.action_tree ?? [], metadata, chainState, version);
      }
    },

    async executeActionTree(layer, steps, metadata, chainState, version) {
      for (const step of steps ?? []) {
        if (version !== this.executionVersion) return;
        await this.executeActionStep(layer, step, metadata, chainState, version);
      }
    },

    async executeActionStep(layer, step, metadata, chainState, version) {
      if (!step?.type || version !== this.executionVersion) return;
      const previewData = this.getLayerPreviewData(layer);
      const runtimeState = this.getLayerRuntimeState(layer);
      const preview = this.getLayerPreviewElement(layer);

      if (step.type === 'play_animation') {
        const runPromise = preview?.playAnimation(step.target_object_id, step.animation_id, {
          mode: step.mode ?? 'queued'
        });
        if (step.wait !== 'continue') await runPromise;
        else void runPromise;
        const render = getAnimationLastRender(previewData, step.target_object_id, step.animation_id);
        if (render && runtimeState?.objects?.[step.target_object_id]) {
          runtimeState.objects[step.target_object_id].render = render;
          this.pushRuntimeToPreview(layer);
        }
        return;
      }

      if (step.type === 'go_to_frame') {
        const render = getObjectRenderForFrame(previewData, step.target_object_id, step.frame_index);
        if (runtimeState?.objects?.[step.target_object_id]) {
          runtimeState.objects[step.target_object_id].render = render;
        }
        preview?.setObjectRender?.(step.target_object_id, render);
        this.refreshInspectorState();
        return;
      }

      if (step.type === 'set_object_property') {
        const objectState = runtimeState?.objects?.[step.target_object_id];
        if (!objectState) return;
        if (step.property === 'visible') objectState.visible = Boolean(step.value);
        if (step.property === 'enabled') objectState.enabled = Boolean(step.value);
        if (step.property === 'label') objectState.label = String(step.value ?? '');
        this.refreshInspectorState();
        this.pushRuntimeToPreview(layer);
        return;
      }

      if (step.type === 'set_variable') {
        const variableState = this.runtimeState?.variables?.[step.variable_id];
        if (!variableState) return;
        variableState.value = step.value;
        this.refreshInspectorState();
        await this.triggerVariableChanged(layer, step.variable_id, chainState);
        return;
      }

      if (step.type === 'increment_variable') {
        const variableState = this.runtimeState?.variables?.[step.variable_id];
        if (!variableState) return;
        variableState.value = Number(variableState.value || 0) + Number(step.amount || 0);
        this.refreshInspectorState();
        await this.triggerVariableChanged(layer, step.variable_id, chainState);
        return;
      }

      if (step.type === 'toggle_variable') {
        const variableState = this.runtimeState?.variables?.[step.variable_id];
        if (!variableState) return;
        variableState.value = !Boolean(variableState.value);
        this.refreshInspectorState();
        await this.triggerVariableChanged(layer, step.variable_id, chainState);
        return;
      }

      if (step.type === 'show_subtitle') {
        const line = this.pickScriptLine(layer, step.script_line_ids);
        if (!line) return;
        const subtitle = buildSubtitlePayload(line, this.getLanguageSettings());
        if (!subtitle) return;
        const runPromise = this.showSubtitle(layer, subtitle, step.duration_seconds, version);
        if (step.wait !== 'continue') await runPromise;
        else void runPromise;
        return;
      }

      if (step.type === 'play_audio') {
        const line = this.pickScriptLine(layer, step.script_line_ids);
        if (!line) return;
        const runPromise = this.playAudioForLine(layer, line, version);
        if (step.wait !== 'continue') await runPromise;
        else void runPromise;
        return;
      }

      if (step.type === 'crossfade_bgm') {
        const asset = this.findAudioAsset(layer, step.audio_asset_id, 'bgm');
        if (!asset) return;
        const settings = this.getLanguageSettings();
        const runPromise = previewAudioRuntime.crossfadeBgm({
          audioAssetId: asset.id,
          audioUrl: audioAssetUrl(asset.id),
          volume: volumeForChannel(settings.masterVolume, settings.musicVolume),
          durationSeconds: step.duration_seconds
        });
        if (step.wait !== 'continue') await runPromise;
        else void runPromise;
        return;
      }

      if (step.type === 'play_sfx') {
        const asset = this.findAudioAsset(layer, step.audio_asset_id, 'sfx');
        if (!asset) return;
        const settings = this.getLanguageSettings();
        const runPromise = previewAudioRuntime.playSfx({
          audioUrl: audioAssetUrl(asset.id),
          volume: volumeForChannel(settings.masterVolume, settings.sfxVolume)
        });
        if (step.wait !== 'continue') await runPromise;
        else void runPromise;
        return;
      }

      if (step.type === 'if_variable') {
        const variableState = this.runtimeState?.variables?.[step.variable_id];
        if (!variableState) return;
        const matches = compareVariable(variableState.value, step.operator, step.value);
        const branch = matches ? step.then_steps : step.else_steps;
        await this.executeActionTree(layer, branch ?? [], metadata, chainState, version);
        return;
      }

      if (step.type === 'delay') {
        await wait(step.duration_seconds);
        return;
      }

      if (step.type === 'fade_out' || step.type === 'fade_in') {
        const runPromise = this.runFade(layer, step, version);
        if (step.wait !== 'continue') await runPromise;
        else void runPromise;
        return;
      }

      if (step.type === 'change_scene') {
        if (layer === 'overlay' && this.overlayPreviewData) {
          await this.closeOverlayScene();
        }
        await this.changeScene(step.scene_id);
        return;
      }

      if (step.type === 'open_overlay_scene') {
        await this.openOverlayScene(step.scene_id);
        return;
      }

      if (step.type === 'close_overlay_scene') {
        await this.closeOverlayScene();
        return;
      }

      if (step.type === 'change_overlay_scene') {
        await this.changeOverlayScene(step.scene_id);
      }
    },

    async runFade(layer, step, version) {
      const targetOpacity = step.type === 'fade_out' ? 1 : 0;
      const color = normalizeFadeColor(step.color);
      const currentFade = this.getLayerFade(layer);
      this.setLayerFade(layer, {
        color,
        opacity: Number(currentFade?.opacity ?? (step.type === 'fade_out' ? 0 : 1)),
        affectAudio: Boolean(step.affect_audio)
      });
      this.syncFadeOverlay(layer);
      await animateFade(this, {
        layer,
        fromOpacity: this.getLayerFade(layer)?.opacity ?? 0,
        toOpacity: targetOpacity,
        color,
        durationSeconds: step.duration_seconds,
        affectAudio: Boolean(step.affect_audio),
        version
      });
      if (version !== this.executionVersion) return;
      if (targetOpacity <= 0) this.setLayerFade(layer, null);
      else this.setLayerFade(layer, {color, opacity: 1, affectAudio: Boolean(step.affect_audio)});
      this.syncContinuousAudioState();
      this.syncFadeOverlay(layer);
    },

    async openOverlayScene(nextOverlaySceneId) {
      const targetSceneId = Number(nextOverlaySceneId);
      if (!targetSceneId) return;
      if (Number(this.overlayPreviewData?.id) === targetSceneId) return;
      if (this.overlayPreviewData) {
        await this.changeOverlayScene(targetSceneId);
        return;
      }
      this.executionVersion += 1;
      this.stopMediaPlayback();
      this.setStatus(`Opening overlay scene ${targetSceneId}...`);
      try {
        const overlaySettings = this.getGlobalOverlaySettings();
        this.openingOverlaySceneId = targetSceneId;
        this.overlayPreviewData = await fetchPreviewData(targetSceneId);
        this.overlayRuntimeSnapshot = createRuntimeSnapshot(this.overlayPreviewData);
        this.overlayRuntimeState = createOverlayRuntimeState(this.overlayRuntimeSnapshot, this.runtimeState?.variables ?? {});
        this.overlayCurrentSubtitle = null;
        this.overlayCurrentFade = null;
        this.overlayPresentationOpacity = 0;
        await this.refreshView();
        await animateOverlayOpacity(this, {
          fromOpacity: 0,
          toOpacity: 1,
          durationSeconds: overlaySettings.overlayOpenDurationSeconds,
          version: this.executionVersion
        });
      } finally {
        this.openingOverlaySceneId = null;
        this.setStatus('');
      }
    },

    async closeOverlayScene() {
      if (!this.overlayPreviewData) return;
      const overlaySettings = this.getGlobalOverlaySettings();
      await animateOverlayOpacity(this, {
        fromOpacity: this.overlayPresentationOpacity,
        toOpacity: 0,
        durationSeconds: overlaySettings.overlayCloseDurationSeconds,
        version: this.executionVersion
      });
      this.executionVersion += 1;
      this.stopMediaPlayback();
      this.overlayPreview?.stop();
      this.clearOverlayState();
      this.refreshInspectorState();
      await this.refreshView();
      this.setStatus('');
    },

    async changeOverlayScene(nextOverlaySceneId) {
      const targetSceneId = Number(nextOverlaySceneId);
      if (!targetSceneId) return;
      if (!this.overlayPreviewData) {
        await this.openOverlayScene(targetSceneId);
        return;
      }
      if (Number(this.overlayPreviewData.id) === targetSceneId) return;
      await this.closeOverlayScene();
      await this.openOverlayScene(targetSceneId);
    },

    async changeScene(nextSceneId) {
      const targetSceneId = Number(nextSceneId);
      if (!targetSceneId) return;
      if (this.overlayPreviewData) {
        await this.closeOverlayScene();
      }
      if (this.runningSceneExit || this.isTransitioningScene) {
        this.pendingSceneTransitionTarget = targetSceneId;
        return;
      }
      if (targetSceneId === this.sceneId) return;
      this.isTransitioningScene = true;
      this.pendingSceneTransitionTarget = targetSceneId;
      try {
        this.runningSceneExit = true;
        await this.runSceneExitActions();
      } finally {
        this.runningSceneExit = false;
      }
      const resolvedTargetSceneId = Number(this.pendingSceneTransitionTarget);
      this.pendingSceneTransitionTarget = null;
      this.isTransitioningScene = false;
      if (!resolvedTargetSceneId || resolvedTargetSceneId === this.sceneId) return;
      previewSceneCarryover = {
        sceneId: resolvedTargetSceneId,
        fadeState: this.currentFade ? structuredClone(this.currentFade) : null,
        variables: Object.fromEntries(
          Object.entries(this.runtimeState?.variables ?? {}).map(([variableId, variable]) => [
            variableId,
            structuredClone(variable.value)
          ])
        )
      };
      previewRouteTransitionInFlight = true;
      this.executionVersion += 1;
      this.stopMediaPlayback();
      this.setStatus(`Changing to scene ${resolvedTargetSceneId}...`);
      app.goto(`/preview/${resolvedTargetSceneId}`);
    },

    scheduleConnectedScenePreload() {
      if (this.preloadTimer) window.clearTimeout(this.preloadTimer);
      const targetSceneIds = collectConnectedSceneIds(this.previewData, this.sceneId);
      if (!targetSceneIds.length) return;
      this.preloadTimer = window.setTimeout(() => {
        this.preloadTimer = null;
        void preloadConnectedScenes(targetSceneIds);
      }, 150);
    },

    async triggerVariableChanged(layer, variableId, chainState) {
      await this.executeInteractions(
        layer,
        (this.getLayerPreviewData(layer)?.interactions ?? []).filter(interaction => (
          interaction.trigger?.type === 'variable_changed'
          && Number(interaction.trigger?.variable_id) === Number(variableId)
        )),
        {reason: 'variable_changed', variableId},
        chainState
      );
    },

    getLanguageSettings() {
      const variables = this.runtimeState?.variables ?? {};
      return {
        primaryLanguage: normalizeLanguageValue(findVariableByName(variables, 'primary_language')?.value, DEFAULT_PRIMARY_LANGUAGE),
        secondaryLanguage: normalizeLanguageValue(findVariableByName(variables, 'secondary_language')?.value, DEFAULT_SECONDARY_LANGUAGE),
        translationMode: normalizeTranslationMode(findVariableByName(variables, 'translation_mode')?.value, DEFAULT_TRANSLATION_MODE),
        masterVolume: normalizeVolumeValue(findVariableByName(variables, 'master_volume')?.value, 5),
        narratorVolume: normalizeVolumeValue(findVariableByName(variables, 'narrator_volume')?.value, 5),
        musicVolume: normalizeVolumeValue(findVariableByName(variables, 'music_volume')?.value, 5),
        sfxVolume: normalizeVolumeValue(findVariableByName(variables, 'sfx_volume')?.value, 5)
      };
    },

    getGlobalOverlaySettings() {
      return {
        overlayOpenDurationSeconds: Number(this.previewData?.global_settings?.overlay_open_duration_seconds || 0.22),
        overlayCloseDurationSeconds: Number(this.previewData?.global_settings?.overlay_close_duration_seconds || 0.18),
        overlayAffectAudio: Boolean(this.previewData?.global_settings?.overlay_affect_audio)
      };
    },

    findAudioAsset(layer, audioAssetId, expectedKind) {
      return (this.getLayerPreviewData(layer)?.audio_assets ?? []).find(asset => (
        Number(asset.id) === Number(audioAssetId)
        && (!expectedKind || asset.kind === expectedKind)
      )) ?? null;
    },

    pickScriptLine(layer, lineIds) {
      const validIds = (lineIds ?? []).map(Number).filter(Boolean);
      if (!validIds.length) return null;
      const randomId = validIds[Math.floor(Math.random() * validIds.length)];
      return (this.getLayerPreviewData(layer)?.script_lines ?? []).find(
        line => Number(line.line_id) === randomId
      ) ?? null;
    },

    async showSubtitle(layer, subtitle, durationSeconds, version) {
      const token = ++this.subtitleToken;
      this.setLayerSubtitle(layer, subtitle);
      this.syncSubtitleOverlay(layer);
      await wait(durationSeconds);
      await waitMilliseconds(SUBTITLE_LINGER_MS);
      if (token !== this.subtitleToken || version !== this.executionVersion) return;
      this.setLayerSubtitle(layer, null);
      this.syncSubtitleOverlay(layer);
    },

    async playAudioForLine(layer, line, version) {
      const playbackToken = ++this.audioPlaybackToken;
      this.stopActiveAudio();
      const settings = this.getLanguageSettings();
      const subtitle = buildSubtitlePayload(line, settings);
      const sequence = buildAudioSequence(line, settings);
      if (subtitle) {
        this.setLayerSubtitle(layer, subtitle);
        this.syncSubtitleOverlay(layer);
      }
      try {
        if (!sequence.length) return;
        for (const item of sequence) {
          if (playbackToken !== this.audioPlaybackToken || version !== this.executionVersion) return;
          await this.playAudioClip(
            item.audioUrl,
            volumeForChannel(settings.masterVolume, settings.narratorVolume),
            playbackToken,
            version
          );
          if (sequence.length > 1 && item !== sequence[sequence.length - 1]) {
            await waitMilliseconds(SEQUENTIAL_AUDIO_GAP_MS);
          }
        }
      } finally {
        if (playbackToken === this.audioPlaybackToken && version === this.executionVersion) {
          await waitMilliseconds(SUBTITLE_LINGER_MS);
          this.setLayerSubtitle(layer, null);
          this.syncSubtitleOverlay(layer);
        }
      }
    },

    stopActiveAudio() {
      for (const audio of this.activeAudio) {
        audio.pause();
        audio.src = '';
      }
      this.activeAudio = [];
      this.activeAudioBaseVolume = 1;
    },

    async playAudioClip(audioUrl, volume, playbackToken, version) {
      if (!audioUrl) return;
      const audio = new Audio(audioUrl);
      this.activeAudioBaseVolume = volume;
      audio.volume = Math.max(0, Math.min(1, volume * combinedAudioDuckFactor(this)));
      this.activeAudio = [audio];
      await new Promise(resolve => {
        let finished = false;
        const finish = () => {
          if (finished) return;
          finished = true;
          audio.removeEventListener('ended', onEnded);
          audio.removeEventListener('error', onError);
          resolve();
        };
        const onEnded = () => finish();
        const onError = () => finish();
        audio.addEventListener('ended', onEnded, {once: true});
        audio.addEventListener('error', onError, {once: true});
        const playPromise = audio.play();
        if (playPromise?.catch) {
          playPromise.catch(() => finish());
        }
      });
      if (playbackToken !== this.audioPlaybackToken || version !== this.executionVersion) return;
      this.activeAudio = [];
    }
  };

  await controller.refreshData();
  return controller;
};

function createRuntimeSnapshot(previewData) {
  return {
    objects: Object.fromEntries(
      (previewData?.objects ?? []).map(object => [
        object.id,
        {
          id: object.id,
          name: object.name,
          label: object.label || object.name,
          visible: object.visible !== false,
          enabled: object.enabled !== false,
          render: object.default_render ?? null
        }
      ])
    ),
    variables: Object.fromEntries(
      (previewData?.variables ?? []).map(variable => [
        variable.id,
        {
          id: variable.id,
          name: variable.name,
          value_type: variable.value_type,
          value: structuredClone(variable.default_value)
        }
      ])
    )
  };
}

function createOverlayRuntimeState(snapshot, sharedVariables) {
  const nextState = cloneRuntimeState(snapshot);
  nextState.variables = sharedVariables ?? {};
  return nextState;
}

function cloneRuntimeState(snapshot) {
  return structuredClone(snapshot ?? {objects: {}, variables: {}});
}

function getAnimationLastRender(previewData, objectId, animationId) {
  const object = (previewData?.objects ?? []).find(item => Number(item.id) === Number(objectId));
  const animation = object?.animations?.find(item => Number(item.id) === Number(animationId));
  const frames = animation?.frames ?? [];
  for (let index = frames.length - 1; index >= 0; index -= 1) {
    if (frames[index]?.render) return frames[index].render;
  }
  return object?.default_render ?? null;
}

function getObjectRenderForFrame(previewData, objectId, frameIndex) {
  const object = (previewData?.objects ?? []).find(item => Number(item.id) === Number(objectId));
  if (!object) return null;
  const numericFrameIndex = Number(frameIndex);
  const directRender = (object.frame_renders ?? []).find(
    render => Number(render?.frame_index) === numericFrameIndex
  );
  if (directRender) return directRender;
  return object.default_render ?? null;
}

function compareVariable(leftValue, operator, rightValue) {
  if (operator === 'not_equals') return leftValue !== rightValue;
  if (operator === 'greater_than') return Number(leftValue) > Number(rightValue);
  if (operator === 'less_than') return Number(leftValue) < Number(rightValue);
  if (operator === 'greater_or_equal') return Number(leftValue) >= Number(rightValue);
  if (operator === 'less_or_equal') return Number(leftValue) <= Number(rightValue);
  return leftValue === rightValue;
}

function findVariableByName(variables, name) {
  return Object.values(variables ?? {}).find(variable => variable.name === name) ?? null;
}

function normalizeLanguageValue(value, fallback) {
  const trimmed = String(value ?? '').trim().toLowerCase();
  return trimmed || fallback;
}

function normalizeTranslationMode(value, fallback) {
  const trimmed = String(value ?? '').trim().toLowerCase();
  if (['none', 'primary_only', 'secondary_only', 'sequential'].includes(trimmed)) return trimmed;
  return fallback;
}

function normalizeVolumeValue(value, fallback) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return Math.min(10, Math.max(0, numeric));
}

function volumeForChannel(masterVolume, channelVolume) {
  return (masterVolume / 10) * (channelVolume / 10);
}

function isVolumeVariable(name) {
  return String(name ?? '').toLowerCase().endsWith('_volume');
}

function normalizeFadeColor(value) {
  const trimmed = String(value ?? '').trim();
  return trimmed || '#000000';
}

function combinedAudioDuckFactor(controller) {
  let factor = 1;
  for (const fade of [controller.currentFade, controller.overlayCurrentFade]) {
    if (!fade?.affectAudio) continue;
    const opacity = Math.max(0, Math.min(1, Number(fade.opacity) || 0));
    factor = Math.min(factor, 1 - opacity);
  }
  if (controller.overlayPreviewData && controller.getGlobalOverlaySettings().overlayAffectAudio) {
    factor = Math.min(factor, OVERLAY_OPEN_DUCK_FACTOR);
  }
  return Math.max(0, Math.min(1, factor));
}

async function animateFade(controller, {
  layer,
  fromOpacity,
  toOpacity,
  color,
  durationSeconds,
  affectAudio,
  version
}) {
  const durationMs = Math.max(1, Math.round(Number(durationSeconds || 0) * 1000));
  const start = performance.now();
  const updateFrame = () => {
    const elapsed = performance.now() - start;
    const progress = Math.min(1, elapsed / durationMs);
    const opacity = fromOpacity + ((toOpacity - fromOpacity) * progress);
    controller.setLayerFade(layer, {color, opacity, affectAudio});
    controller.syncContinuousAudioState();
    controller.syncFadeOverlay(layer);
    return progress;
  };

  while (version === controller.executionVersion) {
    const progress = updateFrame();
    if (progress >= 1) break;
    await waitMilliseconds(FADE_FRAME_MS);
  }
}

async function animateOverlayOpacity(controller, {
  fromOpacity,
  toOpacity,
  durationSeconds,
  version
}) {
  const durationMs = Math.max(1, Math.round(Number(durationSeconds || 0) * 1000));
  const start = performance.now();
  const updateFrame = () => {
    const elapsed = performance.now() - start;
    const progress = Math.min(1, elapsed / durationMs);
    const opacity = fromOpacity + ((toOpacity - fromOpacity) * progress);
    controller.setOverlayPresentationOpacity(opacity);
    return progress;
  };

  while (version === controller.executionVersion) {
    const progress = updateFrame();
    if (progress >= 1) break;
    await waitMilliseconds(FADE_FRAME_MS);
  }
}

function buildSubtitlePayload(line, settings) {
  const primaryText = resolveLineText(line, settings.primaryLanguage);
  const secondaryText = resolveLineText(line, settings.secondaryLanguage);
  if (!primaryText && !secondaryText) return null;
  const maxLength = Math.max(primaryText.length, secondaryText.length);
  return {
    primaryText,
    secondaryText,
    sizeClass: subtitleSizeClass(maxLength)
  };
}

function resolveLineText(line, language) {
  if (!line || !language) return '';
  const translation = (line.translations ?? []).find(item => item.language === language && item.text?.trim());
  if (translation?.text?.trim()) return translation.text.trim();
  if (language === 'en' && line.source_text) return String(line.source_text).trim();
  return '';
}

function subtitleSizeClass(maxLength) {
  if (maxLength <= 42) return 'is-large';
  if (maxLength <= 72) return 'is-medium';
  if (maxLength <= 108) return 'is-small';
  return 'is-xsmall';
}

function buildAudioSequence(line, settings) {
  if (settings.translationMode === 'none') return [];
  if (settings.translationMode === 'primary_only') {
    return pickAudioCandidate(line, settings.primaryLanguage);
  }
  if (settings.translationMode === 'secondary_only') {
    return pickAudioCandidate(line, settings.secondaryLanguage);
  }
  return [
    ...pickAudioCandidate(line, settings.primaryLanguage),
    ...pickAudioCandidate(line, settings.secondaryLanguage)
  ];
}

function pickAudioCandidate(line, language) {
  const candidates = (line.audio_candidates ?? [])
    .filter(candidate => candidate.language === language && candidate.relative_path);
  if (!candidates.length) return [];
  const selected = candidates.filter(candidate => candidate.selected);
  const choicePool = selected.length ? selected : [candidates[0]];
  const choice = choicePool[Math.floor(Math.random() * choicePool.length)];
  return choice ? [{audioUrl: scriptAudioCandidateUrl(choice.id)}] : [];
}

function formatRuntimeValue(value) {
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (value == null) return '';
  return String(value);
}

function renderPreviewObjects(objects) {
  return (objects ?? []).map(object => `
    <section class="preview-object-card">
      <div class="preview-object-card__header">
        <strong>${escapeHtml(object.name)}</strong>
        <span>${object.visible ? 'visible' : 'hidden'} · ${object.enabled ? 'enabled' : 'disabled'}</span>
      </div>
      ${object.hasAnimations ? `
        <div class="preview-animation-list">
          ${(object.animations ?? []).map(animation => `
            <button
              class="preview-animation-button"
              type="button"
              data-action="play-animation"
              data-object-id="${object.id}"
              data-animation-id="${animation.id}"
            >
              <strong>${escapeHtml(animation.name)}</strong>
              <span>${animation.frameCount} frames</span>
            </button>
          `).join('')}
        </div>
      ` : '<p class="muted">No saved animations.</p>'}
    </section>
  `).join('');
}

function renderPreviewVariables(variables) {
  return (variables ?? []).map(variable => (
    `<span>${escapeHtml(variable.name)} · ${escapeHtml(variable.valueType)} · ${escapeHtml(variable.valueText)}</span>`
  )).join('');
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function wait(durationSeconds) {
  const milliseconds = Math.max(1, Math.round(Number(durationSeconds || 0) * 1000));
  return waitMilliseconds(milliseconds);
}

function waitMilliseconds(milliseconds) {
  return new Promise(resolve => window.setTimeout(resolve, milliseconds));
}

function normalizeEventKeyCode(event) {
  const code = String(event.code || '').trim();
  return code || '';
}

function isEditableTarget(target) {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return Boolean(target.closest('input, textarea, select, [contenteditable="true"]'));
}

export {PreviewCtrl};

async function fetchPreviewData(sceneId) {
  const numericSceneId = Number(sceneId);
  const cached = previewDataCache.get(numericSceneId);
  if (cached?.data) return cached.data;
  if (cached?.promise) return cached.promise;

  const promise = apiFetch(`/api/scenes/${numericSceneId}/preview-data`)
    .then(data => {
      previewDataCache.set(numericSceneId, {data, promise: Promise.resolve(data)});
      return data;
    })
    .catch(error => {
      previewDataCache.delete(numericSceneId);
      throw error;
    });

  previewDataCache.set(numericSceneId, {data: null, promise});
  return promise;
}

function invalidatePreviewDataCache(sceneId) {
  previewDataCache.delete(Number(sceneId));
}

function collectConnectedSceneIds(previewData, currentSceneId) {
  const targets = new Set();
  for (const binding of previewData?.overlay_bindings ?? []) {
    const overlaySceneId = Number(binding.overlay_scene_id);
    if (overlaySceneId) targets.add(overlaySceneId);
  }
  collectConnectedSceneIdsFromSteps(
    (previewData?.interactions ?? []).flatMap(interaction => interaction.action_tree ?? []),
    targets,
    Number(currentSceneId)
  );
  return [...targets].slice(0, MAX_PRELOADED_CONNECTED_SCENES);
}

function collectConnectedSceneIdsFromSteps(steps, targets, currentSceneId) {
  for (const step of steps ?? []) {
    if (step?.type === 'change_scene') {
      const targetSceneId = Number(step.scene_id);
      if (targetSceneId && targetSceneId !== currentSceneId) targets.add(targetSceneId);
    }
    if (step?.type === 'open_overlay_scene' || step?.type === 'change_overlay_scene') {
      const targetSceneId = Number(step.scene_id);
      if (targetSceneId) targets.add(targetSceneId);
    }
    collectConnectedSceneIdsFromSteps(step?.then_steps ?? [], targets, currentSceneId);
    collectConnectedSceneIdsFromSteps(step?.else_steps ?? [], targets, currentSceneId);
  }
}

async function preloadConnectedScenes(sceneIds) {
  await Promise.all(
    [...new Set(sceneIds)]
      .slice(0, MAX_PRELOADED_CONNECTED_SCENES)
      .map(async sceneId => {
        try {
          const previewData = await fetchPreviewData(sceneId);
          await preloadPreviewAssets(previewData);
        } catch {
          invalidatePreviewDataCache(sceneId);
        }
      })
  );
}
