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
    runtimeSnapshot: null,
    runtimeObjects: [],
    runtimeVariables: [],
    runtimeState: null,
    previewObjects: [],
    currentSubtitle: null,
    currentFade: null,
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

    async postLoad() {
      this.root = document.querySelector('[data-preview-page]');
      this.preview = this.root?.querySelector('wonky-scene-preview');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.preview, 'preview-object-click', event => this.onPreviewObjectClick(event));
      this.bind(this.preview, 'preview-error', event => this.onPreviewError(event));
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

    bind(target, type, handler) {
      if (!target) return;
      target.addEventListener(type, handler);
      this.unloadHandlers.push(() => target.removeEventListener(type, handler));
    },

    async refreshData() {
      try {
        this.scene = findScene(this.sceneId) ?? {id: this.sceneId};
        this.previewData = await fetchPreviewData(this.sceneId);
        this.prepareState();
        this.applyCarriedVariables();
        this.scheduleConnectedScenePreload();
        this.editorReady = Boolean(this.previewData);
        this.editorMissing = !this.editorReady;
      } catch {
        this.editorReady = false;
        this.editorMissing = true;
      }
    },

    prepareState() {
      this.runtimeSnapshot = createRuntimeSnapshot(this.previewData);
      this.runtimeState = cloneRuntimeState(this.runtimeSnapshot);
      this.currentSubtitle = null;
      this.refreshInspectorState();
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

    refreshInspectorState() {
      const runtimeObjects = [...(this.previewData?.objects ?? [])]
        .map(object => {
          const state = this.runtimeState?.objects?.[object.id];
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

    async configurePreview() {
      if (!this.preview || !this.previewData) return;
      await this.preview.configure({
        ...this.previewData,
        showBackground: this.showBackground
      });
      this.pushRuntimeToPreview();
      this.syncSubtitleOverlay();
      this.syncFadeOverlay();
    },

    pushRuntimeToPreview() {
      if (!this.preview) return;
      this.preview.applyRuntimeState(this.runtimeState?.objects ?? {});
    },

    async refreshView() {
      app.refresh();
      await Promise.resolve();
      this.root = document.querySelector('[data-preview-page]');
      this.preview = this.root?.querySelector('wonky-scene-preview');
      this.bind(this.root, 'click', event => this.onClick(event));
      this.bind(this.preview, 'preview-object-click', event => this.onPreviewObjectClick(event));
      this.bind(this.preview, 'preview-error', event => this.onPreviewError(event));
      await this.configurePreview();
      this.syncRuntimePanels();
    },

    syncRuntimePanels() {
      const objectsRoot = this.root?.querySelector('[data-preview-objects]');
      if (objectsRoot) objectsRoot.innerHTML = renderPreviewObjects(this.previewObjects);
      const variablesRoot = this.root?.querySelector('[data-preview-variables]');
      if (variablesRoot) variablesRoot.innerHTML = renderPreviewVariables(this.runtimeVariables);
      this.syncSubtitleOverlay();
      this.syncFadeOverlay();
    },

    syncSubtitleOverlay() {
      const subtitleRoot = this.root?.querySelector('[data-preview-subtitles]');
      if (!subtitleRoot) return;
      subtitleRoot.innerHTML = renderSubtitleOverlay(this.currentSubtitle);
    },

    syncFadeOverlay() {
      const fadeRoot = this.root?.querySelector('[data-preview-fade]');
      if (!fadeRoot) return;
      const fade = this.currentFade ?? {opacity: 0, color: '#000000'};
      fadeRoot.style.background = fade.color || '#000000';
      fadeRoot.style.opacity = String(Math.max(0, Math.min(1, Number(fade.opacity) || 0)));
    },

    syncContinuousAudioState() {
      const settings = this.getLanguageSettings();
      previewAudioRuntime.setVolumes({
        bgmVolume: volumeForChannel(settings.masterVolume, settings.musicVolume),
        sfxVolume: volumeForChannel(settings.masterVolume, settings.sfxVolume)
      });
      const duckOpacity = this.currentFade?.affectAudio ? Number(this.currentFade?.opacity) || 0 : 0;
      previewAudioRuntime.setDuckFactor(1 - Math.max(0, Math.min(1, duckOpacity)));
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
      this.refreshInspectorState();
      this.preview?.stop();
      this.pushRuntimeToPreview();
      this.syncSubtitleOverlay();
      this.syncFadeOverlay();
    },

    stopMediaPlayback() {
      this.subtitleToken += 1;
      this.audioPlaybackToken += 1;
      this.currentSubtitle = null;
      for (const audio of this.activeAudio) {
        audio.pause();
        audio.src = '';
      }
      this.activeAudio = [];
      this.activeAudioBaseVolume = 1;
      this.syncSubtitleOverlay();
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
      await this.executeMatchingInteractions(
        interaction => interaction.trigger?.type === 'scene_enter',
        {reason: 'scene_enter'}
      );
    },

    async runSceneExitActions() {
      await this.executeMatchingInteractions(
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
        await this.executeAnimationPreview(objectId, animationId);
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

    async onPreviewObjectClick(event) {
      const objectId = Number(event.detail?.objectId);
      if (!objectId) return;
      const state = this.runtimeState?.objects?.[objectId];
      if (!state?.enabled || !state?.visible) return;
      await this.executeMatchingInteractions(
        interaction => (
          interaction.trigger?.type === 'object_click'
          && Number(interaction.trigger?.object_id) === objectId
        ),
        {reason: 'object_click', objectId}
      );
    },

    onPreviewError(event) {
      const message = event.detail?.message || 'Preview could not load one or more images.';
      this.setStatus(message);
    },

    async executeAnimationPreview(objectId, animationId) {
      const version = ++this.executionVersion;
      this.setStatus('Playing animation...');
      try {
        await this.preview?.playAnimation(objectId, animationId, {mode: 'immediate'});
        if (version !== this.executionVersion) return;
        const render = getAnimationLastRender(this.previewData, objectId, animationId);
        if (render && this.runtimeState?.objects?.[objectId]) {
          this.runtimeState.objects[objectId].render = render;
          this.pushRuntimeToPreview();
        }
        this.refreshInspectorState();
      } finally {
        if (version === this.executionVersion) this.setStatus('');
      }
    },

    async executeMatchingInteractions(predicate, metadata = {}) {
      const interactions = (this.previewData?.interactions ?? []).filter(predicate);
      if (!interactions.length) return;
      const chainState = {remaining: MAX_CHAINED_INTERACTIONS};
      await this.executeInteractions(interactions, metadata, chainState);
    },

    async executeInteractions(interactions, metadata = {}, chainState = {remaining: MAX_CHAINED_INTERACTIONS}) {
      const version = this.executionVersion;
      for (const interaction of interactions) {
        if (version !== this.executionVersion) return;
        if (!interaction?.enabled) continue;
        if (chainState.remaining <= 0) {
          this.setStatus('Stopped preview actions after hitting the interaction safety limit.');
          return;
        }
        chainState.remaining -= 1;
        await this.executeActionTree(interaction.action_tree ?? [], metadata, chainState, version);
      }
    },

    async executeActionTree(steps, metadata, chainState, version) {
      for (const step of steps ?? []) {
        if (version !== this.executionVersion) return;
        await this.executeActionStep(step, metadata, chainState, version);
      }
    },

    async executeActionStep(step, metadata, chainState, version) {
      if (!step?.type || version !== this.executionVersion) return;
      if (step.type === 'play_animation') {
        const runPromise = this.preview?.playAnimation(step.target_object_id, step.animation_id, {
          mode: step.mode ?? 'queued'
        });
        if (step.wait !== 'continue') await runPromise;
        else void runPromise;
        const render = getAnimationLastRender(this.previewData, step.target_object_id, step.animation_id);
        if (render && this.runtimeState?.objects?.[step.target_object_id]) {
          this.runtimeState.objects[step.target_object_id].render = render;
          this.pushRuntimeToPreview();
        }
        return;
      }

      if (step.type === 'set_object_property') {
        const objectState = this.runtimeState?.objects?.[step.target_object_id];
        if (!objectState) return;
        if (step.property === 'visible') objectState.visible = Boolean(step.value);
        if (step.property === 'enabled') objectState.enabled = Boolean(step.value);
        if (step.property === 'label') objectState.label = String(step.value ?? '');
        this.refreshInspectorState();
        this.pushRuntimeToPreview();
        return;
      }

      if (step.type === 'set_variable') {
        const variableState = this.runtimeState?.variables?.[step.variable_id];
        if (!variableState) return;
        variableState.value = step.value;
        this.refreshInspectorState();
        await this.triggerVariableChanged(step.variable_id, chainState);
        return;
      }

      if (step.type === 'increment_variable') {
        const variableState = this.runtimeState?.variables?.[step.variable_id];
        if (!variableState) return;
        variableState.value = Number(variableState.value || 0) + Number(step.amount || 0);
        this.refreshInspectorState();
        await this.triggerVariableChanged(step.variable_id, chainState);
        return;
      }

      if (step.type === 'toggle_variable') {
        const variableState = this.runtimeState?.variables?.[step.variable_id];
        if (!variableState) return;
        variableState.value = !Boolean(variableState.value);
        this.refreshInspectorState();
        await this.triggerVariableChanged(step.variable_id, chainState);
        return;
      }

      if (step.type === 'show_subtitle') {
        const line = this.pickScriptLine(step.script_line_ids);
        if (!line) return;
        const subtitle = buildSubtitlePayload(line, this.getLanguageSettings());
        if (!subtitle) return;
        const runPromise = this.showSubtitle(subtitle, step.duration_seconds, version);
        if (step.wait !== 'continue') await runPromise;
        else void runPromise;
        return;
      }

      if (step.type === 'play_audio') {
        const line = this.pickScriptLine(step.script_line_ids);
        if (!line) return;
        const runPromise = this.playAudioForLine(line, version);
        if (step.wait !== 'continue') await runPromise;
        else void runPromise;
        return;
      }

      if (step.type === 'crossfade_bgm') {
        const asset = this.findAudioAsset(step.audio_asset_id, 'bgm');
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
        const asset = this.findAudioAsset(step.audio_asset_id, 'sfx');
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
        await this.executeActionTree(branch ?? [], metadata, chainState, version);
        return;
      }

      if (step.type === 'delay') {
        await wait(step.duration_seconds);
        return;
      }

      if (step.type === 'fade_out' || step.type === 'fade_in') {
        const runPromise = this.runFade(step, version);
        if (step.wait !== 'continue') await runPromise;
        else void runPromise;
        return;
      }

      if (step.type === 'change_scene') {
        await this.changeScene(step.scene_id);
      }
    },

    async runFade(step, version) {
      const targetOpacity = step.type === 'fade_out' ? 1 : 0;
      const color = normalizeFadeColor(step.color);
      this.currentFade = {
        color,
        opacity: Number(this.currentFade?.opacity ?? (step.type === 'fade_out' ? 0 : 1)),
        affectAudio: Boolean(step.affect_audio)
      };
      this.syncFadeOverlay();
      await animateFade(this, {
        fromOpacity: this.currentFade.opacity,
        toOpacity: targetOpacity,
        color,
        durationSeconds: step.duration_seconds,
        affectAudio: Boolean(step.affect_audio),
        version
      });
      if (version !== this.executionVersion) return;
      if (targetOpacity <= 0) this.currentFade = null;
      else this.currentFade = {color, opacity: 1, affectAudio: Boolean(step.affect_audio)};
      this.syncContinuousAudioState();
      this.syncFadeOverlay();
    },

    async changeScene(nextSceneId) {
      const targetSceneId = Number(nextSceneId);
      if (!targetSceneId) return;
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

    async triggerVariableChanged(variableId, chainState) {
      await this.executeInteractions(
        (this.previewData?.interactions ?? []).filter(interaction => (
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

    findAudioAsset(audioAssetId, expectedKind) {
      return (this.previewData?.audio_assets ?? []).find(asset => (
        Number(asset.id) === Number(audioAssetId)
        && (!expectedKind || asset.kind === expectedKind)
      )) ?? null;
    },

    pickScriptLine(lineIds) {
      const validIds = (lineIds ?? []).map(Number).filter(Boolean);
      if (!validIds.length) return null;
      const randomId = validIds[Math.floor(Math.random() * validIds.length)];
      return (this.previewData?.script_lines ?? []).find(line => Number(line.line_id) === randomId) ?? null;
    },

    async showSubtitle(subtitle, durationSeconds, version) {
      const token = ++this.subtitleToken;
      this.currentSubtitle = subtitle;
      this.syncSubtitleOverlay();
      await wait(durationSeconds);
      await waitMilliseconds(SUBTITLE_LINGER_MS);
      if (token !== this.subtitleToken || version !== this.executionVersion) return;
      this.currentSubtitle = null;
      this.syncSubtitleOverlay();
    },

    async playAudioForLine(line, version) {
      const playbackToken = ++this.audioPlaybackToken;
      this.stopActiveAudio();
      const settings = this.getLanguageSettings();
      const subtitle = buildSubtitlePayload(line, settings);
      const sequence = buildAudioSequence(line, settings);
      if (subtitle) {
        this.currentSubtitle = subtitle;
        this.syncSubtitleOverlay();
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
          this.currentSubtitle = null;
          this.syncSubtitleOverlay();
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
      audio.volume = this.currentFade?.affectAudio
        ? applyFadeGain(volume, this.currentFade?.opacity ?? 0)
        : volume;
      this.activeAudio = [audio];
      await new Promise(resolve => {
        const finish = () => {
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

function applyFadeGain(baseVolume, fadeOpacity) {
  const opacity = Math.max(0, Math.min(1, Number(fadeOpacity) || 0));
  return Math.max(0, Math.min(1, Number(baseVolume || 0) * (1 - opacity)));
}

async function animateFade(controller, {
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
    controller.currentFade = {color, opacity, affectAudio};
    previewAudioRuntime.setDuckFactor(affectAudio ? 1 - Math.max(0, Math.min(1, opacity)) : 1);
    controller.syncFadeOverlay();
    if (affectAudio) {
      const adjustedVolume = applyFadeGain(controller.activeAudioBaseVolume, opacity);
      for (const audio of controller.activeAudio) {
        audio.volume = adjustedVolume;
      }
    }
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

function renderSubtitleOverlay(subtitle) {
  if (!subtitle?.primaryText && !subtitle?.secondaryText) return '';
  return `
    <div class="preview-subtitles ${subtitle.sizeClass}">
      ${subtitle.primaryText ? `<p class="preview-subtitles__primary">${escapeHtml(subtitle.primaryText)}</p>` : ''}
      ${subtitle.secondaryText ? `<p class="preview-subtitles__secondary">${escapeHtml(subtitle.secondaryText)}</p>` : ''}
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

function wait(durationSeconds) {
  const milliseconds = Math.max(1, Math.round(Number(durationSeconds || 0) * 1000));
  return waitMilliseconds(milliseconds);
}

function waitMilliseconds(milliseconds) {
  return new Promise(resolve => window.setTimeout(resolve, milliseconds));
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
    collectConnectedSceneIdsFromSteps(step?.then_steps ?? [], targets, currentSceneId);
    collectConnectedSceneIdsFromSteps(step?.else_steps ?? [], targets, currentSceneId);
  }
}

async function preloadConnectedScenes(sceneIds) {
  await Promise.all(
    [...new Set(sceneIds)]
      .slice(0, MAX_PRELOADED_CONNECTED_SCENES)
      .map(async sceneId => {
        const previewData = await fetchPreviewData(sceneId);
        await preloadPreviewAssets(previewData);
      })
  );
}
