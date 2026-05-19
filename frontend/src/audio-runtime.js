class PreviewAudioRuntime {
  constructor() {
    this.bgmAudio = null;
    this.bgmAssetId = null;
    this.bgmBaseVolume = 0.5;
    this.sfxBaseVolume = 0.5;
    this.duckFactor = 1;
    this.activeSfx = new Set();
    this.pendingBgmRequest = null;
  }

  setVolumes({bgmVolume, sfxVolume}) {
    if (typeof bgmVolume === 'number') this.bgmBaseVolume = clamp01(bgmVolume);
    if (typeof sfxVolume === 'number') this.sfxBaseVolume = clamp01(sfxVolume);
    this.applyVolumes();
  }

  setDuckFactor(duckFactor) {
    this.duckFactor = clamp01(duckFactor);
    this.applyVolumes();
  }

  async crossfadeBgm({audioAssetId, audioUrl, volume, durationSeconds}) {
    const nextAssetId = Number(audioAssetId);
    if (!nextAssetId || !audioUrl) return;
    this.bgmBaseVolume = clamp01(volume);
    if (this.bgmAssetId === nextAssetId && this.bgmAudio) {
      this.applyVolumes();
      return;
    }

    const nextAudio = new Audio(audioUrl);
    nextAudio.loop = true;
    nextAudio.preload = 'auto';
    nextAudio.volume = 0;
    const playStarted = await nextAudio.play()
      .then(() => true)
      .catch(() => false);
    if (!playStarted) {
      this.pendingBgmRequest = {
        audioAssetId: nextAssetId,
        audioUrl,
        volume: this.bgmBaseVolume,
        durationSeconds
      };
      return;
    }
    this.pendingBgmRequest = null;

    const previousAudio = this.bgmAudio;
    const previousVolume = previousAudio?.volume ?? 0;
    this.bgmAudio = nextAudio;
    this.bgmAssetId = nextAssetId;
    await ramp(durationSeconds, progress => {
      const duckedTarget = this.bgmBaseVolume * this.duckFactor;
      nextAudio.volume = duckedTarget * progress;
      if (previousAudio) previousAudio.volume = previousVolume * (1 - progress);
    });
    if (previousAudio) {
      previousAudio.pause();
      previousAudio.src = '';
    }
    this.applyVolumes();
  }

  async resumePendingBgm() {
    if (!this.pendingBgmRequest) return;
    const request = this.pendingBgmRequest;
    this.pendingBgmRequest = null;
    await this.crossfadeBgm(request);
  }

  async playSfx({audioUrl, volume}) {
    if (!audioUrl) return;
    this.sfxBaseVolume = clamp01(volume);
    const audio = new Audio(audioUrl);
    audio.volume = this.sfxBaseVolume * this.duckFactor;
    this.activeSfx.add(audio);
    await new Promise(resolve => {
      const finish = () => {
        this.activeSfx.delete(audio);
        resolve();
      };
      audio.addEventListener('ended', finish, {once: true});
      audio.addEventListener('error', finish, {once: true});
      const playPromise = audio.play();
      if (playPromise?.catch) playPromise.catch(() => finish());
    });
  }

  applyVolumes() {
    if (this.bgmAudio) this.bgmAudio.volume = this.bgmBaseVolume * this.duckFactor;
    for (const audio of this.activeSfx) {
      audio.volume = this.sfxBaseVolume * this.duckFactor;
    }
  }

  stopAll() {
    if (this.bgmAudio) {
      this.bgmAudio.pause();
      this.bgmAudio.src = '';
    }
    this.bgmAudio = null;
    this.bgmAssetId = null;
    for (const audio of this.activeSfx) {
      audio.pause();
      audio.src = '';
    }
    this.activeSfx.clear();
    this.pendingBgmRequest = null;
  }
}

function clamp01(value) {
  return Math.max(0, Math.min(1, Number(value) || 0));
}

async function ramp(durationSeconds, onFrame) {
  const durationMs = Math.max(1, Math.round(Number(durationSeconds || 0) * 1000));
  const start = performance.now();
  while (true) {
    const progress = Math.min(1, (performance.now() - start) / durationMs);
    onFrame(progress);
    if (progress >= 1) break;
    await new Promise(resolve => window.setTimeout(resolve, 33));
  }
}

const previewAudioRuntime = new PreviewAudioRuntime();

export {previewAudioRuntime};
