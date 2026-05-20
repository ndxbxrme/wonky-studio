import {apiFetch, audioAssetUrl, globalSettingsAssetUrl, objectThumbnailUrl, scriptAudioCandidateUrl} from '../api.js';
import {applyStatus} from '../status.js';
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
const VERB_MENU_LONGPRESS_MS = 420;
const VERB_MENU_STAGGER_MS = 30;
const CURSOR_STATE_DEFAULT = 'default';
const CURSOR_STATE_HOVER_INTERACTIVE = 'hover_interactive';
const CURSOR_STATE_BUSY = 'busy';
const CURSOR_STATE_BLOCKED = 'blocked';
const PREVIEW_LOCAL_AUDIO_SETTINGS_KEY = 'wonky-preview-local-audio-settings';
let previewSceneCarryover = null;
let previewRouteTransitionInFlight = false;
const previewDataCache = new Map();
const inventoryBackgroundMetricsCache = new Map();

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
    inventoryItems: [],
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
    viewUnloadHandlers: [],
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
    activeVerbMenu: null,
    verbMenuDismissTimer: null,
    verbMenuAnimationTimer: null,
    verbMenuOpenedAt: 0,
    suppressVerbMenuDismissUntil: 0,
    ignoreNextVerbMenuOutsideClick: false,
    renderedVerbMenuSignature: '',
    inventoryMotion: null,
    inventoryMotionTimer: null,
    heldItemMotion: null,
    heldItemMotionTimer: null,
    heldInventoryGhost: null,
    heldInventoryGhostTimer: null,
    feedbackPulse: null,
    feedbackPulseTimer: null,
    basePreview: null,
    overlayPreview: null,
    overlayShell: null,
    overlayBackdrop: null,
    overlayFrame: null,
    inventoryOverlayShell: null,
    inventoryOverlayBackdrop: null,
    inventoryOverlayFrame: null,
    inventoryStage: null,
    heldInventoryItemRoot: null,
    heldInventoryGhostRoot: null,
    stageRoot: null,
    cursorRoot: null,
    feedbackLayerRoot: null,
    inventoryLayoutVersion: 0,
    loadingScreen: null,
    loadingOverlay: null,
    loadingVisible: true,
    loadingTitle: 'Loading preview',
    loadingDetail: 'Fetching scene data…',
    loadingPercent: 4,
    loadingMeta: 'Preparing scene runtime',
    localMasterVolume: 5,
    localMusicVolume: 5,
    startPromptVisible: false,
    audioUnlocked: false,
    stagePointerInside: false,
    pointerClientX: null,
    pointerClientY: null,
    hoveredBaseObjectId: null,
    hoveredOverlayObjectId: null,
    customCursorStateKey: CURSOR_STATE_DEFAULT,

    async postLoad() {
      this.captureDom();
      this.bindViewEvents();
      this.bind(window, 'keydown', event => {
        this.audioUnlocked = true;
        void this.onWindowKeyDown(event);
      });
      this.bind(window, 'pointerdown', () => {
        this.audioUnlocked = true;
        void previewAudioRuntime.resumePendingBgm();
      });
      this.bind(window, 'pointermove', event => {
        this.syncHeldInventoryItem({clientX: event.clientX, clientY: event.clientY});
        this.updatePreviewPointer(event);
      });
      this.bind(window, 'resize', () => {
        this.syncInventoryOverlay();
      });
      this.bind(window, 'blur', () => this.clearPreviewPointer());
      this.previewSyncCleanup = listenScenePreview(this.sceneId, async () => {
        this.setStatus('Refreshing preview...');
        await this.reloadRuntime({rerunSceneEnter: true});
        this.setStatus('');
      });
      this.setLoadingState({
        visible: true,
        title: 'Loading preview',
        detail: 'Fetching scene data…',
        percent: 4,
        meta: 'Preparing scene runtime'
      });
      await this.configurePreview();
      this.setLoadingState({visible: false});
      await this.waitForPreviewPresentation();
      await this.runStartupSceneEnterActions();
    },

    unload() {
      this.executionVersion += 1;
      this.stopMediaPlayback();
      if (!previewRouteTransitionInFlight) previewAudioRuntime.stopAll();
      if (this.preloadTimer) window.clearTimeout(this.preloadTimer);
      if (this.inventoryMotionTimer) window.clearTimeout(this.inventoryMotionTimer);
      if (this.heldItemMotionTimer) window.clearTimeout(this.heldItemMotionTimer);
      if (this.heldInventoryGhostTimer) window.clearTimeout(this.heldInventoryGhostTimer);
      if (this.feedbackPulseTimer) window.clearTimeout(this.feedbackPulseTimer);
      this.preloadTimer = null;
      this.unloadHandlers.forEach(unload => unload());
      this.unloadHandlers = [];
      this.clearViewBindings();
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
      this.inventoryOverlayShell = this.root?.querySelector('[data-inventory-overlay-shell]') ?? null;
      this.inventoryOverlayBackdrop = this.root?.querySelector('[data-inventory-overlay-backdrop]') ?? null;
      this.inventoryOverlayFrame = this.root?.querySelector('[data-inventory-overlay-frame]') ?? null;
      this.inventoryStage = this.root?.querySelector('[data-inventory-stage]') ?? null;
      this.heldInventoryItemRoot = this.root?.querySelector('[data-held-inventory-item]') ?? null;
      this.heldInventoryGhostRoot = this.root?.querySelector('[data-held-inventory-ghost]') ?? null;
      this.stageRoot = this.root?.querySelector('[data-preview-stage]') ?? null;
      this.cursorRoot = this.root?.querySelector('[data-preview-cursor]') ?? null;
      this.feedbackLayerRoot = this.root?.querySelector('[data-preview-feedback-layer]') ?? null;
      this.verbMenuRoot = this.root?.querySelector('[data-verb-menu-root]') ?? null;
      this.loadingScreen = this.root?.querySelector('[data-preview-loading-screen]') ?? null;
      this.loadingOverlay = this.root?.querySelector('[data-preview-loading-overlay]') ?? null;
    },

    bind(target, type, handler) {
      if (!target) return;
      target.addEventListener(type, handler);
      this.unloadHandlers.push(() => target.removeEventListener(type, handler));
    },

    bindView(target, type, handler) {
      if (!target) return;
      target.addEventListener(type, handler);
      this.viewUnloadHandlers.push(() => target.removeEventListener(type, handler));
    },

    clearViewBindings() {
      this.viewUnloadHandlers.forEach(unload => unload());
      this.viewUnloadHandlers = [];
    },

    bindViewEvents() {
      this.clearViewBindings();
      this.bindView(this.root, 'click', event => this.onClick(event));
      this.bindView(this.root, 'contextmenu', event => this.onContextMenu(event));
      this.bindView(this.root, 'mouseover', event => this.onMouseOver(event));
      this.bindView(this.root, 'mouseout', event => this.onMouseOut(event));
      this.bindView(this.root, 'submit', event => this.onSubmit(event));
      this.bindView(this.root, 'input', event => this.onInput(event));
      this.bindView(this.root, 'change', event => this.onChange(event));
      this.bindPreviewEvents();
    },

    bindPreviewEvents() {
      this.bindView(this.basePreview, 'preview-object-click', event => this.onPreviewObjectClick(event, 'base'));
      this.bindView(this.basePreview, 'preview-object-menu', event => this.onPreviewObjectMenu(event, 'base'));
      this.bindView(this.basePreview, 'preview-object-mouseover', event => this.onPreviewObjectMouseover(event, 'base'));
      this.bindView(this.basePreview, 'preview-object-mouseout', event => this.onPreviewObjectMouseout(event, 'base'));
      this.bindView(this.basePreview, 'preview-error', event => this.onPreviewError(event));
      this.bindView(this.overlayPreview, 'preview-object-click', event => this.onPreviewObjectClick(event, 'overlay'));
      this.bindView(this.overlayPreview, 'preview-object-menu', event => this.onPreviewObjectMenu(event, 'overlay'));
      this.bindView(this.overlayPreview, 'preview-object-mouseover', event => this.onPreviewObjectMouseover(event, 'overlay'));
      this.bindView(this.overlayPreview, 'preview-object-mouseout', event => this.onPreviewObjectMouseout(event, 'overlay'));
      this.bindView(this.overlayPreview, 'preview-error', event => this.onPreviewError(event));
    },

    async refreshData() {
      try {
        this.setLoadingState({
          visible: true,
          title: 'Loading preview',
          detail: 'Fetching scene data…',
          percent: 8,
          meta: `Scene ${this.sceneId}`
        });
        this.scene = findScene(this.sceneId) ?? {id: this.sceneId};
        this.previewData = await fetchPreviewData(this.sceneId);
        this.setLoadingState({
          visible: true,
          title: 'Preparing runtime',
          detail: 'Building object and variable state…',
          percent: 22,
          meta: formatLoadingMeta(this.previewData)
        });
        this.prepareSceneNavigation();
        this.prepareState();
        this.applyCarriedVariables();
        this.applyLocalAudioSettings();
        this.primeCursorAssets();
        this.scheduleConnectedScenePreload();
        this.editorReady = Boolean(this.previewData);
        this.editorMissing = !this.editorReady;
      } catch {
        previewRouteTransitionInFlight = false;
        previewSceneCarryover = null;
        this.editorReady = false;
        this.editorMissing = true;
        this.setLoadingState({
          visible: false,
          title: 'Preview unavailable',
          detail: 'Could not load scene preview.',
          percent: 0,
          meta: ''
        });
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
      this.runtimeState.inventory = structuredClone(previewSceneCarryover.inventory ?? []);
      this.runtimeState.heldInventoryObjectId = previewSceneCarryover.heldInventoryObjectId ?? null;
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
      this.hoveredOverlayObjectId = null;
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
      this.inventoryItems = buildInventoryInspectorItems(
        this.runtimeState?.inventory ?? [],
        this.runtimeState?.heldInventoryObjectId,
        this.inventoryMotion
      );
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
      this.setLoadingState({
        visible: true,
        title: 'Loading artwork',
        detail: 'Warming preview images…',
        percent: 30,
        meta: formatLoadingMeta(this.previewData)
      });
      await this.basePreview.configure(
        {
          ...this.previewData,
          showBackground: this.showBackground
        },
        {
          mode: 'initial',
          onProgress: progress => {
            const total = Math.max(0, Number(progress?.total) || 0);
            const loaded = Math.max(0, Number(progress?.loaded) || 0);
            const ratio = total > 0 ? Math.min(1, loaded / total) : 1;
            this.setLoadingState({
              visible: true,
              title: 'Loading artwork',
              detail: total > 0
                ? `Warming preview images… ${Math.min(loaded, total)} / ${total}`
                : 'Warming preview images…',
              percent: 30 + Math.round(ratio * 60),
              meta: formatLoadingMeta(this.previewData)
            });
          }
        }
      );
      this.setLoadingState({
        visible: true,
        title: 'Finishing preview',
        detail: 'Syncing runtime state…',
        percent: 94,
        meta: formatLoadingMeta(this.previewData)
      });
      this.pushRuntimeToPreview('base');
      this.syncSubtitleOverlay('base');
      this.syncFadeOverlay('base');
      await this.configureOverlayPreview();
      void preloadPreviewAssets(this.previewData, {mode: 'all'}).catch(() => {});
      this.setLoadingState({
        visible: true,
        title: 'Preview ready',
        detail: 'Finalising controls…',
        percent: 100,
        meta: formatLoadingMeta(this.previewData)
      });
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
      }, {mode: 'initial'});
      this.pushRuntimeToPreview('overlay');
      this.syncOverlayPresentation();
      this.syncSubtitleOverlay('overlay');
      this.syncFadeOverlay('overlay');
      void preloadPreviewAssets(this.overlayPreviewData, {mode: 'all'}).catch(() => {});
    },

    pushRuntimeToPreview(layer) {
      const preview = this.getLayerPreviewElement(layer);
      const runtimeState = this.getLayerRuntimeState(layer);
      if (!preview) return;
      preview.applyRuntimeState(runtimeState ?? {objects: {}});
      this.syncKeyboardFocusState(layer);
    },

    async refreshView() {
      app.refresh();
      await Promise.resolve();
      this.captureDom();
      this.syncLoadingUi();
      this.bindViewEvents();
      await this.configurePreview();
      this.syncRuntimePanels();
    },

    syncRuntimePanels() {
      const objectsRoot = this.root?.querySelector('[data-preview-objects]');
      if (objectsRoot) objectsRoot.innerHTML = renderPreviewObjects(this.previewObjects);
      const variablesRoot = this.root?.querySelector('[data-preview-variables]');
      if (variablesRoot) variablesRoot.innerHTML = renderPreviewVariables(this.runtimeVariables);
      const inventoryRoot = this.root?.querySelector('[data-preview-inventory-items]');
      if (inventoryRoot) inventoryRoot.innerHTML = renderInventoryItems(this.inventoryItems);
      this.syncSubtitleOverlay('base');
      this.syncFadeOverlay('base');
      this.syncOverlayPresentation();
      this.syncSubtitleOverlay('overlay');
      this.syncFadeOverlay('overlay');
      this.syncVerbMenu();
      this.syncFeedbackPulse();
      this.syncInventoryOverlay();
      this.syncHeldInventoryItem();
      this.syncCustomCursor();
      this.syncStartOverlay();
      this.syncLocalAudioControls();
    },

    syncLocalAudioControls() {
      const root = this.root;
      if (!root) return;
      const masterInput = root.querySelector('[data-preview-master-volume]');
      const musicInput = root.querySelector('[data-preview-music-volume]');
      const masterValue = root.querySelector('[data-preview-master-volume-value]');
      const musicValue = root.querySelector('[data-preview-music-volume-value]');
      if (masterInput) masterInput.value = String(this.localMasterVolume);
      if (musicInput) musicInput.value = String(this.localMusicVolume);
      if (masterValue) masterValue.textContent = String(this.localMasterVolume);
      if (musicValue) musicValue.textContent = String(this.localMusicVolume);
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

    syncVerbMenu() {
      if (!this.verbMenuRoot) return;
      const menu = this.activeVerbMenu;
      this.verbMenuRoot.classList.toggle('is-hidden', !menu);
      if (!menu) {
        if (this.verbMenuAnimationTimer) window.clearTimeout(this.verbMenuAnimationTimer);
        this.verbMenuAnimationTimer = null;
        this.verbMenuRoot.classList.remove('is-entering');
        this.verbMenuRoot.classList.remove('is-confirming');
        this.verbMenuRoot.style.left = '';
        this.verbMenuRoot.style.top = '';
        this.verbMenuRoot.style.width = '';
        this.verbMenuRoot.style.height = '';
        this.verbMenuRoot.innerHTML = '';
        this.renderedVerbMenuSignature = '';
        return;
      }
      const preview = this.getLayerPreviewElement(menu.layer);
      const previewStageRect = preview?.getStageClientRect?.();
      const stageRootRect = this.stageRoot?.getBoundingClientRect?.();
      if (previewStageRect && stageRootRect) {
        this.verbMenuRoot.style.left = `${previewStageRect.left - stageRootRect.left}px`;
        this.verbMenuRoot.style.top = `${previewStageRect.top - stageRootRect.top}px`;
        this.verbMenuRoot.style.width = `${previewStageRect.width}px`;
        this.verbMenuRoot.style.height = `${previewStageRect.height}px`;
      }
      const signature = buildVerbMenuSignature(menu);
      if (signature !== this.renderedVerbMenuSignature) {
        this.verbMenuRoot.innerHTML = renderVerbMenu(menu);
        this.renderedVerbMenuSignature = signature;
        this.verbMenuRoot.classList.add('is-entering');
        if (this.verbMenuAnimationTimer) window.clearTimeout(this.verbMenuAnimationTimer);
        this.verbMenuAnimationTimer = window.setTimeout(() => {
          this.verbMenuAnimationTimer = null;
          this.verbMenuRoot?.classList.remove('is-entering');
        }, 260);
      }
    },

    syncFeedbackPulse() {
      if (!this.feedbackLayerRoot) return;
      const pulse = this.feedbackPulse;
      this.feedbackLayerRoot.classList.toggle('is-hidden', !pulse);
      if (!pulse) {
        this.feedbackLayerRoot.style.left = '';
        this.feedbackLayerRoot.style.top = '';
        this.feedbackLayerRoot.style.width = '';
        this.feedbackLayerRoot.style.height = '';
        this.feedbackLayerRoot.innerHTML = '';
        return;
      }
      const preview = this.getLayerPreviewElement(pulse.layer);
      const previewStageRect = preview?.getStageClientRect?.();
      const stageRootRect = this.stageRoot?.getBoundingClientRect?.();
      if (previewStageRect && stageRootRect) {
        this.feedbackLayerRoot.style.left = `${previewStageRect.left - stageRootRect.left}px`;
        this.feedbackLayerRoot.style.top = `${previewStageRect.top - stageRootRect.top}px`;
        this.feedbackLayerRoot.style.width = `${previewStageRect.width}px`;
        this.feedbackLayerRoot.style.height = `${previewStageRect.height}px`;
      }
      this.feedbackLayerRoot.innerHTML = renderInteractionPulse(pulse);
    },

    syncInventoryOverlay() {
      const active = Boolean(this.runtimeState?.inventoryOverlayOpen);
      this.inventoryLayoutVersion += 1;
      const layoutVersion = this.inventoryLayoutVersion;
      if (this.inventoryOverlayShell) {
        this.inventoryOverlayShell.classList.toggle('is-hidden', !active);
      }
      if (!this.inventoryStage) return;
      if (!active) {
        this.inventoryStage.innerHTML = '';
        return;
      }
      const config = this.getInventoryConfig();
      this.inventoryStage.style.backgroundImage = config.backgroundUrl ? `url("${config.backgroundUrl}")` : 'none';
      const render = surface => {
        if (!this.runtimeState?.inventoryOverlayOpen) return;
        if (layoutVersion !== this.inventoryLayoutVersion) return;
        this.inventoryStage.innerHTML = renderInventoryOverlay({
          slots: config.slots,
          items: this.runtimeState?.inventory ?? [],
          motion: this.inventoryMotion,
          surface
        });
      };
      render(null);
      if (!config.backgroundUrl) return;
      const stageRect = this.inventoryStage.getBoundingClientRect();
      loadInventoryBackgroundMetrics(config.backgroundUrl).then(metrics => {
        if (!metrics) return;
        render(computeContainedSurfaceLayout(stageRect.width, stageRect.height, metrics.width, metrics.height));
      }).catch(() => {});
    },

    syncHeldInventoryItem(pointerPosition = null) {
      if (!this.heldInventoryItemRoot) return;
      const heldItem = this.getHeldInventoryItem();
      const resolvedPointer = pointerPosition ?? (
        this.pointerClientX != null && this.pointerClientY != null
          ? {clientX: this.pointerClientX, clientY: this.pointerClientY}
          : null
      );
      this.heldInventoryItemRoot.classList.toggle('is-hidden', !heldItem);
      if (!heldItem) {
        this.heldInventoryItemRoot.innerHTML = '';
      } else {
        if (resolvedPointer) {
          this.heldInventoryItemRoot.style.left = `${resolvedPointer.clientX}px`;
          this.heldInventoryItemRoot.style.top = `${resolvedPointer.clientY}px`;
        }
        this.heldInventoryItemRoot.innerHTML = renderHeldInventoryItem(heldItem, this.heldItemMotion);
      }
      if (!this.heldInventoryGhostRoot) return;
      const ghost = this.heldInventoryGhost;
      this.heldInventoryGhostRoot.classList.toggle('is-hidden', !ghost);
      if (!ghost) {
        this.heldInventoryGhostRoot.innerHTML = '';
        return;
      }
      this.heldInventoryGhostRoot.style.left = `${ghost.clientX}px`;
      this.heldInventoryGhostRoot.style.top = `${ghost.clientY}px`;
      this.heldInventoryGhostRoot.innerHTML = renderHeldInventoryGhost(ghost);
    },

    syncCustomCursor() {
      if (!this.stageRoot || !this.cursorRoot) return;
      const cursorState = this.resolveCustomCursorState();
      this.customCursorStateKey = cursorState.stateKey;
      const display = this.getCursorDisplayForState(cursorState.stateKey);
      const useCustomCursor = Boolean(
        this.stagePointerInside
        && this.pointerClientX != null
        && this.pointerClientY != null
        && display?.url
      );
      if (!useCustomCursor) {
        this.stageRoot.classList.remove('has-custom-cursor');
        this.cursorRoot.classList.add('is-hidden');
        this.cursorRoot.innerHTML = '';
        this.basePreview?.setUseExternalCursor?.(false);
        this.overlayPreview?.setUseExternalCursor?.(false);
        return;
      }
      const imageState = getCursorImageState(display.url);
      if (imageState.status === 'idle') {
        void loadCursorImage(display.url).finally(() => this.syncCustomCursor());
      }
      if (imageState.status !== 'loaded') {
        this.stageRoot.classList.remove('has-custom-cursor');
        this.cursorRoot.classList.add('is-hidden');
        this.cursorRoot.innerHTML = '';
        this.basePreview?.setUseExternalCursor?.(false);
        this.overlayPreview?.setUseExternalCursor?.(false);
        return;
      }
      this.stageRoot.classList.add('has-custom-cursor');
      this.cursorRoot.classList.remove('is-hidden');
      this.cursorRoot.style.left = `${this.pointerClientX}px`;
      this.cursorRoot.style.top = `${this.pointerClientY}px`;
      this.cursorRoot.innerHTML = renderCustomCursor(display);
      this.basePreview?.setUseExternalCursor?.(true);
      this.overlayPreview?.setUseExternalCursor?.(true);
    },

    syncStartOverlay() {
      const overlay = this.root?.querySelector('[data-preview-start-overlay]');
      if (!overlay) return;
      overlay.classList.toggle('is-hidden', !this.startPromptVisible);
    },

    updatePreviewPointer(event) {
      const stageRect = this.stageRoot?.getBoundingClientRect();
      if (!stageRect) return;
      const inside = pointInsideRect(event.clientX, event.clientY, stageRect);
      this.stagePointerInside = inside;
      this.pointerClientX = inside ? event.clientX : null;
      this.pointerClientY = inside ? event.clientY : null;
      this.syncCustomCursor();
    },

    clearPreviewPointer() {
      this.stagePointerInside = false;
      this.pointerClientX = null;
      this.pointerClientY = null;
      this.hoveredBaseObjectId = null;
      this.hoveredOverlayObjectId = null;
      this.syncCustomCursor();
    },

    setInventoryMotion(kind, objectIds = []) {
      if (this.inventoryMotionTimer) window.clearTimeout(this.inventoryMotionTimer);
      this.inventoryMotion = {
        kind,
        objectIds: objectIds.map(Number)
      };
      this.syncInventoryOverlay();
      this.refreshInspectorState();
      this.inventoryMotionTimer = window.setTimeout(() => {
        this.inventoryMotionTimer = null;
        this.inventoryMotion = null;
        this.syncInventoryOverlay();
        this.refreshInspectorState();
      }, kind === 'open' ? 340 : 420);
    },

    setHeldItemMotion(kind) {
      if (this.heldItemMotionTimer) window.clearTimeout(this.heldItemMotionTimer);
      this.heldItemMotion = kind;
      this.syncHeldInventoryItem();
      this.heldItemMotionTimer = window.setTimeout(() => {
        this.heldItemMotionTimer = null;
        this.heldItemMotion = null;
        this.syncHeldInventoryItem();
      }, 260);
    },

    setHeldInventoryGhost(item, clientX, clientY) {
      if (this.heldInventoryGhostTimer) window.clearTimeout(this.heldInventoryGhostTimer);
      this.heldInventoryGhost = {
        name: item.name,
        thumbnailUrl: item.thumbnailUrl,
        clientX,
        clientY
      };
      this.syncHeldInventoryItem();
      this.heldInventoryGhostTimer = window.setTimeout(() => {
        this.heldInventoryGhostTimer = null;
        this.heldInventoryGhost = null;
        this.syncHeldInventoryItem();
      }, 220);
    },

    showInteractionPulse(kind, layer, objectId, metadata = {}) {
      if (this.feedbackPulseTimer) window.clearTimeout(this.feedbackPulseTimer);
      const position = resolveStagePulsePosition.call(this, layer, objectId, metadata);
      if (!position) return;
      this.feedbackPulse = {
        kind,
        layer,
        x: position.x,
        y: position.y
      };
      this.syncFeedbackPulse();
      this.feedbackPulseTimer = window.setTimeout(() => {
        this.feedbackPulseTimer = null;
        this.feedbackPulse = null;
        this.syncFeedbackPulse();
      }, 260);
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
      applyStatus(status, message);
    },

    onInput(event) {
      const target = event.target;
      if (!(target instanceof HTMLInputElement)) return;
      if (target.matches('[data-preview-master-volume]')) {
        this.localMasterVolume = clampNumber(Math.round(Number(target.value) || 0), 0, 10);
        this.persistLocalAudioSettings();
        this.syncLocalAudioControls();
        this.syncContinuousAudioState();
        return;
      }
      if (target.matches('[data-preview-music-volume]')) {
        this.localMusicVolume = clampNumber(Math.round(Number(target.value) || 0), 0, 10);
        this.persistLocalAudioSettings();
        this.syncLocalAudioControls();
        this.syncContinuousAudioState();
      }
    },

    onChange(event) {
      this.onInput(event);
    },

    setLoadingState({visible, title, detail, percent, meta} = {}) {
      if (typeof visible === 'boolean') this.loadingVisible = visible;
      if (typeof title === 'string') this.loadingTitle = title;
      if (typeof detail === 'string') this.loadingDetail = detail;
      if (typeof percent === 'number' && Number.isFinite(percent)) {
        this.loadingPercent = Math.max(0, Math.min(100, Math.round(percent)));
      }
      if (typeof meta === 'string') this.loadingMeta = meta;
      this.syncLoadingUi();
      this.syncCustomCursor();
    },

    syncLoadingUi() {
      const roots = [this.loadingScreen, this.loadingOverlay].filter(Boolean);
      for (const root of roots) {
        root.classList.toggle('is-hidden', !this.loadingVisible);
        const title = root.querySelector('[data-preview-loading-title]');
        const detail = root.querySelector('[data-preview-loading-detail]');
        const bar = root.querySelector('[data-preview-loading-bar]');
        const meta = root.querySelector('[data-preview-loading-meta]');
        if (title) title.textContent = this.loadingTitle;
        if (detail) detail.textContent = this.loadingDetail;
        if (bar) bar.style.width = `${this.loadingPercent}%`;
        if (meta) meta.textContent = this.loadingMeta;
      }
    },

    async reloadRuntime({rerunSceneEnter}) {
      this.executionVersion += 1;
      this.stopMediaPlayback();
      const persistedInventory = structuredClone(this.runtimeState?.inventory ?? []);
      invalidatePreviewDataCache(this.sceneId);
      await this.refreshData();
      if (this.runtimeState) {
        this.runtimeState.inventory = persistedInventory;
        this.runtimeState.heldInventoryObjectId = null;
      }
      await this.refreshView();
      this.setLoadingState({visible: false});
      await this.waitForPreviewPresentation();
      if (rerunSceneEnter) {
        await this.runSceneEnterActions();
      }
    },

    async resetRuntime() {
      this.executionVersion += 1;
      this.stopMediaPlayback();
      this.runtimeState = cloneRuntimeState(this.runtimeSnapshot);
      this.closeVerbMenu();
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
      this.syncHeldInventoryItem();
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

    applyLocalAudioSettings() {
      const authored = this.getAuthoredLanguageSettings();
      const stored = readPreviewLocalAudioSettings();
      this.localMasterVolume = clampNumber(
        Number.isFinite(Number(stored.masterVolume)) ? Math.round(Number(stored.masterVolume)) : authored.masterVolume,
        0,
        10
      );
      this.localMusicVolume = clampNumber(
        Number.isFinite(Number(stored.musicVolume)) ? Math.round(Number(stored.musicVolume)) : authored.musicVolume,
        0,
        10
      );
    },

    persistLocalAudioSettings() {
      writePreviewLocalAudioSettings({
        masterVolume: this.localMasterVolume,
        musicVolume: this.localMusicVolume
      });
    },

    async runSceneEnterActions() {
      await this.executeMatchingInteractionsForLayer(
        'base',
        interaction => interaction.trigger?.type === 'scene_enter',
        {reason: 'scene_enter'}
      );
    },

    async runStartupSceneEnterActions() {
      if (this.startupSceneEnterNeedsUserGesture() && !this.audioUnlocked) {
        this.startPromptVisible = true;
        this.syncStartOverlay();
        return;
      }
      this.startPromptVisible = false;
      this.syncStartOverlay();
      await this.runSceneEnterActions();
    },

    startupSceneEnterNeedsUserGesture() {
      const sceneEnterInteractions = (this.previewData?.interactions ?? []).filter(
        interaction => interaction.trigger?.type === 'scene_enter' && interaction.enabled !== false
      );
      return sceneEnterInteractions.some(interaction => actionTreeContainsAudio(interaction.action_tree ?? []));
    },

    async waitForPreviewPresentation() {
      await nextAnimationFrame();
      await nextAnimationFrame();
    },

    async runSceneExitActions() {
      await this.executeMatchingInteractionsForLayer(
        'base',
        interaction => interaction.trigger?.type === 'scene_exit',
        {reason: 'scene_exit', targetSceneId: this.pendingSceneTransitionTarget}
      );
    },

    async onClick(event) {
      void previewAudioRuntime.resumePendingBgm();
      const startPreviewButton = event.target.closest('[data-action="start-preview"]');
      if (startPreviewButton) {
        this.audioUnlocked = true;
        this.startPromptVisible = false;
        this.syncStartOverlay();
        await this.runSceneEnterActions();
        return;
      }
      const verbButton = event.target.closest('[data-action="select-verb"]');
      if (verbButton) {
        const objectId = Number(verbButton.dataset.objectId);
        const verbId = Number(verbButton.dataset.verbId);
        const layer = verbButton.dataset.layer || this.getActiveLayerName();
        if (!verbButton.disabled) {
          await this.animateVerbSelection(verbButton);
          await this.selectVerb(layer, objectId, verbId, event);
        }
        return;
      }

      const inventoryItemButton = event.target.closest('[data-action="select-inventory-item"]');
      if (inventoryItemButton) {
        await this.selectInventoryItem(Number(inventoryItemButton.dataset.objectId));
        return;
      }

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
        return;
      }

      const insideVerbMenu = event.target.closest('[data-verb-menu-root]');
      const insideInventory = event.target.closest('[data-inventory-overlay-shell]');
      if (this.activeVerbMenu && !insideVerbMenu && this.ignoreNextVerbMenuOutsideClick) {
        this.ignoreNextVerbMenuOutsideClick = false;
        return;
      }
      const shouldSuppressVerbDismiss = this.activeVerbMenu
        && performance.now() < Number(this.suppressVerbMenuDismissUntil || 0);
      if (this.activeVerbMenu && !insideVerbMenu && !shouldSuppressVerbDismiss) {
        this.closeVerbMenu();
      }
      if (this.runtimeState?.inventoryOverlayOpen && !insideInventory) {
        this.closeInventoryOverlay();
      }
    },

    onContextMenu(event) {
      void previewAudioRuntime.resumePendingBgm();
      if (this.getHeldInventoryItem()) {
        event.preventDefault();
        this.clearHeldInventoryItem();
      }
    },

    onMouseOver(event) {
      if (!this.activeVerbMenu) return;
      const verbButton = event.target.closest?.('[data-action="select-verb"]');
      if (!verbButton) return;
      if (this.verbMenuDismissTimer) {
        window.clearTimeout(this.verbMenuDismissTimer);
        this.verbMenuDismissTimer = null;
      }
    },

    onMouseOut(event) {
      if (!this.activeVerbMenu) return;
      const verbButton = event.target.closest?.('[data-action="select-verb"]');
      if (!verbButton) return;
      const nextTarget = event.relatedTarget instanceof Element ? event.relatedTarget : null;
      if (nextTarget?.closest?.('[data-action="select-verb"]')) return;
      this.bumpVerbMenuTimeout();
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
      void previewAudioRuntime.resumePendingBgm();
      if (event.defaultPrevented || event.repeat || isEditableTarget(event.target)) return;
      const keyCode = normalizeEventKeyCode(event);
      if (!keyCode) return;

      if (keyCode === 'Escape' && this.activeVerbMenu) {
        event.preventDefault();
        this.closeVerbMenu();
        return;
      }
      if (keyCode === 'Escape' && this.getHeldInventoryItem()) {
        event.preventDefault();
        this.clearHeldInventoryItem();
        return;
      }
      if (keyCode === 'Escape' && this.runtimeState?.inventoryOverlayOpen) {
        event.preventDefault();
        this.closeInventoryOverlay();
        return;
      }
      if (keyCode === 'Escape' && this.overlayPreviewData) {
        event.preventDefault();
        await this.closeOverlayScene();
        return;
      }

      if (keyCode === this.getInventoryConfig().keyCode && !this.overlayPreviewData) {
        event.preventDefault();
        if (this.runtimeState?.inventoryOverlayOpen) this.closeInventoryOverlay();
        else this.openInventoryOverlay();
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
      if (this.activeVerbMenu) this.closeVerbMenu();
      const heldItem = this.getHeldInventoryItem();
      if (heldItem) {
        const matched = await this.triggerInventoryUse(layer, objectId, heldItem.scene_object_id, event.detail ?? {});
        if (matched) this.showInteractionPulse('accept', layer, objectId, event.detail ?? {});
        else this.showInteractionPulse('blocked', layer, objectId, event.detail ?? {});
        return;
      }
      const matched = await this.triggerObjectClick(layer, objectId, event.detail ?? {});
      if (matched) this.showInteractionPulse('accept', layer, objectId, event.detail ?? {});
    },

    async onPreviewObjectMenu(event, layer) {
      if (layer === 'base' && this.overlayPreviewData) return;
      if (layer === 'overlay' && !this.overlayPreviewData) return;
      if (this.getHeldInventoryItem()) {
        this.clearHeldInventoryItem();
        return;
      }
      const objectId = Number(event.detail?.objectId);
      if (!objectId) return;
      this.openVerbMenu(layer, objectId, event.detail ?? {});
    },

    async triggerObjectClick(layer, objectId, metadata = {}) {
      const state = this.getLayerRuntimeState(layer)?.objects?.[objectId];
      if (!state?.enabled || !state?.visible) return false;
      const interactions = resolveTriggeredInteractions(
        this.getLayerPreviewData(layer)?.interactions ?? [],
        buildObjectClickTriggerTiers(Number(objectId))
      );
      if (!interactions.length) return false;
      const chainState = {remaining: MAX_CHAINED_INTERACTIONS};
      await this.executeInteractions(layer, interactions, {reason: 'object_click', objectId: Number(objectId), ...metadata}, chainState);
      return true;
    },

    async triggerInventoryUse(layer, objectId, inventoryObjectId, metadata = {}) {
      const state = this.getLayerRuntimeState(layer)?.objects?.[objectId];
      if (!state?.enabled || !state?.visible) return false;
      const interactions = resolveTriggeredInteractions(
        this.getLayerPreviewData(layer)?.interactions ?? [],
        buildInventoryUseTriggerTiers(Number(objectId), Number(inventoryObjectId))
      );
      if (!interactions.length) return false;
      const chainState = {remaining: MAX_CHAINED_INTERACTIONS};
      await this.executeInteractions(
        layer,
        interactions,
        {reason: 'inventory_use', objectId: Number(objectId), inventoryObjectId: Number(inventoryObjectId), ...metadata},
        chainState
      );
      return true;
    },

    async onPreviewObjectMouseover(event, layer) {
      if (layer === 'base' && this.overlayPreviewData) return;
      if (layer === 'overlay' && !this.overlayPreviewData) return;
      const objectId = Number(event.detail?.objectId);
      if (!objectId) return;
      if (layer === 'overlay') this.hoveredOverlayObjectId = objectId;
      else this.hoveredBaseObjectId = objectId;
      this.syncCustomCursor();
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
      if (layer === 'overlay' && Number(this.hoveredOverlayObjectId) === objectId) this.hoveredOverlayObjectId = null;
      if (layer === 'base' && Number(this.hoveredBaseObjectId) === objectId) this.hoveredBaseObjectId = null;
      this.syncCustomCursor();
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

    openVerbMenu(layer, objectId, metadata = {}) {
      if (this.getHeldInventoryItem()) return;
      const verbs = buildVerbMenuItems(this.getLayerPreviewData(layer), objectId, this.getLanguageSettings());
      if (!verbs.length) return;
      const preview = this.getLayerPreviewElement(layer);
      const stageRect = preview?.getStageClientRect?.();
      const objectRect = preview?.getObjectClientBounds?.(objectId);
      if (!stageRect || !objectRect) return;
      const pointerAnchor = (
        Number.isFinite(Number(metadata.clientX)) && Number.isFinite(Number(metadata.clientY))
      )
        ? {
          x: Number(metadata.clientX) - stageRect.left,
          y: Number(metadata.clientY) - stageRect.top
        }
        : {
          x: (objectRect.left - stageRect.left) + (objectRect.width / 2),
          y: (objectRect.top - stageRect.top) + (objectRect.height / 2)
        };
      const layout = computeVerbMenuLayout(stageRect.width, stageRect.height, pointerAnchor, verbs.length);
      this.activeVerbMenu = {
        layer,
        objectId: Number(objectId),
        items: verbs.map((verb, index) => ({
          ...verb,
          offsetX: layout.offsets[index]?.x ?? 0,
          offsetY: layout.offsets[index]?.y ?? 0
        })),
        left: layout.anchorX,
        top: layout.anchorY
      };
      this.verbMenuOpenedAt = performance.now();
      this.suppressVerbMenuDismissUntil = this.verbMenuOpenedAt + 600;
      this.ignoreNextVerbMenuOutsideClick = true;
      this.bumpVerbMenuTimeout();
      this.syncVerbMenu();
    },

    closeVerbMenu() {
      if (this.verbMenuDismissTimer) window.clearTimeout(this.verbMenuDismissTimer);
      this.verbMenuDismissTimer = null;
      if (this.verbMenuAnimationTimer) window.clearTimeout(this.verbMenuAnimationTimer);
      this.verbMenuAnimationTimer = null;
      this.activeVerbMenu = null;
      this.verbMenuOpenedAt = 0;
      this.suppressVerbMenuDismissUntil = 0;
      this.ignoreNextVerbMenuOutsideClick = false;
      this.syncVerbMenu();
    },

    async animateVerbSelection(button) {
      if (!button || !this.verbMenuRoot) {
        await waitMilliseconds(120);
        return;
      }
      this.verbMenuRoot.classList.remove('is-entering');
      if (this.verbMenuAnimationTimer) {
        window.clearTimeout(this.verbMenuAnimationTimer);
        this.verbMenuAnimationTimer = null;
      }
      this.verbMenuRoot.classList.add('is-confirming');
      button.classList.add('is-confirming');
      await waitMilliseconds(140);
    },

    bumpVerbMenuTimeout() {
      if (this.verbMenuDismissTimer) window.clearTimeout(this.verbMenuDismissTimer);
      this.verbMenuDismissTimer = window.setTimeout(() => {
        this.verbMenuDismissTimer = null;
        this.closeVerbMenu();
      }, Math.round(this.getVerbMenuTimeoutSeconds() * 1000));
    },

    async selectVerb(layer, objectId, verbId, event = null) {
      this.closeVerbMenu();
      const interactions = resolveTriggeredInteractions(
        this.getLayerPreviewData(layer)?.interactions ?? [],
        buildObjectVerbTriggerTiers(Number(objectId), Number(verbId))
      );
      const matched = Boolean(interactions.length);
      if (matched) {
        const chainState = {remaining: MAX_CHAINED_INTERACTIONS};
        await this.executeInteractions(
          layer,
          interactions,
          {reason: 'object_verb', objectId: Number(objectId), verbId: Number(verbId)},
          chainState
        );
      }
      if (matched) {
        this.showInteractionPulse('accept', layer, objectId, event ? {clientX: event.clientX, clientY: event.clientY} : {});
      }
    },

    openInventoryOverlay() {
      if (this.activeVerbMenu) this.closeVerbMenu();
      if (!this.runtimeState) return;
      this.runtimeState.inventoryOverlayOpen = true;
      this.setInventoryMotion('open', (this.runtimeState.inventory ?? []).map(item => Number(item.scene_object_id)));
      this.refreshInspectorState();
    },

    closeInventoryOverlay() {
      if (!this.runtimeState) return;
      this.runtimeState.inventoryOverlayOpen = false;
      this.refreshInspectorState();
    },

    async selectInventoryItem(sceneObjectId) {
      const item = (this.runtimeState?.inventory ?? []).find(
        inventoryItem => Number(inventoryItem.scene_object_id) === Number(sceneObjectId)
      );
      if (!item || !this.runtimeState) return;
      this.runtimeState.heldInventoryObjectId = Number(sceneObjectId);
      this.runtimeState.inventoryOverlayOpen = false;
      this.setHeldItemMotion('attach');
      this.refreshInspectorState();
    },

    clearHeldInventoryItem() {
      if (!this.runtimeState) return;
      const heldItem = this.getHeldInventoryItem();
      if (heldItem && this.pointerClientX != null && this.pointerClientY != null) {
        this.setHeldInventoryGhost(heldItem, this.pointerClientX, this.pointerClientY);
      }
      this.runtimeState.heldInventoryObjectId = null;
      this.syncHeldInventoryItem();
      this.refreshInspectorState();
    },

    getHeldInventoryItem() {
      const heldId = Number(this.runtimeState?.heldInventoryObjectId);
      if (!heldId) return null;
      return (this.runtimeState?.inventory ?? []).find(
        item => Number(item.scene_object_id) === heldId
      ) ?? null;
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
      if (!interactions.length) return false;
      const chainState = {remaining: MAX_CHAINED_INTERACTIONS};
      await this.executeInteractions(layer, interactions, metadata, chainState);
      return true;
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
        const resolvedObjectId = resolveStepTargetObjectId(step, metadata);
        if (!resolvedObjectId) return;
        const resolvedAnimationId = resolveStepAnimationId(previewData, step, resolvedObjectId);
        if (!resolvedAnimationId) return;
        const runPromise = preview?.playAnimation(resolvedObjectId, resolvedAnimationId, {
          mode: step.mode ?? 'queued'
        });
        if (step.wait !== 'continue') await runPromise;
        else void runPromise;
        const render = getAnimationLastRender(previewData, resolvedObjectId, resolvedAnimationId);
        if (render && runtimeState?.objects?.[resolvedObjectId]) {
          runtimeState.objects[resolvedObjectId].render = render;
          this.pushRuntimeToPreview(layer);
        }
        return;
      }

      if (step.type === 'go_to_frame') {
        if ((step.target_scope ?? 'object') === 'background') {
          if (runtimeState) runtimeState.background_frame_index = Number(step.frame_index);
          this.pushRuntimeToPreview(layer);
          return;
        }
        if ((step.target_scope ?? 'object') === 'pickup_background') {
          const resolvedObjectId = resolveStepTargetObjectId(step, metadata);
          if (!resolvedObjectId) return;
          const sceneObject = previewData?.objects?.find(
            object => Number(object.id) === Number(resolvedObjectId)
          );
          const pickupUploadedFileId = Number(sceneObject?.pickup_uploaded_file_id ?? 0);
          const render = getObjectRenderForUploadedFileId(
            previewData,
            resolvedObjectId,
            pickupUploadedFileId
          );
          if (runtimeState?.objects?.[resolvedObjectId]) {
            runtimeState.objects[resolvedObjectId].render = render;
          }
          preview?.setObjectRender?.(resolvedObjectId, render);
          this.refreshInspectorState();
          return;
        }
        const resolvedObjectId = resolveStepTargetObjectId(step, metadata);
        if (!resolvedObjectId) return;
        const render = getObjectRenderForFrame(previewData, resolvedObjectId, step.frame_index);
        if (runtimeState?.objects?.[resolvedObjectId]) {
          runtimeState.objects[resolvedObjectId].render = render;
        }
        preview?.setObjectRender?.(resolvedObjectId, render);
        this.refreshInspectorState();
        return;
      }

      if (step.type === 'set_object_property') {
        const resolvedObjectId = resolveStepTargetObjectId(step, metadata);
        if (!resolvedObjectId) return;
        const objectState = runtimeState?.objects?.[resolvedObjectId];
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

      if (step.type === 'add_inventory_item') {
        const sceneObjectId = resolveStepSceneObjectId(step, metadata);
        if (!sceneObjectId) return;
        const inventoryItem = buildInventoryItemFromSceneObject(this.previewData, this.overlayPreviewData, sceneObjectId);
        if (!inventoryItem || !this.runtimeState) return;
        const exists = (this.runtimeState.inventory ?? []).some(
          item => Number(item.scene_object_id) === Number(inventoryItem.scene_object_id)
        );
        if (!exists) {
          this.runtimeState.inventory = [...(this.runtimeState.inventory ?? []), inventoryItem];
          this.setInventoryMotion('add', [Number(inventoryItem.scene_object_id)]);
        }
        this.refreshInspectorState();
        return;
      }

      if (step.type === 'remove_inventory_item') {
        if (!this.runtimeState) return;
        const sceneObjectId = resolveStepSceneObjectId(step, metadata);
        if (!sceneObjectId) return;
        const removedItem = (this.runtimeState.inventory ?? []).find(
          item => Number(item.scene_object_id) === Number(sceneObjectId)
        );
        if (
          removedItem
          && Number(this.runtimeState.heldInventoryObjectId) === Number(sceneObjectId)
          && this.pointerClientX != null
          && this.pointerClientY != null
        ) {
          this.setHeldInventoryGhost(removedItem, this.pointerClientX, this.pointerClientY);
        }
        this.runtimeState.inventory = (this.runtimeState.inventory ?? []).filter(
          item => Number(item.scene_object_id) !== Number(sceneObjectId)
        );
        if (Number(this.runtimeState.heldInventoryObjectId) === Number(sceneObjectId)) {
          this.runtimeState.heldInventoryObjectId = null;
        }
        this.refreshInspectorState();
        return;
      }

      if (step.type === 'clear_held_inventory_item') {
        const heldItem = this.getHeldInventoryItem();
        if (heldItem && this.pointerClientX != null && this.pointerClientY != null) {
          this.setHeldInventoryGhost(heldItem, this.pointerClientX, this.pointerClientY);
        }
        this.clearHeldInventoryItem();
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
      this.closeVerbMenu();
      this.closeInventoryOverlay();
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
      this.closeVerbMenu();
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
        ),
        inventory: structuredClone(this.runtimeState?.inventory ?? []),
        heldInventoryObjectId: this.runtimeState?.heldInventoryObjectId ?? null
      };
      previewRouteTransitionInFlight = true;
      this.executionVersion += 1;
      this.stopMediaPlayback();
      this.closeVerbMenu();
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

    getAuthoredLanguageSettings() {
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

    getLanguageSettings() {
      const authored = this.getAuthoredLanguageSettings();
      return {
        ...authored,
        masterVolume: clampNumber(Number(this.localMasterVolume), 0, 10),
        musicVolume: clampNumber(Number(this.localMusicVolume), 0, 10)
      };
    },

    getGlobalOverlaySettings() {
      return {
        overlayOpenDurationSeconds: Number(this.previewData?.global_settings?.overlay_open_duration_seconds || 0.22),
        overlayCloseDurationSeconds: Number(this.previewData?.global_settings?.overlay_close_duration_seconds || 0.18),
        overlayAffectAudio: Boolean(this.previewData?.global_settings?.overlay_affect_audio)
      };
    },

    getVerbMenuTimeoutSeconds() {
      return Number(this.previewData?.global_settings?.verb_menu_timeout_seconds || 4);
    },

    getInventoryConfig() {
      return {
        keyCode: this.previewData?.global_settings?.inventory_key_code || 'KeyI',
        slots: normalizeInventorySlots(this.previewData?.global_settings?.inventory_slots ?? []),
        backgroundUrl: this.previewData?.global_settings?.inventory_background_relative_path
          ? globalSettingsAssetUrl('inventory_background')
          : ''
      };
    },

    getCursorDisplayForState(stateKey) {
      const cursorStates = this.previewData?.global_settings?.cursor_states ?? {};
      const requestedState = cursorStates?.[stateKey] ?? {};
      const fallbackState = cursorStates?.[CURSOR_STATE_DEFAULT] ?? {};
      const useFallback = !requestedState.relative_path && stateKey !== CURSOR_STATE_DEFAULT && Boolean(fallbackState.relative_path);
      const normalizedState = useFallback ? fallbackState : requestedState;
      const resolvedStateKey = useFallback ? CURSOR_STATE_DEFAULT : stateKey;
      const relativePath = normalizedState.relative_path;
      return {
        stateKey: resolvedStateKey,
        url: relativePath ? globalSettingsAssetUrl(`cursor_${resolvedStateKey}`) : '',
        hotspotX: Number(normalizedState.hotspot_x ?? 0),
        hotspotY: Number(normalizedState.hotspot_y ?? 0)
      };
    },

    primeCursorAssets() {
      const cursorStates = this.previewData?.global_settings?.cursor_states ?? {};
      for (const stateKey of [
        CURSOR_STATE_DEFAULT,
        CURSOR_STATE_HOVER_INTERACTIVE,
        CURSOR_STATE_BUSY,
        CURSOR_STATE_BLOCKED
      ]) {
        const relativePath = cursorStates?.[stateKey]?.relative_path;
        if (!relativePath) continue;
        void loadCursorImage(globalSettingsAssetUrl(`cursor_${stateKey}`)).catch(() => {});
      }
    },

    resolveCustomCursorState() {
      if (this.loadingVisible && this.previewData?.global_settings?.cursor_states?.busy?.relative_path) {
        return {stateKey: CURSOR_STATE_BUSY};
      }
      const hoveredObjectId = this.overlayPreviewData ? this.hoveredOverlayObjectId : this.hoveredBaseObjectId;
      if (!hoveredObjectId) return {stateKey: CURSOR_STATE_DEFAULT};
      if (this.getHeldInventoryItem()) {
        const heldId = Number(this.runtimeState?.heldInventoryObjectId);
        return {
          stateKey: this.objectHasInventoryUse(this.getActiveLayerName(), hoveredObjectId, heldId)
            ? CURSOR_STATE_HOVER_INTERACTIVE
            : CURSOR_STATE_BLOCKED
        };
      }
      return {
        stateKey: this.objectHasDirectInteraction(this.getActiveLayerName(), hoveredObjectId)
          ? CURSOR_STATE_HOVER_INTERACTIVE
          : CURSOR_STATE_BLOCKED
      };
    },

    objectHasDirectInteraction(layer, objectId) {
      const interactions = this.getLayerPreviewData(layer)?.interactions ?? [];
      if (resolveTriggeredInteractions(interactions, buildObjectClickTriggerTiers(Number(objectId))).length) return true;
      return (this.getLayerPreviewData(layer)?.verbs ?? []).some(verb => (
        resolveTriggeredInteractions(interactions, buildObjectVerbTriggerTiers(Number(objectId), Number(verb.id))).length > 0
      ));
    },

    objectHasInventoryUse(layer, objectId, inventoryObjectId) {
      return resolveTriggeredInteractions(
        this.getLayerPreviewData(layer)?.interactions ?? [],
        buildInventoryUseTriggerTiers(Number(objectId), Number(inventoryObjectId))
      ).length > 0;
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
    background_frame_index: Number(previewData?.background_frame_index ?? 0),
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
    ),
    inventory: [],
    heldInventoryObjectId: null,
    inventoryOverlayOpen: false
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

function getAnimationIdForName(previewData, objectId, animationName) {
  const object = (previewData?.objects ?? []).find(item => Number(item.id) === Number(objectId));
  if (!object) return null;
  const normalizedName = String(animationName ?? '').trim().toLowerCase();
  if (!normalizedName) return null;
  const animation = (object.animations ?? []).find(
    item => String(item.name ?? '').trim().toLowerCase() === normalizedName
  );
  return animation ? Number(animation.id) : null;
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

function getObjectRenderForUploadedFileId(previewData, objectId, uploadedFileId) {
  const numericUploadedFileId = Number(uploadedFileId);
  if (!numericUploadedFileId) return null;
  const frameIndex = Array.isArray(previewData?.images)
    ? previewData.images.findIndex(
      image => Number(image.uploaded_file_id) === numericUploadedFileId
    )
    : -1;
  if (frameIndex < 0) return null;
  return getObjectRenderForFrame(previewData, objectId, frameIndex);
}

function resolveStepTargetObjectId(step, metadata = {}) {
  const mode = String(step?.target_object_mode ?? 'static');
  if (mode === 'trigger_object') return numericOrNull(metadata?.objectId);
  if (mode === 'trigger_inventory_object') return numericOrNull(metadata?.inventoryObjectId);
  return numericOrNull(step?.target_object_id);
}

function resolveStepSceneObjectId(step, metadata = {}) {
  const mode = String(step?.scene_object_mode ?? 'static');
  if (mode === 'trigger_object') return numericOrNull(metadata?.objectId);
  if (mode === 'trigger_inventory_object') return numericOrNull(metadata?.inventoryObjectId);
  return numericOrNull(step?.scene_object_id);
}

function resolveStepAnimationId(previewData, step, resolvedObjectId) {
  if (String(step?.target_object_mode ?? 'static') === 'static') {
    return numericOrNull(step?.animation_id);
  }
  return getAnimationIdForName(previewData, resolvedObjectId, step?.animation_name);
}

function numericOrNull(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
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

function renderInventoryItems(items) {
  return (items ?? []).map(item => `
    <section class="preview-object-card ${item.isJuiceBump ? 'is-juice-bump' : ''}">
      <div class="preview-object-card__header">
        <strong>${escapeHtml(item.name)}</strong>
        <span>${item.isHeld ? 'held' : 'carried'}</span>
      </div>
    </section>
  `).join('');
}

function renderVerbMenu(menu) {
  return `
    <div
      class="scene-runtime-verb-menu__shell"
      style="left:${Number(menu.left || 0).toFixed(2)}px; top:${Number(menu.top || 0).toFixed(2)}px;"
    >
      ${(menu.items ?? []).map((item, index) => {
        return `
          <button
            class="scene-runtime-verb-tag ${item.enabled ? '' : 'is-disabled'}"
            type="button"
            data-action="select-verb"
            data-layer="${escapeHtml(menu.layer)}"
            data-object-id="${menu.objectId}"
            data-verb-id="${item.id}"
            style="--tag-x:${Number(item.offsetX || 0).toFixed(2)}px; --tag-y:${Number(item.offsetY || 0).toFixed(2)}px; --tag-delay:${index * VERB_MENU_STAGGER_MS}ms; --tag-tilt:${verbTiltDirection(item.id, index)};${item.backgroundUrl ? `--tag-background:url('${escapeHtml(item.backgroundUrl)}');` : ''}"
            ${item.enabled ? '' : 'disabled'}
          >
            <span>${escapeHtml(item.label)}</span>
          </button>
        `;
      }).join('')}
    </div>
  `;
}

function buildVerbMenuSignature(menu) {
  return JSON.stringify({
    layer: menu.layer,
    objectId: menu.objectId,
    left: roundMenuValue(menu.left),
    top: roundMenuValue(menu.top),
    items: (menu.items ?? []).map(item => ({
      id: item.id,
      enabled: Boolean(item.enabled),
      offsetX: roundMenuValue(item.offsetX),
      offsetY: roundMenuValue(item.offsetY),
      backgroundUrl: item.backgroundUrl || ''
    }))
  });
}

function roundMenuValue(value) {
  return Math.round((Number(value) || 0) * 100) / 100;
}

async function loadInventoryBackgroundMetrics(url) {
  if (!url) return null;
  if (!inventoryBackgroundMetricsCache.has(url)) {
    inventoryBackgroundMetricsCache.set(url, new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve({
        width: image.naturalWidth || 0,
        height: image.naturalHeight || 0
      });
      image.onerror = reject;
      image.src = url;
    }));
  }
  try {
    return await inventoryBackgroundMetricsCache.get(url);
  } catch {
    return null;
  }
}

function computeContainedSurfaceLayout(stageWidth, stageHeight, sourceWidth, sourceHeight) {
  const availableWidth = Math.max(0, Number(stageWidth) || 0);
  const availableHeight = Math.max(0, Number(stageHeight) || 0);
  const naturalWidth = Math.max(1, Number(sourceWidth) || 1);
  const naturalHeight = Math.max(1, Number(sourceHeight) || 1);
  if (!availableWidth || !availableHeight) {
    return {
      left: 0,
      top: 0,
      width: naturalWidth,
      height: naturalHeight,
      scale: 1
    };
  }
  const scale = Math.min(availableWidth / naturalWidth, availableHeight / naturalHeight);
  const renderedWidth = naturalWidth * scale;
  const renderedHeight = naturalHeight * scale;
  return {
    left: (availableWidth - renderedWidth) / 2,
    top: (availableHeight - renderedHeight) / 2,
    width: naturalWidth,
    height: naturalHeight,
    scale
  };
}

function renderInventoryOverlay({slots, items, motion, surface = null}) {
  const surfaceStyle = surface
    ? `left:${Number(surface.left || 0).toFixed(2)}px; top:${Number(surface.top || 0).toFixed(2)}px; width:${Number(surface.width || 0).toFixed(2)}px; height:${Number(surface.height || 0).toFixed(2)}px; transform:scale(${Number(surface.scale || 1).toFixed(6)}); transform-origin: top left;`
    : 'left:0; top:0; width:100%; height:100%;';
  return `
    <div class="scene-runtime-inventory-surface" style="${surfaceStyle}">
      ${(slots ?? []).map((slot, index) => {
        const item = items?.[index] ?? null;
        const animated = item && shouldAnimateInventoryItem(item.scene_object_id, motion);
        return `
          <button
            class="scene-runtime-inventory-slot ${item ? 'has-item' : ''} ${animated ? 'is-entering' : ''}"
            type="button"
            ${item ? `data-action="select-inventory-item" data-object-id="${item.scene_object_id}"` : 'disabled'}
            style="left:${slot.x}px; top:${slot.y}px; width:${slot.size}px; height:${slot.size}px; transform:${slot.origin === 'center' ? 'translate(-50%, -50%)' : 'none'}; --slot-delay:${index * 34}ms;"
          >
            ${item ? `<img src="${escapeHtml(item.thumbnailUrl)}" alt="${escapeHtml(item.name)}" />` : ''}
          </button>
        `;
      }).join('')}
    </div>
  `;
}

function renderHeldInventoryItem(item, motion = null) {
  return `
    <div class="scene-runtime-held-item__inner ${motion === 'attach' ? 'is-attach' : ''}">
      <img src="${escapeHtml(item.thumbnailUrl)}" alt="${escapeHtml(item.name)}" />
    </div>
  `;
}

function renderHeldInventoryGhost(item) {
  return `
    <div class="scene-runtime-held-item__inner is-ghost">
      <img src="${escapeHtml(item.thumbnailUrl)}" alt="${escapeHtml(item.name)}" />
    </div>
  `;
}

function renderInteractionPulse(pulse) {
  return `
    <div
      class="scene-runtime-feedback-pulse is-${escapeHtml(pulse.kind)}"
      style="left:${Number(pulse.x || 0).toFixed(2)}px; top:${Number(pulse.y || 0).toFixed(2)}px;"
    ></div>
  `;
}

function renderCustomCursor(display) {
  return `
    <div
      class="scene-runtime-cursor__inner"
      style="transform: translate(${-Math.max(0, Number(display.hotspotX) || 0)}px, ${-Math.max(0, Number(display.hotspotY) || 0)}px);"
    >
      <img
        class="scene-runtime-cursor__image"
        src="${escapeHtml(display.url)}"
        alt=""
        aria-hidden="true"
      />
    </div>
  `;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function actionTreeContainsAudio(steps) {
  return (steps ?? []).some(step => {
    if (!step?.type) return false;
    if (['play_audio', 'crossfade_bgm', 'play_sfx'].includes(step.type)) return true;
    if (step.type === 'if_variable') {
      return actionTreeContainsAudio(step.then_steps ?? []) || actionTreeContainsAudio(step.else_steps ?? []);
    }
    return false;
  });
}

function wait(durationSeconds) {
  const milliseconds = Math.max(1, Math.round(Number(durationSeconds || 0) * 1000));
  return waitMilliseconds(milliseconds);
}

function waitMilliseconds(milliseconds) {
  return new Promise(resolve => window.setTimeout(resolve, milliseconds));
}

function nextAnimationFrame() {
  return new Promise(resolve => window.requestAnimationFrame(() => resolve()));
}

function pointInsideRect(x, y, rect) {
  return (
    Number.isFinite(x)
    && Number.isFinite(y)
    && rect
    && x >= rect.left
    && x <= rect.right
    && y >= rect.top
    && y <= rect.bottom
  );
}

function resolveStagePulsePosition(layer, objectId, metadata = {}) {
  const preview = this.getLayerPreviewElement(layer);
  const stageRect = preview?.getStageClientRect?.();
  const objectRect = preview?.getObjectClientBounds?.(objectId);
  if (stageRect && Number.isFinite(Number(metadata.clientX)) && Number.isFinite(Number(metadata.clientY))) {
    return {
      x: Number(metadata.clientX) - stageRect.left,
      y: Number(metadata.clientY) - stageRect.top
    };
  }
  if (stageRect && objectRect) {
    return {
      x: (objectRect.left - stageRect.left) + (objectRect.width / 2),
      y: (objectRect.top - stageRect.top) + (objectRect.height / 2)
    };
  }
  if (stageRect) {
    return {
      x: stageRect.width / 2,
      y: stageRect.height / 2
    };
  }
  return null;
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

function buildInventoryInspectorItems(items, heldInventoryObjectId, motion = null) {
  return (items ?? []).map(item => ({
    ...item,
    isHeld: Number(item.scene_object_id) === Number(heldInventoryObjectId),
    isJuiceBump: shouldAnimateInventoryItem(item.scene_object_id, motion)
  }));
}

function buildInventoryItemFromSceneObject(...previewSources) {
  const objectId = Number(previewSources.pop());
  const sources = previewSources;
  for (const source of sources) {
    const object = (source?.objects ?? []).find(item => Number(item.id) === objectId);
    if (!object) continue;
    return {
      scene_object_id: objectId,
      name: object.name,
      thumbnailUrl: objectThumbnailUrl(objectId),
      isHeld: false
    };
  }
  return null;
}

function normalizeInventorySlots(slots) {
  return (slots ?? []).map(slot => ({
    x: Number(slot.x) || 0,
    y: Number(slot.y) || 0,
    size: Math.max(1, Number(slot.size) || 96),
    origin: slot.origin === 'top_left' ? 'top_left' : 'center'
  }));
}

function getInteractionMatchMode(interaction) {
  const mode = String(interaction?.trigger?.match_mode ?? 'exact');
  return ['exact', 'object_default', 'scene_default'].includes(mode) ? mode : 'exact';
}

function resolveTriggeredInteractions(interactions, tiers) {
  for (const matcher of tiers) {
    const matches = (interactions ?? []).filter(matcher);
    if (matches.length) return matches;
  }
  return [];
}

function buildObjectClickTriggerTiers(objectId) {
  return [
    interaction => (
      interaction.trigger?.type === 'object_click'
      && getInteractionMatchMode(interaction) === 'exact'
      && Number(interaction.trigger?.object_id) === Number(objectId)
    ),
    interaction => (
      interaction.trigger?.type === 'object_click'
      && getInteractionMatchMode(interaction) === 'object_default'
      && Number(interaction.trigger?.object_id) === Number(objectId)
    ),
    interaction => (
      interaction.trigger?.type === 'object_click'
      && getInteractionMatchMode(interaction) === 'scene_default'
    )
  ];
}

function buildObjectVerbTriggerTiers(objectId, verbId) {
  return [
    interaction => (
      interaction.trigger?.type === 'object_verb'
      && getInteractionMatchMode(interaction) === 'exact'
      && Number(interaction.trigger?.object_id) === Number(objectId)
      && Number(interaction.trigger?.verb_id) === Number(verbId)
    ),
    interaction => (
      interaction.trigger?.type === 'object_verb'
      && getInteractionMatchMode(interaction) === 'object_default'
      && Number(interaction.trigger?.object_id) === Number(objectId)
      && Number(interaction.trigger?.verb_id) === Number(verbId)
    ),
    interaction => (
      interaction.trigger?.type === 'object_verb'
      && getInteractionMatchMode(interaction) === 'scene_default'
      && Number(interaction.trigger?.verb_id) === Number(verbId)
    )
  ];
}

function buildInventoryUseTriggerTiers(objectId, inventoryObjectId) {
  return [
    interaction => (
      interaction.trigger?.type === 'inventory_use'
      && getInteractionMatchMode(interaction) === 'exact'
      && Number(interaction.trigger?.object_id) === Number(objectId)
      && Number(interaction.trigger?.inventory_object_id) === Number(inventoryObjectId)
    ),
    interaction => (
      interaction.trigger?.type === 'inventory_use'
      && getInteractionMatchMode(interaction) === 'object_default'
      && Number(interaction.trigger?.object_id) === Number(objectId)
    ),
    interaction => (
      interaction.trigger?.type === 'inventory_use'
      && getInteractionMatchMode(interaction) === 'scene_default'
    )
  ];
}

function buildVerbMenuItems(previewData, objectId, languageSettings) {
  const labels = previewData?.verbs ?? [];
  const showDisabled = previewData?.global_settings?.verb_menu_show_disabled !== false;
  return labels
    .filter(verb => verb.enabled !== false)
    .map(verb => ({
      id: verb.id,
      key: verb.key,
      label: resolveVerbLabel(verb, languageSettings.primaryLanguage),
      enabled: resolveTriggeredInteractions(
        previewData?.interactions ?? [],
        buildObjectVerbTriggerTiers(Number(objectId), Number(verb.id))
      ).length > 0,
      backgroundUrl: previewData?.global_settings?.verb_tag_background_relative_path
        ? globalSettingsAssetUrl('verb_tag_background')
        : ''
    }))
    .filter(verb => showDisabled || verb.enabled);
}

function resolveVerbLabel(verb, language) {
  const labels = verb.labels ?? {};
  const normalizedLanguage = String(language ?? '').trim().toLowerCase();
  const languageCandidates = buildLanguageCandidates(normalizedLanguage);
  for (const candidate of languageCandidates) {
    if (labels[candidate]) return labels[candidate];
  }
  const matchingEntry = Object.entries(labels).find(([key]) => languageCandidates.includes(String(key).trim().toLowerCase()));
  if (matchingEntry?.[1]) return matchingEntry[1];
  return labels.en
    || Object.values(labels)[0]
    || verb.label
    || verb.key;
}

function buildLanguageCandidates(language) {
  const candidates = [];
  const add = value => {
    const normalized = String(value ?? '').trim().toLowerCase();
    if (normalized && !candidates.includes(normalized)) candidates.push(normalized);
  };
  add(language);
  if (language.includes('-')) add(language.split('-')[0]);
  if (language.includes('_')) add(language.split('_')[0]);
  const aliases = {
    english: 'en',
    german: 'de',
    deutsch: 'de',
    spanish: 'es',
    french: 'fr',
    italian: 'it',
    portuguese: 'pt'
  };
  add(aliases[language]);
  return candidates;
}

function computeVerbMenuPosition(stageRect, objectRect, count) {
  return computeVerbMenuLayout(
    stageRect.width,
    stageRect.height,
    {
      x: (objectRect.left - stageRect.left) + (objectRect.width / 2),
      y: (objectRect.top - stageRect.top) + (objectRect.height / 2)
    },
    count
    );
}

function shouldAnimateInventoryItem(sceneObjectId, motion) {
  if (!motion?.objectIds?.length) return false;
  return motion.objectIds.some(id => Number(id) === Number(sceneObjectId));
}

function verbTiltDirection(id, index) {
  const numericId = Number(id);
  return ((numericId || index) % 2 === 0) ? '1deg' : '-1deg';
}

function computeVerbMenuLayout(stageWidth, stageHeight, anchorPoint, count) {
  const tagWidth = 132;
  const tagHeight = 88;
  const tagPadding = 10;
  const radius = count <= 2 ? 82 : 92;
  const minX = (tagWidth / 2) + tagPadding;
  const maxX = Math.max(minX, stageWidth - (tagWidth / 2) - tagPadding);
  const minY = (tagHeight / 2) + tagPadding;
  const maxY = Math.max(minY, stageHeight - (tagHeight / 2) - tagPadding);
  const anchorX = clampNumber(Number(anchorPoint?.x) || (stageWidth / 2), minX, maxX);
  const anchorY = clampNumber(Number(anchorPoint?.y) || (stageHeight / 2), minY, maxY);
  const centerX = stageWidth / 2;
  const centerY = stageHeight / 2;
  const dx = centerX - anchorX;
  const dy = centerY - anchorY;
  const preferredAngle = (Math.abs(dx) < 2 && Math.abs(dy) < 2)
    ? (-90 * Math.PI / 180)
    : Math.atan2(dy, dx);
  const spreadDegrees = count <= 1
    ? 0
    : count === 2
      ? 90
      : count === 3
        ? 128
        : Math.min(210, 108 + ((count - 3) * 24));
  const spreadRadians = spreadDegrees * (Math.PI / 180);
  const offsets = Array.from({length: Math.max(1, count)}, (_, index) => {
    const angle = count <= 1
      ? preferredAngle
      : preferredAngle - (spreadRadians / 2) + ((spreadRadians * index) / (count - 1));
    const targetX = anchorX + (Math.cos(angle) * radius);
    const targetY = anchorY + (Math.sin(angle) * radius);
    const clampedX = clampNumber(targetX, minX, maxX);
    const clampedY = clampNumber(targetY, minY, maxY);
    return {
      x: clampedX - anchorX,
      y: clampedY - anchorY
    };
  });
  return {anchorX, anchorY, offsets};
}

function clampNumber(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function readPreviewLocalAudioSettings() {
  try {
    const raw = window.localStorage.getItem(PREVIEW_LOCAL_AUDIO_SETTINGS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function writePreviewLocalAudioSettings(settings) {
  try {
    window.localStorage.setItem(
      PREVIEW_LOCAL_AUDIO_SETTINGS_KEY,
      JSON.stringify({
        masterVolume: clampNumber(Number(settings?.masterVolume) || 0, 0, 10),
        musicVolume: clampNumber(Number(settings?.musicVolume) || 0, 0, 10)
      })
    );
  } catch {
    // Ignore local storage failures in preview-only settings.
  }
}

const cursorImageCache = new Map();

function getCursorImageState(url) {
  if (!url) return {status: 'missing'};
  return cursorImageCache.get(url) ?? {status: 'idle'};
}

function loadCursorImage(url) {
  if (!url) return Promise.reject(new Error('Could not load cursor: empty source'));
  const existing = cursorImageCache.get(url);
  if (existing?.status === 'loaded') return Promise.resolve(existing.image);
  if (existing?.status === 'loading' && existing.promise) return existing.promise;
  const promise = new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      cursorImageCache.set(url, {status: 'loaded', image});
      resolve(image);
    };
    image.onerror = () => {
      cursorImageCache.set(url, {status: 'failed'});
      reject(new Error('Could not load cursor image'));
    };
    image.src = url;
  });
  cursorImageCache.set(url, {status: 'loading', promise});
  return promise;
}

export {PreviewCtrl};

function formatLoadingMeta(previewData) {
  if (!previewData) return '';
  const frameCount = Number(previewData.images?.length ?? 0);
  const objectCount = Number(previewData.objects?.length ?? 0);
  return `${frameCount} frame${frameCount === 1 ? '' : 's'} · ${objectCount} object${objectCount === 1 ? '' : 's'}`;
}

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
          await preloadPreviewAssets(previewData, {mode: 'initial'});
        } catch {
          invalidatePreviewDataCache(sceneId);
        }
      })
  );
}
